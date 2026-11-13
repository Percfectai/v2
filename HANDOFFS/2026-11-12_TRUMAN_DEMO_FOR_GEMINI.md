# Handoff → Gemini — the 3D WORLD only

**From:** Claude Code · **Date:** 2026-11-12 (updated) · **Repo:** `~/percfectstudios` (PRIVATE)

## 🎯 SCOPE (Nick's split — read this first)
**Gemini builds ONLY the Three.js world / stage.** Claude Code owns the website + the entire pipeline + agent brains + chat. So:

- **Gemini (you):** the visual 3D world — ground/grass, a tree or two, a sun that rises/sets on a clock, lighting, camera, and the stage that **renders whatever rigged character GLB the pipeline hands you** and plays its idle/walk via the existing `CharacterController`. Make it stable for a live call. That's it.
- **Claude (me):** Build-a-Character → multi-image → 3D+animation generation → the **agent/LLM setup** (persona + prompt) → the agent **taking over** the character's animations (driving `CharacterController` commands) → the agent's **perception** of the board → the **phone-style chat box** all agents talk through. I wire the GLB + the agent driver into your world; you don't build pipeline, brains, or chat.

Contract between us: your world exposes the existing `CharacterController` (`static/js/rivals/character_controller.js`) per character and calls `update(dt, camera)` in your animate loop. I feed it characters (GLB URLs from `assets_3d/`) and drive it via the agent command queue + `field_body_drive.js`. Keep using `three@0.160.0` importmap so the controller's loaders line up.

**Goal:** a small, stable live-call demo — one character alive in a tiny Three.js world. **Reuse what's below; don't build from scratch, and don't touch the pipeline/agent/chat code — that's mine.**

---

## ⚠️ READ FIRST — the Eternal Rivals system is ALREADY BUILT in the live repo
This is not a from-scratch build. A working, admin-gated rivals system already ships in `~/percfectstudios`. The demo is **assembly + wiring + assets**, not new construction. Inventory:

**Client (`static/js/rivals/`):**
- `character_controller.js` (49KB) — loads any rigged GLB, fits + plants feet, unified command interface (`move`/`turn`/`idle`/`attack_light`/`attack_heavy`/`block`/`dodge`/`hit_react`/`ko`/`jump`), Mixamo↔Meshy fuzzy bone retargeting, `attachMotionGltf`/`attachAnimationSet` (17-clip set), **procedural gait fallback** when clips are missing.
- `user_driver.js` (keyboard/touch), `agent_driver.js` (agent takeover), `combat.js`, `rivals_config.json`, `agent_field_config.json`.

**In-world chat (`static/js/`):** `world_group_chat.js` (16KB — polls `/api/3d/world-chat/messages`, posts `/api/3d/world-chat/send`), `world_chat_boards_boot.js`, `field_body_drive.js`, `field_anim_sim.js`. This is the in-repo equivalent of the Heart War Room — **use it instead of copying from ara-talk.**

**Stages (prototypes/ + motion-lab/):** `rivals-stage.html`, `agent-field.html`, `colosseum-duel.html`, `colosseum-stage.html`, `metro-tunnel-stage.html`.

**Backend (`app.py`, admin-only, not in nav):** `/studios/3d/rivals` → `rivals-stage.html`; `/studios/3d/agent/field` → `agent-field.html`; `POST /studios/3d/agent/command` → the agent command queue (`_RIVALS_AGENT_QUEUE`, `_RIVALS_ALLOWED_ACTIONS`); the `/api/3d/world-chat/*` chat endpoints; plus per-seat agent chat / key / instructions / designations / reports handlers. Gated by `_rivals_require_admin()`.

