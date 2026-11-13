/**
 * agent_pov.js — first-person perception for a character agent.
 *
 * The board knows everything (every position, every health bar). An agent must only know what
 * its own character could perceive. This module turns the board's god's-eye snapshot into one
 * character's point of view, and turns that character's egocentric intentions back into world
 * commands for the CharacterController.
 *
 *   perceive(snapshot, opts)              → what this character sees / senses / hears (no coordinates)
 *   toWorldAction(action, params, view)   → {action, params} in world space, or null if not possible
 *
 * Conventions (match character_controller.js): yaw 0 faces +z; forward = (sin yaw, cos yaw);
 * a character's right = (-cos yaw, sin yaw). Bearings are degrees, 0 = straight ahead,
 * positive = to the character's right, negative = left, ±180 = directly behind.
 */

export const POV_DEFAULTS = {
  fovDeg: 120,          // vision cone, total width
  viewRange: 14,        // metres it can see within the cone
  senseRadius: 2.2,     // within this it senses someone even behind it (footsteps, breathing)
  maxStep: 6,           // longest single egocentric move it may ask for, metres
};

const DEG = 180 / Math.PI;

export function wrapDeg(d) {
  let x = ((d + 180) % 360 + 360) % 360 - 180;
  if (x === -180) x = 180;
  return x;
}

function xz(p) {
  if (!p) return null;
  if (Array.isArray(p)) return { x: Number(p[0]) || 0, z: Number(p[1]) || 0 };
  if (typeof p === 'object') return { x: Number(p.x) || 0, z: Number(p.z) || 0 };
  return null;
}

/** Bearing (deg, +right) of a world point from an observer at `from` facing `yaw` (radians). */
export function bearingTo(from, yaw, to) {
  const dx = to.x - from.x;
  const dz = to.z - from.z;
  const worldAngle = Math.atan2(dx, dz);           // same convention as controller yaw
  return wrapDeg((yaw - worldAngle) * DEG);        // facing minus target angle → + is right
}

export function directionWord(bearing) {
  const b = Math.abs(bearing);
  const side = bearing >= 0 ? 'right' : 'left';
  if (b <= 15) return 'straight ahead';
  if (b <= 60) return `ahead-${side}`;
  if (b <= 120) return `to your ${side}`;
  if (b <= 165) return `behind-${side}`;
  return 'directly behind you';
}

export function distanceWord(d) {
  if (d < 1.5) return 'within arm\'s reach';
  if (d < 4) return 'close';
  if (d < 9) return 'a short distance away';
  return 'far off';
}

export function conditionWord(health) {
  const h = Number(health);
  if (!Number.isFinite(h)) return 'unknown';
  if (h <= 0) return 'down';
  if (h < 35) return 'badly hurt';
  if (h < 75) return 'hurt';
  return 'unhurt';
}

/**
 * Build one character's point of view.
 * @param {object} snapshot  board.getSnapshot(id): {self:{id,pos,health,state,facing?}, others:[{id,name,pos,state,health}], world, chat}
 * @param {object} [opts]    {facing (radians, overrides snapshot), fovDeg, viewRange, senseRadius, lineOfSight(fromId,toId)->bool}
 * @returns {{view: object, memory: object}}  `view` goes to the brain; `memory` stays in the browser (has coordinates).
 */
export function perceive(snapshot, opts = {}) {
  const o = { ...POV_DEFAULTS, ...opts };
  const self = (snapshot && snapshot.self) || {};
  const me = xz(self.pos || self.position) || { x: 0, z: 0 };
  const yaw = Number.isFinite(o.facing) ? o.facing : (Number(self.facing) || 0);
  const half = o.fovDeg / 2;

  const seen = [];
  const memory = { self: { id: self.id, pos: me, yaw }, visible: {} };

  for (const other of (snapshot && snapshot.others) || []) {
    const p = xz(other.pos || other.position);
    if (!p || !other.id) continue;
    const dist = Math.hypot(p.x - me.x, p.z - me.z);
    const bearing = bearingTo(me, yaw, p);
    const inCone = Math.abs(bearing) <= half && dist <= o.viewRange;
    const sensed = dist <= o.senseRadius;
    if (!inCone && !sensed) continue;
    if (inCone && typeof o.lineOfSight === 'function' && o.lineOfSight(self.id, other.id) === false && !sensed) continue;

    const entry = {
      id: String(other.id),
      name: String(other.name || other.id),
      distance_m: Math.round(dist * 2) / 2,           // nearest half-metre, not exact
      bearing_deg: Math.round(bearing / 5) * 5,        // nearest 5°, not exact
      where: `${directionWord(bearing)}, ${distanceWord(dist)}`,
    };
    if (inCone) {
      entry.doing = String(other.state || 'idle');
      entry.condition = conditionWord(other.health);
    } else {
      entry.sensed_only = true;   // felt nearby but not seen: no detail about what they are doing
    }
    seen.push(entry);
    memory.visible[entry.id] = { pos: p, name: entry.name, inCone };
  }
  seen.sort((a, b) => a.distance_m - b.distance_m);

  const view = {
    you: {
      health: Number(self.health ?? 100),
      condition: conditionWord(self.health ?? 100),
      doing: String(self.state || 'idle'),
    },
    you_see: seen.filter((s) => !s.sensed_only),
    you_sense_nearby: seen.filter((s) => s.sensed_only).map(({ id, name, where }) => ({ id, name, where })),
    note: seen.length ? undefined : 'Nobody is in sight.',
    world: {
      time_of_day: snapshot && snapshot.world ? snapshot.world.time_of_day : undefined,
      events: snapshot && snapshot.world && Array.isArray(snapshot.world.events) ? snapshot.world.events.slice(-5) : [],
    },
    phone: Array.isArray(snapshot && snapshot.chat) ? snapshot.chat.slice(-8) : [],
  };
  if (!view.note) delete view.note;
  return { view, memory };
}

