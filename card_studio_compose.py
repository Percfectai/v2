"""Stamp Percfect chrome onto a 2:3 plate (Card Studio pack)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
LOGO_CANDIDATES = (
    ROOT / "static" / "assets" / "brand" / "percfect_logo_crowned_p.png",
    ROOT / "static" / "assets" / "brand" / "crowned-p.png",
)
THEMES = ROOT / "static" / "assets" / "cards" / "themes"

W, H = 832, 1248
STAT_KEYS = {
    "men": ("Attack", "Defence", "Speed", "Swag"),
    "women": ("Attack", "Defence", "Beauty", "Seduction"),
    "villains": ("Attack", "Defence", "Deviousness", "Swag"),
}


def serial_of(card: dict[str, Any]) -> str:
    n = int(card.get("number") or 0)
    digits = f"{n:02d}" if n < 100 else str(n)
    return f"{card.get('rarity', 'R')}{card.get('theme', 'H')}{digits}"


_FONT_STACKS = {
    "hero": (
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "Oswald-Bold.ttf",
    ),
    "gothic": (
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ),
    "script": (
        "/System/Library/Fonts/Supplemental/SnellRoundhand.ttc",
        "/System/Library/Fonts/Supplemental/Apple Chancery.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    ),
    "serif": (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "DejaVuSerif.ttf",
    ),
    "stencil": (
        "/System/Library/Fonts/Supplemental/Copperplate.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ),
}


def _font(size: int, bold: bool = False, plate: str = "hero") -> ImageFont.ImageFont:
    stack = list(_FONT_STACKS.get(plate) or _FONT_STACKS["hero"])
    stack.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for name in stack:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _logo_path() -> Path | None:
    for p in LOGO_CANDIDATES:
        if p.exists():
            return p
    return None


def _theme_path(theme: str) -> Path | None:
    key = {"D": "dc", "M": "marvel", "G": "got", "V": "villain"}.get(str(theme), "")
    if not key:
        return None
    for p in (THEMES / f"{key}.jpg", THEMES / key / "scene.jpg"):
        if p.exists():
            return p
    return None


def _backdrop_path(card: dict[str, Any]) -> Path | None:
    key = str(card.get("backdrop") or "").strip().lower()
    if key and key not in ("none", "custom"):
        for p in (THEMES / f"{key}.jpg", THEMES / key / "scene.jpg"):
            if p.exists():
                return p
    return _theme_path(card.get("theme") or "")


def compose_front(card: dict[str, Any], art: Image.Image | None = None) -> Image.Image:
    plate = Image.new("RGB", (W, H), (14, 16, 22))
    custom = card.get("customBackdrop") or card.get("custom_backdrop")
    bg_im = None
    if isinstance(custom, Image.Image):
        bg_im = custom.convert("RGB").resize((W, H))
    elif isinstance(custom, str) and custom.strip():
        try:
            import requests

            r = requests.get(custom, timeout=20)
            r.raise_for_status()
            bg_im = Image.open(io.BytesIO(r.content)).convert("RGB").resize((W, H))
        except Exception:
            bg_im = None
    if bg_im is None:
        theme = _backdrop_path(card)
        if theme:
            bg_im = Image.open(theme).convert("RGB").resize((W, H))
    if bg_im is not None:
        plate.paste(bg_im, (0, 0))
    if art is not None:
        # Same as the page: the still covers the whole plate, anchored to the top.
        a = art.convert("RGBA")
        s = max(W / a.width, H / a.height)
        a = a.resize((round(a.width * s), round(a.height * s)), Image.Resampling.LANCZOS)
        x = (a.width - W) // 2
        plate = plate.convert("RGBA")
        plate.alpha_composite(a.crop((x, 0, x + W, H)))
        plate = plate.convert("RGB")

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, 0, W, 220), fill=(8, 10, 14, 110))
    d.rectangle((0, H - 340, W, H), fill=(8, 10, 14, 150))
    plate = Image.alpha_composite(plate.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(plate)

    plate_font = str(card.get("plateFont") or card.get("plate_font") or "hero")
    name = str(card.get("name") or "CHARACTER NAME")
    if plate_font != "script":
        name = name.upper()
    tag = str(card.get("tagline") or "")
    draw.text((36, 36), name[:22], font=_font(54, True, plate_font), fill=(236, 240, 246))
    if tag:
        draw.text((36, 98), tag[:42], font=_font(22, False, plate_font), fill=(210, 214, 220))
    num = int(card.get("number") or 0)
    draw.text((W - 150, 42), f"no. {num:03d}" if num else "no. —", font=_font(22), fill=(210, 214, 220))

    stats = card.get("stats") or []
    keys = STAT_KEYS.get(card.get("role") or "men", STAT_KEYS["men"])
    y = H - 310
    for i, key in enumerate(keys):
        val = 0
        if i < len(stats):
            item = stats[i]
            val = int(item.get("value") or 0) if isinstance(item, dict) else int(item or 0)
        draw.rounded_rectangle((28, y, 250, y + 52), 8, fill=(12, 14, 18), outline=(200, 208, 220))
        draw.text((40, y + 12), key, font=_font(20), fill=(236, 240, 246))
        draw.text((188, y + 12), f"{val:03d}" if val else "000", font=_font(20, True), fill=(236, 240, 246))
        y += 60

    logo = _logo_path()
    if logo:
        mark = Image.open(logo).convert("RGBA")
        mark.thumbnail((120, 120), Image.Resampling.LANCZOS)
        plate.paste(mark, (W - 148, H - 168), mark)
    draw.text((W - 148, H - 44), serial_of(card), font=_font(16, True), fill=(236, 240, 246))
    return plate


def compose_back(card: dict[str, Any]) -> Image.Image:
    plate = Image.new("RGB", (W, H), (11, 13, 18))
    draw = ImageDraw.Draw(plate)
    draw.text((36, 36), "CHARACTER DETAILS", font=_font(16), fill=(150, 146, 138))
    draw.text((36, 64), str(card.get("name") or "UNNAMED").upper(), font=_font(48, True), fill=(244, 241, 234))
    meta = f"Lv {card.get('level', 1)}    {card.get('xp', 0)} XP    {serial_of(card)}"
    draw.text((36, 128), meta, font=_font(16), fill=(197, 205, 216))
    dossier = str(card.get("dossier") or card.get("tagline") or "").strip()
    draw.rounded_rectangle((28, 168, W - 28, H // 2 - 16), 10, outline=(60, 64, 72), fill=(18, 20, 26))
    draw.text((44, 184), "BIO", font=_font(14), fill=(150, 146, 138))
    # wrap bio
    y = 210
    line = ""
    for word in (dossier or "—").split():
        trial = (line + " " + word).strip()
        if len(trial) > 42:
            draw.text((44, y), line[:48], font=_font(18), fill=(183, 177, 167))
            y += 28
            line = word
            if y > H // 2 - 50:
                break
        else:
            line = trial
    if line and y <= H // 2 - 50:
        draw.text((44, y), line[:48], font=_font(18), fill=(183, 177, 167))

    abilities = card.get("abilities") or []
    level = int(card.get("level") or 1)
    y = H // 2 + 8
    box_h = 92
    for i in range(4):
        unlocked = level >= i + 1
        a = abilities[i] if i < len(abilities) and isinstance(abilities[i], dict) else {}
        name = a.get("name") if unlocked else f"L{i + 1}"
        desc = a.get("description") if unlocked else "Locked"
        draw.rounded_rectangle((28, y, W - 28, y + box_h), 10, outline=(60, 64, 72), fill=(18, 20, 26))
        draw.text((44, y + 12), f"{i + 1:02d}", font=_font(14), fill=(110, 106, 100))
        draw.text((88, y + 12), str(name or "—")[:28], font=_font(20, True), fill=(244, 241, 234))
        draw.text((88, y + 44), str(desc or "")[:70], font=_font(15), fill=(183, 177, 167))
        y += box_h + 10
    wins = int(card.get("wins") or 0)
    draw.text((36, H - 56), f"TROPHIES    {wins}", font=_font(20, True), fill=(244, 241, 234))
    return plate


def to_jpeg(im: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()
