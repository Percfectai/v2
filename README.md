# Percfectai/v2

The original Percfect site, trimmed and live again.

| | |
|---|---|
| Site | https://percfectai.com and https://www.percfectai.com |
| Render | `percfectai-v2` at https://percfectai-v2.onrender.com |
| Repo | https://github.com/Percfectai/v2 |
| Old host | `percfectstudios.onrender.com` is the previous service. Do not deploy this repo there. |

`/ping` returns 200. Comics is live at `/build/comics`. Do not bring back the old Flask book generator.

## Read this first

1. This file.
2. [AGENTS.md](AGENTS.md) if you are an agent.
3. The one lane doc that matches the work, from the map below.
4. [HANDOFFS/README.md](HANDOFFS/README.md) only when you need the carry list, card prompts, or Stripe notes.

Do not start from the old `percfectstudios` tree. Do not copy Discord, voice bots, Perchance, the princess product, Kodi, prototypes, or `.bak` files back in.

## Rules

- Keep a working lane as it is. Do not rewrite it.
- Nick is the only person who edits prompts. `CHARACTER_SPIN_PROMPT` in `app.py` stays locked.
- Image keys never run chat or voice.
- Keys stay in the local V2 keys file and in Render. Never commit them and never paste them into chat.

## How to write a hub

The Build page is the pattern. It is the V1 hub, copied forward.

- The public address is `/build`. `/studios/build` only redirects there. Do not make a second Studios Build page.
- The page file is `static/layouts/percfect-site/build-hub/index.html`. A folder named `build/` is gitignored, so do not put the page in a directory named `build`.
- The route in `app.py` is `build_hub_page()`, and it loads that file through `_layout_page_html("build-hub")`.
- Three doors, in this order: **Cards** (`/studios/trading-cards`), **Comics** (`/build/comics`), **Character** (`/studios/percfectcharacter`). The pictures are `card.jpg`, `comic.jpg`, and `character.jpg` next to that HTML.

Write the next hub the same way: one HTML file, the real pictures, short names, and a route that is not under `/studios` unless the product page itself already lives there.

## Map

| Lane | Start here |
|---|---|
| Photos and videos | `templates/percfectstudios.html`, `static/js/studio_jobs.js`, `studio_task_handlers.py` |
| Characters | `templates/percfect_character.html`, `static/js/character_profile.js`, `CHARACTER_SPIN_PROMPT` in `app.py` |
| Arena | `templates/proto_arena_stage.html`, `battle_agent.py`, `world_chat_api.py` |
| 3-D | `percfect_3d_providers.py`, `percfect_api_3d.py`, `three_d_character_gen.py` |
| Cards | `templates/proto_trading_cards.html`, `card_studio.py`, `HANDOFFS/cards_OFFICIAL_PROMPTS.md` |
| Posts | `percfect_posts_bp.py`, `templates/percfect_posts.html`, `percfect-posts-app/src/` |
| Productions | `percfect_productions_bp.py` — parked, under construction |
| Credits, auth, Stripe | `credit_wallet.py`, `HANDOFFS/2026-09-24_STRIPE_MONEY_SAFETY.md` |
| Comics (coming) | `percfect_comics.py`, `perfect-comics-app/src/studio.tsx` — not live on the site yet |
| GitHub and Actions | `.grok/skills/` and `.claude/skills/` — read the matching `SKILL.md` before `gh` or a workflow |

## Skills

The same GitHub skill folders are in `.grok/skills/` and `.claude/skills/`: `github`, `github-actions`, `github-actions-advanced`, `github-actions-debugger`, `github-actions-templates`, `github-automation`, `github-issue-creator`.
