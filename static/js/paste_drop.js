/**
 * PercfectPasteDrop — paste images/videos from clipboard (Cmd/Ctrl+V).
 *
 * Rules:
 *  - Clipboard image → always attach as file (even if focus is in the prompt box)
 *  - Clipboard URL text → attach as URL when zone accepts it
 *  - Plain text in a normal text field → leave alone (type as usual)
 *  - No need to click the drop zone first when only one image zone is bound
 */
(function (global) {
  const zones = new Map();
  let activeId = null;
  let docBound = false;

  function isUrl(text) {
    const t = (text || '').trim();
    return /^https?:\/\//i.test(t);
  }

  function isTypingTarget(el) {
    if (!el) return false;
    const tag = el.tagName;
    if (tag === 'TEXTAREA' || el.isContentEditable) return true;
    if (tag === 'INPUT') {
      const type = (el.type || 'text').toLowerCase();
      return !['button', 'submit', 'checkbox', 'radio', 'file', 'range', 'color'].includes(type);
    }
    return false;
  }

  function pickClipboardFile(clipboardData, accept) {
    if (!clipboardData) return null;
    const items = clipboardData.items;
    if (items && items.length) {
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind !== 'file') continue;
        const file = item.getAsFile();
        if (!file) continue;
        if (fileOk(file, accept || 'image')) return file;
      }
    }
    // Some browsers put files on clipboardData.files
    const files = clipboardData.files;
    if (files && files.length) {
      for (let i = 0; i < files.length; i++) {
        if (fileOk(files[i], accept || 'image')) return files[i];
      }
    }
    return null;
  }

  function fileOk(file, accept) {
    if (!file) return false;
    const name = file.name || 'paste';
    if (accept === 'image') {
      return (file.type && file.type.startsWith('image/')) ||
        /\.(png|jpe?g|gif|webp|heic|heif|bmp)$/i.test(name);
    }
    if (accept === 'video') {
      return (file.type && file.type.startsWith('video/')) ||
        /\.(mp4|mov|webm|mkv|m4v)$/i.test(name);
    }
    return true;
  }

  function resolveCfg() {
    if (activeId && zones.has(activeId)) return zones.get(activeId);
    // Single bound zone — use it without requiring a prior click
    if (zones.size === 1) {
      const only = zones.values().next().value;
      return only || null;
    }
    // Prefer an image zone if several
    for (const cfg of zones.values()) {
      if ((cfg.accept || 'image') === 'image') return cfg;
    }
    return zones.size ? zones.values().next().value : null;
  }

  function onPaste(e) {
    const cfg = resolveCfg();
    if (!cfg) return;

    const target = e.target;
    const urlInput = cfg.urlInputId ? document.getElementById(cfg.urlInputId) : null;
    const onUrlField = urlInput && (target === urlInput || (urlInput.contains && urlInput.contains(target)));
    const accept = cfg.accept || 'image';

    // 1) Image/video file on clipboard — ALWAYS take it (works while typing in prompt)
    const file = pickClipboardFile(e.clipboardData, accept);
    if (file) {
      e.preventDefault();
      e.stopPropagation();
      try {
        if (cfg.onFile) cfg.onFile(file);
      } catch (err) {
        console.error('[paste] onFile failed', err);
      }
      // Visual feedback on zone if present
      const zoneEl = document.getElementById(cfg.zoneId);
      if (zoneEl) {
        zoneEl.classList.add('paste-flash');
        setTimeout(() => zoneEl.classList.remove('paste-flash'), 500);
      }
      return;
    }

    // 2) URL text
    const text = (e.clipboardData && e.clipboardData.getData('text/plain')) || '';
    if (isUrl(text)) {
      // In a normal typing field that is NOT the URL field, allow pasting URL as text
      // unless it's clearly an image/video URL and we have an image zone
      const looksMedia =
        accept === 'image'
          ? /\.(png|jpe?g|gif|webp|heic|bmp)(\?|$)/i.test(text) ||
            /cdn\.|imgur|twimg|googleusercontent|supabase|storage/i.test(text)
          : true;
      if (isTypingTarget(target) && !onUrlField && !looksMedia) return;

      e.preventDefault();
      e.stopPropagation();
      if (urlInput) urlInput.value = text.trim();
      try {
        if (cfg.onUrl) cfg.onUrl(text.trim());
      } catch (err) {
        console.error('[paste] onUrl failed', err);
      }
      return;
    }

    // 3) Plain text — don't intercept (let prompt typing work)
  }

  function ensureDocListener() {
    if (docBound) return;
    // capture phase so we beat other handlers
    document.addEventListener('paste', onPaste, true);
    docBound = true;
  }

  function bind(opts) {
    const zone = typeof opts.zone === 'string' ? document.getElementById(opts.zone) : opts.zone;
    const extraFocus = opts.focusIds || [];
    if (!zone && !extraFocus.length) return { activate() {}, destroy() {} };

    const id = (zone && (zone.id || ('paste-zone-' + zones.size))) || ('paste-zone-' + zones.size);
    if (zone && !zone.id) zone.id = id;

    const cfg = {
      zoneId: zone ? zone.id : id,
      accept: opts.accept || 'image',
      onFile: opts.onFile || null,
      onUrl: opts.onUrl || null,
      urlInputId: opts.urlInputId || null,
    };
    zones.set(id, cfg);
    ensureDocListener();

    const activate = () => { activeId = id; };
    if (zone) {
      zone.addEventListener('mousedown', activate);
      zone.addEventListener('click', activate);
      zone.addEventListener('focusin', activate);
      if (!zone.hasAttribute('tabindex')) zone.setAttribute('tabindex', '0');
      zone.setAttribute('title', zone.getAttribute('title') || 'Click then Cmd/Ctrl+V to paste a photo');
    }

    // Also activate when user focuses prompt / URL / related fields
    const focusEls = [];
    if (cfg.urlInputId) {
      const urlEl = document.getElementById(cfg.urlInputId);
      if (urlEl) focusEls.push(urlEl);
    }
    (opts.focusIds || []).forEach((fid) => {
      const el = typeof fid === 'string' ? document.getElementById(fid) : fid;
      if (el) focusEls.push(el);
    });
    focusEls.forEach((el) => {
      el.addEventListener('focus', activate);
      el.addEventListener('mousedown', activate);
    });

    // Auto-add URL when user finishes pasting a URL into the URL field
    if (cfg.urlInputId) {
      const urlEl = document.getElementById(cfg.urlInputId);
      if (urlEl) {
        urlEl.addEventListener('paste', (ev) => {
          // After browser pastes text, next tick check URL
          setTimeout(() => {
            const u = (urlEl.value || '').trim();
            if (u && isUrl(u) && cfg.onUrl) cfg.onUrl(u);
          }, 0);
        });
      }
    }

    return {
      activate,
      destroy() {
        zones.delete(id);
        if (activeId === id) activeId = null;
      },
    };
  }

  global.PercfectPasteDrop = { bind, isUrl };
})(typeof window !== 'undefined' ? window : globalThis);
