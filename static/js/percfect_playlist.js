/**
 * Site-wide Percfect playlist — resumes across page navigations via localStorage.
 * Multi-page sites can't keep one <audio> alive on full reload; we save time +
 * playing flag and pick up on the next page within ~1s.
 */
(function () {
  if (window.__percfectPlaylist) return;
  window.__percfectPlaylist = true;

  var KEY = "percfect_playlist_v1";
  var TRACKS = [
    {
      src: "/static/assets/audio/perfect_ai_hero_cards.mp3",
      title: "Perfect AI · Hero Cards",
      sub: "Track 1 of 4",
    },
    {
      src: "/static/assets/audio/perfect_ai_pop.mp3",
      title: "Perfect AI Pop",
      sub: "Track 2 of 4",
    },
    {
      src: "/static/assets/audio/perfect_ai_pop_2.mp3",
      title: "Perfect AI Pop 2",
      sub: "Track 3 of 4",
    },
    {
      src: "/static/assets/audio/grizzly_reapers_tunnel.mp3",
      title: "Grizzly Reaper\u2019s Tunnel",
      sub: "Track 4 of 4",
    },
  ];

  function loadState() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || "{}") || {};
    } catch (e) {
      return {};
    }
  }
  function saveState(partial) {
    var s = Object.assign(loadState(), partial, { updated: Date.now() });
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch (e) {}
  }

  function ensureDom() {
    var bar = document.getElementById("percfectSiteMusic");
    if (bar) return bar;
    bar = document.createElement("div");
    bar.id = "percfectSiteMusic";
    bar.className = "percfect-site-music";
    bar.innerHTML =
      '<audio id="percfectSiteAudio" preload="metadata"></audio>' +
      '<button type="button" id="percfectSiteMusicBtn" aria-label="Play">▶</button>' +
      '<div class="percfect-site-music-meta">' +
      '<div class="percfect-site-music-title" id="percfectSiteMusicTitle"></div>' +
      '<div class="percfect-site-music-sub" id="percfectSiteMusicSub"></div>' +
      "</div>" +
      '<button type="button" id="percfectSiteMusicNext" aria-label="Next" title="Next">⏭</button>';
    document.body.appendChild(bar);
    if (!document.getElementById("percfectSiteMusicCss")) {
      var css = document.createElement("style");
      css.id = "percfectSiteMusicCss";
      css.textContent =
        /* Bottom-left so it doesn't cover studio options / library (BR) */
        ".percfect-site-music{position:fixed;bottom:1.25rem;left:1rem;right:auto;transform:none;z-index:1100;" +
        "display:flex;align-items:center;gap:.5rem;padding:.45rem .7rem;border-radius:999px;" +
        "background:rgba(8,12,22,.94);border:1px solid rgba(94,231,255,.28);backdrop-filter:blur(10px);" +
        "box-shadow:0 8px 28px rgba(0,0,0,.5);max-width:min(72vw,380px);font-family:system-ui,sans-serif}" +
        ".percfect-site-music button{width:2rem;height:2rem;border-radius:50%;background:rgba(94,231,255,.12);" +
        "border:1px solid rgba(94,231,255,.4);color:#5ee7ff;font-size:.72rem;display:grid;place-items:center;cursor:pointer;flex-shrink:0}" +
        ".percfect-site-music-meta{min-width:0;flex:1}" +
        ".percfect-site-music-title{font-size:.68rem;font-weight:700;color:#f2f6ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
        ".percfect-site-music-sub{font-size:.52rem;color:rgba(200,215,240,.55);letter-spacing:.06em;text-transform:uppercase}" +
        /* Sit above Vanessa FAB when present (also bottom-left on some pages) */
        "body:has(#vanessa-fab) .percfect-site-music,body:has(.vanessa-fab) .percfect-site-music{bottom:5.5rem}" +
        "@media(max-width:420px){.percfect-site-music{bottom:1rem;left:.65rem;padding:.4rem .55rem;max-width:78vw}" +
        "body:has(#vanessa-fab) .percfect-site-music{bottom:5.25rem}}";
      document.head.appendChild(css);
    }
    return bar;
  }

  function boot() {
    ensureDom();
    var audio = document.getElementById("percfectSiteAudio");
    var btn = document.getElementById("percfectSiteMusicBtn");
    var nextBtn = document.getElementById("percfectSiteMusicNext");
    var titleEl = document.getElementById("percfectSiteMusicTitle");
    var subEl = document.getElementById("percfectSiteMusicSub");
    var state = loadState();
    var idx = Math.max(0, Math.min(TRACKS.length - 1, parseInt(state.i, 10) || 0));

    // Home page: jukebox skin only — hide the plain floating bar
    var path = (location.pathname || "/").replace(/\/$/, "") || "/";
    if (path === "/" || path === "/home" || path === "/homebase" || path === "/percfectstudios") {
      var bar = document.getElementById("percfectSiteMusic");
      if (bar) bar.style.display = "none";
    }

    // One sound at a time: any other media pauses site music; site music pauses other media
    function pauseOthers(except) {
      try {
        document.querySelectorAll("audio, video").forEach(function (el) {
          if (el === except) return;
          if (!el.paused) el.pause();
        });
      } catch (e) {}
    }
    document.addEventListener(
      "play",
      function (e) {
        var t = e.target;
        if (!t || (t.tagName !== "AUDIO" && t.tagName !== "VIDEO")) return;
        pauseOthers(t);
        if (t !== audio && t.id !== "jbAudio") {
          // Video/other audio started — mark music paused in shared state
          saveState({ playing: false, t: audio.currentTime || 0, i: idx });
        }
      },
      true
    );
    window.percfectPauseAllMedia = function () {
      pauseOthers(null);
    };
    window.percfectPauseMusic = function () {
      if (audio && !audio.paused) audio.pause();
      var jb = document.getElementById("jbAudio");
      if (jb && !jb.paused) jb.pause();
    };

    function applyTrack(i, seek) {
      idx = i;
      var t = TRACKS[idx];
      if (!t) return;
      if (titleEl) titleEl.textContent = t.title;
      if (subEl) subEl.textContent = t.sub;
      var want = seek != null ? seek : 0;
      if (audio.getAttribute("src") !== t.src) {
        audio.src = t.src;
      }
      var onMeta = function () {
        audio.removeEventListener("loadedmetadata", onMeta);
        try {
          if (want > 0 && isFinite(audio.duration) && want < audio.duration) {
            audio.currentTime = want;
          }
        } catch (e) {}
      };
      audio.addEventListener("loadedmetadata", onMeta);
      if (audio.readyState >= 1) onMeta();
    }

    function syncBtn() {
      btn.textContent = audio.paused ? "▶" : "❚❚";
      btn.setAttribute("aria-label", audio.paused ? "Play" : "Pause");
    }

    function persist() {
      saveState({
        i: idx,
        t: audio.currentTime || 0,
        playing: !audio.paused,
      });
    }

    applyTrack(idx, parseFloat(state.t) || 0);

    btn.addEventListener("click", function () {
      if (audio.paused) {
        audio.play().catch(function () {});
      } else {
        audio.pause();
      }
      syncBtn();
      persist();
    });

    nextBtn.addEventListener("click", function () {
      var was = !audio.paused;
      applyTrack((idx + 1) % TRACKS.length, 0);
      if (was) audio.play().catch(function () {});
      syncBtn();
      persist();
    });

    audio.addEventListener("play", function () {
      syncBtn();
      persist();
    });
    audio.addEventListener("pause", function () {
      syncBtn();
      persist();
    });
    audio.addEventListener("ended", function () {
      applyTrack((idx + 1) % TRACKS.length, 0);
      audio.play().catch(function () {});
      persist();
    });
    audio.addEventListener("timeupdate", function () {
      if (!audio.paused && Math.floor(audio.currentTime) % 2 === 0) persist();
    });

    window.addEventListener("pagehide", persist);
    window.addEventListener("beforeunload", persist);

    // Resume if it was playing on the previous page
    if (state.playing) {
      audio.play().catch(function () {
        /* autoplay blocked until user taps once site-wide */
      });
    }
    syncBtn();

    // Hide duplicate page-local song bars so we don't get two players
    document.querySelectorAll(".song-bar, #songBar").forEach(function (el) {
      if (el.id !== "percfectSiteMusic") el.style.display = "none";
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
