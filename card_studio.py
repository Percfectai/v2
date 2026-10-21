"""Percfect Card Studio — /studios/trading-cards forge + stamp.

Writer = chat silo (XAI_CHARACTER_CHAT_API_KEY / XAI_CARD_WRITER_API_KEY).
Portrait = image pool via generate_image_xai. Never mix those keys.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

import requests
from flask import Blueprint, Response, jsonify, request
from flask_login import current_user, login_required
from PIL import Image

from card_studio_compose import compose_back, compose_front, serial_of, to_jpeg

log = logging.getLogger("card_studio")
bp = Blueprint("card_studio", __name__)

IMAGINE_TEMPLATE = (
    "Cinematic full-body FRONT VIEW still of a single original character STANDING, "
    "feet visible, looking at the camera, trading-card portrait composition filling a 2:3 frame, "
    "photoreal digital painting, dramatic lighting, rich environment behind them. {art}. "
    "No text, no letters, no watermark, no frame, no logo, no UI, no stats, no title, no card chrome."
)
STAT_KEYS = {
    "men": ["Attack", "Defence", "Speed", "Swag"],
    "women": ["Attack", "Defence", "Beauty", "Seduction"],
    "villains": ["Attack", "Defence", "Deviousness", "Swag"],
}
# Card art is full bleed. Saying "never stretch" also keeps generate_image_xai from appending its
# "preserve exact proportions" guard, which padded square refs into 2:3 with bars (the border bug).
EDGE_TO_EDGE = (
    "Edge to edge: no border, no frame, no bars, no padding, no letterboxing. "
    "Never stretch the character."
)

# Scene shot: the Photos generator run from the card page.
SCENE_SHOT_PROMPT = (
    "Epic card-style shot of the character shown in <IMAGE_1>: full-body rendering, "
    "taking up the frame head to toe, {pose} pose, {where}. "
    "Same face, hair, outfit and style as <IMAGE_1>. "
    "NO wording, text, letters, logo, border or frame: the action trading card template "
    "gets layered over this image. " + EDGE_TO_EDGE
)

# Six-pose sheet (handoff 1.4a, Appendix A): a cheap 3×2 preview; the picked panel is re-rendered
# at full resolution, never cropped for final art.
# Nick's prompt, word for word; do not reword. {x } = theme, {y} = character name, {z} = description.
# An empty theme drops "{x }", an empty description drops ", {z}". Sent with exact_prompt (nothing added).
POSE_SHEET_PROMPT = (
    "Create six 2:3 epic {x }themed character trading cards based on this charcter shown in image1 named, "
    "{y}, {z}. Six different epic style backgrounds, and poses for the character having them fill the hole "
    "frame in every card.No wording border or stats written on the card it should be just the background "
    "and character to be prepared for my template to overlay it, 2 rows 3 columns."
)
# Nick's "six more" prompt, word for word; sent with the old sheet as image2. {x} = what to change,
# typed by the user; an empty box drops " (Make the next six more {x})".
SIX_MORE_PROMPT = (
    "On the same layout of two rows, three columns, create Six more different style backgrounds, and poses "
    "for the character, having them fill the frame, Head to toe in every card. No wording border or stats "
    "written on the card it should be just the background and character to be prepared for my template to "
    "overlay it. (Make the next six more {x})"
)

POSE_PICK_PROMPT = (
    "Recreate the panel in <IMAGE_2> as one full-resolution image: the same pose, the same "
    "background, the same lighting and camera angle. The character is exactly the one in <IMAGE_1>: "
    "same face, hair, body, outfit, colors, armor and accessories. The character fills the frame, head "
    "to toe. No text, no letters, no watermark, no logo, no UI, no card chrome. " + EDGE_TO_EDGE
)
SCENE_BY_THEME = {
    "P": "fairytale castle", "D": "Gotham-style city at night", "M": "superhero city",
    "V": "dark villain lair", "N": "bright video-game world", "G": "medieval castle in the north",
    "I": "vintage", "F": "fantasy kingdom",
}
THEME_BACKDROPS = ("dc", "marvel", "got", "villain")
_backdrop_urls: dict[str, str] = {}

# Shown only until the skills agent writes this character's own versions (handoff Part 2.2).
DEFAULT_ABS = [{"name": "", "description": ""} for _ in range(4)]


# Chat model the keys can actually use (grok-3 is not on any of them). Override with XAI_CARD_WRITER_MODEL.
WRITER_MODEL = os.getenv("XAI_CARD_WRITER_MODEL") or "grok-4.20-0309-non-reasoning"


def _writer_key() -> str:
    # Chat keys only — never image pool (XAI_API_KEY / XAI_API_KEYS).
    # Prefer dedicated card writer; fall back to other chat silos (Vanessa etc.) so
    # "Write skills with AI" works when CARD_WRITER / CHARACTER_CHAT aren't set on Render.
    for env in (
        "XAI_CARD_WRITER_API_KEY",
        "XAI_CHARACTER_CHAT_API_KEY",
        "XAI_BRIDGE_API_KEY",
        "XAI_DIRECTOR_API_KEY",
        "XAI_VANESSA_API_KEY",
        "XAI_MIRA_API_KEY",
        "XAI_SAL_API_KEY",
        "XAI_ASHLEY_API_KEY",
        "XAI_DEBUG_API_KEY",
    ):
        k = (os.getenv(env) or "").strip()
        if k and "," not in k:
            return k
    return ""


def _brain_json(system: str, user: str, xai_key: str = "", images: list | None = None, max_tokens: int = 0) -> dict:
    """The card 'AI brain': Gemini when GEMINI_API_KEY is set (Nick's pick), else the xAI chat key.

    images: picture URLs the brain should look at (e.g. the character's front/back/side shots).
    """
    import base64

    images = [u for u in (images or []) if isinstance(u, str) and u.startswith("http")][:3]
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if gemini_key:
        model = os.getenv("GEMINI_MODEL") or "gemini-flash-latest"
        parts = [{"text": user}]
        for u in images:
            try:
                img = requests.get(u, timeout=20)
                img.raise_for_status()
                parts.append({"inline_data": {
                    "mime_type": img.headers.get("content-type", "image/jpeg").split(";")[0],
                    "data": base64.b64encode(img.content).decode("ascii"),
                }})
            except Exception:
                log.warning("brain: could not load picture %s", u[:80])
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"X-goog-api-key": gemini_key, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0.9, "maxOutputTokens": max_tokens or 900, "responseMimeType": "application/json"},
            },
            timeout=60,
        )
        r.raise_for_status()
        parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])
        text = "".join(p.get("text") or "" for p in parts) or "{}"
    else:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {xai_key}", "Content-Type": "application/json"},
            json={
                "model": WRITER_MODEL,
                "temperature": 0.9,
                "max_tokens": max_tokens or 700,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [{"type": "text", "text": user}] + [
                        {"type": "image_url", "image_url": {"url": u}} for u in images
                    ]},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        text = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


# Gemini fills the theme + description slots of Nick's six-pose prompt from the character's photos.
# Claude's wording; Nick can replace it. Nick's prompt itself is never changed.
SLOT_FILL_PROMPT = (
    "You fill in two blanks in a trading-card image prompt. Look at the character's pictures and read "
    "what the creator wrote. Work out who the character is and which world, film, show, game or era they "
    "come from. Return ONLY JSON: {\"theme\": str, \"description\": str}. theme: 1 to 4 words naming "
    "their world (it is used as '<theme> themed'). description: one sentence on who they are and the "
    "settings that fit them; it follows their name, so don't start with the name. Villains and heroes "
    "alike: fit the character as they are. If the creator gave a theme or description, keep its meaning and make it "
    "sharper; never contradict it."
)


def _fill_pose_slots(template: str, name: str, theme: str, description: str, pictures: list) -> tuple:
    """(theme, description) for Nick's prompt, sharpened by the AI brain from the photos. Falls back to his input."""
    user = (
        f"Creator's name for the character: {name or '(none)'}\nCreator's theme: {theme or '(none)'}\n"
        f"Creator's description: {description or '(none)'}\nThe prompt these fill in: {template}"
    )
    try:
        out = _brain_json(SLOT_FILL_PROMPT, user, _writer_key(), pictures)
        return (
            str(out.get("theme") or theme or "").strip()[:60],
            str(out.get("description") or description or "").strip()[:500],
        )
    except Exception:
        log.exception("pose sheet: slot fill failed; using the creator's text")
        return theme, description


# AI help for the back description. Claude's wording; Nick can replace it.
DESCRIBE_PROMPT = (
    "You write the short description on the back of a Percfect trading card. Look at the character's "
    "pictures (front, back and side) and read how they were described when they were built. Say who "
    "they are, what they look like and what they're from (film, show, anime, game), in a smart way "
    "that fits this exact character. One or two sentences, at most 140 characters, no hashtags. "
    "Return ONLY JSON: {\"description\": str}."
)


# Every card has the same four skill mechanics (handoff Part 2). The xAI chat agent writes
# how THIS character does each one, so the battle video can show it their way.
# (label on the card, fixed game effect, what the story must show on screen)
SKILL_MECHANICS = (
    ("Weakest stat +50",
     "their weakest stat{weakest} goes up by 50; this can never win the fight on its own",
     "they fix their weak spot{weakest}, so the weakness visibly turns into a strength"),
    ("Opponent's best stat → 0",
     "the opponent's strongest stat drops to 0",
     "they shut down the opponent's best weapon or strength, so it visibly stops working"),
    ("All stats +50",
     "every one of their stats goes up by 50",
     "a full-body surge where everything about them powers up at once"),
    ("Wins vs any lower level",
     "automatic win against any lower-level card; against another level 4 they play their strongest "
     "asset{strongest} in the smartest way they can",
     "their signature finishing move, built on their strongest asset{strongest}"),
)


def write_card_skills(name: str, gender: str, description: str, stats: list, idea: str = "") -> tuple:
    """xAI chat agent: four in-character skills (name + on-screen story) for the fixed mechanics.

    stats: [{"key": "Attack", "value": 70}, ...]. idea: the creator's own direction, followed if given.
    Returns (skills, written_by_ai). Fallback skills are never saved to the character.
    """
    fallback = [
        {"level": i + 1, "name": DEFAULT_ABS[i]["name"], "description": DEFAULT_ABS[i]["description"], "effect": m[0]}
        for i, m in enumerate(SKILL_MECHANICS)
    ]
    api_key = _writer_key()
    if not api_key and not os.getenv("GEMINI_API_KEY"):
        log.warning("skills agent: no GEMINI_API_KEY and no xAI chat key set")
        return fallback, False
    vals = {str(s.get("key")): int(s.get("value") or 0) for s in (stats or []) if isinstance(s, dict) and s.get("key")}
    ranked = sorted(vals, key=vals.get) if len(set(vals.values())) > 1 else []
    weakest = f" ({ranked[0]})" if ranked else ""
    strongest = f" ({ranked[-1]})" if ranked else ""
    system = (
        "You write the four special skills for one Percfect battle card. Every card has the same four "
        "skills with FIXED game effects. Never change, soften or add to an effect. Your only job: invent "
        "how THIS character does each one, with their powers, gear, world and personality (a witch brews "
        "a potion, a knight raises a banner), so the battle video can show it happening. "
        "Return ONLY JSON: {\"description\": str, \"skills\": [{\"name\": str, \"story\": str}, exactly 4, "
        "in level order]}. description: one or two sentences, at most 140 characters, introducing who "
        "they are, for the back of their card. "
        "name: 2 to 4 punchy words, the move's name. story: one vivid sentence, at most 30 words, of "
        "exactly what happens on screen when the skill fires; it must clearly show that level's effect. "
        "No numbers and no stat names in the story. PG-13."
    )
    user = (
        f"Character: {name}\nGender: {gender or 'unspecified'}\n"
        f"Who they are: {description or 'use the name for inspiration'}\n"
        f"Their stats: {', '.join(f'{k} {v}' for k, v in vals.items()) or 'not set yet'}\n"
        + (f"Creator's idea for their powers (follow it): {idea}\n" if idea else "")
        + "\n"
        + "\n".join(
            f"Level {i + 1}. Effect: {m[1].format(weakest=weakest, strongest=strongest)}. "
            f"Story must show: {m[2].format(weakest=weakest, strongest=strongest)}."
            for i, m in enumerate(SKILL_MECHANICS)
        )
    )
    try:
        parsed = _brain_json(system, user, api_key)
        raw = parsed.get("skills") or []
        write_card_skills.last_description = str(parsed.get("description") or "").strip()[:140]
    except Exception:
        log.exception("skills agent failed")
        return fallback, False
    if len([s for s in raw if isinstance(s, dict) and s.get("name") and s.get("story")]) < 4:
        log.warning("skills agent returned %s usable skills", len(raw))
        return fallback, False
    out = []
    for i, m in enumerate(SKILL_MECHANICS):
        s = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        out.append({
            "level": i + 1,
            "name": str(s.get("name") or fallback[i]["name"])[:28],
            "description": str(s.get("story") or fallback[i]["description"])[:180],
            "effect": m[0],
        })
    return out, True


def _role_from_gender(gender: str) -> str:
    g = (gender or "").strip().lower()
    if g in ("female", "f", "woman", "girl", "she"):
        return "women"
    if g in ("villain", "dark"):
        return "villains"
    return "men"


def _open_art(src: str) -> Optional[Image.Image]:
    if not src:
        return None
    try:
        if src.startswith("data:"):
            import base64

            raw = base64.b64decode(src.split(",", 1)[1])
            return Image.open(io.BytesIO(raw))
        r = requests.get(src, timeout=30)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content))
    except Exception:
        log.exception("card art open failed")
        return None


