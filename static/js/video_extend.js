/**
 * Shared video extend — Arena, Motion, Studios.
 * One input: { file } or { url } → POST /percfectstudios/extend-video
 * (video_file or video_url — backend resolves to the same xAI video payload).
 */
(function (global) {
  const ENDPOINT = '/percfectstudios/extend-video';

  function buildPrompt(promptId) {
    const extra = (document.getElementById(promptId)?.value || '').trim();
    return extra ? ('extend this video ' + extra) : 'extend this video';
  }

  function progressMaxSec(sec) {
    const s = parseInt(sec, 10) || 6;
    return 180 + s * 45;
  }

  function applyVideo(videoEl, url, cfg) {
    if (!videoEl || !url) return;
    const bust = url + (url.includes('?') ? '&' : '?') + 't=' + Date.now();
    videoEl.onerror = () => {
      if (cfg.onError) cfg.onError('Extended video failed to load — try Download or run Extend again.');
    };
    videoEl.pause();
    videoEl.src = bust;
    videoEl.style.display = 'block';
    if (cfg.placeholderId) {
      const ph = document.getElementById(cfg.placeholderId);
      if (ph) ph.style.display = 'none';
    }
    videoEl.load();
    videoEl.play().catch(() => {});
  }

  function deductCredits(creditsId, secs) {
    const el = document.getElementById(creditsId);
    if (!el) return;
    const n = parseInt(el.textContent, 10);
    if (!isNaN(n)) el.textContent = Math.max(0, n - secs);
  }

  function bind(cfg) {
    let extendSec = cfg.defaultSec || 6;
    let timer = null;
    // Video billing is credits-per-second (default 6); override via cfg.creditsPerSecond
    const rate = Math.max(1, parseInt(cfg.creditsPerSecond, 10) || 6);
    function creditCost(sec) {
      return Math.max(1, (parseInt(sec, 10) || extendSec) * rate);
    }

    function setDuration(sec, chipEl) {
      extendSec = sec;
      if (cfg.chipsSelector) {
        const chipSel = cfg.chipSelector || '.dur-chip, .style-chip';
        document.querySelectorAll(cfg.chipsSelector + ' ' + chipSel).forEach((c) => {
          c.classList.remove('selected', 'active', cfg.chipActiveClass || 'selected');
        });
        if (chipEl) chipEl.classList.add(cfg.chipActiveClass || 'selected');
      }
      const cost = document.getElementById(cfg.costId);
      if (cost) cost.textContent = creditCost(sec);
    }

    // Stage-based progress: filled from real job status (queued/processing/done),
    // not elapsed seconds. Returns onProgress fn stored on `stageProg`.
    let stageProg = null;
    function startProgress() {
      const wrap = document.getElementById(cfg.progressWrap);
      const bar = document.getElementById(cfg.progressBar);
      const el = document.getElementById(cfg.progressElapsed);
      if (wrap) wrap.style.display = '';
      if (bar) bar.style.width = '0%';
      if (el) { el.textContent = ''; el.style.display = 'none'; }
      if (timer) { clearInterval(timer); timer = null; }
      stageProg = (global.PercfectStudioJobs && global.PercfectStudioJobs.makeStageProgress)
        ? global.PercfectStudioJobs.makeStageProgress({
            bar: cfg.progressBar,
            label: cfg.progressLabel || null,
          })
        : null;
      if (stageProg) stageProg({ status: 'queued' }, 'Starting…');
    }

    function stopProgress(success) {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      const bar = document.getElementById(cfg.progressBar);
      const wrap = document.getElementById(cfg.progressWrap);
      if (success) {
        if (stageProg && stageProg.done) stageProg.done('Done');
        else if (bar) bar.style.width = '100%';
        setTimeout(() => { if (wrap) wrap.style.display = 'none'; }, 400);
      } else {
        if (stageProg && stageProg.reset) stageProg.reset();
        else if (bar) bar.style.width = '0%';
        if (wrap) wrap.style.display = 'none';
      }
    }

    function resetBtn(btn) {
      if (!btn) return;
      btn.disabled = false;
      btn.innerHTML = '⤢ Extend (<span id="' + cfg.costId + '">' + creditCost(extendSec) + '</span> credits)';
    }

    function fail(msg) {
      // Hard stop: always tell the user the real error (progress stopped in finally)
      const text = (msg && String(msg).trim()) || 'Extend failed. You were not charged.';
      if (cfg.onError) cfg.onError(text);
    }

    async function run() {
      if (cfg.onBefore) {
        const ok = cfg.onBefore();
        if (ok === false) return;
      }
      const src = cfg.getSource ? cfg.getSource() : null;
      if (!src || (!src.url && !src.file)) {
        fail(cfg.noSourceMsg || 'No video to extend yet. Drop an MP4 or generate one first.');
        return;
      }

      const btn = document.getElementById(cfg.btnId);
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Extending…';
      }
      startProgress();

      const fd = new FormData();
      if (src.file) fd.append('video_file', src.file);
      else fd.append('video_url', src.url);
      fd.append('duration', extendSec);
      fd.append('prompt', buildPrompt(cfg.promptId));

      let ok = false;
      try {
        const res = await fetch(ENDPOINT, { method: 'POST', body: fd, credentials: 'same-origin' });
        let data;
        try {
          data = global.PercfectStudioJobs
            ? await global.PercfectStudioJobs.resolveGenerationResponse(res, {
                kind: 'extend',
                onProgress: (d, label) => { if (stageProg) stageProg(d, label); },
              })
            : await res.json();
        } catch (e) {
          // Timeout / failed job / network inside poll — stop and show exact message
          fail((e && e.message) || 'Extend failed. You were not charged.');
          return;
        }
        if (!data || !data.url) {
          fail((data && data.error) || 'Extend failed — no video returned. You were not charged.');
          return;
        }
        const videoEl = document.getElementById(cfg.videoId);
        applyVideo(videoEl, data.url, cfg);
        if (cfg.downloadId) {
          const dl = document.getElementById(cfg.downloadId);
          if (dl) dl.dataset.url = data.url;
        }
        if (cfg.actionsId) {
          const actions = document.getElementById(cfg.actionsId);
          if (actions) actions.style.display = 'flex';
        }
        if (cfg.creditsId) {
          const charged = (data && data.charged != null) ? data.charged : creditCost(extendSec);
          deductCredits(cfg.creditsId, charged);
        }
        if (cfg.onSuccess) cfg.onSuccess(data);
        ok = true;
      } catch (e) {
        fail((e && e.message) || 'Connection lost during extend. Generation stopped. You were not charged — try again.');
      } finally {
        stopProgress(ok);
        resetBtn(btn);
      }
    }

    return { setDuration, run, getSec: () => extendSec };
  }

  global.PercfectVideoExtend = { bind, buildPrompt, progressMaxSec, applyVideo };
})(window);
