/**
 * Async studio jobs — instant ack, background render, poll for result.
 * Website uses SESSION cookies only (never X-API-Key / "API key required").
 */
(function (global) {
  // Generation optimization: snappier browser poll so UI notices "done" ASAP
  const POLL_MS_IMAGE = 400;
  const POLL_MS_VIDEO = 800;
  const POLL_MS = POLL_MS_IMAGE;
  // 3 min allows ref rehost + edit path under load after batch runs
  const DEADLINE_IMAGE_MS = 180000;
  // xAI video often 2–6+ min; 120s made the UI quit while the job still ran
  const DEADLINE_VIDEO_MS = 480000;
  const DEADLINE_MOTION_MS = 600000;

  function deadlineForKind(kind) {
    // Character restyle rebuilds 4 angles — needs video-length budget
    if (
      kind === 'image' ||
      kind === 'batch' ||
      kind === 'character_one' ||
      kind === 'character_precision_seed' ||
      kind === 'character_pack' ||
      kind === 'character_finalize' ||
      kind === 'character_refine' ||
      kind === 'api_image' ||
      kind === 'picture_logo' ||
      kind === 'trading_card' ||
      kind === 'princess_image' ||
      kind === 'motion_save_background'
    ) {
      // batch / multi-angle builds can take longer than a single image
      if (kind === 'batch' || kind === 'character_finalize' || kind === 'character_restyle') {
        return Math.max(DEADLINE_IMAGE_MS, 240000);
      }
      if (kind === 'character_pack') {
        // 360 video + frame extract
        return Math.max(DEADLINE_VIDEO_MS, 300000);
      }
      return DEADLINE_IMAGE_MS;
    }
    // Studio video / arena / extend — up to DEADLINE_VIDEO_MS (8 min)
    if (
      kind === 'video' ||
      kind === 'extend' ||
      kind === 'spin' ||
      kind === 'character_pack' ||
      kind === 'arena' ||
      kind === 'fight' ||
      kind === 'api_video'
    ) {
      return kind === 'character_pack' ? Math.max(DEADLINE_VIDEO_MS, 300000) : DEADLINE_VIDEO_MS;
    }
    // Motion extract / retarget can be long (local MediaPipe + optional gen)
    if (
      kind === 'motion_retarget' ||
      kind === 'motion_build_character' ||
      kind === 'motion_build_character_preview'
    ) {
      return DEADLINE_MOTION_MS;
    }
    return DEADLINE_VIDEO_MS;
  }

  function pollIntervalForKind(kind) {
    if (
      kind === 'video' ||
      kind === 'extend' ||
      kind === 'spin' ||
      kind === 'arena' ||
      kind === 'fight' ||
      kind === 'api_video' ||
      kind === 'character_restyle' ||
      kind === 'character_split_version' ||
      kind === 'character_finalize' ||
      kind === 'motion_retarget' ||
      kind === 'motion_build_character' ||
      kind === 'motion_build_character_preview' ||
      kind === 'motion_save_background'
    ) {
      return POLL_MS_VIDEO;
    }
    return POLL_MS_IMAGE;
  }

  /** Flatten job.result onto the poll payload so callers can use data.character / data.url. */
  function flattenDone(data) {
    if (!data || typeof data !== 'object') return data;
    const r = data.result;
    if (!r || typeof r !== 'object') return data;
    // Always merge result fields (restyle returns character/ok, not url)
    return Object.assign({}, data, r);
  }

  function queueLabel(data) {
    if (data.status === 'queued' && data.queue_ahead > 0) {
      return `In queue — ${data.queue_ahead} ahead of you…`;
    }
    if (data.status === 'queued' || data.status === 'pending') {
      return 'Starting…';
    }
    if (data.status === 'processing') {
      return 'Rendering…';
    }
    return 'Working…';
  }

  const api = {};

  api.pollStudioJob = async function pollStudioJob(jobId, opts) {
    let interval = (opts && opts.intervalMs) || POLL_MS;
    const onProgress = opts && opts.onProgress;
    const startMs = Date.now();
    let deadline = startMs + ((opts && opts.deadlineMs) || DEADLINE_VIDEO_MS);
    let deadlineSet = !!(opts && opts.deadlineMs);

    // Session-only paths (login cookie). Never /api/generation-job (that is for API keys).
    const pollUrls = [
      '/percfectstudios/generation-job/' + encodeURIComponent(jobId),
      '/studios/generation-job/' + encodeURIComponent(jobId),
    ];
    let urlIdx = 0;
    let serverErrorStreak = 0;

    while (Date.now() < deadline) {
      let res;
      let data = {};
      try {
        // Never hang forever on a single poll — 15s fetch cap
        const ac = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        const fetchTimer = ac ? setTimeout(() => { try { ac.abort(); } catch (_e) {} }, 15000) : null;
        res = await fetch(pollUrls[urlIdx], {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          signal: ac ? ac.signal : undefined,
        });
        if (fetchTimer) clearTimeout(fetchTimer);
        try {
          data = await res.json();
        } catch (_e) {
          data = {};
        }
      } catch (_net) {
        await new Promise((r) => setTimeout(r, interval));
        continue;
      }

      // Job not stored yet — normal; keep waiting (do not switch endpoints).
      // Exception: body may already say failed (older servers returned 404 for any
      // payload with an error field — surface that immediately, don't spin forever).
      if (res.status === 404) {
        const st404 = String((data && data.status) || '').toLowerCase();
        if (st404 === 'failed' || st404 === 'error') {
          const errMsg =
            (data && data.error) ||
            (data && data.result && (data.result.error || data.result.message)) ||
            'Generation failed.';
          throw new Error(errMsg);
        }
        serverErrorStreak = 0;
        if (onProgress) onProgress({ status: 'queued' }, 'Starting…');
        await new Promise((r) => setTimeout(r, interval));
        continue;
      }

      if (res.status === 401 || res.status === 403) {
        const msg = String((data && data.error) || '');
        // Never show "API key required" in the website UI
        if (/api key/i.test(msg)) {
          if (urlIdx < pollUrls.length - 1) {
            urlIdx += 1;
            continue;
          }
          throw new Error('Session expired — refresh the page and log in again.');
        }
        throw new Error(msg || 'Log in to continue.');
      }

      if (res.status >= 500) {
        serverErrorStreak += 1;
        if (serverErrorStreak > 3 && urlIdx < pollUrls.length - 1) {
          urlIdx += 1;
          serverErrorStreak = 0;
        }
        await new Promise((r) => setTimeout(r, interval));
        continue;
      }

      if (!res.ok) {
        throw new Error((data && data.error) || ('Job poll failed (' + res.status + ').'));
      }

      serverErrorStreak = 0;
      if (!deadlineSet && data.kind) {
        deadline = Date.now() + deadlineForKind(data.kind);
        deadlineSet = true;
        if (!(opts && opts.intervalMs)) {
          interval = pollIntervalForKind(data.kind);
        }
      }
      if (onProgress) onProgress(data, queueLabel(data));
      // Accept common terminal statuses
      const st = String(data.status || '').toLowerCase();
      if (st === 'failed' || st === 'error') {
        const errMsg =
          data.error ||
          (data.result && (data.result.error || data.result.message)) ||
          'Generation failed.';
        throw new Error(errMsg);
      }
      if (st === 'done' || st === 'completed' || st === 'success') {
        return flattenDone(data);
      }
      // Media payload without a running status → treat as done (proxy edge cases)
      const hasMedia =
        !!(data.url ||
          (Array.isArray(data.urls) && data.urls.length) ||
          (data.result && (data.result.url || (Array.isArray(data.result.urls) && data.result.urls.length))));
      const stillRunning = !st || st === 'queued' || st === 'pending' || st === 'processing' || st === 'running';
      if (hasMedia && !stillRunning) {
        return flattenDone(data);
      }
      await new Promise((r) => setTimeout(r, interval));
    }

    // Deadline hit — surface as our hang (caller maps to error 69069 + retry).
    const waitedSec = Math.round((Date.now() - startMs) / 1000);
    const err = new Error(
      'Error 69069 — no finish after long wait (our side). You were not charged if it never completed. Check last 6 — it may still land.'
    );
    err.code = '69069';
    err.reason = 'timeout';
    err.waitedSec = waitedSec;
    throw err;
  };

  api.resolveGenerationResponse = async function resolveGenerationResponse(res, opts) {
    let data;
    try {
      data = await res.json();
    } catch (_e) {
      data = {};
    }
    if (!res.ok) {
      const err = new Error(data.error || 'Generation failed.');
      err.data = data;
      throw err;
    }
    // Support a few ack shapes (async + job_id, or job only)
    const jobId = data.job_id || data.id || (data.job && data.job.id);
    const isAsync = data.async || data.status === 'queued' || data.status === 'pending' || !!data.job_id;
    if (jobId && isAsync) {
      const pollOpts = Object.assign({}, opts || {});
      if (opts && opts.kind && !pollOpts.deadlineMs) {
        pollOpts.deadlineMs = deadlineForKind(opts.kind);
      }
      return api.pollStudioJob(jobId, pollOpts);
    }
    return data;
  };

  api.postQueued = async function postQueued(url, body, opts) {
    const res = await fetch(url, {
      method: 'POST',
      body,
      credentials: 'same-origin',
      headers:
        body instanceof FormData
          ? undefined
          : { 'Content-Type': 'application/json', Accept: 'application/json' },
    });
    return api.resolveGenerationResponse(res, opts);
  };

  api.queueLabel = queueLabel;

  /**
   * Honest stage progress — bar only moves when the job status actually changes.
   * Never invents % from elapsed time or poll ticks.
   * If the server sends progress / percent / pct (0–100 or 0–1), that wins.
   * Otherwise:
   *   queued/pending → 12%
   *   processing/running → 55% (holds until done — no creep)
   *   saving → 90%
   *   done → 100%
   */
  api.makeStageProgress = function makeStageProgress(opts) {
    opts = opts || {};
    const $ = (x) => (typeof x === 'string' ? document.getElementById(x) : x || null);
    let pct = 0;
    function paint(p, text) {
      pct = Math.max(pct, Math.min(100, p));
      const bar = $(opts.bar);
      const lab = $(opts.label);
      if (bar) bar.style.width = pct + '%';
      if (lab && text) lab.textContent = (opts.prefix || '') + text;
    }
    function readServerPct(data) {
      if (!data || typeof data !== 'object') return null;
      const raw =
        data.progress != null ? data.progress :
        data.percent != null ? data.percent :
        data.pct != null ? data.pct :
        (data.result && (data.result.progress != null ? data.result.progress :
          data.result.percent != null ? data.result.percent : null));
      if (raw == null || raw === '') return null;
      let n = Number(raw);
      if (!isFinite(n)) return null;
      if (n > 0 && n <= 1) n = n * 100; // 0–1 → 0–100
      return Math.max(0, Math.min(100, n));
    }
    function onProgress(data, label) {
      const serverPct = readServerPct(data);
      if (serverPct != null) {
        paint(serverPct, label || queueLabel(data || {}));
        return;
      }
      const st = String((data && data.status) || '').toLowerCase();
      if (st === 'queued' || st === 'pending' || !st) {
        paint(12, label || queueLabel(data || {}));
      } else if (st === 'processing' || st === 'running') {
        // Floor only — live server progress (data.progress) wins above.
        // Never park forever at 55 if progress never arrives; floor is 20.
        paint(Math.max(pct, 20), label || 'Rendering…');
      } else if (st === 'saving') {
        paint(90, 'Saving…');
      } else if (st === 'done' || st === 'completed' || st === 'success') {
        paint(100, 'Done');
      } else {
        paint(Math.max(pct, 12), label || 'Working…');
      }
    }
    onProgress.done = function (text) { paint(100, text || 'Done'); };
    onProgress.reset = function () {
      pct = 0;
      const bar = $(opts.bar);
      if (bar) bar.style.width = '0%';
    };
    return onProgress;
  };

  global.PercfectStudioJobs = api;
})(window);