def _write_plate_spec(prompt: str, role: str, theme: str, rarity: str, name: str) -> dict:
    keys = STAT_KEYS.get(role) or STAT_KEYS["men"]
    api_key = _writer_key()
    spec: dict[str, Any] = {}
    if api_key:
        sys = (
            "You are the plate writer for Percfect Cards. Return ONLY JSON with keys: "
            "name, tagline, stats (object with EXACT keys "
            + ", ".join(f'"{k}"' for k in keys)
            + " as integers 0-100), abilities (array of exactly 4 {name, description}), "
            "artPrompt (full-body FRONT VIEW still, no text/logo/frame), atmosphere (rain|snow|embers|mist|none)."
        )
        try:
            r = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": WRITER_MODEL,
                    "temperature": 0.8,
                    "max_tokens": 900,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": sys},
                        {
                            "role": "user",
                            "content": f"Prompt: {prompt[:800]}\nRole: {role}\nTheme: {theme}\nRarity: {rarity}\nName: {name or 'invent one'}",
                        },
                    ],
                },
                timeout=60,
            )
            if r.status_code < 400:
                text = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"
                start, end = text.find("{"), text.rfind("}")
                if start != -1 and end != -1:
                    spec = json.loads(text[start : end + 1])
        except Exception:
            log.exception("card writer failed")
    spec_name = str(spec.get("name") or name or "UNNAMED")[:28]
    tagline = str(spec.get("tagline") or "Uncatalogued")[:48]
    stats_obj = spec.get("stats") if isinstance(spec.get("stats"), dict) else {}
    if not stats_obj:
        try:
            import app as app_mod

            gmap = {"women": "female", "men": "male", "villains": "villain"}
            stats_obj = app_mod._trading_card_stats_for_gender(gmap.get(role, "male"), spec_name)
        except Exception:
            stats_obj = {k: 28 for k in keys}
    stats = [{"key": k, "value": max(0, min(100, int(stats_obj.get(k) or 28)))} for k in keys]
    raw_abs = spec.get("abilities") if isinstance(spec.get("abilities"), list) else DEFAULT_ABS
    abilities = []
    for i in range(4):
        a = raw_abs[i] if i < len(raw_abs) and isinstance(raw_abs[i], dict) else DEFAULT_ABS[i]
        abilities.append({
            "name": str(a.get("name") or DEFAULT_ABS[i]["name"])[:28],
            "description": str(a.get("description") or "")[:120],
        })
    art_prompt = str(spec.get("artPrompt") or prompt or spec_name)[:900]
    atmosphere = spec.get("atmosphere") if spec.get("atmosphere") in ("rain", "snow", "embers", "mist", "none") else "none"
    return {
        "name": spec_name,
        "tagline": tagline,
        "stats": stats,
        "abilities": abilities,
        "artPrompt": art_prompt,
        "atmosphere": atmosphere,
        "role": role,
        "theme": theme,
        "rarity": rarity,
    }


