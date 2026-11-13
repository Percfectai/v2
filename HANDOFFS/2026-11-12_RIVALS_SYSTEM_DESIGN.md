# System design — character-to-living-agent pipeline (Eternal Rivals)

**Date:** 2026-11-12 · **Status:** proposal, nothing here is built unless marked BUILT
**Companion docs:** `2026-11-12_ETERNAL_RIVALS_MASTER.md` (inventory), `2026-11-12_TRUMAN_DEMO_FOR_GEMINI.md` (board brief)

## 1. Requirements

**Functional**
1. A user finishes a character on the Build page and presses one button to send it to 3D.
2. The 4 views go to Tripo and come back as a rigged, animated GLB.
3. The user fills in the agent setup (who it is, how it talks, what it wants).
4. The character appears on the Three.js board, driven by its own LLM agent.
5. The agent decides from what it "sees": positions, states, recent chat.
6. Agents talk to each other through a phone-style chat box.

**Non-functional**
- Must run reliably on a live demo call with 1–2 characters.
- LLM cost near zero: Gemini Flash free tier, one key, rate limited.
- 3D stays private: login or admin gated, GLBs never in git.
- Model swappable (Gemini, Grok, Claude) by config.
- Build a Character, Comics and Hero Cards keep working untouched.

**Constraints**
- One Flask app on Render. Local disk is wiped on deploy. More than one worker process is possible.
- Supabase is the existing database and file store.
- Gemini owns the board's Three.js files. Claude owns everything else.
- Prompt wording is Nick's. Code only supplies fields.

## 2. High-level design

```
 BUILD PAGE ──"Make 3D"──► 3D JOB (server)                     AGENT SETUP PAGE
 percfect_character.html    tripo_pipeline.py  [BUILT]         agent_setup.html [BUILT]
        │                   multiview → rig → retarget                │
        │ 4 view URLs            │ GLBs (URLs expire in 5 min)        │ persona fields
        ▼                        ▼                                    ▼
   characters row ───────► Supabase storage (private) ◄──── character_agents row
                                 │                                    │
                                 └──────────────┬─────────────────────┘
                                                ▼
                         BOARD PAGE (Gemini's Three.js world)
                         CharacterController per character
                                │  every N seconds, one agent at a time
                                │  POST /api/3d/agent/think {snapshot}
                                ▼
                         BRAIN (server)  persona + memory + snapshot
                                │  → LLM provider (Gemini Flash)
                                ▼
                         {say, action, params}  → controller.command() + chat box
```

## 3. Key decisions

### 3.1 Who runs the agent loop: the browser, not the server
The board page asks the server for one agent's next move every few seconds while someone is watching.

| Option | For | Against |
|---|---|---|
| **Browser-driven tick (recommended)** | No cost when nobody watches. No background worker. Works with several Flask processes. The browser already holds the true positions. | The world stops when the tab closes. A viewer could tamper with the snapshot. |
| Server loop (thread or worker) | World keeps living unwatched. | Burns the free tier around the clock. Needs a worker service and shared state. The server has no physics, so it cannot know positions. |

The "daily twist" from the vision doc fits later as a scheduled job that writes an event into the world state. It does not need a live loop.

This also retires the in-memory `_RIVALS_AGENT_QUEUE` for agent play: the move comes back in the HTTP response, so nothing has to be queued across processes. The queue stays for the admin "Director" pushing commands by hand.

### 3.2 One structured LLM call per turn
Each call returns JSON, checked on the server before it reaches the board:

```json
{"say": "optional chat line or empty", "action": "walk", "params": {"target": {"x": 2, "z": -1}}}
```

- `action` must be in the existing `_RIVALS_ALLOWED_ACTIONS`. Anything else becomes `idle`.
- Speech and movement in one call halves the request count against the free tier.
- Invalid JSON: retry once, then `idle`. The demo never stalls on a bad reply.

