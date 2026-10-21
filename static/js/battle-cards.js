/* Battle Cards, five steps (Nick's design 2026-09-27): 01 Pick · 02 Lobby · 03 Sync · 04 Director · 05 Result.
   The player picks the length and the arena. The server rolls the dice (they pick which skill each fighter
   lands), the rules engine rules, Leera (battle_agent.py) writes the fight, and the job films it.
   No live player matchmaking yet: the lobby offers the house challenger (vs Bot) or your own cards. */
(function () {
  const CFG = window.BATTLE_CFG || {};
  const PER = { human: 1, ai: 1, teams: 3 };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const TICKET = '<svg class="bt-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4Z"/><path d="M13 6v12" stroke-dasharray="2 2"/></svg>';
  const PERSON = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/><path d="M2 12h3M19 12h3" stroke="#39c0e6"/></svg>';
  const ARENA_LOOK = {
    neon_rooftop: "linear-gradient(160deg, rgba(160,92,255,.35), rgba(57,192,230,.18) 60%, rgba(4,9,13,.9))",
    throne_hall: "linear-gradient(160deg, rgba(224,169,78,.32), rgba(80,40,20,.35) 60%, rgba(4,9,13,.9))",
    storm_coast: "linear-gradient(160deg, rgba(120,140,170,.35), rgba(30,50,80,.4) 60%, rgba(4,9,13,.9))",
    ice_citadel: "linear-gradient(160deg, rgba(169,221,238,.35), rgba(43,127,212,.25) 60%, rgba(4,9,13,.9))",
    circuit_void: "linear-gradient(160deg, rgba(57,192,230,.3), rgba(10,18,27,.6) 60%, rgba(4,9,13,.95))",
  };

  const state = {
    step: 1,
    reached: 1,
    mode: "human",
    cards: [],
    blue: [],
    red: [],
    duration: 10,
    arena: (CFG.arenas && CFG.arenas.length && CFG.arenas[CFG.arenas.length - 1].key) || "circuit_void",
    upload: null,
    uploadUrl: "",
    tickets: CFG.tickets | 0,
    busy: false,
    rolled: null, // duels from the server, once the dice are rolled
    ack: null,
    job: null,
    render: { status: "", pct: 0 },
    typing: false,
  };

  const cost = (d) => CFG.cost[d || state.duration] || CFG.cost[String(d || state.duration)] || 5;
  const winFor = (d) => CFG.win[d || state.duration] || CFG.win[String(d || state.duration)] || 8;
  const words = { 6: "six", 10: "ten", 15: "fifteen" };

  function setStatus(msg, cls) {
    const el = $("status");
    el.className = "bt-status" + (cls ? " " + cls : "");
    el.innerHTML = msg || "";
  }
  function renderTickets() {
    $("tixBal").textContent = String(state.tickets);
  }

  // ── pieces ───────────────────────────────────────────────────────────────────────────────
  function cardHtml(c, cls, extra) {
    if (!c) return "";
    return `<div class="bt-card ${cls || ""}" data-id="${esc(c.id)}"><img src="${esc(c.url)}" alt="${esc(c.name)}" loading="lazy" />${extra || ""}</div>`;
  }
  function leeraHtml(mood, text) {
    const bars = [6, 14, 22, 10, 18, 26, 12, 8, 16, 20, 6]
      .map((h, i) => `<span style="height:${h}px;animation-delay:${-i * 0.13}s"></span>`)
      .join("");
    return `<aside class="bt-leera" aria-label="AI director"><div class="bt-avatar">${PERSON}<span>ANIMATED<br>AVATAR</span></div>
      <div><div class="who"><b>LEERA</b><small>AI Director · ${esc(mood)}</small></div><p>${text}</p><div class="bt-wave">${bars}</div></div></aside>`;
  }
  function need() {
    return PER[state.mode];
  }
  function opponentReady() {
    return state.mode === "ai" || state.red.length === need();
  }

  function paintSteps() {
    document.querySelectorAll("#steps button").forEach((b) => {
      const n = Number(b.dataset.step);
      b.classList.toggle("on", n === state.step);
      const locked = state.busy ? n !== state.step : n > state.reached || (n >= 4 && !state.ack);
      b.disabled = locked;
    });
  }
  function go(n) {
    state.step = n;
    state.reached = Math.max(state.reached, n);
    render();
  }

  function render() {
    paintSteps();
    const main = $("main");
    main.className = `bt-main bt-s${state.step}`;
    if (!CFG.loggedIn) {
      main.innerHTML = `<div class="bt-gate"><div class="bt-h2">Battle Cards</div><p>Please <a href="/login?next=/studios/battle-cards">log in</a> to battle. Daily tickets land when you sign in.</p></div>`;
      return;
    }
    main.innerHTML = [null, pickHtml, lobbyHtml, syncHtml, directorHtml, resultHtml][state.step]();
    if (state.step === 3) setTimeout(fillSync, 60);
    if (state.step === 5) {
      const v = main.querySelector("video");
      if (v) v.play().catch(() => {});
    }
  }

  // ── 01 pick ──────────────────────────────────────────────────────────────────────────────
  function pickHtml() {
    const modes = [
      ["human", "Human", "1v1"],
      ["ai", "AI", "vs Bot"],
      ["teams", "Teams", "3v3"],
    ]
      .map(([k, a, b]) => `<button type="button" data-mode="${k}" class="${state.mode === k ? "on" : ""}">${a}<i>${b}</i></button>`)
      .join("");
    const picked = new Set(state.blue.map((c) => c.id));
    const deck = state.cards.length
      ? state.cards
          .map((c) => cardHtml(c, picked.has(c.id) ? "blue" : "", `<span class="lv">Lv${c.level || 1}</span>${picked.has(c.id) ? `<span class="pick">YOU</span>` : ""}`))
          .join("")
      : `<p class="bt-deck-empty">No saved cards yet. <a href="/studios/trading-cards">Make one in Card Studio</a>, tap <b>Save card</b>, then come back to battle.</p>`;
    const n = need();
    let blueSide;
    if (n === 1) {
      blueSide = state.blue[0]
        ? cardHtml(state.blue[0], "blue")
        : `<div class="bt-empty-card blue"><b>YOUR CARD</b><p>Tap a card in your deck.</p></div>`;
    } else {
      blueSide = `<div class="bt-teamrow">${[0, 1, 2]
        .map((i) => (state.blue[i] ? cardHtml(state.blue[i], "blue") : `<div class="bt-empty-card blue"><p>${i + 1}</p></div>`))
        .join("")}</div>`;
    }
    const redText =
      state.mode === "ai"
        ? "The house challenger: matched to your card's level, stats within about 8% of yours."
        : state.mode === "teams"
          ? "Three more of your cards, picked in the lobby."
          : "Picked in the lobby: another of your cards.";
    const ready = state.blue.length === n;
    const tip =
      state.mode === "teams"
        ? "Pick three cards for your side. The server shuffles the fight order."
        : "Pick the card you want to bring. Its level decides which abilities I can put in the fight.";
    return `
      <section class="bt-panel bt-deck">
        <div class="bt-deck-head"><span class="bt-h3">Your deck</span><small>${state.cards.length} cards</small></div>
        <div class="bt-modes" id="modes">${modes}</div>
        <div class="bt-deck-grid" id="deck">${deck}</div>
      </section>
      <section class="bt-pick-right">
        <div class="bt-eyebrow">Step 01 · Choose your fighter</div>
        <h1 class="bt-h1">Two cards in. One fight out.</h1>
        <p class="bt-lead">Pick your card, match an opponent, and Leera, the AI director, turns both characters into a battle video from your cards' art, stats and unlocked abilities.</p>
        <div class="bt-sides">
          <div class="bt-side"><small>Blue side · You</small><div class="bt-slot">${blueSide}</div></div>
          <div class="bt-vs">VS</div>
          <div class="bt-side red"><small>Red side · Opponent</small><div class="bt-slot"><div class="bt-empty-card red"><b>OPPONENT</b><p>${redText}</p></div></div></div>
        </div>
        <div class="bt-pick-foot">
          <div class="bt-cta"><button type="button" class="bt-btn blue" id="toLobby" ${ready ? "" : "disabled"}>Enter the lobby →</button>
            <span class="bt-note">Tickets are only spent once both players agree.</span></div>
          ${leeraHtml("Speaking", esc(tip))}
        </div>
      </section>`;
  }
  function tapDeck(id) {
    const c = state.cards.find((x) => String(x.id) === String(id));
    if (!c) return;
    const n = need();
    const i = state.blue.findIndex((x) => x.id === c.id);
    if (n === 1) state.blue = [c];
    else if (i >= 0) state.blue.splice(i, 1);
    else if (state.blue.length < n) state.blue.push(c);
    else {
      setStatus("Three cards per side. Tap one of yours to swap it out.", "err");
      return;
    }
    state.red = state.red.filter((x) => !state.blue.some((b) => b.id === x.id));
    resetFight();
    setStatus("");
    render();
  }
  function setMode(m) {
    if (!PER[m] || state.busy) return;
    state.mode = m;
    state.blue = state.blue.slice(0, PER[m]);
    state.red = [];
    state.reached = 1;
    resetFight();
    render();
  }
  function resetFight() {
    state.rolled = null;
    state.ack = null;
    state.job = null;
    state.render = { status: "", pct: 0 };
    state.reached = Math.min(state.reached, 3);
  }

  // ── 02 lobby ─────────────────────────────────────────────────────────────────────────────
  function lobbyHtml() {
    const n = need();
    let rows;
    let count;
    if (state.mode === "ai") {
      count = 1;
      rows = `<button type="button" class="bt-row on" data-house="1"><span class="av">H</span><span class="nm"><b>House challenger</b><small>Lv${state.blue[0] ? state.blue[0].level || 1 : 1} · matched to your card</small></span><span class="bt-tag">Ready</span><span class="ch">Challenged</span></button>`;
    } else {
      const pool = state.cards.filter((c) => !state.blue.some((b) => b.id === c.id));
      count = pool.length;
      rows = pool.length
        ? pool
            .map((c) => {
              const on = state.red.some((r) => r.id === c.id);
              return `<button type="button" class="bt-row${on ? " on" : ""}" data-red="${esc(c.id)}"><span class="av"><img src="${esc(c.url)}" alt="" /></span><span class="nm"><b>${esc(c.name)}</b><small>Your card · Lv${c.level || 1}</small></span><span class="bt-tag">Ready</span><span class="ch">${on ? "Picked" : "Challenge"}</span></button>`;
            })
            .join("")
        : `<p class="bt-note">You need ${n === 3 ? "three more cards" : "another card"} for this. <a href="/studios/trading-cards" style="color:var(--cyan)">Make one in Card Studio</a>, or switch to AI vs Bot.</p>`;
    }
    const redCards =
      state.mode === "ai"
        ? `<div class="bt-empty-card red"><b>?</b><p>House challenger, revealed in the fight.</p></div>`
        : n === 1
          ? state.red[0]
            ? cardHtml(state.red[0], "red")
            : `<div class="bt-empty-card red"><b>OPPONENT</b><p>Challenge a card on the left.</p></div>`
          : `<div class="bt-teamrow">${[0, 1, 2].map((i) => (state.red[i] ? cardHtml(state.red[i], "red") : `<div class="bt-empty-card red"><p>${i + 1}</p></div>`)).join("")}</div>`;
    const blueCards = n === 1 ? cardHtml(state.blue[0], "blue") : `<div class="bt-teamrow">${state.blue.map((c) => cardHtml(c, "blue")).join("")}</div>`;
    const ready = opponentReady();
    const oppName = state.mode === "ai" ? "HOUSE" : n === 1 ? (state.red[0] ? state.red[0].name.toUpperCase() : "OPPONENT") : "RED TEAM";
    const money =
      state.mode === "ai"
        ? "Beat the house card to win tickets. Your XP counts win or lose."
        : "Your own cards fighting each other earn XP only, no ticket winnings.";
    const leera =
      state.mode === "ai"
        ? "The house challenger is ready. Agree, and I'll load you both into the chamber."
        : ready
          ? "Both sides are set. Agree, and I'll load them into the chamber."
          : "I'm watching the lobby. Challenge a card and I'll load you both into the chamber.";
    return `
      <section class="bt-lobby-left">
        <div class="bt-panel">
          <div class="bt-deck-head"><span class="bt-h3">${state.mode === "ai" ? "Challengers" : "Your cards"}</span><span class="bt-live">● ${count} ready</span></div>
          <div class="bt-rows" id="rows">${rows}</div>
        </div>
        ${leeraHtml("Hosting", esc(leera))}
      </section>
      <section class="bt-lobby-mid">
        <div class="bt-eyebrow">Step 02 · Challenge accepted?</div>
        <div class="bt-duo${n === 3 ? " teams" : ""}">${blueCards}<div class="bt-vs">VS</div>${redCards}</div>
        <div class="bt-agree"><span class="yes"><i class="box">✓</i><b>YOU</b> Ready</span><span class="red${ready ? " yes" : ""}"><i class="box">${ready ? "✓" : ""}</i><b>${esc(oppName)}</b> ${ready ? "Ready" : "Waiting…"}</span></div>
        <p class="bt-note" style="text-align:center">${esc(money)}<br>Nothing is charged until you press Battle in the sync chamber.</p>
        <button type="button" class="bt-btn blue" id="agree" style="min-width:290px" ${ready ? "" : "disabled"}>Agree to battle</button>
      </section>
      <section class="bt-panel bt-chat" style="display:flex">
        <div class="bt-chat-head"><span class="bt-h3">Lobby chat</span><small>TEXT ONLY</small></div>
        <div class="bt-chat-body">Live players join the lobby soon. Until then, challenge the house card for tickets, or fight your own cards for XP.</div>
        <div class="bt-chat-foot"><input placeholder="Talk your talk…" disabled /><button type="button" disabled>Send</button></div>
      </section>`;
  }
  function tapRed(id) {
    const c = state.cards.find((x) => String(x.id) === String(id));
    if (!c) return;
    const n = need();
    const i = state.red.findIndex((x) => x.id === c.id);
    if (n === 1) state.red = [c];
    else if (i >= 0) state.red.splice(i, 1);
    else if (state.red.length < n) state.red.push(c);
    else return setStatus("Three cards on the red side. Tap one to swap it out.", "err");
    resetFight();
    setStatus("");
    render();
  }

  // ── 03 sync ──────────────────────────────────────────────────────────────────────────────
  function diceBoxHtml() {
    const duels = state.rolled || [];
    const pairs = state.mode === "teams" ? 3 : 1;
    let out = "";
    for (let i = 0; i < pairs; i++) {
      const d = duels[i];
      out += `<div class="bt-pair"><div class="bt-die blue" data-die="b${i}">${d ? d.dice.blue : "?"}</div><div class="bt-die red" data-die="r${i}">${d ? d.dice.red : "?"}</div></div>`;
    }
    let note = "Each die picks the skill that side lands.";
    if (duels.length === 1) note = `${skillShort("blue", duels[0])}<br>${skillShort("red", duels[0])}`;
    else if (duels.length) note = "Three duels rolled. The server set the order.";
    return `<div class="bt-dice" id="dice"><small>DICE ROLL</small>${out}<div class="bt-skillnote">${note}</div></div>`;
  }
  function skillShort(color, d) {
    const s = d.skills[color];
    if (d.finisher[color]) return `<b>${color === "blue" ? "Blue" : "Red"}</b>: the finisher`;
    return s ? `<b>${color === "blue" ? "Blue" : "Red"}</b>: ${esc(s.name)}` : `<b>${color === "blue" ? "Blue" : "Red"}</b>: no skill`;
  }
  function syncHtml() {
    const teams = state.mode === "teams";
    const redCards = state.mode === "ai" ? (state.ack ? [aiCardFromAck()] : []) : state.red;
    const redHtml = redCards.length
      ? redCards.map((c) => cardHtml(c, "red")).join("")
      : `<div class="bt-empty-card red" style="height:min(360px, calc(100vh - 470px))"><b>?</b><p>House challenger</p></div>`;
    const blueHtml = state.blue.map((c) => cardHtml(c, "blue")).join("");
    const float = teams
      ? `<div class="team">${blueHtml}</div>${diceBoxHtml()}<div class="team">${redHtml}</div>`
      : `${blueHtml}${diceBoxHtml()}${redHtml}`;
    const lengths = [6, 10, 15]
      .map(
        (d) =>
          `<button type="button" data-d="${d}" class="${d === state.duration ? "on" : ""}"><b>${d}s</b><span>${TICKET} Entry ${cost(d)}</span><em>${
            state.mode === "ai" ? `Winner gets<i>+${winFor(d)}</i>` : "XP only"
          }</em></button>`
      )
      .join("");
    const arenas = (CFG.arenas || [])
      .map((a) => `<button type="button" data-arena="${esc(a.key)}" class="${state.arena === a.key ? "on" : ""}" style="background-image:${ARENA_LOOK[a.key] || "none"}">${esc(a.label)}</button>`)
      .join("");
    const up = `<label class="${state.arena === "upload" ? "on" : ""}" ${state.uploadUrl ? `style="background-image:linear-gradient(transparent, rgba(4,9,13,.85)), url('${esc(state.uploadUrl)}');align-items:flex-end;justify-content:flex-start;color:var(--ink)"` : ""}>${
      state.upload ? "Your arena" : "+ Upload your own"
    }<input type="file" accept="image/*" id="bgFile" /></label>`;
    const lv4 = state.blue.some((c) => (c.level || 1) >= 4);
    const short = !CFG.isAdmin && state.tickets < cost();
    const label = state.busy
      ? "Rolling the dice…"
      : `Battle · ${state.duration} seconds · ${cost()} tickets${CFG.isAdmin ? " · not charged" : ""}`;
    const arenaName = state.arena === "upload" ? "your arena" : ((CFG.arenas || []).find((a) => a.key === state.arena) || {}).label || "the arena";
    const leera = state.rolled ? rollLine() : `${esc(cap(words[state.duration] || state.duration))} seconds in ${esc(arenaName)}. Press Battle and I'll roll: each die picks the skill that fighter lands. Then I'll write the fight.`;
    return `
      <section class="bt-chamber">
        <div class="bt-eyebrow">Step 03 · Sync chamber</div>
        <h1 class="bt-h1">Loading fighters into the simulation</h1>
        <div class="bt-float${teams ? " teams" : ""}">${float}</div>
        <div class="bt-syncbars"><div><label>BLUE SYNC <i id="bsyncT">0%</i></label><div class="bt-bar"><i id="bsync"></i></div></div>
          <div class="red"><label>RED SYNC <i id="rsyncT">0%</i></label><div class="bt-bar"><i id="rsync"></i></div></div></div>
        <div style="align-self:flex-start">${leeraHtml(state.rolled ? "Rolling" : "Ready", leera)}</div>
      </section>
      <section class="bt-sync-right">
        <div class="bt-panel">
          <div class="bt-h3">Battle length: you pick</div>
          <div class="bt-lengths" id="lengths">${lengths}</div>
          <p class="bt-note">Leera rolls the dice fairly on the server. They pick which skill each fighter lands; the tumble you see is just the reveal.</p>
        </div>
        <div class="bt-panel">
          <div class="bt-h3">Arena for the video</div>
          <div class="bt-arenas" id="arenas">${arenas}${up}</div>
          ${lv4 ? `<input class="bt-finisher" id="finisher" maxlength="200" autocomplete="off" placeholder="Finisher (optional): how your level 4 card wins if it rolls a 6" value="${esc(state.finisher || "")}" />` : ""}
        </div>
        <button type="button" class="bt-btn gold" id="battle" ${state.busy ? "disabled" : ""}>${TICKET.replace('class="bt-ico"', 'class="bt-ico" style="stroke:#1a1206"')} ${esc(label)}</button>
        ${short ? `<p class="bt-note">You have ${state.tickets} tickets. <button type="button" class="bt-buy" data-buy="1">Buy 5 · ${CFG.creditsPerTicket * 5} credits</button> or come back for your free daily tickets.</p>` : ""}
      </section>`;
  }
  const cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);
  function fillSync() {
    const b = $("bsync");
    const r = $("rsync");
    if (!b || !r) return;
    b.style.width = "100%";
    r.style.width = "100%";
    let p = 0;
    const t = setInterval(() => {
      p = Math.min(100, p + 7);
      if ($("bsyncT")) $("bsyncT").textContent = Math.min(100, p + 16) + "%";
      if ($("rsyncT")) $("rsyncT").textContent = p + "%";
      if (p >= 100) clearInterval(t);
    }, 90);
  }
  function rollLine() {
    const d = state.rolled;
    if (!d || !d.length) return "";
    if (d.length > 1) return "Three duels, three rolls. The server set the order; now I'm writing the fight.";
    const x = d[0];
    const part = (c) => {
      const f = c === "blue" ? x.blue_fighter : x.red_fighter;
      if (x.finisher[c]) return `${esc(f.name)} rolled a 6 at level 4: the finisher.`;
      const s = x.skills[c];
      return s ? `${esc(f.name)} rolled ${x.dice[c]}: ${esc(s.name)}.` : `${esc(f.name)} rolled a 5: no skill this round.`;
    };
    return `${part("blue")} ${part("red")} Now I'll write the fight.`;
  }
  function aiCardFromAck() {
    const r = state.ack && state.ack.duels && state.ack.duels[0] && state.ack.duels[0].red_fighter;
    return r ? { id: r.id, name: r.name, url: r.art, level: r.level } : null;
  }

  async function rollReveal(duels) {
    const els = [...document.querySelectorAll(".bt-die")];
    els.forEach((e) => e.classList.add("rolling"));
    const spin = setInterval(() => els.forEach((e) => (e.textContent = 1 + Math.floor(Math.random() * 6))), 70);
    await sleep(1100);
    clearInterval(spin);
    state.rolled = duels || [];
    render();
  }

  async function startBattle() {
    if (state.busy) return;
    if (state.blue.length !== need() || !opponentReady()) return go(2);
    if (!CFG.isAdmin && state.tickets < cost()) {
      setStatus(`You need ${cost()} tickets and have ${state.tickets}.`, "err");
      return;
    }
    const fin = $("finisher");
    if (fin) state.finisher = fin.value.trim();
    state.busy = true;
    state.rolled = null;
    state.ack = null;
    state.job = null;
    render();
    setStatus("Spending tickets and rolling the dice…");
    let charged = false;
    try {
      const fd = new FormData();
      fd.append("mode", state.mode);
      fd.append("character_ids", [...state.blue, ...state.red].map((c) => c.id).join(","));
      fd.append("duration", String(state.duration));
      fd.append("finisher", state.finisher || "");
      if (state.arena === "upload" && state.upload) fd.append("bg_file", state.upload);
      else fd.append("bg_preset", state.arena);
      const res = await fetch("/studios/battle-cards/generate", { method: "POST", body: fd, credentials: "same-origin" });
      const ack = await res.clone().json().catch(() => ({}));
      if (!res.ok) {
        if (ack.tickets != null) {
          state.tickets = ack.tickets;
          renderTickets();
        }
        throw new Error(ack.error || "The fight failed to start.");
      }
      charged = !CFG.isAdmin;
      state.ack = ack;
      if (ack.tickets != null) {
        state.tickets = ack.tickets;
        renderTickets();
      }
      if (state.mode === "teams" && ack.order) {
        const byId = {};
        [...state.blue, ...state.red].forEach((c) => (byId[c.id] = c));
        state.blue = ack.order.blue.map((id) => byId[String(id)]).filter(Boolean);
        state.red = ack.order.red.map((id) => byId[String(id)]).filter(Boolean);
      }
      render();
      await rollReveal(ack.duels);
      setStatus("");
      await sleep(2200);
      state.render = { status: "queued", pct: 12 };
      go(4);
      typeBeats();
      const job = await PercfectStudioJobs.resolveGenerationResponse(res, {
        kind: "arena",
        onProgress: (d) => {
          const s = (d && d.status) || "";
          const pct = s === "done" ? 100 : s === "saving" ? 90 : s === "processing" || s === "running" ? 55 : 12;
          state.render = { status: s === "processing" || s === "running" || s === "saving" ? "rendering" : "queued", pct: Math.max(state.render.pct, pct) };
          paintRender();
        },
      });
      charged = false;
      state.job = Object.assign({}, job, (job && job.result) || {});
      state.render = { status: "delivered", pct: 100 };
      if (state.job.tickets != null) {
        state.tickets = state.job.tickets;
        renderTickets();
      }
      state.busy = false;
      state.reached = 5;
      paintSteps();
      paintRender();
      if ($("premiere")) $("premiere").disabled = false;
      setStatus("The fight is ready. Premiere it.", "ok");
    } catch (e) {
      state.busy = false;
      let msg = esc((e && e.message) || "The fight failed.");
      if (charged) {
        state.tickets += cost();
        renderTickets();
        msg += " Your entry tickets were returned.";
      }
      if (e && e.message && /tickets/i.test(e.message)) msg += ` <a href="/buy-credits">Buy credits</a> or come back for your free daily tickets.`;
      state.ack = null;
      state.rolled = null;
      state.step = 3;
      state.reached = 3;
      render();
      setStatus(msg, "err");
    }
  }

  // ── 04 director ──────────────────────────────────────────────────────────────────────────
  function beatRows() {
    const beats = (state.ack && state.ack.beats) || [];
    const d = state.ack ? state.ack.duration || state.duration : state.duration;
    const n = beats.length || 1;
    const names = n === 1 ? ["Finisher"] : beats.map((_b, i) => (i === 0 ? "Opening" : i === n - 1 ? "Finisher" : i === 1 ? "Clash" : "Turn"));
    const chips = [];
    (state.ack ? state.ack.duels : []).forEach((x) => {
      ["blue", "red"].forEach((c) => {
        const s = x.skills[c];
        const f = c === "blue" ? x.blue_fighter : x.red_fighter;
        if (s) chips.push({ key: s.name, html: `<span class="bt-chip ${c}">${esc(s.name)} · ${esc(f.name)}</span>` });
      });
    });
    const used = new Set();
    const rows = beats.map((b, i) => {
      const a = Math.round((d * i) / n);
      const z = Math.round((d * (i + 1)) / n);
      const mine = chips.filter((c) => !used.has(c.key) && b.toLowerCase().includes(String(c.key).toLowerCase()));
      mine.forEach((c) => used.add(c.key));
      return { t: `${a}–${z}s`, name: names[i], text: b, chips: mine.map((c) => c.html).join("") };
    });
    const left = chips.filter((c) => !used.has(c.key)).map((c) => c.html).join("");
    return { rows, left };
  }
  function directorHtml() {
    const ack = state.ack || {};
    const { rows, left } = beatRows();
    const beats = rows
      .map(
        (r, i) =>
          `<div class="bt-beat"><div class="t"><b>${r.t}</b><small>${esc(r.name)}</small></div><div><p data-beat="${i}">${state.typing ? "" : esc(r.text)}</p>${r.chips}</div></div>`
      )
      .join("");
    const fighters = (ack.duels || []).flatMap((x) => [x.blue_fighter.name, x.red_fighter.name]);
    const skills = (ack.duels || []).flatMap((x) => ["blue", "red"].map((c) => (x.finisher[c] ? "Finisher" : x.skills[c] && x.skills[c].name)).filter(Boolean));
    const dur = ack.duration || state.duration;
    const speak = rollLine() || "Writing the fight.";
    return `
      <section class="bt-dir-left">
        <div class="bt-stage-leera"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg><b>LEERA</b><small>AI Director · Animated</small></div>
        ${leeraHtml(state.render.status === "delivered" ? "Wrapped" : "Writing", speak)}
      </section>
      <section class="bt-panel bt-beats-panel">
        <div class="bt-eyebrow">Step 04 · Director's cut</div>
        <h2 class="bt-h2" style="margin-bottom:6px">The fight, beat by beat</h2>
        ${beats || `<p class="bt-note">Leera is writing…</p>`}
        ${left ? `<div>${left}</div>` : ""}
        <div><button type="button" class="bt-btn" id="rewrite" style="min-height:44px;font-size:14px;margin-top:10px">Watch Leera write it</button></div>
      </section>
      <section class="bt-dir-right">
        <div class="bt-panel bt-sent"><div class="bt-h3">Sent to video gen</div>
          <dl><dt>Characters</dt><dd>${esc(fighters.join(" · "))}</dd>
          <dt>Arena</dt><dd>${esc(ack.arena || "")}</dd>
          <dt>Length</dt><dd>${dur} seconds · 16:9</dd>
          <dt>Abilities</dt><dd>${esc(skills.join(", ") || "None this time")}</dd>
          <dt>Outcome</dt><dd>Sealed on server before render</dd></dl></div>
        <div class="bt-panel bt-render"><div class="bt-h3">Render</div><div id="renderBox">${renderInner()}</div></div>
        <button type="button" class="bt-btn blue" id="premiere" ${state.render.status === "delivered" ? "" : "disabled"}>Premiere the fight →</button>
      </section>`;
  }
  function renderInner() {
    const order = ["script", "queued", "rendering", "delivered"];
    const at = Math.max(1, order.indexOf(state.render.status));
    const stages = order
      .map((s, i) => `<span class="${i < at || (s === "delivered" && at === 3) ? "done" : i === at ? "now" : ""}">${s}</span>`)
      .join("");
    return `<div class="bt-stages">${stages}</div><div class="bt-bar"><i style="width:${state.render.pct}%"></i></div><div class="bt-render-meta"><span>${state.render.pct}%</span><span>${
      state.render.status === "delivered" ? "Ready" : "Filming…"
    }</span></div>`;
  }
  function paintRender() {
    const box = $("renderBox");
    if (box) box.innerHTML = renderInner();
  }
  async function typeBeats() {
    if (state.step !== 4 || state.typing) return;
    const { rows } = beatRows();
    state.typing = true;
    document.querySelectorAll("[data-beat]").forEach((p) => (p.textContent = ""));
    for (let i = 0; i < rows.length; i++) {
      const p = document.querySelector(`[data-beat="${i}"]`);
      if (!p) break;
      p.classList.add("bt-typing");
      const text = rows[i].text;
      for (let k = 1; k <= text.length; k += 2) {
        if (state.step !== 4) break;
        p.textContent = text.slice(0, k);
        await sleep(14);
      }
      p.textContent = text;
      p.classList.remove("bt-typing");
    }
    state.typing = false;
  }

  // ── 05 result ────────────────────────────────────────────────────────────────────────────
  function resultHtml() {
    const ack = state.ack || {};
    const job = state.job || {};
    const w = ack.winner || {};
    const teams = state.mode === "teams";
    const dur = ack.duration || state.duration;
    let winCard = "";
    if (!teams) {
      const x = (ack.duels || [])[0];
      const f = x && (w.side === 0 ? x.blue_fighter : x.red_fighter);
      const mine = [...state.blue, ...state.red].find((c) => f && String(c.id) === String(f.id));
      winCard = cardHtml(mine || (f && { id: f.id, name: f.name, url: f.art }), "gold");
    } else {
      const side = w.side === 0 ? state.blue : state.red;
      winCard = `<div class="bt-teamrow" style="width:100%">${side.map((c) => cardHtml(c, "gold")).join("")}</div>`;
    }
    const lost = state.mode === "ai" && w.side === 1;
    const rewards = [];
    if (state.mode === "ai") {
      if (ack.ticket_win) rewards.push(`<div class="r"><span>${TICKET} Tickets won</span><b>+${ack.ticket_win}</b></div>`);
      else if (ack.ticket_refund) rewards.push(`<div class="r"><span>${TICKET} Back for fighting up</span><b>+${ack.ticket_refund}</b></div>`);
      else rewards.push(`<div class="r"><span>${TICKET} Tickets won</span><b class="muted">0</b></div>`);
    } else {
      rewards.push(`<div class="r"><span>${TICKET} Tickets</span><b class="muted">XP only · your own cards</b></div>`);
    }
    rewards.push(`<div class="r"><span>Entry</span><b class="muted">${CFG.isAdmin ? "free (admin)" : "−" + (ack.ticket_cost || cost(dur)) + " tickets"}</b></div>`);
    const names = {};
    (ack.duels || []).forEach((x) => {
      names[x.blue_fighter.id] = x.blue_fighter.name;
      names[x.red_fighter.id] = x.red_fighter.name;
    });
    Object.entries(job.progress || {}).forEach(([id, p]) => {
      const lv = p.level || 1;
      const next = CFG.levelXp[lv];
      const xp = p.xp || 0;
      const bar = next
        ? `<div class="xp"><div><span>${esc(names[id] || "Card")} · XP to Level ${lv + 1}</span><i>${xp.toLocaleString()} / ${next.toLocaleString()}</i></div><div class="bt-bar"><i style="width:${Math.min(100, (xp / next) * 100)}%"></i></div></div>`
        : `<div class="r"><span>${esc(names[id] || "Card")}</span><b class="gold">Max level</b></div>`;
      rewards.push(`<div class="r"><span>${esc(names[id] || "Card")} XP</span><b class="gold">+${p.gained || 0}</b></div>` + bar);
    });
    const x = (ack.duels || [])[0];
    const wc = w.side === 0 ? "blue" : "red";
    const ws = x && !teams ? (x.finisher[wc] ? "The finisher" : x.skills[wc] && x.skills[wc].name) : "";
    const wrap = `That's a wrap. ${esc(w.name || "")} takes it.${ws ? ` ${esc(ws)} was the difference.` : ""}`;
    return `
      <section class="bt-res-left">
        <div class="bt-res-head"><div class="bt-eyebrow">Step 05 · Premiere</div><span>${esc(ack.arena || "")} · ${dur}s</span></div>
        <div class="bt-video"><video src="${esc(job.url || "")}" controls playsinline loop></video></div>
        <div class="bt-res-actions">
          <button type="button" class="bt-btn" id="rematch">Rematch</button>
          <a class="bt-btn" href="/library" title="Battle videos save to your Library automatically">In your Library ↗</a>
          <button type="button" class="bt-btn" id="share">Share</button>
          <button type="button" class="bt-btn" id="toLobby2">Back to lobby</button>
        </div>
        ${leeraHtml("Wrapped", wrap)}
      </section>
      <section class="bt-res-right">
        <div class="bt-panel bt-winner${lost ? " lost" : ""}"><small>Winner</small>${winCard}<div class="takes">${esc(teams ? w.name + " wins" : (w.name || "") + " takes it")}</div></div>
        <div class="bt-panel bt-rewards">${rewards.join("")}</div>
      </section>`;
  }
  async function share() {
    const url = state.job && state.job.url;
    if (!url) return;
    try {
      if (navigator.share) await navigator.share({ title: "Battle Cards", url });
      else {
        await navigator.clipboard.writeText(url);
        setStatus("Video link copied.", "ok");
      }
    } catch (_e) {}
  }

  // ── wiring ───────────────────────────────────────────────────────────────────────────────
  $("steps").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-step]");
    if (b && !b.disabled) {
      setStatus("");
      go(Number(b.dataset.step));
    }
  });
  $("main").addEventListener("click", (e) => {
    const t = e.target;
    const m = t.closest("[data-mode]");
    if (m) return setMode(m.dataset.mode);
    const card = t.closest("#deck .bt-card");
    if (card) return tapDeck(card.dataset.id);
    const red = t.closest("[data-red]");
    if (red) return tapRed(red.dataset.red);
    const d = t.closest("[data-d]");
    if (d && !state.busy) {
      state.duration = Number(d.dataset.d);
      if (state.rolled) resetFight();
      return render();
    }
    const a = t.closest("[data-arena]");
    if (a && !state.busy) {
      state.arena = a.dataset.arena;
      return render();
    }
    if (t.closest("[data-buy]")) return buyTickets();
    const id = (t.closest("button[id], a[id]") || {}).id;
    if (id === "toLobby" || id === "toLobby2") return go(2);
    if (id === "agree") return go(3);
    if (id === "battle") return startBattle();
    if (id === "rewrite") return typeBeats();
    if (id === "premiere") return go(5);
    if (id === "share") return share();
    if (id === "rematch") {
      resetFight();
      state.reached = 3;
      return go(3);
    }
  });
  $("main").addEventListener("change", (e) => {
    if (e.target.id !== "bgFile") return;
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    if (state.uploadUrl) URL.revokeObjectURL(state.uploadUrl);
    state.upload = f;
    state.uploadUrl = URL.createObjectURL(f);
    state.arena = "upload";
    render();
  });

  async function buyTickets() {
    if (!CFG.loggedIn) {
      location.href = "/login?next=/studios/battle-cards";
      return;
    }
    try {
      const res = await fetch("/studios/battle-cards/buy-tickets", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ amount: 5 }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setStatus(esc(data.error || "Could not buy tickets.") + (res.status === 402 ? ' <a href="/buy-credits">Buy credits</a>' : ""), "err");
        return;
      }
      if (data.tickets != null) {
        state.tickets = data.tickets;
        renderTickets();
      }
      setStatus(esc(data.message || "+5 tickets"), "ok");
      if (state.step === 3 && !state.busy) render();
    } catch (_e) {
      setStatus("Network error. Try again.", "err");
    }
  }
  $("buyTix").addEventListener("click", buyTickets);

  // Library → "Battle with this card"
  window.percfectPickCard = function (card) {
    if (!card || card.id == null) return;
    if (!state.cards.some((c) => String(c.id) === String(card.id))) state.cards.unshift(normal(card));
    state.step = 1;
    tapDeck(card.id);
  };
  function normal(c) {
    return { id: String(c.id), name: c.name || "Card", url: c.url || c.thumb || "", level: c.level || 1, xp: c.xp || 0, serial: c.serial || "" };
  }

  // the floor grid from the design: lines fanning out from the horizon
  function drawGrid() {
    const svg = $("grid");
    const W = window.innerWidth;
    const H = window.innerHeight;
    const cx = W / 2;
    const hy = H * 0.44;
    let out = "";
    for (let i = -12; i <= 12; i++) out += `<line x1="${cx}" y1="${hy}" x2="${cx + i * 140 * (W / 1440)}" y2="${H}" stroke="#39c0e6" stroke-opacity=".08"/>`;
    let y = hy + 20;
    let step = 11;
    while (y < H) {
      out += `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="#39c0e6" stroke-opacity=".06"/>`;
      step *= 1.35;
      y += step;
    }
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = out;
  }
  window.addEventListener("resize", drawGrid);

  async function boot() {
    drawGrid();
    render();
    if (!CFG.loggedIn) return;
    try {
      const res = await fetch("/api/my-library", { credentials: "same-origin" });
      const lib = res.ok ? await res.json() : {};
      state.cards = (lib.cards || []).map(normal);
    } catch (_e) {
      state.cards = [];
    }
    let pending = null;
    try {
      pending = sessionStorage.getItem("percfect_battle_pick");
      sessionStorage.removeItem("percfect_battle_pick");
    } catch (_e) {}
    const hit = pending && state.cards.find((c) => String(c.id) === String(pending));
    if (hit) state.blue = [hit];
    render();
  }
  boot();
})();