def _imagine_portrait(art_prompt: str, reference: Optional[str]) -> Optional[str]:
    import app as app_mod

    prompt = IMAGINE_TEMPLATE.format(art=(art_prompt or "")[:700])
    refs = [reference] if reference else []
    result = app_mod.generate_image_xai(
        prompt,
        image_urls=refs or None,
        aspect_ratio="2:3",
        force_aspect=True,
    )
    url = None
    if isinstance(result, dict):
        url = ((result.get("data") or [{}])[0].get("url") if result.get("data") else None) or result.get("url")
    if url:
        try:
            return app_mod._persist_image(url)
        except Exception:
            return url
    return None


def stamp_jpeg(card: dict, face: str = "front") -> bytes:
    art = None
    src = card.get("artUrl") or card.get("art_url") or card.get("primary_image_url") or ""
    if face != "back":
        art = _open_art(src)
    im = compose_back(card) if face == "back" else compose_front(card, art)
    return to_jpeg(im)


def stamp_hero_card(
    *,
    user_id: int,
    name: str,
    gender: str,
    description: str,
    portrait_url: str,
    is_admin: bool = False,
    theme: str = "H",
    rarity: str = "R",
    number: int = 0,
    backdrop: str = "",
    custom_backdrop: str = "",
    plate_font: str = "hero",
    stats: list | None = None,
    restyle: bool = False,
    tagline: str = "",
) -> dict:
    """Stamp Card Studio chrome. Imagine restyle only if restyle=True (image pool)."""
    import app as app_mod
    from credit_wallet import credit_balance

    app_mod.reset_daily_if_needed(user_id)
    u = (
        app_mod.supabase.table("users")
        .select("picture_credits,video_credits,images_today,is_admin")
        .eq("id", user_id)
        .single()
        .execute()
        .data
        or {}
    )
    cost = int(getattr(app_mod, "CARD_STATIC_CREDITS", 2) or 2)
    bal = credit_balance(u)
    if not is_admin and bal < cost:
        raise RuntimeError(f"Hero card needs {cost} credits — you have {bal}.")
    role = _role_from_gender(gender)
    spec = _write_plate_spec(description or name, role, theme, rarity, name)
    spec["number"] = int(number or 0)
    spec["theme"] = (theme or "H")[:1]
    spec["rarity"] = rarity if rarity in ("R", "S", "G") else "R"
    spec["backdrop"] = (backdrop or "").strip().lower()
    spec["customBackdrop"] = (custom_backdrop or "").strip()
    spec["plateFont"] = plate_font if plate_font in ("hero", "gothic", "script", "serif", "stencil") else "hero"
    if tagline:
        spec["tagline"] = str(tagline)[:48]
    if isinstance(stats, list) and stats:
        keys = STAT_KEYS.get(role) or STAT_KEYS["men"]
        cleaned = []
        for i, k in enumerate(keys):
            item = stats[i] if i < len(stats) else {}
            if isinstance(item, dict):
                val = int(item.get("value") or 0)
            else:
                try:
                    val = int(item)
                except (TypeError, ValueError):
                    val = 0
            cleaned.append({"key": k, "value": max(0, min(100, val))})
        spec["stats"] = cleaned
    art_url = portrait_url
    if restyle:
        try:
            painted = _imagine_portrait(spec.get("artPrompt") or name, portrait_url or None)
            if painted:
                art_url = painted
        except Exception:
            log.exception("hero card imagine failed; stamping source portrait")
    spec["artUrl"] = art_url
    jpeg = stamp_jpeg(spec, "front")
    url = app_mod._persist_image_bytes(jpeg, ext="jpg", content_type="image/jpeg")
    if not is_admin:
        try:
            app_mod._apply_spend(
                user_id,
                u,
                cost,
                {"images_today": int(u.get("images_today") or 0) + 1},
            )
        except Exception:
            log.exception("hero card credit consume")
    spec["serial"] = serial_of(spec)
    spec["url"] = url
    return spec