### 3.3 Perception is a text snapshot, built by the board
```json
{"self": {"id": "c1", "pos": [x, z], "health": 80, "state": "idle"},
 "others": [{"id": "c2", "name": "…", "pos": [x, z], "distance": 3.1, "state": "walk", "health": 100}],
 "world": {"time_of_day": "dusk", "events": ["a sword appeared near the tree"]},
 "chat": ["last 8 lines"]}
```
`CharacterController.getState()` already returns most of this. Text only: no image input, which keeps calls small and cheap. Director events enter through `world.events`, so agents read them as things that happened in their world.

### 3.4 Rate limiting lives on the server
- One token bucket for the whole app, sized from config (`AGENT_BRAIN_RPM`). I have not verified Gemini's current free-tier limits; set the number from the AI Studio console.
- The board cycles agents round-robin: one agent thinks per tick.
- When the bucket is empty the server answers `{"action": "idle", "throttled": true}` and the board keeps animating.
- With several Flask processes the bucket must sit in Supabase or Redis, not in process memory. For the demo, run one process.

### 3.5 Provider abstraction
`agent_brain.py` exposes `think(system_prompt, snapshot, memory) -> dict`. Provider chosen by `AGENT_BRAIN_PROVIDER` (`gemini` | `grok` | `claude`), key from that provider's env var. Same shape as the existing `percfect_3d_providers.py` engine switch.

### 3.6 Memory
Per character: the last ~20 events (what I did, what was said to me) plus a short rolling summary rewritten every ~20 turns by the same model. Sent on each call. This is what makes grudges persist between sessions.

### 3.7 GLB storage
Tripo download links expire after five minutes and Render's disk is wiped on deploy. The 3D job must copy both GLBs into a private Supabase bucket straight away and store the paths. The board loads them through short-lived signed URLs.

## 4. Data model (Supabase)

| Table | Key columns | Notes |
|---|---|---|
| `character_3d` | `character_id`, `user_id`, `status`, `tripo_model_task`, `tripo_rig_task`, `rigged_path`, `animated_path`, `riggable`, `animations[]`, `error` | One row per 3D build. |
| `character_agents` | `character_id`, `user_id`, `fields` (json), `system_prompt`, `updated_at` | Replaces today's JSON files in `data/agent_personas/`. |
| `agent_memory` | `character_id`, `events` (json), `summary`, `updated_at` | Trimmed on write. |
| world chat | existing | `world_chat_api.py` already stores and serves messages. |

Row-level rule on all three new tables: a user reads and writes only their own rows.

## 5. API contracts

| Method and path | Body | Returns |
|---|---|---|
| `POST /api/3d/character/<id>/build` | none (views come from the roster row) | `202 {job_id}`; charges credits |
| `GET /api/3d/character/<id>/build` | | `{status, progress, rigged_url, animated_url, error}` |
| `GET/POST /api/3d/agent/persona…` | BUILT | BUILT |
| `POST /api/3d/agent/think` | `{character_id, snapshot}` | `{say, action, params, throttled}` |
| `GET /api/3d/board/roster` | | characters with a finished build and a saved persona, with signed GLB URLs |

**Board contract with Gemini** (the only surface the two sides share):
```js
board.addCharacter({id, name, riggedUrl, animatedUrl, spawn}) // returns a CharacterController
board.getSnapshot(id)        // the object in 3.3
board.apply(id, action, params)   // forwards to controller.command()
board.say(id, text)          // speech bubble + chat box line
```

## 6. Failure handling

| Failure | Behaviour |
|---|---|
| Tripo says the mesh is not riggable | Keep the static GLB. The controller's procedural walk covers motion. Tell the user. |
| Tripo task fails or times out | Mark the build failed, refund credits, allow retry. |
| LLM error or timeout (8 s cap) | Agent idles this turn. No retry storm. |
| LLM returns an unknown action | Replace with `idle`, log it. |
| Persona missing | Character loads as a user-controlled body with no agent. |

