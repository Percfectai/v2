/* Shared character roster cards + profile modal (builder, arena, motion). */
(function () {
  const POSE = ['Front', 'Left side', 'Right side', 'Back'];

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  }

  window.openLightbox = function (src) {
    if (!src) return;
    const o = document.createElement('div');
    o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:9999;display:flex;align-items:center;justify-content:center;cursor:zoom-out';
    const img = document.createElement('img');
    img.src = src;
    img.style.cssText = 'max-width:92vw;max-height:92vh;border-radius:10px;box-shadow:0 0 50px rgba(0,0,0,.7)';
    o.appendChild(img);
    o.onclick = () => o.remove();
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { o.remove(); document.removeEventListener('keydown', esc); }
    });
    document.body.appendChild(o);
  };

  const CharProfile = {
    chars: {},
    canDownload: false,
    isAdmin: false,
    profileId: null,
    profileSlot: 0,
    profileView: 'spin',
    profileGender: null,
    modal: null,
    opts: {},
    celebrateMode: false,
    celebrateDownloadUrl: '',
    celebratePackCharged: 0,
    _rosterHoverId: null,
    _rosterHoverPlayer: null,
    _pickerClickTimer: null,

    init(options) {
      this.opts = options || {};
      if (this.opts.isAdmin != null) this.isAdmin = !!this.opts.isAdmin;
      else if (typeof global.PERCFECT_IS_ADMIN !== 'undefined') this.isAdmin = !!global.PERCFECT_IS_ADMIN;
      this._bindRosterHoverTracking();
      const el = $('profileModal');
      if (el && !el._cpInit) {
        el._cpInit = true;
        el.addEventListener('hidden.bs.modal', () => {
          const v = $('profile-hero-spin');
          if (v) { v.pause(); v.removeAttribute('src'); v.style.display = 'none'; }
          this.profileId = null;
          this.cancelNameEdit(true);
          this.clearCelebrateMode();
        });
      }
      const hero = $('profile-hero');
      if (hero && !hero._cpHover) {
        hero._cpHover = true;
        hero.addEventListener('mouseenter', () => this.heroHoverSpin(true));
        hero.addEventListener('mouseleave', () => this.heroHoverSpin(false));
      }
    },

    charById(id) {
      return this.chars[id] || this.chars[String(id)] || null;
    },

    setChars(chars, canDownload) {
      this.chars = {};
      (chars || []).forEach(c => {
        this.chars[c.id] = c;
        this.chars[String(c.id)] = c;
      });
      this.canDownload = !!canDownload;
    },

    shots(c) {
      // Only URL strings — ignore embedded version meta objects if any leak through
      const imgs = (c.images || []).filter((x) => typeof x === 'string' && x);
      if (imgs.length) return imgs;
      return c.primary_image_url ? [c.primary_image_url] : [];
    },

    dlBtn(c) {
      return this.canDownload
        ? `<a class="rbtn" href="/studios/percfectcharacter/download/${c.id}" onclick="event.stopPropagation()">↓ Download</a>`
        : `<a class="rbtn locked" href="/buy-credits" title="Buy credits to unlock" onclick="event.stopPropagation()">🔒 Download</a>`;
    },

    profileErr(msg) {
      const e = $('profile-err');
      if (!e) return;
      if (msg) { e.textContent = msg; e.style.display = 'block'; }
      else { e.textContent = ''; e.style.display = 'none'; }
    },

    updateShotLabel() {
      const el = $('profile-shot-label');
      if (el) el.textContent = '· ' + (POSE[this.profileSlot] || ('Angle ' + (this.profileSlot + 1)));
    },

    setProfileGenderUI(g) {
      this.profileGender = g;
      ['profile-gender-male', 'profile-celebrate-gender-male'].forEach(id => {
        const el = $(id);
        if (el) el.classList.toggle('active', g === 'male');
      });
      ['profile-gender-female', 'profile-celebrate-gender-female'].forEach(id => {
        const el = $(id);
        if (el) el.classList.toggle('active', g === 'female');
      });
      ['profile-gender-other', 'profile-celebrate-gender-other'].forEach(id => {
        const el = $(id);
        if (el) el.classList.toggle('active', g === 'other');
      });
    },

    setProfileGender(g) {
      this.setProfileGenderUI(g);
      this.saveGender();
    },

    async saveGender() {
      const id = this.profileId;
      if (!id || !this.profileGender) return;
      const fd = new FormData();
      fd.append('character_id', id);
      fd.append('gender', this.profileGender);
      try {
        const res = await fetch('/studios/percfectcharacter/edit', { method: 'POST', body: fd });
        const data = await res.json();
        if (res.ok && data.character) {
          this.chars[id] = data.character;
          $('profile-meta').textContent = this.metaLine(data.character);
        }
      } catch (e) { /* silent */ }
    },

    metaLine(c) {
      return [c.gender, c.spin_video_url ? '360° spin ready' : 'No spin yet'].filter(Boolean).join(' · ');
    },

    toggleNameEdit() {
      const display = $('profile-name-display');
      const input = $('profile-name-input');
      const editBtn = $('profile-name-edit-btn');
      const saveBtn = $('profile-name-save');
      const cancelBtn = $('profile-name-cancel');
      if (!input) return;
      // Always open editor (don't gate on computed style quirks)
      const cur = (display && display.textContent) || (this.charById(this.profileId) || {}).name || '';
      input.value = cur === 'Unnamed' ? '' : cur;
      if (display) display.style.display = 'none';
      if (editBtn) editBtn.style.display = 'none';
      input.style.display = 'block';
      if (saveBtn) saveBtn.style.display = 'inline-block';
      if (cancelBtn) cancelBtn.style.display = 'inline-block';
      try { input.focus(); input.select(); } catch (_e) { /* ignore */ }
    },

    cancelNameEdit(silent) {
      const c = this.charById(this.profileId);
      const display = $('profile-name-display');
      const input = $('profile-name-input');
      const editBtn = $('profile-name-edit-btn');
      const saveBtn = $('profile-name-save');
      const cancelBtn = $('profile-name-cancel');
      if (display) {
        display.style.display = '';
        if (c) display.textContent = c.name || 'Unnamed';
      }
      if (input) input.style.display = 'none';
      if (editBtn) editBtn.style.display = '';
      if (saveBtn) saveBtn.style.display = 'none';
      if (cancelBtn) cancelBtn.style.display = 'none';
      if (!silent) this.profileErr('');
    },

    versionTier() {
      // Full outfit rebuild on this card (10 credits)
      return 'full';
    },

    versionCost() {
      return 10; // new outfit on same player card
    },

    splitCost() {
      return 30; // separate player card + own 360
    },

    syncVersionBtn() {
      const btn = $('profile-accessories-btn');
      if (!btn || btn.disabled) return;
      btn.textContent = `✨ Build outfit · same card (${this.versionCost()} credits)`;
    },

    renderSideShots(c, shots) {
      $('profile-shots').innerHTML = shots.map((u, i) => `
        <button type="button" class="profile-shot${this.profileView === 'shot' && i === this.profileSlot ? ' active' : ''}" title="${POSE[i] || ''}"
          onclick="CharProfile.pickShot(${i})">
          <img src="${u}" alt="${POSE[i] || ''}">
        </button>`).join('') || '<p style="color:var(--text-muted);font-size:.75rem;padding:.25rem">No angles</p>';
      const spinThumb = $('profile-spin-thumb');
      if (spinThumb) {
        const showThumb = c.spin_video_url && this.profileView === 'shot';
        spinThumb.style.display = showThumb ? '' : 'none';
        spinThumb.classList.toggle('active', false);
      }
    },

    showHeroSpin(c) {
      const heroImg = $('profile-hero-img');
      const heroSpin = $('profile-hero-spin');
      const heroPh = $('profile-hero-ph');
      const shotPanel = $('profile-shot-panel');
      heroImg.style.display = 'none';
      if (shotPanel) shotPanel.style.display = 'none';
      if (c.spin_video_url) {
        heroPh.style.display = 'none';
        heroSpin.src = c.spin_video_url;
        heroSpin.style.display = 'block';
        heroSpin.play().catch(() => {});
        this._bindSpinDrag(heroSpin, c);
        const spinThumb = $('profile-spin-thumb');
        if (spinThumb) this._bindSpinDrag(spinThumb, c);
      } else {
        heroSpin.pause();
        heroSpin.removeAttribute('src');
        heroSpin.style.display = 'none';
        heroSpin.draggable = false;
        heroPh.style.display = '';
        heroPh.textContent = 'No 360° spin yet — create one below.';
      }
    },

    showHeroShot(c, shots) {
      const url = shots[this.profileSlot];
      const heroImg = $('profile-hero-img');
      const heroSpin = $('profile-hero-spin');
      const heroPh = $('profile-hero-ph');
      const shotPanel = $('profile-shot-panel');
      heroSpin.pause();
      heroSpin.style.display = 'none';
      heroPh.style.display = 'none';
      if (url) {
        heroImg.src = url;
        heroImg.alt = c.name || 'Character';
        heroImg.style.display = 'block';
      } else {
        heroImg.style.display = 'none';
      }
      if (shotPanel) shotPanel.style.display = '';
      this.updateShotLabel();
    },

    viewSpin() {
      const c = this.chars[this.profileId];
      if (!c) return;
      this.profileView = 'spin';
      this.profileErr('');
      $('profile-shot-fix').value = '';
      this.showHeroSpin(c);
      this.renderSideShots(c, this.shots(c));
    },

    pickShot(i) {
      const c = this.chars[this.profileId];
      if (!c) return;
      const shots = this.shots(c);
      if (!shots[i]) return;
      this.profileView = 'shot';
      this.profileSlot = i;
      this.profileErr('');
      this.showHeroShot(c, shots);
      this.renderSideShots(c, shots);
    },

    clearCelebrateMode() {
      this.celebrateMode = false;
      this.celebrateDownloadUrl = '';
      this.celebratePackCharged = 0;
      const root = document.querySelector('#profileModal .profile-modal');
      if (root) root.classList.remove('profile-celebrate');
      const bar = $('profile-celebrate-bar');
      if (bar) bar.style.display = 'none';
      const descIn = $('profile-desc-input');
      if (descIn) descIn.style.display = 'none';
      const v = $('profile-hero-spin');
      if (v) v.setAttribute('controls', '');
    },

    applyCelebrateMode() {
      const c = this.chars[this.profileId];
      if (!c) return;
      const root = document.querySelector('#profileModal .profile-modal');
      if (root) root.classList.add('profile-celebrate');

      this.profileView = 'spin';
      this.profileErr('');
      this.showHeroSpin(c);
      const shots = this.shots(c);
      this.renderSideShots(c, shots);

      const v = $('profile-hero-spin');
      if (v) {
        v.removeAttribute('controls');
        v.loop = true;
        v.muted = true;
        v.play().catch(() => {});
      }

      const nameIn = $('profile-name-input');
      const display = $('profile-name-display');
      if (nameIn) {
        const n = (c.name || '').trim();
        nameIn.value = (n && n !== 'Unnamed Character') ? n : '';
        nameIn.style.display = '';
      }
      if (display) display.style.display = 'none';
      const editBtn = $('profile-name-edit-btn');
      if (editBtn) editBtn.style.display = 'none';

      const descIn = $('profile-desc-input');
      const desc = $('profile-desc');
      if (descIn) {
        descIn.value = (c.prompt || '').trim();
        descIn.style.display = '';
      }
      if (desc) desc.style.display = 'none';

      const pill = $('profile-celebrate-pill');
      if (pill && this.celebratePackCharged) {
        pill.textContent = `✓ Profile complete — ${this.celebratePackCharged} credits charged`;
      }
      const bar = $('profile-celebrate-bar');
      if (bar) bar.style.display = '';
      const dl = $('profile-celebrate-dl');
      if (dl && this.celebrateDownloadUrl) {
        dl.href = this.celebrateDownloadUrl;
        dl.style.display = '';
      } else if (dl) {
        dl.style.display = 'none';
      }

      setTimeout(() => { if (nameIn) nameIn.focus(); }, 300);
    },

    async saveCelebrate() {
      const id = this.profileId;
      if (!id) return;
      const name = ($('profile-name-input')?.value || '').trim();
      const prompt = ($('profile-desc-input')?.value || '').trim();
      if (!name) {
        this.profileErr('Enter a name for your character.');
        return;
      }
      this.profileErr('');
      const fd = new FormData();
      fd.append('character_id', id);
      fd.append('name', name);
      fd.append('prompt', prompt);
      if (this.profileGender) fd.append('gender', this.profileGender);
      try {
        const res = await fetch('/studios/percfectcharacter/edit', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        });
        let data = {};
        try { data = await res.json(); } catch (_e) { /* non-json */ }
        if (!res.ok) {
          this.profileErr(data.error || data.detail || 'Save failed.');
          return;
        }
        if (data.character) this._storeChar(data.character);
        this.clearCelebrateMode();
        if (this.modal) this.modal.hide();
        if (this.opts.onReload) await this.opts.onReload();
      } catch (e) {
        this.profileErr(e.message || 'Network error — please try again.');
      }
    },

    open(id, openOpts) {
      openOpts = openOpts || {};
      this.celebrateMode = !!openOpts.celebrate;
      this.celebrateDownloadUrl = openOpts.downloadUrl || '';
      this.celebratePackCharged = openOpts.packCharged || 0;
      const c = this.charById(id);
      if (!c) return;
      this.profileId = c.id != null ? c.id : id;
      this.profileSlot = 0;
      this.profileErr('');
      this.cancelNameEdit(true);

      const shots = this.shots(c);
      if ($('profile-name-display')) $('profile-name-display').textContent = c.name || 'Unnamed';
      if ($('profile-name-input')) $('profile-name-input').value = c.name || '';
      $('profile-meta').textContent = this.metaLine(c);
      // Hide internal xAI engine prompts on roster/profile
      let desc = (c.prompt || '').trim();
      if (desc && /transform the character|using the reference|plain white background|3d-style illustration|character select render/i.test(desc)) {
        desc = '';
      }
      if (desc.length > 220) desc = desc.slice(0, 217) + '…';
      const descEl = $('profile-desc');
      descEl.textContent = desc || 'No description saved for this character yet.';
      descEl.classList.toggle('empty', !desc);
      if ($('profile-accessories-input')) $('profile-accessories-input').value = '';
      if ($('profile-adjust-input')) $('profile-adjust-input').value = '';
      if ($('profile-shot-fix')) $('profile-shot-fix').value = '';

      const g = (c.gender === 'female' || c.gender === 'male' || c.gender === 'other')
        ? c.gender
        : null;
      this.setProfileGenderUI(g);

      if (c.spin_video_url) {
        this.profileView = 'spin';
        this.showHeroSpin(c);
      } else if (shots.length) {
        this.profileView = 'shot';
        this.showHeroShot(c, shots);
      } else {
        this.profileView = 'spin';
        this.showHeroSpin(c);
      }
      this.renderSideShots(c, shots);
      this.renderVersions(c);
      this.renderProfileActions(c);
      this.renderShopPanel(c);
      this.syncVersionBtn();

      if (!this.modal) this.modal = new bootstrap.Modal($('profileModal'));
      if (!this.celebrateMode) this.clearCelebrateMode();
      this.modal.show();
      if (this.celebrateMode) {
        requestAnimationFrame(() => this.applyCelebrateMode());
      }
    },

    renderShopPanel(c) {
      const panel = $('profile-shop-panel');
      if (!panel) return;
      const show = !!(this.isAdmin && c && c.primary_image_url);
      panel.style.display = show ? '' : 'none';
    },

    async listInShop() {
      if (!this.isAdmin) {
        this.profileErr('Only admins can list premade characters.');
        return;
      }
      const id = this.profileId;
      if (!id) return;
      const priceEl = $('profile-shop-price');
      const blurbEl = $('profile-shop-blurb');
      const btn = $('profile-shop-btn');
      let price = parseInt(priceEl && priceEl.value, 10);
      if (!Number.isFinite(price) || price < 1) price = 30;
      const blurb = (blurbEl && blurbEl.value || '').trim();
      this.profileErr('');
      if (btn) { btn.disabled = true; btn.textContent = 'Listing…'; }
      try {
        const res = await fetch('/studios/character-shop/admin/publish', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            character_id: id,
            price_credits: price,
            blurb,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.profileErr(data.error || 'Could not list in shop.');
          return;
        }
        const meta = $('profile-meta');
        if (meta) {
          meta.textContent = (meta.textContent || '') +
            ` · listed in shop (${data.listing && data.listing.price_credits ? data.listing.price_credits + ' cr' : price + ' cr'})`;
        }
        this.profileErr('');
        if (typeof global.alert === 'function') {
          // soft toast via meta is enough; also link
        }
        const note = document.createElement('div');
        note.className = 'credit-note shop-list-note';
        note.style.cssText = 'text-align:left;margin-top:.5rem;color:var(--accent-2)';
        note.innerHTML = `✓ ${escapeHtml(data.message || 'Listed.')} <a href="/studios/character-shop">Open shop →</a>`;
        const shopPanel = $('profile-shop-panel');
        if (shopPanel) {
          shopPanel.querySelectorAll('.shop-list-note').forEach((n) => n.remove());
          shopPanel.appendChild(note);
        }
      } catch (e) {
        this.profileErr(e.message || 'Network error listing character.');
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = '🛒 List in Character Shop'; }
      }
    },

    renderProfileActions(c) {
      const spinBtn = c.spin_video_url ? '' : `<button type="button" class="rbtn" onclick="CharProfile.createSpin()">🎥 Create 360° (6 credits)</button>`;
      let selectBtn = '';
      if (this.opts.picker && this.opts.onToggleSelect) {
        const on = this.opts.isSelected && this.opts.isSelected(c.id);
        selectBtn = `<button type="button" class="rbtn" id="profile-select-btn" onclick="CharProfile.toggleSelect()">${on ? '✓ Selected' : '＋ Select for scene'}</button>`;
      }
      const del = this.opts.showDelete
        ? `<button type="button" class="rbtn danger" onclick="CharProfile.deleteChar(${c.id})">🗑 Delete</button>`
        : '';
      $('profile-actions').innerHTML = `
        ${selectBtn}
        ${spinBtn}
        ${this.dlBtn(c)}
        ${del}
        <a class="rbtn" href="/studios/percfectcharacter/arena">⚔ Arena</a>
        <a class="rbtn" href="/studios/percfectmotion">🎬 Motion</a>`;
    },

    toggleSelect() {
      if (!this.profileId || !this.opts.onToggleSelect) return;
      this.opts.onToggleSelect(this.profileId);
      const c = this.chars[this.profileId];
      if (c) this.renderProfileActions(c);
    },

    togglePickerSelect(id, ev) {
      if (ev) {
        ev.preventDefault();
        ev.stopPropagation();
      }
      if (this.opts.picker && this.opts.onToggleSelect) {
        this.opts.onToggleSelect(id);
      } else {
        this.open(id);
      }
    },

    pickerCardClick(id, ev) {
      if (ev) {
        ev.preventDefault();
        ev.stopPropagation();
      }
      if (this.opts.pickerDblClickOpensProfile) {
        if (this._pickerClickTimer) clearTimeout(this._pickerClickTimer);
        this._pickerClickTimer = setTimeout(() => {
          this._pickerClickTimer = null;
          this.togglePickerSelect(id, ev);
        }, 260);
        return;
      }
      this.togglePickerSelect(id, ev);
    },

    pickerCardDblClick(id, ev) {
      if (ev) {
        ev.preventDefault();
        ev.stopPropagation();
      }
      if (this._pickerClickTimer) {
        clearTimeout(this._pickerClickTimer);
        this._pickerClickTimer = null;
      }
      this.open(id);
    },

    _bindSpinDrag(el, c) {
      if (!el || !c?.spin_video_url) {
        if (el) el.draggable = false;
        return;
      }
      el.draggable = true;
      el.title = 'Drag this 360° spin to the Motion upload zone';
      el.dataset.spinUrl = c.spin_video_url;
      el.dataset.spinName = c.name || 'character';
      el.dataset.spinCharId = String(c.id);
      if (el._spinDragBound) return;
      el._spinDragBound = true;
      el.addEventListener('dragstart', (e) => {
        const url = el.dataset.spinUrl;
        if (!url) return;
        const payload = JSON.stringify({
          url,
          name: el.dataset.spinName || 'character',
          id: el.dataset.spinCharId,
        });
        e.dataTransfer.setData('application/x-percfect-spin', payload);
        e.dataTransfer.setData('text/uri-list', url);
        e.dataTransfer.effectAllowed = 'copy';
      });
    },

    _storeChar(c) {
      if (!c || c.id == null) return;
      this.chars[c.id] = c;
      this.chars[String(c.id)] = c;
    },

    async saveName() {
      const id = this.profileId;
      if (!id) {
        this.profileErr('No character open — close and reopen the profile.');
        return;
      }
      const input = $('profile-name-input');
      const name = (input && input.value || '').trim();
      if (!name) { this.profileErr('Enter a name first.'); return; }
      this.profileErr('');
      const saveBtn = $('profile-name-save');
      if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
      const fd = new FormData();
      fd.append('character_id', String(id));
      fd.append('name', name);
      try {
        const res = await fetch('/studios/percfectcharacter/edit', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        });
        let data = {};
        try { data = await res.json(); } catch (_e) { /* non-json */ }
        if (!res.ok) {
          this.profileErr(data.error || data.detail || `Save failed (${res.status}).`);
          return;
        }
        const saved = data.character || { ...(this.chars[id] || this.chars[String(id)] || {}), id, name };
        // Always force the name we just saved (server may omit it on weird rows)
        saved.name = name;
        saved.id = saved.id != null ? saved.id : id;
        this._storeChar(saved);
        if ($('profile-name-display')) {
          $('profile-name-display').textContent = name;
        }
        this.cancelNameEdit(true);
        if (this.opts.onReload) {
          try { await this.opts.onReload(); } catch (_e) { /* keep local name */ }
        }
        // Re-apply local name if reload raced with stale list
        const again = this.charById(id);
        if (again) {
          again.name = name;
          this._storeChar(again);
        }
        if ($('profile-name-display')) {
          $('profile-name-display').textContent = name;
        }
        if ($('profile-meta') && saved) {
          $('profile-meta').textContent = this.metaLine(saved);
        }
        // Refresh roster card titles if grid is present
        try {
          if (this.opts.onReload) { /* already called */ }
          else if (typeof this.fillGrid === 'function' && this.opts.gridId) {
            /* no-op */
          }
        } catch (_e) { /* ignore */ }
      } catch (e) {
        this.profileErr(e.message || 'Network error — please try again.');
      } finally {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save'; }
      }
    },

    versionsOf(c) {
      const list = (c && c.versions && c.versions.length) ? c.versions : null;
      if (list) {
        return list.map((v) => ({
          ...v,
          images: (v.images || []).filter((x) => typeof x === 'string' && x),
        }));
      }
      if (!c) return [];
      return [{
        id: 'v1',
        label: 'Original',
        primary_image_url: c.primary_image_url,
        images: this.shots(c),
        spin_video_url: c.spin_video_url,
      }];
    },

    renderVersions(c) {
      // Outfit list — Original + extra outfits on this card
      const wrap = $('profile-versions');
      if (!wrap) return;
      const vers = this.versionsOf(c);
      const active = c.active_version_id || 'v1';
      if (vers.length <= 1) {
        wrap.innerHTML = '<span style="font-size:.78rem;color:var(--text-muted)">Original outfit (build a new outfit below)</span>';
        return;
      }
      wrap.innerHTML = vers.map(v => {
        const on = String(v.id) === String(active);
        const safeId = String(v.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        let lab = v.label || v.id;
        if (String(v.id) === 'v1' || /^(original|v1)$/i.test(String(lab))) lab = 'Original';
        return `<button type="button" class="profile-gender-btn${on ? ' active' : ''}" data-vid="${escapeHtml(String(v.id))}"
          onclick="CharProfile.selectVersion('${safeId}')"
          style="${on ? 'background:var(--accent);color:#fff;border-color:var(--accent)' : ''}">${escapeHtml(lab)}</button>`;
      }).join('');
    },

    async selectVersion(versionId) {
      const c = this.charById(this.profileId);
      if (!c) return;
      const vers = this.versionsOf(c);
      const v = vers.find(x => String(x.id) === String(versionId));
      if (!v) return;
      // Optimistic local switch
      c.active_version_id = v.id;
      c.images = (v.images || []).filter((x) => typeof x === 'string' && x);
      c.primary_image_url = v.primary_image_url || c.images[0] || c.primary_image_url;
      if (v.spin_video_url !== undefined) c.spin_video_url = v.spin_video_url;
      this._storeChar(c);
      this.renderVersions(c);
      const shotList = this.shots(c);
      this.profileView = 'shot';
      this.profileSlot = 0;
      this.showHeroShot(c, shotList);
      this.renderSideShots(c, shotList);
      // Persist so Library / Arena / reloads keep the same active look
      try {
        const fd = new FormData();
        fd.append('character_id', String(c.id));
        fd.append('version_id', String(v.id));
        const res = await fetch('/studios/percfectcharacter/set-version', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.character) {
          this._storeChar(data.character);
          if (String(this.profileId) === String(data.character.id)) {
            this.renderVersions(data.character);
            const shots = this.shots(data.character);
            this.showHeroShot(data.character, shots);
            this.renderSideShots(data.character, shots);
          }
        }
      } catch (_e) { /* local switch still works */ }
    },

    /** New outfit on same player card (not a separate roster entry). */
    async applyAdjust() {
      const adj = ($('profile-adjust-input')?.value || '').trim()
        || ($('profile-accessories-input')?.value || '').trim();
      if (adj && $('profile-accessories-input')) {
        $('profile-accessories-input').value = adj;
      }
      return this.applyAccessories();
    },

    async applyAccessories() {
      const id = this.profileId;
      if (!id) {
        this.profileErr('No character open — close and reopen the profile.');
        return;
      }
      const change = ($('profile-accessories-input')?.value || '').trim()
        || ($('profile-adjust-input')?.value || '').trim();
      if (!change) {
        this.profileErr('Describe the new outfit (e.g. “red leather jacket and boots”).');
        return;
      }
      const tier = 'full';
      const cost = this.versionCost();
      this.profileErr('');
      const btn = $('profile-accessories-btn');
      if (btn) {
        btn.disabled = true;
        btn.textContent = `✨ Building outfit… (${cost} credits)`;
      }
      const fd = new FormData();
      fd.append('character_id', String(id));
      fd.append('change', change);
      fd.append('outfit', change);
      fd.append('tier', tier);
      fd.append('cost', String(cost));
      try {
        if (!global.PercfectStudioJobs) {
          this.profileErr('Job system unavailable — hard-refresh the page (Cmd+Shift+R).');
          return;
        }
        const raw = await global.PercfectStudioJobs.postQueued(
          '/studios/percfectcharacter/restyle',
          fd,
          {
            deadlineMs: 600000,
            onProgress: (_d, label) => {
              if (btn) btn.textContent = label || '✨ Building outfit…';
            },
          }
        );
        // Job poll may leave fields on .result if flatten missed — accept both shapes
        const data = (raw && raw.character) ? raw : Object.assign({}, raw, (raw && raw.result) || {});
        if (!data.ok && !data.character) {
          this.profileErr(data.error || raw.error || 'Outfit build failed.');
          return;
        }
        const saved = data.character;
        if (saved) {
          this._storeChar(saved);
          this.adjImgCredits(-(data.charged != null ? data.charged : cost));
          if (this.opts.onReload) {
            try { await this.opts.onReload(); } catch (_e) { /* keep local */ }
          }
          this.open(saved.id);
          if (data.version_id) this.selectVersion(data.version_id);
          if ($('profile-accessories-input')) $('profile-accessories-input').value = '';
          this.profileErr('');
          const meta = $('profile-meta');
          if (meta) {
            meta.textContent = (this.metaLine(saved) || '') + ' · new outfit on this player card';
          }
        }
      } catch (e) {
        this.profileErr(e.message || e.data?.error || 'Outfit build failed — try again.');
      } finally {
        if (btn) {
          btn.disabled = false;
          this.syncVersionBtn();
        }
      }
    },

    /** Clone active outfit → new roster card + own 360 (30 credits). */
    async splitToNewCard() {
      const id = this.profileId;
      const c = this.charById(id);
      if (!id || !c) {
        this.profileErr('No character open — close and reopen the profile.');
        return;
      }
      const cost = this.splitCost();
      const vid = c.active_version_id || 'v1';
      this.profileErr('');
      const btn = $('profile-split-btn');
      if (btn) {
        btn.disabled = true;
        btn.textContent = `🃏 Creating separate card + 360… (${cost} credits)`;
      }
      const fd = new FormData();
      fd.append('character_id', String(id));
      fd.append('version_id', String(vid));
      fd.append('cost', String(cost));
      try {
        if (!global.PercfectStudioJobs) {
          this.profileErr('Job system unavailable — hard-refresh the page (Cmd+Shift+R).');
          return;
        }
        const raw = await global.PercfectStudioJobs.postQueued(
          '/studios/percfectcharacter/split-version',
          fd,
          {
            deadlineMs: 600000,
            onProgress: (_d, label) => {
              if (btn) btn.textContent = label || '🃏 Building separate card…';
            },
          }
        );
        const data = (raw && raw.character) ? raw : Object.assign({}, raw, (raw && raw.result) || {});
        if (!data.ok && !data.character) {
          this.profileErr(data.error || raw.error || 'Could not create separate player card.');
          return;
        }
        this.adjImgCredits(-(data.charged != null ? data.charged : cost));
        if (data.character) {
          this._storeChar(data.character);
          if (this.opts.onReload) {
            try { await this.opts.onReload(); } catch (_e) { /* keep local */ }
          }
          // Open the NEW player card
          this.open(data.character.id);
          this.profileErr('');
          const meta = $('profile-meta');
          if (meta) {
            meta.textContent = (this.metaLine(data.character) || '') +
              ' · new player card' + (data.spin_video_url ? ' + 360°' : '');
          }
        }
      } catch (e) {
        this.profileErr(e.message || e.data?.error || 'Separate player card failed — try again.');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = '🃏 Separate player card + 360° · 30 credits';
        }
      }
    },

    async applyShotFix() {
      const id = this.profileId;
      const correction = ($('profile-shot-fix').value || '').trim();
      if (!correction) { this.profileErr('Describe what to change on this angle.'); return; }
      this.profileErr('');
      const btn = $('profile-shot-btn');
      if (btn) { btn.disabled = true; btn.textContent = '✎ Fixing…'; }
      const fd = new FormData();
      fd.append('character_id', id);
      fd.append('slot', this.profileSlot);
      fd.append('correction', correction);
      try {
        const data = global.PercfectStudioJobs
          ? await global.PercfectStudioJobs.postQueued('/studios/percfectcharacter/refine', fd)
          : await (await fetch('/studios/percfectcharacter/refine', { method: 'POST', body: fd })).json();
        if (!data.ok && !data.images) { this.profileErr(data.error || 'Fix failed.'); return; }
        const c = this.chars[id];
        if (c) {
          c.images = data.images;
          if (data.slot === 0) c.primary_image_url = data.images[0];
          this.chars[id] = c;
        }
        $('profile-shot-fix').value = '';
        this.adjImgCredits(-1);
        if (this.opts.onReload) await this.opts.onReload();
        const slot = data.slot != null ? data.slot : this.profileSlot;
        const refreshed = this.chars[id];
        if (refreshed) {
          const shotList = this.shots(refreshed);
          this.profileView = 'shot';
          this.profileSlot = slot;
          this.showHeroShot(refreshed, shotList);
          this.renderSideShots(refreshed, shotList);
        }
      } catch (e) { this.profileErr('Network error — please try again.'); }
      finally {
        if (btn) { btn.disabled = false; btn.textContent = '✎ Fix this angle (1 credit)'; }
      }
    },

    async createSpin() {
      const id = this.profileId;
      if (!id) return;
      this.profileErr('');
      const fd = new FormData();
      fd.append('character_id', id);
      try {
        const res = await fetch('/studios/percfectcharacter/generate-spin', { method: 'POST', body: fd });
        let data;
        try {
          data = global.PercfectStudioJobs
            ? await global.PercfectStudioJobs.resolveGenerationResponse(res, { deadlineMs: 600000 })
            : await res.json();
        } catch (e) {
          this.profileErr(e.message || '360° spin failed.');
          return;
        }
        if (!data.url) { this.profileErr(data.error || '360° spin failed.'); return; }
        const c = this.chars[id];
        if (c) c.spin_video_url = data.url;
        this.adjVidCredits(-6);
        if (this.opts.onReload) await this.opts.onReload();
        this.open(id);
        this.viewSpin();
      } catch (e) { this.profileErr('Network error — please try again.'); }
    },

    adjImgCredits(d) {
      const el = $('img-credits');
      if (el) { const n = parseInt(el.textContent, 10); if (!isNaN(n)) el.textContent = Math.max(0, n + d); }
    },

    adjVidCredits(d) {
      const el = $('vid-credits');
      if (el) { const n = parseInt(el.textContent, 10); if (!isNaN(n)) el.textContent = Math.max(0, n + d); }
    },

    heroHoverSpin(enter) {
      const c = this.chars[this.profileId];
      if (!c || !c.spin_video_url) return;
      const heroImg = $('profile-hero-img');
      const heroSpin = $('profile-hero-spin');
      const heroPh = $('profile-hero-ph');
      if (!heroSpin) return;

      if (this.profileView === 'spin') {
        if (enter && heroSpin.style.display !== 'none') heroSpin.play().catch(() => {});
        return;
      }

      if (enter) {
        if (heroImg) heroImg.style.display = 'none';
        if (heroPh) heroPh.style.display = 'none';
        heroSpin.src = c.spin_video_url;
        heroSpin.style.display = 'block';
        heroSpin.currentTime = 0;
        heroSpin.play().catch(() => {});
      } else {
        heroSpin.pause();
        const shots = this.shots(c);
        this.showHeroShot(c, shots);
      }
    },

    _bindRosterHoverTracking() {
      // no-op: hover video lives inside each card (no fixed overlay to track)
    },

    rosterHoverSpin(id, enter) {
      const c = this.charById(id);
      const img = $('rchar-img-' + id);
      const v = $('rchar-spin-' + id);
      if (!img) return;

      if (enter) {
        const url = (c && (c.spin_video_url || c.spinVideoUrl)) || '';
        if (!url || !v) return;
        this._rosterHoverId = id;
        // In-card video — survives scroll, bottom roster, sticky nav
        if (v.dataset.src !== url) {
          v.dataset.src = url;
          v.src = url;
        }
        v.style.display = 'block';
        img.style.opacity = '0';
        try { v.currentTime = 0; } catch (_e) { /* ignore */ }
        const tryPlay = () => { v.play().catch(() => { /* muted autoplay may need user gesture */ }); };
        if (v.readyState >= 2) tryPlay();
        else {
          v.addEventListener('loadeddata', tryPlay, { once: true });
          v.load();
        }
      } else if (this._rosterHoverId === id || this._rosterHoverId == null) {
        this._rosterHoverId = null;
        if (v) {
          try { v.pause(); } catch (_e) { /* ignore */ }
          v.style.display = 'none';
        }
        if (img) img.style.opacity = '1';
      }
    },

    rosterCardHtml(c, options) {
      const hasSpin = !!(c.spin_video_url);
      const spin = hasSpin ? '<span class="rchar-badge" style="position:absolute;top:.5rem;left:.5rem;z-index:2;background:rgba(0,0,0,.75);color:var(--accent-3);font-size:.62rem;font-family:var(--font-mono);padding:.15rem .5rem;border-radius:6px;">360°</span>' : '';
      const spinVideo = hasSpin
        ? `<video id="rchar-spin-${c.id}" class="rchar-spin-hover" muted loop playsinline preload="metadata"
            data-src="${escapeHtml(c.spin_video_url)}"
            style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none;z-index:1;pointer-events:none;border:0;"></video>`
        : '';
      const order = options.picker ? `<div class="acard-order" id="ord-${c.id}" style="display:none;position:absolute;top:.5rem;left:.5rem;background:rgba(0,0,0,.7);color:var(--accent-3);font-size:.62rem;font-family:var(--font-mono);padding:.15rem .5rem;border-radius:6px;"></div><div class="acard-check" style="position:absolute;top:.5rem;right:.5rem;width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;display:none;align-items:center;justify-content:center;font-weight:800;font-size:.8rem;">✓</div>` : '';
      const cls = options.picker ? 'acard viewable' : 'rchar clickable';
      const body = options.picker
        ? `<div class="acard-name" style="padding:.6rem;font-weight:700;font-size:.9rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(c.name || 'Unnamed')}</div>`
        : `<div class="rchar-body" style="padding:.75rem;">
            <div class="rchar-name" style="font-weight:700;font-size:.95rem;margin-bottom:.1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(c.name || 'Unnamed')}</div>
            <div class="rchar-meta" style="color:var(--text-muted);font-size:.72rem;margin-bottom:.5rem;">${c.gender || ''}${hasSpin ? ' · 360°' : ' · no 360 yet'}</div>
          </div>`;
      const pickerDbl = options.picker && options.pickerDblClickOpensProfile;
      const cardClick = options.picker
        ? (pickerDbl
          ? `CharProfile.pickerCardClick(${c.id}, event)`
          : `CharProfile.togglePickerSelect(${c.id}, event)`)
        : `CharProfile.open(${c.id})`;
      const cardDblClick = pickerDbl ? ` ondblclick="CharProfile.pickerCardDblClick(${c.id}, event)"` : '';
      const profileTap = options.picker
        ? (pickerDbl
          ? `<span class="acard-tap acard-hint">Click · select · double-click · profile</span>`
          : `<button type="button" class="acard-tap acard-profile-btn" onclick="event.stopPropagation();CharProfile.open(${c.id})" title="View full profile">Profile</button>`)
        : `<span class="rchar-tap">View profile</span>`;
      const keyPicker = pickerDbl ? `CharProfile.pickerCardClick(${c.id}, event)` : `CharProfile.togglePickerSelect(${c.id}, event)`;
      return `<div class="${cls}" id="ac-${c.id}" onclick="${cardClick}"${cardDblClick} role="button" tabindex="0"
        onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${options.picker ? keyPicker : `CharProfile.open(${c.id})`};}">
        ${order}
        <div class="${options.picker ? 'acard-img' : 'rchar-img'}" style="position:relative;aspect-ratio:1;background:var(--bg-3);overflow:hidden;"
          onmouseenter="CharProfile.rosterHoverSpin(${c.id},true)" onmouseleave="CharProfile.rosterHoverSpin(${c.id},false)">
          <img id="rchar-img-${c.id}" src="${escapeHtml(c.primary_image_url || '')}" alt="" style="width:100%;height:100%;object-fit:cover;display:block;transition:opacity .15s;">
          ${spinVideo}
          ${spin}
          ${profileTap}
        </div>
        ${body}
      </div>`;
    },

    fillGrid(gridId, chars, options) {
      const grid = $(gridId);
      if (!grid) return;
      const opts = { ...this.opts, ...(options || {}) };
      grid.innerHTML = (chars || []).map(c => this.rosterCardHtml(c, opts)).join('');
    },

    async deleteChar(id) {
      if (!confirm('Delete this character?')) return;
      const fd = new FormData();
      fd.append('character_id', id);
      await fetch('/studios/percfectcharacter/delete', { method: 'POST', body: fd });
      if (this.modal) this.modal.hide();
      if (this.opts.onReload) await this.opts.onReload();
    },
  };

  window.CharProfile = CharProfile;
})();