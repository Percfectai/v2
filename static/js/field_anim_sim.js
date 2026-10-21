/**
 * Field Animate / Sim controls
 * Injects an Animate panel and wires CharacterController.command() for
 * pilot / last-clicked / Voltage (or first) targets.
 * Depends on window.__AGENT_FIELD__ (agents + pilot APIs).
 */
(function (global) {
  'use strict';

  var animTargetId = null;
  var wired = false;
  var STYLE_ID = 'field-anim-sim-css';
  var PANEL_ID = 'anim-panel';

  var CSS = [
    'button.btn.hot{border-color:rgba(255,92,122,0.45);color:var(--hot,#ff5c7a);background:rgba(255,92,122,0.12)}',
    '.anim-panel{margin:0.35rem 0 0.55rem;padding:0.5rem 0.45rem 0.45rem;border-radius:12px;',
    'border:1px solid rgba(0,255,136,0.22);background:rgba(0,0,0,0.35)}',
    '.anim-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:0.35rem;margin-bottom:0.35rem}',
    '.anim-title{font-family:var(--mono,ui-monospace,monospace);font-size:0.62rem;letter-spacing:0.08em;',
    'color:var(--accent,#00ff88);font-weight:700;text-transform:uppercase}',
    '.anim-target{font-size:0.68rem;color:var(--muted,#8fb89a);font-weight:700;max-width:55%;',
    'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.anim-row{margin:0;gap:0.28rem}.anim-row .btn{font-size:0.68rem;padding:0.32rem 0.5rem}',
    '.anim-hint{margin:0.4rem 0 0;font-size:0.62rem;color:var(--muted,#8fb89a);',
    'font-family:var(--mono,ui-monospace,monospace);line-height:1.4}',
    '.anim-all{display:inline-flex;align-items:center;gap:0.28rem;font-size:0.62rem;',
    'color:var(--muted,#8fb89a);font-family:var(--mono,ui-monospace,monospace);cursor:pointer;user-select:none}',
    '.anim-all input{accent-color:var(--accent,#00ff88)}',
  ].join('');

  function ensureCss() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function ensurePanel() {
    if (document.getElementById(PANEL_ID)) return document.getElementById(PANEL_ID);
    var roster = document.querySelector('.roster');
    if (!roster) return null;
    var hop = document.getElementById('btn-hop-all');
    var anchorRow = hop && hop.closest('.row');
    var panel = document.createElement('div');
    panel.className = 'anim-panel';
    panel.id = PANEL_ID;
    panel.setAttribute('aria-label', 'Simulate animations');
    panel.innerHTML =
      '<div class="anim-head">' +
      '<span class="anim-title">Animate</span>' +
      '<span class="anim-target" id="anim-target">Target: —</span>' +
      '<label class="anim-all" title="Fire on every body"><input type="checkbox" id="anim-all" /> All</label>' +
      '</div>' +
      '<div class="row anim-row" id="anim-btns">' +
      '<button type="button" class="btn" data-anim="idle" title="Idle">Idle</button>' +
      '<button type="button" class="btn" data-anim="jump" title="Jump · J">Jump</button>' +
      '<button type="button" class="btn" data-anim="attack_light" title="Punch · 1">Punch</button>' +
      '<button type="button" class="btn" data-anim="attack_heavy" title="Heavy · 2">Heavy</button>' +
      '<button type="button" class="btn" data-anim="block" title="Block · B">Block</button>' +
      '<button type="button" class="btn" data-anim="dodge" title="Dodge · F">Dodge</button>' +
      '<button type="button" class="btn" data-anim="hit_react" title="Hit react">Hit</button>' +
      '<button type="button" class="btn hot" data-anim="ko" title="KO">KO</button>' +
      '<button type="button" class="btn" data-anim="reset" title="Reset after KO">Reset</button>' +
      '</div>' +
      '<p class="anim-hint">Pilot or last-clicked crew → buttons fire CharacterController. POV keys: J 1 2 B F. Clips if baked; else procedural.</p>';
    if (anchorRow && anchorRow.parentNode) {
      if (anchorRow.nextSibling) anchorRow.parentNode.insertBefore(panel, anchorRow.nextSibling);
      else anchorRow.parentNode.appendChild(panel);
    } else {
      var list = document.getElementById('crew-list');
      if (list && list.parentNode) list.parentNode.insertBefore(panel, list);
      else roster.appendChild(panel);
    }
    return panel;
  }

  function patchControlsHint() {
    var el = document.querySelector('.controls-hint');
    if (!el) return;
    var t = el.textContent || '';
    if (/Animate POV|J jump|1 punch/i.test(t)) return;
    el.textContent = t.replace(/\s*$/, '') +
      ' · Animate POV: J jump · 1 punch · 2 heavy · B block · F dodge';
  }

  function getAgents(af) {
    if (af && Array.isArray(af._agents)) return af._agents;
    return [];
  }

  function getJumpVel(af) {
    try {
      var m = af && af.cfg && af.cfg.movement;
      if (m && m.jump_velocity != null) return Number(m.jump_velocity) || 5.2;
    } catch (_) { /* ignore */ }
    return 5.2;
  }

  function getViewMode(af) {
    try {
      if (typeof af.getViewMode === 'function') return af.getViewMode();
    } catch (_) { /* ignore */ }
    return 'overview';
  }

  function getPilotId(af) {
    if (af && af.__pilotId != null) return af.__pilotId;
    return null;
  }

  function typingInUi(el) {
    if (!el) return false;
    var tag = (el.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    if (el.isContentEditable) return true;
    if (el.closest && el.closest('#wgc-root, .wgc-root')) return true;
    return false;
  }

  function defaultAnimTargetId(agents) {
    var v = agents.find(function (a) {
      var id = String((a.meta && a.meta.id) || '').toLowerCase();
      var label = String((a.meta && a.meta.label) || '').toLowerCase();
      return id === 'voltage' || label === 'voltage';
    });
    return ((v || agents[0]) && (v || agents[0]).meta && (v || agents[0]).meta.id) || null;
  }

  function findAgent(agents, seatOrLabel) {
    var key = String(seatOrLabel || '').trim().toLowerCase();
    if (!key) return null;
    return agents.find(function (a) {
      var id = String((a.meta && a.meta.id) || '').toLowerCase();
      var label = String((a.meta && a.meta.label) || '').toLowerCase();
      return id === key || label === key || label.replace(/\s+/g, '') === key;
    }) || null;
  }

  function getAnimTargetAgent(af) {
    var agents = getAgents(af);
    var viewMode = getViewMode(af);
    var pilotId = getPilotId(af);
    if (viewMode === 'pov' && pilotId) {
      var p = agents.find(function (x) { return x.meta && x.meta.id === pilotId; });
      if (p) return p;
    }
    if (animTargetId) {
      var t = agents.find(function (x) { return x.meta && x.meta.id === animTargetId; });
      if (t) return t;
    }
    var def = defaultAnimTargetId(agents);
    return def
      ? (agents.find(function (x) { return x.meta && x.meta.id === def; }) || agents[0] || null)
      : (agents[0] || null);
  }

  function updateAnimTargetUi(af) {
    var el = document.getElementById('anim-target');
    if (!el) return;
    var a = getAnimTargetAgent(af);
    var pilotId = getPilotId(af);
    var mode = (getViewMode(af) === 'pov' && a && a.meta && a.meta.id === pilotId) ? ' · pilot' : '';
    el.textContent = a ? ('Target: ' + a.meta.label + mode) : 'Target: —';
  }

  function isAgentPiloted(af, agent) {
    return getViewMode(af) === 'pov' && agent && agent.meta && agent.meta.id === getPilotId(af);
  }

  function resetAgentController(controller) {
    if (!controller) return;
    controller.alive = true;
    controller.health = controller.maxHealth;
    controller.busyUntil = 0;
    controller.invulnUntil = 0;
    controller.blocking = false;
    controller._attackHitWindow = null;
    controller._knock = null;
    controller._dodgeVel = null;
    try { controller.command('idle'); } catch (_) { /* ignore */ }
  }

  function scheduleWanderResume(af, agent, minMs) {
    if (!agent || !agent.brain || isAgentPiloted(af, agent)) return;
    var now = performance.now();
    var busyUntil = Number(agent.controller && agent.controller.busyUntil) || now;
    var resumeAt = Math.max(now + (minMs || 3000), busyUntil + 250);
    agent.brain.nextAt = resumeAt;
    agent.brain.hopAt = Math.max(agent.brain.hopAt || 0, resumeAt + 500);
  }

  function playAnimOnAgent(af, agent, action, params) {
    if (!agent || !agent.controller) return { ok: false, error: 'no agent' };
    params = params || {};
    var act = String(action || '').toLowerCase().trim();
    var now = performance.now();
    var jumpVel = getJumpVel(af);

    if (agent.brain) {
      if (isAgentPiloted(af, agent)) {
        agent.brain.nextAt = now + 999999;
      } else {
        agent.brain.nextAt = now + 3000;
        agent.brain.hopAt = now + 3500;
        if (act !== 'move') agent.brain.target = null;
      }
    }

    var res;
    if (act === 'reset' || act === 'revive') {
      resetAgentController(agent.controller);
      res = { ok: true, action: 'reset' };
      if (!isAgentPiloted(af, agent)) scheduleWanderResume(af, agent, 800);
    } else if (act === 'block') {
      res = agent.controller.command('block', { on: params.on !== false });
      if (params.on !== false) {
        setTimeout(function () {
          if (agent.controller && agent.controller.state === 'block') {
            agent.controller.command('block', { on: false });
          }
          scheduleWanderResume(af, agent, 400);
        }, Number(params.hold_ms) || 1100);
      }
    } else {
      var p = {};
      for (var k in params) if (Object.prototype.hasOwnProperty.call(params, k)) p[k] = params[k];
      if (act === 'jump' && p.height == null) p.height = jumpVel;
      res = agent.controller.command(act, p);
      if (['attack_light', 'attack_heavy', 'dodge', 'hit_react', 'jump', 'idle', 'ko'].indexOf(act) >= 0) {
        scheduleWanderResume(af, agent, act === 'idle' ? 600 : 3000);
      }
    }

    var hud = document.getElementById('hud-state');
    if (hud && agent.meta) hud.textContent = agent.meta.label + ': ' + act;
    return res || { ok: false, error: 'failed' };
  }

  function playAnim(af, seatOrLabel, action, params) {
    var agents = getAgents(af);
    var agent = seatOrLabel ? findAgent(agents, seatOrLabel) : null;
    if (!agent) agent = getAnimTargetAgent(af);
    if (!agent) return { ok: false, error: 'no target' };
    animTargetId = agent.meta.id;
    updateAnimTargetUi(af);
    return playAnimOnAgent(af, agent, action, params || {});
  }

  function wire(af) {
    if (wired || af.__fieldAnimSimWired) return;
    if (typeof af.playAnim === 'function' && document.getElementById('anim-btns')) {
      af.__fieldAnimSimWired = true;
      wired = true;
      console.info('[field-anim-sim] skip — playAnim already present');
      return;
    }
    wired = true;
    af.__fieldAnimSimWired = true;
    ensureCss();
    ensurePanel();
    patchControlsHint();

    var agents = getAgents(af);
    if (agents.length && !animTargetId) animTargetId = defaultAnimTargetId(agents);
    updateAnimTargetUi(af);

    if (typeof af.enterPov === 'function') {
      var origPov = af.enterPov.bind(af);
      af.enterPov = function (id) {
        animTargetId = id;
        af.__pilotId = id;
        var r = origPov(id);
        updateAnimTargetUi(af);
        return r;
      };
    }
    if (typeof af.setPilot === 'function') {
      var origSet = af.setPilot.bind(af);
      af.setPilot = function (id) {
        animTargetId = id;
        af.__pilotId = id;
        var r = origSet(id);
        updateAnimTargetUi(af);
        return r;
      };
    }
    if (typeof af.enterOverview === 'function') {
      var origOv = af.enterOverview.bind(af);
      af.enterOverview = function () {
        af.__pilotId = null;
        var r = origOv();
        updateAnimTargetUi(af);
        return r;
      };
    }

    af.playAnim = function (seatOrLabel, action, params) {
      return playAnim(af, seatOrLabel, action, params);
    };
    af.getAnimTarget = function () {
      var a = getAnimTargetAgent(af);
      return (a && a.meta && a.meta.id) || null;
    };

    var btns = document.getElementById('anim-btns');
    if (btns) {
      btns.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest && e.target.closest('[data-anim]');
        if (!btn) return;
        var anim = btn.getAttribute('data-anim');
        var all = document.getElementById('anim-all');
        var jumpVel = getJumpVel(af);
        if (all && all.checked) {
          getAgents(af).forEach(function (a) {
            playAnimOnAgent(af, a, anim, anim === 'jump' ? { height: jumpVel } : {});
          });
          return;
        }
        playAnim(af, null, anim);
      });
    }

    global.addEventListener('keydown', function (e) {
      if (typingInUi(e.target || document.activeElement)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (getViewMode(af) !== 'pov') return;
      var map = {
        j: 'jump',
        '1': 'attack_light',
        '2': 'attack_heavy',
        b: 'block',
        f: 'dodge',
      };
      var key = String(e.key || '').toLowerCase();
      var anim = map[key];
      if (!anim) return;
      e.preventDefault();
      playAnim(af, null, anim);
    });

    setInterval(function () {
      if (!animTargetId && getAgents(af).length) {
        animTargetId = defaultAnimTargetId(getAgents(af));
      }
      updateAnimTargetUi(af);
    }, 2000);

    console.info('[field-anim-sim] wired · Animate panel + playAnim / getAnimTarget on __AGENT_FIELD__');
  }

  function tryWire() {
    var af = global.__AGENT_FIELD__;
    if (!af || !Array.isArray(af._agents)) return false;
    if (af._agents.length === 0 && !af.cfg) return false;
    wire(af);
    return true;
  }

  function boot() {
    ensureCss();
    if (tryWire()) return;
    var n = 0;
    var t = setInterval(function () {
      n += 1;
      if (tryWire() || n > 200) clearInterval(t);
    }, 100);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(typeof window !== 'undefined' ? window : globalThis);