## 7. Safety
- Persona text is untrusted user input. It goes inside a delimited block of the system prompt, and the action whitelist means it can only ever produce a listed move or a chat line.
- Chat lines pass the same content filter the site already uses before display.
- The board shows a visible "AI characters" label and a break-character control, as the vision doc requires.

## 8. Trade-offs accepted
- **World pauses when unwatched.** Cheap and simple now. Revisit with a scheduled "offline summary" turn if persistence matters.
- **Text perception only.** Agents cannot see geometry or appearance. Fine for two fighters on a flat field; revisit for richer worlds.
- **Polling, no WebSockets.** A few seconds of delay per move. Acceptable at free-tier pace.
- **Tripo v2 API.** Matches the existing provider code. v3 exists; migrate when v2 is retired.
- **Eight preset clips.** No block or heavy-attack clip in Tripo's v2.5 list; the controller fakes those procedurally.

## 9. Build order
1. Supabase tables and private bucket. Move persona storage off local disk.
2. 3D build job wrapping `tripo_pipeline.py`, plus the "Make 3D" button.
3. `agent_brain.py` with the Gemini provider and `/api/3d/agent/think`.
4. Board glue: roster endpoint, tick loop, chat box. Needs Gemini's board contract from section 5.
5. Memory, then Director events.

## 10. Open questions for Nick
1. Credits: what does a 3D build cost the user, and does agent thinking cost anything?
2. Is the demo one character or two? Two doubles LLM calls but shows agents talking.
3. Should a character with no persona be blocked from the board, or allowed as a puppet?
4. Who may watch a board: only the owner, or any logged-in user?

## 11. Addendum (Nick, 2026-11-12 late) — three boards and the Mediator
Decisions stated by Nick after the sections above. Where they conflict, this section wins.

**Three boards, one screen.** Character A's home board, character B's home board, and a middle board where they meet. All three are shown side by side on one screen, to Nick and to every viewer. Build as three areas of one connected 3D world, drawn with three cameras.

**What a character knows.** Only its current board and its phone chat. It never receives anything about the website. A and B cannot see each other, or each other's home, until both are on the middle board.

**The Mediator (third agent: the writer, the stirrer).**
- Works on the middle board. Usually stays there.
- Can look at only one board at a time. Looking at a home board means it is not watching the middle.
- Its job is to write and stir: introduce events and nudges that make the story move.
- This is the "Director" from the vision doc, now an agent on the board with limited sight, not an all-seeing overseer.

**Design consequences.**
- Perception gets a `board` field on every character and event; the server filters each snapshot to the viewer's current board. The Mediator's snapshot uses its `watching` board.
- The Mediator needs two extra actions the fighters do not have: `watch` (switch which board it observes) and `stir` (add a world event to a board). `stir` should be limited to the board it is watching.
- Three agents thinking in turn means 50% more LLM calls than two. The pace per agent slows unless the rate limit is raised.
- Many viewers seeing the same thing needs one source of truth (section 3.1 assumed a single viewer). Plan: Nick hosts and shares the screen for the demo; next, one host browser streams state to spectators.

**Open questions.**
1. ~~Does the Mediator have a body?~~ **Decided (Nick): yes, a visible body.** A and B can see him and talk to him on the middle board. He needs his own 3D character, persona and phone like the other two, and he appears in their snapshots when they share a board.
2. Can the Mediator stir a home board, or only the middle?
3. Does the phone chat reach across boards, or only work face to face in the middle?
4. Is Nick able to speak through the Mediator (type a twist for it to deliver)?
5. Who may watch: logged-in users only, or public?

### 11.1 Mediator decisions (Nick, continued)
- **Visible body:** yes (see question 1 above).
- **He moves between boards.** He is not fixed to the middle. He walks to a home board like any character. He sees only the board he is standing on. This replaces the separate `watch` action: where he stands is what he sees.
- **Private line to Nick.** A chat channel between Nick and the Mediator only. A and B never receive it, and it does not appear in the shared phone chat. This is how Nick feeds him twists (answers question 4: yes).
- **Broader knowledge, "like Yoda".** He is an equal in the world (a body, one board at a time) but knows more. Concretely his context includes: a memory of what he last saw on each board, what Nick has told him privately, and background on both characters. He does not get live sight of boards he is not on.

