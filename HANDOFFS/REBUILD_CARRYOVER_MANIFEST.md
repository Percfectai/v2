# PERCFECT REBUILD — CARRY-OVER MANIFEST

**Created:** 2026-10-17 · **Author:** Claude (Opus 4.8) · **For:** Nick
**Purpose:** The feature-by-feature list of what moves from the old `percfectstudios` repo
into the **fresh repo / new Render / new Supabase**, trimmed of all the dead weight.
**Status:** LIVE. The original site is back up at https://percfectai.com. Render service is `percfectai-v2` (`https://percfectai-v2.onrender.com`), repo `Percfectai/v2`, trimmed of the dead products. Read `README.md` first. A comic page is coming. It is not a live lane yet. This file is the carry list, not a draft waiting for a repo name. Keys are not in git.

> Golden rule from the handoff dictation: **perfected features get reused with the EXACT
> same code.** Nobody rewrites a working feature. **Nobody touches the prompts but Nick.**
> This doc decides *which files move*, not *how they're rewritten* (they're not).

---

## 0. The problem we're solving (why a fresh repo)

- Old repo = **1.4 GB on disk, 876 MB of that is `.git` history, 1,063 tracked files.**
- Most of the bulk is dead products carried in git history forever. A clean copy-forward
  (new empty repo, copy only the live code + needed assets) is what actually kills the bloat.
  Cloning and deleting does **not** — the history keeps the weight.
- Repeated breakage came from many agents editing shared files with no lane discipline.
  The fresh build pairs each page with a **specialized agent** trained on that page's docs.

---

## 1. Infrastructure baseline (what the new repo starts from — carries verbatim)

| File | Role | Carry? | Note |
|---|---|---|---|
| `Dockerfile` | Playwright-python base + ffmpeg, gunicorn gthread | ✅ carry | Drop `perchance`/`PRINCESS_PAGE_ENABLED` env + the perchance profile lines (dead product) |
| `Dockerfile.worker` | background worker image | ✅ carry | only if we keep the worker service |
| `Procfile` | process defs | ✅ carry | review |
| `render.yaml` | Render service + env var declarations | ✅ carry, **edit** | new service name, strip Vercel/perchance/princess + Google-Maps demo keys unless used |
| `requirements.txt` | 18 deps | ✅ carry, **trim** | drop `perchance==0.1.0`; keep flask/supabase/stripe/pillow/opencv/mediapipe/numpy/playwright |
| `app.py` | 14,268-line Flask monolith | ⚠️ **extract, don't copy whole** | see §2 — we lift only the live routes + the locked `CHARACTER_SPIN_PROMPT` |

**`CHARACTER_SPIN_PROMPT` lives in `app.py`.** This is the 360° spin prompt Nick owns —
moves verbatim, locked, password-gated. Do not reformat it.

---

## 2. Live lanes — CARRY VERBATIM

Each lane below is a feature Nick has perfected. Code moves as-is; an agent owns each lane.

### CREATE ▸ Perfect Pictures
| Piece | Path |
|---|---|
| Route | `app.py` → `studio_mode="photos"` (≈ line 8685 block) |
| Template | `templates/percfectstudios.html` (shared photos/videos board) |
| Page JS | `static/js/studio_jobs.js` |
| Backend handlers | `studio_task_handlers.py` → `handle_image`, `handle_batch`, `_generate_photo_xai`, `_photo_source_images` |
| XAI keys | `xai_keys.py` · provider glue `ai_providers.py` |
| Jobs/queue | `studio_jobs.py` · `studio_enqueue.py` · `studio_worker.py` |

### CREATE ▸ Perfect Videos  *(already exists — answers the old open question)*
| Piece | Path |
|---|---|
| Routes | `app.py` → `/studios/percfectvideos`, `/studios/videos`, `/percfectvideos` (≈ line 8696) `studio_mode="videos"` |
| Template | `templates/percfectstudios.html` (same file, videos mode) + `static/js/video_extend.js`, `static/js/extend_byo.js` |
| Backend | `studio_task_handlers.py` → `handle_video`, `handle_extend`; `video_chains.py` |
| Note | Shares the Photos UX by design (refs, AI-assist, saved/recent, last-10 strip). Dictation confirms. |