/**
 * SpicyAPI Studio Controls, Dynamic Options, Credit Pricing & Moderation Redirect UI
 * - Photos (/studios/photos): dedicated "18+ Generate for Mature Audiences" button (no model dropdown)
 * - Videos (/studios/videos): Grok Imagine (Default) + MiniMax H3 with quality, duration & credit math
 */
(function (global) {
  if (typeof document === 'undefined') return;

  const state = {
    maturePhotoModelId: 'bytedance/seedream-5.5',
    maturePhotoRes: '2k',
    maturePhotoCredits: 3,
    nextPhotoModel: '',
    nextPhotoRes: '',
    videoModels: [],
    vidModel: 'grok',
    vidRes: '',
    vidAspect: 'auto',
    vidDur: 6,
    extendModel: 'grok',
    extendRes: '',
    extendDur: 6,
    moderatedUntil: { img: 0, batch: 0, vid: 0, extend: 0 },
  };

  function findVideoModel(id) {
    if (!id || id === 'grok') return null;
    return state.videoModels.find((m) => m.id === id) || null;
  }

  function injectStyles() {
    if (document.getElementById('spicy-studio-css')) return;
    const st = document.createElement('style');
    st.id = 'spicy-studio-css';
    st.textContent = [
      '.studio-mature-btn{width:100%;margin-top:.48rem;padding:.68rem .9rem;border-radius:12px;border:1px solid rgba(244,114,182,.45);background:linear-gradient(135deg,rgba(190,24,93,.22),rgba(124,92,252,.22));color:#fdf2f8;font-size:.9rem;font-weight:700;display:flex;align-items:center;justify-content:center;gap:.5rem;cursor:pointer;transition:transform .12s ease,border-color .15s ease,background .15s ease;}',
      '.studio-mature-btn:hover:not(:disabled){border-color:rgba(244,114,182,.8);background:linear-gradient(135deg,rgba(190,24,93,.34),rgba(124,92,252,.32));transform:translateY(-1px);}',
      '.studio-mature-btn:disabled{opacity:.6;cursor:not-allowed;}',
      '.studio-mature-badge{display:inline-flex;align-items:center;justify-content:center;padding:.12rem .42rem;border-radius:6px;background:rgba(244,63,94,.28);border:1px solid rgba(251,113,133,.65);color:#fecdd3;font-size:.7rem;font-weight:800;letter-spacing:.04em;line-height:1.1;}',
      '.studio-model-box{margin-top:.55rem;padding:.55rem .65rem;border:1px solid var(--border-2,#263d52);border-radius:12px;background:rgba(255,255,255,.03);display:flex;flex-direction:column;gap:.42rem;}',
      '.studio-model-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem;}',
      '.studio-model-label{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--accent-2,#a78bfa);font-family:var(--font-mono,ui-monospace,monospace);}',
      '.studio-model-select{width:100%;padding:.48rem .6rem;border-radius:9px;border:1px solid var(--border-2,#263d52);background:var(--bg-3,#11131d);color:var(--text,#eef4f9);font-size:.85rem;font-weight:600;font-family:inherit;}',
      '.studio-model-select:focus{outline:none;border-color:var(--accent,#7c5cfc);}',
      '.studio-model-opts{display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;}',
      '.studio-opt-label{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted,#9fb0c0);min-width:3.1rem;}',
      '.studio-model-opts .photos-split-chips{flex:1 1 auto;flex-wrap:wrap;}',
      '.studio-audio-toggle{display:inline-flex;align-items:center;gap:.4rem;font-size:.76rem;color:var(--text,#eef4f9);cursor:pointer;margin:0;}',
      '.studio-audio-toggle input{accent-color:var(--accent,#7c5cfc);}',
      '.studio-model-hint{font-size:.72rem;color:#fbbf24;line-height:1.3;}',
      '.studio-mod-banner{margin-top:.55rem;padding:.7rem .85rem;border-radius:12px;border:1px solid rgba(251,191,36,.45);background:rgba(251,191,36,.1);color:#fde68a;font-size:.82rem;line-height:1.4;}',
      '.studio-mod-banner a{color:#fbbf24;font-weight:700;text-decoration:underline;margin-left:.35rem;}',
    ].join('');
    document.head.appendChild(st);
  }

  function renderChips(containerId, items, activeVal, onPick) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.innerHTML = '';
    (items || []).forEach((val) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'style-chip' + (String(val) === String(activeVal) ? ' active' : '');
      btn.textContent = String(val);
      btn.onclick = () => onPick(val, btn);
      box.appendChild(btn);
    });
  }

  function populateVideoSelect(selectId, models, extendOnly) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    const prev = sel.value || 'grok';
    const list = extendOnly ? models.filter((m) => m.routes && m.routes.extend) : models;

    function opt(m) {
      const p = m.pricing || {};
      const u = p.unit === 'second' ? ' cr/s' : ' cr';
      const label = `${m.label} (${p.default_credits || 3}${u})`;
      return `<option value="${String(m.id).replace(/"/g, '&quot;')}">${label.replace(/</g, '&lt;')}</option>`;
    }

    const baseRate = extendOnly ? `${global.VIDEO_EXTEND_RATE || 6} cr/s` : `${global.VIDEO_RATE || 3} cr/s`;
    let html = `<option value="grok">Grok Imagine (Default · ${baseRate})</option>` + list.map(opt).join('');
    sel.innerHTML = html;
    sel.value = Array.from(sel.options).some((o) => o.value === prev) ? prev : 'grok';
  }

  function updateMatureButtonLabel(busy) {
    const btn = document.getElementById('img-mature-btn');
    const txt = document.getElementById('img-mature-btn-text');
    if (!btn || !txt) return;
    btn.disabled = !!busy;
    const c = state.maturePhotoCredits || 3;
    if (busy) {
      txt.textContent = 'Generating…';
    } else {
      txt.innerHTML = `Generate for Mature Audiences (<span id="img-mature-cost">${c} credit${c === 1 ? '' : 's'}</span>)`;
    }
  }

  function updateVideoHint() {
    const hint = document.getElementById('vid-model-hint');
    if (!hint) return;
    const m = findVideoModel(state.vidModel);
    const refs = typeof global.videoRefCount === 'function' ? global.videoRefCount() : 0;
    if (m && m.requires_ref && refs === 0) {
      hint.textContent = '⚠ Requires 1 reference photo (pick from Library or upload in References →).';
      hint.style.display = 'block';
    } else {
      hint.style.display = 'none';
    }
  }

  function showModNotice(panel, data) {
    state.moderatedUntil[panel] = Date.now() + 3000;
    const targetId = panel === 'img' ? 'img-toast' : (panel === 'batch' ? 'batch-toast' : (panel === 'extend' ? 'extend-error' : 'vid-error'));
    const box = document.getElementById(targetId);
    if (!box) return;
    box.className = 'studio-mod-banner';
    box.style.display = 'block';
    box.innerHTML = '';
    const span = document.createElement('span');
    span.textContent = (data && data.message) || 'Sent to your private vault on the mature site. Sign in with your same login to get your file.';
    box.appendChild(span);
    if (data && data.mature_site_url) {
      const a = document.createElement('a');
      a.href = data.mature_site_url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = 'Open mature site →';
      box.appendChild(a);
    }
    const crEl = document.getElementById(panel === 'vid' || panel === 'extend' ? 'vid-credits' : 'img-credits');
    if (crEl && data && data.charged != null) {
      const bal = parseInt(crEl.textContent, 10);
      if (!isNaN(bal)) crEl.textContent = String(Math.max(0, bal - Number(data.charged || 0)));
    }
  }

  function onVidModelChange() {
    const sel = document.getElementById('vid-model-select');
    state.vidModel = sel ? sel.value : 'grok';
    const m = findVideoModel(state.vidModel);
    const resWrap = document.getElementById('vid-res-wrap');
    const arWrap = document.getElementById('vid-aspect-wrap');
    const audWrap = document.getElementById('vid-audio-wrap');

    if (m && m.resolutions && m.resolutions.length) {
      if (!m.resolutions.includes(state.vidRes)) state.vidRes = m.default_resolution || m.resolutions[0];
      if (resWrap) resWrap.style.display = 'flex';
      renderChips('vid-res-chips', m.resolutions, state.vidRes, (val) => {
        state.vidRes = val;
        onVidModelChange();
      });
    } else {
      state.vidRes = '';
      if (resWrap) resWrap.style.display = 'none';
    }

    if (m && m.aspect_ratios && m.aspect_ratios.length) {
      const ars = ['auto'].concat(m.aspect_ratios);
      if (!ars.includes(state.vidAspect)) state.vidAspect = 'auto';
      if (arWrap) arWrap.style.display = 'flex';
      renderChips('vid-aspect-chips', ars, state.vidAspect, (val) => {
        state.vidAspect = val;
        onVidModelChange();
      });
    } else {
      state.vidAspect = 'auto';
      if (arWrap) arWrap.style.display = 'none';
    }

    if (audWrap) audWrap.style.display = (m && m.supports_audio) ? 'inline-flex' : 'none';

    const dOpts = (m && m.durations && m.durations.options && m.durations.options.length) ? m.durations.options : [6, 10, 15];
    if (!dOpts.includes(state.vidDur)) state.vidDur = dOpts.includes(6) ? 6 : dOpts[0];
    const durBox = document.getElementById('vid-duration-chips');
    if (durBox) {
      durBox.innerHTML = '';
      dOpts.forEach((sec) => {
        const chip = document.createElement('span');
        chip.className = 'style-chip' + (sec === state.vidDur ? ' active' : '');
        chip.textContent = `${sec}s`;
        chip.onclick = () => {
          state.vidDur = sec;
          if (typeof global.setDuration === 'function') global.setDuration(chip, sec);
        };
        durBox.appendChild(chip);
      });
    }
    updateVideoHint();
    if (typeof global.updateVidCostUI === 'function') global.updateVidCostUI();
  }

  function onExtendModelChange() {
    const sel = document.getElementById('extend-model-select');
    state.extendModel = sel ? sel.value : 'grok';
    const m = findVideoModel(state.extendModel);
    const resWrap = document.getElementById('extend-res-wrap');
    if (m && m.resolutions && m.resolutions.length) {
      if (!m.resolutions.includes(state.extendRes)) state.extendRes = m.default_resolution || m.resolutions[0];
      if (resWrap) resWrap.style.display = 'flex';
      renderChips('extend-res-chips', m.resolutions, state.extendRes, (val) => {
        state.extendRes = val;
        onExtendModelChange();
      });
    } else {
      state.extendRes = '';
      if (resWrap) resWrap.style.display = 'none';
    }
    const dOpts = (m && m.durations && m.durations.options && m.durations.options.length) ? m.durations.options : [6, 8, 10];
    if (!dOpts.includes(state.extendDur)) state.extendDur = dOpts.includes(6) ? 6 : dOpts[0];
    const exBox = document.getElementById('extend-chips');
    if (exBox) {
      exBox.innerHTML = '';
      dOpts.forEach((sec) => {
        const chip = document.createElement('span');
        chip.className = 'style-chip' + (sec === state.extendDur ? ' active' : '');
        chip.textContent = `+${sec}s`;
        chip.onclick = () => {
          state.extendDur = sec;
          if (typeof global.setExtend === 'function') global.setExtend(chip, sec);
        };
        exBox.appendChild(chip);
      });
    }
    const ec = document.getElementById('extend-cost');
    if (ec && typeof global.extendCreditCost === 'function') ec.textContent = String(global.extendCreditCost(state.extendDur));
  }

  function wrapGlobalFunctions() {
    if (typeof global.setLoading === 'function') {
      const origSetLoading = global.setLoading;
      global.setLoading = function (prefix, on) {
        origSetLoading(prefix, on);
        if (prefix === 'img') updateMatureButtonLabel(!!on);
      };
    }
    if (typeof global.videoGenRate === 'function') {
      const origRate = global.videoGenRate;
      global.videoGenRate = function () {
        const m = findVideoModel(state.vidModel);
        if (m && m.pricing) {
          const rkey = state.vidRes || 'default';
          return (m.pricing.by_resolution && m.pricing.by_resolution[rkey]) || m.pricing.default_credits || 3;
        }
        return origRate();
      };
    }
    if (typeof global.videoCreditCost === 'function') {
      const origVidCost = global.videoCreditCost;
      global.videoCreditCost = function (secs) {
        const m = findVideoModel(state.vidModel);
        const s = parseInt(secs || state.vidDur, 10) || 6;
        if (m && m.pricing) {
          const rkey = state.vidRes || 'default';
          const dmap = m.pricing.by_duration && m.pricing.by_duration[rkey];
          if (dmap && dmap[String(s)] != null) return dmap[String(s)];
          if (m.pricing.unit === 'second') return s * global.videoGenRate();
          return m.pricing.default_credits || 18;
        }
        return origVidCost(s);
      };
    }
    if (typeof global.setDuration === 'function') {
      const origSetDur = global.setDuration;
      global.setDuration = function (chip, secs) {
        const s = parseInt(secs, 10) || 6;
        state.vidDur = s;
        if (!findVideoModel(state.vidModel)) return origSetDur(chip, s);
        const root = (chip && chip.closest && chip.closest('.duration-chips')) || document.getElementById('vid-duration-chips');
        if (root) root.querySelectorAll('.style-chip').forEach((c) => c.classList.remove('active'));
        if (chip) chip.classList.add('active');
        if (typeof global.updateVidCostUI === 'function') global.updateVidCostUI();
      };
    }
    if (typeof global.updateVidCostUI === 'function') {
      const origVidUI = global.updateVidCostUI;
      global.updateVidCostUI = function () {
        const m = findVideoModel(state.vidModel);
        if (!m) {
          origVidUI();
          updateVideoHint();
          return;
        }
        const rate = global.videoGenRate();
        const cost = global.videoCreditCost(state.vidDur);
        const vc = document.getElementById('vid-cost');
        if (vc) vc.textContent = String(cost);
        const note = document.getElementById('duration-note');
        if (note) {
          const rateTxt = (m.pricing && m.pricing.unit === 'request') ? `flat ${cost} cr` : `${rate} credits/sec`;
          note.textContent = `${state.vidDur}s · ${rateTxt}${state.vidRes ? ' · ' + state.vidRes : ''}`;
        }
        updateVideoHint();
      };
    }
    if (typeof global.extendCreditCost === 'function') {
      const origExCost = global.extendCreditCost;
      global.extendCreditCost = function (secs) {
        const m = findVideoModel(state.extendModel);
        const s = parseInt(secs || state.extendDur, 10) || 6;
        if (m && m.pricing) {
          const rkey = state.extendRes || 'default';
          const dmap = m.pricing.by_duration && m.pricing.by_duration[rkey];
          if (dmap && dmap[String(s)] != null) return dmap[String(s)];
          const rate = (m.pricing.by_resolution && m.pricing.by_resolution[rkey]) || m.pricing.default_credits || 6;
          return m.pricing.unit === 'second' ? s * rate : rate;
        }
        return origExCost(s);
      };
    }
    if (typeof global.setExtend === 'function') {
      const origSetEx = global.setExtend;
      global.setExtend = function (chip, secs) {
        const s = parseInt(secs, 10) || 6;
        state.extendDur = s;
        if (!findVideoModel(state.extendModel)) return origSetEx(chip, s);
        const box = document.getElementById('extend-chips');
        if (box) box.querySelectorAll('.style-chip').forEach((c) => c.classList.remove('active'));
        if (chip) chip.classList.add('active');
        const ec = document.getElementById('extend-cost');
        if (ec) ec.textContent = String(global.extendCreditCost(s));
      };
    }
    ['showError', 'showBatchError', 'showVidError', 'showExtendError'].forEach((fnName) => {
      if (typeof global[fnName] !== 'function') return;
      const orig = global[fnName];
      global[fnName] = function () {
        const now = Date.now();
        if (fnName === 'showError') {
          const p = arguments[0];
          if (state.moderatedUntil[p] && now < state.moderatedUntil[p]) return;
        } else if (fnName === 'showBatchError' && now < state.moderatedUntil.batch) {
          return;
        } else if (fnName === 'showVidError' && now < state.moderatedUntil.vid) {
          return;
        } else if (fnName === 'showExtendError' && now < state.moderatedUntil.extend) {
          return;
        }
        return orig.apply(this, arguments);
      };
    });
  }

  function installPollAndFetchHooks() {
    const api = global.PercfectStudioJobs;
    if (api && !api.__spicyWrapped) {
      api.__spicyWrapped = true;
      const origResolve = api.resolveGenerationResponse;
      api.resolveGenerationResponse = async function (res, opts) {
        const data = await origResolve.call(this, res, opts);
        if (data && (data.moderated_redirect || (data.moderated_count > 0 && !(data.urls && data.urls.length)))) {
          const k = (opts && opts.kind) || '';
          const panel = k === 'batch' ? 'batch' : (k === 'extend' ? 'extend' : (k === 'video' ? 'vid' : 'img'));
          showModNotice(panel, data);
        }
        return data;
      };
    }

    if (global.__spicyFetchWrapped) return;
    global.__spicyFetchWrapped = true;
    const origFetch = global.fetch;
    global.fetch = function (input, init) {
      try {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const method = ((init && init.method) || 'GET').toUpperCase();
        if (method === 'POST' && init && init.body instanceof FormData) {
          if (url.endsWith('/percfectstudios/generate-image')) {
            if (state.nextPhotoModel) {
              init.body.set('model', state.nextPhotoModel);
              if (state.nextPhotoRes) init.body.set('resolution', state.nextPhotoRes);
              state.nextPhotoModel = '';
              state.nextPhotoRes = '';
            } else {
              init.body.set('model', 'grok');
            }
          } else if (url.endsWith('/percfectstudios/generate-video')) {
            init.body.set('model', state.vidModel || 'grok');
            if (state.vidModel && state.vidModel !== 'grok') {
              init.body.set('duration', String(state.vidDur || 6));
              if (state.vidRes) init.body.set('resolution', state.vidRes);
              if (state.vidAspect && state.vidAspect !== 'auto') init.body.set('aspect_ratio', state.vidAspect);
            }
          } else if (url.endsWith('/percfectstudios/extend-video')) {
            init.body.set('model', state.extendModel || 'grok');
            if (state.extendModel && state.extendModel !== 'grok') {
              init.body.set('duration', String(state.extendDur || 6));
              if (state.extendRes) init.body.set('resolution', state.extendRes);
            }
          }
        }
      } catch (_e) {}
      return origFetch.apply(this, arguments);
    };
  }

  function triggerMaturePhotoGenerate() {
    const start = () => {
      state.nextPhotoModel = state.maturePhotoModelId || 'bytedance/seedream-5.5';
      state.nextPhotoRes = state.maturePhotoRes || '2k';
      if (typeof global._generateImage === 'function') {
        global._generateImage();
      } else if (typeof global.generateImage === 'function') {
        global.generateImage();
      }
    };
    if (typeof global.requireAuth === 'function') {
      global.requireAuth(start);
    } else {
      start();
    }
  }

  async function mountStudioModels() {
    const imgBtn = document.getElementById('img-btn');
    const vidDur = document.getElementById('vid-duration-chips');
    if (!imgBtn && !vidDur) return;

    injectStyles();
    wrapGlobalFunctions();
    installPollAndFetchHooks();

    if (imgBtn && !document.getElementById('img-mature-btn')) {
      const mBtn = document.createElement('button');
      mBtn.type = 'button';
      mBtn.id = 'img-mature-btn';
      mBtn.className = 'studio-mature-btn';
      mBtn.innerHTML =
        '<span class="studio-mature-badge" aria-hidden="true">18+</span>' +
        '<span id="img-mature-btn-text">Generate for Mature Audiences (<span id="img-mature-cost">3 credits</span>)</span>';
      imgBtn.insertAdjacentElement('afterend', mBtn);
      mBtn.addEventListener('click', triggerMaturePhotoGenerate);
      try {
        const res = await fetch('/api/spicy/studio-models?modality=image&spicy=0');
        const data = await res.json();
        const m = ((data && data.models) || [])[0];
        if (m) {
          state.maturePhotoModelId = m.id;
          state.maturePhotoRes = m.default_resolution || '2k';
          const rkey = state.maturePhotoRes || 'default';
          state.maturePhotoCredits = (m.pricing && m.pricing.by_resolution && m.pricing.by_resolution[rkey]) || (m.pricing && m.pricing.default_credits) || 3;
          updateMatureButtonLabel(false);
        }
      } catch (_e) {}
    }

    if (vidDur && !document.getElementById('vid-model-box')) {
      const box = document.createElement('div');
      box.className = 'studio-model-box';
      box.id = 'vid-model-box';
      box.innerHTML =
        '<div class="studio-model-head"><span class="studio-model-label">Model</span></div>' +
        '<select id="vid-model-select" class="studio-model-select" aria-label="Video model"><option value="grok">Grok Imagine (Default · 3 cr/s)</option></select>' +
        '<div id="vid-res-wrap" class="studio-model-opts" style="display:none"><span class="studio-opt-label">Quality</span><div class="style-chips photos-split-chips" id="vid-res-chips"></div></div>' +
        '<div id="vid-aspect-wrap" class="studio-model-opts" style="display:none"><span class="studio-opt-label">Ratio</span><div class="style-chips photos-split-chips" id="vid-aspect-chips"></div></div>' +
        '<label id="vid-audio-wrap" class="studio-audio-toggle" style="display:none"><input type="checkbox" id="vid-audio-check"> Generate audio</label>' +
        '<div id="vid-model-hint" class="studio-model-hint" style="display:none"></div>';
      vidDur.parentNode.insertBefore(box, vidDur);
      document.getElementById('vid-model-select').addEventListener('change', onVidModelChange);

      const extAdv = document.querySelector('#vid-extend .photos-col-adv');
      if (extAdv && !document.getElementById('extend-model-box')) {
        const ebox = document.createElement('div');
        ebox.className = 'studio-model-box';
        ebox.id = 'extend-model-box';
        ebox.style.marginTop = '0';
        ebox.innerHTML =
          '<div class="studio-model-head"><span class="studio-model-label">Extend model</span></div>' +
          '<select id="extend-model-select" class="studio-model-select" aria-label="Extend model"><option value="grok">Grok Imagine (Default · 6 cr/s)</option></select>' +
          '<div id="extend-res-wrap" class="studio-model-opts" style="display:none"><span class="studio-opt-label">Quality</span><div class="style-chips photos-split-chips" id="extend-res-chips"></div></div>';
        extAdv.insertBefore(ebox, extAdv.firstChild);
        document.getElementById('extend-model-select').addEventListener('change', onExtendModelChange);
      }

      try {
        const res = await fetch('/api/spicy/studio-models?modality=video&spicy=0');
        const data = await res.json();
        state.videoModels = (data && data.models) || [];
        populateVideoSelect('vid-model-select', state.videoModels, false);
        onVidModelChange();
        populateVideoSelect('extend-model-select', state.videoModels, true);
        onExtendModelChange();
      } catch (_e) {}
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountStudioModels);
  } else {
    mountStudioModels();
  }
})(window);