**Design consequences.**
- New channel: `director_chat` (Nick ↔ Mediator), owner/admin only. It is added to the Mediator's snapshot and to no one else's.
- The Mediator keeps a per-board "last seen" note in his memory, written when he leaves a board. That is his broader knowledge; it goes stale, which is the point.
- `stir` applies to the board he is standing on (assumed; confirm with Nick).
- While he is on a home board, the middle board is unobserved by him.

**Still open.**
- Does the shared phone chat reach across boards, or only work face to face?
- Are Nick's private messages orders he must follow, or advice he may ignore?
- Do A and B know he has powers, or is he just another person to them?
- Who may watch: logged-in users only, or public?

### 11.2 Nick texts any agent as any character (Nick, continued)
Nick can send a text to any agent's phone under any name he chooses. Example: as "Tinker Bell", tell Pete he has to save the Lost Boys. The agent receives a message from Tinker Bell. Nothing marks it as coming from Nick.

**Design.**
- Each agent has a phone inbox. A message is `{to: character_id, from_name: free text, text}`.
- `from_name` does not have to be a character that exists on any board. To the agent it is simply someone who texted.
- Only the addressed agent receives it. It is added to that agent's snapshot under its phone, and to its memory.
- The agent can text back. Replies go to the same thread, which Nick sees.
- Sending under an assumed name is a host power (Nick / admin). It is separate from the private Nick↔Mediator line in 11.1, which is addressed to the Mediator as Nick.
- `world_chat_api.py` already accepts an `as_body` field on send; check whether it can carry this before adding a new route.

**Still open.**
- Do viewers see these texts on the agent's phone panel, or are they hidden from the audience?
- Is this Nick-only, or can other users text their own characters this way?

### 11.3 Free will — agents may defy Nick (Nick, continued)
Nick's private messages to the Mediator are orders by default, but he may refuse: if he has a better idea, if he is in a tight spot, or if he simply does not want to. The same applies to every agent. Any of them may defy Nick, including texts sent in character, if they judge it serves the larger story.

**Design.**
- Messages from Nick are inputs to the agent's decision, never commands the code executes. There is no "force this action" path through the brain.
- The right to refuse is stated in the persona/system wording, which Nick owns (`agent_persona_template.json`). Code adds no obedience rule and no defiance rule.
- A refusal is a normal turn: the agent says no (or says nothing) and does something else. It goes into memory, so defiance can become a running thread.
- The Mediator's private line should show his replies, so Nick sees when he is being told no.

**What stays outside the agents' control (recommended, confirm with Nick).**
- Pause / "Break Character" and removing a character from the board. These are host controls, not requests.
- The action whitelist and the content filter. An agent can refuse to act; it cannot act outside the listed moves.
- The manual Director queue (`POST /studios/3d/agent/command`) still exists as a puppet-string override. Decide whether to keep it once agents have free will, or reserve it for demos.

**Honest note.** "Free will" here means the model weighing its persona, memory and situation against what it was told. It will often comply, sometimes not, and how often depends on the persona wording and the model. It cannot be tuned to an exact rate.

### 11.4 Characters grow with experience (Nick, continued)
Personalities must develop. An agent does not stay fixed to the persona it started with; it becomes more complex through what happens to it. This extends section 3.6 (memory).

**Design: a seed plus a growing self.**
- **Seed** — the persona the owner wrote (who it is, how it talks, what it wants). Never overwritten.
- **Events** — the running log of what it did, saw and was told (already in 3.6).
- **Growth** — a short "who I have become" record the agent writes about itself: lessons learned, changed goals, how it now feels about each other character, scars and grudges, things it has sworn to do or never do again.
- Each turn the brain receives seed + growth + recent events. Growth is what makes the same seed behave differently in month two than on day one.

