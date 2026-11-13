# HANDOFF — Eternal Rivals / Truman Show, test run 1

> ## CORRECTION (2026-11-13) — read before anything below
> - **This repo (`~/percfect-v2` → `github.com/Percfectai/v2`) is the working repo.** `~/percfectstudios` (→ `nickpelectrical/percfectstudios`) is retired. The pipeline was first built there by mistake and copied forward here on branch `lane/eternal-rivals-pipeline`. Copy-forward only: never delete from the old repo.
> - **V2's Supabase project is `fyxofxprzffcdgbkdyax`.** The `biofeygmxomcpaxqkgfe` project named below no longer exists. `czeovrjzlsfdcdvlbwoq` is PerfectNDA: do not touch it for this work.
> - **V2 still hard-codes 157 storage links to the dead project** (145 `arena-anims`, 12 `previews`) in `static/motion-lab/animated/manifest_*.json`, `agent_field_config.json` (two copies) and `premade_shop.json`. Those assets will not load until re-uploaded to the V2 project and re-pointed.
> - Where the text below says `lane/character-angles-fix`, "uncommitted", or the `bio…` project, this banner wins.
> - Tripo: Nick's key is valid on v2 and v3 APIs. Nick has since said the API wallet is funded; retest the balance before a build.


**Written:** 2026-11-12 late · **For:** the next AI session picking this up
**Branch right now:** `lane/character-angles-fix` (unrelated lane; nothing below is committed)

## Read in this order
1. `HANDOFFS/2026-11-12_RIVALS_SYSTEM_DESIGN.md` — **section 12 is the spec for what gets built now** (test run 1). Section 11 is Nick's decisions in the order he made them. Sections 1–10 are the earlier proposal; section 12 wins on any conflict.
2. `HANDOFFS/2026-11-12_ETERNAL_RIVALS_MASTER.md` — where everything lives on this Mac, and the existing rivals system in the repo.
3. `HANDOFFS/2026-11-12_TRUMAN_DEMO_FOR_GEMINI.md` — Gemini's brief (the Three.js board only).

## Who does what
- **Gemini:** only the Three.js board. **Claude:** the website, pipeline, brains, chat, storage.
- More than one Claude session has been writing in this folder. **Check `list_sessions` before editing** and keep one writer per file. A collision nearly erased work once today.

## Test run 1 in one paragraph
Three boards on one screen (home A, home B, the middle). Three agents: A, B, and the Mediator/Director, who has a body, walks between boards and sees only the one he is on. Agents are never told they are AI. They have free will and may defy Nick. No resets, no deletion, personas lock once on a board. They grow from experience. Every real day: one event (the Mediator invents it if Nick is silent by a cutoff) and one private journal per character. Nick alone has a private line to the Mediator and can text any agent under any name. No agent ever sees a journal. Everything is logged, append-only.

## What exists (all uncommitted, none run with a real key)
| File | What it is | State |
|---|---|---|
| `tripo_pipeline.py` | 4 views → Tripo model → rig → animate → GLBs | Compiles; guards tested offline; **never called Tripo** |
| `character_agents.py` | Persona store + setup page + `/api/3d/agent/think` + `brain-status` | Tested with Flask test client, 13/13 |
| `character_brain.py` | Gemini Flash brain, action whitelist, throttle | Written by another session; **not reviewed line by line** |
| `templates/agent_setup.html` | Setup form with character picker | Tested via test client only |
| `static/data/agent_persona_template.json` | Form labels + prompt frame | **Gitignored by `data/` → needs `git add -f`.** Wording is a draft; Nick owns it |
| `static/js/rivals/board_agent_loop.js` | Roster loader, paced think loop, chat listener | 8/8 against a stub board; another session edited it afterwards — re-read before use |
| `app.py` | ~10-line hook registering `character_agents` | Compiles |

Already in the repo before today: `static/js/rivals/character_controller.js` (+ drivers, combat), `world_group_chat.js`, `world_chat_api.py`, admin routes `/studios/3d/rivals`, `/studios/3d/field`, `POST /studios/3d/agent/command`.

## Not built (test run 1 build order — design doc section 12)
1. **Durable storage in Supabase** — personas, memory, growth, journals, chat, append-only log. Was in progress when this was written; nothing drafted yet.
2. Three-board world + per-board filtered snapshots.
3. The Mediator (movement, per-board notes, `stir`).
4. Phones: per-agent inbox, in-character texting, Nick's private Mediator line.
5. Growth + journal reflection.
6. Daily scheduled job (event → reactions → journals).
7. Host research view.
Also open: job-runner wrapper for `tripo_pipeline.build_animated_character` (it blocks for minutes; must not run in a web request), and the "Make 3D →" button on the Build page.

