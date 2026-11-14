# ETERNAL RIVALS / Truman Show — MASTER consolidation + build plan

**Date:** 2026-11-12 · **Author:** Claude Code · **Repo:** `~/percfectstudios` (PRIVATE — keep private)
**Purpose:** the single place that pulls together work scattered across the Mac, states who builds what, maps the pipeline, and lists the build stages. Nick's wish: *"I wish I had all of this together."* This is that.

---

## 1. Division of labor (Nick's split, 2026-11-12)
- **Gemini → the Three.js WORLD only.** Ground/grass, tree(s), day/night sun on a clock, lighting, camera, and a stage that renders whatever rigged character GLB the pipeline hands it and plays idle/walk via the existing `CharacterController`. Stable for a live call. Nothing else. (Brief: `HANDOFFS/2026-11-12_TRUMAN_DEMO_FOR_GEMINI.md`.)
- **Claude → the website + the whole pipeline + agent brains + chat.** Everything in §3.

---

## 2. The pipeline (Nick's definitive spec, 2026-11-12) — with THE GAP marked
```
BUILD character
  → 360 VIDEO (generate-spin)
  → MULTI-IMAGE (front/left/right/back snapped from the 360)
  → TRIPO 3D GLB (multi-image → Tripo/Meshy rigged mesh)
  ───────────────────────────────────────────────────────────
  → ⛔ GAP: FBX ANIMATED + RIGGED
        the static Tripo GLB must become a RIGGED character carrying the
        animation set (idle/walk/attack/block/dodge/hit/ko…), FBX/Mixamo-style,
        so a controller can play clips — not just slide a static mesh.
  ───────────────────────────────────────────────────────────
  → LLM AGENT CONTROLS THE RIG (all skills/tools: the full CharacterController command set)
        + persona/prompt setup (who it is, how it talks, what it wants)
        + perception (sees the board through its own eyes)
  → THREE.JS BOARD (Gemini's world renders it)
  → CHAT ROOM (phone-style box; how all agents on the board talk to each other)
```
Nick drops any character through the website; the pipeline carries it all the way to a living agent on the board. **The GAP is the one piece that isn't solid yet** — rigging + animation on the Tripo output.

### Why the gap is mostly closable with what exists
`character_controller.js` already: fuzzy-maps Mixamo↔Meshy bones, retargets clips from a motion GLB onto the character's skeleton (`attachMotionGltf`/`attachMotionUrl`), loads a full 17-clip set (`attachAnimationSet`, see `HANDOFFS/GROK_ANIMATION_SET_INTEGRATION.md` + `static/motion-lab/controller.html`), and falls back to a **procedural gait** when no clip binds. So the real work in the gap is: (a) confirm Tripo's GLB comes out **rigged** (skinned skeleton), and (b) provide the **animation-set source** (the 17-clip Meshy set or an FBX/Mixamo pack) to retarget on. If Tripo returns an unrigged mesh, that's the auto-rig sub-problem to solve or outsource (Meshy/Mixamo auto-rig).

---

## 3. What ALREADY EXISTS in the live repo (don't rebuild — wire it)
**Client — `static/js/rivals/`:** `character_controller.js` (49KB: load GLB, fit+plant feet, unified command interface move/turn/idle/attack_light/attack_heavy/block/dodge/hit_react/ko/jump, Mixamo↔Meshy bone retarget, `attachMotionGltf`/`attachAnimationSet` 17-clip, procedural gait fallback), `user_driver.js`, `agent_driver.js`, `combat.js`, `rivals_config.json`, `agent_field_config.json`.

**In-world chat — `static/js/`:** `world_group_chat.js` (polls `/api/3d/world-chat/messages`, posts `/send`), `world_chat_boards_boot.js`, `field_body_drive.js`, `field_anim_sim.js`. Backend `world_chat_api.py`: `/api/3d/world-chat/{messages,send,crew}`, `pick_responders`, per-seat agent replies.

