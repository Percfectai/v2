/**
 * Percfect Productions — site chrome + library import + film polish hooks.
 */
(function () {
  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function injectStyles() {
    if (document.getElementById("pp-film-css")) return;
    var css = document.createElement("style");
    css.id = "pp-film-css";
    css.textContent = [
      /* Match Percfect World chrome */
      "body.bg-bg{background:#07080c !important;}",
      "header.flex.items-center{min-height:56px;padding-top:10px !important;padding-bottom:10px !important;",
      "  border-bottom:1px solid rgba(224,169,78,.22) !important;background:rgba(8,10,14,.92) !important;}",
      "header a[aria-label] img,#pp-site-logo{height:40px !important;width:auto !important;max-width:200px;",
      "  object-fit:contain !important;display:block;}",
      "#pp-wallet{margin-left:auto;display:flex;align-items:center;gap:8px;}",
      "#pp-wallet .chip{font:600 12px/1 system-ui,sans-serif;padding:6px 10px;border-radius:999px;",
      "  border:1px solid rgba(224,169,78,.35);color:#e0a94e;background:rgba(0,0,0,.35);}",
      "#pp-wallet a{font:600 11px/1 system-ui,sans-serif;color:rgba(200,210,230,.55);text-decoration:none;",
      "  letter-spacing:.08em;text-transform:uppercase;}",
      "#pp-wallet a:hover{color:#e0a94e;}",
      /* Film-strip clips on timeline */
      ".timeline-hatch [data-clip]{border-radius:4px !important;",
      "  box-shadow:inset 0 0 0 1px rgba(224,169,78,.25), 0 4px 12px rgba(0,0,0,.35) !important;}",
      ".timeline-hatch [data-clip]::before,.timeline-hatch [data-clip]::after{",
      "  content:'';position:absolute;top:0;bottom:0;width:6px;opacity:.55;",
      "  background:repeating-linear-gradient(180deg,#111 0 4px,transparent 4px 8px);pointer-events:none;}",
      ".timeline-hatch [data-clip]::before{left:0;}",
      ".timeline-hatch [data-clip]::after{right:0;}",
      /* Library FAB match homepage */
      "#user-lib-fab{right:22px !important;bottom:calc(22px + env(safe-area-inset-bottom,0px)) !important;",
      "  width:60px !important;height:60px !important;border-radius:50% !important;",
      "  border:1px solid rgba(57,192,230,.35) !important;background:rgba(8,12,22,.92) !important;",
      "  box-shadow:0 10px 28px rgba(0,0,0,.5),0 0 24px rgba(57,192,230,.25) !important;}",
      "#user-lib-fab img{width:40px !important;height:40px !important;object-fit:contain !important;",
      "  animation:ppLibSpin 6s linear infinite;filter:drop-shadow(0 0 8px rgba(57,192,230,.6));}",
      "@keyframes ppLibSpin{from{transform:rotateY(0)}to{transform:rotateY(360deg)}}",
      /* Music bottom-left clear of library */
      ".percfect-site-music{left:1rem !important;right:auto !important;bottom:1.25rem !important;",
      "  transform:none !important;z-index:1100 !important;}",
      /* Always-available Add videos strip (upload + library) */
      "#pp-cta{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;padding:14px;",
      "  border-bottom:1px solid rgba(224,169,78,.18);background:rgba(12,14,20,.9);}",
      "#pp-cta button,#pp-cta a.btn{font:700 12px/1 system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;",
      "  padding:10px 14px;border-radius:999px;border:1px solid rgba(224,169,78,.4);cursor:pointer;",
      "  background:rgba(224,169,78,.12);color:#f2efe8;text-decoration:none;}",
      "#pp-cta button.primary,#pp-cta a.primary{background:#e0a94e;color:#111;border-color:#e0a94e;}",
      "#pp-cta .pp-note{font:500 11px/1.3 system-ui,sans-serif;color:rgba(200,210,230,.55);width:100%;text-align:center;}",
    ].join("");
    document.head.appendChild(css);
  }

  function fixLogo() {
    var header = document.querySelector("header");
    if (!header) return;
    var link = header.querySelector('a[aria-label]');
    var brand = link || header.firstElementChild;
    if (!brand) return;
    if (!brand.querySelector("#pp-site-logo")) {
      brand.innerHTML =
        '<img id="pp-site-logo" src="/static/layouts/percfect-site/home/logo-clear.png" alt="PERCFECT STUDIOS" ' +
        'onerror="this.src=\'/static/assets/brand/logo_percfect_studios.jpg\'" />';
      if (link) link.setAttribute("href", "/");
    }
    // Wallet chips in header
    if (!document.getElementById("pp-wallet")) {
      var w = document.createElement("div");
      w.id = "pp-wallet";
      w.innerHTML =
        '<span class="chip"><span id="ppCr">…</span> credits</span>' +
        '<a href="/re-up">Re-Up</a>';
      // insert before the ml-auto actions if present
      var actions = header.querySelector(".ml-auto");
      if (actions) header.insertBefore(w, actions);
      else header.appendChild(w);
      fetch("/api/me", { credentials: "same-origin" })
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .then(function (d) {
          var el = document.getElementById("ppCr");
          if (!el || !d) return;
          var cr =
            (d.picture_credits || 0) +
            (d.video_credits || 0) +
            (d.credits || d.balance || 0);
          el.textContent = String(cr || 0);
        })
        .catch(function () {
          var el = document.getElementById("ppCr");
          if (el) el.textContent = "—";
        });
    }
  }

  function ensureCta() {
    if (document.getElementById("pp-cta")) return;
    var cta = document.createElement("div");
    cta.id = "pp-cta";
    cta.innerHTML =
      '<button type="button" class="primary" id="ppAddVideos">Add videos</button>' +
      '<button type="button" id="ppOpenFolder">Open folder</button>' +
      '<button type="button" id="ppOpenLib">Add from library</button>' +
      '<a class="btn" href="/create">Back to Create</a>' +
      '<div class="pp-note">Add anytime — upload files or pull from Library. Drag works too.</div>' +
      '<input type="file" id="ppAddVideosInput" accept="video/*,.mp4,.webm,.mov,.m4v,.mkv" multiple hidden />';
    var app = document.getElementById("app");
    if (app && app.parentNode) app.parentNode.insertBefore(cta, app);
    else document.body.insertBefore(cta, document.body.firstChild);

    function importFileList(fileList) {
      var files = Array.prototype.slice.call(fileList || []).filter(function (f) {
        return f && (String(f.type || "").indexOf("video") === 0 || /\.(mp4|webm|mov|m4v|mkv)$/i.test(f.name || ""));
      });
      if (!files.length) {
        alert("Pick one or more video files");
        return;
      }
      if (typeof window.__ppImportFiles === "function") {
        window.__ppImportFiles(files, "upload");
      } else {
        alert("Stitcher still loading — try again in a second");
      }
    }

    document.getElementById("ppAddVideos").onclick = function () {
      document.getElementById("ppAddVideosInput").click();
    };
    document.getElementById("ppAddVideosInput").onchange = function (ev) {
      importFileList(ev.target.files);
      ev.target.value = "";
    };
    document.getElementById("ppOpenFolder").onclick = function () {
      var inp = document.querySelector('input[webkitdirectory], input[type="file"][multiple]');
      if (inp) inp.click();
      else document.getElementById("ppAddVideosInput").click();
    };
    document.getElementById("ppOpenLib").onclick = function () {
      var fab = document.getElementById("user-lib-fab");
      if (fab) fab.click();
      else alert("Library loading — try again in a second");
    };
  }

  async function filesFromLibraryItems(items) {
    var files = [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var url = it.url || it.src || it.video_url || it.file_url;
      if (!url) continue;
      try {
        var res = await fetch(url, { credentials: "same-origin" });
        if (!res.ok) throw new Error("fetch " + res.status);
        var blob = await res.blob();
        var name = it.name || it.fileName || it.title || "clip-" + (i + 1) + ".mp4";
        if (!/\.(mp4|webm|mov|m4v|mkv)$/i.test(name)) name += ".mp4";
        files.push(new File([blob], name, { type: blob.type || "video/mp4" }));
      } catch (e) {
        console.warn("library video import failed", e);
      }
    }
    return files;
  }

  async function importVideosFromItems(items) {
    var files = await filesFromLibraryItems(items);
    if (!files.length) return false;
    if (typeof window.__ppImportFiles === "function") {
      await window.__ppImportFiles(files, "library");
      return true;
    }
    return false;
  }

  function wireLibrary() {
    window.addEventListener("percfect:library-use", function (ev) {
      var d = (ev && ev.detail) || {};
      var kind = d.kind || d.type || "";
      var url = d.url || d.src || d.video_url || d.file_url;
      if (!url) return;
      if (String(kind).indexOf("video") < 0 && !/\.(mp4|webm|mov)(\?|$)/i.test(url)) return;
      importVideosFromItems([d]);
    });
  }

  function boot() {
    injectStyles();
    fixLogo();
    ensureCta();
    wireLibrary();
    var n = 0;
    var t = setInterval(function () {
      fixLogo();
      if (++n > 30) clearInterval(t);
    }, 300);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