### CREATE ▸ Percfect Productions  → **PARK (under construction) + consolidate history**
| Piece | Path |
|---|---|
| Blueprint | `percfect_productions_bp.py` |
| Client SPA | `static/percfectproductions/` |
| Action | Keep code but mark UC; gather all Productions handoffs into ONE dated history MD (in-repo), per dictation |

### BUILD ▸ Build-Your-Character  ← **biggest, most important, keep EXACTLY as is**
| Piece | Path |
|---|---|
| LIVE | `/studios/percfectcharacter` |
| Template | `templates/percfect_character.html` |
| Profile modal | `templates/partials/char_profile_modal.html` |
| Roster/profile JS | `static/js/character_profile.js` |
| Backend handlers | `studio_task_handlers.py` → `handle_character_one`, `character_precision_seed`, `character_pack`, `character_finalize`, `character_refine`, `character_restyle`, `handle_spin`, `_snapshot_angles_from_spin_video`, `_generate_character_xai` |
| Flow (verified in code) | front shot 1 cr → approve → pack (L/R + back + 360 spin) 50 cr → snapshot angles from spin @ 1.5s/3s/4.5s/6s. **Matches the dictation exactly.** |
| Locked prompt | `CHARACTER_SPIN_PROMPT` in `app.py` — Nick-only |

### BUILD ▸ Arena  ← **keep exactly as is (new under Build)**
| Piece | Path |
|---|---|
| LIVE | `/studios/percfectcharacter/arena` |
| Templates | `templates/proto_arena_stage.html`, `templates/arena_street_picker.html`, `templates/take_it_to_the_streets.html` |
| Backend | `studio_task_handlers.py` → `handle_arena`, `handle_fight`; `battle_agent.py`; `world_chat_api.py` (blueprint); `field_world_agents.py` |
| JS | `static/js/world_chat_boards_boot.js`, `world_group_chat.js`, `field_anim_sim.js`, `field_body_drive.js`, `percfect_stage_overlay.js`, `static/js/rivals/` |

### BUILD ▸ 3-D (Tripo)  ← **brand-new simple page; reuse the working pipeline**
| Piece | Path |
|---|---|
| Providers | `percfect_3d_providers.py` (Tripo multiview→GLB; meshy/replicate alts — env `PERCFECT_3D_PROVIDER`) |
| API | `percfect_api_3d.py` · blueprint `three_d_character_gen.py` (`/api/3d/generate-character`, `/library-characters`, `/upload-character`) · `routes/3d_characters.py` |
| Motion/rig | `motion_retarget.py`, `motion_analyze_poyo.py`, `motion_analyzer/`, `percfect_spin_renderer.py` |
| JS | `static/js/percfect_stage_3d.js`, `stage_glb_file_drop.js`, `user_library_glb_drop.js` |
| Pipeline (matches dictation) | character's 360 spin → multi-pose angle shots → Tripo multi-image → rigged `.glb` |
| History | Old 3-D projects/handoffs → **PRIVATE local MD, NOT in repo** (per dictation) |

### CARDS ▸ Card Studio · Battle Cards · Card Shop  ← **KEEP as its own top-nav section** (Nick, 2026-10-17)
| Piece | Path |
|---|---|
| Routes | `app.py` → `/cards` `/studios/cards` (hub); `/studios/trading-cards` (Card Studio); `/studios/battle-cards`; `/studios/card-shop` |
| Templates | `templates/proto_trading_cards.html`, `templates/trading_cards.html`, `templates/battle_cards.html`, `templates/card_shop.html` |
| Backend | `card_studio.py` (blueprint) · `card_studio_compose.py` · `card_stamp.py` · `battle_agent.py` (shared with Arena) |
| JS | `static/js/trading-cards.js`, `static/js/battle-cards.js` |
| Prompts/catalog | `HANDOFFS/cards_OFFICIAL_PROMPTS.md`, `HANDOFFS/cards_official_catalog.json` |
| Frame templates | Nick's frame art overlay, one per category; stats in fixed % boxes (see memory) |

### POST ▸ Percfect Posts  ← **KEEP as a live lane** (Nick, 2026-10-17)
| Piece | Path |
|---|---|
| Blueprint | `percfect_posts_bp.py` (routes `/percfectposts`, upload-media, site-profile, history, ai-keys, wand) |
| Studio logic | `percfect_posts_studio.py` · `static/js/percfect_posts.js` · `templates/percfect_posts.html` |
| Client app | `percfect-posts-app/` → carry **`src/`, `server.ts`, config only**; `node_modules` (227 MB) stays gitignored/rebuilt |