**Stages — `prototypes/` + `static/motion-lab/`:** `rivals-stage.html`, `agent-field.html`, `colosseum-duel.html`, `colosseum-stage.html`, `metro-tunnel-stage.html`, `aethelgard-stage.html`, `agent-stage.html`. (These are Gemini's starting points — he polishes the WORLD.)

**Pipeline backend — `app.py` / `three_d_character_gen.py` / `studio_task_handlers.py`:**
- Build-a-Character: `/studios/percfectcharacter` + generate-one, precision-seed, pack, finalize, refine, restyle, split-version, **generate-spin (360)**, edit, characters, download, set-version.
- Multi-image → 3D: `three_d_character_gen.py` `generate_character()` (`/api/3d/generate-character`, PoYo Meshy-6 multi-image → rigged GLB), status poll, `store_user_glb_character`, `list_library_characters_for_3d`, upload.
- Agent layer (admin-only, not in nav): `/studios/3d/rivals`, `/studios/3d/field`, `/studios/3d/crew`, `POST /studios/3d/agent/command` (+ `_RIVALS_AGENT_QUEUE`, `_RIVALS_ALLOWED_ACTIONS`), `/studios/3d/agent/commands`, `/api/lab/agents`, `/api/lab/agent/<seat>/chat`. Gated by `_rivals_require_admin()`.

**Asset master:** `~/percfectstudios/assets_3d/` (`characters/ stages/ vehicles/`) — gitignored (`.gitignore` 29–33). ⚠️ `characters/` has no committed GLB on disk here now; copy masters in from the troves in §5.

---

## 4. BUILD PLAN — the stages Claude owns (pipeline + website)
**Priority = close the GAP first (stage 2, rigging + animation).** Nick flagged it as the one piece that isn't solid. Each stage is additive; Build-a-Character / Comics / Hero-Cards must keep working. Branch + PR, never push to main. 3D stays private/admin-gated. **Prompt wording is Nick's only — I build the fields/plumbing, not the persona text** ([[never-change-prompts]]).

1. **Stitch the existing flow** — one continuous journey: character → multiview → 3D. Confirm `generate-spin` → `/api/3d/generate-character` handoff; make "make 3D" reachable from a finished character.
2. **Animation attach** — ensure the generated/updated GLB gets idle/walk (and the 17-clip set when present) via `attachAnimationSet`/`attachMotionGltf`. Masters/clips from §5.
3. **AGENT SETUP page (the keystone gap)** — a new step after 3D: capture persona (who it is, how it talks, what it wants) + save as the agent's prompt, stored per character (extend `rivals_config.json` / a per-character persona store). Nick writes the actual persona words; I build the form + storage + wiring.
4. **Agent takeover** — point the agent brain at **Gemini Flash** (one Google AI Studio key, env var, model-swappable), feed it the saved persona + perceived board state, have it emit `CharacterController` commands through `/studios/3d/agent/command` + `field_body_drive.js`. Pace it (slow tick when unwatched) per the cost rule in `HANDOFFS/vision/ETERNAL_ARENA.md`.
5. **Perception** — assemble the "through its own eyes" context: own + others' positions/health/state + recent world-chat, fed into the agent prompt each tick.
6. **Phone-style chat box** — the cell-phone chat UI in the scene over `world_group_chat.js` + `/api/3d/world-chat/*`; this is how agents talk to each other on the board.
7. **Surface** — admin routes exist; public booth is `the_dome.html`. Pick one clean entry for the live call.

---

## 5. Scattered-work inventory (consolidate FROM here INTO `assets_3d/`)
Real roots (ignore `~/.grok/worktrees/*` = git worktree copies, and `~/DUPLICATES_SAFE_TO_DELETE/*` = known dupes):

**Code/repos that carry rivals/3D work**
- `~/percfectstudios` — the live repo (source of truth).
- `~/percfect-v2` (567M) — the rebuild; has the same `static/js/rivals/*`, `world_chat_api.py`, extra stage `aethelgard-stage.html`, `proto_arena_stage.html`. Cross-check for anything newer.
- `~/Downloads/downloadsort/.../percfectstudios copy edit/` — a working copy with `world_chat_api.py`, `HANDOFFS/agent_field_app_patch.md`, the rivals `character_controller.js`, all stages.
- `~/Percfect Site Sorted/Old` + `New` — sorted site archive; `Old/Handoffs/Arena/Rival agents handoff.md`.
- `~/MetroBoard` — a metro-board 3D project (5 GLBs) tied to `metro-tunnel-stage`.
- `~/UnityProjects/GlbMultiplayerWorld` — a Unity multiplayer GLB world (separate engine; reference only).

**GLB/FBX asset troves (gitignored elsewhere; copy chosen masters into `assets_3d/characters|stages|vehicles/`)**
- `~/Percfect Site Sorted/Old/3D` (22) + `New/3D` (7) — largest trove.
- `~/Downloads/downloadsort/07_Archive/July_August_2026/3d` (12) — rigged idle + merged-animation bipeds, low-poly castle (stage).
- `~/princessdownloads/slow n steady/GLB 3D THE PAGE/` + `CARDS FROM GROK/` — dj character, gian-giant, jojomollica, etc.
- `~/Desktop/Wolverine_3D_EasyOpen/` — Wolverine pipeline sample (360 mp4 → 4 views → GLB) + `DROP_ON_3JS.html` drag-GLB viewer.
- `~/princessdownloads/` (dj character, dj_mixer_desk) · `~/3dviz-pro-max/.../kits/gltf` (kit props).
- The many `*.glb.MOVED_TO_PERCFECT_ASSETS_3D.txt` stubs all point back to `~/percfectstudios/assets_3d`.

**Vision / origin / references**
- `HANDOFFS/vision/ETERNAL_ARENA.md` (canonical), origin transcript `~/claudev2/Truman Show.txt` (+ 8 copies), `~/MyGrok/data/chats.json` & `~/memory/.../mygrok/chats.json` (full Grok history), r3f movement boilerplate (`~/Downloads/.../slow n steady/GLB 3D THE PAGE/r3f-character-controls-main`), three.js skill guides (`~/Downloads/agentic-awesome-skills-main/skills/threejs-{animation,loaders}`).

**Heart app (reuse pattern only, don't touch):** `~/ara-talk/heart-native/war_room.py` — shared append-only transcript each agent reads before replying. In-repo equivalent already exists (`world_group_chat.js`), so prefer that.

---

## 6. Hard rules
3D = PRIVATE (repo private; `*.glb`/`assets_3d/`/`user_glb_characters/` gitignored; 3D routes login/admin-gated). Don't change Build-a-Character/Comics/Hero-Cards behavior. Branch + PR, never push to main; Nick approves deploy. Keys in env only. Persona/prompt wording is Nick's. "3D powered by Tripo" credit in the 3D section.
