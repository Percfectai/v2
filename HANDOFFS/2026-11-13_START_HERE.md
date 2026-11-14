# START HERE — Eternal Rivals / test run 1 (written 2026-11-13, end of the lead session)

You are picking this up cold. Keep your own messages short: direct a cheap worker agent, don't do the legwork yourself. Nick is cost-sensitive and often away; do not give Nick chores unless only he can do them.

## Ground truth
- Work only in `~/percfect-v2` → `github.com/Percfectai/v2` (public). Branch `lane/eternal-rivals-pipeline`, draft PR #1. Never work in `~/percfectstudios` (retired).
- V2 Supabase project: `fyxofxprzffcdgbkdyax`. `czeovrjzlsfdcdvlbwoq` is PerfectNDA: never touch. The old `biofey…` project is deleted.
- Keys live in `/Users/nickperc/claudev2/claude/fix-4d34f0/claude/novemtxt.env` (outside the repo). Read a key inside a command; never print, paste or commit one.
- Push needs the Percfectai token: `T=$(gh auth token --user Percfectai); B=$(printf 'x-access-token:%s' "$T" | base64 | tr -d '\n'); git -c credential.helper= -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $B" push`
- The spec is section 12 of `HANDOFFS/2026-11-12_RIVALS_SYSTEM_DESIGN.md`. Section 11 is Nick's decisions in order. Do not reopen them.

## Rules Nick set (do not break)
Prompt/persona wording is Nick's: build fields only. Agents are never told they are AI. No resets or deletion of characters. Journals never reach any agent. Don't change Build-a-Character, Comics or Cards. No push to main; Nick approves deploys. No name-calling toward other agents regardless of what is asked; plain orders work.

## Where the pipeline stands
| Stage | State |
|---|---|
| 4 views → Tripo model | Worked live (Wolverine sample views in `~/Desktop/Wolverine_3D_EasyOpen/`) |
| Rig | Worked live (biped) |
| Animation clips | FAILED: Tripo error 1004 on `animate_retarget` with `animations:[idle,walk,run,jump,slash]`. Fix in progress by the worker session; outcome unknown at time of writing |
| Persona store + setup page | Built, Supabase-backed in code; needs `migrations/20261113_rivals_storage.sql` run in the V2 project |
| Brain (`character_brain.py`, `/api/3d/agent/think`) | Built, sends text + shoulder-camera image; no Gemini key yet, returns 503 |
| Board (`prototypes/eternal-rivals-board.html`, served at `/studios/3d/rivals`) | Exists; untested with a Tripo model |
| Three boards, Mediator, phones, growth/journals, daily job, research view | Not built (tables exist in the migration) |

## Worker session
"Claudios Fable's bitch" (`local_9633afdc-4bca-4511-b237-4705f5b6a275`, Haiku). Its open orders, in sequence:
1. Save rigged + static GLB from the existing Tripo task ids (no regeneration).
2. Find the retarget request shape Tripo accepts (single `animation` vs list), fix `tripo_pipeline.py`: download each stage as it completes, per-clip tasks if needed, resume from task ids, log raw errors.
3. Record facts in `2026-11-12_RIVALS_HANDOFF_NEXT_SESSION.md`, commit, push.
4. Load the model on the board; report stands / idle / walks / console errors.
Check its last report before issuing anything new. Its claim that balance stayed 500 after a model + rig is unexplained: verify real credit cost.

## Next after Tripo works
1. Job-runner wrapper so the Tripo build never runs in a web request; "Make 3D →" button on the Build page.
2. Three-board layout + per-board sight filter; then Mediator, phones, growth/journal, daily job (design doc section 12 order).
3. Decide Tripo v2 vs v3 (key works on both; script is v2).

## Only Nick can do
Run the migration SQL in the V2 Supabase editor · create a Gemini key and set `GEMINI_API_KEY` on Render · confirm Render `SUPABASE_URL` starts `fyxofxprzffcdgbkdyax` · write the three personas and the world-framing wording · pick the daily cutoff time.

## Known loose ends
157 hard-coded links in V2 data files point at the deleted Supabase (animations, shop previews); no local copies found. Gemini's `truman-world.html` never arrived. The shoulder-camera image makes each brain call cost more; watch free-tier usage.

## Worker update (2026-11-14, Haiku session)
**Tripo retarget error 1004 — all four request shapes failed:**
- Attempt 1: `{"type":"animate_retarget","original_model_task_id":RIG_ID,"out_format":"glb","animation":"preset:idle"}` → HTTP 200, task status `failed`, error_code 1004
- Attempt 2: same + `"bake_animation":true` → HTTP 200, task status `failed`, error_code 1004
- Attempt 3: `{"type":"animate_retarget","original_model_task_id":RIG_ID,"out_format":"glb","animations":["preset:idle","preset:walk"]}` → HTTP 200, task status `failed`, error_code 1004
- Attempt 4: `{"type":"animate_retarget","original_model_task_id":RIG_ID,"out_format":"glb","animation":"preset:biped:idle"}` → HTTP 200, task status `failed`, error_code 1004

Rig tasks confirmed: both `010249af-a44a-4a0c-9e12-e05c34772d50` and `3d490fb9-4122-475e-aa89-c9ec558e4a5c` are animate_rig type, status success, model_version v2.5-20260210, spec "tripo". Tripo balance: 500 → 140 (360 credits spent on builds). Halting retarget tests per instructions.