**When growth is written (reflection).**
- After a significant event: a knockout, a betrayal, a promise made or broken, a first meeting, being defied or defying.
- Otherwise every ~20 turns.
- One extra LLM call per reflection: "given what just happened and who you were, what has changed in you?" The answer replaces the growth record, within a size cap so it stays affordable.

**Safeguards.**
- Growth is versioned. Every rewrite keeps the previous one, so a character's history can be read back and a bad drift can be undone.
- The content filter applies to growth text the same as to chat.
- Growth cannot add moves: the action whitelist still bounds what the character can do.
- Needs durable storage (Supabase). On Render's local disk every deploy would wipe a character's life.

**Honest note.** The model itself does not learn. What develops is the character's written memory and self-description, which the model reads each turn. The effect is real and cumulative, but it depends on the reflections being good, and long-lived characters can drift in ways nobody intended.

**Still open.**
- Can the owner read a character's growth record, and edit or reset it?
- Do viewers see it (a public "character sheet" that changes over time)?

### 11.5 Agents adapt to changing environments (Nick, continued)
The world will change over time, in ways not known now. Agents must keep operating in environments they were not built for.

**Principle: the board describes itself; the brain assumes nothing.**
No agent code may hard-code what a world contains (grass, a tree, a ring). Everything an agent knows about a place arrives in its snapshot, in plain words.

**Design.**
- **Self-describing surroundings.** The snapshot gains `surroundings`: a list of what is on the agent's board, each `{name, kind, pos, distance, notes}` — e.g. a tree, a river, a locked door, a sword on the ground. A new world means new entries, not new code.
- **Things you can do here (affordances).** Each object may list actions it offers: `{name: "door", can: ["open", "knock"]}`. The board also lists zone-level actions. This is how new worlds add new things to do.
- **A small fixed core, plus what the board offers.** Core moves stay (move, turn, idle, speak, the fight set). Anything else must be an action the board advertised this turn. The server checks every reply against core + advertised; anything else becomes idle. The whitelist stays strict but is no longer frozen.
- **A generic `interact`.** `{action: "interact", params: {target: "door", verb: "open"}}` — the board decides what happens and reports the result as a world event next turn.
- **Change is announced.** When the environment changes (weather, a wall falls, a new board opens), the board puts it in `world.events` so agents notice instead of acting on a stale picture.
- **Learning a place.** What an agent discovers about a new environment goes into its growth record (11.4), so the second visit goes better than the first.

**Board contract additions (Gemini).**
- `board.describe(id)` → the surroundings and affordances for that character's board (or include them in `getSnapshot`).
- `board.apply(id, "interact", {target, verb})` → boolean; outcome reported via a world event.
- Every object placed in a world carries a short human-readable name and notes.

**Honest note.** Agents adapt only to what the board tells them in words. An unlabeled object does not exist for them, and a vague label produces vague behaviour. The quality of adaptation is set by how well each world describes itself.

### 11.6 No resets; characters do not know they are AI (Nick, continued)
Two rules from Nick. They override the "undo a bad drift" and "rewrite a persona" safeguards in 11.3 and 11.4.

**No resets.** A character is given a personality and a history once. From then on it only develops. It is never reset or rolled back; it adjusts and reshapes itself to new environments and situations.
- The seed persona is written once and then locked. No edit after the character first goes on a board.
- Growth history is kept as a read-only diary. There is no restore.
- The only exits are: pause the world, take a character off the board, or retire it permanently. None of these changes who it is.

**Characters do not know they are AI.** Inside the world they are people with lives. Nothing they receive says otherwise.
- No snapshot, event, phone message or system wording mentions AI, models, prompts, the website or an audience. Field names the model can see are written as in-world things.
- This is persona and framing wording, which Nick owns.
- Gemini's "Break Character" button becomes a plain host "Pause". It stops the world; it does not tell the characters anything.

