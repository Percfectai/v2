/**
 * Drive Field 3D bodies when world-chat agents reply.
 * Listens for CustomEvent 'percfect-agent-body' and window.__AGENT_FIELD__.drive.
 * Loaded by character_controller side-boot on /motion-lab/agent-field.html
 */
(function (global) {
  'use strict';
  if (global.__PERCFECT_FIELD_BODY_DRIVE__) return;
  global.__PERCFECT_FIELD_BODY_DRIVE__ = true;

  function findAgent(seatOrLabel) {
    var af = global.__AGENT_FIELD__;
    if (!af) return null;
    if (typeof af.findAgent === 'function') return af.findAgent(seatOrLabel);
    var key = String(seatOrLabel || '').trim().toLowerCase();
    if (!key || !af._agents) return null;
    for (var i = 0; i < af._agents.length; i++) {
      var a = af._agents[i];
      var id = String((a.meta && a.meta.id) || a.id || '').toLowerCase();
      var label = String((a.meta && a.meta.label) || a.label || '').toLowerCase();
      if (id === key || label === key) return a;
    }
    return null;
  }

  function driveFallback(seatOrLabel, actions, detail) {
    var af = global.__AGENT_FIELD__;
    if (af && typeof af.drive === 'function') {
      return af.drive(seatOrLabel, actions, detail);
    }
    var a = findAgent(seatOrLabel) || (detail && findAgent(detail.label));
    if (!a || !a.controller || !a.controller.command) {
      console.warn('[field-body-drive] no controller for', seatOrLabel);
      return false;
    }
    var list = (actions && actions.length) ? actions : [{ op: 'approach' }, { op: 'jump' }];
    if (a.brain) {
      a.brain.nextAt = performance.now() + 8000;
      a.brain.target = null;
    }
    var delay = 0;
    list.slice(0, 5).forEach(function (act) {
      var op = String((act && (act.op || act.action)) || '').toLowerCase();
      setTimeout(function () {
        try {
          if (op === 'jump') a.controller.command('jump', { height: act.height || 5.2 });
          else if (op === 'idle' || op === 'stop') a.controller.command('idle');
          else if (op === 'move' && act.x != null && act.z != null) {
            a.controller.command('move', { x: +act.x, z: +act.z });
          } else if (op === 'approach') {
            a.controller.command('move', { x: (Math.random() - 0.5) * 2, z: (Math.random() - 0.5) * 2 });
          } else if (op === 'scatter') {
            var ang = Math.random() * Math.PI * 2;
            var r = 4 + Math.random() * 8;
            a.controller.command('move', { x: Math.cos(ang) * r, z: Math.sin(ang) * r });
          } else if (op === 'look_at_pilot' || op === 'look') {
            a.controller.command('turn', { look_at: { x: 0, z: 0 } });
          }
        } catch (e) {
          console.warn('[field-body-drive]', e);
        }
      }, delay);
      delay += op === 'jump' ? 450 : 700;
    });
    return true;
  }

  global.addEventListener('percfect-agent-body', function (ev) {
    var d = (ev && ev.detail) || {};
    driveFallback(d.seat || d.label, d.actions, d);
  });

  // Poll hook: if AF exposes register, rebind when ready
  var tries = 0;
  var t = setInterval(function () {
    tries += 1;
    var af = global.__AGENT_FIELD__;
    if (af && !af._bodyDriveWired) {
      af._bodyDriveWired = true;
      if (!af.drive) af.drive = driveFallback;
      console.info('[field-body-drive] wired to __AGENT_FIELD__');
      clearInterval(t);
    }
    if (tries > 40) clearInterval(t);
  }, 500);

  global.PercfectFieldBodyDrive = { drive: driveFallback };

  // Animate / Sim panel (CharacterController combat clips + procedural)
  if (!global.__PERCFECT_FIELD_ANIM_SIM_LOADER__) {
    global.__PERCFECT_FIELD_ANIM_SIM_LOADER__ = true;
    try {
      var s = document.createElement('script');
      s.src = '/static/js/field_anim_sim.js?v=1';
      s.async = true;
      (document.head || document.documentElement).appendChild(s);
    } catch (e) {
      console.warn('[field-body-drive] anim sim load failed', e);
    }
  }
})(typeof window !== 'undefined' ? window : this);