**Asset masters:** `~/percfectstudios/assets_3d/` (`characters/ stages/ vehicles/`) is the GLB master home — **gitignored** (`.gitignore` lines 29–33: `assets_3d/`, `static/user_glb_characters/`, `static/motion-lab/*.glb`, `prototypes/*.glb`, `**/*.glb`). ⚠️ On this machine `assets_3d/characters/` currently has **no committed GLB on disk** — the masters are the duplicates in Downloads (same `character.glb`/`character_textured.glb` that the `.MOVED_TO_PERCFECT_ASSETS_3D.txt` stubs point back to). **First real task: copy a rigged character GLB into `assets_3d/characters/` (stays gitignored).**

### What this means for the demo (the REAL gaps)
1. **Assets** — put at least one rigged character GLB (+ idle/walk clips) into `assets_3d/characters/`; wire a small environment GLB (low-poly castle, or the DJ desk) as the `?stage=`.
2. **The tiny world** — grass plane + a tree or two + a day/night sun on a clock, on the existing stage. `metro-tunnel-stage.html` already shows `AnimationMixer` + movement to copy.
3. **Agent brains → Gemini Flash** — confirm/point the world-chat + agent-command loop at Gemini Flash (one Google AI Studio key, env var). Pace it (slow tick when unwatched) per the cost rule.
4. **Step 2b — agent setup stage** — add the persona-setup step to the pipeline (below); `rivals_config.json` already holds persona/combat tuning (Nick owns the wording).
5. **Surface it** — the admin routes exist; the public booth is `the_dome.html`. Pick one clean entry for the live call.

Everything below is the deeper reference (vision, assets, Heart pattern, rules). The parts above supersede any "build from scratch" reading.

---

## Original TL;DR (still true, now with the above on top)
Nick's repo already has the whole skeleton of the "Truman Show / Eternal Rivals" idea. Your job is to assemble a clean demo from these parts on a new branch, not reinvent them.

- **The booth page is built:** `templates/the_dome.html` = THE DOME — *"Two rivals live in the ring. You sit in the silent booth and throw the weather, the weapons, the next beat. They never know you are here."* Today it's an iframe shell that loads `THE_DOME_URL`. Routes: `/studios/the-dome`, `/studios/dome`, `/the-dome` (login required). **This is where the demo should surface.**
- **A 2-character Three.js stage is built:** `prototypes/stage-board.html` — orbit/zoom, `?glb=` character, `?glb2=` second character, `?stage=` environment GLB. Served admin-only at `/proto/stage-board`.
- **A reusable 3D viewer partial:** `templates/partials/stage_3d.html` (215 lines) — importmap `three@0.160.0`, `GLTFLoader`, loads a job's GLB, download button.
- **A movement scene with animation:** `prototypes/metro-tunnel-stage.html` (800 lines) — `AnimationMixer`, movement HUD, pilot body, loads character + environment GLBs. Best reference for idle/walk playback.
- **A 360 turntable:** `prototypes/spin-studio.html` (`/proto/spin-studio`).
- **The 3D generation pipeline (Tripo/Meshy/PoYo → GLB):** `three_d_character_gen.py` owns `/api/3d/*` (generate-character, multi-image → rigged GLB), plus `percfect_3d_providers.py`, `percfect_api_3d.py`, `poyo_client.py` (GLB/FBX extraction), `routes/3d_characters.py` (roster picker, config probe).

**Three.js version to match everywhere:** `three@0.160.0` via unpkg importmap (`three` + `three/addons/`). Keep it consistent so loaders line up.

---

## Step 1 findings (what I searched, what exists)

### The vision (origin + canonical docs — read these)
- **`HANDOFFS/vision/ETERNAL_ARENA.md`** — the real build guidance. Key points: build the BRAIN first on the existing 2D Arena (cheap text/image rival loop + GM injection), prove it's addictive and cost-controlled, THEN graft onto 3D. **Cost is the #1 killer:** the scheming loop must tick slowly when unwatched, think hard only when a user is present or on a daily beat.
- Origin transcript (same content, many copies): `~/claudev2/Truman Show.txt` and 8+ duplicates across the Mac. This is the Grok Build conversation where the concept was born (chain of agents → immersed 3D rivals → "Truman Show Director" GM injecting daily variables). Already distilled into the vision doc above — you don't need to re-read the raw transcripts.
- Prior build spec (memory): a PRIVATE build was started 2026-07-16 — admin-only `/studios/3d/rivals`, one control abstraction (move + fight: attack/block/dodge/hit/ko, health, 2 characters), Driver A = user (keyboard/touch), Driver B = agent takeover via `POST /studios/3d/agent/command` queue driving the same interface. Any roster GLB loadable.

