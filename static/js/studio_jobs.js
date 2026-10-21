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