def export_plate_http():
    data = request.get_json(silent=True) or {}
    card = data.get("card") or {}
    face = "back" if data.get("face") == "back" else "front"
    if data.get("artBytes") and not card.get("artUrl"):
        card = dict(card)
        card["artUrl"] = data.get("artBytes")
    payload = stamp_jpeg(card, face)
    filename = f"{serial_of(card)}-{face}.jpg"
    return Response(
        payload,
        mimetype="image/jpeg",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _cutout_rgba(im: Image.Image) -> Image.Image:
    """Lift a character off the white studio, keeping the original frame.

    Studio white touching the edge, flat white pockets (the gap between the legs)
    and the white rim all go transparent. The grey floor patch under the feet
    becomes a soft dark shadow so it reads on any scene.
    """
    import cv2
    import numpy as np

    rgba = np.array(im.convert("RGBA"))
    h, w = rgba.shape[:2]
    rgb = rgba[..., :3].astype(np.int16)
    lum = rgb.mean(axis=2)
    sat = rgb.max(axis=2) - rgb.min(axis=2)

    white = (lum > 236) & (sat < 14)
    shadow = np.zeros_like(white)
    shadow[int(h * 0.85):] = True
    shadow &= (lum > 165) & (sat < 18)

    _n, labels = cv2.connectedComponents((white | shadow).astype(np.uint8), connectivity=4)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bg = np.isin(labels, edge[edge > 0])

    # Enclosed pockets of flat studio white. White clothes have shading, so they stay.
    n, pockets = cv2.connectedComponents(white.astype(np.uint8), connectivity=4)
    flat = pockets.ravel()
    count = np.bincount(flat, minlength=n)
    mean = np.bincount(flat, weights=lum.ravel(), minlength=n) / np.maximum(count, 1)
    sq = np.bincount(flat, weights=(lum ** 2).ravel(), minlength=n) / np.maximum(count, 1)
    std = np.sqrt(np.maximum(sq - mean ** 2, 0))
    gap = (mean > 244) & (std < 3.5) & (count > (h * w) // 4000)
    gap[0] = False
    bg |= gap[pockets]

    if bg.mean() < 0.08:
        # Not a white studio shot: try rembg if it is installed, else leave it whole.
        try:
            from rembg import remove

            cut = remove(im.convert("RGBA"))
            return cut if isinstance(cut, Image.Image) else Image.open(io.BytesIO(cut)).convert("RGBA")
        except Exception:
            log.info("no rembg; leaving a full-scene image whole")
        return im.convert("RGBA")

    # Shave the outer 1-2 px (the white blend) and feather inward only.
    fg = np.where(bg, 0, 255).astype(np.uint8)
    k = 5 if max(h, w) > 900 else 3
    soft = cv2.GaussianBlur(cv2.erode(fg, np.ones((k, k), np.uint8)), (0, 0), 1.0)
    out = rgba.copy()
    out[..., 3] = np.minimum(soft, fg)
    floor = bg & shadow
    out[floor, :3] = 0
    out[floor, 3] = np.clip((236 - lum[floor]) * 1.4, 0, 160).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


@bp.route("/studios/trading-cards/cutout", methods=["POST"])
@login_required
def cutout():
    import app as app_mod
    import base64

    data = request.get_json(silent=True) or {}
    src = (data.get("image") or data.get("url") or "").strip()
    f = request.files.get("file")
    im = None
    if f and getattr(f, "filename", None):
        im = Image.open(io.BytesIO(f.read()))
    elif src.startswith("data:"):
        raw = base64.b64decode(src.split(",", 1)[1])
        im = Image.open(io.BytesIO(raw))
    elif src:
        r = requests.get(src, timeout=30)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content))
    if im is None:
        return jsonify({"ok": False, "error": "Need a character still."}), 400
    cut = _cutout_rgba(im)
    buf = io.BytesIO()
    cut.save(buf, "PNG")
    png = buf.getvalue()
    try:
        url = app_mod._persist_image_bytes(png, ext="png", content_type="image/png")
    except Exception:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return jsonify({"ok": True, "url": url})


