/* Percfect Card Studio — front + back on /studios/trading-cards only */
(function () {
  const ASSET = "/static/assets";
  const API = "/studios/trading-cards";

  const FONTS = [
    { id: "hero", label: "Hero" },
    { id: "gothic", label: "Gothic" },
    { id: "script", label: "Script" },
    { id: "serif", label: "Serif" },
    { id: "stencil", label: "Stencil" },
  ];
  // Rarity: the border shows on front and back; Silver / Holo re-render the art with AI (charged).
  const FINISHES = [
    { id: "standard", label: "Standard", rarity: "R" },
    { id: "silver", label: "Silver Rare · 2 credits", rarity: "S" },
    { id: "holo", label: "Super Rare Hologram · 2 credits", rarity: "G" },
  ];
  const BACKDROPS = [
    { id: "dc", label: "DC", src: ASSET + "/cards/themes/dc.jpg" },
    { id: "marvel", label: "Marvel", src: ASSET + "/cards/themes/marvel.jpg" },
    { id: "got", label: "GOT", src: ASSET + "/cards/themes/got.jpg" },
    { id: "villain", label: "Villain", src: ASSET + "/cards/themes/villain.jpg" },
  ];
  const KEYS = {
    men: ["Attack", "Defence", "Speed", "Swag"],
    women: ["Attack", "Defence", "Beauty", "Seduction"],
    villains: ["Attack", "Defence", "Deviousness", "Swag"],
  };
  // Same four mechanics on every card (handoff Part 2); the AI writes each character's version.
  const SKILL_EFFECTS = ["Weakest stat +50", "Opponent's best stat → 0", "All stats +50", "Wins vs any lower level"];
  // XP to reach Lv1..Lv4 (handoff Part 3.1); LEVEL_XP[level] = XP needed for the next level.
  const LEVEL_XP = [0, 1000, 3000, 7000];
  const SKILL_RULES = [
    "Weakest stat +50 · never wins the fight on its own",
    "Opponent's strongest stat → 0",
    "All stats +50",
    "Automatic win vs any lower level · vs another level 4: strongest asset, played tactically",
  ];
  const CHARACTER_DRAG = "application/x-percfect-character";
  const LIBRARY_DRAG = "application/x-percfect-library";
  const rosterById = {};

  function blank() {
    return {
      id: null,
      name: "CHARACTER NAME",
      tagline: "ALIAS",
      dossier: "",
      number: 0,
      rarity: "R",
      theme: "H",
      role: "men",
      stats: KEYS.men.map((key) => ({ key, value: 0 })),
      // Shown only until the skills agent writes this character's own versions (handoff Part 2.2).
      // Blank until the AI (or the creator) writes what each skill looks like in the video.
      abilities: [0, 1, 2, 3].map(() => ({ name: "", description: "" })),
      level: 1,
      xp: 0,
      wins: 0,
      artUrl: null,
      charUrl: null, // clean character still, the reference for scene shots
      characterId: null, // the Supabase character this card saves onto
      atmosphere: "none",
      plateFont: "hero",
      backdrop: "none",
      customBackdrop: null,
    };
  }

  let card = blank();
  let flipped = false;
  let spinning = true; // the card turns (front, back) until they hit Stop or touch it
  const binder = [];

  function serial() {
    const n = Math.max(0, Number(card.number) || 0);
    const digits = n < 100 ? String(n).padStart(2, "0") : String(n);
    return card.rarity + card.theme + digits;
  }
  function sceneSrc() {
    if (card.customBackdrop) return card.customBackdrop;
    const hit = BACKDROPS.find((b) => b.id === card.backdrop);
    return hit ? hit.src : null;
  }
  function nameScale(n) {
    if ((n || "").length > 14) return "is-xlong";
    if ((n || "").length > 9) return "is-long";
    return "";
  }
  function isBlankName(n) {
    return !n || n === "CHARACTER NAME";
  }
  function isBlankAlias(t) {
    const s = (t || "").replace(/^["“”']+|["“”']+$/g, "");
    return !s || s === "ALIAS" || s === "Uncatalogued";
  }

  function renderFront() {
    const scene = sceneSrc();
    const name = isBlankName(card.name) ? "" : card.name;
    const alias = isBlankAlias(card.tagline) ? "" : card.tagline.replace(/^["“”']+|["“”']+$/g, "");
    // Nick 2026-09-28: stats are typed right on the card; tap the 4th label to switch Swag / Seduction.
    const stats = card.stats
      .slice(0, 4)
      .map((s, i) => {
        const key =
          i === 3
            ? `<button type="button" class="tc-stat-key tc-stat-toggle" data-role-toggle title="Tap to switch Swag / Seduction">${esc(s.key)}</button>`
            : `<span class="tc-stat-key">${esc(s.key)}</span>`;
        return `<li class="tc-stat">${key}<span class="tc-stat-cut"></span><input class="tc-stat-val tc-stat-input" data-statv="${i}" inputmode="numeric" maxlength="3" value="${s.value}" aria-label="${escAttr(s.key)}" /></li>`;
      })
      .join("");
    document.getElementById("front-stage").innerHTML = `
      <article class="tc-bezel tc-rarity-${card.rarity} tc-theme-${card.theme} tc-font-${card.plateFont || "hero"}">
        <div class="tc-window">
          ${scene ? `<img class="tc-backdrop-img" src="${scene}" alt="" />` : ""}
          ${
            card.artUrl
              ? `<img class="tc-art${scene ? " tc-art-on-backdrop" : ""}" src="${card.artUrl}" alt="" />`
              : scene
                ? ""
                : `<div class="tc-art-empty"><span>Drop your Character</span><small>Tap here, or drag one in from your library (bottom-right)</small></div>`
          }
          <div class="tc-vignette"></div>
          <button type="button" class="tc-font-chip no-capture" data-cycle-font title="Change the font">Aa · ${esc((FONTS.find((f) => f.id === (card.plateFont || "hero")) || FONTS[0]).label)}</button>
          <div class="tc-nameblock">
            <input class="tc-name-input ${nameScale(card.name)}" value="${escAttr(name)}" placeholder="Character name" maxlength="22" data-field="name" />
            <input class="tc-alias-input" value="${escAttr(alias)}" placeholder="ALIAS" maxlength="42" data-field="tagline" />
          </div>
          <label class="tc-num">no. <input class="tc-num-input" data-field="number" inputmode="numeric" maxlength="3" value="${card.number ? String(card.number).padStart(3, "0") : ""}" placeholder="—" aria-label="Card number" /></label>
          <ul class="tc-stats">${stats}</ul>
          <div class="tc-logo">
            <img src="${ASSET}/brand/card_logo_blue_p.png" alt="" />
            <span class="tc-serial">${serial()}</span>
          </div>
        </div>
      </article>`;
    document.querySelectorAll("#front-stage [data-field]").forEach((el) => {
      el.addEventListener("input", () => {
        if (el.dataset.field === "name") {
          // Keep the case as typed; CSS prints caps except in Script.
          card.name = (el.value || "CHARACTER NAME").slice(0, 22);
          el.className = `tc-name-input ${nameScale(card.name)}`;
          const backName = document.querySelector("#back-stage .tc-back-name");
          if (backName) backName.textContent = isBlankName(card.name) ? "UNNAMED" : card.name;
        }
        if (el.dataset.field === "tagline") card.tagline = el.value || "ALIAS";
        if (el.dataset.field === "number") {
          const raw = el.value.replace(/[^\d]/g, "").slice(0, 3);
          card.number = raw ? Number(raw) : 0;
          document.querySelectorAll(".tc-serial").forEach((s) => (s.textContent = serial()));
        }
      });
    });
  }

  function renderBack() {
    // Skill lists are public: locked skills still show, marked with the level that unlocks them.
    const abs = card.abilities
      .slice(0, 4)
      .map((a, i) => {
        const on = card.level >= i + 1;
        const lock = on ? "" : ` <span class="tc-ability-lock">🔒 unlocks at ${LEVEL_XP[i].toLocaleString()} XP</span>`;
        return `<li class="tc-ability${on ? "" : " is-locked"}">
          <div class="tc-ability-index">${String(i + 1).padStart(2, "0")}</div>
          <div><p class="tc-ability-name">${esc(a.name || "Level " + (i + 1))} <span class="tc-ability-effect">· ${esc(SKILL_EFFECTS[i])}</span>${lock}</p>
          <textarea class="tc-ability-desc" data-ab-desc="${i}" rows="2" maxlength="180" placeholder="What the video shows (AI writes this, or type your own)" aria-label="Level ${i + 1} skill">${esc(a.description)}</textarea></div>
        </li>`;
      })
      .join("");
    // Top half: name + description. Bottom half: the four skills. Very bottom: XP, wins, next unlock.
    const nextXp = LEVEL_XP[card.level];
    const unlock = nextXp ? `Level ${card.level + 1} unlocks at ${nextXp.toLocaleString()} XP` : "Max level";
    document.getElementById("back-stage").innerHTML = `
      <article class="tc-bezel tc-rarity-${card.rarity} tc-theme-${card.theme} tc-font-${card.plateFont || "hero"}">
        <div class="tc-window tc-window-back">
          <div class="tc-back-top">
            <h2 class="tc-back-name">${esc(isBlankName(card.name) ? "UNNAMED" : card.name)}</h2>
            <textarea class="tc-back-desc" rows="5" maxlength="220" placeholder="Add a short description…" aria-label="Short description">${esc(card.dossier || "")}</textarea>
            <button type="button" class="tc-ai-btn no-capture" data-describe>✍ AI description</button>
            ${card.craftedBy ? `<p class="tc-back-crafted">Crafted by ${esc(card.craftedBy)}</p>` : ""}
          </div>
          <ol class="tc-abilities">${abs}</ol>
          <div class="tc-back-foot"><span>Lv ${card.level}</span><span>${Number(card.xp || 0).toLocaleString()} XP</span><span>${card.wins} wins</span><span>${unlock}</span></div>
        </div>
      </article>`;
    // Type the description right on the back; the Bio box below stays in sync.
    const desc = document.querySelector("#back-stage .tc-back-desc");
    desc.addEventListener("input", () => {
      card.dossier = desc.value.slice(0, 220);
      const bio = document.getElementById("dossier");
      if (bio) bio.value = card.dossier;
    });
  }

  function renderChrome() {
    const fontSelect = document.getElementById("font-select");
    if (fontSelect) {
      fontSelect.innerHTML = FONTS.map(
        (f) => `<option value="${f.id}"${card.plateFont === f.id ? " selected" : ""}>${f.label}</option>`
      ).join("");
    }
    document.getElementById("sliders").innerHTML = card.stats
      .slice(0, 4)
      .map((s, i) => {
        const women = card.role === "women";
        const label =
          i === 3
            ? `<span class="studio-role" role="group" aria-label="Fourth stat"><button type="button" data-role="men" aria-pressed="${!women}" class="${women ? "" : "is-on"}">Swag</button><button type="button" data-role="women" aria-pressed="${women}" class="${women ? "is-on" : ""}">Seduction</button></span>`
            : `<span>${esc(s.key)}</span>`;
        const tint = i === 3 ? (women ? " is-girl" : " is-boy") : "";
        return `<div class="studio-slider${tint}">${label}<input type="range" min="0" max="100" value="${s.value}" data-stat="${i}" aria-label="${escAttr(s.key)}" /><b>${s.value}</b></div>`;
      })
      .join("");
    const finish = card.rarity === "G" ? "holo" : card.rarity === "S" ? "silver" : "standard";
    document.getElementById("finishes").innerHTML = FINISHES.map(
      (f) =>
        `<button type="button" class="press-chip${finish === f.id ? " is-on" : ""}" data-finish="${f.id}">${f.label}</button>`
    ).join("");
  }

  function paint() {
    renderFront();
    renderBack();
    renderChrome();
    bind();
    syncPreview();
  }

  // Center card = a live copy of both sides, spinning, look only (Nick 2026-09-28).
  let syncQueued = false;
  function syncPreview() {
    if (syncQueued) return;
    syncQueued = true;
    requestAnimationFrame(() => {
      syncQueued = false;
      [["front-stage", "front-preview"], ["back-stage", "back-preview"]].forEach(([from, to]) => {
        const src = document.getElementById(from);
        const dst = document.getElementById(to);
        if (!src || !dst) return;
        const copy = src.cloneNode(true);
        const a = src.querySelectorAll("input, textarea, select");
        copy.querySelectorAll("input, textarea, select").forEach((el, i) => {
          el.value = a[i].value;
          if (el.tagName === "TEXTAREA") el.textContent = a[i].value;
          else el.setAttribute("value", a[i].value);
          el.readOnly = true;
          el.tabIndex = -1;
        });
        copy.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
        copy.querySelectorAll(".no-capture").forEach((el) => el.remove());
        dst.replaceChildren(...copy.childNodes);
        dst.inert = true;
      });
    });
  }
  ["front-stage", "back-stage"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", syncPreview);
      el.addEventListener("change", syncPreview);
    }
  });

  function bind() {
    document.querySelectorAll("[data-statv]").forEach((el) =>
      el.addEventListener("input", () => {
        const i = Number(el.dataset.statv);
        const digits = el.value.replace(/\D/g, "").slice(0, 3);
        const v = Math.max(0, Math.min(100, Number(digits) || 0));
        if (el.value !== digits) el.value = digits;
        card.stats[i].value = v;
      })
    );
    document.querySelectorAll("[data-statv]").forEach((el) =>
      el.addEventListener("blur", () => {
        el.value = String(card.stats[Number(el.dataset.statv)].value);
        syncPreview();
      })
    );
    document.querySelectorAll("[data-role-toggle]").forEach((b) =>
      b.addEventListener("click", () => {
        setRole(card.role === "women" ? "men" : "women");
        paint();
      })
    );
    document.querySelectorAll("[data-cycle-font]").forEach((b) =>
      b.addEventListener("click", () => {
        const i = FONTS.findIndex((f) => f.id === (card.plateFont || "hero"));
        setFont(FONTS[(i + 1) % FONTS.length].id, false);
        b.textContent = "Aa · " + FONTS[(i + 1) % FONTS.length].label;
        syncPreview();
      })
    );
    document.querySelectorAll("[data-font]").forEach((b) => {
      // Keep the caret in the name while switching fonts.
      b.addEventListener("mousedown", (e) => e.preventDefault());
      b.addEventListener("click", (e) => setFont(b.dataset.font, e.detail > 0));
    });
    document.querySelectorAll("[data-stat]").forEach((el) =>
      el.addEventListener("input", () => {
        const i = Number(el.dataset.stat);
        const v = Math.max(0, Math.min(100, Number(el.value) || 0));
        card.stats[i].value = v;
        // Update the readout and the plate only; rebuilding the slider mid-drag ends the drag.
        el.nextElementSibling.textContent = v;
        const plateVal = document.querySelectorAll("#front-stage .tc-stat-val")[i];
        if (plateVal) plateVal.textContent = v;
      })
    );
    document.querySelectorAll("[data-role]").forEach((b) =>
      b.addEventListener("click", () => {
        setRole(b.dataset.role);
        paint();
      })
    );
    document.querySelectorAll("[data-finish]").forEach((b) =>
      b.addEventListener("click", () => applyFinish(FINISHES.find((x) => x.id === b.dataset.finish)))
    );
    document.querySelectorAll("[data-describe]").forEach((b) => b.addEventListener("click", describeWithAI));
    document.querySelectorAll("[data-ab-name]").forEach((el) =>
      el.addEventListener("input", () => {
        card.abilities[Number(el.dataset.abName)].name = el.value.slice(0, 28);
      })
    );
    document.querySelectorAll("[data-ab-desc]").forEach((el) =>
      el.addEventListener("input", () => {
        card.abilities[Number(el.dataset.abDesc)].description = el.value.slice(0, 180);
      })
    );
    document.querySelectorAll("[data-load]").forEach((b) =>
      b.addEventListener("click", () => {
        const hit = binder.find((c) => c.id === b.dataset.load);
        if (hit) {
          card = JSON.parse(JSON.stringify(hit));
          paint();
        }
      })
    );
  }

  function setRole(role) {
    const keys = KEYS[role] || KEYS.men;
    card.role = role === "women" ? "women" : role === "villains" ? "villains" : "men";
    card.stats = keys.map((key, i) => ({ key, value: card.stats[i] ? card.stats[i].value : 0 }));
  }

  function setFont(font, fromPointer) {
    card.plateFont = font;
    // Swap the class in place so the name field survives and keeps focus.
    document.querySelectorAll(".tc-bezel").forEach((el) => {
      el.className = el.className.replace(/\btc-font-[\w-]+/, "tc-font-" + font);
    });
    document.querySelectorAll("[data-font]").forEach((b) => b.classList.toggle("is-on", b.dataset.font === font));
    // Pick a font with the mouse, then just start typing.
    const name = document.querySelector("#front-stage .tc-name-input");
    if (name && fromPointer && document.activeElement !== name && matchMedia("(hover: hover)").matches) {
      name.focus();
      name.setSelectionRange(name.value.length, name.value.length);
    }
  }

  function readFile(file) {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result);
      r.onerror = rej;
      r.readAsDataURL(file);
    });
  }

  function setStatus(msg) {
    const el = document.getElementById("card-status");
    if (el) el.textContent = msg || "";
  }

  async function pollJob(jobId) {
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 1200));
      const r = await fetch("/studios/generation-job/" + encodeURIComponent(jobId), { credentials: "same-origin" });
      const d = await r.json();
      if (d.status === "done" || d.url) return Object.assign({}, d, d.result || {});
      if (d.status === "failed") throw new Error(d.error || "Character build failed");
    }
    throw new Error("Timed out building the character");
  }

  async function cutoutUrl(url) {
    const res = await fetch(API + "/cutout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ image: url }),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || "Cutout failed");
    return body.url;
  }

  async function takeArt(file) {
    if (!file) return;
    setStatus("Running through Characters (3D animated, white studio)…");
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (!isBlankName(card.name)) fd.append("name", card.name);
      const res = await fetch(API + "/from-upload", { method: "POST", body: fd, credentials: "same-origin" });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Upload failed");
      const done = await pollJob(body.job_id);
      let url = done.url || "";
      if (!url) throw new Error("No character still returned");
      card.charUrl = url;
      const cut = document.getElementById("cut-bg");
      if (!cut || cut.checked) {
        setStatus("Cutting white background…");
        url = await cutoutUrl(url);
      }
      setArt(url);
      setStatus("");
      paint();
    } catch (err) {
      setStatus(err.message || "Could not build character");
    }
  }

  // Builder gender → Swag (boy) or Seduction (girl); anything else leaves the toggle alone.
  function roleFromGender(gender) {
    const g = String(gender || "").trim().toLowerCase();
    if (["female", "f", "woman", "girl", "she"].includes(g)) return "women";
    if (["male", "m", "man", "boy", "he"].includes(g)) return "men";
    return null;
  }

  async function useRosterStill(url, name, gender, id) {
    if (!url) return;
    setStatus("Placing character…");
    try {
      let art = url;
      const cut = document.getElementById("cut-bg");
      if (!cut || cut.checked) art = await cutoutUrl(url);
      setArt(art);
      card.charUrl = url;
      card.characterId = id || null;
      const role = roleFromGender(gender);
      if (role) setRole(role);
      if (name && isBlankName(card.name)) card.name = String(name).slice(0, 22);
      setStatus("");
      paint();
      // New character on the card: the skills agent writes their four skills.
      const who = id || name || "";
      if (who && card.skillsFor !== who) {
        card.skillsFor = who;
        writeSkills();
      }
    } catch (err) {
      setStatus(err.message || "Could not place character");
    }
  }

  async function loadRoster() {
    const box = document.getElementById("roster");
    if (!box) return;
    const signIn = `<p class="studio-lede" style="margin:0"><a href="/login?next=/studios/trading-cards">Log in</a> to load your characters.</p>`;
    try {
      const res = await fetch(API + "/roster", { credentials: "same-origin" });
      if (res.status === 401) {
        box.innerHTML = signIn;
        return;
      }
      const body = await res.json();
      const list = body.cards || [];
      if (!list.length) {
        box.innerHTML = `<p class="studio-lede" style="margin:0">None yet — build one on Characters, or upload.</p>`;
        return;
      }
      box.innerHTML = list
        .map((c) => {
          const src = c.primary_image_url || "";
          const nm = c.name || "Unnamed";
          rosterById[String(c.id)] = c;
          return `<button type="button" draggable="true" title="Drag onto the card, or click" data-roster="${escAttr(src)}" data-roster-name="${escAttr(nm)}" data-roster-gender="${escAttr(c.gender || "")}" data-roster-id="${escAttr(c.id)}"><img src="${escAttr(src)}" alt="" draggable="false" /><span>${esc(nm)}</span></button>`;
        })
        .join("");
      box.querySelectorAll("[data-roster]").forEach((b) => {
        const d = b.dataset;
        b.addEventListener("click", () => useRosterStill(d.roster, d.rosterName, d.rosterGender, d.rosterId));
        b.addEventListener("dragstart", (e) => {
          e.dataTransfer.effectAllowed = "copy";
          e.dataTransfer.setData(CHARACTER_DRAG, JSON.stringify({ url: d.roster, name: d.rosterName, gender: d.rosterGender, id: d.rosterId }));
          e.dataTransfer.setData("text/uri-list", b.dataset.roster);
        });
      });
    } catch {
      box.innerHTML = signIn;
    }
  }
  // Rarity finish. Standard restores the original art for free; Silver Rare and Super Rare Hologram
  // re-render the finished art by AI from that exact image (charged like one Photos render).
  let finishing = false;
  async function applyFinish(f) {
    if (!f || finishing || card.rarity === f.rarity) return;
    if (f.rarity === "R") {
      if (card.baseArtUrl) {
        card.artUrl = card.baseArtUrl;
        card.customBackdrop = card.baseBackdrop || null;
        card.backdrop = card.baseBackdropId || "none";
      }
      card.rarity = "R";
      paint();
      return;
    }
    const base = card.baseArtUrl || card.artUrl;
    if (!base) {
      setStatus("Make the card art first, then pick the finish.");
      return;
    }
    finishing = true;
    setStatus(`Rendering ${f.label.split(" · ")[0]}…`);
    try {
      const res = await fetch(API + "/finish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ art: base, finish: f.id, background: sceneSrc() ? absUrl(sceneSrc()) : "" }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Could not render the finish");
      const done = await pollJob(body.job_id);
      if (!done.url) throw new Error("No image came back");
      if (!card.baseArtUrl) {
        card.baseArtUrl = base;
        card.baseBackdrop = card.customBackdrop;
        card.baseBackdropId = card.backdrop;
      }
      card.artUrl = done.url;
      card.customBackdrop = null;
      card.backdrop = "none";
      card.rarity = f.rarity;
      setStatus("Saved to your Library.");
      paint();
    } catch (err) {
      setStatus(err.message || "Could not render the finish");
    } finally {
      finishing = false;
    }
  }
  function absUrl(u) {
    return /^(https?:|data:)/i.test(u) ? u : location.origin + u;
  }
  // New art on the card starts back at Standard; a finish always renders from the current art.
  function setArt(url) {
    card.artUrl = url;
    card.baseArtUrl = null;
    card.baseBackdrop = null;
    card.baseBackdropId = null;
    card.rarity = "R";
  }

  // Skills agent (xAI chat): four in-character skills for the fixed mechanics, saved for Battle.
  async function writeSkills() {
    const name = isBlankName(card.name) ? "" : card.name;
    if (!card.characterId && !name) {
      setStatus("Type a character name on the card (or drop a character), then hit Write skills.");
      return;
    }
    const btn = document.getElementById("btn-skills");
    if (btn) btn.disabled = true;
    setStatus("Writing their skills…");
    try {
      const res = await fetch(API + "/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          characterId: card.characterId,
          name,
          role: card.role,
          description: card.dossier || "",
          stats: card.stats,
          idea: (document.getElementById("skill-idea") || {}).value || "",
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 401) throw new Error("Log in to write skills with AI.");
      if (!res.ok || !body.ok) throw new Error(body.error || "Could not write skills");
      const skills = Array.isArray(body.skills) ? body.skills : [];
      if (!skills.length) throw new Error("AI returned no skills — try again.");
      card.abilities = skills.map((s) => ({
        name: s.name || "Skill",
        description: s.description || s.story || s.text || "",
      }));
      // Keep four slots for the back of the card
      while (card.abilities.length < 4) {
        card.abilities.push({ name: "Level " + (card.abilities.length + 1), description: "" });
      }
      if (body.description && !card.dossier) card.dossier = body.description;
      if (body.crafted_by) card.craftedBy = body.crafted_by;
      setStatus(body.ai ? "Skills written." : "AI writer offline — using the standard four skills.");
      paint();
    } catch (err) {
      setStatus(err.message || "Could not write skills");
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  document.getElementById("btn-skills").addEventListener("click", writeSkills);

  // Everything the corner library hands us: characters go on the card,
  // photos become the background, saved cards reopen.
  function placeFromLibrary(p) {
    if (!p) return;
    const known = rosterById[String(p.id)] || {};
    if (p.kind === "card") {
      openSavedCard(p.id);
      return;
    }
    if (p.kind === "character") {
      useRosterStill(
        p.primary_image_url || p.url || known.primary_image_url,
        p.name || known.name,
        p.gender || known.gender,
        p.id
      );
      return;
    }
    const url = p.url || p.thumb;
    if (url) {
      card.customBackdrop = url;
      card.backdrop = "none";
      paint();
    }
  }

  async function openSavedCard(id) {
    let c = rosterById[String(id)];
    if (!c || !c.card_plate) {
      try {
        const res = await fetch(API + "/roster?id=" + encodeURIComponent(id), { credentials: "same-origin" });
        c = ((await res.json()).cards || [])[0] || c;
      } catch {}
    }
    if (c && c.card_plate) {
      card = Object.assign(blank(), c.card_plate, { characterId: c.id });
      setStatus("Your saved card is back on the press.");
      paint();
    } else if (c) {
      useRosterStill(c.primary_image_url, c.name, c.gender, c.id);
    }
  }

  // The corner logo pops open on your Characters; tap one, or drag it onto the card.
  function pickCharacter() {
    if (!window.PercfectLibrary) {
      setStatus("Log in to pick from your characters.");
      return;
    }
    PercfectLibrary.openCharacterPicker({
      max: 1,
      title: "Pick a character for the card",
      open: true,
      autoDone: true,
      onDone: (_ids, items) => {
        const c = items && items[0];
        if (c) placeFromLibrary(Object.assign({}, c, { kind: "character" }));
      },
    });
  }

  function pickBackground() {
    if (!window.PercfectLibrary) {
      setStatus("Log in to pick from your Photos.");
      return;
    }
    PercfectLibrary.openPhotoPicker({
      max: 1,
      title: "Pick a background",
      open: true,
      autoDone: true,
      onDone: (_ids, items) => {
        const p = items && items[0];
        if (p) placeFromLibrary(Object.assign({}, p, { kind: "photo" }));
      },
    });
  }
  document.getElementById("btn-bg-photos").addEventListener("click", pickBackground);
  window.PercfectCardStudio = { place: placeFromLibrary };

  // Photos generator from the card page: new pose on an epic scene, saved to the Library.
  async function sceneShot(mine) {
    const character = card.charUrl || card.artUrl;
    if (!character) {
      setStatus("Drop a character on the card first.");
      return;
    }
    if (mine && !card.customBackdrop && card.backdrop === "none") {
      setStatus("Pick a background or upload your own first.");
      return;
    }
    const btns = [document.getElementById("btn-poses"), document.getElementById("btn-scene-mine")];
    btns.forEach((b) => (b.disabled = true));
    setStatus(mine ? "Putting them in your background…" : "Painting an epic background…");
    try {
      const res = await fetch(API + "/scene-shot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          character,
          mine,
          background: mine ? card.customBackdrop || "" : "",
          backdrop: card.backdrop,
          scene: document.getElementById("scene-text").value.trim(),
          theme: card.theme,
        }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Scene shot failed");
      const done = await pollJob(body.job_id);
      if (!done.url) throw new Error("No image came back");
      setArt(done.url);
      setStatus("Saved to your Library.");
      paint();
    } catch (err) {
      setStatus(err.message || "Scene shot failed");
    } finally {
      btns.forEach((b) => (b.disabled = false));
    }
  }
  document.getElementById("btn-scene-mine").addEventListener("click", () => sceneShot(true));

  // Six poses (handoff 1.4a): one cheap 3×2 preview sheet, then the picked panel re-rendered full size.
  async function showPoses(previous, change) {
    const character = card.charUrl || card.artUrl;
    if (!character) {
      setStatus("Drop a character on the card first.");
      return;
    }
    const btn = document.getElementById("btn-poses");
    btn.disabled = true;
    setStatus(previous ? "Generating 6 more styles…" : "Generating 6 styles…");
    try {
      const res = await fetch(API + "/pose-sheet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          character,
          scene: document.getElementById("scene-text").value.trim(),
          characterId: card.characterId,
          name: isBlankName(card.name) ? "" : card.name,
          details: card.dossier || "",
          previous: typeof previous === "string" ? previous : "",
          change: change || "",
        }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Could not paint the poses");
      const done = await pollJob(body.job_id);
      if (!done.url) throw new Error("No pose sheet came back");
      setStatus("");
      openPoseSheet(done.url, character, !!body.more);
    } catch (err) {
      setStatus(err.message || "Could not paint the poses");
    } finally {
      btn.disabled = false;
    }
  }
  document.getElementById("btn-poses").addEventListener("click", () => showPoses());

  function openPoseSheet(sheet, character, more) {
    const wrap = document.createElement("div");
    wrap.className = "pose-sheet";
    wrap.innerHTML = `<div class="pose-sheet-box">
        <p class="studio-col-label">Tap the pose you want · 3 credits for the full-size card art</p>
        <img class="pose-sheet-img" src="${escAttr(sheet)}" alt="Six styles: tap the one you want" />
        <div class="studio-controls" style="margin-top:0">
          ${more ? `<input class="press-idea" data-change maxlength="120" placeholder="How should the next six change? e.g. more epic, more lewd, more seductive, more bright, more dark, more Gothic" style="min-width:min(92vw,420px)" /><button type="button" class="studio-btn" data-more>🔁 Six more · 3 credits</button>` : ""}
          <button type="button" class="studio-btn" data-report>⚑ Report a problem</button>
          <button type="button" class="studio-btn ghost" data-close>Close</button>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener("click", async (e) => {
      if (e.target === wrap || e.target.closest("[data-close]")) {
        wrap.remove();
        return;
      }
      if (e.target.closest("[data-more]")) {
        const change = (wrap.querySelector("[data-change]") || {}).value || "";
        wrap.remove();
        showPoses(sheet, change.trim());
        return;
      }
      if (e.target.closest("[data-report]")) {
        const note = window.prompt("What's wrong with these six shots?");
        if (note === null) return;
        try {
          const res = await fetch(API + "/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ sheet, note }),
          });
          const body = await res.json();
          if (!res.ok || !body.ok) throw new Error(body.error || "Could not send the report");
          setStatus("Reported. Thanks, we'll look at it.");
        } catch (err) {
          setStatus(err.message || "Could not send the report");
        }
        return;
      }
      // Send where they tapped; the server finds which panel that is (the AI lays out 3×2 or 2×3).
      if (e.target.classList.contains("pose-sheet-img")) {
        const r = e.target.getBoundingClientRect();
        wrap.remove();
        pickPose(sheet, character, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
      }
    });
  }

  async function pickPose(sheet, character, x, y) {
    setStatus("Rendering your pick full size…");
    try {
      const res = await fetch(API + "/pose-pick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ character, sheet, x, y }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Could not render that pose");
      const done = await pollJob(body.job_id);
      if (!done.url) throw new Error("No image came back");
      setArt(done.url);
      setStatus("Saved to your Library.");
      paint();
    } catch (err) {
      setStatus(err.message || "Could not render that pose");
    }
  }

  async function takeBg(file) {
    if (!file) return;
    card.customBackdrop = await readFile(file);
    card.backdrop = "none";
    paint();
  }

  // Admin quick card: the picture goes straight onto the card (no Characters run, no AI, no credits).
  // Saving it creates the character on the admin's account (card_studio.save). Customers build first.
  async function quickArt(file) {
    setStatus("Placing your picture…");
    try {
      let url = await new Promise((ok, bad) => {
        const r = new FileReader();
        r.onload = () => ok(r.result);
        r.onerror = () => bad(new Error("Could not read that file"));
        r.readAsDataURL(file);
      });
      const cut = document.getElementById("cut-bg");
      if (cut && cut.checked) {
        setStatus("Cutting white background…");
        url = await cutoutUrl(url);
      }
      setArt(url);
      card.charUrl = url;
      card.characterId = null;
      if (isBlankName(card.name)) {
        const base = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
        if (base) card.name = base.slice(0, 22);
      }
      setStatus("Name it, set the stats, then Save card.");
      paint();
    } catch (err) {
      setStatus(err.message || "Could not place that picture");
    }
  }
  const dropArt = document.getElementById("drop-art");
  if (dropArt)
    dropArt.addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (f) (window.CARD_STUDIO_ADMIN ? quickArt : takeArt)(f);
    });
  document.getElementById("file-bg").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (f) takeBg(f);
  });
  const frontStage = document.getElementById("front-stage");
  frontStage.addEventListener("dragover", (e) => {
    e.preventDefault();
    frontStage.classList.add("is-drop");
  });
  frontStage.addEventListener("click", (e) => {
    if (stopClick) {
      stopClick = false; // the touch that stopped the spin doesn't also open the library
      return;
    }
    if (e.target.closest(".tc-art-empty, .tc-art, .tc-backdrop-img")) pickCharacter();
  });
  frontStage.addEventListener("dragleave", (e) => {
    if (!frontStage.contains(e.relatedTarget)) frontStage.classList.remove("is-drop");
  });
  frontStage.addEventListener("drop", (e) => {
    e.preventDefault();
    frontStage.classList.remove("is-drop");
    const dt = e.dataTransfer;
    // From the corner library: characters go on the card, photos become the background.
    const lib = dt.getData(LIBRARY_DRAG);
    if (lib) {
      try {
        placeFromLibrary(JSON.parse(lib));
        return;
      } catch {}
    }
    // A character from Your characters: already built, so no Characters rebuild.
    const built = dt.getData(CHARACTER_DRAG);
    if (built) {
      try {
        const c = JSON.parse(built);
        useRosterStill(c.url, c.name, c.gender, c.id);
        return;
      } catch {}
    }
    // A still dragged in from the Library (or any page) in another tab.
    const url = (dt.getData("text/uri-list") || "")
      .split(/\r?\n/)
      .map((s) => s.trim())
      .find((s) => /^https?:\/\//i.test(s));
    if (url) {
      useRosterStill(url, "");
      return;
    }
    const f = dt.files && dt.files[0];
    if (f) takeArt(f);
  });
  const dosEl = document.getElementById("dossier");
  if (dosEl) {
    dosEl.addEventListener("input", () => {
      card.dossier = dosEl.value.slice(0, 160);
      const back = document.querySelector("#back-stage .tc-back-desc");
      if (back) back.value = card.dossier;
    });
  }
  document.getElementById("font-select").addEventListener("change", (e) => setFont(e.target.value, false));

  document.getElementById("btn-new").addEventListener("click", () => {
    card = blank();
    paint();
  });

  // One card: it turns (front, back) until Stop or a touch; Flip shows the other side to type on.
  const card3d = document.getElementById("card3d");
  let stopClick = false;
  function setSpin(on) {
    spinning = on;
    card3d.classList.toggle("is-spinning", on);
    document.getElementById("btn-spin").textContent = on ? "Stop" : "Spin";
  }
  document.getElementById("btn-spin").addEventListener("click", () => setSpin(!spinning));
  document.getElementById("btn-flip").addEventListener("click", () => {
    setSpin(false);
    flipped = !flipped;
    card3d.classList.toggle("is-flipped", flipped);
    document.getElementById("btn-flip").textContent = flipped ? "Flip to front" : "Flip to back";
  });
  // The center card is the preview: it keeps spinning (no touch-to-stop, nothing to edit on it).

  // The card exactly as it looks on the page: same fonts, layout, border and art (no editing buttons).
  async function cardPng(face) {
    const el = document.querySelector(`#${face}-stage .tc-bezel`);
    if (!el || !window.htmlToImage) throw new Error("Could not capture the card");
    return window.htmlToImage.toPng(el, {
      pixelRatio: 3,
      cacheBust: true,
      filter: (node) => !(node.classList && node.classList.contains("no-capture")),
    });
  }

  // Preview: the final front and back, exactly as they'll come out.
  document.getElementById("btn-preview").addEventListener("click", async () => {
    setStatus("Building the preview…");
    try {
      const [front, back] = await Promise.all([cardPng("front"), cardPng("back")]);
      const wrap = document.createElement("div");
      wrap.className = "pose-sheet";
      wrap.innerHTML = `<div class="pose-sheet-box">
          <p class="studio-col-label">This is exactly how your card comes out</p>
          <div class="preview-pair"><img src="${front}" alt="Front" /><img src="${back}" alt="Back" /></div>
          <button type="button" class="studio-btn ghost" data-close>Close</button>
        </div>`;
      document.body.appendChild(wrap);
      wrap.addEventListener("click", (e) => {
        if (e.target === wrap || e.target.closest("[data-close]")) wrap.remove();
      });
      setStatus("");
    } catch {
      setStatus("Could not build the preview. Try again.");
    }
  });

  // AI help for the back description: from the character's pictures and how they were built.
  async function describeWithAI() {
    if (!card.characterId && isBlankName(card.name)) {
      setStatus("Pick a character first.");
      return;
    }
    setStatus("Writing the description…");
    try {
      const res = await fetch(API + "/describe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          characterId: card.characterId,
          name: isBlankName(card.name) ? "" : card.name,
          image: card.charUrl || "",
        }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Could not write the description");
      card.dossier = body.description;
      if (body.crafted_by) card.craftedBy = body.crafted_by;
      setStatus("");
      paint();
    } catch (err) {
      setStatus(err.message || "Could not write the description");
    }
  }

  async function download(face) {
    setStatus("Preparing your card…");
    try {
      const a = document.createElement("a");
      a.href = await cardPng(face);
      a.download = serial() + "-" + face + ".png";
      a.click();
      setStatus("");
    } catch {
      setStatus("Could not capture the card. Try again, or take a screenshot.");
    }
  }
  document.getElementById("btn-dl-front").addEventListener("click", () => download("front"));
  document.getElementById("btn-dl-back").addEventListener("click", () => download("back"));

  document.getElementById("btn-save").addEventListener("click", async () => {
    if (isBlankName(card.name) || !card.artUrl) {
      setStatus("Name it and drop a character first.");
      return;
    }
    if (!card.characterId && !window.CARD_STUDIO_ADMIN) {
      setStatus("Build a character first, then tap the card to pick them.");
      return;
    }
    const btn = document.getElementById("btn-save");
    btn.disabled = true;
    setStatus("Saving your card…");
    const payload = { ...card, id: card.id || crypto.randomUUID(), serial: serial() };
    let frontPng = "";
    try {
      frontPng = await cardPng("front");
    } catch {}
    try {
      const res = await fetch(API + "/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ card: payload, frontPng }),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) throw new Error(body.error || "Save failed");
      card = Object.assign(blank(), body.card);
      const i = binder.findIndex((c) => c.id === card.id);
      if (i >= 0) binder[i] = JSON.parse(JSON.stringify(card));
      else binder.unshift(JSON.parse(JSON.stringify(card)));
      if (window.PercfectLibrary && PercfectLibrary.reload) PercfectLibrary.reload();
      setStatus("Saved: it's in your Library under Cards.");
      paint();
    } catch (err) {
      setStatus(err.message || "Save failed");
    } finally {
      btn.disabled = false;
    }
  });

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function escAttr(s) {
    return esc(s).replace(/"/g, "&quot;");
  }

  // "Create Percfect Hero Card" / "Edit in Card Studio" from the Library on another page.
  async function boot() {
    await loadRoster();
    let pick = null;
    try {
      pick = JSON.parse(sessionStorage.getItem("percfect_card_pick") || "null");
      sessionStorage.removeItem("percfect_card_pick");
    } catch {}
    if (pick) placeFromLibrary(pick);
  }

  paint();
  boot();
})();
