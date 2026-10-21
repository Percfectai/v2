/**
 * Percfect User Library Sidebar
 * Your characters · photos · videos · motion backgrounds · 3D GLBs — drag anywhere.
 * Only loads for the logged-in user.
 */
(function (global) {
  const MIME = 'application/x-percfect-library';
  const PAGE_SIZE = 24;
  let open = false;
  let tab = 'characters';
  // A page can lock the picker to one section (Card Shop / Battle Cards → cards).
  const onlyTab = global.PERCFECT_LIBRARY_ONLY || null;
  if (onlyTab) tab = onlyTab;
  let cache = null;
  let loading = false;
  /** @type {Record<string, number>} */
  let pageByTab = {};
  /** @type {null | { max: number, selected: string[], tab?: string, kind?: string, title?: string, autoDone?: boolean, onChange?: Function, onDone?: Function, onCancel?: Function }} */
  let pickMode = null;

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[m]));
  }

  function isProbablyVideoUrl(u) {
    return /\.(mp4|webm|mov)($|\?)/i.test(String(u || ''));
  }

  /** Collapse extend/trim/re-roll clips into one library tile per chain_id. */
  function groupVideosByChain(items) {
    const sorted = (items || []).slice().sort((a, b) => {
      const ta = Date.parse(a.created_at || 0) || 0;
      const tb = Date.parse(b.created_at || 0) || 0;
      if (tb !== ta) return tb - ta;
      return (Number(b.id) || 0) - (Number(a.id) || 0);
    });
    const map = new Map();
    const order = [];
    sorted.forEach((it) => {
      const cid = String(it.chain_id || it.id || it.url || '');
      if (!cid) return;
      if (!map.has(cid)) {
        map.set(cid, []);
        order.push(cid);
      }
      map.get(cid).push(it);
    });
    return order.map((cid) => {
      const clips = map.get(cid) || [];
      const newest = clips[0] || {};
      const oldestFirst = clips.slice().reverse();
      return {
        ...newest,
        chain_id: cid,
        chain_count: clips.length,
        chain_clips: oldestFirst,
        chain_prompts: oldestFirst.map((c) => c.prompt || '').filter(Boolean),
        is_chain: clips.length > 1,
        name: clips.length > 1
          ? ((newest.prompt || newest.name || 'Video chain').slice(0, 40) + ' · ×' + clips.length)
          : (newest.name || newest.prompt || 'Video'),
      };
    });
  }

  /** Show first frame for <video class="lib-vid-thumb"> tiles (no separate poster). */
  function hydrateVideoThumbs(root) {
    const scope = root || document;
    scope.querySelectorAll('video.lib-vid-thumb').forEach((vid) => {
      if (!vid || vid.dataset.posterReady === '1') return;
      const seek = () => {
        try {
          const d = Number(vid.duration);
          const t = (Number.isFinite(d) && d > 0) ? Math.min(0.1, d * 0.02) : 0.1;
          if (vid.currentTime < 0.05) vid.currentTime = t;
        } catch (_e) { /* ignore seek errors */ }
      };
      const mark = () => {
        try { vid.pause(); } catch (_e) {}
        vid.dataset.posterReady = '1';
      };
      vid.addEventListener('loadedmetadata', seek, { once: true });
      vid.addEventListener('seeked', mark, { once: true });
      if (vid.readyState >= 1) seek();
    });
  }

  function toast(msg) {
    let t = $('lib-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'lib-toast';
      t.className = 'lib-toast';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), 2200);
  }

  /** Full-screen image/video preview (above library panel z-index 1050). */
  function openMediaLightbox(opts) {
    const o = opts || {};
    const url = o.url || '';
    if (!url) {
      toast('No media URL for this item');
      return;
    }
    const isVideo = !!(o.isVideo || o.kind === 'video' || o.type === 'video');
    const name = o.name || (isVideo ? 'Video' : 'Image');
    // Close any prior library lightbox
    document.querySelectorAll('.lib-media-lightbox').forEach((el) => el.remove());

    const overlay = document.createElement('div');
    overlay.className = 'lib-media-lightbox';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', name);

    const media = isVideo
      ? Object.assign(document.createElement('video'), {
          src: url,
          controls: true,
          playsInline: true,
          autoplay: true,
          loop: true,
        })
      : Object.assign(document.createElement('img'), { src: url, alt: name });

    const actions = document.createElement('div');
    actions.className = 'lib-media-lightbox-actions';

    const close = () => {
      try {
        if (isVideo && media.pause) media.pause();
      } catch (_e) { /* ignore */ }
      overlay.remove();
      document.removeEventListener('keydown', onKey);
    };

    let applying = false;
    const mkBtn = (label, cls, fn) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = cls || 'lib-lb-btn';
      b.textContent = label;
      b.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        // One click only — stacked clicks were freezing UI then filling every ref slot
        if (b.disabled || applying) return;
        const ret = fn(b);
        if (ret && typeof ret.then === 'function') {
          b.disabled = true;
          ret.finally(() => {
            /* leave disabled if close() removes the overlay */
          });
        }
      };
      return b;
    };

    // Primary actions by kind — not just Close
    // Photo / still → Animate (make a video) + optional Use as reference
    // Video → Extend
    // Character still → Animate + Arena (+ profile / 360 if available)

    const payload = {
      kind: o.kind || (isVideo ? 'video' : 'photo'),
      url,
      id: o.id || '',
      name,
      thumb: o.thumb || url,
      primary_image_url: url,
      spin: o.spin || o.spin_video_url || '',
      spin_video_url: o.spin || o.spin_video_url || '',
      type: o.type || (isVideo ? 'video' : 'image'),
    };

    /** Put still in a ref box if we're on Videos/Photos; else go to Videos with handoff */
    function goAnimateStill() {
      const still = url;
      if (!still) {
        toast('No image URL');
        return;
      }
      try {
        sessionStorage.setItem('percfect_animate_url', still);
        sessionStorage.setItem('percfect_animate_prompt', 'animate this');
      } catch (_e) { /* ignore */ }
      close();
      setOpen(false);

      // Already on Videos → drop into next empty ref + set prompt
      if (document.getElementById('vid-ref-slots')) {
        try {
          if (typeof global.vidAddUrl === 'function') {
            global.vidAddUrl(still, null);
          } else if (typeof global.applyLibraryVideoImage === 'function') {
            global.applyLibraryVideoImage({ kind: 'photo', url: still, primary_image_url: still });
          }
          const ta = document.getElementById('vid-prompt');
          if (ta && !String(ta.value || '').trim()) ta.value = 'animate this';
          if (typeof global.ensureAnimatePrompt === 'function') global.ensureAnimatePrompt();
          if (typeof global.updateVidCostUI === 'function') global.updateVidCostUI();
          document.getElementById('vid-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          toast('Reference set — ready to generate');
          return;
        } catch (err) {
          toast((err && err.message) || 'Could not set video ref');
        }
      }

      // On Photos page → still can go to photo refs, then user can Animate; or jump to Videos
      if (document.getElementById('img-ref-slots') && typeof global.photoAddUrl === 'function') {
        try {
          global.photoAddUrl(still, null);
        } catch (_e) { /* ignore */ }
      }

      if (typeof global.sendToVideo === 'function') {
        try {
          global.sendToVideo(still);
          return;
        } catch (_e) { /* fall through */ }
      }
      window.location.href = '/percfectstudios/videos?animate=1';
    }

    /** Extend this clip on Videos page */
    function goExtendVideo() {
      try {
        sessionStorage.setItem('percfect_extend_url', url);
      } catch (_e) { /* ignore */ }
      close();
      setOpen(false);
      if (typeof global.applyLibraryExtend === 'function') {
        global.applyLibraryExtend(payload).catch(() => {
          window.location.href = '/percfectstudios/videos';
        });
        return;
      }
      if (typeof global.applyLibraryVideo === 'function') {
        global.applyLibraryVideo(payload).catch(() => {
          window.location.href = '/percfectstudios/videos';
        });
        return;
      }
      window.location.href = '/percfectstudios/videos';
    }

    /** Open Arena with this character pre-seeded when possible */
    function goArena() {
      if (o.id) {
        try {
          sessionStorage.setItem('percfect_arena_char_id', String(o.id));
          sessionStorage.setItem('percfect_arena_char_url', url);
        } catch (_e) { /* ignore */ }
      }
      close();
      setOpen(false);
      window.location.href = '/studios/percfectcharacter/arena';
    }

    /** Card Studio with this character on the card (a card reopens its saved plate). */
    function goCardStudio() {
      close();
      setOpen(false);
      const pick = { id: o.id || '', url, name: name || '', kind: o.kind || '' };
      if (global.PercfectCardStudio && typeof global.PercfectCardStudio.place === 'function') {
        global.PercfectCardStudio.place(pick);
        return;
      }
      try {
        sessionStorage.setItem('percfect_card_pick', JSON.stringify(pick));
      } catch (_e) { /* ignore */ }
      window.location.href = '/studios/trading-cards';
    }

    /** Battle Cards with this card's character as your fighter */
    function goBattle() {
      close();
      setOpen(false);
      if (typeof global.percfectPickCard === 'function') {
        global.percfectPickCard(payload);
        return;
      }
      try {
        sessionStorage.setItem('percfect_battle_pick', String(o.id || ''));
      } catch (_e) { /* ignore */ }
      window.location.href = '/studios/battle-cards';
    }

    const soon = (label) => {
      const b = mkBtn(label + ' · coming soon', 'lib-lb-btn lib-lb-btn-ghost', () => {});
      b.disabled = true;
      b.title = 'Coming soon';
      return b;
    };

    /** Download / save a copy to the device (in case it was never saved locally) */
    async function goSaveDownload() {
      const safe = String(name || (isVideo ? 'percfect-video' : 'percfect-image'))
        .replace(/[^\w\-]+/g, '_')
        .slice(0, 48);
      const ext = isVideo ? 'mp4' : 'jpg';
      const filename = safe + '.' + ext;
      try {
        if (typeof global.downloadFile === 'function') {
          await global.downloadFile(url, filename);
          toast('Saving… check your downloads');
          return;
        }
        const res = await fetch(url, { mode: 'cors', credentials: 'omit' });
        if (!res.ok) throw new Error('download failed');
        const blob = await res.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        toast('Saved to downloads');
      } catch (_e) {
        // Cross-origin: open in new tab so user can save manually
        window.open(url, '_blank', 'noopener');
        toast('Opened media — use Save / Download in the browser');
      }
    }

    /** ONE ref box only. Close lightbox + library. Never scroll to Extend. */
    async function useAsReferenceOnce(btn) {
      if (applying) return;
      applying = true;
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Setting…';
      }
      close(); // lightbox first
      try {
        let slot = -1;
        if (document.getElementById('vid-ref-slots')) {
          if (typeof global.applyLibraryVideoImage === 'function') {
            slot = await global.applyLibraryVideoImage(payload, null);
          } else if (typeof global.vidAddUrl === 'function') {
            slot = global.vidAddUrl(url, null);
          }
          if (slot == null || slot < 0) throw new Error('All 4 video refs are full');
          toast('Ref ' + (Number(slot) + 1) + ' set');
        } else if (document.getElementById('img-ref-slots')) {
          if (typeof global.applyLibraryImage === 'function') {
            slot = await global.applyLibraryImage(payload, null);
          } else if (typeof global.photoAddUrl === 'function') {
            slot = global.photoAddUrl(url, null);
          }
          if (slot == null || slot < 0) throw new Error('All photo refs are full');
          toast('Ref ' + (Number(slot) + 1) + ' set');
        } else {
          toast('Open Videos or Photos to use a reference');
          return;
        }
        setOpen(false); // close library so they can hit Generate
        // Stay on gen panel — do NOT scroll to Extend
        try {
          document.getElementById('vid-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (_e) { /* ignore */ }
      } catch (err) {
        applying = false;
        toast((err && err.message) || 'Could not set reference');
      }
    }

    async function deleteLibraryItem() {
      const id = o.id;
      if (!id) {
        toast('Nothing to delete');
        return;
      }
      const label = name || (isVideo ? 'this video' : o.kind === 'character' ? 'this character' : 'this item');
      if (!window.confirm('Delete ' + label + ' forever? This cannot be undone.')) return;
      try {
        let res;
        if (o.kind === 'character') {
          const fd = new FormData();
          fd.append('character_id', String(id));
          res = await fetch('/studios/percfectcharacter/delete', {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
          });
        } else {
          res = await fetch('/percfectstudios/delete-generation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ id: String(id) }),
          });
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Delete failed');
        if (cache) {
          ['characters', 'videos', 'photos', 'backgrounds', 'cards'].forEach((k) => {
            if (Array.isArray(cache[k])) {
              cache[k] = cache[k].filter((x) => String(x.id) !== String(id));
            }
          });
        }
        toast('Deleted');
        close();
        render();
      } catch (err) {
        toast((err && err.message) || 'Could not delete');
      }
    }

    // —— Contextual CTAs (primary first) ——
    if (isVideo) {
      // On Percfect Productions: drop this library video straight into the stitcher
      if (/\/percfectproductions/.test(location.pathname)) {
        actions.appendChild(mkBtn('＋ Add to this cut', 'lib-lb-btn', async () => {
          const vurl = o.url || o.src || o.video_url || o.file_url || url;
          if (!vurl) {
            toast('No video URL');
            return;
          }
          try {
            const res = await fetch(vurl, { credentials: 'same-origin' });
            if (!res.ok) throw new Error('Could not download video');
            const blob = await res.blob();
            let fname = o.name || o.fileName || 'library-clip.mp4';
            if (!/\.(mp4|webm|mov|m4v|mkv)$/i.test(fname)) fname += '.mp4';
            const file = new File([blob], fname, { type: blob.type || 'video/mp4' });
            if (typeof window.__ppImportFiles === 'function') {
              await window.__ppImportFiles([file], 'library');
            } else {
              const root = document.querySelector('.flex.h-dvh') || document.getElementById('app');
              if (!root) throw new Error('Productions page not ready');
              const dt = new DataTransfer();
              dt.items.add(file);
              root.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            }
            toast('Added to Productions');
            close();
            setOpen(false);
          } catch (err) {
            toast((err && err.message) || 'Could not add video');
          }
        }));
      }
      actions.appendChild(mkBtn('⤢ Extend', 'lib-lb-btn', goExtendVideo));
      if (o.id) actions.appendChild(mkBtn('🗑 Delete video', 'lib-lb-btn lib-lb-btn-ghost', deleteLibraryItem));
    } else if (o.kind === 'card') {
      actions.appendChild(mkBtn('⚔ Battle with this card', 'lib-lb-btn', goBattle));
      actions.appendChild(mkBtn('✎ Edit in Card Studio', 'lib-lb-btn', goCardStudio));
    } else if (o.kind === 'character') {
      actions.appendChild(mkBtn('🃏 Create Percfect Hero Card', 'lib-lb-btn', goCardStudio));
      actions.appendChild(mkBtn('⚔ Take to Arena', 'lib-lb-btn', goArena));
      actions.appendChild(soon('Add to comic reference sheet'));
      actions.appendChild(soon('Make 3D'));
      actions.appendChild(mkBtn('▶ Animate', 'lib-lb-btn', goAnimateStill));
      // Character still can also be a single video/photo ref
      if (document.getElementById('vid-ref-slots') || document.getElementById('img-ref-slots')) {
        actions.appendChild(mkBtn('Use as reference', 'lib-lb-btn', useAsReferenceOnce));
      }
      if (o.spin) {
        actions.appendChild(mkBtn('Play 360°', 'lib-lb-btn', () => {
          close();
          openMediaLightbox({
            url: o.spin,
            kind: 'character',
            type: 'video',
            id: o.id,
            name: (name || 'Character') + ' · 360°',
            thumb: o.thumb || url,
            spin: o.spin,
            isVideo: true,
          });
        }));
      }
      if (o.id && global.CharProfile && typeof CharProfile.open === 'function') {
        actions.appendChild(mkBtn('Open profile', 'lib-lb-btn', () => {
          close();
          try {
            if (cache && cache.characters) {
              CharProfile.setChars(cache.characters.map(c => ({
                id: c.id,
                name: c.name,
                primary_image_url: c.url || c.primary_image_url,
                images: c.images || [],
                spin_video_url: c.spin_video_url,
                gender: c.gender,
                prompt: c.prompt,
              })), true);
            }
            CharProfile.open(Number(o.id) || o.id);
          } catch (_e) {
            toast('Could not open profile');
          }
        }));
      }
      if (o.id) actions.appendChild(mkBtn('🗑 Delete character', 'lib-lb-btn lib-lb-btn-ghost', deleteLibraryItem));
    } else {
      // Photos, backgrounds, generic stills — make a video from this image
      actions.appendChild(mkBtn('✎ Edit', 'lib-lb-btn', () => {
        if (!url) return;
        close();
        if (typeof global.loadImageAsReference === 'function' && document.getElementById('img-ref-slots')) {
          global.loadImageAsReference(url);
          return;
        }
        try { sessionStorage.setItem('percfect_photo_ref', url); } catch (_e) {}
        window.location.href = '/percfectstudios/photos';
      }));
      actions.appendChild(mkBtn('▶ Animate', 'lib-lb-btn', goAnimateStill));
      if (typeof global.applyLibraryImage === 'function'
          || typeof global.applyLibraryVideoImage === 'function'
          || typeof global.vidAddUrl === 'function'
          || typeof global.photoAddUrl === 'function'
          || document.getElementById('vid-ref-slots')
          || document.getElementById('img-ref-slots')) {
        actions.appendChild(mkBtn('Use as reference', 'lib-lb-btn', useAsReferenceOnce));
      }
      if (o.id) actions.appendChild(mkBtn('🗑 Delete', 'lib-lb-btn lib-lb-btn-ghost', deleteLibraryItem));
    }

    // Always offer Save/download (forgot to keep a local copy)
    actions.appendChild(mkBtn('↓ Save', 'lib-lb-btn', () => { goSaveDownload(); }));
    actions.appendChild(mkBtn('Close', 'lib-lb-btn lib-lb-btn-ghost', close));

    const hint = document.createElement('p');
    hint.className = 'lib-media-lightbox-hint';
    hint.textContent = isVideo
      ? 'Extend continues this clip · Save downloads a copy · Esc to close'
      : (o.kind === 'character'
        ? 'Hero Card · Arena · Animate = video · Save a copy · Esc to close'
        : o.kind === 'card'
          ? 'Battle · Edit in Card Studio · Save a copy · Esc to close'
          : 'Animate = make a video · Save a copy · Esc to close');

    overlay.append(media, actions, hint);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    media.addEventListener('click', (e) => e.stopPropagation());

    const onKey = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
  }

  /**
   * On Photos/Videos pages: one tap puts a still into the next empty ref box.
   * Returns true if it dropped. Full blow-up is the ⛶ zoom button.
   */
  let _dropStillBusy = false;
  async function tryDropStillIntoPageRefs(el) {
    if (!el || pickMode) return false;
    // One tap = one slot. Ignore re-entry while painting (was multi-filling all 4).
    if (_dropStillBusy) return true;
    const p = payloadFromEl(el);
    const kind = (p.kind || p.type || '').toLowerCase();
    // Only stills for ref boxes (not videos / 3d)
    if (kind === 'video' || kind === '3d') return false;
    const url = (p.url || p.thumb || p.primary_image_url || '').trim();
    if (!url) return false;

    // Videos page — 4 ref slots (prefer explicit helpers on window)
    const vidSlots = document.getElementById('vid-ref-slots');
    if (vidSlots) {
      const addVid = global.vidAddUrl || (typeof vidAddUrl === 'function' ? vidAddUrl : null);
      const firstEmpty = global.vidFirstEmpty || (typeof vidFirstEmpty === 'function' ? vidFirstEmpty : null);
      if (typeof firstEmpty === 'function' && firstEmpty() < 0) {
        toast('All 4 video refs are full');
        return true;
      }
      _dropStillBusy = true;
      try {
        if (typeof addVid === 'function') {
          const slot = addVid(url, null);
          if (slot < 0) {
            toast('All 4 video refs are full');
            return true;
          }
          if (typeof global.ensureAnimatePrompt === 'function') global.ensureAnimatePrompt();
          if (typeof global.updateVidCostUI === 'function') global.updateVidCostUI();
          toast('Ref ' + (Number(slot) + 1) + ' set');
          return true;
        }
        if (typeof global.applyLibraryVideoImage === 'function') {
          await global.applyLibraryVideoImage(p);
          toast('Video reference set');
          return true;
        }
      } finally {
        setTimeout(() => { _dropStillBusy = false; }, 350);
      }
    }

    // Photos page — 3 ref slots
    const imgSlots = document.getElementById('img-ref-slots');
    if (imgSlots) {
      const addPhoto = global.photoAddUrl || (typeof photoAddUrl === 'function' ? photoAddUrl : null);
      const firstEmpty = global.photoFirstEmpty || (typeof photoFirstEmpty === 'function' ? photoFirstEmpty : null);
      if (typeof firstEmpty === 'function' && firstEmpty() < 0) {
        toast('All photo refs are full');
        return true;
      }
      _dropStillBusy = true;
      try {
        if (typeof addPhoto === 'function') {
          const slot = addPhoto(url, null);
          if (slot < 0) {
            toast('All photo refs are full');
            return true;
          }
          toast('Ref ' + (Number(slot) + 1) + ' set');
          return true;
        }
        if (typeof global.applyLibraryImage === 'function') {
          await global.applyLibraryImage(p);
          toast('Photo reference set');
          return true;
        }
      } finally {
        setTimeout(() => { _dropStillBusy = false; }, 350);
      }
    }
    return false;
  }

  function openItemPreview(el) {
    if (!el) return;
    const p = payloadFromEl(el);
    const isVideo = p.kind === 'video' || p.type === 'video';
    // Characters: still first; spin video available via button if present
    let mediaUrl = isVideo ? (p.url || p.spin || '') : (p.url || p.thumb || '');
    if (!mediaUrl && p.spin) {
      openMediaLightbox({
        url: p.spin,
        kind: p.kind,
        type: 'video',
        id: p.id,
        name: p.name,
        thumb: p.thumb,
        spin: p.spin,
        isVideo: true,
      });
      return;
    }
    openMediaLightbox({
      url: mediaUrl,
      kind: p.kind,
      type: p.type,
      id: p.id,
      name: p.name,
      thumb: p.thumb,
      spin: p.spin,
      isVideo,
    });
  }

  function setOpen(v) {
    open = !!v;
    const panel = $('user-lib-panel');
    const fab = $('user-lib-fab');
    const scrim = $('user-lib-scrim');
    if (panel) panel.classList.toggle('open', open);
    if (fab) fab.classList.toggle('open', open);
    if (scrim) scrim.classList.toggle('open', open);
    document.body.classList.toggle('lib-sidebar-open', open);
    if (open && !cache && !loading) loadLibrary();
    if (!open && pickMode) {
      // Closing via scrim/X while picking — cancel pick, leave prior selection alone
      const cancel = pickMode.onCancel;
      clearPickUi(false);
      if (typeof cancel === 'function') {
        try { cancel(); } catch (_e) { /* ignore */ }
      }
    }
  }

  function toggle() { setOpen(!open); }

  function setTab(name) {
    if (pickMode) {
      const allowed = pickMode.tab || 'characters';
      const kind = pickMode.kind || allowed;
      // Extend picker: videos tab OR characters (360° spin)
      if (kind === 'extend' || kind === 'videos_or_spins') {
        if (name !== 'videos' && name !== 'characters') {
          toast('Pick a video or a character with 360° spin');
          return;
        }
      } else if (kind === 'photos' || kind === 'photo' || kind === 'images') {
        // Photo / animate pickers: photos, characters, backgrounds all valid stills
        if (name !== 'photos' && name !== 'characters' && name !== 'backgrounds') {
          toast('Pick a photo, character, or background still');
          return;
        }
      } else if (name !== allowed) {
        toast(allowed === 'backgrounds' ? 'Pick a background from this list' : 'Pick from this list');
        return;
      }
    }
    if (onlyTab && name !== onlyTab) return;
    tab = name;
    if (!pageByTab[tab]) pageByTab[tab] = 1;
    document.querySelectorAll('.lib-tab').forEach(el => {
      el.classList.toggle('active', el.dataset.tab === name);
      if (!pickMode) {
        el.style.opacity = '';
        el.style.pointerEvents = '';
      }
    });
    render();
  }

  function clearPickUi(keepOpen) {
    pickMode = null;
    document.body.classList.remove('lib-pick-mode');
    const ban = $('lib-pick-banner');
    const acts = $('lib-pick-actions');
    const foot = $('lib-foot');
    if (ban) { ban.classList.remove('show'); ban.innerHTML = ''; }
    if (acts) acts.classList.remove('show');
    if (foot) foot.style.display = '';
    document.querySelectorAll('.lib-tab').forEach(el => {
      el.style.opacity = '';
      el.style.pointerEvents = '';
    });
    if (!keepOpen) {
      // leave open state to caller
    }
    if (cache) render();
  }

  function updatePickChrome() {
    if (!pickMode) return;
    const max = Math.max(1, Number(pickMode.max) || 1);
    const min = Math.max(1, Math.min(max, Number(pickMode.min) || max));
    const n = pickMode.selected.length;
    const ban = $('lib-pick-banner');
    const done = $('lib-pick-done');
    const kind = pickMode.kind || pickMode.tab || 'characters';
    const isBg = kind === 'backgrounds' || kind === 'background';
    const isStillPick = kind === 'photos' || kind === 'photo' || kind === 'images' || kind === 'image';
    if (ban) {
      let need;
      if (isBg) {
        need = 'Tap a background to use it.';
      } else if (isStillPick) {
        need = max === 1
          ? 'Tap a <strong>character</strong>, photo, or background still.'
          : `Tap up to <strong>${max}</strong> stills (characters · photos · backgrounds).`;
      } else if (max === 1) {
        need = 'Tap a character to select it.';
      } else if (min < max) {
        need = `Tap <strong>${min}–${max}</strong> characters (order = #1, #2…).`;
      } else {
        need = `Tap <strong>${max}</strong> characters (order = #1, #2${max > 2 ? ', …' : ''}).`;
      }
      const title = pickMode.title || (isBg ? 'Pick background' : (isStillPick ? 'Pick still' : 'Pick character'));
      const picked = n
        ? ` · <strong>${n}/${max}</strong> selected`
        : (min < max
          ? ` · select <strong>${min}–${max}</strong>`
          : ` · select <strong>${max}</strong>`);
      ban.innerHTML = `<strong>${escapeHtml(title)}</strong> — ${need}${picked}`;
      ban.classList.add('show');
    }
    if (done) {
      // Arena: min 2 max 3 — Done enables at 2, not only at 3
      done.disabled = n < min;
      if (isBg) {
        done.textContent = n >= min ? '✓ Use this background' : 'Select a background';
      } else if (isStillPick) {
        done.textContent = n >= min
          ? (max === 1 ? '✓ Use this still' : `✓ Use these ${n} stills`)
          : 'Select a still';
      } else if (max === 1) {
        done.textContent = n >= min ? '✓ Use this character' : 'Select a character';
      } else if (n < min) {
        done.textContent = `Select ${min - n} more`;
      } else if (n < max) {
        done.textContent = `✓ Use these ${n} (or pick up to ${max})`;
      } else {
        done.textContent = `✓ Use these ${n} characters`;
      }
    }
    const acts = $('lib-pick-actions');
    if (acts) acts.classList.add('show');
    const foot = $('lib-foot');
    if (foot) foot.style.display = 'none';
    document.body.classList.add('lib-pick-mode');
    // Lock non-target tabs visually (still-pick allows characters + photos + backgrounds)
    document.querySelectorAll('.lib-tab').forEach(el => {
      const t = el.dataset.tab;
      const kind = pickMode.kind || pickMode.tab || 'characters';
      let ok = false;
      if (kind === 'extend' || kind === 'videos_or_spins') {
        ok = (t === 'videos' || t === 'characters');
      } else if (kind === 'photos' || kind === 'photo' || kind === 'images' || kind === 'image') {
        // Animate / video refs / photo refs — any still source
        ok = (t === 'photos' || t === 'characters' || t === 'backgrounds');
      } else if (kind === 'backgrounds' || kind === 'background') {
        ok = (t === 'backgrounds');
      } else {
        const allowed = pickMode.tab || 'characters';
        ok = (t === allowed);
      }
      el.style.opacity = ok ? '1' : '0.35';
      el.style.pointerEvents = ok ? '' : 'none';
    });
  }

  function togglePickItem(id, name) {
    if (!pickMode || id == null || id === '') return;
    const max = Math.max(1, Number(pickMode.max) || 1);
    id = String(id);
    const i = pickMode.selected.indexOf(id);
    if (i >= 0) {
      pickMode.selected.splice(i, 1);
    } else if (max === 1) {
      pickMode.selected = [id];
    } else if (pickMode.selected.length >= max) {
      pickMode.selected.pop();
      pickMode.selected.push(id);
    } else {
      pickMode.selected.push(id);
    }
    pickMode.selected = pickMode.selected.filter((v, idx, a) => a.indexOf(v) === idx);
    updatePickChrome();
    render();
    if (typeof pickMode.onChange === 'function') {
      try {
        pickMode.onChange(pickMode.selected.slice(), { id, name });
      } catch (_e) { /* ignore */ }
    }
    // Auto-finish when full (one tap for single pick)
    const auto = pickMode.autoDone !== false;
    if (auto && pickMode.selected.length >= max) {
      setTimeout(() => finishPick(), 120);
    }
  }

  function togglePickCharacter(id, name) {
    togglePickItem(id, name);
  }

  /**
   * Open library for selection.
   * opts: { tab, kind, max, min, selected, title, open, autoDone, onChange, onDone, onCancel }
   * min defaults to max (exact count). Arena uses min:2 max:3.
   */
  function openPicker(opts) {
    const o = opts || {};
    const pickTab = o.tab || o.kind || 'characters';
    const tabName = pickTab === 'background' ? 'backgrounds' : pickTab;
    const max = Math.max(1, Number(o.max) || 1);
    let min = o.min != null ? Number(o.min) : max;
    if (!Number.isFinite(min) || min < 1) min = max;
    min = Math.max(1, Math.min(max, min));
    pickMode = {
      max,
      min,
      selected: (o.selected || []).map(String).filter(Boolean),
      tab: tabName,
      // Prefer explicit kind (characters) over tab alias
      kind: o.kind || tabName,
      title: o.title || (tabName === 'backgrounds' ? 'Pick background' : 'Pick character'),
      autoDone: o.autoDone !== false,
      onChange: o.onChange || null,
      onDone: o.onDone || null,
      onCancel: o.onCancel || null,
    };
    tab = tabName;
    document.querySelectorAll('.lib-tab').forEach(el => {
      el.classList.toggle('active', el.dataset.tab === tabName);
    });
    updatePickChrome();
    // Always refresh so list is current when picking
    cache = null;
    if (o.open !== false) {
      open = false; // force visual re-open
      setOpen(true);
    }
    loadLibrary();
  }

  function openCharacterPicker(opts) {
    const o = opts || {};
    openPicker(Object.assign({}, o, { tab: 'characters', kind: 'characters' }));
  }

  function openBackgroundPicker(opts) {
    const o = opts || {};
    openPicker(Object.assign({}, o, {
      tab: 'backgrounds',
      kind: 'backgrounds',
      max: 1,
      title: o.title || 'Pick background',
    }));
  }

  /** Photos (and character/background stills) for image-to-image / prompt reference */
  function openPhotoPicker(opts) {
    const o = opts || {};
    openPicker(Object.assign({}, o, {
      tab: 'photos',
      kind: 'photos',
      max: Math.max(1, Number(o.max) || 1),
      title: o.title || 'Pick photo reference',
    }));
  }

  function finishPick() {
    if (!pickMode) return;
    const max = Math.max(1, Number(pickMode.max) || 1);
    const min = Math.max(1, Math.min(max, Number(pickMode.min) || max));
    if (pickMode.selected.length < min) {
      const k = pickMode.kind || '';
      toast(
        k === 'backgrounds' || k === 'background' ? 'Pick a background first'
          : k === 'photos' || k === 'photo' ? 'Pick a photo first'
          : (min === 1 ? 'Pick a character first'
            : (min < max ? `Pick at least ${min} characters (up to ${max})` : `Pick ${min} characters`))
      );
      return;
    }
    const ids = pickMode.selected.slice();
    const onDone = pickMode.onDone;
    const kind = pickMode.kind;
    // Full item payloads (need URLs for photos/backgrounds)
    let items = [];
    if (cache) {
      let list = [];
      if (kind === 'backgrounds') list = cache.backgrounds || [];
      else if (kind === 'photos' || kind === 'photo' || kind === 'images' || kind === 'image') {
        // Allow photo + character + background stills as image refs
        list = []
          .concat(cache.photos || [])
          .concat(cache.characters || [])
          .concat(cache.backgrounds || []);
      } else if (kind === 'videos' || kind === 'video') {
        list = cache.videos || [];
      } else if (kind === 'extend' || kind === 'videos_or_spins') {
        list = []
          .concat(cache.videos || [])
          .concat(cache.characters || []);
      } else if (kind === 'cards' || kind === 'card') {
        list = cache.cards || [];
      } else {
        list = cache.characters || [];
      }
      items = ids.map(id => list.find(x => String(x.id) === String(id))).filter(Boolean)
        .map(x => ({
          kind: x.kind,
          id: x.id,
          name: x.name || x.label || x.prompt,
          url: x.url || x.primary_image_url || x.output_url || '',
          thumb: x.thumb || x.primary_image_url || x.url || '',
          primary_image_url: x.primary_image_url || x.url,
          images: x.images || [],
          spin_video_url: x.spin_video_url || x.spin || '',
          spin: x.spin_video_url || x.spin || '',
          type: x.type || x.kind,
          // Arena / Motion need outfit versions after multi-pick
          versions: x.versions || [],
          active_version_id: x.active_version_id || 'v1',
          gender: x.gender,
          prompt: x.prompt,
          level: x.level,
          xp: x.xp,
          serial: x.serial,
        }));
    }
    clearPickUi(true);
    document.querySelectorAll('.lib-tab').forEach(el => {
      el.style.opacity = '';
      el.style.pointerEvents = '';
    });
    setOpen(false);
    if (typeof onDone === 'function') {
      try { onDone(ids, items); } catch (_e) { /* ignore */ }
    }
    if (kind === 'backgrounds') toast('Background selected');
    else if (kind === 'photos') toast(items.length === 1 ? 'Photo reference set' : 'Photo references set');
    else if (kind === 'videos' || kind === 'video') toast(items.length === 1 ? 'Video selected' : `${ids.length} videos selected`);
    else if (kind === 'cards') toast('Card selected');
    else toast(ids.length === 1 ? 'Character selected' : `${ids.length} characters selected`);
  }

  function cancelPick() {
    const cancel = pickMode && pickMode.onCancel;
    clearPickUi(true);
    setOpen(false);
    if (typeof cancel === 'function') {
      try { cancel(); } catch (_e) { /* ignore */ }
    }
  }

  async function loadLibrary() {
    loading = true;
    const body = $('lib-body');
    if (body) body.innerHTML = '<p class="lib-empty">Loading your library…</p>';
    try {
      const res = await fetch('/api/my-library', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (res.status === 401) {
        if (body) body.innerHTML = '<p class="lib-empty">Log in to see your library.</p>';
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not load library');
      // Normalize stills so Photos tab never drops items with type/kind drift
      const photos = (data.photos || []).map((p) => ({
        ...p,
        kind: p.kind || 'photo',
        type: p.type || 'image',
        url: p.url || p.primary_image_url || p.output_url || p.thumb || '',
        thumb: p.thumb || p.url || p.primary_image_url || '',
      })).filter((p) => p.url);
      const characters = (data.characters || []).map((c) => ({
        ...c,
        kind: 'character',
        url: c.url || c.primary_image_url || c.thumb || '',
        thumb: c.thumb || c.url || c.primary_image_url || '',
      }));
      const videos = (data.videos || []).map((v) => {
        const url = v.url || v.output_url || '';
        const preview = v.preview_url || v.thumb || '';
        const thumb = (preview && !isProbablyVideoUrl(preview)) ? preview : '';
        return {
          ...v,
          kind: 'video',
          type: 'video',
          url,
          preview_url: preview || '',
          thumb,
          chain_id: v.chain_id || v.id || null,
        };
      }).filter((v) => v.url);
      const backgrounds = (data.backgrounds || []).map((b) => ({
        ...b,
        kind: 'background',
        url: b.url || b.primary_image_url || b.thumb || '',
        thumb: b.thumb || b.url || '',
      })).filter((b) => b.url);
      // 3D GLB roster
      let chars3d = [];
      try {
        const r3 = await fetch('/api/3d/characters', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        if (r3.ok) {
          const j3 = await r3.json();
          const raw = j3.characters || j3.roster || [];
          chars3d = raw.map((c) => ({ kind: '3d', id: c.id, name: c.name || '3D body', url: c.glb_url || c.url || '', glb_url: c.glb_url || c.url || '', thumb: c.thumb || c.preview_url || '', type: '3d' }));
        }
      } catch (_e3) {}
      const cards = (data.cards || []).map((c) => ({
        ...c,
        kind: 'card',
        url: c.url || c.thumb || c.card_art_url || '',
        thumb: c.thumb || c.url || '',
      })).filter((c) => c.url);
      cache = {
        characters,
        photos,
        videos,
        cards,
        backgrounds,
        characters3d: chars3d,
        counts: data.counts || {},
      };
      pageByTab = {};

      render();
    } catch (e) {
      if (body) body.innerHTML = `<p class="lib-empty">${escapeHtml(e.message || 'Load failed')}</p>`;
    } finally {
      loading = false;
    }
  }

  function payloadFromEl(el) {
    return {
      kind: el.dataset.kind,
      url: el.dataset.url || '',
      id: el.dataset.id || '',
      name: el.dataset.name || '',
      thumb: el.dataset.thumb || el.dataset.url || '',
      type: el.dataset.type || '',
      spin: el.dataset.spin || '',
      spin_video_url: el.dataset.spin || '',
      primary_image_url: el.dataset.url || '',
    };
  }

  function bindDrag(el) {
    el.draggable = true;
    el.addEventListener('dragstart', (e) => {
      const p = payloadFromEl(el);
      // Prefer still URL for image refs; keep video URL for extend / video drops
      const dragUrl = (p.kind === 'video')
        ? (p.url || '')
        : (p.url || p.thumb || p.primary_image_url || '');
      if (!p.url && dragUrl) p.url = dragUrl;
      if (!p.primary_image_url) p.primary_image_url = p.url || p.thumb || '';
      const raw = JSON.stringify(p);
      try {
        e.dataTransfer.setData(MIME, raw);
        e.dataTransfer.setData('text/plain', dragUrl || p.name || '');
        if (dragUrl) e.dataTransfer.setData('text/uri-list', dragUrl);
        // Helps some browsers accept the drag as a URL drop
        if (dragUrl && p.kind !== 'video' && p.kind !== '3d') {
          e.dataTransfer.setData('text/html', '<img src="' + String(dragUrl).replace(/"/g, '') + '" />');
        }
      } catch (_e) { /* IE / rare */ }
      e.dataTransfer.effectAllowed = 'copy';
      el.classList.add('dragging');
      document.body.classList.add('lib-dragging');
    });
    el.addEventListener('dragend', () => {
      el.classList.remove('dragging');
      document.body.classList.remove('lib-dragging');
    });
  }

  function pickKindMatches(itemKind) {
    if (!pickMode) return false;
    const pk = pickMode.kind || pickMode.tab || 'characters';
    if (pk === 'characters' || pk === 'character') return itemKind === 'character';
    if (pk === 'backgrounds' || pk === 'background') return itemKind === 'background';
    if (pk === 'cards' || pk === 'card') return itemKind === 'card';
    if (pk === 'photos' || pk === 'photo' || pk === 'images' || pk === 'image') {
      return itemKind === 'photo' || itemKind === 'image' || itemKind === 'background' || itemKind === 'character';
    }
    if (pk === 'videos' || pk === 'video') return itemKind === 'video';
    if (pk === 'extend' || pk === 'videos_or_spins') {
      return itemKind === 'video' || itemKind === 'character';
    }
    return false;
  }

  function itemHtml(item) {
    const kind = item.kind;
    const url = item.url || item.primary_image_url || item.output_url || '';
    const rawThumb = item.thumb || item.preview_url || item.primary_image_url || (kind === 'video' ? '' : url);
    const thumb = (rawThumb && !isProbablyVideoUrl(rawThumb)) ? rawThumb : (kind === 'video' ? '' : url);
    const name = item.name || item.label || item.prompt || kind;
    const id = item.id != null ? String(item.id) : '';
    const type = item.type || kind;
    const short = (name || '').slice(0, 48);
    const picking = pickKindMatches(kind);
    const selected = picking && pickMode.selected.indexOf(id) >= 0;
    const pickIdx = picking ? pickMode.selected.indexOf(id) : -1;
    const orderBadge = pickIdx >= 0
      ? (pickMode.max > 1 ? `T${pickIdx + 1}` : '✓')
      : '';

    let media = '';
    if (kind === 'video' || type === 'video') {
      media = thumb
        ? `<img src="${escapeHtml(thumb)}" alt="" loading="lazy" />`
        : (url
          ? `<video class="lib-vid-thumb" src="${escapeHtml(url)}" muted playsinline preload="metadata"></video>`
          : `<div class="lib-vid-ph">▶</div>`);
      if (item.is_chain && item.chain_count > 1) {
        media += `<span class="lib-badge">×${item.chain_count}</span>`;
      }
    } else if (kind === '3d') {
      media = thumb ? `<img src=\"${escapeHtml(thumb)}\" alt=\"\" loading=\"lazy\" />` : `<div class=\"lib-vid-ph\">3D</div>`;
      media += '<span class=\"lib-badge\">GLB</span>';
    } else if (kind === 'character') {
      media = `<img src="${escapeHtml(url)}" alt="" loading="lazy" />`;
      if (item.spin_video_url) media += '<span class="lib-badge">360°</span>';
      if (orderBadge) media += `<span class="lib-badge" style="left:auto;right:3px;background:#00c96b;color:#04140c">${orderBadge}</span>`;
    } else {
      media = url
        ? `<img src="${escapeHtml(url)}" alt="" loading="lazy" />`
        : `<div class="lib-vid-ph">?</div>`;
    }

    const cls = [
      'lib-item',
      picking ? 'pickable' : '',
      selected ? 'pick-selected' : '',
    ].filter(Boolean).join(' ');

    const title = picking
      ? (selected ? 'Click to deselect' : 'Click to select')
      : 'Click for full-screen · drag onto a studio drop zone';

    // Zoom control always available (same full-screen lightbox) — even while picking
    const zoomBtn = (url || (kind === 'video'))
      ? `<button type="button" class="lib-zoom-btn" data-lib-zoom="1" title="Full screen preview" aria-label="Zoom">⛶</button>`
      : '';

    return `<div class="${cls}" draggable="${picking ? 'false' : 'true'}"
      data-kind="${escapeHtml(kind)}"
      data-url="${escapeHtml(url)}"
      data-id="${escapeHtml(id)}"
      data-chain-id="${escapeHtml(String(item.chain_id || id || ''))}"
      data-name="${escapeHtml(name)}"
      data-thumb="${escapeHtml(thumb || url)}"
      data-type="${escapeHtml(type)}"
      data-spin="${escapeHtml(item.spin_video_url || '')}"
      title="${escapeHtml(title)}">
      <div class="lib-thumb">${media}${zoomBtn}</div>
      <div class="lib-meta">
        <div class="lib-name">${escapeHtml(short)}</div>
        <div class="lib-kind">${picking ? (selected ? 'Selected · ⛶ to zoom' : 'Tap to select · ⛶ zoom') : 'Click full-screen'}</div>
      </div>
    </div>`;
  }

  function sync3dTools() {
    const tools = $('lib-3d-tools');
    if (!tools) return;
    const show = tab === '3d' && !pickMode;
    tools.hidden = !show;
    tools.style.display = show ? 'flex' : 'none';
  }
  /** Stills for Photos tab / video refs: photos + character faces + backgrounds. */
  function stillsForPhotosTab() {
    const photos = cache && cache.photos ? cache.photos : [];
    const chars = cache && cache.characters ? cache.characters : [];
    const bgs = cache && cache.backgrounds ? cache.backgrounds : [];
    // On Videos page always mix stills (refs need any image). Same in photo pick mode.
    const onVideos = !!(document.getElementById('vid-ref-slots'));
    const pickStills = !!(pickMode && (
      pickMode.kind === 'photos' || pickMode.kind === 'photo'
      || pickMode.kind === 'images' || pickMode.kind === 'image'
    ));
    if (onVideos || pickStills) {
      const seen = new Set();
      const out = [];
      []
        .concat(photos)
        .concat(chars)
        .concat(bgs)
        .forEach((it) => {
          if (!it) return;
          const key = String(it.id != null ? it.id : (it.url || it.primary_image_url || ''));
          if (!key || seen.has(key)) return;
          seen.add(key);
          out.push(it);
        });
      return out;
    }
    return photos;
  }

  function ensurePagerEl() {
    let pager = $('lib-pager');
    if (pager) return pager;
    const body = $('lib-body');
    if (!body || !body.parentNode) return null;
    pager = document.createElement('div');
    pager.id = 'lib-pager';
    pager.className = 'lib-pager';
    body.insertAdjacentElement('afterend', pager);
    return pager;
  }

  function renderPager(total, page, pages) {
    const pager = ensurePagerEl();
    if (!pager) return;
    if (pages <= 1) {
      pager.innerHTML = total
        ? `<span class="lib-pager-meta">${total} item${total === 1 ? '' : 's'}</span>`
        : '';
      pager.style.display = total ? 'flex' : 'none';
      return;
    }
    const btns = [];
    for (let p = 1; p <= pages; p++) {
      btns.push(
        `<button type="button" class="lib-page-btn${p === page ? ' active' : ''}" data-lib-page="${p}">${p}</button>`
      );
    }
    pager.style.display = 'flex';
    pager.innerHTML =
      `<span class="lib-pager-meta">${total} · page ${page}/${pages}</span>` +
      `<div class="lib-page-btns">${btns.join('')}</div>`;
    pager.querySelectorAll('[data-lib-page]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const next = Number(btn.getAttribute('data-lib-page')) || 1;
        pageByTab[tab] = next;
        render();
        const body = $('lib-body');
        if (body) body.scrollTop = 0;
      });
    });
  }

  function render() {
    const body = $('lib-body');
    if (!body || !cache) return;
    sync3dTools();

    let items = [];
    if (tab === 'characters') items = cache.characters || [];
    else if (tab === 'cards') items = cache.cards || [];
    else if (tab === 'photos') items = stillsForPhotosTab();
    else if (tab === 'videos') items = groupVideosByChain(cache.videos || []);
    else if (tab === 'backgrounds') items = cache.backgrounds || [];
    else if (tab === '3d') items = cache.characters3d || [];

    const total = items.length;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    let page = Math.max(1, Number(pageByTab[tab]) || 1);
    if (page > pages) page = pages;
    pageByTab[tab] = page;
    const start = (page - 1) * PAGE_SIZE;
    const pageItems = items.slice(start, start + PAGE_SIZE);

    if (!total) {
      const hints = {
        characters: pickMode
          ? 'No characters yet — build one from extract (50-credit pack) or Character studio, then come back.'
          : 'No characters yet — build some in Character studio.',
        cards: 'No cards yet — make one in Card Studio and tap Save card.',
        photos: pickMode || document.getElementById('vid-ref-slots')
          ? 'No stills yet — generate Photos, save Characters, or Motion backgrounds, then pick here.'
          : 'No photos yet — generate in Studio or save from Motion.',
        videos: 'No videos yet — generate in Studio, Arena, or Motion overlay.',
        backgrounds: 'No backgrounds yet — use “Fill shadows → Arena still” on Motion.',
        '3d': 'No 3D bodies yet — generate on /3d (Meshy) or upload a .glb here.',
      };
      body.innerHTML = `<p class="lib-empty">${hints[tab] || 'Nothing here yet.'}</p>`;
      renderPager(0, 1, 1);
      if (pickMode) updatePickChrome();
      return;
    }

    body.innerHTML = pageItems.map(itemHtml).join('');
    renderPager(total, page, pages);
    hydrateVideoThumbs(body);
    if (!pickMode) {
      body.querySelectorAll('.lib-item').forEach(bindDrag);
    }

    // Full-screen zoom (same lightbox everywhere — Arena / Motion pick included)
    body.querySelectorAll('[data-lib-zoom]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const el = btn.closest('.lib-item');
        if (el) openItemPreview(el);
      });
    });

    body.querySelectorAll('.lib-item[data-kind="character"]').forEach(el => {
      if (pickMode && (pickMode.kind === 'characters' || pickMode.tab === 'characters' || !pickMode.kind || pickMode.kind === 'character')) {
        el.addEventListener('click', (e) => {
          if (e.target.closest('[data-lib-zoom]')) return;
          e.preventDefault();
          e.stopPropagation();
          togglePickItem(el.dataset.id, el.dataset.name);
        });
      } else if (!pickMode) {
        el.addEventListener('click', async (e) => {
          if (e.target.closest('[data-lib-zoom]')) return;
          e.preventDefault();
          e.stopPropagation();
          // On Videos/Photos: one tap → fill next ref box. ⛶ = blow-up with actions.
          try {
            if (await tryDropStillIntoPageRefs(el)) return;
          } catch (_e) { /* fall through to preview */ }
          openItemPreview(el);
        });
        el.addEventListener('dblclick', () => {
          const id = el.dataset.id;
          if (id && global.CharProfile && typeof CharProfile.open === 'function') {
            if (cache.characters) {
              CharProfile.setChars(cache.characters.map(c => ({
                id: c.id,
                name: c.name,
                primary_image_url: c.url || c.primary_image_url,
                images: c.images || [],
                spin_video_url: c.spin_video_url,
                gender: c.gender,
                prompt: c.prompt,
                versions: c.versions,
                active_version_id: c.active_version_id,
              })), true);
            }
            CharProfile.open(Number(id) || id);
          }
        });
      }
    });

    body.querySelectorAll('.lib-item[data-kind="photo"], .lib-item[data-kind="image"]').forEach(el => {
      el.addEventListener('click', async (e) => {
        if (e.target.closest('[data-lib-zoom]')) return;
        e.preventDefault();
        e.stopPropagation();
        if (pickMode && (pickMode.kind === 'photos' || pickMode.tab === 'photos' || pickMode.kind === 'photo' || pickMode.kind === 'images')) {
          togglePickItem(el.dataset.id, el.dataset.name);
          return;
        }
        if (pickMode) return;
        try {
          if (await tryDropStillIntoPageRefs(el)) return;
        } catch (_e) { /* fall through */ }
        openItemPreview(el);
      });
    });

    body.querySelectorAll('.lib-item[data-kind="video"]').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('[data-lib-zoom]')) return;
        e.preventDefault();
        e.stopPropagation();
        if (pickMode && (pickMode.kind === 'extend' || pickMode.kind === 'videos' || pickMode.kind === 'video' || pickMode.kind === 'videos_or_spins')) {
          togglePickItem(el.dataset.id, el.dataset.name);
          return;
        }
        if (pickMode) return;
        // Videos: blow-up → Extend / Save / Close
        openItemPreview(el);
      });
    });

    body.querySelectorAll('.lib-item[data-kind="background"]').forEach(el => {
      el.addEventListener('click', async (e) => {
        if (e.target.closest('[data-lib-zoom]')) return;
        e.preventDefault();
        e.stopPropagation();
        if (pickMode && (pickMode.kind === 'backgrounds' || pickMode.tab === 'backgrounds' || pickMode.kind === 'photos')) {
          togglePickItem(el.dataset.id, el.dataset.name);
          return;
        }
        if (pickMode) return;
        try {
          if (await tryDropStillIntoPageRefs(el)) return;
        } catch (_e) { /* fall through */ }
        openItemPreview(el);
      });
    });

    body.querySelectorAll('.lib-item[data-kind="3d"]').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('[data-lib-zoom]')) return;
        e.preventDefault(); e.stopPropagation();
        if (pickMode && (pickMode.kind === '3d' || pickMode.tab === '3d')) { togglePickItem(el.dataset.id, el.dataset.name); return; }
        if (pickMode) return;
        const glb = el.dataset.glb || el.dataset.url || '';
        if (glb) { window.open('/motion-lab/colosseum-stage.html?glb=' + encodeURIComponent(glb), '_blank', 'noopener'); toast('Opening on 3D stage…'); }
        else toast('No GLB URL');
      });
    });

    body.querySelectorAll('.lib-item[data-kind="card"]').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('[data-lib-zoom]')) return;
        e.preventDefault();
        e.stopPropagation();
        if (pickMode && (pickMode.kind === 'cards' || pickMode.tab === 'cards')) { togglePickItem(el.dataset.id, el.dataset.name); return; }
        if (pickMode) return;
        // Battle Cards: tapping one of your cards picks that fighter.
        if (typeof global.percfectPickCard === 'function') {
          setOpen(false);
          global.percfectPickCard(payloadFromEl(el));
          return;
        }
        openItemPreview(el);
      });
    });
    if (pickMode) updatePickChrome();
  }

  /** Wire a drop zone to accept library drags. */
  function registerDropZone(el, opts) {
    if (!el) return;
    // Avoid stacking duplicate listeners when page + autoWire both register
    if (el._percfectLibDropBound) return;
    el._percfectLibDropBound = true;
    const cfg = opts || {};
    el.classList.add('lib-drop-zone');

    el.addEventListener('dragover', (e) => {
      if (![...e.dataTransfer.types].includes(MIME) &&
          ![...e.dataTransfer.types].includes('text/uri-list') &&
          ![...e.dataTransfer.types].includes('text/plain')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      el.classList.add('lib-drop-hover');
    });
    el.addEventListener('dragleave', () => el.classList.remove('lib-drop-hover'));
    el.addEventListener('drop', async (e) => {
      el.classList.remove('lib-drop-hover');
      let p = null;
      try {
        const raw = e.dataTransfer.getData(MIME);
        if (raw) p = JSON.parse(raw);
      } catch (_e) { /* ignore */ }
      if (!p) {
        const url = (e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain') || '')
          .trim().split('\n')[0].trim();
        if (url && /^https?:\/\//i.test(url)) {
          const kind = isProbablyVideoUrl(url) ? 'video' : 'image';
          p = { kind, type: kind, url, primary_image_url: url, name: 'Dropped media' };
        }
      }
      if (!p) return;
      e.preventDefault();
      e.stopPropagation();
      if (!p.url) p.url = p.thumb || p.primary_image_url || '';
      if (!p.primary_image_url) p.primary_image_url = p.url || p.thumb || '';

      // Kind filter
      const accept = cfg.accept; // 'character' | 'image' | 'video' | 'background' | array
      if (accept) {
        const list = Array.isArray(accept) ? accept : [accept];
        const k = (p.kind || p.type || '').toLowerCase();
        const ok = list.some(a =>
          a === k ||
          (a === 'image' && (k === 'photo' || k === 'background' || k === 'image' || k === 'character')) ||
          (a === 'photo' && (k === 'photo' || k === 'image' || k === 'background' || k === 'character')) ||
          (a === 'background' && (k === 'background' || k === 'photo' || k === 'image')) ||
          (a === 'video' && (k === 'video' || k === 'character')) ||
          (a === 'character' && k === 'character')
        );
        if (!ok) {
          toast('That item does not drop here');
          return;
        }
      }

      if (typeof cfg.onDrop === 'function') {
        try {
          await cfg.onDrop(p, e);
          toast('Added from your library');
        } catch (err) {
          toast(err.message || 'Drop failed');
        }
      }

      // Global custom event for page-level listeners
      document.dispatchEvent(new CustomEvent('percfect-library-drop', {
        detail: { payload: p, zone: el, originalEvent: e },
      }));
    });
  }

  function init() {
    const fab = $('user-lib-fab');
    const close = $('user-lib-close');
    const scrim = $('user-lib-scrim');
    const refresh = $('user-lib-refresh');
    if (!fab) return; // not logged in / partial missing

    // One tap = quick panel (sort tabs, drag onto refs/prompt). Two taps = full library page.
    let fabTimer = null;
    fab.addEventListener('click', () => {
      if (fabTimer) {
        clearTimeout(fabTimer);
        fabTimer = null;
        window.location.href = '/library';
        return;
      }
      fabTimer = setTimeout(() => {
        fabTimer = null;
        // FAB opens normal library (exit pick mode if active)
        if (pickMode) clearPickUi(true);
        toggle();
      }, 280);
    });
    if (close) close.addEventListener('click', () => setOpen(false));
    if (scrim) scrim.addEventListener('click', () => setOpen(false));
    if (refresh) refresh.addEventListener('click', () => { cache = null; loadLibrary(); });

    const pickDone = $('lib-pick-done');
    const pickCancel = $('lib-pick-cancel');
    if (pickDone) pickDone.addEventListener('click', finishPick);
    if (pickCancel) pickCancel.addEventListener('click', cancelPick);

    document.querySelectorAll('.lib-tab').forEach(el => {
      el.addEventListener('click', () => setTab(el.dataset.tab));
    });
    if (onlyTab) {
      document.querySelectorAll('.lib-tab').forEach(el => {
        el.hidden = el.dataset.tab !== onlyTab;
        el.classList.toggle('active', el.dataset.tab === onlyTab);
      });
    }
    const uploadBtn = $('lib-3d-upload');
    const fileInput = $('lib-3d-file');
    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', async () => {
        const f = fileInput.files && fileInput.files[0];
        fileInput.value = '';
        if (!f) return;
        if (!/\.glb$/i.test(f.name || '') && f.type !== 'model/gltf-binary') { toast('Upload a .glb file'); return; }
        toast('Uploading GLB…');
        try {
          const fd = new FormData();
          fd.append('glb', f);
          fd.append('name', (f.name || 'Body').replace(/\.glb$/i, ''));
          const res = await fetch('/api/3d/upload-character', { method: 'POST', body: fd, credentials: 'same-origin' });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || 'Upload failed');
          toast('3D body saved to library'); cache = null; await loadLibrary(); setTab('3d');
        } catch (err) { toast(err.message || 'Upload failed'); }
      });
    }


    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && open) setOpen(false);
    });

    // Auto-register common drop zones when present
    autoWirePageZones();
  }

  function autoWirePageZones() {
    // Studio photo reference (character / photo / background)
    registerDropZone($('img-drop-zone'), {
      accept: ['image', 'photo', 'background', 'character'],
      onDrop: async (p) => {
        if (typeof global.applyLibraryImage === 'function') {
          await global.applyLibraryImage(p);
          return;
        }
        const urlField = document.getElementById('img-image-url') || document.getElementById('img-url');
        if (urlField && p.url) {
          urlField.value = p.url;
          urlField.dispatchEvent(new Event('change', { bubbles: true }));
        }
      },
    });
    // Photos page: 3 ref slots — drag from corner library
    const imgRefGrid = $('img-ref-slots');
    if (imgRefGrid) {
      const dropIntoPhotoRef = async (p, preferredSlot) => {
        const url = p.url || p.thumb || p.primary_image_url || '';
        if (!url) throw new Error('No image on that library item');
        if (typeof global.photoAddUrl === 'function') {
          global.photoAddUrl(url, preferredSlot != null ? preferredSlot : null);
          return;
        }
        if (typeof global.applyLibraryImage === 'function') {
          await global.applyLibraryImage(p);
        }
      };
      registerDropZone(imgRefGrid, {
        accept: ['image', 'photo', 'character', 'background'],
        onDrop: async (p) => { await dropIntoPhotoRef(p, null); },
      });
      for (let si = 0; si < 3; si++) {
        const cell = $('img-ref-' + si);
        if (!cell) continue;
        registerDropZone(cell, {
          accept: ['image', 'photo', 'character', 'background'],
          onDrop: async (p) => { await dropIntoPhotoRef(p, si); },
        });
      }
    }

    // Studio video “animate an image” start frame
    registerDropZone($('drop-zone'), {
      accept: ['image', 'photo', 'character', 'background'],
      onDrop: async (p) => {
        if (typeof global.applyLibraryVideoImage === 'function') {
          await global.applyLibraryVideoImage(p);
          return;
        }
        if (typeof global.applyLibraryImage === 'function') {
          await global.applyLibraryImage(p);
          return;
        }
      },
    });

    // Videos page: 4 ref slots (+ grid) — library drag from sidebar
    const vidRefGrid = $('vid-ref-slots') || document.querySelector('[data-lib-drop="image"]#vid-ref-slots');
    if (vidRefGrid) {
      const dropIntoVidRef = async (p, preferredSlot) => {
        if (typeof global.applyLibraryVideoImage === 'function') {
          // Prefer slot-aware helper when present
          if (typeof global.vidAddUrl === 'function') {
            const url = p.url || p.thumb || p.primary_image_url || '';
            if (!url) throw new Error('No image on that library item');
            global.vidAddUrl(url, preferredSlot != null ? preferredSlot : null);
            if (typeof global.ensureAnimatePrompt === 'function') global.ensureAnimatePrompt();
            return;
          }
          await global.applyLibraryVideoImage(p);
          return;
        }
        if (typeof global.applyLibraryImage === 'function') {
          await global.applyLibraryImage(p);
        }
      };
      registerDropZone(vidRefGrid, {
        accept: ['image', 'photo', 'character', 'background'],
        onDrop: async (p) => { await dropIntoVidRef(p, null); },
      });
      for (let si = 0; si < 4; si++) {
        const cell = $('vid-ref-' + si);
        if (!cell) continue;
        registerDropZone(cell, {
          accept: ['image', 'photo', 'character', 'background'],
          onDrop: async (p) => { await dropIntoVidRef(p, si); },
        });
      }
    }

    // Studio / any page: video extend source
    registerDropZone($('extend-drop-zone') || document.querySelector('[data-lib-drop="video"]'), {
      accept: ['video', 'character'],
      onDrop: async (p) => {
        if (typeof global.applyLibraryExtend === 'function') {
          await global.applyLibraryExtend(p);
          return;
        }
        if (typeof global.applyLibraryVideo === 'function') {
          await global.applyLibraryVideo(p);
          return;
        }
        const url = (p.kind === 'character' ? (p.spin || '') : '') || p.url;
        const urlField = document.getElementById('extend-video-url') || document.getElementById('vid-url');
        if (urlField && url) {
          urlField.value = url;
          urlField.dispatchEvent(new Event('change', { bubbles: true }));
        }
      },
    });

    registerDropZone($('vid-upload-zone'), {
      accept: ['video', 'character'],
      onDrop: async (p) => {
        if (typeof global.applyLibraryVideo === 'function') {
          await global.applyLibraryVideo(p);
          return;
        }
        const urlField = document.getElementById('vid-url');
        if (urlField && p.url) {
          urlField.value = p.spin || p.url;
          urlField.dispatchEvent(new Event('change', { bubbles: true }));
        }
      },
    });

    // Arena background
    registerDropZone($('bg-upload-wrap') || document.querySelector('[data-lib-drop="background"]'), {
      accept: ['background', 'image', 'photo'],
      onDrop: async (p) => {
        if (typeof global.applyLibraryBackground === 'function') {
          await global.applyLibraryBackground(p);
          return;
        }
        // Default: fetch as file into #bg-file
        if (!p.url) return;
        const res = await fetch(p.url);
        const blob = await res.blob();
        const file = new File([blob], 'library-bg.jpg', { type: blob.type || 'image/jpeg' });
        if (typeof global.bgFile !== 'undefined') {
          // arena uses let bgFile
        }
        const input = document.getElementById('bg-file');
        if (input) {
          const dt = new DataTransfer();
          dt.items.add(file);
          input.files = dt.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        if (typeof global.setBgMode === 'function') global.setBgMode('upload');
        if (typeof global.bgFilePicked === 'function') global.bgFilePicked(input);
        // Arena: set bgFile global if present
        try {
          if (typeof bgFile !== 'undefined') {
            // eslint-disable-next-line no-global-assign
            window.bgFile = file;
          }
        } catch (_e) { /* ignore */ }
        const n = document.getElementById('bg-file-name');
        if (n) { n.textContent = '✓ ' + (p.name || 'Library background'); n.style.display = 'block'; }
      },
    });

    // Motion performance upload (percfectmotion.html also self-registers; this is the backup wire)
    registerDropZone(
      $('motion-upload-zone') || document.querySelector('[data-lib-drop="motion-video"]'),
      {
        accept: ['video', 'character'],
        onDrop: async (p) => {
          if (typeof global.applyLibraryMotionVideo === 'function') {
            await global.applyLibraryMotionVideo(p);
            return;
          }
          if (typeof global.applyLibraryVideo === 'function') {
            await global.applyLibraryVideo(p);
            return;
          }
          if (typeof global.onMotionFilePicked === 'function' && p && p.url) {
            const res = await fetch(p.url);
            const blob = await res.blob();
            const file = new File([blob], 'library-video.mp4', { type: blob.type || 'video/mp4' });
            global.onMotionFilePicked(file);
          }
        },
      }
    );

    // Character builder reference photo (PERCFECT CHARACTERS)
    const charDrop =
      document.querySelector('[data-lib-drop="character-ref"]') ||
      $('drop') ||
      $('upload-zone');
    registerDropZone(charDrop, {
      accept: ['character', 'image', 'photo', 'background'],
      onDrop: async (p) => {
        if (typeof global.applyLibraryCharacterRef === 'function') {
          await global.applyLibraryCharacterRef(p);
          return;
        }
        if (typeof global.applyLibraryImage === 'function') {
          await global.applyLibraryImage(p);
          return;
        }
        const url = p.url || p.thumb || p.primary_image_url || '';
        if (!url) return;
        const urlField = document.getElementById('char-image-url');
        if (urlField) {
          urlField.value = url;
          urlField.dispatchEvent(new Event('change', { bubbles: true }));
        }
        if (typeof global.loadImageUrl === 'function') {
          global.loadImageUrl(url);
          return;
        }
        try {
          const res = await fetch(url);
          const blob = await res.blob();
          const file = new File([blob], 'library-ref.jpg', { type: blob.type || 'image/jpeg' });
          if (typeof global.loadFile === 'function') global.loadFile(file);
        } catch (_e) { /* ignore */ }
      },
    });
  }

  /** Open library on a specific tab (e.g. 'photos' from Videos ref P-button). */
  function openOnTab(tabName) {
    const name = tabName || 'photos';
    // Always exit pick mode — stuck "extend" pick was blocking the Photos tab on Videos
    if (pickMode) {
      try { clearPickUi(true); } catch (_e) { pickMode = null; }
    }
    tab = name;
    document.querySelectorAll('.lib-tab').forEach((el) => {
      el.classList.toggle('active', el.dataset.tab === name);
      el.style.opacity = '';
      el.style.pointerEvents = '';
    });
    setOpen(true);
    // Fresh load so Videos page always sees current photos (not a stale empty cache)
    cache = null;
    loadLibrary();
  }

  global.PercfectLibrary = {
    open: () => setOpen(true),
    openOnTab,
    close: () => setOpen(false),
    toggle,
    reload: () => { cache = null; return loadLibrary(); },
    registerDropZone,
    openPicker,
    openCharacterPicker,
    openBackgroundPicker,
    openPhotoPicker,
    open3dPicker: (opts) => openPicker(Object.assign({}, opts || {}, { tab: '3d', kind: '3d', max: 1, title: (opts && opts.title) || 'Pick 3D body' })),
    openMediaLightbox,
    isPickMode: () => !!pickMode,
    MIME,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