@bp.route("/studios/trading-cards/from-upload", methods=["POST"])
@login_required
def from_upload():
    """Run an upload through Characters (3D animated, white studio) then return the job."""
    import app as app_mod
    from credit_wallet import character_generate_cost, credit_balance
    from studio_enqueue import enqueue

    app_mod.reset_daily_if_needed(current_user.id)
    res = (
        app_mod.supabase.table("users")
        .select("picture_credits,video_credits,images_today,is_admin")
        .eq("id", current_user.id)
        .single()
        .execute()
    )
    u = res.data or {}
    f = request.files.get("file") or request.files.get("image")
    src = (request.form.get("image_url") or "").strip()
    if f and getattr(f, "filename", None):
        raw = f.read()
        ext, ct = "png", f.mimetype or "image/png"
        if "jpeg" in ct or (f.filename or "").lower().endswith((".jpg", ".jpeg")):
            ext, ct = "jpg", "image/jpeg"
        src = app_mod._persist_image_bytes(raw, ext=ext, content_type=ct)
    if not src:
        return jsonify({"ok": False, "error": "Upload a photo first."}), 400
    cost = character_generate_cost(1, super_accuracy=False)
    bal = credit_balance(u)
    if not current_user.is_admin and bal < cost:
        return jsonify({"ok": False, "error": f"Needs {cost} credits — you have {bal}.", "needed": cost}), 402
    payload = {
        "source_image": src,
        "source_images": [src],
        "description": (
            "full-body standing front view, 3D animated character, "
            "solid pure white studio background, mature adult, same identity as the reference"
        ),
        "name": (request.form.get("name") or "")[:80],
        "gender": (request.form.get("gender") or "").strip(),
        "is_admin": bool(current_user.is_admin),
        "super_accuracy": False,
        "cost": cost,
        "ref_count": 1,
    }
    job_id = enqueue(app_mod.studio_jobs, int(current_user.id), "character_one", payload)
    return jsonify({"ok": True, "job_id": job_id, "async": True, "kind": "character_one", "cost": cost})


def _hosted_image(src: str) -> str:
    """Data URL → public URL so Imagine can fetch it; http URLs pass through."""
    import app as app_mod
    import base64

    if not src.startswith("data:"):
        return src
    head, b64 = src.split(",", 1)
    ext, ct = ("png", "image/png") if "png" in head else ("jpg", "image/jpeg")
    return app_mod._persist_image_bytes(base64.b64decode(b64), ext=ext, content_type=ct)


@bp.route("/studios/trading-cards/scene-shot", methods=["POST"])
@login_required
def scene_shot():
    """Character in a new pose on an epic scene, without leaving the card page.

    Auto = character only; mine = character + background.
    """
    import app as app_mod

    data = request.get_json(silent=True) or {}
    character = (data.get("character") or "").strip()
    if not character:
        return jsonify({"ok": False, "error": "Drop a character on the card first."}), 400
    pose = (data.get("pose") or "").strip()[:40] or "serious"
    refs = [_hosted_image(character)]
    if data.get("mine"):
        bg = (data.get("background") or "").strip()
        preset = (data.get("backdrop") or "").strip().lower()
        if not bg and preset in THEME_BACKDROPS:
            if preset not in _backdrop_urls:
                path = os.path.join(app_mod.app.static_folder, "assets", "cards", "themes", f"{preset}.jpg")
                with open(path, "rb") as fh:
                    _backdrop_urls[preset] = app_mod._persist_image_bytes(
                        fh.read(), ext="jpg", content_type="image/jpeg"
                    )
            bg = _backdrop_urls[preset]
        if not bg:
            return jsonify({"ok": False, "error": "Pick a background or upload your own first."}), 400
        refs.append(_hosted_image(bg))
        where = "with <IMAGE_2> as the background, keeping its setting, mood and lighting"
    else:
        scene = (data.get("scene") or "").strip()[:80] or SCENE_BY_THEME.get((data.get("theme") or "")[:1], "")
        where = f"with an epic {scene} background" if scene else "with an epic background"
    return _enqueue_card_image(SCENE_SHOT_PROMPT.format(pose=pose, where=where), refs, "2:3")


# Rarity finishes: the finished art re-rendered by AI from the exact same image.
FINISH_PROMPTS = {
    "silver": (
        "Turn the picture in <IMAGE_1> into a Silver Rare trading card image: a brushed silver "
        "metallic foil sheen and fine sparkle across the whole picture. "
    ),
    "holo": (
        "Turn the picture in <IMAGE_1> into a Super Rare holographic trading card image: rainbow "
        "holographic foil, prismatic light refractions and sparkle across the whole picture, like a "
        "premium holo card. "
    ),
}
FINISH_KEEP = (
    "Keep the character, pose, background, composition, colors and likeness exactly the same. "
    "No text, no letters, no logo, no frame, no card chrome. " + EDGE_TO_EDGE
)