## Known problems and traps
- **Supabase MCP is connected to the wrong project.** It only shows `perfectnda` (`czeovrjzlsfdcdvlbwoq`). The site's project is a different one (ref `biofeygmxomcpaxqkgfe` appears in `agent_field_config.json`). **Do not apply anything to `perfectnda`.** Migrations here are plain SQL files in `migrations/` that Nick runs in the Supabase SQL editor (see `migrations/20261003_email_list.sql` for the style).
- **Render disk is wiped on deploy.** Personas currently save to `data/agent_personas/` on disk. With "no resets", a deploy would erase a character's life. Storage must move to Supabase before any character starts living.
- **Nothing carries a `world_id` yet.** Add one to every new table (single value for this run) so other world types can come later.
- **Gemini's patched board file is not in the repo.** Only its summary was pasted. It may look for `window.CharacterController`; the real controller is an ES module and sets no global, so the page could silently fall back to its own controller. Verify when the file arrives.
- **Tripo script refuses all images** unless `SITE_URL`, `PUBLIC_BASE_URL`, `SUPABASE_URL` or `TRIPO_ALLOWED_IMAGE_HOSTS` is set.
- **The deploy lock** in `HANDOFFS/ACTIVE_AGENTS.md` still shows LOCKED from 2026-09-21.

## Rules that must not be broken
- 3D is private: repo private, `*.glb` and `assets_3d/` gitignored, 3D routes login/admin gated.
- Prompt and persona wording is Nick's. Build fields, never write or reword the text.
- Don't change Build-a-Character, Comics or Hero Cards behaviour.
- Branch + PR; never push this work to main; Nick approves deploys.
- Keys in env only. Never print or commit them.
- Journals never go into any agent's snapshot, memory or phone.

## Waiting on Nick
- Tripo API key; Gemini (Google AI Studio) key.
- The three starting personas and the world-framing wording (permanent once used).
- The daily cutoff time for the Mediator's event.
- Open questions listed in design doc sections 10 and 11 (credits, phone reach across boards, whether A and B know the Mediator has powers, keeping the puppet override).

## STATUS UPDATE — 2026-11-13 (latest; wins over everything above)
**Where things are**
- Working repo: `~/percfect-v2` → `github.com/Percfectai/v2` (PUBLIC by Nick's decision, 2026-11-13). Branch `lane/eternal-rivals-pipeline` holds all pipeline work.
- Old repo renamed `nickpelectrical/old-version-1`: private, archived, reference only. The old local folder `~/percfectstudios` still exists; do not work there.
- Supabase for V2: project `fyxofxprzffcdgbkdyax`. Old `biofeygmxomcpaxqkgfe` is deleted. `czeovrjzlsfdcdvlbwoq` is PerfectNDA (hands off). The Supabase MCP connector in Claude is signed in to the PerfectNDA account, so V2 table changes go through a SQL file in `migrations/` that Nick runs, unless the connector is re-signed-in.
- Confirm on Render: V2 service `percfect-studios-v2` has `SUPABASE_URL` beginning `fyxofxprzffcdgbkdyax`.

**Honest state of the build: nothing in test run 1 works end to end yet.**
Built and unit-tested offline only: Tripo script, persona store + setup page, brain route, board loop, POV helper. Never run with live keys. Not built: storage tables, three-board world, Mediator, phones, journals/growth, daily job, research view, job-runner wrapper for Tripo, "Make 3D" button.

**Blockers, in order**
1. **Tripo API wallet is 0.** Key is valid (v2 and v3 APIs) but a test task returned error 2010 "not enough credit". Nick has 3,000 credits somewhere, probably on a different Tripo account or in the app wallet. Fix: create the key from the account whose developer console shows the credits. Free check: `GET https://openapi.tripo3d.ai/v3/account/balance`.
2. **No Gemini key yet.** Brain returns 503 "disabled" until `GEMINI_API_KEY` is set.
3. **Storage.** Personas save to local disk (`data/agent_personas/`), wiped on every Render deploy. Must move to Supabase before any character starts living (no-reset rule).
4. **Gemini's patched board file is not in the repo.** Only its summary exists. Needs a path and a route; verify it imports `/static/js/rivals/character_controller.js` (it is an ES module, there is no `window.CharacterController`).
5. **157 dead storage links** in V2 data files point at the deleted Supabase (145 `arena-anims`, 12 `previews`). No local copies of those files were found.

**Next steps for whoever picks this up**
1. Write `migrations/2026xxxx_rivals_storage.sql` for V2: personas, memory, growth, journals, phone messages, append-only turn log; every table with `world_id`, `character_id`, `user_id`. Journals must never be readable by an agent path.
2. Switch `character_agents.py` storage from disk to those tables.
3. Decide Tripo v2 vs v3 (key works on both; v3 is current, script is written for v2).
4. Then section 12 build order in `2026-11-12_RIVALS_SYSTEM_DESIGN.md`.

**Secrets**
- Nick keeps keys in a local file outside this repo. Read keys from it inside a command; never print, paste or commit them. This repo is public.
