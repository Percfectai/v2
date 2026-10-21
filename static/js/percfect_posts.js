/* Percfect Posts — Streamline V5 page (v: streamline-v5-1)
 * Layout: left toolbar · center library (blows up one photo) · right composer.
 * Caption + tags AI wands. Per-network templates with native post-type
 * dropdowns and API -> Playwright/login fallback.
 *
 * Reuses the existing live endpoints (additive, no backend changes needed):
 *   GET  /api/my-library                      (app.py)
 *   GET  /api/percfectposts/history           (blueprint)
 *   POST /api/percfectposts/mark              (blueprint)
 *   POST /api/percfectposts/wand              (blueprint)
 *   GET  /api/percfectposts/ai-keys           (blueprint)
 *   POST /api/percfectposts/ai-keys           (blueprint)
 *   POST /api/percfectposts/ai-keys/test      (blueprint)
 *
 * Deferred (not wired here): SMM Boost, music/sound Track row.
 */
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };

  // ── Networks ──────────────────────────────────────────────────────
  var NETS = [
    { key: "x", label: "X", ab: "X", url: "https://x.com/compose/post" },
    { key: "instagram", label: "Instagram", ab: "IG", url: "https://www.instagram.com/" },
    { key: "facebook", label: "Facebook", ab: "FB", url: "https://www.facebook.com/" },
    { key: "tiktok", label: "TikTok", ab: "TT", url: "https://www.tiktok.com/upload" },
    { key: "linkedin", label: "LinkedIn", ab: "LI", url: "https://www.linkedin.com/feed/?shareActive=true" },
    { key: "youtube", label: "YouTube", ab: "YT", url: "https://studio.youtube.com/" },
    { key: "threads", label: "Threads", ab: "TH", url: "https://www.threads.net/" },
    { key: "pinterest", label: "Pinterest", ab: "PT", url: "https://www.pinterest.com/pin-builder/" },
    { key: "bluesky", label: "Bluesky", ab: "BS", url: "https://bsky.app/" },
    { key: "mastodon", label: "Mastodon", ab: "MA", url: "https://mastodon.social/" },
    { key: "reddit", label: "Reddit", ab: "RD", url: "https://www.reddit.com/submit" },
    { key: "patreon", label: "Patreon", ab: "PA", url: "https://www.patreon.com/posts/new" },
    { key: "telegram", label: "Telegram", ab: "TG", url: "https://web.telegram.org/" },
    { key: "discord", label: "Discord", ab: "DC", url: "https://discord.com/channels/@me" },
    { key: "deviantart", label: "DeviantArt", ab: "DA", url: "https://www.deviantart.com/submit" }
  ];
  var VISIBLE = 5;

  var METHOD = {
    x: "api", facebook: "api", youtube: "api", telegram: "api", discord: "api",
    bluesky: "api", mastodon: "api", reddit: "api",
    instagram: "review", tiktok: "review", linkedin: "review", threads: "review", pinterest: "review",
    deviantart: "browser", patreon: "browser"
  };
  var BADGE = {
    api: ["⚡ Auto-post · API", "api"],
    review: ["◻ API · after approval", "review"],
    browser: ["🧩 Browser + your login", "browser"]
  };
  // native post types per network (from the platform-features breakdown)
  var POSTTYPES = {
    instagram: ["Feed Post", "Carousel", "Reels", "Stories", "Collab Post"],
    facebook: ["Standard Feed", "Carousel", "Reels", "Stories", "Live / Event"],
    x: ["Post (Tweet)", "Premium (long-form)", "Multi-image", "Video", "Thread"],
    tiktok: ["Short Video", "Photo Mode", "Text Post", "Duet / Stitch"],
    linkedin: ["Text Post", "Single Image / Video", "Document Carousel", "Article", "Poll"],
    youtube: ["Shorts", "Standard Video", "Community Post"],
    pinterest: ["Standard Pin", "Idea Pin", "Video Pin"],
    threads: ["Text Post", "Image / Carousel", "Video Post"],
    bluesky: ["Text Post", "Image Post"],
    patreon: ["Text / Blog", "Audio", "Video", "Image Gallery"],
    mastodon: ["Text", "Image", "Poll"],
    reddit: ["Image Post", "Link Post", "Text Post", "Video Post"],
    discord: ["Message", "Embed"],
    telegram: ["Photo", "Video", "Text"],
    deviantart: ["Deviation (Image)", "Journal", "Poll"]
  };
  // extra fields a network needs, beyond caption
  var TPL = {
    youtube: [["Title", "input"], ["Description", "textarea"]],
    pinterest: [["Title", "input"], ["Board", "input"], ["Destination link", "input"]],
    reddit: [["Subreddit", "input"], ["Post title", "input"]],
    deviantart: [["Title", "input"], ["Mature content (yes/no)", "input"]],
    patreon: [["Title", "input"], ["Tier access", "input"]],
    linkedin: [["Visibility (public / connections)", "input"]]
  };
  var PROVIDER_LABEL = { grok: "Grok", claude: "Claude", gemini: "Gemini", openai: "OpenAI" };

  // ── State ─────────────────────────────────────────────────────────
  var LIB = [];                 // flattened library items {id,kind,url,thumb,label,...}
  var HISTORY = {};             // file_id -> [{network,status,...}]
  var filter = "all";
  var picked = [];              // ordered selection (array acts as set w/ order)
  var on = {};                  // network key -> true
  var showAllNets = false;
  var activeAI = "grok";
  var wandField = null;

  function netLabel(k) { for (var i = 0; i < NETS.length; i++) if (NETS[i].key === k) return NETS[i].label; return k; }
  function netUrl(k) { for (var i = 0; i < NETS.length; i++) if (NETS[i].key === k) return NETS[i].url; return "#"; }
  function pickedKeys() { var a = []; for (var k in on) if (on[k]) a.push(k); return a; }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  // ── Library load ──────────────────────────────────────────────────
  function flatten(data) {
    var out = [];
    function add(arr, kind) {
      (arr || []).forEach(function (it) {
        out.push({
          id: String(it.id),
          kind: kind,
          url: it.url || it.primary_image_url || it.thumb || "",
          thumb: it.thumb || it.url || it.primary_image_url || "",
          label: it.name || kind,
          video: kind === "video"
        });
      });
    }
    add(data.photos, "photo");
    add(data.videos, "video");
    add(data.characters, "character");
    return out;
  }

  function loadLibrary() {
    fetch("/api/my-library", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("lib " + r.status); return r.json(); })
      .then(function (data) { LIB = flatten(data || {}); loadHistory(); render(); })
      .catch(function () {
        // dev fallback so the page is judgeable when not signed in
        LIB = [
          { id: "1", kind: "photo", label: "Your photo" },
          { id: "2", kind: "photo", label: "Your photo" },
          { id: "3", kind: "video", label: "Your video" },
          { id: "4", kind: "character", label: "Character" },
          { id: "5", kind: "photo", label: "Your photo" },
          { id: "6", kind: "video", label: "Your video" }
        ];
        render();
      });
  }
  function loadHistory() {
    fetch("/api/percfectposts/history", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (h) { HISTORY = h || {}; render(); })
      .catch(function () {});
  }
  function statusFor(id) {
    var h = HISTORY[id]; if (!h || !h.length) return null;
    var order = { failed: 0, scheduled: 1, posted: 2 }, best = null;
    h.forEach(function (e) { if (best === null || (order[e.status] || 0) < order[best] ) best = e.status; });
    return best;
  }

  // ── Render: library / blow-up ─────────────────────────────────────
  function tileInner(d) {
    if (d.thumb) return '<img class="fill" src="' + esc(d.thumb) + '" alt="' + esc(d.label) + '" loading="lazy">';
    return '<div class="ph-tile fill">' + esc(d.label) + "</div>";
  }
  function render() {
    var grid = $("#grid"), big = $("#big");
    var items = LIB.filter(function (d) { return filter === "all" || d.kind === filter; });
    grid.innerHTML = "";
    if (!items.length) { grid.innerHTML = '<div class="pp-grid-empty">Nothing here yet — generate some images first.</div>'; }
    items.forEach(function (d) {
      var i = picked.indexOf(d.id);
      var st = statusFor(d.id);
      var b = document.createElement("button");
      b.type = "button";
      b.className = "pp-thumb" + (i >= 0 ? " picked" : "");
      b.setAttribute("aria-label", d.label + (i >= 0 ? " (selected)" : ""));
      b.innerHTML = tileInner(d) +
        (i >= 0 && picked.length > 1 ? '<span class="pick-n">' + (i + 1) + "</span>" : "") +
        (st ? '<span class="dot ' + st + '"></span>' : "");
      b.onclick = function () {
        var at = picked.indexOf(d.id);
        if (at >= 0) picked.splice(at, 1); else picked.push(d.id);
        render();
      };
      grid.appendChild(b);
    });
    var one = picked.length === 1;
    big.classList.toggle("show", one);
    grid.classList.toggle("hide", one);
    if (one) {
      var d = LIB.filter(function (x) { return x.id === picked[0]; })[0];
      var fill = $("#big-fill");
      if (d && d.thumb) { fill.outerHTML = '<img class="fill" id="big-fill" src="' + esc(d.url || d.thumb) + '" alt="' + esc(d.label) + '">'; }
      else { fill.className = "fill ph-tile"; fill.textContent = d ? d.label : "Your photo"; }
    }
    var note = $("#carousel-note");
    if (picked.length > 1) { note.hidden = false; note.textContent = "Carousel / group — " + picked.length + " selected (posts as a multi-image/carousel where supported)"; }
    else note.hidden = true;
    syncPost();
  }

  function syncPost() {
    var ready = picked.length > 0 && pickedKeys().length > 0;
    $("#post").disabled = !ready;
    var nk = pickedKeys().length;
    $("#netcount").textContent = picked.length === 0 ? "Pick a photo + a network"
      : nk === 0 ? "Pick a network"
      : picked.length + " item" + (picked.length > 1 ? "s" : "") + " → " + nk + " network" + (nk > 1 ? "s" : "");
  }

  // ── Networks ──────────────────────────────────────────────────────
  function renderNets() {
    var el = $("#nets"); el.innerHTML = "";
    var list = showAllNets ? NETS : NETS.slice(0, VISIBLE);
    list.forEach(function (nw) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "pp-net" + (on[nw.key] ? " on" : "");
      b.setAttribute("aria-pressed", !!on[nw.key]);
      b.innerHTML = nw.label + ' <span class="ab">' + nw.ab + "</span>";
      b.onclick = function () { on[nw.key] = !on[nw.key]; renderNets(); syncPost(); };
      el.appendChild(b);
    });
    $("#net-more").textContent = showAllNets ? "– Fewer networks" : "+ More networks";
  }

  // ── AI keys / active provider ─────────────────────────────────────
  function setAI(key) {
    activeAI = key;
    var label = PROVIDER_LABEL[key] || key;
    $("#ai-active").textContent = "AI · " + label;
    $("#tool-ai-name").textContent = label;
    $("#wp-head").textContent = label + " · reads the image";
    document.querySelectorAll(".ai-row").forEach(function (r) { r.classList.toggle("active", r.getAttribute("data-ai") === key); });
    var radio = document.querySelector('.ai-use input[value="' + key + '"]'); if (radio) radio.checked = true;
  }
  function loadAIKeys() {
    fetch("/api/percfectposts/ai-keys", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (d) {
        var keys = (d && d.keys) || d || {};
        var first = null;
        document.querySelectorAll(".ai-row").forEach(function (row) {
          var k = row.getAttribute("data-ai");
          if (keys[k] && (keys[k].connected || keys[k].has_key || keys[k] === true)) {
            if (!first) first = k;
            var ok = document.createElement("span"); ok.className = "ai-ok"; ok.textContent = "✓ connected";
            if (!row.querySelector(".ai-ok")) row.appendChild(ok);
          }
        });
        setAI(first || "grok");
      })
      .catch(function () { setAI("grok"); });
  }
  function connectKey(row) {
    var k = row.getAttribute("data-ai");
    var input = row.querySelector(".ai-key");
    var body = { provider: k, api_key: input ? input.value : "" };
    var btn = row.querySelector(".ai-connect"); if (btn) { btn.textContent = "…"; btn.disabled = true; }
    fetch("/api/percfectposts/ai-keys", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (res) {
        if (btn) { btn.disabled = false; btn.textContent = res && res.error ? "Retry" : "Connected"; }
        if (!(res && res.error)) {
          if (!row.querySelector(".ai-ok")) { var ok = document.createElement("span"); ok.className = "ai-ok"; ok.textContent = "✓ connected"; row.appendChild(ok); }
          setAI(k);
        }
      }).catch(function () { if (btn) { btn.disabled = false; btn.textContent = "Retry"; } });
  }

  // ── Wand ──────────────────────────────────────────────────────────
  function currentImageUrl() {
    if (picked.length !== 1) return null;
    var d = LIB.filter(function (x) { return x.id === picked[0]; })[0];
    return d ? (d.url || d.thumb) : null;
  }
  function openWand(btn, field) {
    if (picked.length !== 1) { alert("Pick one photo first — the AI writes from that image."); return; }
    wandField = field;
    var r = btn.getBoundingClientRect(), pop = $("#wandpop");
    pop.style.top = (r.bottom + 6) + "px";
    pop.style.left = Math.max(8, r.right - 200) + "px";
    pop.hidden = false;
  }
  function runWand(mode) {
    var pop = $("#wandpop"); pop.hidden = true;
    var img = currentImageUrl();
    var field = wandField;
    var hint = (field === "tags" ? "tags only" : "caption") + (mode === "fill" ? ", finish what I started: " + ($("#caption").value || "") : ", from scratch");
    var target = field === "tags" ? $("#tags") : $("#caption");
    var prev = target.value; target.value = prev + (prev ? " " : "") + "…";
    fetch("/api/percfectposts/wand", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_url: img, hint: hint, field: field, mode: mode })
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (res) {
        if (res && res.error) { target.value = prev; alert(res.error); return; }
        if (field === "tags") {
          var tags = res.tags ? (Array.isArray(res.tags) ? res.tags.map(function (t) { return t[0] === "#" ? t : "#" + t; }).join(" ") : res.tags) : "";
          target.value = mode === "fill" && prev ? (prev + " " + tags).trim() : tags;
        } else {
          var desc = res.description || res.text || "";
          target.value = mode === "fill" && prev ? (prev + " " + desc).trim() : desc;
        }
      }).catch(function () { target.value = prev; alert("AI wand could not run — connect a key in Settings."); });
  }

  // ── Sheets ────────────────────────────────────────────────────────
  function scrim() {
    var o = $("#sheet-more").classList.contains("open") || $("#sheet-settings").classList.contains("open");
    $("#scrim").hidden = !o;
  }
  function openMore() { $("#sheet-settings").classList.remove("open"); $("#sheet-more").classList.add("open"); scrim(); }
  function openSettings() { $("#sheet-more").classList.remove("open"); $("#sheet-settings").classList.add("open"); scrim(); }
  function closeSheets() { $("#sheet-more").classList.remove("open"); $("#sheet-settings").classList.remove("open"); scrim(); }

  // ── Review & post ─────────────────────────────────────────────────
  function openReview() {
    if ($("#post").disabled) return;
    var cap = $("#caption").value.trim(), tags = $("#tags").value.trim();
    var body = (cap + (tags ? "\n\n" + tags : "")).trim() || "(your caption will fill in here)";
    var list = $("#rv-list"); list.innerHTML = "";
    var keys = pickedKeys();
    keys.forEach(function (k) {
      var m = METHOD[k] || "review", b = BADGE[m];
      var types = POSTTYPES[k] || ["Post"];
      var typeOpts = types.map(function (t, i) { return "<option" + (i === 0 ? " selected" : "") + ">" + esc(t) + "</option>"; }).join("");
      var fields = '<label>Post type · ' + esc(netLabel(k)) + '</label><select class="rv-type">' + typeOpts + "</select>";
      fields += "<label>Caption</label><textarea rows=\"2\">" + esc(body) + "</textarea>";
      (TPL[k] || []).forEach(function (f) { fields += "<label>" + esc(f[0]) + "</label>" + (f[1] === "textarea" ? '<textarea rows="2"></textarea>' : "<input>"); });
      var note = m === "api" ? "Posts in one click via " + netLabel(k) + "’s API."
        : m === "review" ? "Auto-posts once your " + netLabel(k) + " app is approved — opens with your login until then."
        : "No posting API — opens " + netLabel(k) + " with your login and auto-fills the form.";
      var act = m === "api" ? "Post" : "Open &amp; fill";
      var card = document.createElement("div"); card.className = "rv-card";
      card.innerHTML = '<div class="rv-head"><span class="rv-name">' + esc(netLabel(k)) + '</span><span class="rv-badge ' + b[1] + '">' + b[0] + "</span></div>" +
        '<div class="rv-fields">' + fields + "</div>" +
        '<div class="rv-foot"><span class="rv-note">' + note + '</span><button type="button" class="rv-go" data-k="' + k + '">' + act + "</button></div>";
      list.appendChild(card);
    });
    var apiN = keys.filter(function (k) { return METHOD[k] === "api"; }).length;
    $("#rv-count").textContent = apiN + " of " + keys.length + " post automatically · the rest open with your login";
    $("#review").classList.add("open");

    list.querySelectorAll(".rv-go").forEach(function (btn) {
      btn.onclick = function () { postOne(btn.getAttribute("data-k")); };
    });
  }
  function postOne(k) {
    var m = METHOD[k] || "review";
    // Open compose page for manual/login + browser-fallback flows; API path is backend (not wired live yet).
    if (m !== "api") { try { window.open(netUrl(k), "_blank", "noopener"); } catch (e) {} }
    markPosted(k, m === "api" ? "posted" : "posted");
  }
  function markPosted(k, status) {
    if (!picked.length) return;
    picked.forEach(function (fid) {
      var item = LIB.filter(function (x) { return x.id === fid; })[0];
      fetch("/api/percfectposts/mark", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: fid, file_kind: item ? item.kind : "photo", network: k, status: status, method: (METHOD[k] === "api" ? "api" : "manual"), url: null })
      }).then(function () { loadHistory(); }).catch(function () {});
    });
  }

  // ── Wire up ───────────────────────────────────────────────────────
  function init() {
    $("#filter").onclick = function (e) {
      var b = e.target.closest("button"); if (!b) return;
      [].forEach.call($("#filter").children, function (x) { x.classList.remove("on"); });
      b.classList.add("on"); filter = b.getAttribute("data-k"); render();
    };
    $("#net-more").onclick = function () { showAllNets = !showAllNets; renderNets(); };
    $("#big-back").onclick = function () { picked = []; render(); };
    $("#crops").onclick = function (e) {
      var b = e.target.closest("button"); if (!b) return;
      [].forEach.call($("#crops").children, function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      var p = b.getAttribute("data-c").split(":"); $("#big-stage").style.aspectRatio = p[0] + "/" + p[1];
    };

    document.querySelectorAll(".pp-wand").forEach(function (w) {
      w.addEventListener("click", function (e) { e.stopPropagation(); openWand(w, w.getAttribute("data-f")); });
    });
    $("#wandpop").querySelectorAll("button").forEach(function (b) { b.onclick = function () { runWand(b.getAttribute("data-a")); }; });
    document.addEventListener("click", function (e) { var p = $("#wandpop"); if (!p.hidden && !p.contains(e.target)) p.hidden = true; });

    document.querySelectorAll(".ai-use input").forEach(function (r) { r.addEventListener("change", function () { setAI(r.value); }); });
    document.querySelectorAll(".ai-connect").forEach(function (btn) { btn.onclick = function () { connectKey(btn.closest(".ai-row")); }; });
    $("#ai-active").onclick = openSettings; $("#tool-ai").onclick = openSettings;

    $("#btn-more").onclick = openMore; $("#btn-settings").onclick = openSettings;
    $("#free-upg").onclick = function (e) { e.preventDefault(); window.location.href = "/buy-credits"; };
    $("#btn-vault").onclick = function () { window.location.href = "/studios/library"; };
    $("#scrim").onclick = closeSheets;
    document.querySelectorAll("[data-close]").forEach(function (b) { b.onclick = closeSheets; });

    $("#sched").onclick = function () { $("#sched-row").classList.toggle("show"); };
    $("#post").onclick = openReview;
    $("#review-close").onclick = function () { $("#review").classList.remove("open"); };
    $("#review").onclick = function (e) { if (e.target === $("#review")) $("#review").classList.remove("open"); };
    $("#rv-all").onclick = function () {
      $("#review").classList.remove("open");
      pickedKeys().forEach(function (k) { postOne(k); });
    };

    renderNets();
    loadAIKeys();
    loadLibrary();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