@bp.route("/studios/trading-cards/finish", methods=["POST"])
@login_required
def finish():
    """Silver Rare / Super Rare Hologram: charged like one Photos render, saved to the Library."""
    data = request.get_json(silent=True) or {}
    art = (data.get("art") or "").strip()
    kind = data.get("finish")
    if kind not in FINISH_PROMPTS:
        return jsonify({"ok": False, "error": "Pick Silver Rare or Super Rare Hologram."}), 400
    if not art:
        return jsonify({"ok": False, "error": "Finish the card art first."}), 400
    refs = [_hosted_image(art)]
    prompt = FINISH_PROMPTS[kind]
    background = (data.get("background") or "").strip()
    if background:
        # Character cut out over a background: keep both in the render.
        refs.append(_hosted_image(background))
        prompt += "The character stands in front of the background in <IMAGE_2>, exactly as layered. "
    return _enqueue_card_image(prompt + FINISH_KEEP, refs, "2:3")


@bp.route("/studios/trading-cards/pose-sheet", methods=["POST"])
@login_required
def pose_sheet():
    """Six poses and backgrounds of this character on one 3×2 preview sheet (handoff 1.4a)."""
    data = request.get_json(silent=True) or {}
    character = (data.get("character") or "").strip()
    if not character:
        return jsonify({"ok": False, "error": "Drop a character on the card first."}), 400
    scene = (data.get("scene") or "").strip()[:80]
    # The character's description: the builder description (story, films) + the card bio.
    name = (data.get("name") or "").strip()[:40]
    details = [(data.get("details") or "").strip()[:400]]
    if data.get("characterId"):
        import app as app_mod

        try:
            rows = (
                app_mod.supabase.table("characters")
                .select("name,prompt")
                .eq("id", data.get("characterId"))
                .eq("user_id", current_user.id)
                .limit(1)
                .execute()
                .data
            )
            row = (rows or [{}])[0]
            name = name or row.get("name") or ""
            details.insert(0, str(row.get("prompt") or "").strip()[:500])
        except Exception:
            log.exception("pose sheet: character lookup failed")
    description = ". ".join(d for d in details if d)
    refs = [_hosted_image(character)]
    template = POSE_SHEET_PROMPT
    previous = (data.get("previous") or "").strip()
    if previous:
        # "Six more": Nick's second prompt, with the old sheet as image2 (charged again).
        if not SIX_MORE_PROMPT:
            return jsonify({"ok": False, "error": "Six more isn't set up yet."}), 400
        refs.append(_hosted_image(previous))
        change = (data.get("change") or "").strip()[:120]
        # Nick's prompt already says "more"; a typed "more tanks" must not become "more more tanks".
        change = re.sub(r"^\s*more\s+", "", change, flags=re.IGNORECASE)
        prompt = SIX_MORE_PROMPT.replace(
            " (Make the next six more {x})", f" (Make the next six more {change})" if change else ""
        )
        return _enqueue_card_image(prompt, refs, "1:1", exact=True)
    # The AI brain (Gemini when GEMINI_API_KEY is set) reads the photos and fills the theme +
    # description slots so they fit who the character is. Nick's prompt text is untouched.
    scene, description = _fill_pose_slots(template, name, scene, description, refs[:1])
    prompt = (
        template.replace("{x }", f"{scene} " if scene else "")
        .replace(", {z}", f", {description}" if description else "")
        .replace("{y}", name)
    )
    return _enqueue_card_image(prompt, refs, "1:1", exact=True)


@bp.route("/studios/trading-cards/report", methods=["POST"])
@login_required
def report_sheet():
    """Report a problem with a six-pose sheet: kept in Supabase + the support inbox."""
    import app as app_mod

    data = request.get_json(silent=True) or {}
    sheet = (data.get("sheet") or "").strip()[:600]
    note = (data.get("note") or "").strip()[:1000]
    if not sheet:
        return jsonify({"ok": False, "error": "Nothing to report."}), 400
    try:
        app_mod.supabase.table("card_reports").insert({
            "user_id": current_user.id, "sheet_url": sheet, "note": note,
        }).execute()
    except Exception:
        log.exception("card report insert failed")
        return jsonify({"ok": False, "error": "Could not send the report. Try again."}), 500
    try:
        from support_escalations import record_escalation

        record_escalation(
            customer_message=note or "(no note)",
            bug_summary=f"Card Studio six poses reported: {sheet}",
            user_id=current_user.id,
        )
    except Exception:
        log.exception("card report escalation failed")
    return jsonify({"ok": True})


