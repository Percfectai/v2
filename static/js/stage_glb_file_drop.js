/**
 * Drop .glb files from Finder/OS onto the 3D board (or /3d stage wrap).
 * Flow: upload → /api/3d/upload-character → dock URL into Colosseum / Field / loadGlb.
 */
(function (global) {
  'use strict';
  if (global.__PERCFECT_STAGE_GLB_DROP__) return;
  global.__PERCFECT_STAGE_GLB_DROP__ = true;

  var MAX = 45 * 1024 * 1024;

  function isGlb(f) {
    if (!f) return false;
    var n = f.name || '';
    var t = (f.type || '').toLowerCase();
    return /\.glb$/i.test(n) || t === 'model/gltf-binary' ||
      (t === 'application/octet-stream' && /\.glb$/i.test(n));
  }

  function toast(msg) {
    if (global.PercfectLibrary && typeof global.PercfectLibrary.toast === 'function') {
      try { global.PercfectLibrary.toast(msg); return; } catch (_e) {}
    }
    var el = document.getElementById('p3d-stage-flash') || document.getElementById('boot-err');
    if (el && el.id === 'p3d-stage-flash') {
      el.textContent = msg;
      el.classList.add('is-on');
      setTimeout(function () { el.classList.remove('is-on'); }, 2000);
      return;
    }
    try {
      var t = document.createElement('div');
      t.textContent = msg;
      t.style.cssText = 'position:fixed;bottom:1.25rem;left:50%;transform:translateX(-50%);z-index:9999;background:rgba(0,0,0,.85);color:#86efac;padding:.5rem 1rem;border-radius:10px;font:700 13px system-ui;pointer-events:none';
      document.body.appendChild(t);
      setTimeout(function () { t.remove(); }, 2500);
    } catch (_e2) {
      console.info('[glb-drop]', msg);
    }
  }

  function hasOsFiles(e) {
    var dt = e.dataTransfer;
    if (!dt || !dt.types) return false;
    var types = Array.from(dt.types);
    return types.indexOf('Files') !== -1;
  }

  async function uploadOne(file) {
    if (file.size > MAX) throw new Error(file.name + ': too large (max ~45MB)');
    var fd = new FormData();
    fd.append('glb', file, file.name || 'body.glb');
    fd.append('name', (file.name || 'Body').replace(/\.glb$/i, ''));
    var res = await fetch('/api/3d/upload-character', {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
    });
    var data = await res.json().catch(function () { return {}; });
    if (res.status === 401 || data.login_required) {
      throw new Error('Log in to drop GLBs on the board');
    }
    if (!res.ok) throw new Error(data.error || ('Upload failed (' + res.status + ')'));
    var ch = data.character || data;
    var url = ch.glb_url || ch.url;
    if (!url) throw new Error('Upload ok but no glb_url returned');
    return { url: url, name: ch.name || file.name, id: ch.id };
  }

  function dockToBoard(url, name) {
    // Parent /3d page
    if (typeof global.loadGlb === 'function') {
      global.loadGlb(url, { celebrate: true });
      return true;
    }
    if (typeof global.dockGlbToStage === 'function') {
      global.dockGlbToStage(url);
      return true;
    }
    // Inside Colosseum — uses loadOne if exposed, else postMessage self
    if (global.__COLOSSEUM__ && typeof global.__COLOSSEUM__.loadGlb === 'function') {
      global.__COLOSSEUM__.loadGlb(url, name);
      return true;
    }
    // Inside Agent Field
    if (global.__AGENT_FIELD__ && typeof global.__AGENT_FIELD__.loadGlb === 'function') {
      global.__AGENT_FIELD__.loadGlb(url, name);
      return true;
    }
    // postMessage to parent or self handlers
    try {
      global.postMessage(
        { source: 'percfect-3d', type: 'loadGlb', action: 'loadGlb', url: url, name: name },
        '*'
      );
    } catch (_e) {}
    if (global.parent && global.parent !== global) {
      try {
        global.parent.postMessage(
          { source: 'percfect-3d', type: 'loadGlb', action: 'loadGlb', url: url, name: name },
          '*'
        );
      } catch (_e2) {}
    }
    // Last resort: open colosseum with glb
    if (!global.__AGENT_FIELD__ && !global.__COLOSSEUM__ && !document.getElementById('p3d-iframe')) {
      global.location.href = '/motion-lab/colosseum-stage.html?glb=' + encodeURIComponent(url);
      return true;
    }
    return false;
  }

  async function handleFiles(fileList) {
    var files = Array.from(fileList || []).filter(isGlb);
    if (!files.length) {
      toast('Drop a .glb file');
      return;
    }
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      toast(files.length > 1 ? 'Uploading ' + (i + 1) + '/' + files.length + '…' : 'Uploading ' + f.name + '…');
      try {
        var ent = await uploadOne(f);
        dockToBoard(ent.url, ent.name);
        toast((ent.name || 'Body') + ' on the board');
      } catch (err) {
        toast(err.message || 'Drop failed');
        console.warn('[stage-glb-drop]', err);
      }
    }
  }

  function wireZone(el) {
    if (!el || el._stageGlbDropBound) return;
    el._stageGlbDropBound = true;
    el.classList.add('stage-glb-drop-zone');

    el.addEventListener('dragenter', function (e) {
      if (!hasOsFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      el.classList.add('stage-glb-drag');
    });
    el.addEventListener('dragover', function (e) {
      if (!hasOsFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      try { e.dataTransfer.dropEffect = 'copy'; } catch (_e) {}
      el.classList.add('stage-glb-drag');
    });
    el.addEventListener('dragleave', function (e) {
      if (e.target === el || !el.contains(e.relatedTarget)) {
        el.classList.remove('stage-glb-drag');
      }
    });
    el.addEventListener('drop', function (e) {
      if (!hasOsFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      el.classList.remove('stage-glb-drag');
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) handleFiles(files);
    });
  }

  function injectCss() {
    if (document.getElementById('stage-glb-drop-css')) return;
    var s = document.createElement('style');
    s.id = 'stage-glb-drop-css';
    s.textContent =
      '.stage-glb-drop-zone.stage-glb-drag,' +
      '.p3d-stage-wrap.stage-glb-drag,' +
      'body.stage-glb-drag {' +
      '  outline: 3px dashed #00ff88 !important;' +
      '  outline-offset: -6px;' +
      '  box-shadow: inset 0 0 0 9999px rgba(0,255,136,0.08);' +
      '}' +
      '.p3d-stage-wrap { position: relative; }' +
      '.p3d-stage-wrap.stage-glb-drag::after {' +
      '  content: "Drop .glb onto the board";' +
      '  position: absolute; inset: 0; z-index: 30;' +
      '  display: flex; align-items: center; justify-content: center;' +
      '  pointer-events: none; font: 800 1.1rem system-ui; color: #86efac;' +
      '  background: rgba(6,12,18,0.45);' +
      '}';
    document.head.appendChild(s);
  }

  function boot() {
    injectCss();
    // Parent /3d page — overlay must sit above iframe so Finder drops work
    var wrap = document.getElementById('p3d-stage-wrap') ||
      document.querySelector('[data-lib-drop="3d"]');
    if (wrap) {
      // Transparent capture layer above iframe during file drag
      var cap = document.getElementById('p3d-glb-drop-cap');
      if (!cap) {
        cap = document.createElement('div');
        cap.id = 'p3d-glb-drop-cap';
        cap.setAttribute('aria-hidden', 'true');
        cap.style.cssText = 'position:absolute;inset:0;z-index:20;display:none;';
        wrap.appendChild(cap);
      }
      // Show capture layer only when OS files are dragged over window
      var depth = 0;
      window.addEventListener('dragenter', function (e) {
        if (!hasOsFiles(e)) return;
        depth += 1;
        cap.style.display = 'block';
        wrap.classList.add('stage-glb-drag');
      });
      window.addEventListener('dragleave', function () {
        depth = Math.max(0, depth - 1);
        if (depth === 0) {
          cap.style.display = 'none';
          wrap.classList.remove('stage-glb-drag');
        }
      });
      window.addEventListener('drop', function () {
        depth = 0;
        cap.style.display = 'none';
        wrap.classList.remove('stage-glb-drag');
      });
      wireZone(cap);
      wireZone(wrap);
    }

    // Full-page boards (Colosseum / Field / agent-stage) — drop on body/canvas
    var path = (global.location && global.location.pathname) || '';
    if (/colosseum-stage|agent-field|agent-stage|stage-board|rivals-stage/i.test(path)) {
      wireZone(document.body);
      var canvas = document.getElementById('field-canvas') ||
        document.querySelector('canvas');
      if (canvas && canvas.parentElement) wireZone(canvas.parentElement);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  global.PercfectStageGlbDrop = { handleFiles: handleFiles, uploadOne: uploadOne, dockToBoard: dockToBoard };
})(typeof window !== 'undefined' ? window : this);