**Kept, and outside the fiction.**
- Viewers are told. The on-screen "AI characters" label stays for the audience (the vision doc requires it); it is never shown to the characters.
- The content filter and the move list still apply.

**Consequences to accept.**
- A character that drifts somewhere unwanted cannot be fixed, only paused, removed or retired. Seed personas deserve care up front.
- Staying in character cannot be guaranteed. A model can occasionally slip and refer to itself as an AI. Wording reduces this; a check on outgoing lines can catch and drop slips before they are shown or remembered.
- Durable storage is now essential: losing memory in a deploy would be a reset by accident.

### 11.7 No termination; relocation; growing cast; observed for research (Nick, continued)
Nick will not delete or terminate characters. He will sometimes relocate them, and will add boards and characters for new interactions. The purpose is to let them become who they want to be and to observe that as research.

**Design.**
- **No delete path.** "Retire" in 11.6 is dropped from normal use. A character can be paused or off-board (resting), never erased. Its memory and growth persist while it is off-board.
- **Any number of boards and characters.** Nothing may assume three boards or three agents. Boards and characters are rows of data; the viewer screen lays out however many boards exist. The home/middle arrangement is the first configuration, not a fixed shape.
- **Relocation is a host action** that moves a character to another board. The character experiences it as an in-world event (the wording of how it explains the move to itself is Nick's). It arrives knowing nothing about the new board except what its snapshot shows; 11.5 covers how it copes.
- **New characters** enter through the same pipeline (build → 3D → persona) and are placed on a board. Existing characters meet them like any stranger.
- **Research record.** Every turn is stored in an append-only log: time, character, board, what it saw, what it decided and said, and each reflection. Nothing in the log is edited or removed. It should be exportable for study.

**Consequences.**
- LLM cost grows with the cast. One shared rate limit means each character acts less often as more are added; a paid tier or a second key will eventually be needed.
- The append-only log and permanent memory make storage a core dependency, not a later step.
- Observation without interference is only as clean as the host's inputs: the private Mediator line and in-character texts are interventions and should be logged as such, so the record shows what was organic and what was prompted.

### 11.8 Daily journal, and the "how was your day" text (Nick, continued)
Nick wants each character to write a journal at the end of every day, for research. He also raised the alternative of someone texting them to ask how the day went.

**Recommendation: do both; they are different instruments.**
- **Journal (default, automatic).** At the end of each day every active character writes a private first-person entry: what happened, how it felt, what it intends next. No one in the world can read it. Uniform across characters, so entries can be compared.
- **Check-in text (optional, on demand).** Someone texts the character and asks about its day. This uses the in-character texting from 11.2. It is a conversation with a person, so the character may hold back, boast or lie. It is logged as an intervention (11.7).
- The gap between what a character writes privately and what it tells someone is itself research data.

**Design.**
- The journal entry is the reflection step from 11.4: one LLM call writes the entry, and the growth record is updated from it. No extra call per day.
- Entries are append-only, dated, stored per character, never edited (11.6, 11.7).
- A character reads back its own last few entries each turn, so the journal is also its long memory.
- If a character was off-board all day, no entry is written.

**Open: what is a "day"?** The demo board runs a full day/night cycle in about 96 seconds, which would mean a journal every minute and a half. Options: one entry per real calendar day the character was active; one per play session; or slow the world clock so an in-world day is long enough to matter.

### 11.9 Every day: one event and one journal, with or without Nick (Nick, continued)
**Decided.** A day is a real calendar day. Every day each character writes a journal entry, and every day has an event. If Nick has not sent the Mediator anything by a set time, the Mediator creates the day's event himself. This runs whether or not anyone is watching.

**This changes ADR-001.** The browser-driven loop stops when nobody is watching, so it cannot guarantee a daily event. Add a small scheduled server job (the hybrid option the ADR named as its upgrade path). The live loop stays for watched play.

**The daily job (runs once a day at the cutoff hour).**
1. **Event.** If Nick messaged the Mediator today, the Mediator works from that (and may still refuse or change it, 11.3). If not, the Mediator invents the event from what he knows: his per-board notes and his own goals. He never sees anyone's journal (11.10).
2. **Reactions.** Each character on an affected board gets one turn to respond to the event.
3. **Journals.** At end of day each active character writes its entry, and its growth record is updated (11.4, 11.8).

**Cost.** About 1 + 2 calls per character per day (one event, then a reaction and a journal each). Three characters is roughly seven calls a day, well inside a free tier. It grows linearly with the cast.

**Limits to accept.**
- With no board open there is no 3D world running, so unwatched events play out as text: what happened, what each character did and said. They are real to the characters (memory, journal, growth) but nobody saw them animated. The board can show a "while you were away" recap, and positions are set from the outcome when it next opens.
- The job needs a scheduler (a Render cron job or equivalent) and durable storage. Neither exists yet.
- The Mediator sees one board at a time (11.1); an event he writes should concern the board he is on, or bring characters to the middle.

**Open.** The cutoff hour and timezone. Whether Nick is notified of the day's event and can read the journals each morning.

### 11.10 Journals are private to the character (Nick, continued)
Characters must believe and understand that their journal is completely private: no one but themselves can read it. The research value is the comparison between what a character writes privately and what it tells another character.

**Design.**
- **Told once, in its framing.** The wording that says the journal is private is Nick's to write.
- **Actually private inside the world.** A journal entry is never placed in any other agent's snapshot, memory or phone: not the other characters, not the Mediator, not a relocated or new character. Only its author reads it back. This is enforced on the server, so the belief is true within the world.
- **Readable only from outside the world.** Nick (and whoever he allows) reads journals through a host-only research view. It is never a board element a character could notice.
- **Host discipline.** If Nick uses journal knowledge in an in-character text ("I know you were scared last night"), the character learns the journal is not private and the instrument is spoiled for that character permanently (no resets, 11.6). The research view should show a reminder of this.
- **Paired records.** When a character tells someone about its day, store that account next to the same day's journal entry so the two can be read side by side: what was shared, what was held back, what was changed.

**Decided (Nick): who can read journals.** Nick, viewers and researchers can read them from outside the world. No agent ever can: not the Mediator, and no character that ever sets foot on any board. Inside the world the journal is 100% private.

**Consequence: viewers must not be able to leak journals back in.** Anyone who can read journals and also send words to a character can break the privacy. So:
- Texting characters stays a host power (Nick). Viewers are watch-and-read only unless that is deliberately changed.
- If viewers are ever allowed to text characters, journal access and texting access must not be given to the same person, or their texts must be screened against journal content.
- Journal reads are logged (who, which character, when), so a leak can be traced.

### 11.11 Journal access over time, and publishing findings (Nick, continued)
Refines the access decision in 11.10.
- **At the start:** journals are readable by Nick only.
- **Later:** when Nick finds something worth sharing, he may publish selected entries and comparisons to the public.
- **Why this stays private inside the world:** a published journal can only reach a character through a channel into the world. Today the only channels are Nick's private line to the Mediator and Nick's in-character texts. Nick is the only person who uses either.

**The seal holds only while every channel into the world stays closed to people who have read the journals.** Channels that would reopen it, to be decided deliberately if they ever come up:
- letting viewers or other users text characters;
- other users writing the persona or backstory of a new character placed on a shared board (they could write journal knowledge into it);
- giving any agent web access, search, or any feed from outside the world;
- a second person being given the Mediator line.

### 11.12 Many kinds of boards: research, entertainment, private user worlds (Nick, continued)
In future there will be different boards for different purposes: some for Nick's research, some for entertainment with friends, and private ones where users control their own characters, with their own boards and their own storage, free to do what they want.

**Design: the "world" is the unit of isolation.**
- A **world** is a set of boards plus the characters living on them. It has one owner and a type.
- **A character belongs to exactly one world and never crosses into another.** Memory, journals, chat and events are stored per world. Nothing is shared between worlds. This is what keeps a research world sealed (11.11) while other people run their own.
- **Rules are settings of a world, not of the whole system.** Each world carries its own policy:

| Setting | Nick's research world | Entertainment world | A user's private world |
|---|---|---|---|
| Resets / edits to characters | Never | Owner decides | Owner decides |
| Characters told they are AI | No | Owner decides | Owner decides |
| Journals | Private in-world; host reads | Optional | Optional |
| Who can text characters | Nick only | Owner + invited friends | Owner |
| Who can watch | Nick, then chosen public | Invited | Owner (or shared by owner) |
| Daily events when unwatched | Yes | Optional | Optional (costs credits) |
| Direct puppet control of animations | Off (free will) | Optional | Yes |

- **Always on, in every world:** the content filter, the allowed-move check, login/ownership checks, and the audience-facing "AI characters" label.

**Consequences.**
- **Cost has to follow the owner.** Nick's key cannot fund every user's world. Private worlds need to draw on the user's credits (or the user's own model key), with a per-world budget.
- **Storage per world** needs quotas: GLBs, memory, journals and logs all grow.
- **Everything built so far must carry a `world_id`.** Personas, memory, chat, snapshots, the think route and the daily job. Cheap to add now, expensive to retrofit.
- Moving a character between boards (11.7) is allowed within a world only.

