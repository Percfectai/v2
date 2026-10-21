"""Stamp Nick finished fronts: name · N## · 4 stats · logo BR.

Admin types ONLY: character name, card number, four stats.
Base art: static/assets/cards/bases/{id}_base.webp (art only — no text).
If base missing, falls back to drafts/{id}_draft.png as art source (not ideal).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent
BASES = ROOT / "static" / "assets" / "cards" / "bases"
DRAFTS = ROOT / "static" / "assets" / "cards" / "drafts"
PREMIUM = ROOT / "static" / "assets" / "cards" / "premium"
LOGO = ROOT / "static" / "assets" / "brand" / "percfect_logo_crowned_p.png"
CATALOG = ROOT / "static" / "assets" / "cards" / "catalog" / "official_catalog.json"
HANDOFF_CATALOG = ROOT / "HANDOFFS" / "cards_official_catalog.json"

# Template lock (Nick Nightwing ref): name top · N00 TR · bars BL · logo BR
STAT_KEYS_MALE = ["Attack", "Defence", "Speed", "Swag"]
STAT_KEYS_FEMALE = ["Attack", "Defence", "Beauty", "Seduction"]
STAT_KEYS_VILLAIN = ["Attack", "Defence", "Deviousness", "Swag"]


def _font(size: int, bold: bool = False):
    cands = []
    if bold:
        cands += [
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    cands += [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def find_base(card_id: str) -> Optional[Path]:
    cid = (card_id or "").strip().lower()
    for ext in (".webp", ".png", ".jpg", ".jpeg"):
        p = BASES / f"{cid}_base{ext}"
        if p.is_file():
            return p
    return None


def _keys_for(gender: str = "", theme_key: str = "") -> List[str]:
    t = (theme_key or "").lower()
    g = (gender or "").lower()
    if t in ("villain", "dark", "temptress") or "maleficent" in t:
        return list(STAT_KEYS_VILLAIN)
    if g in ("female", "f", "woman", "girl", "she"):
        return list(STAT_KEYS_FEMALE)
    return list(STAT_KEYS_MALE)


def stamp_card(
    base_path: Path,
    *,
    name: str,
    number: int,
    stats: Dict[str, int],
    out_path: Path,
    gender: str = "",
    theme_key: str = "",
    stamp_mode: str = "full",
) -> Path:
    """Draw name, N##, stats, logo — nothing else. Editable anytime.

    stamp_mode:
      full — name + N## + stats + logo (Nick base = art only)
      stats_logo — stats + logo only (Nick base already has name/number)
    """
    im = Image.open(base_path).convert("RGBA")
    W, H = im.size
    draw = ImageDraw.Draw(im)

    name = (name or "CHARACTER").strip().upper()
    num = max(1, min(99, int(number or 1)))
    num_txt = f"N{num:02d}"
    mode = (stamp_mode or "full").strip().lower()

    # Soft vignette so overlays read
    vig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    if mode == "full":
        for i in range(int(H * 0.14)):
            a = int(140 * (1 - i / max(1, H * 0.14)))
            vd.line([(0, i), (W, i)], fill=(0, 0, 0, a))
    for i in range(int(H * 0.22)):
        a = int(170 * (i / max(1, H * 0.22)) ** 1.2)
        vd.line([(0, H - 1 - i), (W, H - 1 - i)], fill=(0, 0, 0, a))
    im = Image.alpha_composite(im, vig)
    draw = ImageDraw.Draw(im)

    if mode == "full":
        # Name — top center (template style)
        f_name = _font(max(36, int(H * 0.048)), True)
        draw.text((W // 2 + 2, int(H * 0.045) + 2), name[:28], fill=(0, 0, 0, 200), font=f_name, anchor="mt")
        draw.text((W // 2, int(H * 0.045)), name[:28], fill=(255, 230, 160, 255), font=f_name, anchor="mt")
        # Card number — top right N07
        f_num = _font(max(22, int(H * 0.028)), True)
        draw.text((W - int(W * 0.04), int(H * 0.04)), num_txt, fill=(255, 255, 255, 245), font=f_num, anchor="rt")

    # Stats — bottom left metallic bars
    keys = _keys_for(gender, theme_key)
    items = []
    for k in keys:
        if k in stats:
            items.append((k, max(0, min(50, int(stats[k])))))
    # fallback order if stats keys differ
    if len(items) < 4:
        for k, v in list(stats.items())[:4]:
            if (k, max(0, min(50, int(v)))) not in items:
                items.append((str(k), max(0, min(50, int(v)))))
        items = items[:4]

    bar_w = int(W * 0.42)
    bar_h = int(H * 0.038)
    gap = int(H * 0.008)
    margin = int(W * 0.04)
    stack_h = len(items) * bar_h + max(0, len(items) - 1) * gap
    bx = margin
    by = H - margin - stack_h - int(H * 0.02)
    pad = int(W * 0.015)
    draw.rounded_rectangle(
        [bx - pad, by - pad, bx + bar_w + pad, by + stack_h + pad],
        radius=10,
        fill=(0, 0, 0, 150),
    )
    f_lab = _font(max(14, int(H * 0.018)), True)
    f_val = _font(max(16, int(H * 0.022)), True)
    for i, (lab, val) in enumerate(items):
        y = by + i * (bar_h + gap)
        draw.rounded_rectangle(
            [bx, y, bx + bar_w, y + bar_h],
            radius=6,
            fill=(18, 18, 22, 220),
            outline=(190, 190, 200, 200),
            width=2,
        )
        draw.text((bx + 12, y + bar_h // 2), lab, fill=(230, 230, 235, 255), font=f_lab, anchor="lm")
        draw.text((bx + bar_w - 12, y + bar_h // 2), str(val), fill=(255, 255, 255, 255), font=f_val, anchor="rm")

    # Logo BR
    if LOGO.is_file():
        logo_size = int(W * 0.14)
        logo = Image.open(LOGO).convert("RGBA").resize((logo_size, logo_size), Image.LANCZOS)
        lx = W - margin - logo_size
        ly = H - margin - logo_size
        draw.ellipse(
            [lx - 4, ly - 4, lx + logo_size + 4, ly + logo_size + 4],
            fill=(0, 0, 0, 120),
            outline=(232, 200, 120, 160),
            width=2,
        )
        im.alpha_composite(logo, (lx, ly))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "card"


def update_catalog_entry(
    card_id: str,
    *,
    name: str,
    number: int,
    stats: Dict[str, int],
    gender: str = "",
    theme_key: str = "",
) -> bool:
    cid = (card_id or "").strip().lower()
    ok = False
    for path in (CATALOG, HANDOFF_CATALOG):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        found = False
        for c in data.get("characters") or []:
            if str(c.get("id")) == cid:
                c["name"] = (name or c.get("name") or cid).upper()
                c["number"] = int(number)
                c["number_label"] = f"{int(number):02d}"
                c["stats"] = {str(k): int(v) for k, v in stats.items()}
                c["image_url"] = f"/static/assets/cards/drafts/{cid}_draft.png"
                if gender:
                    c["gender"] = gender
                if theme_key:
                    c["theme_key"] = theme_key
                found = True
                ok = True
                break
        if not found:
            # create listing
            data.setdefault("characters", []).append({
                "id": cid,
                "name": (name or cid).upper(),
                "number": int(number),
                "number_label": f"{int(number):02d}",
                "edition": 500,
                "gender": gender or "male",
                "theme_key": theme_key or "dc",
                "stats": {str(k): int(v) for k, v in stats.items()},
                "price_credits": 25,
                "free": False,
                "image_url": f"/static/assets/cards/drafts/{cid}_draft.png",
                "theme_scene": f"/static/assets/cards/themes/{theme_key or 'dc'}/scene.jpg",
                "blurb": "Stamped from Nick front",
                "finish": "nick_front_stamp",
            })
            ok = True
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ok


def restamp_card(
    card_id: str,
    stats: Dict[str, int],
    *,
    name: str = "",
    number: int = None,
    gender: str = "",
    theme_key: str = "",
) -> Tuple[bool, str]:
    cid = (card_id or "").strip().lower() or _slug(name)
    base = find_base(cid)
    if not base:
        return False, f"No base art at bases/{cid}_base.webp — drop Nick front (no text) first."

    # pull defaults from catalog if name/number omitted
    cat_name, cat_num, cat_gender, cat_theme = name, number, gender, theme_key
    stamp_mode = "full"
    if CATALOG.is_file():
        try:
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            for c in data.get("characters") or []:
                if str(c.get("id")) == cid:
                    cat_name = cat_name or c.get("name") or cid
                    cat_num = cat_num if cat_num is not None else int(c.get("number") or 1)
                    cat_gender = cat_gender or c.get("gender") or ""
                    cat_theme = cat_theme or c.get("theme_key") or ""
                    stamp_mode = (c.get("stamp_mode") or "full").strip().lower()
                    if not stats:
                        stats = dict(c.get("stats") or {})
                    break
        except Exception:
            pass

    cat_name = (cat_name or cid).upper()
    cat_num = int(cat_num if cat_num is not None else 1)
    clean = {str(k): max(0, min(50, int(v))) for k, v in stats.items()}

    out = DRAFTS / f"{cid}_draft.png"
    stamp_card(
        base,
        name=cat_name,
        number=cat_num,
        stats=clean,
        out_path=out,
        gender=cat_gender,
        theme_key=cat_theme,
        stamp_mode=stamp_mode,
    )
    try:
        Image.open(out).save(PREMIUM / f"{cid}.png", "PNG", optimize=True)
    except Exception:
        pass
    update_catalog_entry(
        cid,
        name=cat_name,
        number=cat_num,
        stats=clean,
        gender=cat_gender,
        theme_key=cat_theme,
    )
    return True, f"/static/assets/cards/drafts/{cid}_draft.png?v={int(out.stat().st_mtime)}"