@bp.route("/studios/trading-cards/pose-pick", methods=["POST"])
@login_required
def pose_pick():
    """Re-render the picked panel as one full-resolution 2:3 image; the crop is only a reference."""
    import app as app_mod

    data = request.get_json(silent=True) or {}
    character = (data.get("character") or "").strip()
    sheet = (data.get("sheet") or "").strip()
    try:
        x, y = float(data.get("x")), float(data.get("y"))
    except (TypeError, ValueError):
        x = y = -1.0
    if not character or not (0 <= x <= 1 and 0 <= y <= 1):
        return jsonify({"ok": False, "error": "Tap one of the six poses."}), 400
    # Only our own storage: this URL is fetched server-side.
    if not sheet.startswith(f"{app_mod.SUPABASE_URL}/storage/"):
        return jsonify({"ok": False, "error": "Show the six poses again, then pick one."}), 400
    im = _open_art(sheet)
    if im is None:
        return jsonify({"ok": False, "error": "Could not load the pose sheet."}), 400
    w, h = im.size
    cols, rows = _sheet_layout(im)
    col, row = min(cols - 1, int(x * cols)), min(rows - 1, int(y * rows))
    cell = im.convert("RGB").crop((col * w // cols, row * h // rows, (col + 1) * w // cols, (row + 1) * h // rows))
    buf = io.BytesIO()
    cell.save(buf, "JPEG", quality=92)
    crop_url = app_mod._persist_image_bytes(buf.getvalue(), ext="jpg", content_type="image/jpeg")
    return _enqueue_card_image(POSE_PICK_PROMPT, [_hosted_image(character), crop_url], "2:3")


def _sheet_layout(im: Image.Image) -> tuple:
    """(cols, rows) of a six-pose sheet. The AI returns 3×2 or 2×3; read it from where the panel seams are."""
    import numpy as np

    g = np.asarray(im.convert("L"), dtype=np.float32)
    col_diff = np.abs(np.diff(g, axis=1)).mean(axis=0)
    row_diff = np.abs(np.diff(g, axis=0)).mean(axis=1)

    def seam(d, frac):
        c, r = int(frac * len(d)), max(2, len(d) // 100)
        return float(d[max(0, c - r): c + r].max())

    three_by_two = (seam(col_diff, 1 / 3) + seam(col_diff, 2 / 3)) / 2 + seam(row_diff, 1 / 2)
    two_by_three = seam(col_diff, 1 / 2) + (seam(row_diff, 1 / 3) + seam(row_diff, 2 / 3)) / 2
    return (3, 2) if three_by_two >= two_by_three else (2, 3)


def _enqueue_card_image(prompt: str, refs: list, aspect: str, exact: bool = False):
    """Photos "image" job from the card page: same charge (1 + 1 per reference), lands in the Library.

    exact: Nick's own prompt; nothing is added to it (no reference line, no proportions guard).
    """
    import app as app_mod
    from credit_wallet import credit_balance, photo_generate_cost
    from studio_enqueue import enqueue

    if exact:
        refs, full_prompt = [r for r in app_mod._rehost_ref_slots(refs) if r], prompt
    else:
        refs, full_prompt = app_mod._align_photo_prompt_and_refs(prompt, app_mod._rehost_ref_slots(refs))
    app_mod.reset_daily_if_needed(current_user.id)
    u = (
        app_mod.supabase.table("users")
        .select("picture_credits,video_credits,images_today,is_admin")
        .eq("id", current_user.id)
        .single()
        .execute()
        .data
        or {}
    )
    cost = photo_generate_cost(len(refs))
    bal = credit_balance(u)
    if not current_user.is_admin and bal < cost:
        return jsonify({"ok": False, "error": f"Needs {cost} credits — you have {bal}.", "needed": cost}), 402
    payload = {
        "full_prompt": full_prompt,
        "source_image": refs[0] if refs else None,
        "source_images": refs,
        "cost": cost,
        "is_admin": bool(current_user.is_admin),
        "aspect_ratio": aspect,
        "split_n": 0,
        "exact_prompt": exact,
    }
    job_id = enqueue(app_mod.studio_jobs, int(current_user.id), "image", payload)
    return jsonify({"ok": True, "job_id": job_id, "cost": cost, "more": bool(SIX_MORE_PROMPT)})


@bp.route("/studios/trading-cards/forge", methods=["POST"])
@login_required
def forge():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    role = data.get("role") if data.get("role") in STAT_KEYS else "men"
    theme = (data.get("theme") or "H")[:1]
    rarity = data.get("rarity") if data.get("rarity") in ("R", "S", "G") else "R"
    name = (data.get("name") or "").strip()[:28]
    number = int(data.get("number") or 0)
    ref = data.get("referenceImage")
    restyle = bool(data.get("restyle")) and bool(ref)
    if len(prompt) < 3 and not ref:
        return jsonify({"ok": False, "error": "Give the press a prompt or a portrait."}), 400
    spec = _write_plate_spec(prompt, role, theme, rarity, name)
    spec["number"] = number
    art_data_url = None
    art_error = None
    try:
        art_data_url = _imagine_portrait(spec.get("artPrompt") or prompt, ref if restyle else None)
    except Exception as exc:
        art_error = f"Portrait press failed ({exc}). Plate still stamped."
    return jsonify({"ok": True, "spec": spec, "artDataUrl": art_data_url, "artError": art_error})


@bp.route("/studios/trading-cards/save", methods=["POST"])
@login_required
def save():
    import app as app_mod

    data = request.get_json(silent=True) or {}
    card = data.get("card") or {}
    char_id = card.get("characterId") or card.get("character_id") or card.get("char_id")
    if not card.get("name") or not (card.get("artUrl") or card.get("art_url")):
        return jsonify({"ok": False, "error": "Name it and drop a character first."}), 400
    if not char_id and current_user.is_admin:
        # Admin quick card (stocking the shop): make the character from the card art, no build step.
        art = card.get("artUrl") or card.get("art_url") or ""
        if art.startswith("data:"):
            art = _hosted_image(art)
            card["artUrl"] = art
        gender = {"women": "female", "men": "male"}.get(str(card.get("role") or ""), "")
        try:
            row = app_mod.supabase.table("characters").insert({
                "user_id": current_user.id,
                "name": str(card.get("name"))[:80],
                "gender": gender,
                "images": [art],
                "primary_image_url": art,
                "spin_video_url": None,
                "prompt": "",
                "source_mode": "admin_quick_card",
            }).execute()
            char_id = (row.data or [{}])[0].get("id")
        except Exception:
            log.exception("admin quick card: character insert failed")
        if not char_id:
            return jsonify({"ok": False, "error": "Could not create the character for this card."}), 500
        card["characterId"] = char_id
    if not char_id:
        return jsonify({"ok": False, "error": "Build a character first, then tap the card to pick them."}), 400
    card["id"] = card.get("id") or str(uuid.uuid4())
    card["serial"] = serial_of(card)
    card["craftedBy"] = _crafted_by()  # set by the server, never trusted from the page
    # Keep the saved plate small: host pasted images instead of storing data URLs.
    for key in ("artUrl", "charUrl", "customBackdrop"):
        if str(card.get(key) or "").startswith("data:"):
            card[key] = _hosted_image(card[key])
    # The saved card is the exact picture the creator sees on the page (captured in the browser).
    # The server stamp is only a fallback: it uses different fonts and looks different.
    front = None
    shot = str(data.get("frontPng") or "")
    if shot.startswith("data:image/png;base64,"):
        try:
            import base64

            front = app_mod._persist_image_bytes(base64.b64decode(shot.split(",", 1)[1]), ext="png", content_type="image/png")
        except Exception:
            log.exception("card save: page capture upload failed")
    if not front:
        try:
            front = app_mod._persist_image_bytes(stamp_jpeg(card, "front"), ext="jpg", content_type="image/jpeg")
        except Exception:
            log.exception("card save: front stamp failed; keeping the character art")
            front = card.get("artUrl")
    res = app_mod.supabase.table("characters").update({
        "card_art_url": front,
        "card_serial": card["serial"],
        "card_tagline": card.get("tagline") or "",
        "card_rarity": card.get("rarity") or "R",
        "card_theme": card.get("theme") or "H",
        "card_number": int(card.get("number") or 0),
        "card_stats": card.get("stats"),
        "card_abilities": card.get("abilities"),
        "card_plate": card,
    }).eq("id", char_id).eq("user_id", current_user.id).execute()
    if not res.data:
        return jsonify({"ok": False, "error": "Could not find that character on your account."}), 404
    card["cardUrl"] = front
    return jsonify({"ok": True, "card": card})


@bp.route("/studios/trading-cards/skills", methods=["POST"])
@login_required
def skills():
    """Skills agent: writes this character's four skills and saves them for Battle."""
    import app as app_mod

    data = request.get_json(silent=True) or {}
    char_id = data.get("characterId")
    name = (data.get("name") or "").strip()[:40]
    description = (data.get("description") or "").strip()[:600]
    gender = ""
    if char_id:
        try:
            rows = (
                app_mod.supabase.table("characters")
                .select("name,gender,prompt")
                .eq("id", char_id)
                .eq("user_id", current_user.id)
                .limit(1)
                .execute()
                .data
            )
            row = (rows or [{}])[0]
            name = name or row.get("name") or ""
            gender = row.get("gender") or ""
            description = description or str(row.get("prompt") or "")[:600]
        except Exception:
            log.exception("skills: character lookup failed")
    if not name:
        return jsonify({"ok": False, "error": "Name the character first."}), 400
    role = data.get("role") if data.get("role") in STAT_KEYS else _role_from_gender(gender)
    stats = data.get("stats") if isinstance(data.get("stats"), list) else []
    stats = stats or [{"key": k, "value": 0} for k in STAT_KEYS[role]]
    idea = (data.get("idea") or "").strip()[:300]
    write_card_skills.last_description = ""
    written, by_ai = write_card_skills(name, gender, description, stats, idea)
    if char_id and by_ai:
        try:
            app_mod.supabase.table("characters").update({"card_abilities": written}).eq("id", char_id).eq(
                "user_id", current_user.id
            ).execute()
        except Exception:
            log.exception("skills: save failed")
    return jsonify({
        "ok": True,
        "skills": written,
        "ai": by_ai,
        "description": write_card_skills.last_description if by_ai else "",
        "crafted_by": _crafted_by(),
    })


@bp.route("/studios/trading-cards/describe", methods=["POST"])
@login_required
def describe():
    """✍ AI description on the back of the card: from the character's pictures + build description."""
    import app as app_mod

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:40]
    built = ""
    pictures = []
    if data.get("characterId"):
        try:
            rows = (
                app_mod.supabase.table("characters")
                .select("name,prompt,images,primary_image_url")
                .eq("id", data.get("characterId"))
                .eq("user_id", current_user.id)
                .limit(1)
                .execute()
                .data
            )
            row = (rows or [{}])[0]
            name = name or row.get("name") or ""
            built = str(row.get("prompt") or "").strip()[:600]
            shots, _versions, _active = app_mod._split_images_field(row.get("images"))
            pictures = [u for u in [row.get("primary_image_url")] + shots if u]
        except Exception:
            log.exception("describe: character lookup failed")
    if not pictures and (data.get("image") or "").startswith("http"):
        pictures = [data["image"]]
    if not name and not built and not pictures:
        return jsonify({"ok": False, "error": "Pick a character first."}), 400
    user = f"Character: {name or 'unnamed'}\nHow they were described when built: {built or '(nothing written)'}"
    try:
        text = str(_brain_json(DESCRIBE_PROMPT, user, _writer_key(), list(dict.fromkeys(pictures))).get("description") or "")
    except Exception:
        log.exception("describe: brain failed")
        return jsonify({"ok": False, "error": "The AI couldn't write it right now. Try again."}), 502
    text = text.strip()
    if len(text) > 220:
        text = text[:220].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return jsonify({"ok": True, "description": text, "crafted_by": _crafted_by()})


def _crafted_by() -> str:
    """Who crafted the card: 'Founder' for Nick (admin), else the username."""
    return "Founder" if getattr(current_user, "is_admin", False) else (getattr(current_user, "username", "") or "a Percfect player")


@bp.route("/studios/trading-cards/roster", methods=["GET"])
@login_required
def roster():
    """Characters from the builder: the same Supabase rows the Library lists.

    Only select columns that exist on `characters` (no card_* columns yet),
    or the whole query fails and the roster comes back empty.
    """
    import app as app_mod

    def fetch(cols: str) -> list:
        q = app_mod.supabase.table("characters").select(cols).eq("user_id", current_user.id)
        one = (request.args.get("id") or "").strip()
        if one:
            q = q.eq("id", one)
        return q.order("created_at", desc=True).limit(40).execute().data or []

    try:
        try:
            rows = fetch("id,name,gender,images,primary_image_url,card_art_url,card_plate")
        except Exception:
            rows = fetch("id,name,gender,images,primary_image_url")
    except Exception:
        log.exception("card studio roster query failed")
        rows = []
    cards = []
    for c in rows:
        primary = (c.get("primary_image_url") or "").strip()
        if not primary:
            shots, _versions, _active = app_mod._split_images_field(c.get("images"))
            primary = shots[0] if shots else ""
        if not primary:
            continue
        cards.append({
            "id": c.get("id"),
            "name": c.get("name") or "Unnamed",
            "gender": c.get("gender"),
            "primary_image_url": primary,
            "card_art_url": c.get("card_art_url") or "",
            "card_plate": c.get("card_plate"),
        })
    return jsonify({"ok": True, "cards": cards})


def init_app(flask_app) -> None:
    if bp.name not in getattr(flask_app, "blueprints", {}):
        flask_app.register_blueprint(bp)