### Shared chrome / hub / wallet / auth  (carry verbatim)
| Piece | Path |
|---|---|
| Base chrome | `templates/base.html` (Studios ▾, credits pill, Library launcher, Vanessa FAB) |
| Six-section hub (image-as-page) | `app.py` `_layout_page_html()` + `static/layouts/percfect-site/{home,create,build,play,cards,reup}/` |
| Credits | `credit_wallet.py` (1 cr = 1 image · 6 cr = 1 s video) |
| Auth | login/register routes + Supabase `users` table |
| Stripe | buy-credits route + `/studios/battle-cards/buy-tickets` pattern; `HANDOFFS/2026-09-24_STRIPE_MONEY_SAFETY.md` |
| API blueprint | `percfect_api.py` (`api_bp`) if external API stays |

---

## 3. Supabase schema to recreate in the new project (`yncgfgmtuigguuphmcav`)

From `supabase_schema.sql`:
- **Tables:** `users`, `generations`, `promo_codes`, `promo_redemptions`, `api_keys`, `api_jobs`, `generation_jobs`
- **Functions:** `claim_studio_job()`, `studio_queue_ahead()`
- Recreate via a single migration in the new repo; verify RLS before go-live.

---

## 4. CUT — the fat (do NOT carry into the new repo)

| Item | On disk | Why cut |
|---|---|---|
| `percfect-posts-app/node_modules` | 227 MB | build artifact; gitignore + rebuild. **Posts lane itself KEPT** (Nick, 2026-10-17) |
| `perfect-comics-app/node_modules` | build artifact | gitignore it. The comics studio itself is **IN** (`perfect-comics-app/src`, `percfect_comics.py`, `static/comics`). |
| `discord_bot/`, `discord_bridge.py` | 30 MB | dead |
| `voice_agents/`, `telegram_voice_bot/` | 12 MB+ | dead |
| `perchance*`, `perchance_*.py`, princess templates | — | dead product (princessdownloads is old) |
| `kodi/`, `kodi-dist/` | 1.3 MB + | separate product; its own repo if kept |
| `prototypes/`, `shield/`, `percfectpictures2.0/`, `sdk/`, `perchance` | — | dead/experimental |
| `__pycache__/`, `.bak` files, `frontend_previews/` | — | junk |
| Card Studio / Battle Cards / Card Shop | — | **OPEN Q** — dictation drops Cards from Build; confirm whether Cards stays as its own top-nav or is cut |

---

## 5. Render keep-alive (anti-cold-start — "kick it every couple minutes")

App already exposes **`/ping`**. Options, cleanest first:
1. **cron-job.org** (free, 1-min interval) → GET the live `/ping`. Best for "couple minutes."
2. **GitHub Actions** scheduled workflow in the new repo (free, self-contained, but ~5-min min + drift).
3. **Render Starter tier ($7/mo)** — never sleeps, no pinging. The "just pay" option.
Plan: cron-job.org primary + a GH Actions fallback committed to the repo. Wire once Render URL exists.

---

## 6. Decided

1. Live site is https://percfectai.com on Render service `percfectai-v2` (`https://percfectai-v2.onrender.com`). The old host `percfectstudios.onrender.com` is not this repo.
2. GitHub repo is `Percfectai/v2`, not a repo under `nickpelectrical`.
3. Cards stays as its own top nav. Comics is also in, at `/comics`.
4. Posts stays as a live lane.
5. Render and Supabase keys stay out of chat and out of git.

---

## 7. Agent chain-of-command (proposed, to flesh out next)

One trained agent per lane, each with the right docs baked in:
- **Pictures agent** — xAI image-gen docs
- **Videos agent** — xAI video-gen docs (all models), refreshes periodically
- **Characters agent** — character flow + locked prompt (read-only on prompt)
- **Arena agent** — arena/fight + world-chat
- **3-D agent** — Tripo GLB/FBX, rig/retarget (also owns the private 3-D history MD)
- **Backend/Ops agent** — app.py, credits, keys, Supabase, Render, deploy
- Chain of command + lane rules ported from `AI_START_HERE.md` discipline.
