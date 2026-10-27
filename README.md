# Percfectai/v2 — read this first

**Organization:** [Percfectai](https://github.com/Percfectai) · **Repo:** [Percfectai/v2](https://github.com/Percfectai/v2)

The original site is live again: **https://percfectai.com** and **https://www.percfectai.com**. Render service is `percfectai-v2` (`https://percfectai-v2.onrender.com`), deploys from this repo. `/ping` returns 200. This repo is that site, with the fat trimmed. Dead products are not in here. Do not copy them back from the old `percfectstudios` tree.

A comic page is coming. It is not a live lane on the site yet. Do not treat `/comics` as shipped, and do not rebuild the old Flask book generator.

Every agent opens this file before editing. The lane list below is the current product, not the 17 October draft.

## Rules

- Perfected features stay the same code. Do not rewrite a working lane.
- Nobody edits prompts except Nick. `CHARACTER_SPIN_PROMPT` in `app.py` is locked.
- Image keys never run chat or voice. The comic writer uses `XAI_COMIC_WRITER_API_KEY` (then the other chat keys). Comic pictures use the image pool in `xai_keys.py`.
- Render API keys stay in Render and in `HANDOFFS/keys.txt`. Never print them in chat or commit them.

## Comic page — coming

A comic page is coming. The studio to use, when it is wired onto the live site, is the 25 September one from `nickpelectrical/perfect-comics`, not the older Flask book generator. Code for that studio is in this repo and is not the public page yet.

| | |
|---|---|
| Page | `/comics` and `/studios/comics` |
| Code | `percfect_comics.py`, `perfect-comics-app/src/`, built files in `static/comics/` |
| Book | Cover + 9 pages. Settings, characters, summary, cover, beginning, middle, ending, review. |
| Price | Cover $2. Each 3-page act $6. Full comic $20. Every 5th finished comic is free. Credits are a local dollar balance in `localStorage` `perfect-comics-v1`. |
| Pictures | 3 per page. Free watermarked draft, then 2 edits after that block is unlocked. Model `grok-imagine-image-2.0`, 1K, medium. At most 3 reference images. |
| Stamp | Unpaid pages are saved as a JPEG with **PERCFECT PREVIEW** drawn into the pixels. The clean file stays in memory until unlock and is not written to `localStorage`. |
| Not built | Pro selling. The site does not take 10% yet. Publish opens the local reader. |

## Lanes that stay

Photos, Videos, Characters (exact flow, locked spin prompt), Arena, 3-D, Posts, Cards (own top nav), Productions (parked, under construction), shared chrome, credits, auth, Stripe.

## Trimmed out

Discord bots, Telegram and voice-agent trees, Perchance, the princess page product, Kodi, prototypes, `percfectpictures2.0`, sdk, and `.bak` files. They are not part of this repo. Leave them out.

## Render

The live site is https://percfectai.com on Render service `percfectai-v2` (`https://percfectai-v2.onrender.com`). `percfectstudios.onrender.com` is the previous service. Do not deploy this repo there. The Render API key stays in the local V2 keys file and in Render. Never commit it and never paste it into chat.

Full carry list: `HANDOFFS/REBUILD_CARRYOVER_MANIFEST.md`.

GitHub and Actions skills for every agent are in `.grok/skills/` and `.claude/skills/` (`github`, `github-actions`, `github-actions-advanced`, `github-actions-debugger`, `github-actions-templates`, `github-automation`, `github-issue-creator`). Read the skill before using `gh` or adding a workflow.