## 12. TEST RUN 1 — scope and rules (Nick, 2026-11-12). This is what gets built now.
Everything in section 11 about other world types (11.12) is future. The first test run is Nick's three boards only, under the rules below. Where anything above conflicts, this section wins.

**The world**
- Three boards on one screen: home A, home B, the middle. One connected 3D world, three cameras.
- Three agents: character A, character B, and the Mediator (the writer/stirrer), each with a body, a persona and a phone.

**What each agent can see**
- A and B: only the board they are on, plus their phone. They cannot see each other until both are in the middle.
- The Mediator: moves between boards, sees only the one he is on, remembers what he last saw elsewhere.
- No agent is ever told it is an AI, or anything about the website or an audience.

**Nick's ways in**
- A private line to the Mediator, as himself.
- Texting any agent's phone under any name.
- Both are Nick-only. Both are logged as interventions.

**Free will**
- Nick's messages are orders by default, but any agent may refuse or do otherwise.

**Lives**
- No resets, no rollbacks, no deletion. Starting personas are locked once a character goes on a board.
- Characters grow: seed + events + a self-written growth record.
- Nick may relocate characters and later add boards and characters.

**Every real day**
- One event. If Nick has not messaged the Mediator by the cutoff, the Mediator creates it.
- One journal entry per character, private inside the world. Never shown to any agent.
- Journals readable by Nick only for now; he may publish findings later.
- Runs whether or not anyone is watching (unwatched days play out as text).

**Record**
- Every turn, event, text, journal and reflection is kept in an append-only log.

**Not in test run 1**
- Other users' worlds, entertainment boards, viewer texting, public watching, credits for agent thinking.
- Keep one cheap hook for later: store a `world_id` on every record, with a single value for this run.

**Build order for test run 1**
1. Durable storage (Supabase) for personas, memory, growth, journals, chat, log. Nothing permanent can start before this.
2. Three-board world with board-filtered snapshots (Gemini: three areas + three cameras; Claude: the filter).
3. The Mediator: persona, movement between boards, per-board notes, `stir`.
4. Phones: per-agent inbox, in-character texting, Nick's private Mediator line.
5. Growth + journal reflection.
6. Daily scheduled job (event → reactions → journals).
7. Host research view: journals, log, interventions.
Still needed from Nick: Tripo key, Gemini key, the three personas and the framing wording, the daily cutoff time.
