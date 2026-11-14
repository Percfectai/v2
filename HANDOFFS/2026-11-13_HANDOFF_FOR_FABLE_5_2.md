# Handoff for a new Fable 5.2 session (written 2026-11-13, evening)

Read this file, then `HANDOFFS/2026-11-13_START_HERE.md`. Work only in `~/percfect-v2`.

## Rules from Nick
- Cost matters a lot. Keep replies short. Don't re-read big files; grep instead.
- Nick is often at work and on his phone. Give him one clear next step, not a menu.
- Nick decides spending. Ask before any paid Tripo or Gemini call.
- Never print, paste or commit API keys. Keys live in `/Users/nickperc/claudev2/claude/fix-4d34f0/claude/novemtxt.env`.
- The repo is public. Keep keys and `.glb` files out of git.
- Prompt and persona wording is Nick's. Don't reword it.

## Where things are
- Branch `lane/eternal-rivals-pipeline`, draft PR #1 on `Percfectai/v2`.
- Supabase project for V2: `fyxofxprzffcdgbkdyax`. Don't touch `czeovrjzlsfdcdvlbwoq` (PerfectNDA).
- Tripo balance: 115 credits (as of this evening). Nick paid $13 subscription + $5 top-up.

## State of the pipeline
- Tripo model from 4 views: worked.
- Rig: worked. Rigged files in `assets_3d/characters/*_rigged.glb` (7 files, ~12 MB each, not in git).
- Animation clips (idle, walk, run, jump, slash): FAILED with Tripo error 1004 on `animate_retarget`. Not fixed yet.
- Board page (`prototypes/eternal-rivals-board.html`): not yet tested with a Tripo model.
- Agent brain: built; no working Gemini key confirmed yet.
- Storage tables: in `migrations/20261113_rivals_storage.sql`; Nick must run it in the V2 Supabase SQL editor.

## Open items, in order
1. Find the rig task id for one `_rigged.glb` (worker session "Claudios Fable's bitch", id local_9633afdc-4bca-4511-b237-4705f5b6a275, failed, may hold it).
2. One paid Tripo test: idle clip only, after Nick says yes. Then check the file on the board.
3. Dry run (free): board loads rigged files; persona and brain routes respond.
4. Nick's list of eight pre-product items: not found in the files; ask Nick for it.

## Not yet confirmed
- The Gemini key Nick says he has (not in the keys file in a usable form).
- Whether the worker's last animation fix changed `tripo_pipeline.py` (it is modified and uncommitted).
