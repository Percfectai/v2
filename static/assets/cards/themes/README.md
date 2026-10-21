# Percfect Cards — theme templates

Each theme folder contains:

| File | Use |
|------|-----|
| `frame.svg` | Border / frame overlay (transparent center) |
| `bg.svg` | Background under the character |
| `theme.json` | Colors + labels (mirrors `CARD_THEMES` in app.py) |

## Themes

- **hero** — gold / black loading-screen
- **collector** — yellow / blue collector energy
- **classic** — white / red classic sports card
- **royal** — purple / gold
- **enchantress** — green / gold (seed line)
- **temptress** — red / gold (seed line)
- **mythic** — pink / cyan holo energy
- **neon** — cyan / magenta
- **dark** — silver / black
- **arena** — bronze / sand

## Wire-up

- UI: `/studios/trading-cards` theme chips → CSS `background-image` on `.theme-bg` + `.theme-frame`
- Export: `app.py` `_compose_trading_card_image` uses `CARD_THEMES` colors for PNG save
- Manifest: `manifest.json` lists all themes for tools / future pack seeds

Add a theme: copy a folder, edit SVG colors + `theme.json`, add entry to `CARD_THEMES` in `app.py`.
