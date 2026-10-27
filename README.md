# Percfectai/v2 — read this first

**Organization:** [Percfectai](https://github.com/Percfectai) · **Repo:** [Percfectai/v2](https://github.com/Percfectai/v2)
**Live site:** https://percfectai.com (Cloudflare → Render → gunicorn). `/ping` returns 200.
**Do not use** `percfectstudios.onrender.com` as this app. That host is the old service.

Every agent opens this file before editing. The lane list and the rules below are the current product, not the 17 October draft.

## Rules

- Perfected features stay the same code. Do not rewrite a working lane.
- Nobody edits prompts except Nick. `CHARACTER_SPIN_PROMPT` in `app.py` is locked.
- Image keys never run chat or voice. The comic writer uses `XAI_COMIC_WRITER_API_KEY` (then the other chat keys). Comic pictures use the image pool in `xai_keys.py`.
- Render API keys stay in Render and in `HANDOFFS/keys.txt`. Never print them in chat or commit them.

## Comics is in

Perfect Comics is a live lane in this repo as of 27 October 2026. It is the 25 September studio from `nickpelectrical/perfect-comics`, not the older Flask book generator.

| | |
|---|---|
| Page | `/comics` and `/studios/comics` |
| Code | `percfect_comics.py`, `perfect-comics-app/src/`, built files in `static/comics/` |
| Book | Cover + 9 pages. Settings, characters, summary, cover, beginning, middle, ending, review. |
| Price | Cover $2. Each 3-page act $6. Full comic $20. Every 5th finished comic is free. Credits are a local dollar balance in `localStorage` `perfect-comics-v1`. |
| Pictures | 3 per page. Free watermarked draft, then 2 edits after that block is unlocked. Model `grok-imagine-image-2.0`, 1K, medium. At most 3 reference images. |
| Stamp | Unpaid pages are saved as a JPEG with **PERCFECT PREVIEW** drawn into the pixels. The clean file stays in memory until unlock and is not written to `localStorage`. |
| Not built | Pro selling. The site does not take 10% yet. Publish opens the local reader. |

The public site returned 404 for `/comics` before this commit. After Render deploys this repo, https://percfectai.com/comics is the page.

## Lanes that stay

Photos, Videos, Characters (exact flow, locked spin prompt), Arena, 3-D, Posts, Cards (own top nav), Productions (parked, under construction), shared chrome, credits, auth, Stripe.

## Still out

Discord bots, Telegram and voice-agent trees, Perchance, princess page product, Kodi, prototypes, `percfectpictures2.0`, sdk, `.bak` files. Do not copy those back in from the old `percfectstudios` repo.

## Render

Service name in `render.yaml`: `percfect-studios-v2`. The site people use is https://percfectai.com. Old notes that say the only live host is `percfectstudios.onrender.com` are about the previous repo.

Full carry list: `HANDOFFS/REBUILD_CARRYOVER_MANIFEST.md`.