function resolveOther(ref, memory) {
  if (!ref) return null;
  const key = String(ref);
  if (memory.visible[key]) return { id: key, ...memory.visible[key] };
  const low = key.toLowerCase();
  for (const [id, v] of Object.entries(memory.visible)) {
    if (String(v.name).toLowerCase() === low) return { id, ...v };
  }
  return null;  // not perceived right now → cannot target it
}

function clampStep(m, max) {
  const n = Number(m);
  if (!Number.isFinite(n) || n <= 0) return 2;
  return Math.min(n, max);
}

/**
 * Turn an egocentric intention into a world-space controller command.
 * Accepted params (anything else is ignored; world coordinates from the agent are refused):
 *   move: {toward: id|name} | {away_from: id|name} | {direction: forward|back|left|right, distance_m}
 *   turn: {toward: id|name} | {degrees: +right/-left}
 *   attack_light / attack_heavy: {at: id|name}  (turns to face them first; only if they are in sight)
 *   idle, block, dodge {side: left|right}, jump: passed through
 * Returns {action, params} or null (agent asked for something its character cannot do from here).
 */
export function toWorldAction(action, params, memory, opts = {}) {
  const o = { ...POV_DEFAULTS, ...opts };
  const a = String(action || '').toLowerCase();
  const p = (params && typeof params === 'object') ? params : {};
  const me = memory.self.pos;
  const yaw = memory.self.yaw;
  const fwd = { x: Math.sin(yaw), z: Math.cos(yaw) };
  const right = { x: -Math.cos(yaw), z: Math.sin(yaw) };

  if (a === 'move' || a === 'walk' || a === 'run') {
    if (p.toward || p.away_from) {
      const t = resolveOther(p.toward || p.away_from, memory);
      if (!t) return null;
      const dx = t.pos.x - me.x;
      const dz = t.pos.z - me.z;
      const len = Math.hypot(dx, dz) || 1;
      if (p.toward) {
        const stop = Math.max(0, len - 1.0);                      // stop about an arm's length short
        const step = Math.min(stop, clampStep(p.distance_m ?? stop, o.maxStep));
        return { action: 'move', params: { target: { x: me.x + (dx / len) * step, z: me.z + (dz / len) * step } } };
      }
      const step = clampStep(p.distance_m, o.maxStep);
      return { action: 'move', params: { target: { x: me.x - (dx / len) * step, z: me.z - (dz / len) * step } } };
    }
    if (!p.direction && (p.target || p.look_at || 'x' in p || 'z' in p)) return null;  // world coords: refused
    const dir = String(p.direction || 'forward').toLowerCase();
    const v = dir === 'back' || dir === 'backward' ? { x: -fwd.x, z: -fwd.z }
      : dir === 'left' ? { x: -right.x, z: -right.z }
      : dir === 'right' ? right
      : dir === 'forward' || dir === 'ahead' ? fwd
      : null;
    if (!v) return null;
    const step = clampStep(p.distance_m, o.maxStep);
    return { action: 'move', params: { target: { x: me.x + v.x * step, z: me.z + v.z * step } } };
  }

  if (a === 'turn') {
    if (p.toward) {
      const t = resolveOther(p.toward, memory);
      if (!t) return null;
      return { action: 'turn', params: { look_at: { x: t.pos.x, z: t.pos.z } } };
    }
    const deg = Number(p.degrees);
    if (!Number.isFinite(deg)) return null;
    // +degrees = turn to the character's right = decrease yaw (see bearing convention)
    return { action: 'turn', params: { yaw: yaw - (Math.max(-180, Math.min(180, deg)) / DEG) } };
  }

  if (a === 'attack_light' || a === 'attack_heavy') {
    if (p.at) {
      const t = resolveOther(p.at, memory);
      if (!t || !t.inCone) return null;                       // can't strike what you can't see
      return { action: a, params: { look_at: { x: t.pos.x, z: t.pos.z } } };
    }
    return { action: a, params: {} };
  }

  if (a === 'dodge') return { action: 'dodge', params: p.side === 'left' ? { side: 'left' } : { side: 'right' } };
  if (a === 'idle' || a === 'block' || a === 'jump') return { action: a, params: {} };
  return null;   // hit_react / ko are things that happen TO a character, not choices
}