### Character-movement boilerplate (optional reference — different stack)
`~/Downloads/.../slow n steady/GLB 3D THE PAGE/r3f-character-controls-main/` — a **React-Three-Fiber + React-Three-Cannon** boilerplate (thomas-rooty): smooth movement with accel/decel, follow-camera, raycast collision, physics. Good movement reference, **but it's R3F/React**, whereas the repo's scenes are vanilla `three@0.160.0` importmap. For a stable call demo, prefer extending the repo's vanilla `metro-tunnel-stage.html` movement rather than introducing a React build; pull ideas (accel/decel, follow cam) from r3f if useful. More GLBs in that same folder: `CARDS FROM GROK/jojomollica.glb`, `CARDS FROM GROK/gian-giant.glb`.

### Ready-made GLB drag-drop viewer + more references
- **`~/Desktop/Wolverine_3D_EasyOpen/DROP_ON_3JS.html`** — a self-contained drag-a-GLB-onto-the-page Three.js viewer (drop zone → `GLTFLoader` → `AnimationMixer`). Uses `three@0.164.1` (note: repo is pinned at `0.160.0` — pick one version and stick to it). Fastest way to eyeball any GLB's animations. That folder also shows the **exact pipeline output**: `00_source_360_spin.mp4` → `01..04_source_{front,left,right,back}.jpg` → `meshy6_character.glb` (now moved to `assets_3d/`), confirming `assets_3d/` is the local GLB masters home.
- **Three.js skill guides** (reference, in Downloads): `~/Downloads/agentic-awesome-skills-main/skills/threejs-animation/references/detailed-guide.md` and `.../threejs-loaders/references/detailed-guide.md` — animation mixer + GLTF/FBX loader patterns.

### GLB / FBX assets (NOT in the repo — gitignored; masters live in Downloads)
No `.glb`/`.fbx` are committed (see "3D = PRIVATE" below). More GLBs also at `~/princessdownloads/` (`dj character 3d model_Clone1.glb`, `dj_mixer_desk.glb` — DJ character + a desk/environment prop; note the princessdownloads *package* is old but these model files are fine as assets). Rigged masters with animations are here:
`~/Downloads/downloadsort/07_Archive/July_August_2026/3d/`
- `character.glb`
- `vader(idle).glb`, `jasbride(idle).glb`, `redjas(idle).glb` — **idle-animation GLBs**
- `Meshy_AI_Crimson_Siren_biped_..._Merged_Animations.glb`, `redjas (dance?)..._Merged_Animations.glb` — **rigged biped with merged animation clips**
- `Meshy_AI_Low_Poly_Castle_...glb` — an environment GLB (stage candidate)
- `poyo_X_cast.glb`, plus `~/Downloads/downloadsort/jojomollica.glb`

For the demo you need **one** rigged character GLB with an idle + a walk clip. Start with a `..._Merged_Animations.glb` (has clips) or an `(idle).glb`. Copy the chosen file into a **local, gitignored** stage-assets dir (e.g. `static/user_glb_characters/` or `assets_3d/`) and reference it by path — never commit the GLB.

### The 3D routes already wired (`app.py`)
`/the-dome` + `/studios/the-dome` (THE DOME), `/3d`, `/studios/3d`, `/studios/3d-games`, `/studios/3d/rivals`, `/studios/3d/field`, `/studios/3d/crew`. `three_d_character_gen.init_app(app)` mounts `/api/3d/*`.

