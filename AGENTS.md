# Agents

Open files in this order. Do not skip ahead.

1. [README.md](README.md). That is the product, the live URL, and the lane map.
2. This file.
3. One lane from the README map. Read only the files for the lane you were asked to change.
4. [HANDOFFS/README.md](HANDOFFS/README.md) if the task is money, card prompts, or what was carried into this repo.

## What is true right now

- The original site is live again at https://percfectai.com.
- Render service is `percfectai-v2` (`https://percfectai-v2.onrender.com`). This repo deploys there.
- `percfectstudios.onrender.com` is the old service. Do not use it.
- The repo is the trimmed site. Dead products stay out.
- Build is https://percfectai.com/build. It is the V1 hub: Cards, Comics, Character. The file is `static/layouts/percfect-site/build-hub/index.html`. Do not add `/studios/build` as its own page. Do not put hub HTML in a folder named `build/` because git ignores that name.
- Comics is live at `/build/comics`. Do not ship the old Flask book generator in its place.
- Prompts stay as Nick left them. `CHARACTER_SPIN_PROMPT` in `app.py` is locked.
- Keys stay out of git and out of chat.

## Skills

Before GitHub issues, pull requests, Actions, or a deploy workflow, read the matching skill in `.grok/skills/` (Claude agents use `.claude/skills/`).

- `github` — `gh` for issues, pull requests, and workflow runs. Helper: `github/scripts/github_thread.py`
- `github-actions` — workflow files
- `github-actions-advanced` — harder pipeline cases
- `github-actions-debugger` — failed runs
- `github-actions-templates` — starter workflows
- `github-automation` — repo automation
- `github-issue-creator` — opening issues

Do not add a production deploy workflow unless Nick asks.
