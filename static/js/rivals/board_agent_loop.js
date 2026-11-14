/**
 * board_agent_loop.js — glue between the Three.js board (Gemini) and the agent brain (server).
 *
 * The board owns rendering. This file owns three things:
 *   1. loadRoster()      — which of the user's 3D characters can go on the board
 *   2. startAgentLoop()  — the paced tick: snapshot → /api/3d/agent/think → apply + say
 *   3. chat listener     — one place that hears every line spoken on the board
 *
 * Board contract used (window.board):
 *   addCharacter({id, name, riggedUrl, animatedUrls, spawn}) -> Promise<controller|null>
 *   getSnapshot(id) -> object|null     apply(id, action, params) -> boolean
 *   say(id, text) -> boolean           aiPaused -> boolean ("Break Character")
 *   events: 'rivals:board-say' {id, name, text}, 'rivals:break-character' {paused}
 *
 * Server contract used:
 *   GET  /api/3d/characters                 -> {characters: [{id, name, glb_url, extra?}]}
 *   GET  /api/3d/agent/persona/<id>         -> 200 if an agent is set up, 404 if not
 *   POST /api/3d/agent/think {character_id, world_state}
 *        -> {say, actions: [{action, params}], throttled?, disabled?, error?}
 *
 * No framework, no globals except the optional window.RivalsAgentLoop convenience at the bottom.
 */

import { perceive, toWorldAction } from './agent_pov.js';

const THINK_URL = '/api/3d/agent/think';
const ROSTER_URL = '/api/3d/characters';
const PERSONA_URL = '/api/3d/agent/persona/';

const DEFAULTS = {
  intervalMs: 6000,        // one agent thinks per tick (round-robin) — free-tier pace
  backoffMs: 20000,        // wait this long after a throttle / server error
  maxActionsPerTurn: 2,    // never let one reply queue a long chain of moves
  fetchTimeoutMs: 12000,
};