### The Heart app messaging (reuse the pattern — do NOT touch `~/ara-talk`)
The reusable multi-agent chat is the **War Room** in `~/ara-talk/heart-native/war_room.py`. How it works:
- A War Room is a shared group chat for two agents (A + B) plus the user.
- The shared transcript is an **append-only JSONL file** (`write_room` / `append_room_line`); only the **last ~16 messages** are fed back in as context.
- `brief_for(name, partner, user_text, room_messages)` builds each agent's prompt, embedding that recent shared transcript so **both agents see each other**.
- `RoomAgent.send(user_text, room_messages)` runs the agent (currently via Grok Build CLI, model `grok-4.5`) and returns a reply, which is appended to the shared file.

**Reuse:** copy this pattern for the in-world chat between the two rivals — a per-stage shared transcript + world-state file that each agent reads (last N lines) before replying. Swap the Grok Build CLI call for **Gemini Flash** (see below). **Do not import from or modify `~/ara-talk`** — it's a separate live app; copy the idea, not the files.

---

## What to build (Steps 2, 2b, 3)

### Step 2 — Assemble the demo
- One Tripo-made rigged character GLB playing **idle** + **walk** (use `AnimationMixer`; copy from `metro-tunnel-stage.html`).
- A small world: grass ground plane, a tree or two, a sun that rises/sets on a clock.
- Simple and stable — it has to run reliably on a live call. Build it on the **stage-board** foundation (`?glb=` / `?stage=`) rather than a blank scene.

### Step 2b — Agent setup stage (new pipeline step)
Pipeline order: **photo → 360 → multi-view → 3D model → agent setup → into the world.**
- After the 3D model is made, add an "agent setup" step where the user personalizes the character's agent (who it is, how it talks, what it wants) and that gets saved as the agent's prompt.
- That saved prompt drives the character once it's in the world.

### Step 3 — Optional if time allows
- A small in-world chat box in the scene.
- Hook the character to an LLM so it can say a line or two (use the War Room transcript pattern above).

### Agent brains (LLM)
- Start with **Gemini Flash free tier**, one **Google AI Studio API key** for all agents.
- Each agent gets its own prompt + memory; messages pass between agents through the in-world chat (shared transcript).
- Build model-swappable (Claude, Grok, etc.) without rebuilding.
- **Key goes in an env var, never in code or Git.** Expect free-tier rate limits — pace the agents' chat (slow tick when unwatched; this matches the cost rule in the vision doc).

---

## Hard rules (do not break)
1. **3D = PRIVATE** (`HANDOFFS/3D_PRIVATE.md`, Nick's law). Repo stays **private**. `*.glb`, `assets_3d/`, `static/user_glb_characters/` are **gitignored** — keep them that way; never commit a GLB or make a 3D route public without Nick's explicit OK. 3D surfaces stay login/admin-gated.
2. **Do not change Build a Character, Comics, or Hero Cards.** They must keep working untouched. Build a Character stays the shared starting point for every path; the 3D + agent journey gets its **own separate section/files**. Comics and hero cards never need any 3D step.
3. **You (Gemini) own the 3D section's files.** Claude Code won't edit them while you're building, so you don't collide. Keep your work under the 3D section / `prototypes/` / a `stage/` assets dir.
4. **Work on a branch, open a PR. Never push to main.** Nick approves before deploy.
5. **Never commit or print API keys.** Env vars only.
6. Add a small **"3D powered by Tripo"** credit in the 3D section.
7. **Don't touch `~/ara-talk` (Heart app)** — reuse/copy the War Room comms pattern only.

---

## Suggested first move
1. Branch off `main` (e.g. `lane/truman-3d-demo`).
2. Copy one `..._Merged_Animations.glb` from the Downloads 3d folder into a gitignored local assets dir.
3. Fork `prototypes/stage-board.html` → a small demo scene: load that character, add ground + tree + a day/night sun, play idle→walk via `AnimationMixer`.
4. Surface it where `the_dome.html` expects a booth (or a new admin-gated `/studios/3d/demo`).
5. Open a PR; leave the GLB out of the diff. Report what you reused, what you built, what's still missing.