async function fetchJson(url, opts = {}, fetchImpl = fetch, timeoutMs = DEFAULTS.fetchTimeoutMs) {
  const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  try {
    const res = await fetchImpl(url, { credentials: 'same-origin', ...opts, signal: ctrl ? ctrl.signal : undefined });
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON body */ }
    return { status: res.status, ok: res.ok, body };
  } catch (err) {
    return { status: 0, ok: false, body: null, error: String(err && err.message || err) };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * The user's 3D characters, each marked with whether an agent is set up.
 * Returns [{id, name, riggedUrl, animatedUrls, hasAgent}].
 */
export async function loadRoster({ fetchImpl = fetch } = {}) {
  const r = await fetchJson(ROSTER_URL, {}, fetchImpl);
  if (!r.ok || !r.body || !Array.isArray(r.body.characters)) {
    return { ok: false, status: r.status, characters: [] };
  }
  const characters = [];
  for (const c of r.body.characters) {
    if (!c || !c.id || !c.glb_url) continue;
    const extra = (c.extra && typeof c.extra === 'object') ? c.extra : {};
    const p = await fetchJson(PERSONA_URL + encodeURIComponent(c.id), {}, fetchImpl);
    characters.push({
      id: String(c.id),
      name: (p.ok && p.body && p.body.fields && p.body.fields.display_name) || c.name || 'Character',
      riggedUrl: extra.rigged_url || c.glb_url,
      animatedUrls: Array.isArray(extra.animated_urls) ? extra.animated_urls : [],
      hasAgent: p.status === 200,
    });
  }
  return { ok: true, status: 200, characters };
}

/** Put roster characters on the board, spread along a line. Returns the ids that loaded. */
export async function spawnRoster(board, characters, { spacing = 3.2 } = {}) {
  const placed = [];
  const n = characters.length;
  for (let i = 0; i < n; i++) {
    const c = characters[i];
    const x = (i - (n - 1) / 2) * spacing;
    const ctl = await board.addCharacter({
      id: c.id, name: c.name, riggedUrl: c.riggedUrl, animatedUrls: c.animatedUrls, spawn: [x, 0],
    });
    if (ctl) placed.push(c.id);
  }
  return placed;
}

/** Which way the character faces (radians). Snapshot first, then the live controller, then the mesh. */
export function facingOf(board, id, snapshot) {
  const s = snapshot && snapshot.self;
  if (s && Number.isFinite(Number(s.facing))) return Number(s.facing);
  try {
    const entry = board.characters && board.characters.get && board.characters.get(id);
    const ctl = entry && entry.controller;
    if (ctl && typeof ctl.getFacing === 'function') return Number(ctl.getFacing()) || 0;
    if (ctl && typeof ctl.getState === 'function') {
      const st = ctl.getState();
      if (st && Number.isFinite(Number(st.facing))) return Number(st.facing);
    }
    const root = (ctl && ctl.root) || (entry && entry.root);
    if (root && root.rotation) return Number(root.rotation.y) || 0;
  } catch (_) { /* fall through */ }
  return 0;
}

/**
 * Start the paced agent loop. One character thinks per tick, in turn.
 * Returns { stop(), tickOnce(), state } — tickOnce() runs a single turn (used by tests and a "step" button).
 */
export function startAgentLoop(board, characterIds, options = {}) {
  const opt = { ...DEFAULTS, ...options };
  const fetchImpl = opt.fetchImpl || fetch;
  const log = opt.onLog || (() => {});
  const ids = characterIds.slice();
  const state = { running: true, index: 0, inFlight: false, pausedUntil: 0, disabled: false, turns: 0, removed: [] };
  let timer = null;

  function shouldSkip(now) {
    if (!state.running || state.disabled || state.inFlight) return true;
    if (board.aiPaused) return true;                                   // "Break Character"
    if (typeof document !== 'undefined' && document.hidden) return true; // tab not visible: spend nothing
    if (now < state.pausedUntil) return true;
    return ids.length === 0;
  }

  async function tickOnce(now = Date.now()) {
    if (shouldSkip(now)) return { skipped: true };
    const id = ids[state.index % ids.length];
    state.index = (state.index + 1) % Math.max(1, ids.length);
    const snapshot = board.getSnapshot(id);
    if (!snapshot) return { skipped: true, id };

    // First-person only: the brain gets what THIS character perceives, never the god's-eye snapshot.
    const { view, memory } = perceive(snapshot, {
      ...opt.pov,
      facing: facingOf(board, id, snapshot),
      lineOfSight: typeof board.lineOfSight === 'function' ? board.lineOfSight.bind(board) : undefined,
    });
    // Shoulder JPEG stays out of the text view until the brain splits it into an image part.
    if (typeof snapshot.vision_base64 === 'string' && snapshot.vision_base64.startsWith('data:image/')) {
      view.vision_base64 = snapshot.vision_base64;
    }

    state.inFlight = true;
    let r;
    try {
      r = await fetchJson(THINK_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_id: id, world_state: view }),
      }, fetchImpl, opt.fetchTimeoutMs);
    } finally {
      state.inFlight = false;
    }
    const body = r.body || {};

    if (r.status === 401) { state.disabled = true; log('stopped: not logged in'); return { id, stopped: 'login' }; }
    if (r.status === 503 || body.disabled) { state.disabled = true; log('stopped: brain not configured'); return { id, stopped: 'disabled' }; }
    if (r.status === 404) {                      // this character has no agent — drop it, keep the rest
      const at = ids.indexOf(id);
      if (at >= 0) ids.splice(at, 1);
      state.removed.push(id);
      state.index = 0;
      log(`${id}: no agent set up, left as a puppet`);
      return { id, removed: true };
    }
    if (!r.ok || body.throttled || body.error) { // rate limit, timeout, model error: idle and wait
      state.pausedUntil = Date.now() + opt.backoffMs;
      log(`${id}: backing off (${body.error || (body.throttled ? 'throttled' : 'http ' + r.status)})`);
      return { id, backoff: true };
    }
    if (board.aiPaused) return { id, dropped: true }; // user broke character while we were waiting

    const actions = Array.isArray(body.actions) ? body.actions.slice(0, opt.maxActionsPerTurn) : [];
    let applied = 0;
    let refused = 0;
    for (const a of actions) {
      if (!a || typeof a.action !== 'string') continue;
      const w = toWorldAction(a.action, a.params || {}, memory, opt.pov);
      if (!w) { refused++; continue; }            // e.g. "move toward" someone it cannot see
      if (board.apply(id, w.action, w.params)) applied++;
    }
    if (refused) log(`${id}: ${refused} move(s) refused — not possible from its point of view`);
    const said = typeof body.say === 'string' && body.say.trim() ? board.say(id, body.say.trim()) !== false : false;
    state.turns++;
    return { id, applied, said };
  }

  if (opt.autoStart !== false && typeof setInterval !== 'undefined') {
    timer = setInterval(() => { tickOnce().catch((e) => log('tick error: ' + e)); }, opt.intervalMs);
  }

  return {
    state,
    tickOnce,
    stop() { state.running = false; if (timer) clearInterval(timer); },
  };
}

/**
 * Hear every line spoken on the board. Returns an unsubscribe function.
 * The board dispatches 'rivals:board-say' with {id, name, text}.
 */
export function onBoardSay(handler, target = (typeof window !== 'undefined' ? window : null)) {
  if (!target) return () => {};
  const fn = (e) => {
    const d = (e && e.detail) || {};
    const id = d.id || d.character_id;
    if (id && d.text) handler({ id: String(id), name: d.name || String(id), text: String(d.text) });
  };
  target.addEventListener('rivals:board-say', fn);
  return () => target.removeEventListener('rivals:board-say', fn);
}

/** One call for the board page: load roster → spawn → start the loop for characters that have agents. */
export async function bootBoard(board, options = {}) {
  const roster = await loadRoster(options);
  if (!roster.ok) return { ok: false, status: roster.status, placed: [], loop: null };
  const placed = await spawnRoster(board, roster.characters, options);
  const withAgents = roster.characters.filter((c) => c.hasAgent && placed.includes(c.id)).map((c) => c.id);
  const loop = withAgents.length ? startAgentLoop(board, withAgents, options) : null;
  return { ok: true, placed, withAgents, loop };
}

if (typeof window !== 'undefined') {
  window.RivalsAgentLoop = { loadRoster, spawnRoster, startAgentLoop, onBoardSay, bootBoard };
}
