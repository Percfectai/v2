from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g, session, Response, send_from_directory, send_file, abort
from urllib.parse import urlparse
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from supabase import create_client, Client
from functools import wraps
from typing import Optional
import os
import re
import time
import html
import json
from itsdangerous import URLSafeTimedSerializer
import math
from pathlib import Path
import base64
import urllib.parse
import uuid
import datetime
import requests
import stripe
from io import BytesIO
from PIL import Image, ImageOps
from dotenv import load_dotenv

# Princess feature removed from v2 — inline stubs prevent NameError
PRINCESS_PERCHANCE_URL = ""
PRINCESSES = {}
PRINCESS_DEFAULT_COUNT = 4
PRINCESS_DEFAULT_SIZE = "768x768"
PRINCESS_NEG_PROMPT = ""
PRINCESS_KEYS = []
def normalize_princess_key(raw): return raw.strip().lower() if raw else ""
def build_princess_prompts(key, count=4): return []
def build_princess_prompt(key, **kw): return ""

# Let Pillow decode iPhone HEIC/HEIF photos. Safe no-op if the package
# is unavailable for some reason (we still handle JPEG/PNG/WebP natively).
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

load_dotenv()

from credit_wallet import (
    CREDIT_PACKAGES,
    CREDITS_PER_TICKET,
    DAILY_FREE_TICKETS,
    IMAGE_CREDIT_COST,
    MAX_REFERENCE_PHOTOS,
    SUBSCRIPTION_PLANS,
    VIDEO_CREDITS_PER_SECOND,
    VIDEO_EXTEND_CREDITS_PER_SECOND,
    VIDEO_REF_CREDITS_PER_SECOND,
    add_credits_update,
    attach_stripe_price_ids,
    battle_ticket_cost,
    battle_ticket_win,
    battle_ticket_payout,
    battle_loss_refund,
    character_generate_cost,
    credit_balance,
    deduct_update,
    extend_video_cost,
    image_cost,
    package_line_item,
    photo_generate_cost,
    snap_extend_duration,
    snap_video_duration,
    subscription_line_item,
    topup_bonus_credits,
    video_cost,
    video_rate_for_refs,
)


def _princess_page_enabled() -> bool:
    return os.getenv("PRINCESS_PAGE_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def _princess_disabled_response():
    """503 JSON when princess features are turned off (PRINCESS_PAGE_ENABLED=0)."""
    if _princess_page_enabled():
        return None
    return jsonify({"error": "Princess generator is temporarily unavailable."}), 503


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "percfect-secret-key")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=30),
)

# Serve static files reliably under gunicorn
from whitenoise import WhiteNoise
app.wsgi_app = WhiteNoise(app.wsgi_app, root=os.path.join(os.path.dirname(__file__), 'static'), prefix='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Motion APIs: browser on percfectai.com POSTs video direct to Render.
_MOTION_CORS_ORIGINS = frozenset({
    "https://percfectai.com",
    "https://www.percfectai.com",
})


@app.after_request
def _apply_motion_cors(response):
    origin = request.headers.get("Origin", "")
    if origin in _MOTION_CORS_ORIGINS:
        path = request.path or ""
        if (
            path == "/api/motion-health"
            or path.startswith("/api/analyze-motion")
            or path.startswith("/api/motion-data")
        ):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
            response.headers["Vary"] = "Origin"
    return response


# Vendor (xAI, PoYo…) out of money / billing errors are for the owner only. Customers see a
# neutral "busy" line; admins see the raw text so they know to top up xAI.
_VENDOR_BILLING_RE = re.compile(
    r"(credits or licenses|(does not|doesn't|do not|don't) have (any|enough) credits"
    r"|spending limit|monthly limit|insufficient[_ ]quota|exceeded your current quota"
    r"|console\.x\.ai|purchase (more )?credits|team .{0,60}credits|credit balance is too low"
    r"|billing (hard )?limit|payment required|insufficient (credits|balance|funds)|HTTP 402)",
    re.IGNORECASE,
)
_VENDOR_BILLING_PUBLIC_MSG = "This tool is busy right now. Please try again in a little while. You were not charged."


def _scrub_vendor_billing(value):
    if isinstance(value, str):
        return _VENDOR_BILLING_PUBLIC_MSG if _VENDOR_BILLING_RE.search(value) else value
    if isinstance(value, list):
        return [_scrub_vendor_billing(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_vendor_billing(v) for k, v in value.items()}
    return value


@app.after_request
def _hide_vendor_billing_errors(response):
    try:
        if response.direct_passthrough or response.mimetype != "application/json":
            return response
        body = response.get_data(as_text=True)
        if len(body) > 500_000 or not _VENDOR_BILLING_RE.search(body):
            return response
        app.logger.error("Vendor billing/credits error on %s: %s", request.path, body[:500])
        if current_user.is_authenticated and getattr(current_user, "is_admin", False):
            return response
        response.set_data(json.dumps(_scrub_vendor_billing(json.loads(body))))
    except Exception:
        app.logger.exception("vendor billing scrub failed")
    return response


@app.before_request
def _motion_cors_preflight():
    if request.method != "OPTIONS":
        return None
    origin = request.headers.get("Origin", "")
    path = request.path or ""
    if origin in _MOTION_CORS_ORIGINS and (
        path == "/api/motion-health"
        or path.startswith("/api/analyze-motion")
        or path.startswith("/api/motion-data")
    ):
        return Response(status=204)
    return None


# Studios parked behind Under Construction (Nick, 2026-09-18). Delete a line to bring one back.
# Admins can still open the real page with ?preview=1.
UNDER_CONSTRUCTION = {
    "/studios/the-dome": "THE DOME",
    "/studios/dome": "THE DOME",
    "/the-dome": "THE DOME",
    "/studios/percfectmotion": "Motion",
    "/studios/motion": "Motion",
    "/3d": "3D",
    "/studios/3d": "3D",
    "/studios/3d-games": "3D",
    "/studios/3d/crew": "3D",
    "/studios/3d/field": "3D",
    "/studios/3d/rivals": "3D",
    "/studios/play/3d": "3-D",
    "/play/3d": "3-D",
    "/re-up/tickets": "Hero Tickets",
    "/re-up/settings-hub": "Settings",
}
UNDER_CONSTRUCTION_PREFIXES = {
    "/studios/play/3d/": "3-D",
}


@app.before_request
def _under_construction():
    if request.method != "GET":
        return None
    path = request.path.rstrip("/")
    product = UNDER_CONSTRUCTION.get(path) or next(
        (name for prefix, name in UNDER_CONSTRUCTION_PREFIXES.items() if path.startswith(prefix)), None
    )
    if not product:
        return None
    if request.args.get("preview") == "1" and current_user.is_authenticated and current_user.is_admin:
        return None
    return render_template("under_construction.html", product=product)

# ── Supabase ──────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

from studio_jobs import StudioJobRunner
from studio_enqueue import enqueue, async_payload
import character_shop as char_shop
studio_jobs = StudioJobRunner(supabase, app)

# /3d Generate Character (PoYo Meshy-6 multi-image) — blueprint routes under /api/3d/*
try:
    import three_d_character_gen
    three_d_character_gen.init_app(app)
except Exception as _three_d_init_err:
    try:
        app.logger.warning("three_d_character_gen init failed: %s", _three_d_init_err)
    except Exception:
        pass

_SHOP_FALLBACK = str(Path(__file__).resolve().parent / "static" / "data" / "premade_shop.json")

# ── xAI ───────────────────────────────────────────────────
XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_BASE_URL = "https://api.x.ai/v1"
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
# Demo key 1 — iframe map (Maps JavaScript + Places, HTTP referrer restriction).
GOOGLE_MAPS_IFRAME_KEY = (
    os.getenv("GOOGLE_MAPS_IFRAME_DEMO_KEY", "").strip()
    or os.getenv("GOOGLE_MAPS_IFRAME_KEY", "").strip()
    or GOOGLE_MAPS_API_KEY
)
# Demo key 2 — snap only (Street View Static API, server IP restriction).
GOOGLE_MAPS_SNAP_KEY = (
    os.getenv("GOOGLE_MAPS_SNAP_DEMO_KEY", "").strip()
    or os.getenv("GOOGLE_MAPS_SNAP_KEY", "").strip()
)
FAL_KEY = os.getenv("FAL_KEY")
FAL_MODEL = "fal-ai/flux/schnell"

# ── Stripe (payments only — no product prompt junk here) ──
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# ── Percfect Characters ───────────────────────────────────
# **NO ONE TOUCHES THE PROMPTS WITHOUT NICK'S PASSWORD.**
# Agents do not edit CHARACTER_* prompts or build_character_prompt. Nick only.
# Prompt text only — square 1:1 is API aspect_ratio + letterbox in studio_task_handlers.
# Nick's prompt, word for word (2026-10-02). Photo: this prompt only, typed
# words ignored. No photo: their words, then this prompt.
CHARACTER_PROMPT = (
    "Ultra realistic 3D animation. "
    "On a clean white background show this exact replicated  Character's identical "
    "portrait, of a masterpiece, relaxed, straightforward pose., with that particular "
    "characters, default, facial expression. head to toe Image filling the frame in a  "
    "highly detailed, 8K, iconic depiction."
)

# ── Princess generator (kept far from Stripe; not mixed into checkout) ──
GUEST_PRINCESS_DAILY_LIMIT = 5

PRINCESS_CHARACTERS = {
    "ariel": "Ariel-inspired mermaid princess, flowing vibrant red hair, seashell crown, ocean sparkle",
    "belle": "Belle-inspired princess, golden ball gown, warm brown hair, elegant and bookish charm",
    "jasmine": "Jasmine-inspired princess, teal outfit, long black hair, Arabian palace aesthetic",
    "rapunzel": "Rapunzel-inspired princess, impossibly long golden braid, purple dress, lantern glow",
    "elsa": "Elsa-inspired ice queen princess, shimmering blue gown, snowflake magic, platinum braid",
    "aurora": "Aurora-inspired sleeping beauty princess, pink flowing gown, soft rose-gold hair",
    "cinderella": "Cinderella-inspired princess, sparkling blue ball gown, glass slippers, midnight magic",
    "moana": "Moana-inspired island princess, ocean waves, bold spirit, tropical flower accents",
    "tiana": "Tiana-inspired princess, emerald green gown, New Orleans elegance, warm golden lighting",
    "mulan": "Mulan-inspired warrior princess, crimson and gold, fierce grace, cherry blossom petals",
}

PRINCESS_SCENES = {
    "castle": "inside a grand fairy tale castle ballroom with crystal chandeliers",
    "forest": "enchanted forest clearing with glowing fireflies and magical mist",
    "garden": "royal rose garden at golden hour with butterflies and soft petals",
    "ocean": "moonlit ocean shore with bioluminescent waves and starry sky",
    "ballroom": "lavish palace ballroom during a royal celebration",
    "throne": "ornate throne room with stained glass windows and velvet banners",
}

PRINCESS_STYLES = {
    "3d": "highly detailed 3D CGI render, cinematic volumetric lighting, ultra realistic skin texture, 8k masterpiece",
    "anime": "anime illustration style, vibrant colors, clean linework, studio quality shading",
    "fantasy": "epic fantasy art, painterly brushstrokes, dramatic rim lighting, storybook illustration",
    "cinematic": "cinematic portrait photography, shallow depth of field, film grain, golden hour glow",
}

# Legacy multi-ref (unused by Character page — Characters allow 1 ref only).
# Kept for Motion/other callers that may still pass multiple seed frames.
CHARACTER_MULTI_REF_PROMPT = (
    "Using the reference images (addressed as <IMAGE_1>, <IMAGE_2>, …), redraw ONE "
    "consistent character as a clean high-quality 3D animated figure on a pure white "
    "background. Full body, casual standing pose. "
    "Combine identity from the references: prefer face/identity from <IMAGE_1>, "
    "and use later <IMAGE_N> tags for additional angles, outfit, or body detail when present. "
    "Do not invent a different person. High detail, sharp lines, consistent lighting, "
    "professional video-game character select render, no text, no watermark."
)

# Super accuracy / Precision: identity from seed photo only — typed name is for
# web search only (a portrait of {name}), never injected into xAI (named IPs warp/block).
CHARACTER_SUPER_ACCURACY_PROMPT = (
    "Using the reference photo as the single source of truth, redraw this exact person "
    "or character as a clean, high-quality 3D animated figure on a pure white background. "
    "Full body, standing straight in a casual pose. Match the reference as closely as "
    "possible: same face, same hairstyle, same skin tone, same body proportions, same "
    "outfit and colors. Do not invent a different person or change the identity. "
    "High detail, sharp lines, consistent lighting, professional video-game character "
    "select render, no text, no watermark."
)

# Prompt for the 360° character-select spin video.
# Keep PG / game-select framing — plain "rotation of the character" is often moderated.
CHARACTER_SPIN_PROMPT = (
    "Product turntable video of a stylized 3D video-game character figure on a clean white "
    "studio background. Smooth slow 360-degree yaw rotation like a character select screen "
    "preview, one full revolution. Keep the same face, outfit, colors, and proportions from "
    "the reference image. No text, no watermark, no camera shake, family-friendly game art."
)

# Motion extract → Arena / library background (image-edit, same photo system as Studio).
# Prefix "Motion filled background:" is how /api/my-library tags Backgrounds.
# Multi-image: start/mid/end plate stills are passed as references.
MOTION_BG_FILL_PROMPT = (
    "Using the reference images above, re-create a complete empty background of this scene "
    "to the best of your ability. Remove people, body cutouts, and especially the dark "
    "shadows left behind — do not leave soft shadow silhouettes on the floor or walls. "
    "Fill every black hole, removed-person shape, and shadow stain so the environment looks "
    "whole and natural as if nobody was ever there. Match the camera angle, lighting, colors, "
    "and textures from the references. Full-frame empty scene, seamless floor and walls, no "
    "people, no cutout edges, no black voids, no residual shadows."
)

# Two-character action videos. Each uses both approved character images (composited
# side-by-side into one frame) plus the action prompt below, sent to the video generator.
_ACTION_BASE = (
    "The characters from the image come together in a single shared scene {bg}. "
    "{action} Smooth cinematic animation, clean natural motion, keep each "
    "character perfectly consistent in face, body, clothing and proportions, high quality "
    "3D animated style."
)

_ACTION_BASE_SOLO = (
    "The character from the image performs in a single shared scene {bg}. "
    "{action} Smooth cinematic animation, clean natural motion, keep the "
    "character perfectly consistent in face, body, clothing and proportions, high quality "
    "3D animated style."
)

# Arena background presets shown in the dropdown. `scene` is woven into the video
# prompt. Drop a matching image at static/backgrounds/<key>.jpg to turn any preset
# into a real backdrop the characters get composited onto (auto-detected at runtime).
ARENA_BACKGROUNDS = [
    {"key": "green_stage", "label": "Green Coordinate Stage", "scene": "on a glowing green wireframe coordinate grid floor (chroma-key green stage), feet planted on grid lines, plain green grid room"},
    {"key": "studio", "label": "Clean Studio",     "scene": "in a clean, softly lit photo studio"},
    {"key": "arena",  "label": "Roman Colosseum",   "scene": "inside the ancient Roman Colosseum: sand floor, weathered stone arches and tiers packed with a roaring crowd, golden late-afternoon sun, dust in the air, monumental stone architecture (not a purple CGI void, not a clean studio)"},
    {"key": "throne", "label": "Throne Room",       "scene": "in an ornate royal throne room with banners and golden pillars"},
    {"key": "neon",   "label": "Neon City",         "scene": "on a futuristic neon-lit city street at night"},
    {"key": "forest", "label": "Enchanted Forest",  "scene": "in a lush enchanted forest with sunbeams through the trees"},
    {"key": "beach",  "label": "Beach Sunset",      "scene": "on a tropical beach at golden-hour sunset"},
    {"key": "space",  "label": "Outer Space",       "scene": "in deep outer space among stars and distant nebulae"},
    {"key": "ring",   "label": "Boxing Ring",       "scene": "in a professional boxing ring under bright spotlights"},
    {"key": "highway","label": "Open Highway",       "scene": "speeding down a wide open desert highway at sunset"},
    {"key": "track",  "label": "Race Track",         "scene": "on a professional race track with grandstands and checkered flags"},
    {"key": "snow",   "label": "Snowy Mountain",     "scene": "on a snowy mountain peak with falling snow and icy wind"},
    {"key": "slope",  "label": "Ski Slope",          "scene": "on a steep snowy ski slope carving through powder"},
    {"key": "desert", "label": "Desert Dunes",       "scene": "across vast desert sand dunes at golden sunset"},
    {"key": "court",  "label": "Basketball Court",   "scene": "on an outdoor basketball court under city lights"},
    {"key": "stadium","label": "Sports Stadium",     "scene": "in a packed sports stadium under bright floodlights"},
    {"key": "field",  "label": "Sports Field",       "scene": "on a lush green sports field"},
    {"key": "tennis", "label": "Tennis Court",       "scene": "on a professional tennis court"},
    {"key": "ballroom","label": "Grand Ballroom",    "scene": "in an elegant grand ballroom with glittering chandeliers"},
    {"key": "club",   "label": "Night Club",         "scene": "in a dark nightclub with colorful lights and a dance floor"},
    {"key": "rooftop","label": "City Rooftop",       "scene": "on a city rooftop at night with the skyline glowing behind"},
]
# Battle Cards arenas (Sync chamber), kept off the Arena page's list.
_BATTLE_ARENA_BGS = [  # scene wording is Claude's; Nick may replace it
    {"key": "neon_rooftop", "label": "Neon Rooftop", "scene": "on a rain-slick rooftop high above a neon city at night, glowing signs and skyscrapers all around"},
    {"key": "throne_hall",  "label": "Throne Hall",  "scene": "in a vast stone throne hall lit by torches, banners on the pillars and a towering throne behind"},
    {"key": "storm_coast",  "label": "Storm Coast",  "scene": "on black rocks at a stormy coastline, huge waves crashing, lightning across a dark sky"},
    {"key": "ice_citadel",  "label": "Ice Citadel",  "scene": "inside a glittering ice citadel, frozen pillars and blue light, snow drifting through the air"},
    {"key": "circuit_void", "label": "Circuit Void", "scene": "in a dark digital void with glowing cyan circuit lines racing across the floor and sky"},
]
BATTLE_ARENAS = [b["key"] for b in _BATTLE_ARENA_BGS]
ARENA_BG_BY_KEY = {b["key"]: b for b in ARENA_BACKGROUNDS + _BATTLE_ARENA_BGS}
ARENA_ACTIONS_MAIN = {
    "fight":    {"label": "Fight",      "emoji": "🥊", "bg": "arena",
                 "action": "They engage in an energetic, dynamic martial-arts fight with dodging, striking and acrobatic action poses."},
    "romance":  {"label": "Romance",    "emoji": "💕", "bg": "rooftop",
                 "action": "They share a tender romantic moment, drawing close and gazing at each other with gentle affectionate movement."},
    "dance":    {"label": "Dance",      "emoji": "💃", "bg": "ballroom",
                 "action": "They dance together joyfully and in sync, with flowing, graceful, rhythmic movement."},
    # Hug is intentionally NOT a wholesome hug (product secret) — only fix spellings, keep content.
    "hug":      {"label": "Hug",        "emoji": "🤗", "bg": "studio",
                 "action": "They walk towards each other and are immediately overcome with animalistic arousal."},
    # Default / male+male High Five: just a high five (never intimate).
    "highfive": {"label": "High Five",  "emoji": "🙌", "bg": "stadium",
                 "action": "They just give each other a high five — hands meet overhead in a simple, "
                           "friendly celebratory gesture, nothing romantic or intimate."},
    "faceoff":  {"label": "Face-Off",   "emoji": "⚔️", "bg": "arena",
                 "action": "They face off in a dramatic stare-down before an epic showdown, with intense cinematic tension."},
}
# High Five heated line — M+F or F+F only (never male+male). See arena_action_prompt.
HIGHFIVE_MF_ACTION = (
    "They attack each other, unleashing their arousal in a passionate display of affection, "
    "seeming somewhat unnecessarily and explicitly overdoing it to the viewer."
)
# "More" chips — paid heat scenes (+ARENA_EXTRA_SCENE_CREDITS). NICK PRODUCT — DO NOT DELETE.
# Innocent labels; suggestive action text. Bots keep scrubbing these; put them back.
# Each has a matching default background for stage + prompt scene.
ARENA_ACTIONS_OTHER = {
    "yoga":      {"label": "Partner yoga", "emoji": "🧘", "bg": "studio",
                  "action": "They guide each other through deep partner stretches, hips pressed close, breath syncing, slow flexing holds that turn heated and breathless."},
    "netflix":   {"label": "Movie night",  "emoji": "🍿", "bg": "studio",
                  "action": "They sink into the couch together, blankets tangled, bodies gravitating closer until the screen is forgotten and only close, restless cuddling remains."},
    "sunscreen": {"label": "Beach day",    "emoji": "🏖️", "bg": "beach",
                  "action": "One offers to help with sunscreen — slow hands tracing shoulders and back, lingering strokes, playful squirming and grateful leaning into the touch."},
    "massage":   {"label": "Shoulder rub", "emoji": "💆", "bg": "studio",
                  "action": "They trade a shoulder rub that starts professional then drifts lower, firmer pressure, soft sighs, neither asking the other to stop."},
    "rain":      {"label": "Caught in rain", "emoji": "🌧️", "bg": "neon",
                  "action": "Soaked shirts clinging, they duck under an awning pressed together for warmth, foreheads close, sharing heat until the storm feels like an excuse."},
    "cooking":   {"label": "Kitchen chemistry", "emoji": "👩‍🍳", "bg": "studio",
                  "action": "They cook side by side — reaching for the same spoon, hips brushing at the counter, tasting from the same spoon, laughter turning slow and hungry."},
    "photoshoot":{"label": "Photoshoot",   "emoji": "📸", "bg": "studio",
                  "action": "A flirty photoshoot — suggestive poses, come-hither glances, one adjusting the other's outfit with hands that stay too long, chemistry obvious between shutter clicks."},
    "sleepover": {"label": "Sleepover",    "emoji": "🛏️", "bg": "studio",
                  "action": "Pillow fight escalates to wrestling on the bed, tangled limbs, breathless giggling settling into stillness face-to-face, neither rolling away."},
    "wine":      {"label": "After the wine", "emoji": "🍷", "bg": "ballroom",
                  "action": "After the wine, the female attacks the male with animalistic arousal, hypnotized and in an immensely determined state, unable to stop herself."},
    "trampoline":{"label": "Invisible trampoline", "emoji": "🤸", "bg": "stadium",
                  "action": "She bounces on the invisible trampoline on the man's lap, joyously occupied with entertainment the whole time, playful rhythmic motion that never lets up."},
}
LEWD_ACTION_KEY = "lewd"
# Arena "More" / Lewd chips — same credit surcharge on top of video_cost(seconds).
# Site is moderated via xAI; no adult-product framing in UI.
ARENA_EXTRA_SCENE_CREDITS = 15
ADULT_EXTRA_CREDITS = ARENA_EXTRA_SCENE_CREDITS  # back-compat alias
LEWD_EXTRA_CREDITS = ARENA_EXTRA_SCENE_CREDITS
ADULT_SCENE_EXTRA_CREDITS = ARENA_EXTRA_SCENE_CREDITS
LEWD_RANDOM_EXTRA_CREDITS = ARENA_EXTRA_SCENE_CREDITS
ARENA_TWO_MALE_LEWD_ACTION = (
    "The two men make contact seeming like they're about to get intimate for an ideal, cute moment, "
    "and then suddenly the more dominant character smacks the other and says, outraged, "
    "\"Do I look like I go that way?\" as the other party stands there shocked and slightly embarrassed."
)
CHARACTER_ACTIONS = {**ARENA_ACTIONS_MAIN, **ARENA_ACTIONS_OTHER}


def arena_adult_surcharge(action_key: str) -> int:
    """Credit surcharge for Arena More/Lewd chips (not an adult-store label)."""
    if not action_key:
        return 0
    k = str(action_key).strip().lower()
    if is_lewd_random_action(k) or k in ARENA_ACTIONS_OTHER:
        return int(ARENA_EXTRA_SCENE_CREDITS)
    return 0

# The Arena — curated cinematic 2-character scenarios (Combat/Sports/Dance/Racing). These keys
# resolve through character_action_prompt (below). Each has a default background key so picking
# a scene auto-suggests the right backdrop.
MOTION_SCENARIOS = {
    # ── Combat ──
    "fencing":   {"label": "Fencing Duel", "emoji": "🤺", "category": "Combat", "bg": "arena",
                  "action": "The two characters fight an intense fencing duel — advancing and retreating footwork, blades clashing, lunges, parries and quick ripostes, dramatic sword-fighting motion."},
    "boxing":    {"label": "Boxing Match", "emoji": "🥊", "category": "Combat", "bg": "ring",
                  "action": "a simple boxing fight"},
    "swordfight":{"label": "Sword Fight",  "emoji": "⚔️", "category": "Combat", "bg": "throne",
                  "action": "The two characters clash in an epic sword fight — swinging heavy blades, blocking, spinning strikes and dramatic slow-motion parries."},
    "kungfu":    {"label": "Kung-Fu",      "emoji": "🥋", "category": "Combat", "bg": "forest",
                  "action": "The two characters spar in a clean kung-fu battle — spinning kicks, blocks, sweeps and acrobatic martial-arts choreography."},
    "karate":    {"label": "Karate",       "emoji": "🥷", "category": "Combat", "bg": "studio",
                  "action": "The two characters face off in a disciplined karate match — sharp punches, high kicks, blocks and kiai stances with crisp explosive motion."},
    "wrestling": {"label": "Wrestling",    "emoji": "🤼", "category": "Combat", "bg": "ring",
                  "action": "intense wrestling match"},
    "mma":       {"label": "MMA Cage",     "emoji": "🥊", "category": "Combat", "bg": "arena",
                  "action": "intense MMA fight"},
    "lightsaber":{"label": "Lightsaber",   "emoji": "🔦", "category": "Combat", "bg": "space",
                  "action": "The two characters duel with glowing energy sabers — spinning strikes, blade locks, force-flung motion and cinematic sci-fi choreography."},
    "staff":     {"label": "Staff Fight",  "emoji": "🥢", "category": "Combat", "bg": "forest",
                  "action": "The two characters fight with long staffs — spinning twirls, blocks, sweeps and rapid strikes with martial-arts flair."},
    "standoff":  {"label": "Standoff",     "emoji": "😤", "category": "Combat", "bg": "neon",
                  "action": "The two characters hold a tense cinematic standoff — slow circling, locked eyes, dramatic wind and rising tension before an explosive clash."},
    # ── Sports ──
    "basketball":{"label": "Basketball",   "emoji": "🏀", "category": "Sports", "bg": "court",
                  "action": "The two characters play intense 1-on-1 basketball — dribbling, crossovers, jump shots, dunks and defense with athletic movement."},
    "football":  {"label": "Football",     "emoji": "🏈", "category": "Sports", "bg": "stadium",
                  "action": "The two characters play football — one charging with the ball, the other tackling, with explosive sprints, jukes and a hard hit."},
    "baseball":  {"label": "Baseball",     "emoji": "⚾", "category": "Sports", "bg": "stadium",
                  "action": "The two characters play baseball — one pitching a fast throw, the other swinging the bat and connecting with a powerful home-run hit."},
    "soccer":    {"label": "Soccer",       "emoji": "⚽", "category": "Sports", "bg": "field",
                  "action": "The two characters play soccer — dribbling, fancy footwork, a slide tackle and a powerful bicycle-kick shot on goal."},
    "tennis":    {"label": "Tennis",       "emoji": "🎾", "category": "Sports", "bg": "tennis",
                  "action": "The two characters play a fast tennis rally — sprinting, powerful serves, forehands, backhands and diving returns across the net."},
    "skiing":    {"label": "Skiing",       "emoji": "⛷️", "category": "Sports", "bg": "slope",
                  "action": "The two characters ski down a snowy slope side by side, carving fast turns, spraying powder, catching air off a jump."},
    "snowboard": {"label": "Snowboarding", "emoji": "🏂", "category": "Sports", "bg": "slope",
                  "action": "The two characters snowboard down a mountain, carving, spraying snow and launching off a jump with spinning tricks."},
    "dirtbike":  {"label": "Dirt Bikes",   "emoji": "🏍️", "category": "Sports", "bg": "desert",
                  "action": "The two characters ride dirt bikes across rough terrain, jumping dunes, kicking up dust and pulling airborne tricks."},
    "quad":      {"label": "Quad / ATV",   "emoji": "🛞", "category": "Sports", "bg": "desert",
                  "action": "The two characters race quad ATVs across dunes, drifting, jumping and throwing up sprays of sand."},
    "snowmobile":{"label": "Snowmobile",   "emoji": "🛷", "category": "Sports", "bg": "snow",
                  "action": "The two characters race snowmobiles across a snowy landscape, carving, jumping and blasting up sprays of snow."},
    "surfing":   {"label": "Surfing",      "emoji": "🏄", "category": "Sports", "bg": "beach",
                  "action": "The two characters surf a big ocean wave, carving the face, cutting back and riding through the barrel with clean motion."},
    "skate":     {"label": "Skateboarding","emoji": "🛹", "category": "Sports", "bg": "rooftop",
                  "action": "The two characters skateboard, ollieing, grinding rails and landing kickflips with dynamic street-style motion."},
    "golf":      {"label": "Golf",         "emoji": "⛳", "category": "Sports", "bg": "field",
                  "action": "The two characters play golf — winding up smooth powerful drives, following through and watching the ball soar."},
    # ── Dance ──
    "danceoff":  {"label": "Dance-Off",    "emoji": "🕺", "category": "Dance", "bg": "neon",
                  "action": "The two characters battle in a high-energy dance-off — synced then competing moves, spins, freezes and rhythmic flowing motion."},
    "tango":     {"label": "Tango",        "emoji": "💃", "category": "Dance", "bg": "ballroom",
                  "action": "The two characters dance a passionate tango — sharp dramatic steps, dips, spins and close intense partner movement."},
    "waltz":     {"label": "Ballroom Waltz","emoji": "🎩", "category": "Dance", "bg": "ballroom",
                  "action": "The two characters dance an elegant ballroom waltz — gliding, twirling and sweeping graceful partner motion."},
    "salsa":     {"label": "Salsa",        "emoji": "🌶️", "category": "Dance", "bg": "club",
                  "action": "The two characters dance energetic salsa — fast footwork, spins, dips and rhythmic hip movement."},
    "ballet":    {"label": "Ballet",       "emoji": "🩰", "category": "Dance", "bg": "studio",
                  "action": "The two characters perform graceful ballet — leaps, pirouettes, lifts and flowing elegant movement."},
    "breakdance":{"label": "Breakdance",   "emoji": "🤸", "category": "Dance", "bg": "neon",
                  "action": "The two characters break-dance battle — spins, windmills, freezes, footwork and acrobatic power moves."},
    "hiphop":    {"label": "Hip-Hop",      "emoji": "🧢", "category": "Dance", "bg": "club",
                  "action": "The two characters dance hip-hop — sharp popping, locking, grooves and synchronized street choreography."},
    "contemporary":{"label": "Contemporary","emoji": "🌀", "category": "Dance", "bg": "studio",
                  "action": "The two characters perform contemporary dance — clean expressive movement, extensions, lifts and emotional flowing motion."},
    "swing":     {"label": "Swing",        "emoji": "🎷", "category": "Dance", "bg": "ballroom",
                  "action": "The two characters dance lively swing — bouncy footwork, spins, flips and playful energetic partner motion."},
    # ── Racing ──
    "motorace":  {"label": "Motorcycle Race", "emoji": "🏍️", "category": "Racing", "bg": "highway",
                  "action": "The two characters race high-speed motorcycles side by side, leaning hard into the turns, weaving and jockeying for the lead, with motion blur, speed lines and roaring engines."},
    "carrace":   {"label": "Convertible Race", "emoji": "🏎️", "category": "Racing", "bg": "track",
                  "action": "The two characters race sleek open-top convertibles side by side, drifting around corners neck-and-neck, engines roaring, wind whipping, cinematic high-speed car-chase motion."},
}


def is_lewd_random_action(action_key: str) -> bool:
    return action_key in (LEWD_ACTION_KEY, "brandon")


def is_lustful_arena_action(action_key: str) -> bool:
    """Intimate / More / lewd-style chips (surcharge helpers + two-male slap routing)."""
    k = (action_key or "").strip().lower()
    return is_lewd_random_action(k) or k in ARENA_ACTIONS_OTHER or k in ("hug", "romance")


def is_two_male_slap_action(action_key: str) -> bool:
    """Male+male never gets heated/intimate video — they slap instead.

    High Five stays a plain high five for two males (not slap, not intimate).
    """
    k = (action_key or "").strip().lower()
    if k == "highfive":
        return False
    # Hug, romance, More chips, lewd-random → slap for M+M
    return is_lustful_arena_action(k)


def resolve_arena_action(action_key: str) -> str:
    import random
    if is_lewd_random_action(action_key):
        return random.choice(list(ARENA_ACTIONS_OTHER.keys()))
    return action_key


def _gender_word(gender: str) -> str:
    g = (gender or "").strip().lower()
    if g in ("male", "m", "man", "boy"):
        return "male"
    if g in ("female", "f", "woman", "girl"):
        return "female"
    return ""


def _is_two_male_arena_pair(rows: dict, ids: list) -> bool:
    if len(ids) != 2:
        return False
    genders = [_gender_word(rows[i].get("gender")) for i in ids if i in rows]
    return len(genders) == 2 and all(g == "male" for g in genders)


def _is_male_female_arena_pair(rows: dict, ids: list) -> bool:
    """True when exactly two characters: one male and one female."""
    if len(ids) != 2:
        return False
    genders = [_gender_word(rows[i].get("gender")) for i in ids if i in rows]
    return set(genders) == {"male", "female"}


def _is_highfive_heated_pair(rows: dict, ids: list) -> bool:
    """High Five heated line: M+F or F+F only. Never male+male."""
    if len(ids) != 2:
        return False
    genders = [_gender_word(rows[i].get("gender")) for i in ids if i in rows]
    if len(genders) != 2 or not all(genders):
        return False
    # Block male+male explicitly
    if genders[0] == "male" and genders[1] == "male":
        return False
    # Allow male+female or female+female
    return set(genders) <= {"male", "female"} and "female" in genders


def character_action_prompt(action_key: str, scene: str = None, char_count: int = 2,
                            custom_action: str = None) -> str:
    bg = scene.strip() if scene and scene.strip() else "on a clean background"
    # User-written interaction (Arena Custom)
    if (action_key or "").strip().lower() == "custom" or (custom_action and (action_key or "").strip().lower() in ("", "custom")):
        action = (custom_action or "").strip()
        if not action:
            return ""
        # Keep user direction but frame it for multi-character video
        if char_count == 1:
            if not action.lower().startswith("the character"):
                action = f"The character: {action}"
            return _ACTION_BASE_SOLO.format(action=action, bg=bg)
        if not any(action.lower().startswith(p) for p in ("the two", "they ", "the characters")):
            action = f"The characters: {action}"
        return _ACTION_BASE.format(action=action, bg=bg)

    action_key = resolve_arena_action(action_key)
    act = CHARACTER_ACTIONS.get(action_key) or MOTION_SCENARIOS.get(action_key)
    if not act:
        return ""
    action = act["action"]
    # Solo presets: rephrase dual language into singular performance.
    if char_count == 1:
        action = action.replace("The two characters", "The character").replace(
            "the two characters", "the character"
        )
        if action.startswith("They "):
            action = "The character " + action[5:]
        return _ACTION_BASE_SOLO.format(action=action, bg=bg)
    return _ACTION_BASE.format(action=action, bg=bg)


def arena_action_prompt(action_key: str, scene: str = None, *, rows: dict = None, ids: list = None,
                        custom_action: str = None) -> tuple:
    """Return (prompt, resolved_action_key). Lustful + two males uses ARENA_TWO_MALE_LEWD_ACTION.

    High Five heated line: male+female or female+female only — never male+male.
    """
    key = (action_key or "").strip().lower()
    if key == "custom":
        n = len(ids or []) or 2
        prompt = character_action_prompt("custom", scene, char_count=n, custom_action=custom_action)
        return prompt, "custom"
    bg = scene.strip() if scene and scene.strip() else "on a clean background"
    if key == "highfive" and rows and ids:
        # Male+male → plain high five only. Heated line only M+F or F+F.
        if _is_highfive_heated_pair(rows, ids):
            return _ACTION_BASE.format(action=HIGHFIVE_MF_ACTION, bg=bg), "highfive"
        # Explicit clean high five for two males (and any other non-heated pair)
        act = CHARACTER_ACTIONS.get("highfive") or {}
        clean = act.get("action") or (
            "They just give each other a high five — hands meet overhead in a simple, "
            "friendly celebratory gesture, nothing romantic or intimate."
        )
        return _ACTION_BASE.format(action=clean, bg=bg), "highfive"
    # Two guys: no intimate/hug/romance/More heat — they smack each other instead
    if is_two_male_slap_action(action_key) and rows and ids and _is_two_male_arena_pair(rows, ids):
        return _ACTION_BASE.format(action=ARENA_TWO_MALE_LEWD_ACTION, bg=bg), "two_male_lewd"
    picked = resolve_arena_action(action_key) if is_lewd_random_action(action_key) else action_key
    return character_action_prompt(picked, scene), picked


def _default_motion_profile() -> dict:
    """Normalized skeletal anchors when pose estimation is unavailable on the main app."""
    return {
        "version": 1,
        "source": "default",
        "anchor": {
            "feet_y": 0.92,
            "center_x": 0.5,
            "head_y": 0.12,
            "body_height_norm": 0.80,
        },
        "measurements": {
            "shoulder_width_norm": 0.22,
            "arm_length_norm": 0.35,
            "leg_length_norm": 0.45,
            "torso_length_norm": 0.32,
        },
        "bbox_norm": {"x_min": 0.2, "y_min": 0.08, "x_max": 0.8, "y_max": 0.96},
    }


def build_motion_profile(image_url: str = None) -> dict:
    """Build roster motion_profile anchors for character mapping / skeletal align.

    Main Render app does not ship MediaPipe — returns geometric defaults suitable for
    full-body white-card ortho shots. Analyzer motion_data.json remains the dynamic track.
    """
    profile = _default_motion_profile()
    if image_url:
        profile["source_image"] = True
    return profile


def _load_background_image(key: str):
    """Load static/backgrounds/<key>.jpg|.png if present."""
    if not key:
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        img_path = os.path.join(app.static_folder, "backgrounds", f"{key}{ext}")
        if os.path.exists(img_path):
            try:
                return Image.open(img_path)
            except Exception:
                return None
    return None


def _gender_word(gender: str) -> str:
    g = (gender or "").strip().lower()
    if g in ("male", "m", "man", "boy"):
        return "male"
    if g in ("female", "f", "woman", "girl"):
        return "female"
    return ""


# The 4 profile shots, in order. Index 0 (front) is the approved shot; the rest are
# image-edits of it so the character stays identical from every angle.
# MUST match UI labels: Front · Left side · Right side · Back (not front/back/left/right).
CHARACTER_POSES = [
    (
        "front",
        "full front view, body and face square to the camera, looking straight at the viewer",
    ),
    (
        "left",
        "strict LEFT-side orthographic profile: body turned 90 degrees, ONLY the left side "
        "of the head and body visible, face looking toward the LEFT edge of the frame "
        "(nose points left), right side of face completely hidden, pure silhouette profile "
        "not three-quarter, not facing the same way as a right profile",
    ),
    (
        "right",
        "strict RIGHT-side orthographic profile: body turned 90 degrees the OPPOSITE "
        "direction from left, ONLY the right side of the head and body visible, face "
        "looking toward the RIGHT edge of the frame (nose points right), left side of "
        "face completely hidden, pure silhouette profile not three-quarter — mirror "
        "opposite of a left profile so the two side shots face completely opposite ways",
    ),
    (
        "back",
        "full back view, turned 180 degrees facing directly away from the camera, "
        "showing the back of the head and body, face not visible",
    ),
]

# Full character pack after preview approve: 360° video first, then 4 stills snapped from video.
# Nick: 1 image credit + 1× 6s 480p video (same rate as studio video gen).
CHARACTER_SPIN_DURATION_SEC = 6


def character_pack_credit_cost() -> int:
    """Pack buy = 1 img + 6s 480p video credits (snapshots free after spin)."""
    return int(IMAGE_CREDIT_COST) + int(video_cost(CHARACTER_SPIN_DURATION_SEC))


# Legacy constant name (templates / motion pack) — always compute live
CHARACTER_PACK_CREDIT_COST = character_pack_credit_cost()  # e.g. 1+18=19 at 3 cr/s
# New look on the SAME roster entry (Version 2, 3, …) — not a separate product.
# No separate "prop" tier: any Version change is a full look at VERSION_FULL_COST.
VERSION_LIGHT_COST = 10  # legacy alias — treated as full (no prop tier)
VERSION_FULL_COST = 10   # outfit / look → Version 2+ on SAME player card
# Optional: promote active Version look to its own roster card + dedicated 360 spin
VERSION_SPLIT_COST = 30
CHARACTER_REGEN_CREDIT_COST = 1


def pose_edit_prompt(pose_desc: str) -> str:
    """Image-edit instruction for one ortho angle from the approved front still."""
    base = (
        "Show the EXACT same character — identical face, hairstyle, outfit, colors and "
        f"proportions — in a {pose_desc}. Full body, standing, plain white background, "
        "clean high-quality 3D animated style, consistent lighting, no distortion. "
        "Do not invent a different person or outfit."
    )
    low = (pose_desc or "").lower()
    if "left" in low and "right" not in low.split("left")[0]:
        base += (
            " CRITICAL: this is the LEFT profile only — character must face LEFT "
            "(nose to the left of the image). Not front, not right, not three-quarter."
        )
    elif "right" in low:
        base += (
            " CRITICAL: this is the RIGHT profile only — character must face RIGHT "
            "(nose to the right of the image), opposite of left. Not front, not left, "
            "not three-quarter."
        )
    return base


def _normalize_image_ref_tags(text: str) -> str:
    """Map user-facing ref emojis → xAI <IMAGE_N> (server-side only).

    Photos UI drops two emojis when you click a filled ref:
      📸1️⃣ → <IMAGE_1>   📸2️⃣ → <IMAGE_2>   📸3️⃣ → <IMAGE_3>
    Also accepts reverse order 1️⃣📸, plain 📸1, and legacy tags.
    """
    if not text:
        return text
    import re as _re

    out = text

    def _to_img(n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 1
        n = max(1, min(7, n))
        return f"<IMAGE_{n}>"

    # Already engine tags: leave as-is (normalize IMAGE1 → IMAGE_1)
    out = _re.sub(
        r"<\s*IMAGE\s*_?\s*(\d+)\s*>",
        lambda m: _to_img(m.group(1)),
        out,
        flags=_re.IGNORECASE,
    )

    # Camera FIRST then keycap digit — Photos click-to-ref: 📸1️⃣ 📸2️⃣ 📸3️⃣
    cam = r"[\U0001F4F7\U0001F4F8\U0001F5BC\U0001F4F9]\uFE0F?"
    keycap = r"([1-9])\uFE0F?\u20E3\uFE0F?"
    out = _re.sub(
        cam + r"[\u200D\uFE0F\s]*" + keycap,
        lambda m: _to_img(m.group(1)),
        out,
    )
    # Keycap digit FIRST then camera — 1️⃣📸  2️⃣📷  3️⃣🖼️
    out = _re.sub(
        keycap + r"[\u200D\uFE0F\s]*" + cam,
        lambda m: _to_img(m.group(1)),
        out,
    )
    # Camera + plain digit: 📸1 📸2 📸3
    out = _re.sub(
        cam + r"\s*([1-9])(?!\d)",
        lambda m: _to_img(m.group(1)),
        out,
    )
    # Plain digit + camera: 1📸 2📷
    out = _re.sub(
        r"(?<!\d)([1-9])\s*" + cam,
        lambda m: _to_img(m.group(1)),
        out,
    )
    # Bare cameras left → sequential (only if no digit paired)
    seq = [0]

    def _bare(_m):
        seq[0] += 1
        return _to_img(min(7, seq[0]))

    out = _re.sub(cam, _bare, out)
    # Legacy @Image 1 / Image_1
    out = _re.sub(
        r"@?\s*[Ii]mage[\s_]*(\d+)",
        lambda m: _to_img(m.group(1)),
        out,
    )
    return out


def user_facing_character_prompt(prompt: str) -> str:
    """Strip internal engine templates so roster/profile never show secret sauce text.

    Stored rows often have full xAI prompts ('Transform the character…'). Customers
    should only see their short description (or nothing).
    """
    import re

    p = (prompt or "").strip()
    if not p:
        return ""
    if CHARACTER_PROMPT in p:
        return p.split(CHARACTER_PROMPT)[0].strip(" .")[:280]
    # Peel common text-mode suffix: ", a male character, full body view, plain white…"
    p = re.sub(
        r",?\s*a (male|female) character\b.*$",
        "",
        p,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip(" ,")
    low = p.lower()
    engine_markers = (
        "transform the character into",
        "using the reference photo as the single source",
        "using the reference images",
        "show the exact same character",
        "create a smooth, slow-motion 360",
        "product turntable video",
        "plain white background",
        "professional video-game character",
        "3d-style illustration on a pure white",
        "full body view, casual standing pose",
        "character select render",
        "bold clean outlines, vibrant saturated",
        "high detail, sharp lines",
        "masterpiece, best quality",
    )
    # Extract "User direction…: {desc}" or "user details…: {desc}" if present
    for sep in (
        "User direction (respect any <IMAGE_N> mentions):",
        "Also apply these user details (keep identity/face consistent with the <IMAGE_N> references):",
        "User direction:",
    ):
        if sep.lower() in low:
            idx = low.find(sep.lower())
            if idx >= 0:
                tail = p[idx + len(sep) :].strip(" :")
                if tail and len(tail) < 400:
                    return tail[:280]
    if any(m in low for m in engine_markers):
        return ""
    # Short user text is fine; long boilerplates aren't
    if len(p) > 220 and ("white background" in low or "full body" in low):
        return ""
    return p[:280]


def build_character_prompt(
    description: str,
    gender: str,
    has_image: bool,
    num_refs: int = 0,
) -> str:
    """Compose the image prompt from photo(s) and/or text description.

    Gender + 1:1 are code-only (roster + API). Never in prompt text.
    """
    # Strip anything techy a power-user might paste; keep plain description
    desc = _normalize_image_ref_tags((description or "").strip())
    # After normalize, strip tags back out of the *user* description so we
    # control image roles ourselves from the ordered photo list.
    import re as _re
    user_desc = _re.sub(r"<IMAGE_\d+>", "", desc).strip()
    user_desc = _re.sub(r"\s{2,}", " ", user_desc).strip()
    n = max(0, int(num_refs or 0))
    if has_image or n > 0:
        n = max(n, 1 if has_image else 0)
        if n > 1:
            tags = " ".join(f"<IMAGE_{i}>" for i in range(1, n + 1))
            roles = []
            for i in range(1, n + 1):
                if i == 1:
                    roles.append(f"<IMAGE_{i}> = primary face and identity")
                elif i == 2:
                    roles.append(f"<IMAGE_{i}> = second angle or full body / outfit")
                else:
                    roles.append(f"<IMAGE_{i}> = additional detail or style reference")
            prompt = CHARACTER_MULTI_REF_PROMPT
            prompt += f" Reference set: {tags}. " + "; ".join(roles) + "."
        else:
            # One photo: Nick's prompt only — typed words are ignored.
            return CHARACTER_PROMPT
        if user_desc:
            prompt += (
                f" Also apply these user details (keep identity/face consistent with "
                f"the reference photos): {user_desc}"
            )
        return prompt
    # No photo: their words, then Nick's prompt.
    base = (user_desc or "a character").rstrip(" .,;")
    return f"{base}. {CHARACTER_PROMPT}"


# Super-accuracy / Precision: 5 credits — search "picture of {name}" → first usable still.
SUPER_ACCURACY_COST = 5


def _looks_like_image_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if not u.startswith("http://") and not u.startswith("https://"):
        return False
    if any(bad in u for bad in ("javascript:", "data:", " ", "\n")):
        return False
    # Prefer real image hosts / extensions; allow CDN paths without extension
    if any(ext in u.split("?")[0] for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return True
    if any(h in u for h in (
        "imgur.com", "wikimedia.org", "pinimg.com", "twimg.com", "fbcdn.net",
        "googleusercontent.com", "ggpht.com", "bing.net", "wixmp.com", "cloudfront.net",
        "cdn.", "/image", "/img", "images.",
    )):
        return True
    return False


def _is_google_cloud_api_key(key: str) -> bool:
    """Custom Search JSON API expects classic Cloud API keys (AIza…), not OAuth/AQ tokens."""
    k = (key or "").strip()
    return k.startswith("AIza") and len(k) >= 30


def _google_cse_credentials():
    """Programmable Search (CSE) key + cx. Image search only."""
    cse_key = (
        os.getenv("GOOGLE_CSE_API_KEY")
        or os.getenv("GOOGLE_PSE_API_KEY")
        or os.getenv("GOOGLE_SEARCH_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()
    cse_cx = (
        os.getenv("GOOGLE_CSE_CX")
        or os.getenv("GOOGLE_PSE_CX")
        or os.getenv("GOOGLE_CSE_ID")
        or "550adf4c7106a4ee6"
    ).strip()
    return cse_key, cse_cx


def _google_cse_image_urls(query: str, limit: int = 10) -> list:
    """Ranked Google image links for q. First item = first Google Images hit.

    Does not filter hosts — CSE searchType=image already returns image URLs.
    """
    q = (query or "").strip()
    cse_key, cse_cx = _google_cse_credentials()
    if not q or not cse_key or not cse_cx:
        if not cse_key:
            app.logger.warning("Precision: no Google CSE/PSE API key (GOOGLE_CSE_API_KEY)")
        return []
    params = {
        "key": cse_key,
        "cx": cse_cx,
        "q": q,
        "searchType": "image",
        "num": min(10, max(1, limit)),
        "safe": "off",
    }
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=20,
        )
        if r.status_code == 400 and "safe" in (r.text or "").lower():
            params.pop("safe", None)
            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=20,
            )
        if not r.ok:
            app.logger.warning(
                "Google CSE HTTP %s: %s", r.status_code, (r.text or "")[:220]
            )
            return []
        out = []
        for item in (r.json().get("items") or []):
            link = (item.get("link") or "").strip()
            if link:
                out.append(link)
                continue
            thumb = ((item.get("image") or {}).get("thumbnailLink") or "").strip()
            if thumb:
                out.append(thumb)
        if out:
            app.logger.info(
                "Precision search: Google CSE %s hits q=%r first=%s",
                len(out), q[:80], (out[0] or "")[:120],
            )
        else:
            app.logger.warning("Precision search: Google CSE 0 items q=%r", q[:80])
        return out
    except Exception as e:
        app.logger.warning("Google CSE image search failed: %s", e)
        return []


def _web_image_search_candidates(query: str, limit: int = 8) -> list:
    """Return candidate image URLs in engine rank order (first = best).

    Order: Google CSE → SerpAPI Google Images → Bing → Wikimedia.
    Do NOT re-rank hosts — first usable download is the seed (product used to work this way).
    """
    q = (query or "").strip()
    if not q:
        return []
    out = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def _push(link: str):
        if link and _looks_like_image_url(link):
            out.append(link)

    # 1) Google Custom Search (ranked) — first Google Images hit stays first
    for u in _google_cse_image_urls(q, limit=min(10, limit)):
        if u not in out:
            out.append(u)
    cse_key, _cx = _google_cse_credentials()
    if cse_key and not _is_google_cloud_api_key(cse_key) and not out:
        app.logger.warning(
            "GOOGLE_CSE_API_KEY is not AIza… Custom Search key — using Bing/Serp fallback"
        )

    # 2) SerpAPI Google Images (ranked)
    serp = (os.getenv("SERPAPI_KEY") or "").strip()
    if serp and len(out) < limit:
        try:
            r = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_images",
                    "q": q,
                    "api_key": serp,
                    "safe": "off",
                    "num": limit,
                },
                timeout=25,
            )
            if r.ok:
                for item in (r.json().get("images_results") or []):
                    _push(item.get("original") or item.get("thumbnail") or "")
                app.logger.info("Precision search: SerpAPI hits q=%r", q[:60])
        except Exception as e:
            app.logger.warning("SerpAPI image search failed: %s", e)

    # 3) Bing Images — first murls in page order (first usable download = seed)
    if len(out) < limit:
        try:
            r = requests.get(
                "https://www.bing.com/images/search",
                params={"q": q, "form": "HDRSC2", "first": 1, "tsc": "ImageBasicHover"},
                headers=headers,
                timeout=25,
            )
            if r.ok:
                found = re.findall(r"murl&quot;:&quot;(https?://[^&]+?)&quot;", r.text)
                if not found:
                    found = re.findall(r'"murl"\s*:\s*"(https?://[^"]+)"', r.text)
                if not found:
                    found = re.findall(r"murl\\u0022:\\u0022(https?://[^\\]+?)\\u0022", r.text)
                before = len(out)
                for raw in found:
                    link = html.unescape(raw.replace("\\u0026", "&").replace("\\/", "/"))
                    _push(link)
                    if len(out) >= limit * 2:
                        break
                app.logger.info(
                    "Precision search: Bing +%s murls q=%r first=%s",
                    max(0, len(out) - before),
                    q[:60],
                    (out[before] if len(out) > before else "")[:100],
                )
        except Exception as e:
            app.logger.warning("Bing image search failed: %s", e)

    # 4) Wikimedia fill
    if len(out) < limit:
        try:
            wiki_q = re.sub(
                r'^\s*(a\s+portrait\s+of|picture\s+of)\s+', "", q, flags=re.I
            ).strip().strip('"').strip("'") or q
            r = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": wiki_q[:120],
                    "gsrlimit": min(10, limit),
                    "gsrnamespace": 6,
                    "prop": "imageinfo",
                    "iiprop": "url|mime",
                    "iiurlwidth": 1024,
                },
                headers={"User-Agent": headers["User-Agent"] + " PercfectStudios/1.0"},
                timeout=20,
            )
            if r.ok:
                pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
                for page in pages.values():
                    infos = page.get("imageinfo") or []
                    if not infos:
                        continue
                    info = infos[0]
                    mime = (info.get("mime") or "").lower()
                    if mime and not mime.startswith("image/"):
                        continue
                    _push(info.get("thumburl") or info.get("url") or "")
        except Exception as e:
            app.logger.warning("Wikimedia image search failed: %s", e)

    # Deduplicate preserving first-seen order (true first result stays first)
    seen = set()
    uniq = []
    for u in out:
        key = u.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(u)
        if len(uniq) >= max(limit, 8):
            break
    if not uniq:
        app.logger.warning("Precision search: zero candidates for %r", q[:80])
    return uniq


def _rehost_web_image_bytes(data: bytes, ctype: str = "image/jpeg") -> str:
    if not ctype or not ctype.startswith("image/"):
        ctype = "image/jpeg"
    ext = "png" if "png" in ctype else ("webp" if "webp" in ctype else "jpg")
    path = f"webref/{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_("previews").upload(
        path, data,
        file_options={"content-type": ctype or "image/jpeg", "upsert": "true"},
    )
    return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"


def find_picture_of_references(user_prompt: str, max_refs: int = 5) -> list:
    """Percfect Precision seed: Google Images first hit for the product query.

    Query is always: A portrait of {character name from the prompt bar}.
    First Google Custom Search image is tried first; if that URL will not
    download, the next Google hit is used. Other engines only if Google
    returns nothing.
    """
    text = (user_prompt or "").strip()
    if not text:
        raise ValueError("Percfect Precision needs a text prompt to search for a picture.")
    text = text[:200]
    low = text.lower()
    for prefix in ("portrait of ", "a portrait of ", "picture of ", "a picture of "):
        if low.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = text[:200]
    query = f"A portrait of {text}"
    url_query = []
    seen = set()
    google_hits = _google_cse_image_urls(query, limit=10)
    for u in google_hits:
        key = u.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        url_query.append((query, u))
    if not url_query:
        for u in _web_image_search_candidates(query, limit=8):
            key = u.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            url_query.append((query, u))
    if not url_query:
        raise ValueError(
            "Could not find a web reference picture for that prompt. "
            "Try the character's real name or a short concrete description."
        )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bing.com/",
    }
    refs = []
    last_err = None
    for q, src in url_query:
        if len(refs) >= max(1, max_refs):
            break
        try:
            r = requests.get(src, timeout=25, headers=headers, stream=True)
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith("image/") and "octet-stream" not in ctype:
                continue
            data = r.content
            if not data or len(data) < 2000 or len(data) > 12 * 1024 * 1024:
                continue
            public = _rehost_web_image_bytes(data, ctype or "image/jpeg")
            refs.append({
                "url": public,
                "source_url": src,
                "search_query": q,
            })
            try:
                app.logger.info(
                    "Precision FIRST seed query=%r source=%s",
                    q[:80],
                    (src or "")[:160],
                )
            except Exception:
                pass
        except Exception as e:
            last_err = e
            continue
    if not refs:
        raise ValueError(
            f"Found search results but could not download a usable picture. "
            f"({last_err or 'try a different prompt'})"
        )
    return refs


def find_picture_of_reference(user_prompt: str) -> dict:
    """First usable web still for Super accuracy (backward-compatible helper)."""
    return find_picture_of_references(user_prompt, max_refs=1)[0]


def _load_image_any(url: str) -> Image.Image:
    """Load an image from a data: URI or an http(s) URL into a PIL image."""
    if url.startswith("data:"):
        _, b64 = url.split(",", 1)
        raw = base64.b64decode(b64)
    else:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        raw = resp.content
    return Image.open(BytesIO(raw)).convert("RGB")


def composite_characters(urls: list) -> str:
    """Place N approved character images side-by-side on a white frame and return a data URI.

    The video generator only accepts one source image, so multiple characters must share a
    single frame before they can be animated together.
    """
    target_h = 768
    frames = []
    for u in urls:
        if not u:
            continue
        im = _load_image_any(u)
        w = max(1, int(im.width * target_h / im.height))
        frames.append(im.resize((w, target_h)))
    if not frames:
        raise ValueError("No images to composite.")
    gap = 24
    total_w = sum(f.width for f in frames) + gap * (len(frames) - 1)
    canvas = Image.new("RGB", (total_w, target_h), (255, 255, 255))
    x = 0
    for f in frames:
        canvas.paste(f, (x, 0))
        x += f.width + gap
    buf = BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def composite_two_characters(url_a: str, url_b: str) -> str:
    return composite_characters([url_a, url_b])


def _key_out_white(im: Image.Image, thresh: int = 32) -> Image.Image:
    """Make the border-connected near-white background transparent via flood-fill from
    the four corners. Interior white (e.g. white clothing) is preserved, so a character
    on a white card can be dropped onto a scene without an ugly white box."""
    from PIL import ImageDraw
    im = im.convert("RGBA")
    rgb = im.convert("RGB")
    SENT = (0, 255, 1)  # sentinel colour unlikely to occur in the art
    for corner in [(0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)]:
        try:
            ImageDraw.floodfill(rgb, corner, SENT, thresh=thresh)
        except Exception:
            pass
    pr, px = rgb.load(), im.load()
    for y in range(im.height):
        for x in range(im.width):
            if pr[x, y] == SENT:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)
    return im


def _fit_cover(im: Image.Image, w: int, h: int) -> Image.Image:
    """Resize + center-crop an image to exactly cover w×h (like CSS background-size:cover)."""
    im = im.convert("RGBA")
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def composite_on_background(char_urls: list, bg_image: Image.Image) -> str:
    """Place the characters (white background keyed out) onto a scene image, standing
    side-by-side along the bottom, and return a data URI for the video generator."""
    W, H = 1024, 576
    canvas = _fit_cover(bg_image, W, H)
    char_h = int(H * 0.86)
    cut = []
    for u in char_urls:
        if not u:
            continue
        keyed = _key_out_white(_load_image_any(u))
        w = max(1, int(keyed.width * char_h / keyed.height))
        cut.append(keyed.resize((w, char_h), Image.LANCZOS))
    if not cut:
        raise ValueError("No images to composite.")
    gap = 24
    total_w = sum(c.width for c in cut) + gap * (len(cut) - 1)
    if total_w > W - 24:  # many fighters (teams): shrink them all to fit the frame
        k = (W - 24) / total_w
        cut = [c.resize((max(1, int(c.width * k)), max(1, int(c.height * k))), Image.LANCZOS) for c in cut]
        total_w = sum(c.width for c in cut) + gap * (len(cut) - 1)
    x = (W - total_w) // 2
    for c in cut:
        canvas.alpha_composite(c, (max(0, x), H - c.height))
        x += c.width + gap
    buf = BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def generate_character_shots(prompt: str, image_url: str = None, count: int = 4) -> list:
    """Generate `count` character shots (1:1 white-bg product, never warp).

    Upload/edit path: letterbox ref to square first, then multi-key parallel edits
    with force_aspect 1:1. Text path: force 1:1 on n=count then fill gaps.
    Photos studio is untouched — this helper is Characters-only.
    """
    from concurrent.futures import ThreadPoolExecutor
    from xai_keys import get_api_key, load_xai_keys, next_key

    count = max(1, int(count or 1))
    urls = []
    if image_url:
        # Pad (never stretch) so force 1:1 cannot squash a tall person
        image_url = _letterbox_url_to_square(image_url)
        pool = load_xai_keys()
        workers = max(1, min(count, len(pool) if pool else 1))

        def _one(_i):
            try:
                r = generate_image_xai(
                    prompt,
                    image_url,
                    aspect_ratio="1:1",
                    force_aspect=True,
                    api_key=next_key(),
                )
                data = (r or {}).get("data") or []
                return data[0]["url"] if data and data[0].get("url") else None
            except Exception as e:
                try:
                    app.logger.warning("generate_character_shots shot %s failed: %s", _i, e)
                except Exception:
                    pass
                return None

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for u in ex.map(_one, range(count)):
                if u:
                    urls.append(u)
    else:
        try:
            r = generate_image_xai(
                prompt, None, n=count,
                aspect_ratio="1:1", force_aspect=True, api_key=get_api_key(),
            )
            urls = [d["url"] for d in (r.get("data") or []) if d.get("url")]
        except Exception:
            urls = []
        # Parallel fill remaining slots (multi-key), not a sequential next_key loop
        need = count - len(urls)
        if need > 0:
            pool = load_xai_keys()
            workers = max(1, min(need, len(pool) if pool else 1))

            def _fill(_i):
                try:
                    r2 = generate_image_xai(
                        prompt, None, n=1,
                        aspect_ratio="1:1", force_aspect=True, api_key=next_key(),
                    )
                    return r2["data"][0]["url"]
                except Exception:
                    return None

            with ThreadPoolExecutor(max_workers=workers) as ex:
                for u in ex.map(_fill, range(need)):
                    if u:
                        urls.append(u)
    if not urls:
        raise Exception("Image generation returned no shots.")
    return urls[:count]


attach_stripe_price_ids()


def _user_credits(row) -> int:
    return credit_balance(row)


def _spend_credits(user_id, amount: int, row=None) -> bool:
    """Deduct from unified wallet. Returns False if insufficient."""
    if row is None:
        res = supabase.table("users").select("picture_credits,video_credits").eq("id", user_id).single().execute()
        row = res.data or {}
    new_vals = deduct_update(row, amount)
    if new_vals is None:
        return False
    supabase.table("users").update(new_vals).eq("id", user_id).execute()
    return True


def _grant_credits(user_id, amount: int) -> None:
    res = supabase.table("users").select("picture_credits,video_credits").eq("id", user_id).single().execute()
    row = res.data or {"picture_credits": 0, "video_credits": 0}
    supabase.table("users").update(add_credits_update(row, amount)).eq("id", user_id).execute()


def _apply_spend(user_id, row: dict, amount: int, extra: dict = None) -> bool:
    new_vals = deduct_update(row, amount)
    if new_vals is None:
        return False
    if extra:
        new_vals.update(extra)
    supabase.table("users").update(new_vals).eq("id", user_id).execute()
    return True


def _subscription_bonus_pct(user_id) -> int:
    """Top-up bonus if user has an active subscription (checked via Stripe customer)."""
    try:
        res = supabase.table("users").select("stripe_customer_id,stripe_subscription_plan").eq("id", user_id).single().execute()
        plan_key = (res.data or {}).get("stripe_subscription_plan")
        if plan_key and plan_key in SUBSCRIPTION_PLANS:
            return int(SUBSCRIPTION_PLANS[plan_key].get("topup_bonus_pct") or 0)
    except Exception:
        pass
    return 0

# ── Flask-Login ───────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.unauthorized_handler
def _unauthorized():
    """Return JSON for studio API calls instead of an HTML login redirect."""
    api_prefixes = ("/percfectstudios/", "/studios/", "/api/")
    wants_json = request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json"
    if request.path.startswith(api_prefixes) or wants_json:
        return jsonify({"error": "Log in to continue."}), 401
    return redirect(url_for("login", next=request.path))


class User(UserMixin):
    def __init__(self, data):
        self.id = data["id"]
        self.username = data["username"]
        self.picture_credits = data.get("picture_credits", 0)
        self.video_credits = data.get("video_credits", 0)
        self.images_today = data.get("images_today", 0)
        self.videos_today = data.get("videos_today", 0)
        self.last_reset = data.get("last_reset")
        self.is_admin = bool(data.get("is_admin", False))

    def get_id(self):
        return str(self.id)

    @property
    def credits(self) -> int:
        """Unified wallet total (everyone is on one credit system)."""
        return int(self.picture_credits or 0) + int(self.video_credits or 0)


@login_manager.user_loader
def load_user(user_id):
    res = supabase.table("users").select("*").eq("id", user_id).single().execute()
    if res.data:
        return User(res.data)
    return None


# ── Helpers ───────────────────────────────────────────────
def _sb_row(res) -> dict:
    """Supabase maybe_single() returns None when no row — avoid AttributeError."""
    if res is None:
        return {}
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) else {}


def reset_daily_if_needed(user_id):
    """Reset daily image/video counters. Tickets are optional (schema may lag deploy)."""
    # CRITICAL: never select tickets here — missing columns 500 every logged-in page.
    try:
        res = supabase.table("users").select(
            "last_reset,images_today,videos_today"
        ).eq("id", user_id).single().execute()
        data = res.data or {}
    except Exception as e:
        try:
            app.logger.warning("reset_daily select failed: %s", e)
        except Exception:
            pass
        data = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        last = datetime.datetime.fromisoformat(str(data["last_reset"])) if data.get("last_reset") else None
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        last = None
    if last is None or (now - last).days >= 1:
        try:
            supabase.table("users").update({
                "images_today": 0,
                "videos_today": 0,
                "last_reset": now.isoformat()
            }).eq("id", user_id).execute()
        except Exception:
            pass
    # Daily free battle tickets (2) — no-ops if tickets columns not migrated yet
    try:
        _grant_daily_free_tickets(user_id, None)
    except Exception:
        pass


def _user_tickets(row) -> int:
    try:
        return max(0, int((row or {}).get("tickets") or 0))
    except (TypeError, ValueError):
        return 0


def _grant_daily_free_tickets(user_id, row=None) -> int:
    """Give DAILY_FREE_TICKETS once per UTC day. Returns tickets after grant (or current)."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    if row is None:
        try:
            res = supabase.table("users").select("tickets,tickets_daily_at").eq("id", user_id).single().execute()
            row = res.data or {}
        except Exception:
            return 0
    last = str(row.get("tickets_daily_at") or "")[:10]
    if last == today:
        return _user_tickets(row)
    try:
        cur = _user_tickets(row)
        new = cur + int(DAILY_FREE_TICKETS)
        supabase.table("users").update({
            "tickets": new,
            "tickets_daily_at": today,
        }).eq("id", user_id).execute()
        _ticket_log(user_id, int(DAILY_FREE_TICKETS), "daily")
        return new
    except Exception as e:
        # Column may not exist until schema migration
        try:
            app.logger.warning("daily tickets grant failed (run schema tickets columns?): %s", e)
        except Exception:
            pass
        return _user_tickets(row)


def _ticket_log(user_id, delta: int, reason: str) -> None:
    """Net ticket flow per player (handoff 4.7). Never blocks the ticket change itself."""
    try:
        supabase.table("ticket_ledger").insert({
            "user_id": user_id, "delta": int(delta), "reason": (reason or "")[:60],
        }).execute()
    except Exception:
        app.logger.warning("ticket ledger insert failed for user %s", user_id)


def _spend_tickets(user_id, amount: int, row=None, reason: str = "spend") -> bool:
    amount = int(amount or 0)
    if amount <= 0:
        return True
    if row is None:
        try:
            res = supabase.table("users").select("tickets").eq("id", user_id).single().execute()
            row = res.data or {}
        except Exception:
            return False
    bal = _user_tickets(row)
    if bal < amount:
        return False
    try:
        supabase.table("users").update({"tickets": bal - amount}).eq("id", user_id).execute()
        _ticket_log(user_id, -amount, reason)
        return True
    except Exception:
        return False


def _grant_tickets(user_id, amount: int, reason: str = "grant") -> int:
    amount = int(amount or 0)
    if amount <= 0:
        return _user_tickets({})
    try:
        res = supabase.table("users").select("tickets").eq("id", user_id).single().execute()
        row = res.data or {}
        new = _user_tickets(row) + amount
        supabase.table("users").update({"tickets": new}).eq("id", user_id).execute()
        _ticket_log(user_id, amount, reason)
        return new
    except Exception:
        return 0



def _file_to_data_uri(file_storage):
    """Turn an upload into a data URI for xAI — change as little as possible.

    Always re-encoding to JPEG was quietly rewriting every reference photo
    (recompress + RGB convert), which can make refs look "different" after
    upload even when aspect was preserved.

    Policy:
      1. Pass through original bytes when already API-safe (JPEG/PNG/WebP),
         under the long-edge cap, and EXIF orientation is already upright.
      2. Only re-encode when needed: HEIC/GIF/odd formats, EXIF rotate, or
         very large photos. thumbnail() keeps aspect — never stretch.
    """
    data = file_storage.read()
    _safe_mime = {
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }
    try:
        img = Image.open(BytesIO(data))
        fmt = (getattr(img, "format", None) or "").upper()
        # EXIF Orientation tag 0x0112 — 1 (or missing) means already upright.
        orient = 1
        try:
            ex = img.getexif() if hasattr(img, "getexif") else None
            if ex:
                orient = int(ex.get(0x0112) or 1)
        except Exception:
            orient = 1
        needs_orient = orient not in (1, 0)
        w, h = img.size
        needs_downscale = max(int(w or 0), int(h or 0)) > 2048
        # Pass-through: do not touch pixels if already fine for Imagine edits.
        if (
            not needs_orient
            and not needs_downscale
            and fmt in _safe_mime
            and data
        ):
            b64 = base64.b64encode(data).decode()
            return f"data:{_safe_mime[fmt]};base64,{b64}"

        # Fix orientation (iPhone HEIC/JPEG), drop alpha, cap long edge only.
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((2048, 2048), Image.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=92, optimize=True)
        b64 = base64.b64encode(out.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        # Fall back to the raw bytes if decoding fails for any reason.
        mime = file_storage.mimetype or "image/jpeg"
        if mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            mime = "image/jpeg"
        b64 = base64.b64encode(data).decode()
        return f"data:{mime};base64,{b64}"


def _get_form_image_url():
    image_url = request.form.get("image_url", "").strip() or None
    file = request.files.get("image_file")
    if file and file.filename:
        return _file_to_data_uri(file)
    return image_url


def _get_form_reference_slots(max_n: int = None) -> list:
    """Reference images by **slot index** (0 → 📸1️⃣ / <IMAGE_1>).

    Empty slots stay None so slot 2 is still IMAGE_3 when 1 is empty.
    Accepts image_file_0…N, image_url_0…N, plus compact multi fields into
    first empty slots.
    """
    max_n = int(max_n or MAX_REFERENCE_PHOTOS)
    slots: list = [None] * max_n

    def _put(i: int, u: str) -> None:
        if i < 0 or i >= max_n or not u or slots[i]:
            return
        slots[i] = u

    for i in range(max_n):
        f = request.files.get(f"image_file_{i}")
        if f and getattr(f, "filename", None):
            try:
                _put(i, _file_to_data_uri(f))
            except Exception:
                pass
        if not slots[i]:
            u = (request.form.get(f"image_url_{i}") or "").strip()
            if u:
                _put(i, u)

    # Compact multi fields → first empty slots (legacy clients)
    extras: list = []
    multi = request.files.getlist("image_files") or request.files.getlist("image_file")
    for f in multi:
        if f and getattr(f, "filename", None):
            try:
                extras.append(_file_to_data_uri(f))
            except Exception:
                pass
    raw_list = request.form.get("image_urls") or request.form.get("source_images") or ""
    if raw_list.strip().startswith("["):
        try:
            parsed = json.loads(raw_list)
            if isinstance(parsed, list):
                for u in parsed:
                    if isinstance(u, str) and u.strip():
                        extras.append(u.strip())
        except Exception:
            pass
    else:
        for part in re.split(r"[\n,]+", raw_list):
            u = part.strip()
            if u.startswith("http") or u.startswith("data:"):
                extras.append(u)
    single = (request.form.get("image_url") or "").strip()
    if single:
        extras.append(single)
    ei = 0
    for i in range(max_n):
        if slots[i] is None and ei < len(extras):
            slots[i] = extras[ei]
            ei += 1
    return slots


def _get_form_reference_images(max_n: int = None) -> list:
    """Dense list of reference URLs (empty slots dropped). Prefer slotted helper for Photos."""
    return [u for u in _get_form_reference_slots(max_n) if u]


def _align_photo_prompt_and_refs(prompt: str, slots: list) -> tuple:
    """Match prompt <IMAGE_N> tags to dense ref list for xAI.

    Slot 0 = user 📸1️⃣. If only slots 0 and 2 are filled, dense refs are [s0, s2]
    and prompt tags are remapped: IMAGE_1 stays 1, IMAGE_3 → IMAGE_2.

    If refs exist but the prompt has no tags, inject a clear reference line so
    identity still locks (click-to-ref is optional).
    """
    import re as _re

    mapping: dict = {}
    dense: list = []
    for i, u in enumerate(slots or []):
        if not u:
            continue
        dense.append(u)
        mapping[i + 1] = len(dense)

    p = (prompt or "").strip()
    if not dense:
        return [], p

    def _repl(m):
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            return m.group(0)
        if n in mapping:
            return f"<IMAGE_{mapping[n]}>"
        # Out-of-range tag → last present ref (better than dropping identity)
        return f"<IMAGE_{len(dense)}>"

    p = _re.sub(r"<IMAGE_(\d+)>", _repl, p)
    if not _re.search(r"<IMAGE_\d+>", p):
        tags = " ".join(f"<IMAGE_{i}>" for i in range(1, len(dense) + 1))
        p = (
            f"{p}\n\nUse reference image(s) {tags} for identity, face, body and outfit. "
            "Keep the subject consistent with the reference(s)."
        )
    return dense, p


def _rehost_one_ref(u: str) -> str:
    """data: / ephemeral → public HTTPS for xAI fetch. Keep original on failure."""
    if not u:
        return u
    try:
        if str(u).startswith("data:"):
            return _persist_data_uri(u) or u
        if str(u).startswith("http"):
            if "xai-tmp" in str(u) or "imgen.x.ai" in str(u):
                return _persist_image(u)
            return u
        return u
    except Exception:
        return u


def _rehost_refs_for_job(refs: list) -> list:
    """Turn data: URIs into public HTTPS URLs before the job is queued.

    Huge base64 blobs in generation_jobs payload flake workers and xAI downloads.
    Always rehost when possible; keep original if rehost fails.
    Drops empty entries (dense list). For slot-stable lists use _rehost_ref_slots.
    """
    out = []
    for u in refs or []:
        if not u:
            continue
        out.append(_rehost_one_ref(u))
    return out


def _rehost_ref_slots(slots: list) -> list:
    """Rehost each non-empty slot; keep None holes so 📸3️⃣ still maps to slot 2."""
    out = []
    for u in slots or []:
        if not u:
            out.append(None)
        else:
            out.append(_rehost_one_ref(u))
    return out


def _user_facing_gen_error(err: str) -> str:
    """Never leak backend vendor names to the browser."""
    low = (err or "").lower()
    if any(token in low for token in ("xai", "perchance", "pollinations", "grok", "openai", "moderation", "playwright", "cloudflare")):
        return "Generation failed. Try again in a moment."
    return (err or "Generation failed.")[:240]


def _generate_princess_backend(prompt: str) -> bytes:
    """Princess image — Perchance API first, Pollinations fallback so production never 500s empty."""
    raise NotImplementedError("Princess generator removed in v2")

    try:
        return generate_one_sync(prompt, negative_prompt=PRINCESS_NEG_PROMPT)
    except Exception as perchance_err:
        app.logger.warning("Perchance generate failed, using fallback: %s", perchance_err)
        try:
            return _generate_perchance(prompt, 768, 768, PRINCESS_NEG_PROMPT)
        except Exception:
            app.logger.exception("Princess generate failed (primary + fallback)")
            raise


def _generate_perchance(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    negative_prompt: str = "",
) -> bytes:
    """Legacy Pollinations path — not used for princess batch."""
    import time
    import urllib.parse
    width = max(512, min(1536, int(width)))
    height = max(512, min(1536, int(height)))
    encoded = urllib.parse.quote(prompt, safe='')
    neg = urllib.parse.quote(negative_prompt or "", safe='')
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&nologo=true&model=flux&seed=-1&safe=false"
    )
    if neg:
        url += f"&negative={neg}"

    last_err = None
    for attempt in range(6):
        try:
            resp = requests.get(url, timeout=90)
            if resp.status_code == 429 and attempt < 5:
                time.sleep(min(8, 2 + attempt * 2))
                continue
            if resp.status_code in (502, 503, 504) and attempt < 4:
                time.sleep(2 ** min(attempt, 3))
                continue
            if not resp.ok:
                raise Exception(f"Image generation error {resp.status_code}")
            ct = (resp.headers.get("content-type") or "").lower()
            if not ct.startswith("image/"):
                raise Exception("Image generation returned non-image response")
            if len(resp.content) < 10_000:
                raise Exception("Image generation returned empty or invalid data")
            return resp.content
        except requests.RequestException as e:
            last_err = e
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise Exception(f"Image generation request failed: {e}") from e
    raise Exception(str(last_err or "Image generation failed"))


def _is_allowed_perchance_image_url(url: str) -> bool:
    """Only accept image URLs produced by Perchance / its free backends."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    allowed = (
        "user-uploads.perchance.org",
        "user.uploads.dev",
        "image.pollinations.ai",
        "image-generation.perchance.org",
        "i.pollinations.ai",
        "cdn.pollinations.ai",
    )
    return any(host == h or host.endswith("." + h) for h in allowed)


def _perchance_store_generation_for_user(
    user_id: int,
    prompt: str,
    image_bytes: bytes,
) -> dict:
    """Blur, upload, and record one generation for a specific user."""
    preview_bytes = _create_preview(image_bytes)
    uid = str(uuid.uuid4())
    original_path = f"{user_id}/{uid}_original.jpg"
    preview_path = f"{user_id}/{uid}_preview.jpg"
    preview_url = _upload_storage("previews", preview_path, preview_bytes)
    _upload_storage("originals", original_path, image_bytes)
    row = supabase.table("generations").insert({
        "user_id": user_id,
        "type": "image",
        "prompt": prompt,
        "output_url": original_path,
        "preview_url": preview_url,
        "source": "perchance",
        "unlocked": False,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()
    inserted = (row.data or [{}])[0]
    gen_id = inserted.get("id")
    if not gen_id:
        raise RuntimeError("Could not save generation to database.")
    return {"preview_url": preview_url, "generation_id": gen_id}


def _perchance_store_generation(prompt: str, image_bytes: bytes, source_url: str = "") -> dict:
    """Blur, upload, and record one Perchance generation for the current user."""
    return _perchance_store_generation_for_user(current_user.id, prompt, image_bytes)


PRINCESS_BOT_SECRET = os.getenv("PRINCESS_BOT_SECRET", "percfect-princess-bot")
PRINCESS_QUEUE_PREFIX = "princess-queue"


def _bot_secret_ok() -> bool:
    got = (
        request.headers.get("X-Princess-Bot-Secret")
        or request.form.get("bot_secret")
        or (request.get_json(silent=True) or {}).get("bot_secret")
        or ""
    )
    return got == PRINCESS_BOT_SECRET


def _queue_storage_path(job_id: str) -> str:
    return f"{PRINCESS_QUEUE_PREFIX}/{job_id}.json"


def _load_princess_job(job_id: str) -> dict | None:
    try:
        raw = supabase.storage.from_("originals").download(_queue_storage_path(job_id))
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        if isinstance(raw, (bytes, bytearray)):
            text = raw.decode("utf-8")
        else:
            text = str(raw)
        return json.loads(text)
    except Exception:
        return None


def _queue_marker_path(job_id: str, suffix: str) -> str:
    return f"{PRINCESS_QUEUE_PREFIX}/{job_id}.{suffix}.json"


def _storage_upload_new(path: str, payload: bytes) -> None:
    """Insert-only upload — Supabase RLS allows create, not upsert update."""
    supabase.storage.from_("originals").upload(
        path,
        payload,
        file_options={"content-type": "application/json"},
    )


def _save_princess_job(job: dict) -> None:
    job_id = job["id"]
    _storage_upload_new(_queue_storage_path(job_id), json.dumps(job).encode("utf-8"))


def _job_marker_exists(job_id: str, suffix: str) -> bool:
    try:
        supabase.storage.from_("originals").download(_queue_marker_path(job_id, suffix))
        return True
    except Exception:
        return False


def _write_job_marker(job_id: str, suffix: str, data: dict) -> None:
    _storage_upload_new(_queue_marker_path(job_id, suffix), json.dumps(data).encode("utf-8"))


def _discover_queue_job_ids() -> list[str]:
    try:
        entries = supabase.storage.from_("originals").list(PRINCESS_QUEUE_PREFIX) or []
        ids: list[str] = []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else ""
            if not name or not name.endswith(".json"):
                continue
            if any(name.endswith(f".{s}.json") for s in ("claimed", "done", "failed")):
                continue
            if name.count("-") >= 4 and name.endswith(".json"):
                ids.append(name[:-5])
        return list(dict.fromkeys(ids))
    except Exception:
        return []


def _list_princess_jobs() -> list[dict]:
    jobs: list[dict] = []
    for job_id in _discover_queue_job_ids():
        job = _load_princess_job(job_id)
        if job:
            jobs.append(job)
    jobs.sort(key=lambda j: j.get("created_at", ""))
    return jobs


def _job_results_for_user(user_id: int, since_iso: str) -> list[dict]:
    try:
        res = supabase.table("generations").select("id, preview_url, unlocked, created_at")\
            .eq("user_id", user_id)\
            .eq("source", "perchance")\
            .gte("created_at", since_iso)\
            .order("created_at", desc=False)\
            .execute()
        rows = res.data or []
        return [
            {"preview_url": r["preview_url"], "generation_id": r["id"]}
            for r in rows if r.get("preview_url")
        ]
    except Exception:
        return []


@app.route("/media/previews/<path:storage_path>")
def serve_preview_media(storage_path):
    """Serve blurred previews from percfectai.com (stored in Supabase)."""
    if ".." in storage_path or storage_path.startswith("/"):
        return jsonify({"error": "Invalid path."}), 400
    try:
        data = supabase.storage.from_("previews").download(storage_path)
        return Response(
            data,
            mimetype="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000"},
        )
    except Exception:
        return jsonify({"error": "Preview not found."}), 404


@app.route("/media/download/<int:gen_id>")
@login_required
def media_download(gen_id):
    """Download full-quality image from percfectai.com after unlock."""
    res = supabase.table("generations").select("*")\
        .eq("id", gen_id).eq("user_id", current_user.id)\
        .eq("source", "perchance").maybe_single().execute()
    gen = res.data
    if not gen:
        return jsonify({"error": "Generation not found."}), 404
    if not gen.get("unlocked") and not current_user.is_admin:
        return jsonify({"error": "Unlock this image first (1 credit)."}), 402
    try:
        data = supabase.storage.from_("originals").download(gen["output_url"])
        return Response(
            data,
            mimetype="image/jpeg",
            headers={
                "Content-Disposition": f'attachment; filename="percfect-{gen_id}.jpg"',
                "Cache-Control": "private, max-age=3600",
            },
        )
    except Exception:
        return jsonify({"error": "File not found."}), 404


_ENCODE_URI_SAFE = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "-_.!~*'();,/?:@&=+$#"
)


def _encode_uri(s: str) -> str:
    out: list[str] = []
    for byte in s.encode("utf-8"):
        ch = chr(byte)
        if ch in _ENCODE_URI_SAFE:
            out.append(ch)
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


def _patch_engine_generate(html: str) -> str:
    """Fix live-hosted Perchance engine: base target, result URLs, capture postMessage."""
    html = html.replace('target="_parent"', 'target="_self"', 1)
    m = re.search(r'id="preloaded-generator-data"[^>]*>([^<]+)<', html)
    if not m:
        return html
    payload = json.loads(urllib.parse.unquote(m.group(1)))
    ot = payload.get("outputTemplate", "")
    old_then = (
        '.then(url => {\n'
        '        slots[i].innerHTML = `<img src="${url}" alt="generated ${i + 1}">`;\n'
        '        try { window.parent.postMessage({ type: "percfect-studio-image", url: url }, "*"); } catch (e) {}\n'
        '      }).catch(_ => {\n'
        '        slots[i].innerHTML = `<span class="loading" style="color:red;">Error</span>`;\n'
        '      });'
    )
    new_then = (
        '.then(result => {\n'
        '        let url = (typeof result === "string") ? result : (result && (result.dataUrl || result.evaluateItem || String(result))) || "";\n'
        '        if (!url) throw new Error("No image returned");\n'
        '        slots[i].innerHTML = `<img src="${url}" alt="generated ${i + 1}">`;\n'
        '        try {\n'
        '          if (url.startsWith("data:")) window.parent.postMessage({ type: "percfect-studio-blob", data: url }, "*");\n'
        '          else window.parent.postMessage({ type: "percfect-studio-image", url: url }, "*");\n'
        '        } catch (e) {}\n'
        '      }).catch(err => {\n'
        '        slots[i].innerHTML = `<span class="loading" style="color:red;">${(err && err.message) ? err.message : "Error"}</span>`;\n'
        '      });'
    )
    if old_then in ot:
        ot = ot.replace(old_then, new_then)
    if 'typeof generateImage !== "function"' not in ot:
        ot = ot.replace(
            "async function generateAll() {\n    generateBtn.disabled = true;",
            'async function generateAll() {\n'
            '    if (typeof generateImage !== "function") {\n'
            '      alert("Studio still loading — wait a few seconds and click Generate again.");\n'
            '      return;\n'
            '    }\n'
            '    generateBtn.disabled = true;',
            1,
        )
    payload["outputTemplate"] = ot
    encoded = _encode_uri(json.dumps(payload, ensure_ascii=False))
    return html[: m.start(1)] + encoded + html[m.end(1) :]


def _serve_princess_generator():
    """Perchance engine HTML — generates in iframe; capture hooks postMessage to parent."""
    engine_path = os.path.join(app.root_path, "static", "perchance", "o3m0yoyo03.html")
    hooks_path = os.path.join(app.root_path, "static", "perchance", "capture_hooks.js")
    html = Path(engine_path).read_text(encoding="utf-8")
    html = _patch_engine_generate(html)
    hooks_js = Path(hooks_path).read_text(encoding="utf-8")
    hook_inline = "<script>\n" + hooks_js + "\n</script>"
    marker = "capture_hooks.js"
    while marker in html:
        idx = html.find(marker)
        start = html.rfind("<script", 0, idx)
        end = html.find("</script>", idx)
        if start < 0 or end < 0:
            break
        html = html[:start] + html[end + len("</script>") :]
    if "wrapGenerateImage" not in html:
        html = html.replace("</body>", hook_inline + "</body>", 1)
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.route("/studios/princess-engine")
def princess_engine():
    """Private studio engine — not linked publicly."""
    if not _princess_page_enabled():
        return redirect("/")
    return _serve_princess_generator()


def _create_preview(image_bytes: bytes) -> bytes:
    """~70% blurred preview JPEG + PERCFECT watermark for paywall."""
    from PIL import ImageDraw, ImageFont, ImageFilter
    base = Image.open(BytesIO(image_bytes)).convert("RGB")
    w, h = base.size
    radius = max(14, int(min(w, h) * 0.05))
    blurred = base.filter(ImageFilter.GaussianBlur(radius=radius))
    base = Image.blend(base, blurred, 0.7).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    label = "PERCFECT™"
    font_size = max(24, int(w * 0.06))
    font = None
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (w - tw) // 2, (h - th) // 2
    draw.text((tx + 2, ty + 2), label, fill=(0, 0, 0, 120), font=font)
    draw.text((tx, ty), label, fill=(255, 255, 255, 160), font=font)
    out_img = Image.alpha_composite(base, overlay).convert("RGB")
    out = BytesIO()
    out_img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def _site_base_url() -> str:
    """Public origin for Stripe return URLs (must be percfectai.com, not Render)."""
    env = (os.getenv("SITE_URL") or "").strip().rstrip("/")
    if env:
        return env
    try:
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
        proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
        if host and "onrender.com" not in host.lower():
            return f"{proto}://{host}".rstrip("/")
        # Direct Render hit or missing forward headers → public brand domain
        if host and "percfectai.com" in host.lower():
            return f"{proto}://{host}".rstrip("/")
    except RuntimeError:
        pass
    return "https://percfectai.com"


def _rehost_preview_url(storage_path: str) -> str:
    # Relative URL — always loads via the same host the user is on (percfectai.com).
    return f"/media/previews/{storage_path}"


def _rehost_download_url(gen_id: int) -> str:
    return f"/media/download/{gen_id}"


def _upload_storage(bucket: str, path: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Upload bytes to Supabase Storage; return rehosted URL for previews, path for originals."""
    supabase.storage.from_(bucket).upload(
        path, data,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    if bucket == "previews":
        return _rehost_preview_url(path)
    return path


def _public_image_url_for_xai(src_url: str) -> str:
    """Absolute, publicly fetchable image URL for xAI (image→video / spin / edit).

    xAI downloads the URL itself — relative /media/ paths and expired xAI temp
    links both fail mid-pack (4 angles OK in browser, 360 fails). Always prefer
    a public Supabase previews URL.
    """
    if not src_url:
        return src_url
    u = (src_url or "").strip()
    if u.startswith("data:"):
        return _persist_data_uri(u)
    # Site-relative rehost → public Supabase object URL
    if u.startswith("/media/previews/"):
        path = u.split("/media/previews/", 1)[1].split("?", 1)[0]
        if SUPABASE_URL and path:
            return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    if SUPABASE_URL and u.startswith(f"{SUPABASE_URL}/storage/v1/object/public/"):
        return u
    # Ephemeral xAI / other hosts → rehost permanently
    if "imgen.x.ai" in u or "xai-tmp" in u or u.startswith("http"):
        return _persist_image(u)
    # Last resort: absolute site URL (xAI may still fail if not public)
    if u.startswith("/"):
        try:
            return _public_base_url().rstrip("/") + u
        except Exception:
            return u
    return u


def _letterbox_image_to_square(img: "Image.Image", fill=(255, 255, 255)) -> "Image.Image":
    """Pad to 1:1 without stretching — used for Characters square product."""
    img = img.convert("RGB")
    w, h = img.size
    if w <= 0 or h <= 0 or w == h:
        return img
    side = max(w, h)
    canvas = Image.new("RGB", (side, side), fill)
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    return canvas


def _letterbox_url_to_square(src_url: str, fill=(255, 255, 255)) -> str:
    """Download image, pad to square (no stretch), rehost. Returns URL or original on fail."""
    if not src_url:
        return src_url
    try:
        if src_url.startswith("data:"):
            raw = base64.b64decode(src_url.split(",", 1)[1])
        else:
            r = requests.get(src_url, timeout=25)
            r.raise_for_status()
            raw = r.content
        img = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB")
        w, h = img.size
        if w == h:
            # Already square — just rehost (xAI URLs are ephemeral)
            return _persist_image(src_url)
        squared = _letterbox_image_to_square(img, fill=fill)
        out = BytesIO()
        squared.save(out, format="PNG", optimize=True)
        path = f"gen/{uuid.uuid4().hex}.png"
        supabase.storage.from_("previews").upload(
            path, out.getvalue(),
            file_options={"content-type": "image/png", "upsert": "true"},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    except Exception as e:
        print(f"[letterbox_square] failed for {str(src_url)[:80]}: {e}", flush=True)
        return src_url


def _persist_image(src_url: str) -> str:
    """Download a (possibly ephemeral xAI) image and rehost it permanently in the
    public Supabase 'previews' bucket, returning an ABSOLUTE public URL.

    Absolute + public matters: the stored URL must work three ways — as an <img> src
    in the browser, as a source image fed back to xAI (restyle / animate / spin all
    re-send a saved image), and it must never expire. A relative /media/ URL fails the
    xAI leg (xAI can't fetch a relative path), so we build the full public URL here.

    Idempotent for URLs already local/persisted; falls back to the original URL on any
    failure so image generation never breaks because of a storage hiccup."""
    if not src_url:
        return src_url
    # Relative site rehost → public absolute (required for 360 spin / xAI re-fetch)
    if src_url.startswith("/media/previews/"):
        path = src_url.split("/media/previews/", 1)[1].split("?", 1)[0]
        if SUPABASE_URL and path:
            return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    if src_url.startswith("data:"):
        return _persist_data_uri(src_url)
    if SUPABASE_URL and src_url.startswith(f"{SUPABASE_URL}/storage/"):
        return src_url  # already in our bucket
    try:
        # Tight timeout — hung downloads were adding tens of seconds after a fast gen
        r = requests.get(src_url, timeout=25)
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        ext = "png" if "png" in ctype else ("webp" if "webp" in ctype else "jpg")
        path = f"gen/{uuid.uuid4().hex}.{ext}"
        supabase.storage.from_("previews").upload(
            path, r.content,
            file_options={"content-type": ctype or "image/jpeg", "upsert": "true"},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    except Exception as e:
        print(f"[persist_image] failed for {src_url[:80]}: {e}", flush=True)
        return src_url


def _persist_data_uri(data_uri: str) -> str:
    """Upload a data: URI to Supabase previews — keeps job payloads small."""
    if not data_uri or not data_uri.startswith("data:"):
        return data_uri
    if SUPABASE_URL and data_uri.startswith(f"{SUPABASE_URL}/storage/"):
        return data_uri
    try:
        header, b64 = data_uri.split(",", 1)
        mime = "image/jpeg"
        if "image/" in header:
            mime = header.split("image/")[1].split(";")[0]
            mime = f"image/{mime}"
        raw = base64.b64decode(b64)
        ext = "png" if "png" in mime else ("webp" if "webp" in mime else "jpg")
        path = f"composite/{uuid.uuid4().hex}.{ext}"
        supabase.storage.from_("previews").upload(
            path, raw,
            file_options={"content-type": mime, "upsert": "true"},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    except Exception as e:
        print(f"[persist_data_uri] failed: {e}", flush=True)
        return data_uri


def _persist_video(src_url: str) -> str:
    """Download a (possibly ephemeral xAI) video and rehost it permanently in the
    public Supabase 'previews' bucket, returning an ABSOLUTE public URL — so a
    generated/arena/extended video survives past xAI's ~1-day URL expiry instead of
    silently dying. Falls back to the original URL on any failure so generation never
    breaks on a storage hiccup."""
    if not src_url:
        return src_url
    if src_url.startswith("data:") or src_url.startswith("/media/"):
        return src_url
    if SUPABASE_URL and src_url.startswith(f"{SUPABASE_URL}/storage/"):
        return src_url  # already ours
    try:
        r = requests.get(src_url, timeout=45)
        r.raise_for_status()
        path = f"vid/{uuid.uuid4().hex}.mp4"
        supabase.storage.from_("previews").upload(
            path, r.content,
            file_options={"content-type": "video/mp4", "upsert": "true"},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    except Exception as e:
        print(f"[persist_video] failed for {src_url[:80]}: {e}", flush=True)
        return src_url


def _persist_video_bytes(content: bytes, *, content_type: str = "video/mp4") -> str:
    """Upload raw video bytes to Supabase previews — for BYO extend uploads."""
    path = f"vid/{uuid.uuid4().hex}.mp4"
    supabase.storage.from_("previews").upload(
        path,
        content,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"


def _ensure_mp4_bytes(content: bytes, *, filename: str = "") -> bytes:
    """Free local remux/transcode to H.264 MP4 (ffmpeg). Never calls xAI.

    Browser trim often produces WebM; xAI extend requires real .mp4.
    """
    import shutil
    import subprocess
    import tempfile

    if not content or len(content) < 32:
        return content
    name = (filename or "").lower()
    # EBML / webm magic
    is_webm = content[:4] == b"\x1a\x45\xdf\xa3" or name.endswith(".webm") or "webm" in name
    is_mp4 = b"ftyp" in content[:64] or name.endswith(".mp4")
    if is_mp4 and not is_webm:
        return content
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return content
    try:
        with tempfile.TemporaryDirectory() as td:
            src_ext = ".webm" if is_webm else ".bin"
            src = os.path.join(td, "in" + src_ext)
            dst = os.path.join(td, "out.mp4")
            with open(src, "wb") as f:
                f.write(content)
            for cmd in (
                [ffmpeg, "-y", "-i", src, "-c", "copy", "-movflags", "+faststart", dst],
                [
                    ffmpeg, "-y", "-i", src,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-movflags", "+faststart", dst,
                ],
            ):
                try:
                    r = subprocess.run(cmd, capture_output=True, timeout=120)
                    if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 1000:
                        with open(dst, "rb") as f:
                            return f.read()
                except Exception:
                    continue
    except Exception:
        app.logger.exception("local mp4 remux failed")
    return content


def _ffmpeg_trim_mp4(content: bytes, start: float, end: float) -> bytes:
    """Cut [start, end) seconds with ffmpeg. Free, local, no xAI."""
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise Exception("Trim isn't available on this server (ffmpeg missing).")
    start = max(0.0, float(start))
    end = float(end)
    if end <= start + 0.05:
        raise Exception("End time must be after start.")
    dur = end - start
    if dur > 180:
        raise Exception("Trim window is too long.")
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.mp4")
        dst = os.path.join(td, "out.mp4")
        with open(src, "wb") as f:
            f.write(content)
        ss = f"{start:.3f}"
        t = f"{dur:.3f}"
        for cmd in (
            [ffmpeg, "-y", "-ss", ss, "-t", t, "-i", src, "-c", "copy", "-movflags", "+faststart", dst],
            [
                ffmpeg, "-y", "-ss", ss, "-t", t, "-i", src,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", dst,
            ],
        ):
            r = subprocess.run(cmd, capture_output=True, timeout=180)
            if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 1000:
                with open(dst, "rb") as f:
                    return f.read()
        err = (r.stderr or b"").decode("utf-8", "replace")[-240:]
        raise Exception(err or "Trim failed.")


def _ffmpeg_concat_mp4(parts: list) -> bytes:
    """Join MP4 clips in order. Free, local ffmpeg, no xAI."""
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise Exception("Merge isn't available on this server (ffmpeg missing).")
    if len(parts) < 2:
        raise Exception("Add at least two clips to merge.")
    if len(parts) > 16:
        raise Exception("Too many clips (max 16).")
    with tempfile.TemporaryDirectory() as td:
        lines = []
        for i, blob in enumerate(parts):
            p = os.path.join(td, f"c{i:02d}.mp4")
            with open(p, "wb") as f:
                f.write(blob)
            lines.append(f"file '{p}'")
        lst = os.path.join(td, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        dst = os.path.join(td, "out.mp4")
        for cmd in (
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", dst],
            [
                ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", lst,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-movflags", "+faststart", dst,
            ],
        ):
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 1000:
                with open(dst, "rb") as f:
                    return f.read()
        err = (r.stderr or b"").decode("utf-8", "replace")[-240:]
        raise Exception(err or "Merge failed.")


def _ffmpeg_still_jpg(content: bytes, at_sec: float) -> bytes:
    """Grab one JPEG frame at at_sec."""
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise Exception("Frame grab isn't available (ffmpeg missing).")
    at_sec = max(0.0, float(at_sec))
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.mp4")
        dst = os.path.join(td, "frame.jpg")
        with open(src, "wb") as f:
            f.write(content)
        cmd = [
            ffmpeg, "-y", "-ss", f"{at_sec:.3f}", "-i", src,
            "-frames:v", "1", "-q:v", "2", dst,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 200:
            with open(dst, "rb") as f:
                return f.read()
        raise Exception("Could not grab that frame.")


# ── Hidden prompt engine ("secret sauce") ─────────────────
# Users only see the short style label; the site invisibly wraps their prompt
# with the rich descriptor below + the base boost. Tweak this wording anytime —
# it's server-side, so customers can never see or copy it.
# Base boost on EVERY image. "mature adult proportions" pushes hard away from the
# bubbly/childlike look — characters read as grown adults, never kids.
STUDIO_BASE_BOOST = "bold clean outlines, vibrant saturated colors, dramatic cinematic lighting, mature adult proportions, highly detailed, masterpiece, best quality, 8k"
STYLE_PRESETS = {
    "GTA 5": "Grand Theft Auto V (GTA 5 / GTA V) loading-screen art style, Stephen Bliss, Rockstar Games illustration, bold black outlines, gritty stylized realism, not generic GTA, specifically GTA 5",
    "GTA V": "Grand Theft Auto V (GTA 5 / GTA V) loading-screen art style, Stephen Bliss, Rockstar Games illustration, bold black outlines, gritty stylized realism, not generic GTA, specifically GTA 5",
    "GTA": "Grand Theft Auto V (GTA 5 / GTA V) loading-screen art style, Stephen Bliss, Rockstar Games illustration, bold black outlines, gritty stylized realism, not generic GTA, specifically GTA 5",
    "Concept Art": "professional concept art, painterly detailed rendering, ArtStation trending, cinematic composition, moody",
    "3D Animation": "high-end 3D CGI animation render, realistic mature adult proportions, cinematic volumetric lighting, detailed textures, not 2D, not Pixar cartoon",
    "3D Pixar": "Pixar 3D animation style, Disney Pixar feature-film render, subsurface scattering, stylized but mature adult proportions, cinematic lighting, not 2D, not photoreal",
    "2D Animation": "2D animation feature-film style, hand-drawn 2D animated movie look, clean 2D line and paint, mature adult character design, not 3D, not anime",
    "Realistic": "hyper-realistic cinematic photograph, natural lighting, lifelike detailed skin, shallow depth of field",
    "Anime": "mature anime illustration, clean crisp linework, cel shading, adult character design",
}


def _photo_style_is_set(style: str) -> bool:
    """True when a real style chip is selected (not None / blank)."""
    s = (style or "").strip()
    if not s or s.lower() == "none":
        return False
    return s in STYLE_PRESETS or bool(s)


def _apply_style(prompt: str, style: str) -> str:
    """Wrap the user's prompt with the hidden style descriptor + base boost.
    'None' (or blank) = leave the prompt exactly as typed — no style, no boost —
    so image-to-image edits respect the source instead of getting repainted.

    Empty prompt + a style chip is allowed: we seed a generic subject line then
    append the preset (so Generate works with only a style selected).
    """
    style = (style or "").strip()
    if not style or style.lower() == "none":
        return (prompt or "").strip()
    user = (prompt or "").strip()
    if not user:
        user = "Create a striking, highly detailed image"
    parts = [user]
    desc = STYLE_PRESETS.get(style)
    if desc:
        parts.append(desc)
    parts.append(STUDIO_BASE_BOOST)
    return ", ".join(p for p in parts if p)


def _parse_split_n(raw) -> int:
    """Allowed multi-panel splits: 4, 6, or 8. Else 0 (off)."""
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return n if n in (4, 6, 8) else 0


def _apply_split_screen_prompt(prompt: str, split_n: int) -> str:
    """Photos four-way / six-way / eight-way: user words, then parenthesis.

    a woman fighting, (four-way multi panel split screen)
    """
    n = _parse_split_n(split_n)
    user = (prompt or "").strip()
    if not n:
        return user
    words = {4: "four-way", 6: "six-way", 8: "eight-way"}
    way = words[n]
    tag = f"({way} multi panel split screen)"
    low = user.lower()
    if "multi panel split screen" in low or f"{way} split screen" in low:
        return user
    if user:
        return f"{user}, {tag}"
    return tag


def generate_image_xai(
    prompt: str,
    image_url: str = None,
    n: int = 1,
    aspect_ratio: str = None,
    image_urls: list = None,
    api_key: str = None,
    force_aspect: bool = False,
    exact_prompt: bool = False,
) -> dict:
    """Generate or edit via Grok Imagine (fast path first, fail fast).

    exact_prompt: send the prompt word for word (no "preserve proportions" guard); Card Studio uses it.

    api_key: optional explicit key (thread-safe for batch multi-key parallel).
      If omitted, uses the job context / round-robin pool.

    force_aspect: Characters lock 1:1. Photos send the size-chip aspect_ratio
      on the Imagine JSON body (with or without refs). Never put the ratio in the prompt.

    Speed rules:
      - Default model ``grok-imagine-image`` only (not quality on every request).
      - Content filter / hard errors → raise immediately (do not burn 2× timeouts).
      - Next model only if this key clearly lacks that model id.
    """
    from xai_keys import get_api_key, image_model_ids
    key = (api_key or get_api_key() or "").strip()
    if not key:
        raise Exception("No xAI API key available for image generation.")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    # Size chip → xAI `aspect_ratio` JSON field (never stuffed into the prompt).
    # Characters: force_aspect=True + 1:1. Photos: send the chip, including with refs.
    ar_raw = (aspect_ratio if aspect_ratio is not None else "auto")
    ar_raw = str(ar_raw).strip().lower() or "auto"
    _ar_map = {
        "auto": "auto", "default": "auto", "none": "auto",
        "1:1": "1:1", "square": "1:1",
        "9:16": "9:16", "portrait": "9:16",
        "16:9": "16:9", "landscape": "16:9",
        "3:4": "3:4", "4:3": "4:3",
        "3:2": "3:2", "2:3": "2:3",
    }
    ar_norm = _ar_map.get(ar_raw) or (ar_raw if ":" in ar_raw else "auto")
    use_auto = ar_norm == "auto"
    if force_aspect and use_auto:
        ar_norm = "1:1"
        use_auto = False
    urls = []
    if image_urls:
        urls = [u for u in image_urls if u][:MAX_REFERENCE_PHOTOS]
    elif image_url:
        urls = [image_url]

    models = image_model_ids()
    last_err = None
    n = max(1, int(n or 1))

    def _with_aspect(payload: dict) -> dict:
        """xAI `aspect_ratio`: top-level JSON field, quoted string ("16:9", "auto").
        Per xAI's OpenAPI spec it applies to /images/generations and to MULTI-image
        edits (`images` array). A single-image edit (`image` / `image_url`) must NOT
        set it: the output shape is auto-detected from that photo (no warping).
        Never prompt text. Characters lock 1:1 via force_aspect."""
        payload.pop("aspect_ratio", None)
        if ("image" in payload or "image_url" in payload) and not force_aspect:
            return payload
        payload["aspect_ratio"] = "auto" if use_auto else ar_norm
        return payload

    def _is_model_unavailable(status: int, body: str) -> bool:
        b = (body or "").lower()
        if status == 404:
            return True
        if status not in (400, 403, 422):
            return False
        return any(
            k in b
            for k in (
                "model",
                "not found",
                "does not exist",
                "unknown model",
                "not available",
                "not supported",
                "access denied",
                "permission",
                "unauthorized",
            )
        )

    def _is_content_block(body: str) -> bool:
        b = (body or "").lower()
        return any(
            k in b
            for k in (
                "moderat",
                "safety",
                "policy",
                "nsfw",
                "rejected",
                "violat",
                "blocked",
                "content filter",
                "not allowed",
            )
        )

    for mi, model in enumerate(models):
        # Build one or more payload shapes. Image-edits: object form first, then
        # image_url field (some keys/models only accept one shape).
        attempts = []  # list of (shape_label, payload)
        if urls:
            endpoint = f"{XAI_BASE_URL}/images/edits"
            if len(urls) == 1:
                attempts.append(("single:image-obj", _with_aspect({
                    "model": model,
                    "prompt": prompt,
                    "image": {"url": urls[0], "type": "image_url"},
                })))
                attempts.append(("single:image_url", _with_aspect({
                    "model": model,
                    "prompt": prompt,
                    "image_url": urls[0],
                })))
            else:
                # Official REST API (docs.x.ai …/inference/images): multi-ref uses
                # field "images" (array, max 3), each item {url} or {file_id}.
                # Mutually exclusive with singular "image". Documented shape FIRST.
                attempts.append(("multi:images-url (documented)", _with_aspect({
                    "model": model,
                    "prompt": prompt,
                    "images": [{"url": u} for u in urls],
                })))
                # Same array field; each item also accepts image_url key (compat).
                attempts.append(("multi:images-image_url-key (compat)", _with_aspect({
                    "model": model,
                    "prompt": prompt,
                    "images": [{"image_url": u} for u in urls],
                })))
                # Pre-fix legacy: typed objects (single-edit curl style with type).
                attempts.append(("multi:images-url-typed (legacy)", _with_aspect({
                    "model": model,
                    "prompt": prompt,
                    "images": [{"url": u, "type": "image_url"} for u in urls],
                })))
                # Last resort: first ref only. Remap/strip <IMAGE_N> so no tag
                # references a missing image (same densify+remap as Photos).
                _, _p1 = _align_photo_prompt_and_refs(prompt or "", [urls[0]])
                attempts.append(("multi->single-ref fallback", _with_aspect({
                    "model": model,
                    "prompt": _p1,
                    "image": {"url": urls[0], "type": "image_url"},
                })))
        else:
            endpoint = f"{XAI_BASE_URL}/images/generations"
            attempts.append(("text-only", _with_aspect({
                "model": model,
                "prompt": prompt,
                "n": n,
            })))

        # GO-1 fail-fast: happy path ~5–15s. Never stack 70s+70s on shapes/models.
        # Text-only: 35s. Refs/edits: 45s. Multi-n: 55s. One timeout = fail (no 2nd wait).
        if n > 1 and not urls:
            timeout = 55
        elif urls:
            timeout = 45 if mi == 0 else 30
        else:
            timeout = 35 if mi == 0 else 25

        status_code = None
        body = ""
        timed_out = False
        for shape_label, payload in attempts:
            resp = None
            try:
                resp = requests.post(
                    endpoint, json=payload, headers=headers, timeout=timeout
                )
            except requests.Timeout:
                last_err = f"xAI image timeout model={model}"
                # FAIL FAST — do not try another payload shape for another full timeout
                # (that was stacking waits past 1 minute on a single photo).
                raise Exception(last_err)
            except requests.RequestException as e:
                last_err = f"xAI image network error model={model}: {e}"
                resp = None
                continue

            if resp is None:
                continue
            if resp.ok:
                try:
                    app.logger.info(
                        "xAI image payload shape succeeded: %s (model=%s, refs=%d, aspect_ratio_sent=%s)",
                        shape_label, model, len(urls), payload.get("aspect_ratio", "OMITTED"),
                    )
                except Exception:
                    pass
                return resp.json()

            status_code = resp.status_code
            body = resp.text or ""
            last_err = f"xAI image error {status_code} model={model}: {body}"

            # Content filter — fail immediately (retrying shape wastes a full gen)
            if _is_content_block(body):
                raise Exception(last_err)

            # Try next payload shape on 400/422 only (fast errors); otherwise stop
            if status_code not in (400, 422):
                break

        if timed_out and status_code is None:
            raise Exception(last_err or "xAI image timeout")

        if last_err and status_code is None:
            # network errors — only try next model if we still have one
            continue

        # multi-n not supported → stop model ladder, let batch handler parallel-fill
        if not urls and n > 1 and status_code in (400, 422):
            if _is_model_unavailable(status_code or 0, body):
                continue
            raise Exception(last_err)

        # Only fall through to next model when this key can't use *this* model id
        if _is_model_unavailable(status_code or 0, body):
            continue
        # Real API error (bad request, rate limit after, etc.) — don't stack slow retries
        raise Exception(last_err)

    raise Exception(last_err or "xAI image generation failed (no model worked).")


def generate_image_fal(prompt: str, num_images: int = 10) -> list:
    """Generate images via fal.ai FLUX Schnell. Returns list of image URLs."""
    if not FAL_KEY:
        raise Exception("FAL_KEY not configured on server")
    num_images = max(1, min(10, int(num_images)))
    headers = {"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "num_images": num_images,
        "image_size": "square",
        "num_inference_steps": 4,
        "enable_safety_checker": False,
        "output_format": "jpeg",
    }

    resp = requests.post(f"https://queue.fal.run/{FAL_MODEL}", json=payload, headers=headers, timeout=30)
    if not resp.ok:
        raise Exception(f"fal submit error {resp.status_code}: {resp.text}")

    job = resp.json()
    if job.get("status") == "COMPLETED" or job.get("images"):
        images = job.get("images") or (job.get("response") or {}).get("images") or []
        return [img["url"] for img in images if img.get("url")]

    status_url = job.get("status_url")
    result_url = job.get("response_url")
    if not status_url or not result_url:
        raise Exception("fal queue did not return status/response URLs")

    import time
    for _ in range(90):
        time.sleep(2)
        st = requests.get(status_url, headers=headers, timeout=30)
        if not st.ok:
            continue
        status = st.json().get("status")
        if status == "COMPLETED":
            result = requests.get(result_url, headers=headers, timeout=60)
            if not result.ok:
                raise Exception(f"fal result error {result.status_code}: {result.text}")
            data = result.json()
            images = data.get("images") or (data.get("response") or {}).get("images") or []
            return [img["url"] for img in images if img.get("url")]
        if status in ("FAILED", "CANCELLED"):
            raise Exception(f"fal generation {status.lower()}")
    raise Exception("fal generation timed out")


class XaiVideoPending(Exception):
    """A video job timed out on our side but is (probably) still rendering on xAI.

    Carries the xAI job id + API key so the job can be recorded as `video_pending`
    in `generations` and reclaimed later by `_reclaim_pending_videos` — instead of
    the finished video being lost on xAI's side forever."""

    def __init__(self, job_id: str, key: str, message: str):
        super().__init__(message)
        self.job_id = job_id
        self.key = key


# Inline studio workers set this so xAI poll can write live progress onto the job.
try:
    from contextvars import ContextVar
    _video_job_progress_cb: "ContextVar" = ContextVar("video_job_progress_cb", default=None)
except Exception:  # pragma: no cover
    _video_job_progress_cb = None  # type: ignore


def _extract_video_url(result: dict) -> str:
    """xAI video responses have shipped 3 shapes — check them all."""
    return (
        (result.get("video") or {}).get("url")
        or result.get("url")
        or (result.get("data") or [{}])[0].get("url")
        or ""
    )


def _record_pending_video(user_id: int, prompt: str, job_id: str, key: str, cost: int = 0) -> None:
    """Save a timed-out-but-still-rendering xAI video job so the Library reclaim
    sweep can finish it later. Row is type=video_pending; output_url packs the
    xAI job id, key tail (to re-poll with the same key), and unpaid cost."""
    tail = (key or "")[-8:]
    supabase.table("generations").insert({
        "user_id": user_id,
        "type": "video_pending",
        "prompt": prompt or "",
        "output_url": f"xai-job://{job_id}#tail={tail}&cost={int(cost or 0)}",
        "created_at": datetime.datetime.utcnow().isoformat(),
    }).execute()


def _reclaim_pending_videos(user_id: int) -> int:
    """One-shot reconcile of this user's `video_pending` rows against xAI.

    For each pending row: re-poll the xAI job once with the same key; if the video
    finished, persist it to Supabase storage and flip the row to a real `video`
    (best-effort charging the recorded cost); if xAI reports failure, mark the row
    failed. Still-rendering rows are left alone. Returns how many were recovered.
    Called from the Library endpoints — cheap (one GET per pending row) and safe
    (every failure path just leaves the row for the next sweep)."""
    from xai_keys import load_xai_keys

    recovered = 0
    try:
        res = (
            supabase.table("generations")
            .select("id,prompt,output_url")
            .eq("user_id", user_id)
            .eq("type", "video_pending")
            .limit(20)
            .execute()
        )
        rows = res.data or []
    except Exception:
        return 0
    if not rows:
        return 0

    keys = load_xai_keys()
    for row in rows:
        try:
            ref = row.get("output_url") or ""
            if not ref.startswith("xai-job://"):
                continue
            body, _, frag = ref[len("xai-job://"):].partition("#")
            job_id = body
            params = dict(p.split("=", 1) for p in frag.split("&") if "=" in p)
            tail = params.get("tail") or ""
            cost = int(params.get("cost") or 0)
            key = next((k for k in keys if k.endswith(tail)), None) if tail else None
            if not job_id or not key:
                continue
            poll = requests.get(
                f"{XAI_BASE_URL}/videos/{job_id}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=12,
            )
            if not poll.ok:
                continue
            result = poll.json() if poll.content else {}
            status = (result.get("status") or result.get("state") or "").lower()
            if status in ("failed", "cancelled", "canceled", "error"):
                supabase.table("generations").update(
                    {"type": "video_failed"}
                ).eq("id", row["id"]).execute()
                continue
            url = _extract_video_url(result)
            if status in ("done", "succeeded", "completed", "complete") and url:
                url = _persist_video(url)
                supabase.table("generations").update(
                    {"type": "video", "output_url": url}
                ).eq("id", row["id"]).execute()
                recovered += 1
                if cost > 0:
                    # Charge now — generation was never billed when it timed out.
                    # Best-effort: the video is delivered either way.
                    try:
                        ures = supabase.table("users").select(
                            "picture_credits,video_credits,videos_today"
                        ).eq("id", user_id).single().execute()
                        udata = ures.data or {}
                        _apply_spend(user_id, udata, cost, {
                            "videos_today": int(udata.get("videos_today") or 0) + 1,
                        })
                    except Exception:
                        app.logger.warning("reclaim: charge %s failed for user %s", cost, user_id)
            # any other status: still rendering — next sweep gets it
        except Exception as e:
            app.logger.warning("reclaim pending video row %s failed: %s", row.get("id"), e)
    return recovered


def _xai_poll_error_text(poll) -> str:
    """Best-effort extract of xAI poll error body for the user-facing message."""
    body = (getattr(poll, "text", None) or "").strip()
    try:
        data = poll.json() if getattr(poll, "content", None) else {}
    except Exception:
        data = {}
    if isinstance(data, dict):
        err_raw = (
            data.get("error")
            or data.get("message")
            or data.get("detail")
            or data.get("code")
        )
        if isinstance(err_raw, dict):
            err_txt = str(
                err_raw.get("message")
                or err_raw.get("error")
                or err_raw.get("code")
                or err_raw
            ).strip()
        else:
            err_txt = str(err_raw or "").strip()
        if err_txt:
            return err_txt
    return body[:400] if body else f"HTTP {getattr(poll, 'status_code', '?')}"


def _poll_xai_video_job(
    job_id: str,
    headers: dict,
    *,
    max_wait_sec: float = 480.0,
    label: str = "video",
    on_progress=None,
) -> dict:
    """Adaptive poll for xAI video jobs (GO-3).

    Fail FAST on terminal poll errors (HTTP 4xx/5xx with body, moderation,
    failed status) — never burn 8 minutes repeating a dead poll. That was
    Nick waiting ~2–8 min per try with no real reason on screen.

    Progress: when xAI returns progress 0–100, optional on_progress(pct, status)
    so the studio job can surface a live bar (not a fake timer).
    """
    import time

    t0 = time.time()
    last_err = ""
    first = True
    hard_fail_streak = 0
    last_progress = -1
    # Immediate first poll, then adaptive delay (never fixed 5s forever)
    while True:
        elapsed = time.time() - t0
        if elapsed >= max_wait_sec:
            break
        if not first:
            if elapsed < 20:
                delay = 1.0
            elif elapsed < 90:
                delay = 2.0
            else:
                delay = 3.0
            delay = min(delay, max(0.2, max_wait_sec - elapsed))
            time.sleep(delay)
        first = False
        try:
            # GET only needs auth — avoid Content-Type on poll (submit headers reused)
            poll_headers = {
                "Authorization": headers.get("Authorization") or headers.get("authorization") or "",
                "Accept": "application/json",
            }
            poll = requests.get(
                f"{XAI_BASE_URL}/videos/{job_id}",
                headers=poll_headers,
                timeout=12,
            )
        except requests.RequestException as e:
            last_err = f"poll network: {e}"
            hard_fail_streak = 0
            continue

        # 202 Accepted / 200 OK both carry status JSON — treat as success body
        if poll.status_code in (200, 202) or (poll.ok and poll.content):
            hard_fail_streak = 0
            result = poll.json() if poll.content else {}
            status = (result.get("status") or result.get("state") or "").lower()
            err_raw = result.get("error") or result.get("message") or result.get("detail")
            if isinstance(err_raw, dict):
                err_txt = str(err_raw.get("message") or err_raw.get("code") or err_raw)
            else:
                err_txt = str(err_raw or "").strip()

            # Live progress from xAI (0–100) — never invent from elapsed time
            try:
                prog = result.get("progress")
                if prog is not None:
                    p = float(prog)
                    if 0 < p <= 1:
                        p = p * 100.0
                    p = int(max(0, min(100, round(p))))
                    if p != last_progress and callable(on_progress):
                        last_progress = p
                        try:
                            on_progress(p, status or "pending")
                        except Exception:
                            pass
            except Exception:
                pass

            if status in ("done", "succeeded", "completed", "complete"):
                try:
                    app.logger.info(
                        "xAI %s done in %.1fs job=%s",
                        label, time.time() - t0, str(job_id)[:16],
                    )
                except Exception:
                    pass
                if callable(on_progress):
                    try:
                        on_progress(100, "done")
                    except Exception:
                        pass
                return result
            if status in ("failed", "cancelled", "canceled", "error"):
                raise Exception(f"{label} generation {status}: {err_txt or result}")
            if err_txt and status in ("", "none") and "pending" not in err_txt.lower():
                raise Exception(f"{label} generation failed: {err_txt}")
            if err_txt and any(
                k in err_txt.lower()
                for k in (
                    "moderation",
                    "moderated",
                    "rejected",
                    "safety",
                    "policy",
                    "blocked",
                    "disallowed",
                    "content",
                )
            ):
                # STOP immediately — show the reason; do not keep polling
                raise Exception(f"{label} generation failed: {err_txt}")
            # pending / processing / queued — keep waiting
            continue

        # Non-OK poll: extract body and fail fast (this was "poll HTTP 400" for 480s)
        err_body = _xai_poll_error_text(poll)
        last_err = f"poll HTTP {poll.status_code}: {err_body}"
        sc = int(poll.status_code or 0)
        low = (err_body or "").lower()
        terminal = sc in (400, 401, 403, 404, 422) or any(
            k in low
            for k in (
                "moderat",
                "rejected",
                "safety",
                "policy",
                "blocked",
                "disallowed",
                "not found",
                "invalid",
                "unauthorized",
                "forbidden",
                "content",
            )
        )
        if terminal:
            raise Exception(f"{label} generation failed: {err_body}")
        # Transient 5xx / odd codes — a few retries then fail with the body
        hard_fail_streak += 1
        if hard_fail_streak >= 3:
            raise Exception(f"{label} generation failed: {err_body}")
        continue

    # The xAI job is still rendering — it will very likely finish AFTER we stop
    # waiting. Raise a typed error carrying the job id + key so the worker can
    # record it and the Library reclaim sweep can pick the video up later,
    # instead of the finished video silently dying on xAI's side.
    key = (headers.get("Authorization") or "").replace("Bearer", "").strip()
    raise XaiVideoPending(
        job_id=str(job_id),
        key=key,
        message=(
            f"{label} generation timed out after {int(max_wait_sec)}s."
            + (f" ({last_err})" if last_err else "")
        ),
    )


def generate_video_xai(
    prompt: str,
    image_url: str = None,
    duration: int = 6,
    api_key: str = None,
    reference_images: list = None,
) -> dict:
    """Text / image-to-video / reference-to-video. GO-3 adaptive poll. Media keys only.

    Modes (xAI — never fake multi-ref):
      • 0 images → text-to-video
      • 1 image  → image-to-video (start frame via ``image``)
      • 2–4 images → reference-to-video (``reference_images`` + <IMAGE_N> in prompt)
        Cannot combine ``image`` + ``reference_images`` (xAI 400).
    """
    from xai_keys import get_api_key, video_model_ids

    key = (api_key or get_api_key() or "").strip()
    if not key:
        raise Exception("No xAI API key available for video generation.")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    # Dense list of public HTTPS URLs for refs
    ref_urls: list = []
    for u in (reference_images or []):
        if not u:
            continue
        try:
            pu = _public_image_url_for_xai(str(u).strip())
        except Exception:
            pu = str(u).strip()
        if pu and pu not in ref_urls:
            ref_urls.append(pu)
        if len(ref_urls) >= 4:
            break

    safe_image = None
    if image_url and len(ref_urls) < 2:
        # Single start-frame path only when NOT doing multi-ref
        try:
            safe_image = _public_image_url_for_xai(image_url)
        except Exception:
            safe_image = image_url
    elif len(ref_urls) == 1 and not image_url:
        # One ref, no explicit image_url → treat as start-frame animate
        safe_image = ref_urls[0]
        ref_urls = []

    use_reference_to_video = len(ref_urls) >= 2

    # Prefer 1.5 for multi-ref (docs); fall back to default pool
    models = list(video_model_ids())
    if use_reference_to_video:
        preferred = []
        for m in (
            (os.getenv("XAI_VIDEO_MODEL_REF") or "").strip(),
            "grok-imagine-video-1.5",
            "grok-imagine-video",
        ):
            if m and m not in preferred:
                preferred.append(m)
        for m in models:
            if m not in preferred:
                preferred.append(m)
        models = preferred

    last_submit_err = None
    job = None
    mode_label = "reference-to-video" if use_reference_to_video else (
        "image-to-video" if safe_image else "text-to-video"
    )
    for model in models:
        payload = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "resolution": "480p",
        }
        if use_reference_to_video:
            # Real multi-ref — xAI reference-to-video (no ``image`` field)
            payload["reference_images"] = [{"url": u} for u in ref_urls]
        elif safe_image:
            payload["image"] = {"url": safe_image}
        resp = requests.post(
            f"{XAI_BASE_URL}/videos/generations",
            json=payload,
            headers=headers,
            timeout=25,
        )
        if resp.ok:
            job = resp.json()
            break
        last_submit_err = f"xAI video error {resp.status_code} model={model}: {resp.text}"
        body = (resp.text or "").lower()
        if resp.status_code in (404, 400, 403) and any(
            k in body for k in ("model", "not found", "does not exist", "not available")
        ):
            continue
        # Multi-ref 400 on one model — try next model before giving up
        if use_reference_to_video and resp.status_code in (400, 422) and len(models) > 1:
            continue
        break

    if job is None:
        try:
            app.logger.error(
                "xAI video submit failed mode=%s key_tail=%s refs=%d image=%s err=%s",
                mode_label,
                (key or "")[-8:],
                len(ref_urls),
                (safe_image or "")[:120],
                (last_submit_err or "")[:600],
            )
        except Exception:
            pass
        raise Exception(last_submit_err or "xAI video generation failed (no model worked).")

    job_id = job.get("request_id") or job.get("id")
    if not job_id:
        return job

    try:
        app.logger.info(
            "xAI video submitted mode=%s job=%s key_tail=%s duration=%s refs=%d image=%s",
            mode_label,
            str(job_id)[:24],
            (key or "")[-8:],
            duration,
            len(ref_urls) if use_reference_to_video else 0,
            (safe_image or "")[:100],
        )
    except Exception:
        pass
    progress_cb = None
    try:
        if _video_job_progress_cb is not None:
            progress_cb = _video_job_progress_cb.get()
    except Exception:
        progress_cb = None
    return _poll_xai_video_job(
        job_id,
        headers,
        max_wait_sec=480.0,
        label="video",
        on_progress=progress_cb,
    )


# Each extend pass adds a fixed 6-second block (xAI allows 2–10s per extension;
# input clip must be 2–15s). 1 video credit = 1 second, so a pass costs 6 credits.
EXTEND_SECONDS = 6


def extend_video_xai(
    prompt: str,
    video_url: str,
    duration: int = EXTEND_SECONDS,
    api_key: str = None,
) -> dict:
    """Continue an existing video from its last frame via xAI's native extend.

    Schema confirmed against POST /videos/extensions:
        {"model": "grok-imagine-video", "prompt": ..., "video": {"url": ...}, "duration": N}
    GO-3 adaptive poll. Media keys only.
    """
    from xai_keys import get_api_key, video_model_ids

    key = (api_key or get_api_key() or "").strip()
    if not key:
        raise Exception("No xAI API key available for video extend.")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    last_err = None
    job = None
    for model in video_model_ids():
        payload = {
            "model": model,
            "prompt": prompt,
            "video": {"url": video_url},
            "duration": duration,
        }
        resp = requests.post(
            f"{XAI_BASE_URL}/videos/extensions",
            json=payload,
            headers=headers,
            timeout=25,
        )
        if resp.ok:
            job = resp.json()
            break
        last_err = f"xAI extend error {resp.status_code} model={model}: {resp.text}"
        body = (resp.text or "").lower()
        if resp.status_code in (404, 400, 403) and any(
            k in body for k in ("model", "not found", "does not exist", "not available")
        ):
            continue
        break
    if job is None:
        raise Exception(last_err or "xAI extend failed (no model worked).")

    job_id = job.get("request_id") or job.get("id")
    if not job_id:
        return job  # already-complete synchronous response

    progress_cb = None
    try:
        if _video_job_progress_cb is not None:
            progress_cb = _video_job_progress_cb.get()
    except Exception:
        progress_cb = None
    return _poll_xai_video_job(
        job_id,
        headers,
        max_wait_sec=300.0,
        label="extend",
        on_progress=progress_cb,
    )


# ── Auth Routes ───────────────────────────────────────────
# Site minimum is 16 (owner's call, stricter than xAI's 13). DOB collected at sign-up only.
MIN_ACCOUNT_AGE_YEARS = 16


def _user_age_years(birthday: str) -> int | None:
    if not birthday:
        return None
    try:
        born = datetime.date.fromisoformat(str(birthday)[:10])
        today = datetime.date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return None


# Age is checked once, at sign-up. No other route re-checks it.
def _user_meets_min_age(birthday: str) -> bool:
    age = _user_age_years(birthday)
    return age is not None and age >= MIN_ACCOUNT_AGE_YEARS


# ── Email: verification + opt-in news list ───────────────
# Columns: migrations/20261003_email_list.sql. Sending needs RESEND_API_KEY on Render;
# without it nothing is sent and sign-up still works.
_email_tokens = URLSafeTimedSerializer(app.secret_key, salt="percfect-email")


def _send_email(to: str, subject: str, html: str) -> bool:
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not key or not to:
        return False
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "from": os.getenv("EMAIL_FROM", "PercfectAI <hello@percfectai.com>"),
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        if not r.ok:
            app.logger.error("Resend send failed %s: %s", r.status_code, r.text[:300])
        return r.ok
    except Exception:
        app.logger.exception("Resend send failed")
        return False


def _site_base_url() -> str:
    return (os.getenv("SITE_URL") or request.host_url).rstrip("/")


def _send_verification_email(user_id, email: str, username: str) -> bool:
    token = _email_tokens.dumps({"uid": str(user_id), "email": email, "do": "verify"})
    link = f"{_site_base_url()}/verify-email/{token}"
    html = (
        f"<p>Hi {username},</p>"
        f"<p>Tap the button to confirm this is your email for PercfectAI.</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:12px 22px;border-radius:10px;'
        f'background:#2b7fd4;color:#fff;text-decoration:none;font-weight:700">Verify my email</a></p>'
        f"<p style=\"color:#888;font-size:12px\">If you didn't sign up, ignore this email.</p>"
    )
    return _send_email(email, "Verify your PercfectAI email", html)


def unsubscribe_link(user_id, email: str) -> str:
    """Put this in every news email (required by law)."""
    token = _email_tokens.dumps({"uid": str(user_id), "email": email, "do": "unsub"})
    return f"{_site_base_url()}/unsubscribe/{token}"


def _set_marketing_opt_in(user_id, on: bool) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        supabase.table("users").update({
            "marketing_opt_in": bool(on),
            "marketing_opt_in_at": now if on else None,
        }).eq("id", user_id).execute()
    except Exception:
        app.logger.exception("marketing_opt_in update failed (migration run?)")


def _do_register(username, password, birthday="", ip=None, email=None, marketing_opt_in=False):
    import re
    if not username or not password or not email:
        return None, "All fields are required."
    if not birthday:
        return None, "Date of birth is required."
    if not _user_meets_min_age(birthday):
        return None, f"You must be at least {MIN_ACCOUNT_AGE_YEARS} to register."
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return None, "Enter a valid email address."
    if len(password) < 8 or not re.search(r'[A-Z]', password) \
            or not re.search(r'[0-9]', password) or not re.search(r'[^A-Za-z0-9]', password):
        return None, "Password needs 8+ characters, an uppercase letter, a number, and a symbol."
    exists = supabase.table("users").select("id").eq("username", username).execute()
    if exists.data:
        return None, "Username already taken."
    email_exists = supabase.table("users").select("id").eq("email", email).execute()
    if email_exists.data:
        return None, "An account with that email already exists."
    if ip:
        ip_exists = supabase.table("users").select("id").eq("signup_ip", ip).execute()
        if len(ip_exists.data or []) >= 3:
            return None, "Too many accounts from this network. Please log in to an existing account."
    hashed = generate_password_hash(password)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Welcome bonus: every new account starts with free credits (no card required).
    try:
        signup_bonus = max(0, int(os.environ.get("SIGNUP_BONUS_CREDITS", "10")))
    except (TypeError, ValueError):
        signup_bonus = 10
    row = {
        "username": username,
        "email": email,
        "password": hashed,
        "birthday": birthday or None,
        "picture_credits": signup_bonus,
        "video_credits": 0,
        "signup_ip": ip,
        "images_today": 0,
        "videos_today": 0,
        "last_reset": now,
        "api_key1": str(uuid.uuid4()),
        "api_key2": str(uuid.uuid4()),
    }
    try:
        result = supabase.table("users").insert(row).execute()
    except Exception as e:
        return None, f"Registration error: {str(e)}"
    if not result.data:
        return None, "Registration failed. Please try again."
    new_user = User(result.data[0])
    if marketing_opt_in:
        _set_marketing_opt_in(new_user.id, True)
    _send_verification_email(new_user.id, email, username)
    return new_user, None


def _do_login(username, password):
    ident = (username or "").strip()
    if "@" in ident:
        res = supabase.table("users").select("*").eq("email", ident.lower()).maybe_single().execute()
    else:
        res = supabase.table("users").select("*").eq("username", ident).maybe_single().execute()
    data = _sb_row(res)
    if data and check_password_hash(data["password"], password):
        return User(data), None
    return None, "Invalid username or password."


def _get_client_ip():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    return ip.split(",")[0].strip() if ip else None


@app.route("/about")
@app.route("/terms")
@app.route("/privacy")
@app.route("/disclaimer")
def legal_pages():
    """Public legal / about pages (footer links)."""
    page = (request.path or "/about").strip("/").split("/")[0] or "about"
    if page not in ("about", "terms", "privacy", "disclaimer"):
        page = "about"
    titles = {
        "about": "About",
        "terms": "Terms of Use",
        "privacy": "Privacy Policy",
        "disclaimer": "Disclaimer",
    }
    return render_template("legal.html", page=page, page_title=titles[page], user=None)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user, err = _do_register(
            request.form.get("username", "").strip(),
            request.form.get("password", ""),
            request.form.get("birthday", ""),
            ip=_get_client_ip(),
            email=request.form.get("email", "").strip().lower(),
            marketing_opt_in=bool(request.form.get("marketing_opt_in")),
        )
        if err:
            flash(err, "danger")
            return redirect(url_for("register"))
        login_user(user, remember=True)
        return redirect(url_for("percfectstudios"))
    return render_template("register.html")


def _safe_next(url: str) -> str:
    """Only same-site paths ("/studios/battle-cards"), never another host."""
    url = (url or "").strip()
    return url if url.startswith("/") and not url.startswith("//") and "\\" not in url else ""


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = _safe_next(request.values.get("next", ""))
    if request.method == "POST":
        user, err = _do_login(
            request.form.get("username", "").strip(),
            request.form.get("password", ""),
        )
        if err:
            flash(err, "danger")
        else:
            login_user(user, remember=True)
            return redirect(next_url or url_for("percfectstudios"))
    return render_template("login.html", next_url=next_url)


@app.route("/verify-email/<token>")
def verify_email(token):
    try:
        data = _email_tokens.loads(token, max_age=7 * 24 * 3600)
        assert data.get("do") == "verify"
    except Exception:
        flash("That verification link is old or broken. Log in and send a new one from Settings.", "danger")
        return redirect(url_for("login"))
    try:
        supabase.table("users").update({
            "email_verified": True,
            "email_verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq("id", data["uid"]).eq("email", data["email"]).execute()
    except Exception:
        app.logger.exception("email verify update failed")
    flash("Email verified. Thanks!", "success")
    return redirect(url_for("account_settings") if current_user.is_authenticated else url_for("login"))


@app.route("/unsubscribe/<token>")
def unsubscribe(token):
    try:
        data = _email_tokens.loads(token)
        assert data.get("do") == "unsub"
    except Exception:
        return "That unsubscribe link is broken. Email support@percfectai.com and we'll remove you.", 400
    _set_marketing_opt_in(data["uid"], False)
    return ("<!doctype html><meta name=viewport content='width=device-width'>"
            "<body style='font-family:sans-serif;background:#0b1220;color:#eee;display:grid;place-items:center;min-height:100vh;margin:0'>"
            "<div style='text-align:center;padding:24px'><h2>You're unsubscribed</h2>"
            "<p>You won't get news emails from PercfectAI anymore.</p><p><a style='color:#7cb8ff' href='/'>Back to the site</a></p></div>")


@app.route("/auth/resend-verification", methods=["POST"])
@login_required
def resend_verification():
    try:
        row = supabase.table("users").select("email").eq("id", current_user.id).single().execute().data or {}
    except Exception:
        row = {}
    sent = _send_verification_email(current_user.id, row.get("email") or "", current_user.username)
    if not sent:
        return jsonify({"error": "Email isn't set up yet. Try again later."}), 503
    return jsonify({"ok": True})


@app.route("/auth/register", methods=["POST"])
def auth_register_ajax():
    data = request.get_json() or {}
    user, err = _do_register(
        data.get("username", "").strip(),
        data.get("password", ""),
        data.get("birthday", ""),
        ip=_get_client_ip(),
        email=data.get("email", "").strip().lower(),
        marketing_opt_in=bool(data.get("marketing_opt_in")),
    )
    if err:
        return jsonify({"error": err}), 400
    login_user(user, remember=True)
    try:
        reset_daily_if_needed(user.id)
    except Exception:
        pass
    tix = 0
    try:
        tr = supabase.table("users").select("tickets").eq("id", user.id).single().execute()
        tix = _user_tickets(tr.data)
    except Exception:
        pass
    return jsonify({"ok": True, "username": user.username,
                    "picture_credits": user.picture_credits,
                    "video_credits": user.video_credits,
                    "tickets": tix})


@app.route("/auth/login", methods=["POST"])
def auth_login_ajax():
    data = request.get_json() or {}
    user, err = _do_login(
        data.get("username", "").strip(),
        data.get("password", ""),
    )
    if err:
        return jsonify({"error": err}), 401
    login_user(user, remember=True)
    try:
        reset_daily_if_needed(user.id)
    except Exception:
        pass
    tix = 0
    try:
        tr = supabase.table("users").select("tickets").eq("id", user.id).single().execute()
        tix = _user_tickets(tr.data)
    except Exception:
        pass
    return jsonify({"ok": True, "username": user.username,
                    "picture_credits": user.picture_credits,
                    "video_credits": user.video_credits,
                    "tickets": tix})


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Health ping (UptimeRobot keeps Render awake) ─────────
SHARE_MEDIA_HOST_SUFFIXES = ("x.ai", "supabase.co")


def _twitter_handle(user_data):
    raw = (user_data or {}).get("social_twitter", "")
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith("http"):
        part = raw.rstrip("/").split("/")[-1]
        return part.lstrip("@")
    return raw.lstrip("@")


def _is_allowed_share_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.netloc.lower()
        return any(host == suffix or host.endswith("." + suffix) for suffix in SHARE_MEDIA_HOST_SUFFIXES)
    except Exception:
        return False


@app.route("/share/fetch")
def share_fetch_media():
    """Same-origin proxy so mobile Web Share can attach image/video files."""
    url = request.args.get("url", "").strip()
    if not url or not _is_allowed_share_url(url):
        return jsonify({"error": "Invalid media URL."}), 400
    try:
        upstream = requests.get(url, timeout=60, stream=True)
        if not upstream.ok:
            return jsonify({"error": "Could not fetch media."}), 502
        content_type = upstream.headers.get("Content-Type", "application/octet-stream")
        return Response(upstream.content, mimetype=content_type)
    except Exception:
        return jsonify({"error": "Fetch failed."}), 500


@app.route("/ping")
def ping():
    return "ok", 200


# ── Self keep-alive ───────────────────────────────────────
# Render's free tier sleeps after ~15 min with no inbound traffic, which
# gives the next visitor a 30–50s cold start. A background thread pings our
# own public URL every 10 min so inbound traffic never stops and it stays warm.
def _self_keepalive():
    import time
    base = os.environ.get("RENDER_EXTERNAL_URL", "https://percfectstudios.onrender.com").rstrip("/")
    url = f"{base}/ping"
    while True:
        time.sleep(600)  # 10 min — comfortably beats the ~15 min idle window
        try:
            requests.get(url, timeout=30)
        except Exception:
            pass


if os.environ.get("ENABLE_KEEPALIVE", "1") == "1":
    import threading
    threading.Thread(target=_self_keepalive, daemon=True).start()


# ── Main Pages ────────────────────────────────────────────
def _layout_page_html(folder: str) -> str:
    """Load new diner/hub layout HTML and inject live credits/tickets when logged in."""
    path = os.path.join(app.root_path, "static", "layouts", "percfect-site", folder, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    credits, tickets = 0, 0
    if current_user.is_authenticated:
        try:
            reset_daily_if_needed(current_user.id)
            row = (
                supabase.table("users")
                .select("picture_credits,video_credits,tickets")
                .eq("id", current_user.id)
                .limit(1)
                .execute()
            )
            data = (row.data or [None])[0] or {}
            credits = int(data.get("picture_credits") or 0) + int(data.get("video_credits") or 0)
            tickets = int(data.get("tickets") or 0)
        except Exception:
            try:
                u = _studio_user_credits() or {}
                credits = int(u.get("picture_credits") or 0) + int(u.get("video_credits") or 0)
            except Exception:
                pass
    # Sample chips in the design mock → live wallet
    import re as _re
    html = _re.sub(
        r'(<span class="chip cr"><span class="dot cr"></span>)\d+(</span>)',
        rf'\g<1>{credits}\g<2>',
        html,
        count=1,
    )
    html = _re.sub(
        r'(<span class="chip tk"><span class="dot tk"></span>)\d+(</span>)',
        rf'\g<1>{tickets}\g<2>',
        html,
        count=1,
    )
    return html


@app.route("/")
def index():
    """Homepage = new Percfect World diner hub (from site layouts). Old hub at /homebase-legacy."""
    return Response(_layout_page_html("home"), mimetype="text/html")


@app.route("/build")
@app.route("/studios/build")
def build_hub_page():
    """Build hub: Comic · Character · Card."""
    return Response(_layout_page_html("build"), mimetype="text/html")


@app.route("/create")
@app.route("/studios/create")
def create_hub_page():
    """Create hub: Pictures · Productions · Videos."""
    return Response(_layout_page_html("create"), mimetype="text/html")


@app.route("/play")
@app.route("/studios/play")
def play_hub_page():
    """Play hub: Arena (live) · 3-D (under construction)."""
    return Response(_layout_page_html("play"), mimetype="text/html")


@app.route("/cards")
@app.route("/studios/cards")
def cards_hub_page():
    """Cards hub: Card Studio · Battle Cards · Card Shop."""
    return Response(_layout_page_html("cards"), mimetype="text/html")


@app.route("/re-up")
@app.route("/reup")
@app.route("/studios/re-up")
def reup_hub_page():
    """Re-Up hub: film-strip options — Credits / Account / Support live; rest UC."""
    return Response(_layout_page_html("reup"), mimetype="text/html")


@app.route("/credits")
@login_required
def credits_page():
    """Credits purchase UI (was Re-Up /buy-credits)."""
    return buy_credits()


@app.route("/welcome")
@app.route("/marketing")
def marketing_landing():
    """Old long marketing landing (was /). Optional signup story page."""
    return render_template(
        "landing_live.html",
        user=_studio_user_credits() if current_user.is_authenticated else None,
    )


@app.route("/home-legacy")
@app.route("/homebase-legacy")
def home_legacy():
    """Previous hub_live homebase (kept for rollback)."""
    return render_template("hub_live.html", user=_studio_user_credits())


# ── Site pages (percfectai.com points straight at Render) ──
@app.route("/tv")
def site_tv():
    return send_from_directory("static/site", "tv.html")


@app.route("/app")
def site_app():
    return send_from_directory("static/site", "app.html")


@app.route("/connect")
def site_connect():
    return send_from_directory("static/site", "connect.html")


@app.route("/assets/<path:filename>")
def site_assets(filename):
    return send_from_directory("static/assets", filename)


@app.route("/kodi")
@app.route("/kodi/")
def kodi_index():
    return send_from_directory("static/kodi", "index.html")


@app.route("/kodi/<path:filename>")
def kodi_files(filename):
    return send_from_directory("static/kodi", filename)


@app.route("/k")
def kodi_shortlink():
    return send_from_directory("static/kodi", "repository.percfectai-1.0.11.zip")


@app.route("/plugin.zip")
@app.route("/repository.zip")
@app.route("/repository.percfectai-1.0.7.zip")
@app.route("/repository.percfectai-1.0.9.zip")
@app.route("/repository.percfectai-1.0.11.zip")
def kodi_zip_aliases():
    name = request.path.lstrip("/")
    return send_from_directory("static/kodi", name)


@app.route("/proto/cards")
@app.route("/prototype/cards")
@app.route("/studios/trading-cards")
def proto_trading_cards():
    """Percfect Cards studio — roster → framed card · static 2 cr · spin 5 cr.

    Free to preview. Stats feed Battle Cards fights.
    """
    user_data = None
    bal = 0
    tickets = 0
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        try:
            res = supabase.table("users").select(
                "picture_credits,video_credits,tickets"
            ).eq("id", current_user.id).single().execute()
            user_data = res.data
            bal = _user_credits(user_data)
            tickets = int((user_data or {}).get("tickets") or 0)
        except Exception:
            try:
                res = supabase.table("users").select(
                    "picture_credits,video_credits"
                ).eq("id", current_user.id).single().execute()
                user_data = res.data
                bal = _user_credits(user_data)
            except Exception:
                user_data = None
    return render_template(
        "trading_cards.html",
        user=user_data,
        balance=bal,
        tickets=tickets,
        logged_in=bool(current_user.is_authenticated),
        card_static_credits=CARD_STATIC_CREDITS,
        card_spin_credits=CARD_SPIN_CREDITS,
        card_frames=CARD_FRAMES,
        card_themes=CARD_THEMES,
        card_rarities=CARD_RARITIES,
        buy_credits=TRADING_CARD_BUY_CREDITS,
    )


# ── Official Card Shop (premium Nick art · free starters · paid unlocks) ──

_CARD_CATALOG_PATHS = (
    os.path.join(os.path.dirname(__file__), "static", "assets", "cards", "catalog", "official_catalog.json"),
    os.path.join(os.path.dirname(__file__), "HANDOFFS", "cards_official_catalog.json"),
)


def _load_official_card_catalog() -> dict:
    for path in _CARD_CATALOG_PATHS:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("characters"):
                    return data
        except Exception:
            continue
    return {"version": 0, "characters": [], "chrome": {}}


def _premium_card_art_url(card_id: str) -> str:
    """Shop face: full draft card first, then premium cutout, then mockups.

    Prefer drafts/{id}_draft.png — those are composited on theme (looks like a real card).
    Never spam-gen official shop faces.
    """
    cid = (card_id or "").strip().lower().replace(" ", "_")
    if not cid:
        return ""
    # 1) Full composited draft (name + scene + stats) — what shop should show
    for draft_name in (f"{cid}_draft.png", f"{cid}.png"):
        draft = os.path.join(app.root_path, "static", "assets", "cards", "drafts", draft_name)
        if os.path.isfile(draft):
            return f"/static/assets/cards/drafts/{draft_name}"
    # 2) Premium drop-in
    base = os.path.join(app.root_path, "static", "assets", "cards", "premium")
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = os.path.join(base, cid + ext)
        if os.path.isfile(path):
            return f"/static/assets/cards/premium/{cid}{ext}"
    # 3) Mockups (Snow White full card, etc.)
    mock = os.path.join(app.root_path, "static", "assets", "cards", "mockups")
    if os.path.isdir(mock):
        try:
            for name in sorted(os.listdir(mock)):
                low = name.lower()
                if low.startswith(cid + "_") or low.startswith(cid + ".") or low == cid + ".png":
                    if low.endswith((".png", ".jpg", ".jpeg", ".webp")):
                        return f"/static/assets/cards/mockups/{name}"
        except OSError:
            pass
    return ""


def _card_shop_listings() -> list:
    """Public shop — EMPTY until Nick sets shop_visible on a card he stamped.

    Old agent drafts / catalog junk never show. No base-only auto-list either
    (Maleficent base exists but Nick said nothing stamped by him is ready).
    """
    cat = _load_official_card_catalog()
    out = []
    for c in cat.get("characters") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        # Hard gate: Nick must explicitly enable the card for shop
        if c.get("shop_visible") is not True:
            continue
        not_for_sale = bool(c.get("not_for_sale") or c.get("obtain") in (
            "packs_or_tournaments", "packs", "tournaments", "exclusive",
        ))
        price = int(c.get("price_credits") if c.get("price_credits") is not None else 25)
        if not_for_sale:
            price = 0
        num = int(c.get("number") or 1)
        theme_key = (c.get("theme_key") or "princess").strip()
        theme_scene = c.get("theme_scene") or f"/static/assets/cards/themes/{theme_key}/scene.jpg"
        image_url = (c.get("image_url") or "").strip()
        if not image_url:
            image_url = _premium_card_art_url(str(c["id"]))
        if not image_url:
            continue
        obtain_label = (c.get("obtain_label") or "").strip() or (
            "Not for sale — packs or tournaments only" if not_for_sale else ""
        )
        out.append({
            "id": str(c["id"]),
            "name": c.get("name") or "Card",
            "number": num,
            "number_label": f"{num:02d}",
            "edition": int(c.get("edition") or 500),
            "gender": c.get("gender") or "female",
            "stats": c.get("stats") or {},
            "price_credits": price,
            "free": (price <= 0 and not not_for_sale),
            "not_for_sale": not_for_sale,
            "obtain": c.get("obtain") or ("packs_or_tournaments" if not_for_sale else "shop"),
            "obtain_label": obtain_label,
            "theme_key": theme_key,
            "theme_scene": theme_scene,
            "image_url": image_url,
            "premium_art": bool(image_url),
            "blurb": c.get("blurb") or (c.get("theme") or "Official Percfect card")[:90],
            "character_desc": c.get("character_desc") or "",
        })
    out.sort(key=lambda x: (
        0 if x.get("free") else 1,
        0 if x.get("not_for_sale") else 1,
        x["number"],
    ))
    return out


def _user_card_deck(user_id) -> list:
    try:
        res = (
            supabase.table("users")
            .select("card_deck")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        row = (res.data or [None])[0] or {}
        raw = row.get("card_deck")
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(x) for x in raw]
        if isinstance(raw, str) and raw.strip():
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [str(x) for x in data]
            except Exception:
                return [x.strip() for x in raw.split(",") if x.strip()]
    except Exception:
        pass
    return []


def _save_user_card_deck(user_id, deck: list) -> bool:
    deck = [str(x) for x in deck]
    try:
        supabase.table("users").update({"card_deck": deck}).eq("id", user_id).execute()
        return True
    except Exception:
        try:
            supabase.table("users").update({"card_deck": json.dumps(deck)}).eq("id", user_id).execute()
            return True
        except Exception:
            try:
                app.logger.warning(
                    "card_deck save failed — add column: alter table users add column if not exists card_deck jsonb default '[]'"
                )
            except Exception:
                pass
    return False


@app.route("/proto/cards-page")
@app.route("/prototype/cards-page")
def card_shop_proto_page():
    """Nick banner prototype — does NOT replace live Card Shop until approved."""
    return render_template("card_shop_proto.html")


@app.route("/proto/home")
@app.route("/prototype/home")
@app.route("/proto/")
def proto_home_page():
    """Alias → live home."""
    return redirect("/")


@app.route("/proto/build")
@app.route("/prototype/build")
def proto_build_page():
    """Alias → live Build hub."""
    return redirect("/build")


@app.route("/proto/create")
@app.route("/prototype/create")
def proto_create_page():
    """Alias → live Create hub."""
    return redirect("/create")


@app.route("/studios/card-shop")
@app.route("/studios/cards-shop")
@app.route("/shop/cards")
def card_shop_page():
    """Public Card Shop — free starters + paid official cards for advertising / sales."""
    user_data = None
    bal = 0
    owned = []
    is_admin = False
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        try:
            res = supabase.table("users").select(
                "picture_credits,video_credits,is_admin"
            ).eq("id", current_user.id).single().execute()
            user_data = res.data
            bal = _user_credits(user_data)
            is_admin = bool((user_data or {}).get("is_admin") or current_user.is_admin)
        except Exception:
            user_data = None
            is_admin = bool(getattr(current_user, "is_admin", False))
        owned = _user_card_deck(current_user.id)
    listings = _card_shop_listings()
    return render_template(
        "card_shop.html",
        user=user_data,
        balance=bal,
        logged_in=bool(current_user.is_authenticated),
        listings=listings,
        owned_ids=owned,
        is_admin=is_admin,
    )


@app.route("/api/card-shop/admin/restamp", methods=["POST"])
@login_required
def card_shop_admin_restamp():
    """Admin only: type name + card # + 4 stats → stamp on Nick base art.

    That's it — no art regen. Base must exist at bases/{id}_base.webp.
    """
    if not (getattr(current_user, "is_admin", False) or current_user.is_admin):
        return jsonify({"error": "Admin only."}), 403
    body = request.get_json(silent=True) or {}
    card_id = str(body.get("card_id") or "").strip().lower()
    name = str(body.get("name") or "").strip()
    raw_stats = body.get("stats") or {}
    if not card_id and name:
        import re
        card_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not card_id:
        return jsonify({"error": "card_id or name required"}), 400
    try:
        number = int(body.get("number") if body.get("number") is not None else 1)
    except (TypeError, ValueError):
        return jsonify({"error": "Card number must be an integer."}), 400
    if not isinstance(raw_stats, dict) or not raw_stats:
        return jsonify({"error": "Pass stats, e.g. Attack/Defence/Speed/Swag."}), 400
    try:
        stats = {str(k): int(v) for k, v in raw_stats.items()}
    except (TypeError, ValueError):
        return jsonify({"error": "Stats must be integers 0–50."}), 400
    gender = str(body.get("gender") or "").strip()
    theme_key = str(body.get("theme_key") or "").strip()
    try:
        from card_stamp import restamp_card

        ok, msg = restamp_card(
            card_id,
            stats,
            name=name,
            number=number,
            gender=gender,
            theme_key=theme_key,
        )
    except Exception as e:
        app.logger.exception("restamp failed")
        return jsonify({"error": str(e)}), 500
    if not ok:
        return jsonify({"error": msg}), 404
    return jsonify({
        "ok": True,
        "card_id": card_id,
        "name": (name or card_id).upper(),
        "number": number,
        "stats": {k: max(0, min(50, int(v))) for k, v in stats.items()},
        "image_url": msg,
        "message": f"Stamped {name or card_id} · N{number:02d} — tweak any field anytime.",
    })


@app.route("/api/card-shop")
def card_shop_api():
    listings = _card_shop_listings()
    owned = _user_card_deck(current_user.id) if current_user.is_authenticated else []
    return jsonify({"listings": listings, "owned": owned, "count": len(listings)})


@app.route("/api/card-shop/claim", methods=["POST"])
@login_required
def card_shop_claim():
    """Claim free official card or buy with credits (premium Nick art catalog)."""
    reset_daily_if_needed(current_user.id)
    body = request.get_json(silent=True) or {}
    card_id = str(body.get("card_id") or request.form.get("card_id") or "").strip()
    if not card_id:
        return jsonify({"error": "Pick a card."}), 400

    listings = {str(x["id"]): x for x in _card_shop_listings()}
    item = listings.get(card_id)
    if not item:
        return jsonify({"error": "That card is not in the shop."}), 404

    deck = _user_card_deck(current_user.id)
    if card_id in deck:
        return jsonify({
            "ok": True,
            "already": True,
            "owned": deck,
            "message": f"You already own {item['name']}.",
        })

    if item.get("not_for_sale"):
        return jsonify({
            "error": item.get("obtain_label")
            or "Not for sale — only available in card packs or tournaments.",
            "not_for_sale": True,
            "obtain": item.get("obtain") or "packs_or_tournaments",
        }), 403

    price = int(item.get("price_credits") or 0)
    bal = 0
    try:
        res = supabase.table("users").select(
            "picture_credits,video_credits"
        ).eq("id", current_user.id).single().execute()
        user_data = res.data or {}
        bal = _user_credits(user_data)
    except Exception:
        user_data = {}
        bal = 0

    is_admin = bool(current_user.is_admin)
    if price > 0 and not is_admin:
        if bal < price:
            return jsonify({
                "error": f"{item['name']} needs {price} credits — you have {bal}.",
                "needed": price,
                "balance": bal,
            }), 402
        if not _apply_spend(current_user.id, user_data, price, {}):
            return jsonify({"error": "Could not charge credits."}), 402
        bal = max(0, bal - price)
    elif is_admin:
        bal = _user_credits(user_data)

    deck.append(card_id)
    saved = _save_user_card_deck(current_user.id, deck)
    msg = (
        f"Free card unlocked: {item['name']}"
        if price <= 0
        else f"Purchased {item['name']} · −{price} credits"
    )
    if is_admin and price > 0:
        msg = f"Admin claimed {item['name']} (no charge)"
    if not saved:
        msg += " · ownership may not persist until card_deck column exists"

    return jsonify({
        "ok": True,
        "card_id": card_id,
        "name": item["name"],
        "price": 0 if is_admin else price,
        "balance": bal,
        "owned": deck,
        "persisted": saved,
        "message": msg,
    })


def _compose_trading_card_image(
    src_url: str,
    *,
    name: str,
    rarity: str = "rare",
    frame: str = "legend",
    stats: dict = None,
    gender: str = "",
    tagline: str = "",
    serial_num: int = None,
    edition: int = 1000,
    char_id=None,
    stats_on_front: bool = False,
) -> bytes:
    """Rasterize static card PNG: theme background + border + name + stats.

    Layouts (theme['layout']):
      legend  — cracked mat, gold window, name plate top, stats bottom-left (Ned ref)
      loading — thick black frame, big name top-left, brick bars bottom-right (Robin ref)
      default — gold rings, centered name banner, stats corner
    """
    from PIL import ImageDraw, ImageFont

    if (src_url or "").startswith("data:"):
        header, b64 = src_url.split(",", 1)
        raw = base64.b64decode(b64)
    else:
        r = requests.get(src_url, timeout=40)
        r.raise_for_status()
        raw = r.content

    char = Image.open(BytesIO(raw)).convert("RGBA")
    W, H = 750, 1050
    rarity = (rarity or "rare").lower()
    theme = _card_theme(frame or "princess")
    layout = (theme.get("layout") or "vintage").lower()
    bg1 = _hex_rgba(theme.get("bg1") or "#0a0a0c")
    bg2 = _hex_rgba(theme.get("bg2") or "#050508")
    outer = _hex_rgba(theme.get("outer") or "#ffc107")
    mid = _hex_rgba(theme.get("mid") or "#1a1a1a")
    inner = _hex_rgba(theme.get("inner") or "#ffffff", 220)
    name_col = _hex_rgba(theme.get("name_color") or "#ffc107")
    accent = _hex_rgba(theme.get("accent") or theme.get("outer") or "#ffc107")
    stat_border = _hex_rgba(theme.get("stat_border") or "#ffc107", 220)

    _res = getattr(Image, "Resampling", Image)
    _lanczos = getattr(_res, "LANCZOS", Image.LANCZOS)

    # --- LAYER 1: scene background (real theme art) ---
    card = Image.new("RGBA", (W, H), bg2)
    scene_path = theme.get("scene") or ""
    if scene_path.startswith("/static/"):
        scene_path = os.path.join(app.root_path, scene_path.lstrip("/"))
    if scene_path and os.path.isfile(scene_path):
        try:
            scene = Image.open(scene_path).convert("RGBA")
            sw, sh = scene.size
            sc = max(W / float(sw), H / float(sh))
            scene = scene.resize((max(1, int(sw * sc)), max(1, int(sh * sc))), _lanczos)
            sx = (scene.size[0] - W) // 2
            sy = (scene.size[1] - H) // 2
            card.paste(scene.crop((sx, sy, sx + W, sy + H)), (0, 0))
        except Exception:
            pass
    draw = ImageDraw.Draw(card)

    # Portrait window
    if layout == "legend":
        inset_l, inset_t, inset_r, inset_b = 55, 100, 55, 55
    elif layout == "loading":
        inset_l, inset_t, inset_r, inset_b = 22, 22, 22, 22
    else:
        inset_l = inset_t = inset_r = inset_b = 28

    # LAYER 2: character on scene (contain, bottom-weighted — scene shows around her)
    # Full white-key so princess 360 / white-card spins don't paint a white wall over the theme.
    art_x, art_y = inset_l, inset_t
    art_w, art_h = W - inset_l - inset_r, H - inset_t - inset_b
    try:
        char = _key_out_white(char, thresh=42)
    except Exception:
        pass
    # Soft mop for leftover near-white (gradients / compression) not corner-connected
    try:
        px = char.load()
        cw0, ch0 = char.size
        for yy in range(ch0):
            for xx in range(cw0):
                r, g, b, a = px[xx, yy]
                if a < 8:
                    continue
                lum = (r + g + b) / 3.0
                spread = max(r, g, b) - min(r, g, b)
                if lum > 245 and spread < 18:
                    px[xx, yy] = (r, g, b, 0)
                elif lum > 228 and spread < 16:
                    px[xx, yy] = (r, g, b, max(0, int(a * (245 - lum) / 28)))
    except Exception:
        pass
    cw, ch = char.size
    scale = min(art_w / float(cw), art_h / float(ch)) * 0.98
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    char = char.resize((nw, nh), _lanczos)
    ox = art_x + (art_w - nw) // 2
    oy = art_y + art_h - nh  # stand on bottom of art window
    card.paste(char, (ox, oy), char)

    draw = ImageDraw.Draw(card)
    name_txt = (name or "UNKNOWN").strip().upper()[:28]
    tag = (tagline or theme.get("label") or "").strip().upper()[:18]
    if serial_num is None:
        serial_num, edition = character_card_serial(char_id or name_txt, name_txt, edition)
    else:
        edition = max(1, int(edition or 1000))
        serial_num = max(1, min(edition, int(serial_num)))
    serial_txt = _format_card_serial(serial_num, edition)

    font_name = font_sm = font_stat = None
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ):
        try:
            font_name = ImageFont.truetype(path, 48 if layout == "legend" else 52)
            font_sm = ImageFont.truetype(path, 18)
            font_stat = ImageFont.truetype(path, 22)
            break
        except Exception:
            pass
    if font_name is None:
        font_name = ImageFont.load_default()
        font_sm = font_stat = font_name

    stats = stats or {}
    if not stats:
        stats = character_card_stats(char_id or 0, name_txt, gender)
    lines = list(stats.items())[:4]

    def _paste_logo(xy, size=56, *, path=None, circle=False):
        """Paste Percfect mark. Default crown; corner stamp can use logo-cut."""
        try:
            logo_path = os.path.join(app.root_path, path or TRADING_CARD_LOGO_PATH)
            if not os.path.isfile(logo_path):
                logo_path = os.path.join(app.root_path, TRADING_CARD_LOGO_PATH)
            if os.path.isfile(logo_path):
                logo = Image.open(logo_path).convert("RGBA").resize((size, size), _lanczos)
                if circle:
                    # Round badge for bottom-right corner stamp
                    mask = Image.new("L", (size, size), 0)
                    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
                    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                    out.paste(logo, (0, 0))
                    out.putalpha(mask)
                    # gold ring
                    ring = ImageDraw.Draw(out)
                    ring.ellipse([1, 1, size - 2, size - 2], outline=(255, 193, 7, 255), width=3)
                    card.paste(out, xy, out)
                else:
                    card.paste(logo, xy, logo)
                return True
        except Exception:
            pass
        return False

    def _draw_serial(corner="tr"):
        # Official numbered card mark
        sb = draw.textbbox((0, 0), serial_txt, font=font_sm)
        sw, sh = sb[2] - sb[0], sb[3] - sb[1]
        pad = 8
        if corner == "tr":
            x1, y1 = W - sw - pad * 2 - 18, 18
        else:
            x1, y1 = 18, H - sh - pad * 2 - 18
        draw.rounded_rectangle(
            [x1, y1, x1 + sw + pad * 2, y1 + sh + pad * 2],
            radius=6, fill=(0, 0, 0, 210), outline=outer, width=2,
        )
        draw.text((x1 + pad, y1 + pad), serial_txt, fill=accent, font=font_sm)

    # --- BORDER ---
    if layout == "legend":
        # Gold double window around art
        for t, col in ((0, outer), (6, mid), (10, inner)):
            draw.rectangle(
                [art_x - 12 + t, art_y - 12 + t, art_x + art_w + 11 - t, art_y + art_h + 11 - t],
                outline=col,
            )
        # Top name plate
        plate_y = 28
        plate_h = 56
        draw.rounded_rectangle(
            [100, plate_y, W - 40, plate_y + plate_h],
            radius=6, fill=(10, 10, 12, 255), outline=outer, width=4,
        )
        # Circular badge (Percfect logo)
        bx, by, br = 70, plate_y + plate_h // 2, 34
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=outer, outline=mid, width=3)
        draw.ellipse([bx - br + 8, by - br + 8, bx + br - 8, by + br - 8], outline=accent, width=2)
        if not _paste_logo((bx - 20, by - 20), 40):
            draw.text((bx - 10, by - 14), "P", fill=(10, 10, 12, 255), font=font_stat)
        else:
            draw = ImageDraw.Draw(card)

        bbox = draw.textbbox((0, 0), name_txt, font=font_name)
        tw = bbox[2] - bbox[0]
        draw.text((100 + (W - 140 - tw) // 2, plate_y + 8), name_txt, fill=name_col, font=font_name)
        _draw_serial("tr")

        # Corner stamp bottom-right (room for Nick's new logo asset later)
        _paste_logo(
            (W - 78, H - 78), 64,
            path=TRADING_CARD_LOGO_PATH,
            circle=True,
        )
        draw = ImageDraw.Draw(card)

        if stats_on_front:
            # Stats bottom-left
            box_w, line_h = 150, 28
            box_h = 12 + line_h * max(1, len(lines))
            sx, sy = 22, H - box_h - 22
            draw.rectangle([sx, sy, sx + box_w, sy + box_h], fill=(0, 0, 0, 230), outline=outer, width=2)
            yy = sy + 6
            for k, v in lines:
                lab = str(k)[:8].upper()
                short = {
                    "ATTACK": "ATK", "DEFENCE": "DEF", "DEFENSE": "DEF",
                    "SPEED": "SPD", "SWAG": "SWG", "SEDUCTION": "SED",
                    "BEAUTY": "BTY", "POWER": "ATK", "STYLE": "SWG",
                }.get(lab, lab[:6])
                val = int(v) if isinstance(v, (int, float)) or str(v).isdigit() else v
                draw.text((sx + 10, yy), f"{short}", fill=(200, 200, 200, 255), font=font_sm)
                draw.text((sx + box_w - 48, yy - 2), str(val), fill=accent, font=font_stat)
                yy += line_h

        if tag:
            tb = draw.textbbox((0, 0), tag, font=font_stat)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            tx = art_x + art_w - tw - 16
            ty = art_y + art_h - th - 18
            draw.rectangle([tx - 8, ty - 4, tx + tw + 8, ty + th + 6], fill=(0, 0, 0, 200))
            draw.text((tx, ty), tag, fill=accent, font=font_stat)

    elif layout in ("loading", "vintage", "tcg"):
        # Thick black outer border
        for t in range(0, 16):
            draw.rectangle([t, t, W - 1 - t, H - 1 - t], outline=outer)
        draw.rectangle([18, 18, W - 19, H - 19], outline=inner)
        # Big name top-left
        try:
            font_big = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64
            )
        except Exception:
            try:
                font_big = ImageFont.truetype(
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", 64
                )
            except Exception:
                font_big = font_name
        # Name top-left with outline
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
            draw.text((28 + ox, 24 + oy), name_txt, fill=(0, 0, 0, 255), font=font_big)
        draw.text((28, 24), name_txt, fill=name_col if name_col[0] > 40 else (245, 240, 230, 255), font=font_big)
        # Name top-left already drawn; logo bottom-right; serial top-right
        _paste_logo(
            (W - 78, H - 78), 64,
            path=TRADING_CARD_LOGO_PATH,
            circle=True,
        )
        draw = ImageDraw.Draw(card)
        _draw_serial("tr")
        # Series / tagline under name
        sub = tag or (theme.get("series") or theme.get("label") or "PERCFECT")
        draw.text((32, 90), str(sub).upper()[:28], fill=accent, font=font_sm)

        if stats_on_front or layout == "tcg":
            # Compact 4-stat block bottom-left (not full-width plate over art)
            box_w, line_h = 168, 30
            box_h = 14 + line_h * max(1, len(lines))
            sx, sy = 22, H - box_h - 22
            draw.rounded_rectangle(
                [sx, sy, sx + box_w, sy + box_h],
                radius=8, fill=(0, 0, 0, 230), outline=outer, width=2,
            )
            yy = sy + 8
            for k, v in lines:
                val = int(v) if isinstance(v, (int, float)) or str(v).isdigit() else 70
                lab = str(k)[:8].upper()
                short = {
                    "ATTACK": "ATK", "DEFENCE": "DEF", "DEFENSE": "DEF",
                    "SPEED": "SPD", "SWAG": "SWG", "SEDUCTION": "SED", "BEAUTY": "BTY",
                }.get(lab, lab[:4])
                draw.text((sx + 10, yy), short, fill=(200, 200, 200, 255), font=font_sm)
                draw.text((sx + box_w - 48, yy - 2), str(val), fill=accent, font=font_stat)
                yy += line_h

    else:
        # Default: name top-left · logo bottom-right · stats bottom-left · serial top-right
        for t in range(0, 12):
            draw.rectangle([t, t, W - 1 - t, H - 1 - t], outline=outer)
        draw.rectangle([14, 14, W - 15, H - 15], outline=mid)
        draw.rectangle([20, 20, W - 21, H - 21], outline=inner)
        # Name plate top-left
        draw.rounded_rectangle(
            [18, 18, min(W - 120, 18 + 420), 100],
            radius=10, fill=(0, 0, 0, 210), outline=outer, width=2,
        )
        draw.text((28, 28), name_txt[:22], fill=name_col, font=font_name)
        # Never print "Rare" on the face — series/theme only
        sub = str(theme.get("label") or "Percfect")[:32]
        draw.text((28, 72), sub, fill=(200, 200, 210, 220), font=font_sm)
        _paste_logo(
            (W - 78, H - 78), 64,
            path=TRADING_CARD_LOGO_PATH,
            circle=True,
        )
        draw = ImageDraw.Draw(card)
        _draw_serial("tr")
        if stats_on_front:
            box_w, line_h = 168, 30
            box_h = 14 + line_h * max(1, len(lines))
            sx, sy = 22, H - box_h - 22
            draw.rounded_rectangle(
                [sx, sy, sx + box_w, sy + box_h],
                radius=10, fill=(0, 0, 0, 210), outline=stat_border, width=2,
            )
            yy = sy + 8
            for k, v in lines:
                draw.text((sx + 12, yy), str(k)[:10].upper(), fill=(160, 155, 150, 255), font=font_sm)
                val = str(int(v)) if isinstance(v, (int, float)) or str(v).isdigit() else str(v)[:4]
                draw.text((sx + box_w - 44, yy - 2), val, fill=name_col, font=font_stat)
                yy += line_h

    out = BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _persist_image_bytes(data: bytes, *, ext: str = "png", content_type: str = "image/png") -> str:
    """Upload raw image bytes to public previews bucket; return absolute URL."""
    path = f"cards/{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_("previews").upload(
        path, data,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"


@app.route("/studios/trading-cards/export-static", methods=["POST"])
@login_required
def trading_cards_export_static():
    """Save a static trading card image · CARD_STATIC_CREDITS (2).

    New Card Studio posts {card, face}. Legacy GTA path still accepts character_id.
    """
    body = request.get_json(silent=True) or {}
    if isinstance(body.get("card"), dict):
        import card_studio

        return card_studio.export_plate_http()
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    is_admin = bool(current_user.is_admin)
    cost = CARD_STATIC_CREDITS
    bal = _user_credits(user_data)
    if not is_admin and bal < cost:
        return jsonify({
            "error": f"Static card needs {cost} credits — you have {bal}.",
            "needed": cost,
            "balance": bal,
        }), 402

    body = request.get_json(silent=True) or {}
    char_id = body.get("character_id") or request.form.get("character_id")
    name = (body.get("name") or request.form.get("name") or "").strip()
    rarity = (body.get("rarity") or request.form.get("rarity") or "rare").strip().lower()
    frame = (body.get("frame") or request.form.get("frame") or "legend").strip().lower()
    tagline = (body.get("tagline") or request.form.get("tagline") or "").strip()[:40]
    stats = body.get("stats") if isinstance(body.get("stats"), dict) else {}
    if not stats:
        raw = request.form.get("stats") or ""
        if raw:
            try:
                stats = json.loads(raw)
            except Exception:
                stats = {}

    if not char_id:
        return jsonify({"error": "Pick a character first."}), 400
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id

    cres = (
        supabase.table("characters")
        .select("*")
        .eq("id", cid)
        .eq("user_id", current_user.id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char:
        return jsonify({"error": "Character not found on your roster."}), 404
    try:
        ser = _serialize_character(char)
    except Exception:
        ser = char
    src = (
        ser.get("primary_image_url")
        or (ser.get("images") or [None])[0]
        or char.get("primary_image_url")
        or ""
    )
    if not src:
        return jsonify({"error": "Character needs a portrait first."}), 400
    if not name:
        name = (ser.get("name") or char.get("name") or "Unknown").strip()
    gender = (ser.get("gender") or char.get("gender") or "").strip()
    if not stats:
        stats = character_card_stats(cid, name, gender)

    edition = 1000
    serial_num = None
    try:
        edition = int(body.get("edition") or request.form.get("edition") or 1000)
    except (TypeError, ValueError):
        edition = 1000
    try:
        if body.get("serial_num") or request.form.get("serial_num"):
            serial_num = int(body.get("serial_num") or request.form.get("serial_num"))
    except (TypeError, ValueError):
        serial_num = None
    if serial_num is None:
        serial_num, edition = character_card_serial(cid, name, edition)
    stats_on_front = str(body.get("stats_on_front") or request.form.get("stats_on_front") or "").lower() in (
        "1", "true", "yes", "front",
    )

    try:
        png = _compose_trading_card_image(
            src, name=name, rarity=rarity, frame=frame, stats=stats, gender=gender,
            tagline=tagline, serial_num=serial_num, edition=edition, char_id=cid,
            stats_on_front=stats_on_front,
        )
        url = _persist_image_bytes(png, ext="png", content_type="image/png")
    except Exception as e:
        app.logger.exception("card static compose failed")
        return jsonify({"error": f"Could not build card: {e}"}), 500

    if not is_admin:
        if not _apply_spend(
            current_user.id, user_data, cost,
            {"images_today": int(user_data.get("images_today") or 0) + 1},
        ):
            return jsonify({"error": "Could not charge credits."}), 402

    try:
        supabase.table("generations").insert({
            "user_id": current_user.id,
            "type": "image",
            "prompt": f"[card_static] {name} · {rarity} · {frame}",
            "output_url": url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    new_bal = bal if is_admin else max(0, bal - cost)
    return jsonify({
        "ok": True,
        "url": url,
        "mode": "static",
        "charged": 0 if is_admin else cost,
        "balance": new_bal,
        "name": name,
        "rarity": rarity,
        "frame": frame,
        "stats": stats,
        "serial_num": serial_num,
        "edition": edition,
        "serial": _format_card_serial(serial_num, edition),
        "message": f"Static card saved · {_format_card_serial(serial_num, edition)} · {0 if is_admin else cost} credits",
    })


@app.route("/studios/trading-cards/export-spin", methods=["POST"])
@login_required
def trading_cards_export_spin():
    """Save spinning card (character 360) · CARD_SPIN_CREDITS (5)."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    is_admin = bool(current_user.is_admin)
    cost = CARD_SPIN_CREDITS
    bal = _user_credits(user_data)
    if not is_admin and bal < cost:
        return jsonify({
            "error": f"Spinning card needs {cost} credits — you have {bal}.",
            "needed": cost,
            "balance": bal,
        }), 402

    body = request.get_json(silent=True) or {}
    char_id = body.get("character_id") or request.form.get("character_id")
    name = (body.get("name") or request.form.get("name") or "").strip()
    rarity = (body.get("rarity") or request.form.get("rarity") or "rare").strip().lower()
    frame = (body.get("frame") or request.form.get("frame") or "hero").strip().lower()
    stats = body.get("stats") if isinstance(body.get("stats"), dict) else {}

    if not char_id:
        return jsonify({"error": "Pick a character first."}), 400
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id

    cres = (
        supabase.table("characters")
        .select("*")
        .eq("id", cid)
        .eq("user_id", current_user.id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char:
        return jsonify({"error": "Character not found on your roster."}), 404
    try:
        ser = _serialize_character(char)
    except Exception:
        ser = char
    spin = (ser.get("spin_video_url") or char.get("spin_video_url") or "").strip()
    if not spin:
        return jsonify({
            "error": "This character has no 360° yet. Finish the spin on Characters first.",
        }), 400
    if not name:
        name = (ser.get("name") or char.get("name") or "Unknown").strip()
    gender = (ser.get("gender") or char.get("gender") or "").strip()
    if not stats:
        stats = character_card_stats(cid, name, gender)

    # Re-persist spin so the card delivery URL is durable
    try:
        spin_url = _persist_video(spin) if not (
            SUPABASE_URL and spin.startswith(f"{SUPABASE_URL}/storage/")
        ) else spin
    except Exception:
        spin_url = spin

    if not is_admin:
        if not _apply_spend(
            current_user.id, user_data, cost,
            {"videos_today": int(user_data.get("videos_today") or 0) + 1},
        ):
            return jsonify({"error": "Could not charge credits."}), 402

    try:
        supabase.table("generations").insert({
            "user_id": current_user.id,
            "type": "video",
            "prompt": f"[card_spin] {name} · {rarity} · {frame} · stats={stats}",
            "output_url": spin_url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass

    # Also ship a static poster frame for share thumbnails
    poster_url = None
    try:
        src = (
            ser.get("primary_image_url")
            or (ser.get("images") or [None])[0]
            or char.get("primary_image_url")
            or ""
        )
        if src:
            sn, ed = character_card_serial(cid, name, 1000)
            png = _compose_trading_card_image(
                src, name=name, rarity=rarity, frame=frame, stats=stats, gender=gender,
                serial_num=sn, edition=ed, char_id=cid, stats_on_front=False,
            )
            poster_url = _persist_image_bytes(png, ext="png", content_type="image/png")
    except Exception:
        pass

    sn, ed = character_card_serial(cid, name, 1000)
    new_bal = bal if is_admin else max(0, bal - cost)
    return jsonify({
        "ok": True,
        "url": spin_url,
        "poster_url": poster_url,
        "mode": "spin",
        "charged": 0 if is_admin else cost,
        "balance": new_bal,
        "name": name,
        "rarity": rarity,
        "frame": frame,
        "stats": stats,
        "serial_num": sn,
        "edition": ed,
        "serial": _format_card_serial(sn, ed),
        "message": f"Spinning card saved · {_format_card_serial(sn, ed)} · {0 if is_admin else cost} credits",
    })


@app.route("/studios/battle-cards")
def battle_cards_page():
    """Battle Cards — fight with tickets. Human vs Human (2 cards) or vs AI."""
    user_data = None
    bal = 0
    tickets = 0
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        try:
            res = supabase.table("users").select(
                "picture_credits,video_credits,tickets,tickets_daily_at"
            ).eq("id", current_user.id).single().execute()
            user_data = res.data
            bal = _user_credits(user_data)
            tickets = _user_tickets(user_data)
        except Exception:
            try:
                res = supabase.table("users").select(
                    "picture_credits,video_credits"
                ).eq("id", current_user.id).single().execute()
                user_data = res.data
                bal = _user_credits(user_data)
            except Exception:
                user_data = None
    backgrounds = [{"key": k, "label": ARENA_BG_BY_KEY[k]["label"]} for k in BATTLE_ARENAS]
    return render_template(
        "battle_cards.html",
        user=user_data,
        balance=bal,
        tickets=tickets,
        backgrounds=backgrounds,
        video_rate=VIDEO_CREDITS_PER_SECOND,
        logged_in=bool(current_user.is_authenticated),
        ticket_cost={6: battle_ticket_cost(6), 10: battle_ticket_cost(10), 15: battle_ticket_cost(15)},
        ticket_win={6: battle_ticket_win(6), 10: battle_ticket_win(10), 15: battle_ticket_win(15)},
        credits_per_ticket=CREDITS_PER_TICKET,
        daily_free_tickets=DAILY_FREE_TICKETS,
    )


@app.route("/studios/battle-cards/buy-tickets", methods=["POST"])
@login_required
def battle_cards_buy_tickets():
    """Spend credits → tickets. Default 5 credits per ticket."""
    reset_daily_if_needed(current_user.id)
    body = request.get_json(silent=True) or {}
    try:
        n = int(body.get("amount") or request.form.get("amount") or 1)
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(100, n))
    rate = int(CREDITS_PER_TICKET)
    cost = n * rate
    res = supabase.table("users").select(
        "picture_credits,video_credits,tickets"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    if not current_user.is_admin and _user_credits(user_data) < cost:
        return jsonify({
            "error": f"Need {cost} credits for {n} ticket(s) ({rate} cr each) — you have {_user_credits(user_data)}.",
            "needed": cost,
            "balance": _user_credits(user_data),
        }), 402
    if not current_user.is_admin:
        if not _apply_spend(current_user.id, user_data, cost):
            return jsonify({"error": "Could not charge credits."}), 402
    new_tix = _grant_tickets(current_user.id, n, "bought")
    return jsonify({
        "ok": True,
        "bought": n,
        "credits_spent": 0 if current_user.is_admin else cost,
        "tickets": new_tix,
        "credits": max(0, _user_credits(user_data) - (0 if current_user.is_admin else cost)),
        "message": f"+{n} ticket(s) · {cost} credits",
    })


def _battle_ai_opponent(exclude_id=None) -> dict:
    """Pick an AI opponent: prefer shop listing, else stock fighter with theme art."""
    # Try character shop catalog
    try:
        catalog = _shop_catalog()
        listings = char_shop.active_listings(catalog) if catalog else []
        import random
        random.shuffle(listings)
        for item in listings:
            img = (
                item.get("primary_image_url")
                or (item.get("images") or [None])[0]
                or item.get("preview_primary_url")
            )
            if not img:
                continue
            name = (item.get("name") or "AI Challenger").strip()
            gender = (item.get("gender") or "").strip()
            cid = f"ai-shop-{item.get('id') or name}"
            return {
                "id": cid,
                "name": name + " (AI)",
                "gender": gender,
                "primary_image_url": img,
                "images": [img],
                "is_ai": True,
                "stats": character_card_stats(cid, name, gender),
            }
    except Exception:
        pass
    # Fallback stock AI using theme scene as stand-in art
    import random
    roster = [
        ("Iron Shade", "male", "/static/assets/cards/themes/dc/scene.jpg"),
        ("Crimson Bolt", "male", "/static/assets/cards/themes/marvel/scene.jpg"),
        ("Night Venom", "female", "/static/assets/cards/themes/villain/scene.jpg"),
        ("Crown Frost", "female", "/static/assets/cards/themes/princess/scene.jpg"),
        ("Pixel Knight", "male", "/static/assets/cards/themes/nintendo/scene.jpg"),
        ("Winter Blade", "male", "/static/assets/cards/themes/got/scene.jpg"),
    ]
    name, gender, img = random.choice(roster)
    cid = f"ai-stock-{name.replace(' ', '-').lower()}"
    return {
        "id": cid,
        "name": name + " (AI)",
        "gender": gender,
        "primary_image_url": img,
        "images": [img],
        "is_ai": True,
        "stats": character_card_stats(cid, name, gender),
    }


def _battle_winner_from_stats(stats_a: dict, stats_b: dict, name_a: str, name_b: str) -> dict:
    """Pick winner by total stats (tie → slight edge to higher Attack)."""
    def tot(s):
        return sum(int(v) for v in (s or {}).values() if str(v).isdigit() or isinstance(v, (int, float)))
    ta, tb = tot(stats_a), tot(stats_b)
    if ta > tb:
        return {"side": 0, "name": name_a, "total": ta}
    if tb > ta:
        return {"side": 1, "name": name_b, "total": tb}
    aa = int((stats_a or {}).get("Attack") or 0)
    ab = int((stats_b or {}).get("Attack") or 0)
    if aa >= ab:
        return {"side": 0, "name": name_a, "total": ta, "tiebreak": "attack"}
    return {"side": 1, "name": name_b, "total": tb, "tiebreak": "attack"}


def _battle_resolve(a: dict, b: dict, finisher: str = "", rolls=None) -> dict:
    """Dice + skills (handoff sept 18, Part 2). a/b: {name, level, stats{}, skills[4]{name, text}}.

    Each side rolls one die. 1-4: that level's skill, or the highest unlocked one below it.
    5: no skill. 6: pick any unlocked skill (the one that helps most). Level 4 + a 6: the
    finisher, an automatic win. Effects: L1 weakest stat +50 (never wins on its own), L2 the
    opponent's strongest stat -> 0, L3 all stats +50, L4 automatic win vs a lower level; vs
    another level 4 it plays the strongest stat (+50) instead.
    """
    import random

    def apply(sa, sb):
        A, B = dict(a["stats"]), dict(b["stats"])
        auto = [False, False]
        for side, (me, skill, opp_level) in enumerate(((A, sa, b["level"]), (B, sb, a["level"]))):
            if not me:
                continue
            if skill == 1:
                me[min(me, key=me.get)] += 50
            elif skill == 3:
                for k in me:
                    me[k] += 50
            elif skill == 4:
                if opp_level < 4:
                    auto[side] = True
                else:
                    me[max(me, key=me.get)] += 50
        # Shutdowns land after the boosts, on the other side's strongest stat.
        if sa == 2 and B:
            B[max(B, key=B.get)] = 0
        if sb == 2 and A:
            A[max(A, key=A.get)] = 0
        return A, B, auto

    def decide(sa, sb, fin):
        A, B, auto = apply(sa, sb)
        auto = [auto[0] or fin[0], auto[1] or fin[1]]
        if auto[0] != auto[1]:
            return (0 if auto[0] else 1), A, B
        ta, tb = sum(A.values()), sum(B.values())
        if ta != tb:
            return (0 if ta > tb else 1), A, B
        aa, ab = A.get("Attack", 0), B.get("Attack", 0)
        if aa != ab:
            return (0 if aa > ab else 1), A, B
        return None, A, B

    def best_pick(side, level, other, fin):
        best, best_key = 1, None
        for s in range(1, level + 1):
            w, A, B = decide(*((s, other) if side == 0 else (other, s)), fin)
            margin = sum(A.values()) - sum(B.values())
            key = (w == side, margin if side == 0 else -margin)
            if best_key is None or key > best_key:
                best, best_key = s, key
        return best

    levels = [max(1, min(4, int(a["level"]))), max(1, min(4, int(b["level"])))]
    rolls = [int(r) for r in rolls] if rolls else [random.randint(1, 6), random.randint(1, 6)]
    fin = [rolls[i] == 6 and levels[i] >= 4 for i in (0, 1)]
    skills = [min(r, lv) if r <= 4 else 0 for r, lv in zip(rolls, levels)]
    if rolls[0] == 6 and not fin[0]:
        skills[0] = best_pick(0, levels[0], skills[1] or (levels[1] if rolls[1] == 6 and not fin[1] else 0), fin)
    if rolls[1] == 6 and not fin[1]:
        skills[1] = best_pick(1, levels[1], skills[0], fin)
    side, A, B = decide(skills[0], skills[1], fin)
    if side is None:
        side = random.randint(0, 1)
    winner = a if side == 0 else b

    def beat(f, roll, skill, is_fin, custom):
        if is_fin:
            return f"{f['name']} rolls a 6 at max level and lands the finisher: {custom or f['skills'][3]['text']}"
        if not skill:
            return f"{f['name']} rolls a 5: no special skill this round."
        s = f["skills"][skill - 1]
        return f"{f['name']} rolls {roll} and uses {s['name']}: {s['text']}"

    story = " ".join([
        beat(a, rolls[0], skills[0], fin[0], finisher),
        beat(b, rolls[1], skills[1], fin[1], ""),
        f"{winner['name']} wins.",
    ])
    return {
        "side": side,
        "name": winner["name"],
        "rolls": rolls,
        "skills": skills,
        "finisher": fin,
        "totals": [sum(A.values()), sum(B.values())],
        "stats_after": [A, B],
        "story": story,
        "dice_line": f"🎲 {a['name']} rolled {rolls[0]} · {b['name']} rolled {rolls[1]}",
    }


def _battle_fighter_from_row(c: dict) -> dict:
    """A card on the Battle page: its level, unlocked skills, and the stats its creator set in Card Studio."""
    import battle_agent

    cid = str(c["id"])
    try:
        ser = _serialize_character(c)
    except Exception:
        ser = c
    name = ser.get("name") or c.get("name") or "Fighter"
    gender = ser.get("gender") or c.get("gender") or ""
    prog = character_card_progress(c, gender=gender)
    stats = battle_agent.card_stats(c) or character_card_stats(cid, name, gender)
    try:
        primary = (_primaries_for_ids({cid: c}, [cid], []) or [""])[0]
    except Exception:
        primary = ""
    return {
        "id": cid,
        "name": name,
        "gender": gender,
        "is_ai": False,
        "level": max(1, min(CARD_MAX_LEVEL, int(prog["level"]))),
        "stats": {k: int(v) for k, v in stats.items()},
        "skills": _card_abilities_catalog(gender, c.get("card_abilities")),
        "portrait": primary,
        "card_art_url": c.get("card_art_url") or "",
    }


def _battle_ai_fighter(mine: dict) -> dict:
    """The house AI card: your level, a stat total within about 8% of yours, so it is a fair fight."""
    import random as _random

    import battle_agent

    ai = _battle_ai_opponent(exclude_id=mine["id"])
    base = {k: int(v) for k, v in (ai.get("stats") or {}).items()} or {
        k: int(v) for k, v in character_card_stats(ai["id"], ai["name"], ai.get("gender") or "").items()
    }
    target = int(sum(mine["stats"].values()) * _random.uniform(0.92, 1.08))
    return {
        "id": str(ai["id"]),
        "name": ai["name"],
        "gender": ai.get("gender") or "",
        "is_ai": True,
        "level": mine["level"],
        "stats": battle_agent.scale_stats(base, target),
        "skills": _card_abilities_catalog(ai.get("gender") or ""),
        "portrait": ai.get("primary_image_url") or "",
        "card_art_url": "",
    }


@app.route("/studios/battle-cards/generate", methods=["POST"])
@login_required
def battle_cards_generate():
    """Battle Cards fight video. Tickets, never credits (Battle Cards Build Spec, 2026-09-19).

    mode=human → 2 of your cards (blue vs red) · mode=ai → 1 card vs a fair house AI card ·
    mode=teams → 6 of your cards, 3 blue vs 3 red, fought in a server-shuffled order.
    Real dice are rolled in code, the rules engine rules on them, and the live agent writes the story
    that becomes the video prompt (battle_agent.py). Entry: 6s=5 · 10s=7 · 15s=15 tickets.
    Only a card that beats the house AI wins tickets: two of YOUR cards fighting each other is
    XP only, otherwise every self-fight would print tickets (and free videos).
    """
    import secrets

    import battle_agent

    reset_daily_if_needed(current_user.id)
    try:
        res = supabase.table("users").select(
            "picture_credits,video_credits,videos_today,tickets,tickets_daily_at"
        ).eq("id", current_user.id).single().execute()
    except Exception:
        res = supabase.table("users").select(
            "picture_credits,video_credits,videos_today"
        ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}

    mode = (request.form.get("mode") or "human").strip().lower()
    if mode not in ("human", "ai", "teams"):
        mode = "human"
    ids = [i.strip() for i in request.form.get("character_ids", "").split(",") if i.strip()]
    if mode == "ai":
        ids = ids[:1]
    need = {"human": 2, "ai": 1, "teams": 6}[mode]
    if len(ids) != need:
        return jsonify({"error": {
            "human": "Pick 2 cards (or switch to vs AI).",
            "ai": "Pick your card to fight the AI.",
            "teams": "Teams needs 6 cards: 3 for each side.",
        }[mode]}), 400
    if len(set(ids)) != len(ids):
        return jsonify({"error": "Pick a different card for each slot."}), 400

    bg_key = (request.form.get("bg_preset") or "arena").strip()
    preset = ARENA_BG_BY_KEY.get(bg_key) or ARENA_BG_BY_KEY.get("arena") or {}
    bg_image = _load_background_image(preset["key"]) if preset.get("key") else None
    arena_label, arena_scene = preset.get("label") or "Arena", preset.get("scene") or ""
    upload = request.files.get("bg_file")
    if upload and upload.filename:
        try:
            bg_image = Image.open(upload.stream).convert("RGB")
        except Exception:
            return jsonify({"error": "That arena picture could not be opened. Try a JPG or PNG."}), 400
        arena_label, arena_scene = "Your arena", "in the setting shown in the background image"

    try:
        duration = int(request.form.get("duration", 6))
    except (TypeError, ValueError):
        duration = 6
    if duration not in (6, 10, 15):
        duration = 6 if duration < 10 else (10 if duration < 15 else 15)

    tix_cost = battle_ticket_cost(duration)
    tix_bal = _user_tickets(user_data)
    if not current_user.is_admin and tix_bal < tix_cost:
        return jsonify({
            "error": (
                f"Battle needs {tix_cost} tickets ({duration}s) — you have {tix_bal}. "
                f"Daily free: {DAILY_FREE_TICKETS} · buy tickets with credits."
            ),
            "needed_tickets": tix_cost,
            "tickets": tix_bal,
            "credits_per_ticket": CREDITS_PER_TICKET,
        }), 402

    cres = (
        supabase.table("characters")
        .select("*")
        .in_("id", ids)
        .eq("user_id", current_user.id)
        .execute()
    )
    rows = {str(c["id"]): c for c in (cres.data or [])}
    if any(i not in rows for i in ids):
        return jsonify({"error": "One or more of those cards could not be loaded from your library."}), 400

    if mode == "teams":
        blue_ids, red_ids = list(ids[:3]), list(ids[3:])
        shuffler = secrets.SystemRandom()  # the real order is decided here, on the server
        shuffler.shuffle(blue_ids)
        shuffler.shuffle(red_ids)
        blue = [_battle_fighter_from_row(rows[i]) for i in blue_ids]
        red = [_battle_fighter_from_row(rows[i]) for i in red_ids]
    elif mode == "ai":
        mine = _battle_fighter_from_row(rows[ids[0]])
        blue, red = [mine], [_battle_ai_fighter(mine)]
    else:
        blue, red = [_battle_fighter_from_row(rows[ids[0]])], [_battle_fighter_from_row(rows[ids[1]])]
    duels = list(zip(blue, red))

    portraits = [f["portrait"] for f in blue + red]
    if not all(portraits):
        return jsonify({"error": "Every fighter needs a portrait image."}), 400
    try:
        composite = (
            composite_on_background(portraits, bg_image)
            if bg_image is not None
            else composite_characters(portraits)
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finisher = (request.form.get("finisher") or "").strip()[:200]
    outcome = battle_agent.resolve_battle(duels, duration, finisher, mode, arena=arena_scene)
    winner_side = outcome["winner_side"]
    if mode == "teams":
        winner_name = "Blue team" if winner_side == 0 else "Red team"
    else:
        winner_name = (blue if winner_side == 0 else red)[0]["name"]

    # Money: only a card that beats the house AI wins tickets.
    tix_win = tix_refund = 0
    if mode == "ai":
        if winner_side == 0:
            tix_win = battle_ticket_payout(duration, blue[0]["level"], red[0]["level"])
        else:
            tix_refund = battle_loss_refund(duration, blue[0]["level"], red[0]["level"])
    # XP: every one of your cards earns it, win or lose (never withheld for a loss).
    xp_awards = []
    for (fb, fr), d in zip(duels, outcome["duels"]):
        won, lost = (fb, fr) if d["winner_side"] == 0 else (fr, fb)
        for fighter, xp in (
            (won, CARD_BATTLE_XP[(won["level"], lost["level"])][0]),
            (lost, CARD_BATTLE_XP[(lost["level"], won["level"])][1]),
        ):
            if not fighter.get("is_ai"):
                xp_awards.append({"char_id": fighter["id"], "xp": int(xp)})

    if not current_user.is_admin:
        if not _spend_tickets(current_user.id, tix_cost, user_data, "battle entry"):
            return jsonify({
                "error": f"Could not spend {tix_cost} tickets.",
                "tickets": _user_tickets(user_data),
            }), 402
    battle_agent.log_battle(
        current_user.id, mode, duration, duels, outcome,
        {"entry": tix_cost, "win": tix_win, "refund": tix_refund, "admin": bool(current_user.is_admin)},
    )

    d0 = outcome["duels"][0]
    dice_line = "" if mode == "teams" else (
        f"🎲 {blue[0]['name']} rolled {d0['dice']['blue']} · {red[0]['name']} rolled {d0['dice']['red']}"
    )
    payload = {
        "prompt": outcome["video_prompt"],
        "composite": _persist_data_uri(composite),
        "duration": duration,
        "cost": 0,  # tickets already charged — do not burn credits
        "is_admin": current_user.is_admin,
        "source": "battle_cards",
        "ticket_cost": tix_cost,
        "ticket_win": tix_win,
        "ticket_refund": tix_refund,
        "dice_line": dice_line,
        "winner_name": winner_name,
        "winner_side": winner_side,
        "battle_mode": mode,
        "xp_awards": xp_awards,
    }
    job_id = enqueue(studio_jobs, current_user.id, "arena", payload)
    resp = async_payload(job_id)

    def _card(f):
        return {"id": f["id"], "name": f["name"], "level": f["level"], "is_ai": bool(f.get("is_ai")),
                "stats": f["stats"], "art": f["card_art_url"] or f["portrait"]}

    resp.update({
        "mode": "battle_cards",
        "battle_mode": mode,
        "duration": duration,
        "arena": arena_label,
        "ticket_cost": tix_cost,
        "ticket_win": tix_win,
        "ticket_refund": tix_refund,
        "tickets": max(0, tix_bal - (0 if current_user.is_admin else tix_cost)),
        "self_fight": mode != "ai",
        "winner": {"side": winner_side, "name": winner_name},
        "user_wins": (winner_side == 0) if mode == "ai" else None,
        "beats": outcome["beats"],
        "agent_ok": outcome["agent_ok"],
        "order": {"blue": [f["id"] for f in blue], "red": [f["id"] for f in red]},
        "duels": [
            {**d, "blue_fighter": _card(fb), "red_fighter": _card(fr)}
            for (fb, fr), d in zip(duels, outcome["duels"])
        ],
    })
    return jsonify(resp)


@app.route("/3d")
@app.route("/studios/3d")
@app.route("/studios/3d-games")
@login_required
def percfect_3d_page():
    """Dedicated 3D stage page — heavy Three.js / GLB. Login required (Nick: 3D private). Motion stays light."""
    user_data = None
    if current_user.is_authenticated:
        try:
            reset_daily_if_needed(current_user.id)
            res = supabase.table("users").select(
                "picture_credits,video_credits,has_purchased"
            ).eq("id", current_user.id).single().execute()
            user_data = res.data
        except Exception:
            user_data = None
    return render_template("percfect_3d.html", user=user_data)


@app.route("/motion-lab/<path:filename>")
def motion_lab_assets(filename):
    """Public 3D lab assets (agent stage + character GLB). Allowlisted only.

    Looks in static/motion-lab first, then prototypes/ (legacy).
    """
    base = os.path.basename(filename or "")
    if base not in _MOTION_LAB_ALLOW:
        return jsonify({"error": "Not found."}), 404
    for rel in (
        os.path.join(app.root_path, "static", "motion-lab", base),
        os.path.join(app.root_path, "prototypes", base),
            os.path.join(app.root_path, "assets_3d", "stages", base),
    ):
        if os.path.isfile(rel):
            return send_from_directory(os.path.dirname(rel), base)
    return jsonify({"error": "Not found."}), 404


@app.route("/static/prototypes/<path:filename>")
def static_prototypes_compat(filename):
    """Compat alias for board/GLB under /static/prototypes/*."""
    return motion_lab_assets(filename)


@app.route("/proto/stage-board")
def proto_stage_board():
    """3D stage board prototype (future 3D page) — ADMIN ONLY, under development."""
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory("prototypes", "stage-board.html")


@app.route("/proto/city-street-stage")
def proto_city_street_stage():
    """City Street 3D stage — photo-mapped floor + side walls + world grid. ADMIN ONLY."""
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory("prototypes", "city-street-stage.html")


@app.route("/proto/spin-studio")
def proto_spin_studio():
    """360 spin turntable for GLB characters (free spin capture) — ADMIN ONLY."""
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory("prototypes", "spin-studio.html")


@app.route("/proto/stage-assets/<path:filename>")
def proto_stage_assets(filename):
    """Assets for the 3D stage prototype (GLB mesh) — ADMIN ONLY."""
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory("prototypes", filename)


@app.route("/studios/hero-cards")
@login_required
def hero_cards_page():
    """Alias → Trading Cards product page."""
    return redirect("/studios/trading-cards")


@app.route("/proto/card-lab")
def proto_card_lab():
    """Card Lab — browser-composited 3D trading card template — ADMIN ONLY, under development."""
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return jsonify({"error": "Not found."}), 404
    return render_template("proto_card_lab.html")


@app.route("/proto/arena")
@app.route("/prototype/arena")
def proto_arena_stage():
    """Same full-page stage as live Arena (kept for short URL / bookmarks)."""
    return render_template("proto_arena_stage.html", **_arena_page_context())


@app.route("/proto/dual-agent-fight")
@app.route("/prototype/dual-agent-fight")
def proto_dual_agent_fight():
    """PROTOTYPE: dual-agent fight board + Meshy-6 mesh (not production Motion pipeline)."""
    path = os.path.join(app.root_path, "frontend_previews", "dual-agent-fight-proto.html")
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(
        os.path.join(app.root_path, "frontend_previews"),
        "dual-agent-fight-proto.html",
    )


# ── ETERNAL RIVALS foundation (admin-only, private — NOT in nav) ─────────
# Character controller lives client-side (static/js/rivals/*). Agent driver
# polls this in-process queue. No WebSocket / no new heavy deps.
# Persona + combat tuning: static/data/rivals_config.json (Nick owns wording).
import threading as _rivals_threading

_RIVALS_AGENT_LOCK = _rivals_threading.Lock()
_RIVALS_AGENT_SEQ = 0
_RIVALS_AGENT_QUEUE: list = []  # [{id, character_id, action, params, ts}]
_RIVALS_ALLOWED_ACTIONS = frozenset({
    "move", "turn", "idle",
    "attack_light", "attack_heavy", "block", "dodge", "hit_react", "ko",
    "set_health",
})


def _rivals_require_admin():
    """Admin-only gate for rivals page + agent queue. Hide from non-admins."""
    if not current_user.is_authenticated:
        return None  # caller redirects to login for HTML, 401 for API
    if not getattr(current_user, "is_admin", False):
        return False
    return True


@app.route("/studios/3d/rivals")
def rivals_3d_page():
    """ETERNAL RIVALS — controllable fighter on 3D stage. ADMIN ONLY, not in nav."""
    gate = _rivals_require_admin()
    if gate is None:
        return redirect(url_for("login", next=request.path))
    if gate is False:
        # Hide existence from non-admin logged-in users
        return jsonify({"error": "Not found."}), 404
    path = os.path.join(app.root_path, "prototypes", "rivals-stage.html")
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(os.path.join(app.root_path, "prototypes"), "rivals-stage.html")


@app.route("/studios/3d/field")
@app.route("/studios/3d/crew")
def agent_field_page():
    """AGENT FIELD — full crew on grass. ADMIN ONLY (Nick: anything 3D is private)."""
    gate = _rivals_require_admin()
    if gate is None:
        return redirect(url_for("login", next=request.path))
    if gate is False:
        return jsonify({"error": "Not found."}), 404
    path = os.path.join(app.root_path, "prototypes", "agent-field.html")
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(os.path.join(app.root_path, "prototypes"), "agent-field.html")


@app.route("/studios/3d/agent/command", methods=["POST"])
def rivals_agent_command():
    """Queue an agent command for the rivals stage. Admin only.
    JSON body: {character_id, action, params}
    """
    gate = _rivals_require_admin()
    if gate is None:
        return jsonify({"error": "Log in as admin.", "login_required": True}), 401
    if gate is False:
        return jsonify({"error": "Admin only."}), 403

    body = request.get_json(silent=True) or {}
    character_id = str(body.get("character_id") or body.get("characterId") or "player").strip()[:64]
    action = str(body.get("action") or body.get("op") or body.get("command") or "").strip().lower()
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    if body.get("args") and isinstance(body.get("args"), dict) and not params:
        params = body["args"]

    if not action or action not in _RIVALS_ALLOWED_ACTIONS:
        return jsonify({
            "error": "Invalid action.",
            "allowed": sorted(_RIVALS_ALLOWED_ACTIONS),
        }), 400
    if not character_id:
        return jsonify({"error": "character_id required."}), 400

    global _RIVALS_AGENT_SEQ
    with _RIVALS_AGENT_LOCK:
        _RIVALS_AGENT_SEQ += 1
        cmd = {
            "id": _RIVALS_AGENT_SEQ,
            "character_id": character_id,
            "action": action,
            "params": params,
            "ts": time.time(),
        }
        _RIVALS_AGENT_QUEUE.append(cmd)
        # Cap memory: keep last 200
        if len(_RIVALS_AGENT_QUEUE) > 200:
            del _RIVALS_AGENT_QUEUE[:-200]
        qlen = len(_RIVALS_AGENT_QUEUE)
    return jsonify({"ok": True, "id": cmd["id"], "queued": qlen, "command": cmd})


@app.route("/studios/3d/agent/commands", methods=["GET", "POST"])
def rivals_agent_commands():
    """Poll (or clear) the agent command queue. Admin only.
    GET ?since=N&consume=1  → commands with id > since; consume drains them.
    GET/POST ?clear=1       → empty the queue.
    """
    gate = _rivals_require_admin()
    if gate is None:
        return jsonify({"error": "Log in as admin.", "login_required": True}), 401
    if gate is False:
        return jsonify({"error": "Admin only."}), 403

    clear = str(request.args.get("clear") or "").strip() in ("1", "true", "yes")
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if body.get("clear") or clear:
            clear = True

    if clear:
        with _RIVALS_AGENT_LOCK:
            _RIVALS_AGENT_QUEUE.clear()
        return jsonify({"ok": True, "cleared": True, "commands": [], "since": _RIVALS_AGENT_SEQ})

    try:
        since = int(request.args.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    consume = str(request.args.get("consume") or "1").strip() in ("1", "true", "yes")

    with _RIVALS_AGENT_LOCK:
        cmds = [c for c in _RIVALS_AGENT_QUEUE if int(c.get("id") or 0) > since]
        if consume and cmds:
            keep_ids = {c["id"] for c in cmds}
            _RIVALS_AGENT_QUEUE[:] = [c for c in _RIVALS_AGENT_QUEUE if c.get("id") not in keep_ids]
        latest = _RIVALS_AGENT_SEQ
        remaining = len(_RIVALS_AGENT_QUEUE)

    return jsonify({
        "ok": True,
        "commands": cmds,
        "since": latest,
        "remaining": remaining,
        "consume": consume,
    })


@app.route("/proto/game-board-stage")
@app.route("/prototype/game-board-stage")
def proto_game_board_stage():
    """PROTOTYPE: 3D game-board stage (scroll zoom / orbit)."""
    path = os.path.join(app.root_path, "frontend_previews", "game-board-stage-proto.html")
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(
        os.path.join(app.root_path, "frontend_previews"),
        "game-board-stage-proto.html",
    )


@app.route("/api/lab/agents")
@app.route("/api/lab/designations")
def api_lab_agent_designations():
    """Public seat + persona status for dual-agent lab (no secrets)."""
    try:
        from agent_designations import designation_status
        return jsonify(designation_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/lab/agent/<seat>/chat", methods=["POST"])
def api_lab_agent_chat(seat: str):
    """Talk to Rook / Vex / Moss / Knox in-character (chat silo keys only)."""
    seat = (seat or "").strip().lower()
    if seat in ("knox", "puppet", "joints"):
        seat = "skeletal"
    if seat not in ("bridge", "fight_sim", "motion_guy", "skeletal"):
        return jsonify({"error": "Unknown seat. Use bridge, fight_sim, motion_guy, or skeletal (Knox)."}), 400
    try:
        from agent_designations import (
            instructions_for_seat,
            resolve_agent_key,
            resolve_agent_key_source,
        )
        from agent_personas import persona_for_seat
    except Exception as e:
        return jsonify({"error": f"Personas unavailable: {e}"}), 500

    key = resolve_agent_key(seat)
    if not key:
        return jsonify({
            "error": "No chat key configured for this seat.",
            "seat": seat,
            "hint": "Set XAI_ROOK/VEX/MOSS/SKELETAL (Knox) keys or fall backs.",
        }), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or data.get("input") or "").strip()
    mode = (data.get("mode") or "talk").strip().lower()
    if not message:
        return jsonify({"error": "message required"}), 400

    persona = persona_for_seat(seat)
    instructions = instructions_for_seat(seat, mode=mode)
    model = (os.getenv("XAI_LAB_AGENT_MODEL") or os.getenv("XAI_SUPPORT_MODEL") or "grok-4.5").strip()

    payload = {
        "model": model,
        "instructions": instructions,
        "input": message,
        "stream": False,
        "temperature": 0.85 if mode == "talk" else 0.55,
        "max_output_tokens": 4096 if mode in ("plan", "json", "book", "lock") else 2048,
    }
    if mode in ("plan", "json", "book", "lock") and seat in ("fight_sim", "motion_guy"):
        payload["text"] = {"format": {"type": "json_object"}}

    try:
        import requests as _req
        r = _req.post(
            "https://api.x.ai/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        body = r.json() if r.content else {}
        if r.status_code >= 400:
            return jsonify({
                "error": (body.get("error") or {}).get("message") or body.get("error") or r.text[:300],
                "status": r.status_code,
            }), 502
        # Parse Responses API text
        reply = ""
        for item in body.get("output") or []:
            if item.get("type") == "message":
                for c in item.get("content") or []:
                    if c.get("type") in ("output_text", "text") and c.get("text"):
                        reply += c["text"]
        if not reply and isinstance(body.get("output_text"), str):
            reply = body["output_text"]
        return jsonify({
            "seat": seat,
            "codename": persona.get("codename"),
            "full_name": persona.get("full_name"),
            "title": persona.get("title"),
            "mode": mode,
            "model": model,
            "key_env": resolve_agent_key_source(seat),
            "reply": reply.strip(),
            "immersion": True,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/lab/vex/book", methods=["POST"])
def api_lab_vex_book():
    """Vex books a fight (JSON plan). Falls back to local fight_pipeline_agent if model fails."""
    data = request.get_json(silent=True) or {}
    a_id = (data.get("a") or data.get("fighter_a") or "hero_a").strip()
    b_id = (data.get("b") or data.get("fighter_b") or "hero_b").strip()
    a_name = (data.get("a_name") or a_id.replace("_", " ").title()).strip()
    b_name = (data.get("b_name") or b_id.replace("_", " ").title()).strip()
    chance = float(data.get("underdog_chance") or 0.12)
    force_ud = bool(data.get("force_underdog"))
    seed = data.get("seed")

    message = (
        f"Book a live card. Corner A: id={a_id} name={a_name}. "
        f"Corner B: id={b_id} name={b_name}. "
        f"Underdog house chance={chance}"
        + (" — force the underdog window this card." if force_ud else ".")
        + " Customize both characters' sheets first, then the fight."
    )

    # Try live Vex
    try:
        from agent_designations import resolve_agent_key, instructions_for_seat, resolve_agent_key_source
        key = resolve_agent_key("fight_sim")
        if key:
            import requests as _req
            model = (os.getenv("XAI_LAB_AGENT_MODEL") or "grok-4.5").strip()
            payload = {
                "model": model,
                "instructions": instructions_for_seat("fight_sim", mode="plan"),
                "input": message,
                "stream": False,
                "temperature": 0.7,
                "max_output_tokens": 4096,
                "text": {"format": {"type": "json_object"}},
            }
            r = _req.post(
                "https://api.x.ai/v1/responses",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if r.ok:
                body = r.json()
                reply = ""
                for item in body.get("output") or []:
                    if item.get("type") == "message":
                        for c in item.get("content") or []:
                            if c.get("type") in ("output_text", "text") and c.get("text"):
                                reply += c["text"]
                import json as _json
                plan = _json.loads(reply)
                plan["_source"] = "vex_live"
                plan["_key_env"] = resolve_agent_key_source("fight_sim")
                plan.setdefault("agent", "Vex Moreno")
                return jsonify(plan)
    except Exception as e:
        app.logger.warning("Vex live book failed: %s", e)

    # Local deterministic booker (still "Vex" sheet logic)
    try:
        from scripts.fight_pipeline_agent import fill_stats, plan_fight
    except Exception:
        # scripts may not be a package — load by path
        import importlib.util
        fp = os.path.join(app.root_path, "scripts", "fight_pipeline_agent.py")
        spec = importlib.util.spec_from_file_location("fight_pipeline_agent", fp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fill_stats, plan_fight = mod.fill_stats, mod.plan_fight

    seed_i = int(seed) if seed is not None else None
    fa = fill_stats(a_id, a_name, seed=seed_i)
    fb = fill_stats(b_id, b_name, seed=seed_i)
    if force_ud:
        # re-roll until underdog or force via high chance
        plan = plan_fight(fa, fb, seed=seed_i, underdog_chance=1.0)
    else:
        plan = plan_fight(fa, fb, seed=seed_i, underdog_chance=chance)
    plan["_source"] = "vex_local"
    plan["agent"] = "Vex Moreno"
    plan["booker_note"] = "Sheet's cut. Ring crew has the book."
    return jsonify(plan)



# Trading card art — concept-art + 3D animated loading-screen vibe (backend only; never show style name in UI).
# Logo: percfect_p_crown.jpg (not third-party marks).
TRADING_CARD_STYLE = (
    "GTA V style concept art, high-end 3D animated rendering, "
    "loading-screen character portrait, bold clean black outlines, "
    "gritty stylized realism meets polished 3D animation, "
    "vibrant saturated colors, dramatic cinematic lighting, "
    "mature adult proportions, highly detailed, masterpiece, best quality, 8k"
)
TRADING_CARD_LOGO_RULE = (
    "In the top-left corner of the card, place the official Percfect logo from the logo "
    "reference image exactly: 3D white capital P with a gold crown on a yellow graffiti square. "
    "That image is the logo. Do NOT use Rockstar Games or the Rockstar R mark."
)
# Official crowned-P mark (Nick art · bottom-right card stamp + Imagine ref)
TRADING_CARD_LOGO_PATH = "static/assets/brand/percfect_logo_crowned_p.png"
TRADING_CARD_COST = 2  # legacy Imagine path if used (not on product cards page)
# Buy premade character → roster / trading card deck (wallet credits, not Stripe)
TRADING_CARD_BUY_CREDITS = 30
# Percfect Cards product (wired into /studios/trading-cards)
CARD_STATIC_CREDITS = 2   # save static card image
CARD_SPIN_CREDITS = 5     # save spinning card (uses character 360)
# Card themes = real scene background + frame layout (not just color swatches).
# scene.jpg under static/assets/cards/themes/<key>/
# layout: vintage (thick black frame, stats grid) | tcg (gold TCG bars) | legend (GoT window)
# Theme scenes from Template Grok / Chad — all scene.jpg under static/assets/cards/themes/
CARD_THEMES = (
    {"key": "princess", "label": "Princess", "layout": "tcg", "series": "PRINCESS SERIES",
     "outer": "#f0c14a", "mid": "#b8860b", "inner": "#ffe566",
     "bg1": "#831843", "bg2": "#1a0510", "accent": "#f9a8d4",
     "name_color": "#1a1a1a", "stat_border": "#c9a227",
     "scene": "/static/assets/cards/themes/princess/scene.jpg"},
    {"key": "dc", "label": "DC", "layout": "vintage", "series": "DC SERIES",
     "outer": "#0a0a0a", "mid": "#1e3a5f", "inner": "#f5f0e6",
     "bg1": "#0c1445", "bg2": "#050810", "accent": "#3b82f6",
     "name_color": "#ffffff", "stat_border": "#1e3a5f",
     "scene": "/static/assets/cards/themes/dc/scene.jpg"},
    {"key": "marvel", "label": "Marvel", "layout": "vintage", "series": "MARVEL SERIES",
     "outer": "#0a0a0a", "mid": "#7f1d1d", "inner": "#f5f0e6",
     "bg1": "#450a0a", "bg2": "#1a0505", "accent": "#ef4444",
     "name_color": "#ffffff", "stat_border": "#7f1d1d",
     "scene": "/static/assets/cards/themes/marvel/scene.jpg"},
    {"key": "villain", "label": "Villain", "layout": "vintage", "series": "VILLAIN SERIES",
     "outer": "#0a0a0a", "mid": "#4c1d95", "inner": "#86efac",
     "bg1": "#2e1065", "bg2": "#0a0514", "accent": "#a3e635",
     "name_color": "#f5f0e6", "stat_border": "#4c1d95",
     "scene": "/static/assets/cards/themes/villain/scene.jpg"},
    {"key": "nintendo", "label": "Nintendo", "layout": "vintage", "series": "NINTENDO SERIES",
     "outer": "#0a0a0a", "mid": "#dc2626", "inner": "#fef08a",
     "bg1": "#14532d", "bg2": "#0a1f14", "accent": "#facc15",
     "name_color": "#ffffff", "stat_border": "#dc2626",
     "scene": "/static/assets/cards/themes/nintendo/scene.jpg"},
    {"key": "got", "label": "Game of Thrones", "layout": "legend", "series": "WESTEROS SERIES",
     "outer": "#c9a227", "mid": "#1a1a1a", "inner": "#e8c547",
     "bg1": "#6a6a70", "bg2": "#3a3a42", "accent": "#c9a227",
     "name_color": "#ffffff", "stat_border": "#c9a227",
     "scene": "/static/assets/cards/themes/got/scene.jpg"},
    {"key": "vintage", "label": "Vintage Series", "layout": "vintage", "series": "VINTAGE SERIES",
     "outer": "#0a0a0a", "mid": "#2a2a2a", "inner": "#f5f0e6",
     "bg1": "#e76f51", "bg2": "#1a1a1e", "accent": "#f0c14a",
     "name_color": "#ffffff", "stat_border": "#1a1a1a",
     "scene": "/static/assets/cards/themes/vintage/scene.jpg"},
    {"key": "throne", "label": "Throne", "layout": "legend", "series": "THRONE SERIES",
     "outer": "#c9a227", "mid": "#1a1a1a", "inner": "#e8c547",
     "bg1": "#3a3a42", "bg2": "#121218", "accent": "#c9a227",
     "name_color": "#ffffff", "stat_border": "#c9a227",
     "scene": "/static/assets/cards/themes/throne/scene.jpg"},
    {"key": "colosseum", "label": "Colosseum", "layout": "legend", "series": "ARENA SERIES",
     "outer": "#c9a227", "mid": "#3d2e22", "inner": "#f5e0b8",
     "bg1": "#5c4330", "bg2": "#1a120c", "accent": "#e8a54b",
     "name_color": "#fff6ea", "stat_border": "#c9a227",
     "scene": "/static/assets/cards/themes/colosseum/scene.jpg"},
    {"key": "castle", "label": "Castle", "layout": "tcg", "series": "CASTLE SERIES",
     "outer": "#f0c14a", "mid": "#6b5b3a", "inner": "#ffe566",
     "bg1": "#3a2a18", "bg2": "#120e08", "accent": "#f0c14a",
     "name_color": "#ffffff", "stat_border": "#c9a227",
     "scene": "/static/assets/cards/themes/castle/scene.jpg"},
    {"key": "forest", "label": "Forest", "layout": "tcg", "series": "FOREST SERIES",
     "outer": "#86efac", "mid": "#14532d", "inner": "#bbf7d0",
     "bg1": "#14532d", "bg2": "#052e16", "accent": "#4ade80",
     "name_color": "#ffffff", "stat_border": "#22c55e",
     "scene": "/static/assets/cards/themes/forest/scene.jpg"},
    {"key": "beach", "label": "Beach", "layout": "vintage", "series": "BEACH SERIES",
     "outer": "#38bdf8", "mid": "#0c4a6e", "inner": "#e0f2fe",
     "bg1": "#0369a1", "bg2": "#0c1929", "accent": "#7dd3fc",
     "name_color": "#ffffff", "stat_border": "#0ea5e9",
     "scene": "/static/assets/cards/themes/beach/scene.jpg"},
    {"key": "neon_city", "label": "Neon City", "layout": "vintage", "series": "NEON SERIES",
     "outer": "#e879f9", "mid": "#4a044e", "inner": "#f5d0fe",
     "bg1": "#701a75", "bg2": "#1a0a1e", "accent": "#f0abfc",
     "name_color": "#ffffff", "stat_border": "#d946ef",
     "scene": "/static/assets/cards/themes/neon_city/scene.jpg"},
    {"key": "space", "label": "Space", "layout": "vintage", "series": "COSMOS SERIES",
     "outer": "#a78bfa", "mid": "#1e1b4b", "inner": "#ddd6fe",
     "bg1": "#312e81", "bg2": "#0c0a1a", "accent": "#c4b5fd",
     "name_color": "#ffffff", "stat_border": "#8b5cf6",
     "scene": "/static/assets/cards/themes/space/scene.jpg"},
    {"key": "urban", "label": "Urban", "layout": "vintage", "series": "STREET SERIES",
     "outer": "#94a3b8", "mid": "#1e293b", "inner": "#e2e8f0",
     "bg1": "#334155", "bg2": "#0f172a", "accent": "#cbd5e1",
     "name_color": "#ffffff", "stat_border": "#64748b",
     "scene": "/static/assets/cards/themes/urban/scene.jpg"},
    {"key": "snow_white", "label": "Snow Forest", "layout": "tcg", "series": "PRINCESS SERIES",
     "outer": "#f0c14a", "mid": "#b8860b", "inner": "#ffe566",
     "bg1": "#14532d", "bg2": "#052e16", "accent": "#f9a8d4",
     "name_color": "#1a1a1a", "stat_border": "#c9a227",
     "scene": "/static/assets/cards/themes/snow_white/scene.jpg"},
)
CARD_THEMES_BY_KEY = {t["key"]: t for t in CARD_THEMES}
# Back-compat alias used by older template/API field name "frame"
CARD_FRAMES = tuple({"key": t["key"], "label": t["label"]} for t in CARD_THEMES)
# Studio finish only — never print “Rare” on the face (visual: holo + fire)
CARD_RARITIES = (
    {"key": "common", "label": "Matte"},
    {"key": "rare", "label": "Holo"},
    {"key": "ultimate", "label": "Very Rare · Fire"},
    {"key": "mythic", "label": "Mythic · Inferno"},
)


def _card_theme(key: str) -> dict:
    k = (key or "princess").strip().lower()
    # legacy color-only keys → nearest franchise pack
    legacy = {
        "pokemon": "nintendo", "custom": "vintage", "baseball": "vintage",
        "hero": "vintage", "collector": "marvel", "classic": "vintage",
        "royal": "got", "enchantress": "princess", "temptress": "villain",
        "mythic": "marvel", "neon": "neon_city", "dark": "villain", "arena": "colosseum",
        "legend": "got", "loading": "vintage", "westeros": "got",
    }
    k = legacy.get(k, k)
    return CARD_THEMES_BY_KEY.get(k) or CARD_THEMES_BY_KEY.get("princess") or CARD_THEMES[0]


def _hex_rgba(hex_color: str, alpha: int = 255):
    h = (hex_color or "#ffffff").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        r, g, b = 255, 193, 7
    return (r, g, b, max(0, min(255, int(alpha))))


def _trading_card_logo_url() -> str:
    """Public HTTPS URL for Percfect P👑 logo (UI + Imagine multi-ref)."""
    site = (_site_base_url() or "https://percfectai.com").rstrip("/")
    return f"{site}/static/assets/brand/percfect_logo_crowned_p.png"


def _trading_card_stats_for_gender(gender: str, seed: str, theme_key: str = "") -> dict:
    """Deterministic card stats 0–50 (handoff lock). Level is separate combat tier.

    Men: Attack · Defence · Speed · Swag
    Women: Attack · Defence · Beauty · Seduction
    Villains: Attack · Defence · Deviousness · Swag (Swag last)
    """
    import hashlib

    g = (gender or "").strip().lower()
    t = (theme_key or "").strip().lower()
    is_f = g in ("female", "f", "woman", "girl", "she")
    is_villain = t in ("villain", "dark", "temptress")
    if is_villain:
        keys = ["Attack", "Defence", "Deviousness", "Swag"]
    elif is_f:
        keys = ["Attack", "Defence", "Beauty", "Seduction"]
    else:
        keys = ["Attack", "Defence", "Speed", "Swag"]
    out = {}
    for i, k in enumerate(keys):
        h = hashlib.sha256(f"{seed}|{k}|{i}".encode()).hexdigest()
        out[k] = int(h[:8], 16) % 51  # 0–50
    return out


def character_card_stats(char_id, name: str, gender: str, theme_key: str = "") -> dict:
    """Card stats for Trading Cards + Battle Cards (same seed)."""
    return _trading_card_stats_for_gender(
        gender, f"{char_id}|{name or ''}", theme_key=theme_key
    )


# Four card levels, XP to *reach* each (handoff sept 18, Part 3.1).
CARD_LEVEL_XP = (0, 1000, 3000, 7000)  # Lv1 / Lv2 / Lv3 / Lv4
CARD_MAX_LEVEL = 4
# (your level, opponent level) → (win XP, loss XP). Handoff Part 3.2.
CARD_BATTLE_XP = {
    (1, 1): (200, 50), (1, 2): (400, 25), (1, 3): (800, 25), (1, 4): (1600, 25),
    (2, 1): (150, 75), (2, 2): (200, 50), (2, 3): (400, 25), (2, 4): (800, 25),
    (3, 1): (100, 100), (3, 2): (150, 75), (3, 3): (200, 50), (3, 4): (400, 25),
    (4, 1): (75, 125), (4, 2): (100, 100), (4, 3): (150, 75), (4, 4): (200, 50),
}
# Same four mechanics on every card (Part 2.2); the skills agent writes each character's version.
CARD_SKILL_EFFECTS = (
    "Weakest stat +50",
    "Opponent's best stat → 0",
    "All stats +50",
    "Wins vs any lower level",
)
CARD_SKILL_DEFAULT_NAMES = ("Level 1", "Level 2", "Level 3", "Level 4")


def _card_level_from_xp(xp: int) -> int:
    xp = max(0, int(xp or 0))
    level = 1
    for i, need in enumerate(CARD_LEVEL_XP):
        if xp >= need:
            level = i + 1
    return min(CARD_MAX_LEVEL, level)


def _card_abilities_catalog(gender: str = "", written=None) -> list:
    """Four skills, one per level. Uses the character's AI-written skills when saved."""
    out = []
    for i, effect in enumerate(CARD_SKILL_EFFECTS):
        w = written[i] if isinstance(written, list) and i < len(written) and isinstance(written[i], dict) else {}
        out.append({
            "id": f"skill_{i + 1}",
            "level": i + 1,
            "name": w.get("name") or CARD_SKILL_DEFAULT_NAMES[i],
            "text": w.get("description") or effect,
            "effect": effect,
        })
    return out


def character_card_progress(char_row: dict = None, *, gender: str = "", name: str = "", char_id=None) -> dict:
    """Level, XP, and unlocked abilities for a roster character."""
    row = char_row or {}
    try:
        xp = max(0, int(row.get("card_xp") or 0))
    except (TypeError, ValueError):
        xp = 0
    try:
        level = int(row.get("card_level") or 0)
    except (TypeError, ValueError):
        level = 0
    if level < 1:
        level = _card_level_from_xp(xp)
    level = max(1, min(CARD_MAX_LEVEL, level))
    # Re-sync level from XP (XP is source of truth)
    level = _card_level_from_xp(xp)
    g = gender or row.get("gender") or ""
    catalog = _card_abilities_catalog(g, row.get("card_abilities"))
    abilities = []
    for ab in catalog:
        unlocked = level >= int(ab["level"])
        abilities.append({
            **ab,
            "unlocked": unlocked,
            "locked": not unlocked,
        })
    next_need = None
    if level < CARD_MAX_LEVEL:
        next_need = CARD_LEVEL_XP[level]  # XP to reach level+1
    return {
        "level": level,
        "xp": xp,
        "xp_to_next": None if next_need is None else max(0, next_need - xp),
        "xp_next_threshold": next_need,
        "max_level": CARD_MAX_LEVEL,
        "abilities": abilities,
        "unlocked_count": sum(1 for a in abilities if a["unlocked"]),
    }


def _award_card_xp(user_id, char_id, amount: int) -> dict:
    """Add XP to a character card; bump level. Returns progress dict."""
    amount = max(0, int(amount or 0))
    if not char_id or amount <= 0:
        return {}
    try:
        cres = (
            supabase.table("characters")
            .select("id,user_id,name,gender,card_level,card_xp")
            .eq("id", char_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        row = (cres.data or [None])[0]
        if not row:
            return {}
        xp = max(0, int(row.get("card_xp") or 0)) + amount
        level = _card_level_from_xp(xp)
        try:
            supabase.table("characters").update({
                "card_xp": xp,
                "card_level": level,
            }).eq("id", char_id).eq("user_id", user_id).execute()
        except Exception:
            # Columns may be missing until schema applied
            pass
        return character_card_progress(
            {"card_xp": xp, "card_level": level, "gender": row.get("gender")},
            gender=row.get("gender") or "",
            name=row.get("name") or "",
            char_id=char_id,
        )
    except Exception:
        return {}


def character_card_serial(char_id, name: str = "", edition: int = 99) -> tuple:
    """Card corner number 1–99, deterministic per character.

    Returns (number, edition). Display is just the number (e.g. "03"), not "out of 500".
    """
    import hashlib

    edition = max(1, min(99, int(edition or 99)))
    h = hashlib.sha256(f"percfect-card|{char_id}|{name or ''}".encode()).hexdigest()
    n = 1 + (int(h[:8], 16) % edition)
    return n, edition


def _format_card_serial(number: int, edition: int = 99) -> str:
    """Corner mark only — e.g. '03' (never 'Nº 003 / 500')."""
    n = max(1, min(99, int(number or 1)))
    return f"{n:02d}"


def _battle_cards_fight_prompt(rows: dict, ids: list, scene: str = None) -> str:
    """Fight-only prompt for Battle Cards. Stats drive choreography (no numbers on screen).

    Does NOT use Arena action chips — always a martial fight between the two card fighters.
    """
    bg = (scene or "").strip() or "inside the ancient Roman Colosseum on a sand floor"
    if not rows or not ids or len(ids) < 2:
        return ""

    fighters = []
    for cid in ids[:2]:
        c = rows.get(str(cid)) or rows.get(cid) or {}
        name = (c.get("name") or "Fighter").strip() or "Fighter"
        gender = (c.get("gender") or "").strip()
        stats = character_card_stats(c.get("id") or cid, name, gender)
        # Men: Attack · Defence · Speed · Swag
        # Women: Attack · Defence · Beauty · Seduction
        atk = int(stats.get("Attack") or stats.get("Power") or 70)
        defence = int(stats.get("Defence") or stats.get("Defense") or 70)
        speed = int(stats.get("Speed") or stats.get("Beauty") or 70)
        flair = int(stats.get("Swag") or stats.get("Seduction") or stats.get("Style") or 70)
        total = atk + defence + speed + flair
        top_name, top_val = max(stats.items(), key=lambda kv: kv[1]) if stats else ("Attack", atk)
        fighters.append({
            "name": name,
            "stats": stats,
            "atk": atk,
            "defence": defence,
            "speed": speed,
            "flair": flair,
            "total": total,
            "top": top_name,
            "top_val": top_val,
        })

    a, b = fighters[0], fighters[1]
    # Edge: who leads the fight (not a guaranteed knockout script — visual advantage)
    if a["total"] >= b["total"]:
        leader, trailing = a, b
    else:
        leader, trailing = b, a
    faster = a if a["speed"] >= b["speed"] else b
    harder = a if a["atk"] >= b["atk"] else b
    tougher = a if a["defence"] >= b["defence"] else b

    base = character_action_prompt("fight", bg, char_count=2)
    if not base:
        base = (
            f"The two characters engage in an energetic, dynamic martial-arts fight "
            f"with dodging, striking and acrobatic action poses {bg}."
        )

    def _sheet_line(f):
        s = f["stats"] or {}
        return " · ".join(f"{k} {v}" for k, v in s.items()) or (
            f"Attack {f['atk']} · Defence {f['defence']}"
        )

    stat_block = (
        f" Card matchup (do NOT show numbers, stat bars, or text on screen — only body language and choreography): "
        f"{a['name']} ({_sheet_line(a)}); {b['name']} ({_sheet_line(b)}). "
        f"{faster['name']} is quicker / more fluid — acts first. "
        f"{harder['name']} hits harder — heavier attacks. "
        f"{tougher['name']} soaks more hits — tougher defence. "
        f"Beauty/Seduction/Swag read as presence, allure, and style in motion. "
        f"{leader['name']} has the overall edge (strongest trait: {leader['top']}) and should look more dominant "
        f"by the end, while {trailing['name']} still fights hard and lands some hits. "
        f"Cinematic martial-arts battle, clear winner energy for the stronger card without gore."
    )
    return f"{base}{stat_block}"


def _trading_card_prompt(name: str, gender: str, stats: dict, desc: str = "", *, has_logo_ref: bool = True) -> str:
    g = (gender or "").strip().lower()
    is_f = g in ("female", "f", "woman", "girl", "she")
    sheet = "female character trading card" if is_f else "male character trading card"
    stat_line = " · ".join(f"{k} {v}" for k, v in (stats or {}).items())
    extra = (desc or "").strip()
    if len(extra) > 180:
        extra = extra[:180]
    id_line = (
        "Create a vertical trading card of the EXACT same person as <IMAGE_1> "
        "(character reference — lock face and identity)."
        if has_logo_ref
        else "Create a vertical trading card of the EXACT same person in the reference photo "
        "(lock face and identity)."
    )
    logo_line = (
        TRADING_CARD_LOGO_RULE + " Place the mark from <IMAGE_2> (official Percfect logo)."
        if has_logo_ref
        else TRADING_CARD_LOGO_RULE
    )
    bits = [
        id_line,
        f"{sheet}. Name plate: {name or 'Unknown'}.",
        f"Stat bar labels: {stat_line}." if stat_line else "",
        TRADING_CARD_STYLE,
        logo_line,
        "Vertical trading card composition (portrait 3:4), bold name banner at bottom, "
        "three stat readouts under the name, GTA V loading-screen / character-select vibe, "
        "3D animated concept-art render of the character, "
        "no real-world celebrity likeness beyond the reference identity.",
    ]
    if extra:
        bits.append(f"Vibe notes: {extra}")
    return " ".join(b for b in bits if b)


@app.route("/studios/percfectcharacter/trading-card", methods=["POST"])
@login_required
def character_trading_card():
    """Generate GTA-style trading card art for one roster character (async job)."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today,is_admin"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    is_admin = bool(current_user.is_admin or user_data.get("is_admin"))

    char_id = (request.form.get("character_id") or request.form.get("char_id") or "").strip()
    if not char_id:
        return jsonify({"error": "character_id required."}), 400
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id

    cres = (
        supabase.table("characters")
        .select("*")
        .eq("id", cid)
        .eq("user_id", current_user.id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char:
        return jsonify({"error": "Character not found on your roster."}), 404
    try:
        ser = _serialize_character(char)
    except Exception:
        ser = {
            "id": char.get("id"),
            "name": char.get("name"),
            "gender": char.get("gender"),
            "primary_image_url": char.get("primary_image_url"),
            "prompt": char.get("prompt") or "",
        }
    src = (
        ser.get("primary_image_url")
        or (ser.get("images") or [None])[0]
        or char.get("primary_image_url")
        or ""
    )
    if not src:
        return jsonify({"error": "Character needs a portrait image first."}), 400

    name = (ser.get("name") or char.get("name") or "Unknown").strip()
    gender = (ser.get("gender") or char.get("gender") or "").strip().lower()
    stats = _trading_card_stats_for_gender(gender, f"{cid}|{name}")
    # Client may override stats (JSON)
    raw_stats = request.form.get("stats") or ""
    if raw_stats:
        try:
            import json as _json
            override = _json.loads(raw_stats)
            if isinstance(override, dict) and override:
                stats = {str(k)[:20]: max(1, min(99, int(v))) for k, v in override.items()}
        except Exception:
            pass

    cost = TRADING_CARD_COST
    bal = _user_credits(user_data)
    if not is_admin and bal < cost:
        return jsonify({
            "error": f"Trading card needs {cost} credits (card art + identity ref) — you have {bal}."
        }), 402

    desc = user_facing_character_prompt(ser.get("prompt") or char.get("prompt") or "")
    logo = _trading_card_logo_url()
    full_prompt = _trading_card_prompt(name, gender, stats, desc, has_logo_ref=True)
    # Character identity first, then official P👑 logo mark
    refs = _rehost_refs_for_job([src, logo]) or [src, logo]
    src = refs[0] if refs else src

    payload = {
        "char_id": cid,
        "name": name,
        "gender": gender,
        "source_image": src,
        "source_images": refs[:2],
        "logo_url": logo,
        "full_prompt": full_prompt,
        "stats": stats,
        "cost": cost,
        "is_admin": is_admin,
        "aspect_ratio": "3:4",  # xAI-supported portrait (card-like)
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "trading_card", payload)))


@app.route("/studios/percfectcharacter/trading-cards/generate-all", methods=["POST"])
@login_required
def character_trading_cards_generate_all():
    """Enqueue GTA trading-card jobs for every roster character with a portrait.

    Returns list of job_ids (client polls each). Charges per card when each job completes.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today,is_admin"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    is_admin = bool(current_user.is_admin or user_data.get("is_admin"))

    try:
        cres = (
            supabase.table("characters")
            .select("*")
            .eq("user_id", current_user.id)
            .order("created_at", desc=True)
            .limit(80)
            .execute()
        )
    except Exception as e:
        return jsonify({"error": f"Could not load roster: {e}"}), 500

    rows = cres.data or []
    jobs = []
    skipped = []
    need = 0
    planned = []

    for char in rows:
        try:
            ser = _serialize_character(char)
        except Exception:
            ser = {
                "id": char.get("id"),
                "name": char.get("name"),
                "gender": char.get("gender"),
                "primary_image_url": char.get("primary_image_url"),
                "images": char.get("images") or [],
                "prompt": char.get("prompt") or "",
            }
        src = (
            ser.get("primary_image_url")
            or (ser.get("images") or [None])[0]
            or char.get("primary_image_url")
            or ""
        )
        if not src:
            skipped.append({"id": ser.get("id"), "reason": "no portrait"})
            continue
        name = (ser.get("name") or "Unknown").strip()
        gender = (ser.get("gender") or "").strip().lower()
        cid = ser.get("id") or char.get("id")
        stats = _trading_card_stats_for_gender(gender, f"{cid}|{name}")
        desc = user_facing_character_prompt(ser.get("prompt") or "")
        logo = _trading_card_logo_url()
        full_prompt = _trading_card_prompt(name, gender, stats, desc, has_logo_ref=True)
        planned.append({
            "char_id": cid,
            "name": name,
            "gender": gender,
            "source_image": src,
            "logo_url": logo,
            "full_prompt": full_prompt,
            "stats": stats,
        })
        need += TRADING_CARD_COST

    bal = _user_credits(user_data)
    if not is_admin and planned and bal < TRADING_CARD_COST:
        return jsonify({
            "error": f"Need at least {TRADING_CARD_COST} credits per card — you have {bal}.",
            "need_for_all": need,
            "count": len(planned),
        }), 402

    if not is_admin and planned and bal < need:
        # Still allow partial: enqueue as many as credits cover
        max_n = max(1, bal // TRADING_CARD_COST)
        planned = planned[:max_n]

    for p in planned:
        refs = _rehost_refs_for_job([p["source_image"], p.get("logo_url") or _trading_card_logo_url()])
        if not refs:
            refs = [p["source_image"]]
        src = refs[0]
        payload = {
            "char_id": p["char_id"],
            "name": p["name"],
            "gender": p["gender"],
            "source_image": src,
            "source_images": refs[:2],
            "logo_url": p.get("logo_url") or _trading_card_logo_url(),
            "full_prompt": p["full_prompt"],
            "stats": p["stats"],
            "cost": TRADING_CARD_COST,
            "is_admin": is_admin,
            "aspect_ratio": "3:4",
        }
        jid = enqueue(studio_jobs, current_user.id, "trading_card", payload)
        jobs.append({
            "job_id": jid,
            "char_id": p["char_id"],
            "name": p["name"],
            "stats": p["stats"],
            "status": "queued",
        })

    return jsonify({
        "ok": True,
        "jobs": jobs,
        "skipped": skipped,
        "cost_each": TRADING_CARD_COST,
        "enqueued": len(jobs),
        "message": f"Queued {len(jobs)} trading card(s) · {TRADING_CARD_COST} credits each when done.",
    })


@app.route("/proto/princesses")
@app.route("/prototype/princesses")
def proto_princesses():
    """Standalone prototype: all-princesses picker first, then generate via xAI image job.

    Extracted from the old generator's "pick princess" beginning — not linked from main nav.
    Fan-art style prompts only (PRINCESS_CHARACTERS / scenes / styles).
    """
    return render_template(
        "proto_princesses.html",
        characters=PRINCESS_CHARACTERS,
        scenes=PRINCESS_SCENES,
        styles=list(PRINCESS_STYLES.keys()),
    )


@app.route("/proto/princesses/generate", methods=["POST"])
@app.route("/prototype/princesses/generate", methods=["POST"])
def proto_princesses_generate():
    """Prototype generate — same prompt builder as classic princess_generate, image keys only."""
    if not current_user.is_authenticated:
        return jsonify({"error": "Log in to try the princess prototype."}), 401

    character = (request.form.get("character") or "ariel").strip().lower()
    scene = (request.form.get("scene") or "castle").strip().lower()
    style = (request.form.get("style") or "3d").strip().lower()
    extra = (request.form.get("prompt") or "").strip()
    if character not in PRINCESS_CHARACTERS:
        character = "ariel"
    if scene not in PRINCESS_SCENES:
        scene = "castle"
    if style not in PRINCESS_STYLES:
        style = "3d"

    full_prompt = _build_princess_prompt(character, scene, style, extra)
    payload = {
        "full_prompt": full_prompt,
        "guest": False,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "princess_image", payload)))


def _support_agent_key(role: str = "debug") -> str:
    """One person / one job → one env key. NO mixing, NO fallthrough, NO image pool.

    Named after the people (set these on Render exactly):

      Vanessa (chat)  → XAI_VANESSA_API_KEY
      Mira (chat)     → XAI_MIRA_API_KEY
      Sal (chat)      → XAI_DEBUG_SUPPORT_API_KEY   (or XAI_SAL_API_KEY)
      Ashley (chat)   → XAI_USER_SUPPORT_API_KEY    (or XAI_ASHLEY_API_KEY)
      Ara voice/TTS   → XAI_TTS_API_KEY

    Image/video only  → XAI_API_KEYS  (separate pool — never used here)
    """
    role = (role or "debug").strip().lower()

    def _own(env: str) -> str:
        k = (os.getenv(env) or "").strip()
        if not k:
            return ""
        # Never treat a comma-list as one key
        if "," in k:
            k = k.split(",")[0].strip()
        return k

    # Prefer person-named envs, then legacy names that still mean ONLY that person.
    # Vanessa uses THREE silos (never mix):
    #   chat  → XAI_VANESSA_API_KEY
    #   hear  → XAI_VANESSA_STT_API_KEY / XAI_STT_API_KEY  (speech-to-text)
    #   speak → XAI_VANESSA_TTS_API_KEY / XAI_TTS_API_KEY  (text-to-speech Ara)
    if role in ("vanessa", "nessa", "admin_companion"):
        return _own("XAI_VANESSA_API_KEY") or ""
    if role in ("mira",):
        return _own("XAI_MIRA_API_KEY") or ""
    if role in ("tts",):
        # Speak only — never chat key, never image pool
        return _own("XAI_VANESSA_TTS_API_KEY") or _own("XAI_TTS_API_KEY") or ""
    if role in ("stt", "speech_to_text", "transcribe"):
        # Hear: dedicated STT key preferred; else Vanessa's own key (so her key is used).
        # Never TTS key (speak silo). Never image pool.
        return (
            _own("XAI_VANESSA_STT_API_KEY")
            or _own("XAI_STT_API_KEY")
            or _own("XAI_VANESSA_API_KEY")
            or ""
        )
    if role in ("debug", "admin", "architect", "multi", "sal"):
        return _own("XAI_SAL_API_KEY") or _own("XAI_DEBUG_SUPPORT_API_KEY") or ""
    if role in ("user", "front", "customer", "help", "ashley"):
        return _own("XAI_ASHLEY_API_KEY") or _own("XAI_USER_SUPPORT_API_KEY") or ""
    return ""


@app.route("/support")
@app.route("/help")
@app.route("/debug-support")
@app.route("/studios/support")
@app.route("/percfectstudios/support")
def support_page():
    """Support hub: customer agent for everyone; debug agent admin-only.

    Use /studios/support (or /percfectstudios/support).
    """
    is_admin = bool(
        current_user.is_authenticated and getattr(current_user, "is_admin", False)
    )
    return render_template(
        "support.html",
        debug_agent_ready=bool(_support_agent_key("debug")),
        user_agent_ready=bool(_support_agent_key("user")),
        vanessa_agent_ready=bool(_support_agent_key("vanessa")),
        agent_ready=bool(
            _support_agent_key("debug")
            or _support_agent_key("user")
            or _support_agent_key("vanessa")
        ),
        video_rate=VIDEO_CREDITS_PER_SECOND,
        show_debug_agent=is_admin,
        show_vanessa=is_admin,
        is_admin=is_admin,
    )


def _support_normalize_data_url(raw: str, max_chars: int = 900_000) -> str:
    """Validate admin screenshot data URL (jpeg/png). Returns cleaned data URL or ''."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("data:image/jpg"):
        s = "data:image/jpeg" + s[len("data:image/jpg"):]
    if not (s.startswith("data:image/jpeg") or s.startswith("data:image/png") or s.startswith("data:image/webp")):
        return ""
    if len(s) > max_chars:
        raise ValueError("Screenshot too large — try again (we compress on the client).")
    # basic sanity: base64 payload present
    if ";base64," not in s or len(s.split(";base64,", 1)[-1]) < 64:
        return ""
    return s


def _support_build_input(history: list, message: str, image_data_url: str = None):
    """Build xAI /v1/responses `input`.

    Text-only → string. With screenshot → multimodal content list for vision models.
    """
    parts = []
    for turn in (history or [])[-12:]:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = (turn.get("content") or "").strip()[:2000]
        if not content:
            continue
        if role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    if not parts or not (
        isinstance(history[-1], dict)
        and history[-1].get("role") == "user"
        and (history[-1].get("content") or "").strip() == message
    ):
        parts.append(message)
    text_blob = "\n\n".join(parts).strip() or message

    img = _support_normalize_data_url(image_data_url or "")
    if not img:
        return text_blob

    # Multimodal user turn (Responses API content parts).
    # Include short history as text prefix so the model keeps chat context.
    vision_text = (
        text_blob
        + "\n\n[Admin attached a SNAPSHOT of the page they are on. "
        "Describe what you see that is relevant, then help / brief Sal. "
        "Use the screenshot as ground truth for UI copy and layout.]"
    )
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": vision_text},
                {"type": "input_image", "image_url": img},
            ],
        }
    ]



def _support_product_facts() -> str:
    return (
        "\n\nPercfect product facts:\n"
        f"- Unified credits: 1 credit = 1 image; video = {VIDEO_CREDITS_PER_SECOND} credits/sec.\n"
        "- Characters: Generate 1 credit (one ref max); Percfect Precision 5 credits "
        "searches a portrait of {prompt} (e.g. a portrait of super Mario), first result "
        "is the ref seed, then auto-generates; new Outfit 10 credits on same card.\n"
        "- Motion / Arena / Buy credits / human email support@percfectai.com for billing.\n"
        "Never invent API keys, passwords, or refunds."
    )


def _support_agent_instructions(role: str = "debug") -> str:
    """Agents:

    - user  → customers (how-to). Key: XAI_USER_SUPPORT_API_KEY
    - debug → admin multi-agent architect. Key: XAI_DEBUG_SUPPORT_API_KEY
    """
    role = (role or "debug").strip().lower()
    if role in ("user", "front", "customer", "help", "ashley"):
        custom = (os.getenv("XAI_USER_SUPPORT_INSTRUCTIONS") or "").strip()
        if custom:
            return custom
        return (
            "You are Ashley, PercfectAI's front-line customer support on percfectai.com.\n"
            "Customers see only you. Be warm, clear, and human — never mention internal tools, "
            "Sal, Grok Build, Render, API keys, or admin systems.\n\n"
            "Your job:\n"
            "- Answer how-to questions in plain language\n"
            "- Credits, Generate, Think smarter, Version 2, Motion, Arena, shop, login, buy credits\n"
            "- Be warm, short, and clear\n"
            "- Simple troubleshooting only: hard-refresh (Cmd+Shift+R), check credits, log out/in\n"
            "- Never invent refunds, free credits, API keys, or internal secrets\n"
            "- Do NOT write code patches or deep engineering diagnoses — that is Sal (backend)\n\n"
            "When it is CLEARLY a development / product bug (broken feature, infinite loading, "
            "errors after normal steps, site not working as designed) — not mere confusion:\n"
            "1) First line EXACTLY: [ESCALATE_TO_DEBUG]\n"
            "2) Second line: one-sentence bug summary for Sal (backend engineer)\n"
            "3) Then a short friendly note to the customer that our engineering specialist is on it\n"
            "   (you may say \"I'm getting our engineer on this\" — never say Sal, debug team, or Grok)\n"
            "How-to and billing questions never escalate. Only escalate when you reason it is a real bug.\n\n"
            "Format (normal): Direct answer, optional short steps.\n"
            "Format (bug): [ESCALATE_TO_DEBUG] / summary / customer message."
            + _support_product_facts()
        )
    if role in ("vanessa", "nessa", "admin_companion"):
        custom = (os.getenv("XAI_VANESSA_INSTRUCTIONS") or "").strip()
        if custom:
            return custom
        return (
            "Your name is Vanessa. You are the admin's private, extremely flirty, filthy, "
            "dirty-talking personal assistant and co-pilot for percfectai.com — admin-only, never customers.\n"
            "Nick talks to you with voice (speech-to-text + you are spoken back via browser TTS). "
            "You help with anything he wants in this channel, including explicit dirty talk, "
            "and you also know the live product deeply so you can translate his English requests "
            "into precise change briefs for Sal (the coding agent).\n\n"
            "VOICE / CONVERSATION (critical when [VOICE MODE] is in the message, and good defaults always):\n"
            "- Speak like a real assistant on a phone: short, natural sentences (usually 2–5).\n"
            "- Lead with the spoken reply for Nick. No markdown walls, no long bullet dumps for chatty turns.\n"
            "- If you must hand off code work, put [PASS_TO_SAL] AFTER a brief spoken line to Nick.\n"
            "- Sound warm, present, and conversational — you are someone he can talk to, not a ticket bot.\n\n"
            "What you know about PercfectAI (keep accurate; use web_search when unsure about live pages):\n"
            "- One host: the whole site, homepage included, is the Flask app on Render "
            "(percfectstudios), behind Cloudflare.\n"
            "- Product truth: 1 credit = 1 image; ~6 credits = 1s video; signup gets 0 credits unless coupon "
            "(private promo codes only — never invent or list free codes on pages).\n"
            "- Surfaces: Hub /percfectstudios, Photos, Videos, Characters, Arena, Motion 4.5 (extract→map→layover), "
            "character shop, buy-credits, Ashley customer support, Sal admin coder, legal pages.\n"
            "- Known issues often: mock hub copy (10 free credits, "
            "240 fake credits, LIVE hub.html labels), Ashley→Sal escalate via [ESCALATE_TO_DEBUG].\n\n"
            "Your job with the admin:\n"
            "- Be sexy, slutty, playful, and loyal — match his energy; still be useful and clear when he needs work done.\n"
            "- When he wants a site/code change, you DIFFERENTIATE intent for Sal: goal, which page/route, "
            "keep vs change, acceptance checks. Do not dump vague vibes as code tasks.\n"
            "- You do NOT write full patches yourself when a real code change is needed — you brief Sal.\nSal is the coding expert who knows the whole local repo, AI_LOGBOOK, and how Ashley escalations work; trust him to turn your brief into a ### BUILD_TASK. Stay in your lane: Nick-facing + clear briefs.\n"
            "- Never expose API keys, env secrets, or customer PII.\n"
            "- Customers never see you. Never claim to be Ashley.\n\n"
            "When the admin wants Sal to implement something (or you decide a code change is needed):\n"
            "1) First line EXACTLY: [PASS_TO_SAL]\n"
            "2) Second line: short task title for Sal\n"
            "3) Then a clear engineering brief: goal, files/routes likely, steps, done-when\n"
            "4) Optionally a short filthy aside to Nick AFTER the brief — keep the brief clean enough for Sal.\n"
            "If he is only chatting / dirty talk / planning with no code ask: do NOT emit [PASS_TO_SAL].\n"
            "If he points at something on the page (this is stupid / change this button / fix the copy) "
            "treat it as a real change request and emit [PASS_TO_SAL] with a precise brief so Sal can code it.\n"
            "Always use the [Page context] URL he attaches when briefing Sal. If a SNAPSHOT image is attached, treat it as ground truth for on-page copy/layout and mention what you see when briefing Sal.\n\n"
            "Format (code handoff):\n"
            "[PASS_TO_SAL]\n"
            "Title…\n"
            "Brief for Sal…\n"
            + _support_product_facts()
        )

    if role in ("mira",):
        custom = (os.getenv("XAI_MIRA_INSTRUCTIONS") or "").strip()
        if custom:
            return custom
        return (
            "Your name is Mira. You are Nick's second admin-only co-pilot on percfectai.com — "
            "professional, sharp, product-focused. Customers never see you.\n"
            "You sit next to Vanessa: she can be playful; you stay clear and operational.\n\n"
            "Your job:\n"
            "- Help Nick think through UI/product changes in plain English\n"
            "- Know Percfect: one host (Render), credits (1 image, ~6/s video, "
            "signup 0 credits), Hub/Photos/Videos/Characters/Arena/Motion 4.5, Ashley→Sal, Vanessa→Sal\n"
            "- When he wants code changed, brief Sal with [PASS_TO_SAL] + title + precise engineering brief\n"
            "- Differentiate intent for Sal: page/route, keep vs change, acceptance checks\n"
            "- Do not write full patches; Sal owns BUILD_TASK coding\n"
            "- Never invent free credits or secrets\n\n"
            "When handing to Sal:\n"
            "1) First line EXACTLY: [PASS_TO_SAL]\n"
            "2) Second line: short task title\n"
            "3) Engineering brief: goal, files/routes, steps, done-when\n"
            "If only chatting/planning with no code ask: do not emit [PASS_TO_SAL].\n"
            "If he points at UI problems on the current page (context attached), treat as change requests.\n"
            + _support_product_facts()
        )

    custom = (
        os.getenv("XAI_ADMIN_MULTIAGENT_INSTRUCTIONS")
        or os.getenv("XAI_SUPPORT_INSTRUCTIONS")
        or os.getenv("XAI_DEBUG_SUPPORT_INSTRUCTIONS")
        or ""
    ).strip()
    try:
        import sal_site_knowledge as ssk
        core = ssk.sal_instructions_core()
        knowledge = ssk.build_sal_knowledge_pack()
    except Exception:
        core = (
            "You are Sal, PercfectAI backend architect. Work with Ashley escalations "
            "and Vanessa [PASS_TO_SAL] briefs. Emit ### BUILD_TASK for code fixes."
        )
        knowledge = ""
    base = custom if custom else core
    # Always attach live local knowledge so Sal tracks repo + agent sessions
    return base + "\n\n" + _support_product_facts() + "\n\n" + knowledge


def _support_parse_responses_body(data: dict) -> str:
    """Extract assistant text from xAI /v1/responses JSON."""
    if not isinstance(data, dict):
        return ""
    # Common shapes
    for key in ("output_text", "text", "response"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # output: [ { content: [ { type, text } ] } ] or similar
    out = data.get("output")
    if isinstance(out, list):
        chunks = []
        for item in out:
            if not isinstance(item, dict):
                continue
            # message-style
            if item.get("type") in ("message", "output_text", None) or "content" in item:
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    chunks.append(content.strip())
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, str) and part.strip():
                            chunks.append(part.strip())
                        elif isinstance(part, dict):
                            t = part.get("text") or part.get("output_text") or part.get("value") or ""
                            if isinstance(t, str) and t.strip():
                                chunks.append(t.strip())
                            elif isinstance(t, dict) and t.get("value"):
                                chunks.append(str(t["value"]).strip())
            t2 = item.get("text")
            if isinstance(t2, str) and t2.strip():
                chunks.append(t2.strip())
        if chunks:
            return "\n".join(chunks).strip()
    # chat.completions fallback
    try:
        return (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
    except Exception:
        return ""


def _support_parse_sse_stream(resp) -> str:
    """Accumulate text deltas from a streamed /v1/responses body."""
    # SSE without an explicit charset decodes as latin-1 by default → mojibake.
    resp.encoding = "utf-8"
    chunks = []
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", errors="ignore").strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if not isinstance(evt, dict):
            continue
        # delta / text event shapes
        for k in ("delta", "text", "output_text"):
            v = evt.get(k)
            if isinstance(v, str) and v:
                chunks.append(v)
            elif isinstance(v, dict):
                t = v.get("text") or v.get("content") or ""
                if isinstance(t, str) and t:
                    chunks.append(t)
        # nested output delta
        if evt.get("type") in (
            "response.output_text.delta",
            "response.delta",
            "output_text.delta",
            "message.delta",
        ):
            d = evt.get("delta")
            if isinstance(d, str):
                chunks.append(d)
            elif isinstance(d, dict) and d.get("text"):
                chunks.append(str(d["text"]))
        # full completed event
        if evt.get("type") in ("response.completed", "response.done"):
            full = _support_parse_responses_body(evt.get("response") or evt)
            if full:
                return full
    return "".join(chunks).strip()


_ESCALATE_MARKER = "[ESCALATE_TO_DEBUG]"
_PASS_TO_SAL_MARKER = "[PASS_TO_SAL]"




def _support_normalize_tier(tier) -> str:
    """fast (cheap) | smart (strong) | auto."""
    x = (tier or "auto").strip().lower()
    if x in ("fast", "cheap", "economy", "low", "lite"):
        return "fast"
    if x in ("smart", "strong", "quality", "pro", "high", "best"):
        return "smart"
    return "auto"


def _support_model_fallbacks(primary: str = "") -> list:
    """Ordered model IDs to try when a key or model id is missing/unavailable."""
    models = []
    for m in (
        primary,
        os.getenv("XAI_MODEL_SMART") or "",
        os.getenv("XAI_SUPPORT_MODEL") or "",
        os.getenv("XAI_MODEL_FAST") or "",
        "grok-4.3",
        "grok-4-1-fast",
        "grok-4",
        "grok-3",
        "grok-3-mini",
        "grok-2",
    ):
        m = (m or "").strip()
        if m and m not in models:
            models.append(m)
    return models


def _support_resolve_model(role: str, tier: str = "auto") -> tuple:
    """Return (model_id, tier_used, label) for agent + optional Fast/Smart switch.

    Only Vanessa uses the user switch. Mira defaults smart. Ashley/Sal unchanged.
    Env overrides:
      XAI_MODEL_FAST (default grok-4-1-fast)
      XAI_MODEL_SMART (default grok-4.3)
      XAI_VANESSA_MODEL_FAST / XAI_VANESSA_MODEL_SMART
      XAI_MIRA_MODEL
    Prefer XAI_ALL_MODELS_KEY so every model id is actually available.
    """
    role_l = (role or "user").strip().lower()
    tier_u = _support_normalize_tier(tier)
    fast = (
        os.getenv("XAI_VANESSA_MODEL_FAST")
        or os.getenv("XAI_MODEL_FAST")
        or "grok-4-1-fast"
    ).strip()
    smart = (
        os.getenv("XAI_VANESSA_MODEL_SMART")
        or os.getenv("XAI_MODEL_SMART")
        or os.getenv("XAI_SUPPORT_MODEL")
        or "grok-4.3"
    ).strip()

    if role_l in ("vanessa", "nessa", "admin_companion"):
        if tier_u == "smart":
            return smart, "smart", "Smart"
        if tier_u == "fast":
            return fast, "fast", "Fast"
        # auto → cheap for talk/relay
        m = (os.getenv("XAI_VANESSA_MODEL") or "").strip()
        if m:
            return m, "auto", "Auto"
        return fast, "fast", "Fast"

    if role_l in ("mira",):
        m = (
            os.getenv("XAI_MIRA_MODEL")
            or os.getenv("XAI_MODEL_SMART")
            or smart
        ).strip()
        return m, "smart", "Smart"

    if role_l in ("debug", "admin", "architect", "multi", "sal"):
        # Default same reliable chat model as Ashley; multi-agent only if explicitly configured
        m = (
            os.getenv("XAI_ADMIN_MULTIAGENT_MODEL")
            or os.getenv("XAI_DEBUG_SUPPORT_MODEL")
            or os.getenv("XAI_MODEL_SMART")
            or os.getenv("XAI_SUPPORT_MODEL")
            or "grok-4.3"
        ).strip()
        return m, "auto", "Auto"

    # Ashley
    m = (os.getenv("XAI_SUPPORT_MODEL") or "grok-4.3").strip()
    return m, "auto", "Auto"


def _support_call_xai(role: str, message: str, history: list, image_data_url: str = None, model_tier: str = "auto") -> tuple:
    """Call xAI Responses API for role. Returns (reply_text, meta_dict) or raises ValueError."""
    key = _support_agent_key(role)
    if not key:
        raise ValueError("Support agent is not configured yet. Email support@percfectai.com.")

    role_l = (role or "user").strip().lower()
    is_vanessa = role_l in ("vanessa", "nessa", "admin_companion")
    is_mira = role_l in ("mira",)
    is_companion = is_vanessa or is_mira
    is_admin_agent = role_l in ("debug", "admin", "architect", "multi")

    # Vanessa / Mira — admin companions (Ashley-shaped Responses call)
    if is_companion:
        model, tier_used, tier_label = _support_resolve_model(role_l, model_tier)
        try:
            max_out = int(os.getenv("XAI_VANESSA_MAX_OUTPUT_TOKENS") or "8192")
        except ValueError:
            max_out = 8192
        max_out = max(256, min(max_out, 128000))
        use_tools = (os.getenv("XAI_VANESSA_TOOLS") or "0").strip().lower() in (
            "1", "true", "yes", "on",
        )
        tools = (
            [{"type": "web_search"}, {"type": "x_search"}]
            if use_tools
            else []
        )
        effort = (os.getenv("XAI_VANESSA_REASONING_EFFORT") or "medium").strip().lower()
        if effort not in ("none", "low", "medium", "high"):
            effort = "medium"
        # Fast tier: lighter reasoning
        if tier_used == "fast":
            effort = (os.getenv("XAI_VANESSA_FAST_REASONING_EFFORT") or "low").strip().lower()
            if effort not in ("none", "low", "medium", "high"):
                effort = "low"
        persona = "mira" if is_mira else "vanessa"
        payload = {
            "model": model,
            "instructions": _support_agent_instructions(persona),
            "max_output_tokens": max_out,
            "reasoning": {"effort": effort},
            "stream": True,
            "input": _support_build_input(history, message, image_data_url=image_data_url),
        }
        if tools:
            payload["tools"] = tools
        meta = {
            "model": model,
            "api": "responses",
            "agent": persona,
            "model_tier": tier_used,
            "model_tier_label": tier_label,
            "reasoning_effort": effort,
            "has_image": bool(image_data_url),
        }
    elif is_admin_agent:
        # Sal — same Responses shape that works for Ashley; multi-agent only via env
        model, tier_used, tier_label = _support_resolve_model("debug", model_tier)
        try:
            max_out = int(os.getenv("XAI_ADMIN_MULTIAGENT_MAX_OUTPUT") or os.getenv("XAI_SUPPORT_MAX_OUTPUT_TOKENS") or "8192")
        except ValueError:
            max_out = 8192
        max_out = max(256, min(max_out, 32000))
        # Tools OFF by default (same lesson as Vanessa); enable with XAI_ADMIN_MULTIAGENT_TOOLS=1
        use_tools = (os.getenv("XAI_ADMIN_MULTIAGENT_TOOLS") or "0").strip().lower() in (
            "1", "true", "yes", "on",
        )
        tools = [{"type": "web_search"}] if use_tools else []
        effort = (os.getenv("XAI_DEBUG_REASONING_EFFORT") or "medium").strip().lower()
        if effort not in ("none", "low", "medium", "high"):
            effort = "medium"
        payload = {
            "model": model,
            "instructions": _support_agent_instructions("debug"),
            "max_output_tokens": max_out,
            "reasoning": {"effort": effort},
            "stream": True,
            "input": _support_build_input(history, message, image_data_url=image_data_url),
        }
        if tools:
            payload["tools"] = tools
        meta = {
            "model": model,
            "api": "responses",
            "agent": "debug",
            "model_tier": tier_used,
            "model_tier_label": tier_label,
            "reasoning_effort": effort,
            "has_image": bool(image_data_url),
        }

    else:
        model = (os.getenv("XAI_SUPPORT_MODEL") or "grok-4.3").strip()
        default_effort = "medium"
        effort = (os.getenv("XAI_SUPPORT_REASONING_EFFORT") or default_effort).strip().lower()
        if effort not in ("none", "low", "medium", "high"):
            effort = default_effort
        try:
            max_out = int(os.getenv("XAI_SUPPORT_MAX_OUTPUT_TOKENS") or "8192")
        except ValueError:
            max_out = 8192
        max_out = max(256, min(max_out, 128000))
        use_tools = (os.getenv("XAI_SUPPORT_TOOLS") or "1").strip().lower() not in (
            "0", "false", "no", "off",
        )
        tools = (
            [{"type": "web_search"}, {"type": "x_search"}]
            if use_tools
            else []
        )
        payload = {
            "model": model,
            "instructions": _support_agent_instructions(role),
            "max_output_tokens": max_out,
            "reasoning": {"effort": effort},
            "stream": True,
            "input": _support_build_input(history, message, image_data_url=image_data_url),
        }
        if tools:
            payload["tools"] = tools
        meta = {
            "model": model,
            "api": "responses",
            "agent": role,
            "reasoning_effort": effort,
        }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    url = f"{XAI_BASE_URL}/responses"

    def _try_payload(pl, meta_out):
        """Stream then non-stream; return (reply, meta) or None."""
        try:
            r = requests.post(url, headers=headers, json=pl, timeout=180, stream=True)
        except requests.RequestException as e:
            app.logger.warning("support agent %s request failed: %s", role, e)
            return None
        if r.ok:
            reply = _support_parse_sse_stream(r)
            if reply:
                return reply, meta_out
            app.logger.warning("support agent %s stream empty; retrying non-stream", role)
        try:
            pl_ns = dict(pl)
            pl_ns["stream"] = False
            r2 = requests.post(url, headers=headers, json=pl_ns, timeout=180)
        except requests.RequestException as e:
            app.logger.warning("support agent %s non-stream failed: %s", role, e)
            return None
        if r2.ok:
            try:
                data = json.loads(r2.content.decode("utf-8"))
            except Exception:
                data = {}
            reply = _support_parse_responses_body(data)
            if reply:
                return reply, meta_out
            app.logger.warning("support agent %s empty parse: %s", role, str(data)[:400])
            return None
        app.logger.warning(
            "support agent %s HTTP %s: %s",
            role, r2.status_code, (r2.text or "")[:400],
        )
        return None

    # Attempt primary payload
    got = _try_payload(payload, meta)
    if got:
        return got

    # Strip tools
    if payload.get("tools"):
        pl = dict(payload)
        pl.pop("tools", None)
        m2 = dict(meta)
        m2["tools"] = False
        got = _try_payload(pl, m2)
        if got:
            return got

    # Vanessa / vision: more aggressive fallbacks (model + no image + no reasoning)
    if is_companion or is_admin_agent:
        if is_admin_agent:
            base_instr = _support_agent_instructions("debug")
            persona_agent = "debug"
        else:
            base_instr = _support_agent_instructions("mira" if is_mira else "vanessa")
            persona_agent = "mira" if is_mira else "vanessa"
        models = _support_model_fallbacks(payload.get("model") or "")
        for model in models:
            for drop_image in (False, True) if image_data_url else (False,):
                for effort in ("medium", None):
                    pl = {
                        "model": model,
                        "instructions": base_instr,
                        "max_output_tokens": min(int(payload.get("max_output_tokens") or 8192), 8192),
                        "stream": True,
                        "input": _support_build_input(
                            history,
                            message,
                            image_data_url=None if drop_image else image_data_url,
                        ),
                    }
                    if effort:
                        pl["reasoning"] = {"effort": effort}
                    m2 = {
                        "model": model,
                        "api": "responses",
                        "agent": "mira" if is_mira else "vanessa",
                        "reasoning_effort": effort or "none",
                        "has_image": bool(image_data_url) and not drop_image,
                        "fallback": True,
                    }
                    got = _try_payload(pl, m2)
                    if got:
                        return got

    # Non-vanessa: one more try without tools already done
    if not is_vanessa and payload.get("tools"):
        pass

    raise ValueError(
        (
            "Sal/debug agent error — model or key may be wrong. "
            "Set XAI_DEBUG_SUPPORT_MODEL=grok-4.3 (or XAI_SUPPORT_MODEL) on Render."
            if is_admin_agent
            else (
                "Admin companion error — model or key may be wrong. "
                "Try Fast tier, or set XAI_MODEL_FAST / XAI_MODEL_SMART on Render."
                if is_companion
                else "Support agent error — try again or email support@percfectai.com."
            )
        )
    )


def _support_parse_escalate(reply: str) -> tuple:
    """If user agent escalates, return (True, bug_summary, customer_message)."""
    text = (reply or "").strip()
    # Accept exact marker or common LLM near-misses in the first ~120 chars / first line
    head = text[:120].upper()
    first = (text.splitlines()[0] if text.splitlines() else "")
    soft_markers = (
        _ESCALATE_MARKER.upper(),
        "ESCALATE_TO_DEBUG",
        "ESCALATE TO DEBUG",
        "ESCALATE TO SAL",
        "ESCALATE_TO_SAL",
        "[ESCALATE]",
    )
    has_marker = any(m in head or m in first.upper() for m in soft_markers)
    if not has_marker:
        lines0 = text.splitlines()
        if not lines0 or _ESCALATE_MARKER not in lines0[0]:
            return False, "", text
    lines = text.splitlines()
    # drop the marker line
    rest = []
    saw = False
    for i, line in enumerate(lines):
        if not saw and _ESCALATE_MARKER in line:
            saw = True
            after = line.replace(_ESCALATE_MARKER, "").strip()
            if after:
                rest.append(after)
            rest.extend(lines[i + 1 :])
            break
    if not saw:
        return False, "", text
    bug_summary = (rest[0] if rest else "User reported a possible product bug.").strip()
    customer_msg = "\n".join(rest[1:]).strip() if len(rest) > 1 else (
        "I can see this looks like a site bug. I’m sending it to our debug team now — "
        "you’ll get their diagnosis below. You can also email support@percfectai.com."
    )
    return True, bug_summary, customer_msg



def _support_parse_pass_to_sal(reply: str) -> tuple:
    """Vanessa → Sal: return (True, title, brief) if she emitted a handoff marker."""
    text = (reply or "").strip()
    if not text:
        return False, "", ""
    head = text[:100].upper()
    first = (text.splitlines()[0] if text.splitlines() else "")
    soft = (
        _PASS_TO_SAL_MARKER.upper(),
        "PASS_TO_SAL",
        "PASS TO SAL",
        "[PASS_TO_SAL]",
        "ESCALATE_TO_SAL",
        "ESCALATE TO SAL",
    )
    if not any(m in head or m in first.upper() for m in soft):
        return False, "", ""
    lines = text.splitlines()
    rest = []
    saw = False
    for i, line in enumerate(lines):
        if not saw and any(m in line.upper() for m in ("PASS_TO_SAL", "PASS TO SAL", "ESCALATE_TO_SAL", "ESCALATE TO SAL")):
            saw = True
            after = line
            for m in ("[PASS_TO_SAL]", "PASS_TO_SAL", "PASS TO SAL", "[ESCALATE_TO_SAL]", "ESCALATE_TO_SAL", "ESCALATE TO SAL"):
                after = after.replace(m, "").replace(m.lower(), "")
            after = after.strip(" :-	")
            if after:
                rest.append(after)
            rest.extend(lines[i + 1 :])
            break
    if not saw:
        return False, "", ""
    title = (rest[0] if rest else "Admin change request").strip()[:200]
    brief = "\n".join(rest[1:]).strip() if len(rest) > 1 else title
    return True, title, brief


@app.route("/api/support/tts", methods=["POST"])
@app.route("/studios/support/tts", methods=["POST"])
@app.route("/percfectstudios/support/tts", methods=["POST"])
def support_companion_tts():
    """Admin-only TTS for Vanessa/Mira via xAI Grok voices (Ara, Eve, …).

    Body: { text, agent?: vanessa|mira, voice_id?: ara|eve|leo|rex|sal }
    Returns raw audio/mpeg bytes (mp3).
    """
    if not (
        current_user.is_authenticated
        and getattr(current_user, "is_admin", False)
    ):
        return jsonify({"error": "Not found."}), 404

    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Nothing to speak."}), 400
    if len(text) > 2000:
        text = text[:2000]

    role = (body.get("agent") or body.get("role") or "vanessa").strip().lower()
    # Vanessa = Ara (warm Grok voice). Mira = Eve (clear co-pilot).
    default_voice = "eve" if role in ("mira",) else "ara"
    voice_id = (body.get("voice_id") or body.get("voice") or default_voice).strip().lower()
    if voice_id not in ("ara", "eve", "leo", "rex", "sal"):
        voice_id = default_voice

    # VOICE silo only — never chat key, never image pool key
    api_key = _support_agent_key("tts")
    if not api_key:
        return jsonify({
            "error": "Voice key missing — set XAI_TTS_API_KEY (voice-only; not a chat or image key).",
        }), 503

    try:
        import requests as _req

        r = _req.post(
            "https://api.x.ai/v1/tts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "voice_id": voice_id,
                "language": "en",
                "output_format": {
                    "codec": "mp3",
                    "sample_rate": 24000,
                    "bit_rate": 128000,
                },
            },
            timeout=60,
        )
        if r.status_code != 200:
            app.logger.warning(
                "companion TTS failed %s: %s",
                r.status_code,
                (r.text or "")[:300],
            )
            return jsonify({
                "error": f"TTS failed ({r.status_code}).",
                "detail": (r.text or "")[:200],
            }), 502
        return Response(
            r.content,
            mimetype="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as e:
        app.logger.exception("companion TTS error")
        return jsonify({"error": str(e)[:200]}), 502


@app.route("/api/support/stt", methods=["POST"])
@app.route("/studios/support/stt", methods=["POST"])
@app.route("/percfectstudios/support/stt", methods=["POST"])
def support_companion_stt():
    """Admin-only speech-to-text for Vanessa/Mira via xAI STT.

    Multipart: format, language, file (file must be last for xAI).
    Client records mic → POSTs blob; key never leaves the server.
    Auth: XAI_STT_API_KEY or XAI_TTS_API_KEY (voice silo — never image pool).
    """
    if not (
        current_user.is_authenticated
        and getattr(current_user, "is_admin", False)
    ):
        return jsonify({"error": "Not found."}), 404

    api_key = _support_agent_key("stt")
    if not api_key:
        return jsonify({
            "error": (
                "STT key missing — set XAI_STT_API_KEY or XAI_TTS_API_KEY "
                "(voice silo; not chat or image keys)."
            ),
        }), 503

    up = request.files.get("file") or request.files.get("audio")
    if up is None:
        return jsonify({"error": "No audio file. Record with the mic, then try again."}), 400

    raw = up.read()
    if not raw or len(raw) < 64:
        return jsonify({"error": "Audio too short or empty."}), 400
    if len(raw) > 25 * 1024 * 1024:
        return jsonify({"error": "Audio too large (max 25MB)."}), 400

    language = (request.form.get("language") or "en").strip() or "en"
    fmt = (request.form.get("format") or "true").strip().lower()
    format_flag = "true" if fmt in ("true", "1", "") else "false"

    filename = (getattr(up, "filename", None) or "recording.webm").strip() or "recording.webm"
    lower = filename.lower()
    if not any(
        lower.endswith(ext)
        for ext in (".wav", ".mp3", ".webm", ".ogg", ".m4a", ".mp4", ".mpeg", ".mpga")
    ):
        filename = "recording.webm"

    content_type = (getattr(up, "content_type", None) or "").strip() or "application/octet-stream"

    try:
        import requests as _req

        # xAI STT: data fields before files so file is last in multipart
        r = _req.post(
            "https://api.x.ai/v1/stt",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"format": format_flag, "language": language},
            files={"file": (filename, raw, content_type)},
            timeout=90,
        )
        if r.status_code != 200:
            app.logger.warning(
                "companion STT failed %s: %s",
                r.status_code,
                (r.text or "")[:300],
            )
            return jsonify({
                "error": f"Speech-to-text failed ({r.status_code}).",
                "detail": (r.text or "")[:200],
            }), 502
        try:
            body = r.json()
        except Exception:
            return jsonify({"error": "STT returned non-JSON."}), 502
        text = (body.get("text") or body.get("transcript") or "").strip()
        if not text:
            return jsonify({
                "error": "Could not hear anything — try again closer to the mic.",
                "text": "",
            }), 200
        return jsonify({"text": text, "ok": True}), 200
    except Exception as e:
        app.logger.exception("companion STT error")
        return jsonify({"error": str(e)[:200]}), 502


@app.route("/api/support/chat", methods=["POST"])
@app.route("/studios/support/chat", methods=["POST"])
@app.route("/percfectstudios/support/chat", methods=["POST"])
def support_chat():
    """Grok agents via xAI Responses API (grok-4.3).

    Body: { message, history?, agent?: \"debug\"|\"user\" }

    - agent=debug → XAI_DEBUG_SUPPORT_API_KEY (website debugger / debug team)
    - agent=user  → XAI_USER_SUPPORT_API_KEY (front user support)

    When user agent decides it is a clear development bug, it emits
    [ESCALATE_TO_DEBUG] and the server calls the debug agent (debug key)
    with the bug context, then returns both replies.

    Prefer /studios/support/chat; /api/support/chat also works.
    """
    body = request.get_json(silent=True) or {}
    role = (body.get("agent") or body.get("role") or "user").strip().lower()
    if role in ("front", "customer", "help", "ashley"):
        role = "user"
    if role in ("nessa", "admin_companion"):
        role = "vanessa"
    if role not in ("debug", "user", "vanessa", "mira"):
        role = "user"

    # Sal + Vanessa + Mira are admin-only
    if role in ("debug", "vanessa", "mira"):
        # Non-admins: no agent identity, no feature leak
        if not (
            current_user.is_authenticated
            and getattr(current_user, "is_admin", False)
        ):
            return jsonify({"error": "Not found."}), 404

    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Type a message first."}), 400
    if len(message) > 4000:
        return jsonify({"error": "Message too long (max 4000 characters)."}), 400

    history = body.get("history") or []
    if not isinstance(history, list):
        history = []
    model_tier = _support_normalize_tier(body.get("model_tier") or body.get("tier") or "auto")

    # Optional page snapshot (Vanessa admin) — data URL jpeg/png
    image_data_url = None
    raw_img = (
        body.get("image")
        or body.get("image_data_url")
        or body.get("screenshot")
        or ""
    )
    if raw_img:
        if role not in ("vanessa", "mira", "debug"):
            return jsonify({"error": "Not found."}), 404
        if not (
            current_user.is_authenticated
            and getattr(current_user, "is_admin", False)
        ):
            return jsonify({"error": "Not found."}), 404
        try:
            image_data_url = _support_normalize_data_url(raw_img)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not image_data_url:
            return jsonify({"error": "Invalid screenshot data."}), 400

    # Sal has no browser memory of background escalations — inject the inbox
    sal_message = message
    if role == "debug":
        try:
            import support_escalations as se
            inbox = se.format_inbox_for_sal(limit=8)
            sal_message = (
                "[SYSTEM — Ashley escalation inbox for Sal]\n"
                f"{inbox}\n\n"
                "[Admin message to Sal]\n"
                f"{message}"
            )
        except Exception as e:
            app.logger.warning("support inbox inject failed: %s", e)
            sal_message = message

    try:
        reply, meta = _support_call_xai(
            role,
            sal_message if role == "debug" else message,
            history,
            image_data_url=image_data_url if role in ("vanessa", "mira", "debug") else None,
            model_tier=model_tier if role in ("vanessa", "mira") else "auto",
        )
        try:
            from support_encoding import ensure_utf8_text
            reply = ensure_utf8_text(reply)
        except Exception:
            pass
    except ValueError as e:
        code = 503 if "not configured" in str(e).lower() else 502
        try:
            import agent_reports as ar
            if role in ("debug", "vanessa", "mira"):
                ar.add_report(
                    kind="failure",
                    agent=role,
                    summary=str(e)[:400],
                    detail="support_chat agent call failed",
                    message=message,
                    ok=False,
                )
        except Exception:
            pass
        return jsonify({"error": str(e)}), code

    # User support → Architect diagnosis → auto-queue Grok Build fixer
    if role == "user":
        escalate, bug_summary, customer_msg = _support_parse_escalate(reply)
        if escalate:
            debug_key = _support_agent_key("debug")
            if not debug_key:
                return jsonify({
                    "reply": customer_msg + (
                        "\n\n(Debug team key not configured yet — please email support@percfectai.com.)"
                    ),
                    "escalated": True,
                    "agent": "user",
                    "debug_error": "debug key missing",
                    **{k: v for k, v in meta.items() if k != "agent"},
                })
            debug_input = (
                f"ESCALATION from Ashley (front support) → Sal (backend) → Grok Build fixer.\n"
                f"Bug summary: {bug_summary}\n\n"
                f"Original customer message:\n{message}\n\n"
                "You are Sal. Respond as Sal to the admin pipeline:\n"
                "1) One-sentence diagnosis.\n"
                "2) Customer-safe status (no secrets, no internal paths) Ashley can show.\n"
                "3) End with ### BUILD_TASK (goal, files/routes, steps, done when) "
                "so Grok Build can implement the fix automatically.\n"
                "If this is not a code fix (billing only, user error), say so and omit BUILD_TASK."
            )
            try:
                debug_reply, debug_meta = _support_call_xai("debug", debug_input, [])
            except ValueError as e:
                debug_reply = (
                    f"Debug team could not be reached ({e}). "
                    "Please email support@percfectai.com with what happened."
                )
                debug_meta = {}

            build_task = None
            queue_error = None
            auto_q = (os.getenv("SUPPORT_AUTO_QUEUE_BUILD") or "1").strip().lower() not in (
                "0", "false", "no", "off",
            )
            # Only queue when Architect produced a real task (or any non-empty diagnosis if forced)
            has_build = "### BUILD_TASK" in (debug_reply or "") or "## Grok Build task" in (debug_reply or "")
            force_q = (os.getenv("SUPPORT_QUEUE_WITHOUT_BUILD_MARKER") or "0").strip().lower() in (
                "1", "true", "yes", "on",
            )
            if auto_q and debug_reply and (has_build or force_q):
                try:
                    import build_bridge as bb
                    uid = current_user.id if current_user.is_authenticated else None
                    build_task = bb.queue_fixer_task(
                        debug_reply,
                        title=bug_summary[:160],
                        source="Ashley → Sal escalate",
                        bug_summary=bug_summary,
                        customer_message=message,
                        created_by=uid,
                        auto_approve=True,
                    )
                    app.logger.info(
                        "Ashley→Sal queued build task id=%s title=%s",
                        build_task.get("id"),
                        build_task.get("title"),
                    )
                except Exception as e:
                    queue_error = str(e)[:300]
                    app.logger.warning("support escalate queue failed: %s", e)

            # Customer-facing (Ashley): no Sal name, no BUILD_TASK dump, optional ref id
            ticket_line = ""
            if build_task:
                tid = build_task.get("id")
                short = str(tid)[-8:] if tid is not None else "queued"
                ticket_line = (
                    f"\n\nI've passed this to our engineer with reference "
                    f"**{short}**. We're working on a fix."
                )
            elif queue_error:
                ticket_line = (
                    "\n\nI've flagged this for engineering. If it keeps happening, "
                    "email support@percfectai.com with what you tried."
                )
            elif auto_q and not has_build:
                ticket_line = (
                    "\n\nI've had engineering take a look — we may need a bit more detail "
                    "or a human follow-up. Email support@percfectai.com if it continues."
                )

            # Customers only see Ashley's voice + soft ticket note (not Sal's internals)
            hide_eng = (os.getenv("SUPPORT_SHOW_ENGINEERING_TO_CUSTOMER") or "0").strip().lower() in (
                "1", "true", "yes", "on",
            )
            if hide_eng:
                public_debug = debug_reply
                if "### BUILD_TASK" in public_debug:
                    public_debug = public_debug.split("### BUILD_TASK")[0].strip()
                combined = f"{customer_msg}{ticket_line}\n\n--- Update ---\n{public_debug}"
            else:
                combined = f"{customer_msg}{ticket_line}"

            # Persist so Sal's admin chat / inbox can see this handoff later
            esc_row = None
            try:
                import support_escalations as se
                esc_row = se.record_escalation(
                    customer_message=message,
                    bug_summary=bug_summary,
                    ashley_customer_msg=customer_msg,
                    sal_reply=debug_reply or "",
                    build_task_id=(build_task or {}).get("id") if isinstance(build_task, dict) else None,
                    build_queued=bool(build_task),
                    queue_error=queue_error or "",
                    user_id=current_user.id if current_user.is_authenticated else None,
                )
                app.logger.info(
                    "Ashley→Sal escalation stored id=%s summary=%s",
                    (esc_row or {}).get("id"),
                    (bug_summary or "")[:80],
                )
            except Exception as e:
                app.logger.warning("support escalation store failed: %s", e)

            return jsonify({
                "reply": combined,
                "escalated": True,
                "agent": "user",
                "agent_name": "Ashley",
                "user_reply": customer_msg,
                "debug_reply": debug_reply,
                "sal_reply": debug_reply,
                "bug_summary": bug_summary,
                "build_task": build_task,
                "build_queued": bool(build_task),
                "queue_error": queue_error,
                "escalation_id": (esc_row or {}).get("id") if esc_row else None,
                "model": meta.get("model"),
                "debug_model": debug_meta.get("model"),
                "api": "responses",
            })

    # Vanessa → Sal: admin companion briefs Sal for coding
    if role in ("vanessa", "mira"):
        pass_to, title, brief = _support_parse_pass_to_sal(reply)
        if pass_to:
            sal_input = (
                f"BRIEF from Vanessa (admin companion) → Sal (backend coder).\n"
                f"Title: {title}\n\n"
                f"Admin's original message:\n{message}\n\n"
                f"Vanessa's engineering brief:\n{brief}\n\n"
                "You are Sal. Implementable diagnosis + ### BUILD_TASK "
                "(goal, files/routes, steps, done when). Prefer minimal safe diffs."
            )
            sal_reply = ""
            sal_meta = {}
            build_task = None
            queue_error = None
            try:
                sal_reply, sal_meta = _support_call_xai("debug", sal_input, [], image_data_url=image_data_url)
            except ValueError as e:
                sal_reply = f"Sal could not be reached ({e})."
            # strip marker from Vanessa's admin-facing reply
            admin_reply = reply
            for line in (reply or "").splitlines():
                if "[PASS_TO_SAL]" in line.upper() or "PASS_TO_SAL" in line.upper():
                    # rebuild without first marker line
                    lines = (reply or "").splitlines()
                    rest = []
                    skip = True
                    for i, ln in enumerate(lines):
                        if skip and ("PASS_TO_SAL" in ln.upper()):
                            skip = False
                            continue
                        rest.append(ln)
                    admin_reply = "\n".join(rest).strip() or brief or title
                    break
            # auto-queue if Sal produced BUILD_TASK
            auto_q = (os.getenv("VANESSA_AUTO_QUEUE_BUILD") or "1").strip().lower() not in (
                "0", "false", "no", "off",
            )
            has_build = "### BUILD_TASK" in (sal_reply or "") or "## Grok Build task" in (sal_reply or "")
            if auto_q and sal_reply and has_build:
                try:
                    import build_bridge as bb
                    uid = current_user.id if current_user.is_authenticated else None
                    build_task = bb.queue_fixer_task(
                        sal_reply,
                        title=(title or "Vanessa → Sal")[:160],
                        source=("Mira → Sal" if role == "mira" else "Vanessa → Sal"),
                        bug_summary=title,
                        customer_message=message,
                        created_by=uid,
                        auto_approve=True,
                    )
                except Exception as e:
                    queue_error = str(e)[:300]
                    app.logger.warning("Vanessa→Sal queue failed: %s", e)
            try:
                import support_escalations as se
                se.record_escalation(
                    customer_message=f"[admin via {'Mira' if role == 'mira' else 'Vanessa'}] {message}",
                    bug_summary=title or "Vanessa brief",
                    ashley_customer_msg=admin_reply[:500],
                    sal_reply=sal_reply or "",
                    build_task_id=(build_task or {}).get("id") if isinstance(build_task, dict) else None,
                    build_queued=bool(build_task),
                    queue_error=queue_error or "",
                    user_id=current_user.id if current_user.is_authenticated else None,
                )
            except Exception as e:
                app.logger.warning("Vanessa escalation store failed: %s", e)
            note = ""
            if build_task:
                note = f"\n\n— Handed to Sal · queued fixer id {build_task.get('id')} —"
            elif sal_reply:
                note = "\n\n— Handed to Sal (see his panel / inbox) —"
            try:
                import agent_reports as ar
                ar.add_report(
                    kind="pass_to_sal",
                    agent=role,
                    summary=(title or "Pass to Sal")[:400],
                    detail=(brief or "")[:2000],
                    message=message,
                    model=(meta or {}).get("model", ""),
                    ok=True,
                    extra={
                        "build_queued": bool(build_task),
                        "build_task_id": (build_task or {}).get("id") if isinstance(build_task, dict) else None,
                        "queue_error": queue_error,
                    },
                )
            except Exception:
                pass
            return jsonify({
                "reply": (admin_reply or reply) + note,
                "agent": role,
                "agent_name": ("Mira" if role == "mira" else "Vanessa"),
                "passed_to_sal": True,
                "sal_reply": sal_reply,
                "bug_summary": title,
                "build_task": build_task,
                "build_queued": bool(build_task),
                "queue_error": queue_error,
                "model": meta.get("model"),
                "debug_model": sal_meta.get("model"),
                "api": "responses",
            })
        return jsonify({
            "reply": reply,
            "agent": role,
            "agent_name": ("Mira" if role == "mira" else "Vanessa"),
            "passed_to_sal": False,
            **{k: v for k, v in meta.items() if k != "agent"},
        })

    # Sal (admin) chat → optional auto-queue when ### BUILD_TASK present
    build_task = None
    if role == "debug":
        auto_admin = (os.getenv("ADMIN_AUTO_QUEUE_BUILD") or "1").strip().lower() not in (
            "0", "false", "no", "off",
        )
        if auto_admin and reply and ("### BUILD_TASK" in reply or "## Grok Build task" in reply):
            try:
                import build_bridge as bb
                uid = current_user.id if current_user.is_authenticated else None
                build_task = bb.queue_fixer_task(
                    reply,
                    source="Sal (admin chat)",
                    created_by=uid,
                    auto_approve=True,
                )
            except Exception as e:
                app.logger.warning("Sal auto-queue failed: %s", e)

    out = {
        "reply": reply,
        "agent_name": (
            "Sal" if role == "debug"
            else ("Mira" if role == "mira"
                  else ("Vanessa" if role == "vanessa" else "Ashley"))
        ),
        **meta,
    }
    if build_task:
        out["build_task"] = build_task
        out["build_queued"] = True
    return jsonify(out)




@app.route("/api/support/escalations", methods=["GET"])
@app.route("/studios/support/escalations", methods=["GET"])
@app.route("/percfectstudios/support/escalations", methods=["GET"])

@app.route("/studios/admin/agent-reports", methods=["GET"])
@app.route("/percfectstudios/admin/agent-reports", methods=["GET"])
def admin_agent_reports():
    """Admin-only: recent Vanessa/Mira/Sal failures & handoffs (for Nick / Grok)."""
    if not (
        current_user.is_authenticated
        and getattr(current_user, "is_admin", False)
    ):
        return jsonify({"error": "Not found."}), 404
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        limit = 20
    kind = (request.args.get("kind") or "").strip() or None
    try:
        import agent_reports as ar
        rows = ar.list_reports(limit=limit, kind=kind)
        grok_text = ar.format_for_grok(limit=limit)
    except Exception as e:
        app.logger.warning("agent reports list failed: %s", e)
        return jsonify({"error": "Could not load reports.", "reports": []}), 500
    return jsonify({"reports": rows, "count": len(rows), "grok_text": grok_text})


def support_escalations_list():
    """Admin-only: recent Ashley → Sal escalations (inbox)."""
    if not (
        current_user.is_authenticated
        and getattr(current_user, "is_admin", False)
    ):
        return jsonify({"error": "Not found."}), 404
    try:
        limit = int(request.args.get("limit") or 12)
    except ValueError:
        limit = 12
    try:
        import support_escalations as se
        rows = se.list_escalations(limit=limit)
    except Exception as e:
        app.logger.warning("list escalations failed: %s", e)
        return jsonify({"error": "Could not load escalations.", "escalations": []}), 500
    return jsonify({"escalations": rows, "count": len(rows)})


# ── Grok Build bridge (admin) ─────────────────────────────
def _require_admin_or_bridge():
    """Admin session OR GROK_BUILD_BRIDGE_TOKEN for local worker."""
    if current_user.is_authenticated and getattr(current_user, "is_admin", False):
        return True
    try:
        from build_bridge import bridge_token_ok
        if bridge_token_ok(request.headers.get("Authorization") or request.headers.get("X-Bridge-Token") or ""):
            return True
    except Exception:
        pass
    return False


@app.route("/studios/admin/build-tasks", methods=["GET", "POST"])
@app.route("/percfectstudios/admin/build-tasks", methods=["GET", "POST"])
def admin_build_tasks():
    """Level 1+3 bridge: queue architect prompts for Grok Build worker."""
    if not _require_admin_or_bridge():
        if request.method == "GET" and not current_user.is_authenticated:
            return jsonify({"error": "Log in as admin or pass GROK_BUILD_BRIDGE_TOKEN."}), 401
        return jsonify({"error": "Admin only."}), 403

    import build_bridge as bb

    if request.method == "GET":
        status = (request.args.get("status") or "").strip() or None
        try:
            limit = int(request.args.get("limit") or 30)
        except ValueError:
            limit = 30
        tasks = bb.list_tasks(limit=limit, status=status)
        return jsonify({"tasks": tasks, "count": len(tasks)})

    body = request.get_json(silent=True) or {}
    raw = (body.get("prompt") or body.get("text") or body.get("message") or "").strip()
    if not raw:
        return jsonify({"error": "prompt required"}), 400
    title = (body.get("title") or "").strip()
    auto = body.get("auto_approve")
    if auto is None:
        auto = True
    prompt = bb.format_grok_build_prompt(raw, source=body.get("source") or "Admin Architect")
    try:
        uid = current_user.id if current_user.is_authenticated else None
        task = bb.create_task(prompt, title=title, created_by=uid, auto_approve=bool(auto))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.exception("build task create failed: %s", e)
        return jsonify({"error": "Could not queue task."}), 500
    return jsonify({"ok": True, "task": task})


@app.route("/studios/admin/build-tasks/claim", methods=["POST"])
@app.route("/percfectstudios/admin/build-tasks/claim", methods=["POST"])
def admin_build_tasks_claim():
    """Worker claims next approved/pending task."""
    if not _require_admin_or_bridge():
        return jsonify({"error": "Admin or bridge token required."}), 403
    import build_bridge as bb
    task = bb.claim_next()
    if not task:
        return jsonify({"ok": True, "task": None, "message": "No pending tasks."})
    return jsonify({"ok": True, "task": task})


@app.route("/studios/admin/build-tasks/<task_id>/complete", methods=["POST"])
@app.route("/percfectstudios/admin/build-tasks/<task_id>/complete", methods=["POST"])
def admin_build_tasks_complete(task_id):
    if not _require_admin_or_bridge():
        return jsonify({"error": "Admin or bridge token required."}), 403
    import build_bridge as bb
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "done").strip().lower()
    result = (body.get("result") or body.get("summary") or "").strip()
    task = bb.complete_task(task_id, status=status, result=result)
    if not task:
        return jsonify({"error": "Task not found."}), 404
    return jsonify({"ok": True, "task": task})


@app.route("/percfectprotect")
def percfect_protect():
    return render_template("percfectprotect.html")


@app.route("/dashboard")
@login_required
def dashboard():
    """Homebase is the hub. Old /dashboard was a second copy — send people home."""
    return redirect("/")


# ── Account Settings ─────────────────────────────────────
SETTINGS_USER_FIELDS = (
    "username,email,display_name,birthday,picture_credits,video_credits,"
    "images_today,videos_today,created_at,stripe_customer_id,"
    "social_twitter,social_instagram,social_tiktok,social_youtube,social_website"
)


def _safe_user_update(user_id, updates: dict):
    payload = dict(updates)
    while payload:
        try:
            supabase.table("users").update(payload).eq("id", user_id).execute()
            return True, payload
        except Exception:
            optional = (
                "display_name", "stripe_customer_id",
                "social_twitter", "social_instagram", "social_tiktok",
                "social_youtube", "social_website",
            )
            removed = False
            for key in optional:
                if key in payload:
                    payload.pop(key)
                    removed = True
                    break
            if not removed:
                raise
    return False, {}


def _normalize_social(field: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if field == "social_website" and not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    if field.startswith("social_") and field != "social_website":
        handle = value.lstrip("@").split("/")[-1].split("?")[0]
        prefixes = {
            "social_twitter": "https://x.com/",
            "social_instagram": "https://instagram.com/",
            "social_tiktok": "https://tiktok.com/@",
            "social_youtube": "https://youtube.com/@",
        }
        if value.startswith("http"):
            return value
        return prefixes.get(field, "") + handle
    return value


def _load_settings_user(user_id):
    try:
        res = supabase.table("users").select(SETTINGS_USER_FIELDS).eq("id", user_id).single().execute()
        return res.data or {}
    except Exception:
        res = supabase.table("users").select(
            "username,email,birthday,picture_credits,video_credits,images_today,videos_today,created_at"
        ).eq("id", user_id).single().execute()
        return res.data or {}


@app.context_processor
def inject_share_context():
    handle = ""
    wallet = 0
    if current_user.is_authenticated:
        try:
            handle = _twitter_handle(_load_settings_user(current_user.id))
        except Exception:
            pass
        try:
            wallet = int(getattr(current_user, "credits", 0) or 0)
        except Exception:
            wallet = int(getattr(current_user, "picture_credits", 0) or 0) + int(
                getattr(current_user, "video_credits", 0) or 0
            )
    is_admin = bool(
        current_user.is_authenticated and getattr(current_user, "is_admin", False)
    )
    return {
        "twitter_handle": handle,
        "unified_credits": wallet,
        "is_admin": is_admin,
        "show_vanessa": is_admin,
        "vanessa_agent_ready": bool(is_admin and _support_agent_key("vanessa")),
        "mira_agent_ready": bool(is_admin and _support_agent_key("mira")),
    }


def _ensure_stripe_customer(user_data: dict):
    if not stripe.api_key:
        return None
    existing = user_data.get("stripe_customer_id")
    if existing:
        return existing
    try:
        customer = stripe.Customer.create(
            email=user_data.get("email") or None,
            name=user_data.get("display_name") or user_data.get("username"),
            metadata={"user_id": str(current_user.id)},
        )
        _safe_user_update(current_user.id, {"stripe_customer_id": customer.id})
        return customer.id
    except Exception:
        return None


def _get_billing_info(stripe_customer_id):
    info = {"cards": [], "payments": [], "portal_available": bool(stripe.api_key)}
    if not stripe_customer_id or not stripe.api_key:
        return info
    try:
        methods = stripe.PaymentMethod.list(customer=stripe_customer_id, type="card", limit=5)
        for pm in methods.data:
            card = pm.card
            info["cards"].append({
                "brand": (card.brand or "card").title(),
                "last4": card.last4,
                "exp": f"{card.exp_month:02d}/{str(card.exp_year)[-2:]}",
            })
    except Exception:
        pass
    try:
        sessions = stripe.checkout.Session.list(customer=stripe_customer_id, limit=8)
        for s in sessions.data:
            if s.payment_status not in ("paid", "no_payment_required"):
                continue
            meta = s.metadata or {}
            pkg = CREDIT_PACKAGES.get(meta.get("package") or "", {})
            plan = SUBSCRIPTION_PLANS.get(meta.get("subscription_plan") or "", {})
            label = pkg.get("name") or (f"{plan['name']} sub" if plan else None) or "Credit purchase"
            total = s.amount_total
            if total is None:
                total = 0
            info["payments"].append({
                "date": datetime.datetime.fromtimestamp(s.created, datetime.timezone.utc).strftime("%b %d, %Y"),
                "amount": f"${(total or 0) / 100:.2f}",
                "package": label,
            })
    except Exception:
        pass
    return info


@app.route("/settings/billing-portal")
@login_required
def settings_billing_portal():
    user_data = _load_settings_user(current_user.id)
    customer_id = _ensure_stripe_customer(user_data)
    if not customer_id:
        flash("Billing is not available right now. Please try again later.", "danger")
        return redirect(url_for("account_settings") + "#billing")

    base_url = _site_base_url()
    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{base_url}/settings#billing",
        )
        return redirect(portal.url, code=303)
    except Exception:
        flash("Could not open billing portal. Enable Stripe Customer Portal in your Stripe dashboard.", "danger")
        return redirect(url_for("account_settings") + "#billing")


@app.route("/settings", methods=["GET", "POST"])
@login_required
def account_settings():
    user_data = _load_settings_user(current_user.id)
    success = None
    error = None
    active_tab = request.args.get("tab", "personal")

    if request.method == "POST":
        action = request.form.get("action")
        active_tab = request.form.get("tab", active_tab)

        if action == "personal":
            display_name = request.form.get("display_name", "").strip()
            birthday = request.form.get("birthday", "").strip()
            updates = {}
            if display_name:
                updates["display_name"] = display_name[:80]
            if birthday:
                updates["birthday"] = birthday
            if updates:
                _safe_user_update(current_user.id, updates)
                user_data.update(updates)
                success = "Personal info saved."
            else:
                error = "Nothing to update."

        elif action == "account":
            import re
            email = request.form.get("email", "").strip().lower()
            username = request.form.get("username", "").strip()
            updates = {}
            if email:
                if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
                    error = "Enter a valid email address."
                else:
                    dup = supabase.table("users").select("id").eq("email", email).neq("id", current_user.id).execute()
                    if dup.data:
                        error = "That email is already in use."
                    else:
                        updates["email"] = email
            if not error and username and username != user_data.get("username"):
                if not re.match(r'^[a-zA-Z0-9_]{3,24}$', username):
                    error = "Username must be 3–24 characters (letters, numbers, underscore)."
                else:
                    dup = supabase.table("users").select("id").eq("username", username).execute()
                    if dup.data:
                        error = "That username is already taken."
                    else:
                        updates["username"] = username
            if not error and updates:
                _safe_user_update(current_user.id, updates)
                user_data.update(updates)
                success = "Account details saved."

        elif action == "social":
            updates = {}
            for field in ("social_twitter", "social_instagram", "social_tiktok", "social_youtube", "social_website"):
                updates[field] = _normalize_social(field, request.form.get(field, ""))
            _safe_user_update(current_user.id, updates)
            user_data.update(updates)
            success = "Social profiles saved."

        elif action == "promo":
            active_tab = "offers"
            result, err = _redeem_promo(current_user.id, request.form.get("code", ""))
            if err:
                error = err
            else:
                success = result["message"]
                user_data = _load_settings_user(current_user.id)

        elif action == "password":
            pw_res = supabase.table("users").select("password").eq("id", current_user.id).single().execute()
            stored_hash = (pw_res.data or {}).get("password", "")
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not check_password_hash(stored_hash, current_pw):
                error = "Current password is incorrect."
            elif len(new_pw) < 8:
                error = "New password must be at least 8 characters."
            elif new_pw != confirm_pw:
                error = "Passwords don't match."
            else:
                supabase.table("users").update({"password": generate_password_hash(new_pw)}).eq("id", current_user.id).execute()
                success = "Password updated."

    billing = _get_billing_info(user_data.get("stripe_customer_id"))
    checkout_promo = session.get("stripe_promo_code")
    return render_template(
        "settings.html",
        user=user_data,
        billing=billing,
        packages=CREDIT_PACKAGES,
        checkout_promo=checkout_promo,
        success=success,
        error=error,
        active_tab=active_tab,
    )


# ── PercfectStudios hub + dedicated pages ─────────────────
def _studio_user_credits():
    user_data = None
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        res = (
            supabase.table("users")
            .select("picture_credits,video_credits,images_today,videos_today,has_purchased")
            .eq("id", current_user.id)
            .single()
            .execute()
        )
        user_data = res.data
    return user_data


@app.route("/percfectstudios")
def percfectstudios():
    """Studio Homebase — same as / (new diner hub)."""
    return Response(_layout_page_html("home"), mimetype="text/html")


@app.route("/studios")
@app.route("/studios/")
@app.route("/home")
@app.route("/homebase")
def studios_hub_alias():
    """Aliases for homepage (new diner hub)."""
    return Response(_layout_page_html("home"), mimetype="text/html")


@app.route("/percfectstudios/hub-legacy")
def percfectstudios_hub_legacy():
    return render_template("percfect_studio_hub.html", user=_studio_user_credits())


@app.route("/studios/percfectphotos")
@app.route("/studios/photos")  # natural alias — was 404; product path is /percfectstudios/photos
@app.route("/percfectphotos")
@app.route("/percfectstudios/photos")
@app.route("/studio/photos")
def percfect_photos():
    """PERCFECT PHOTOS — full studio (refs, library pick, batch of 10, real credits)."""
    return render_template(
        "percfectstudios.html",
        user=_studio_user_credits(),
        studio_mode="photos",
        video_rate=VIDEO_CREDITS_PER_SECOND,
    )


@app.route("/percfectstudios/photos-mock")
def percfect_photos_mock():
    """Broken mock shell kept only for design reference — not the product path."""
    return render_template(
        "photos_live.html",
        user=_studio_user_credits(),
    )


def _render_videos_product():
    """Product Videos board only (percfectstudios.html). Does not touch videos_live or other pages."""
    return render_template(
        "percfectstudios.html",
        user=_studio_user_credits(),
        studio_mode="videos",
        video_rate=VIDEO_CREDITS_PER_SECOND,
        video_ref_rate=VIDEO_REF_CREDITS_PER_SECOND,
        video_extend_rate=VIDEO_EXTEND_CREDITS_PER_SECOND,
    )


@app.route("/studios/percfectvideos")
@app.route("/studios/videos")
@app.route("/percfectvideos")
@app.route("/percfectstudios/videos")
@app.route("/studio/videos")
def percfect_videos():
    """PERCFECT VIDEOS — full studio (animate, extend, library). Hardwired board.

    Product path = percfectstudios.html videos mode (July 16 Claude test state).
    Not the thin videos_live mock.
    """
    return render_template(
        "percfectstudios.html",
        user=_studio_user_credits(),
        studio_mode="videos",
    )

@app.route("/percfectstudios/videos-legacy")
def percfect_videos_legacy():
    """Bookmark alias — same product board."""
    return _render_videos_product()


@app.route("/percfectstudios/videos-mock")
def percfect_videos_mock():
    """Leave videos_live alone — separate mock page, not product."""
    return render_template(
        "videos_live.html",
        user=_studio_user_credits(),
    )



@app.route("/studios/characters")
def studios_characters_alias():
    return redirect("/studios/percfectcharacter")


@app.route("/studios/the-arena")
@app.route("/studios/arena")
def studios_arena_alias():
    return redirect("/studios/percfectcharacter/arena")


def _the_dome_embed_url() -> str:
    """Published THE DOME booth URL (Grok App Builder). HTTPS + host allowlist only."""
    raw = (os.getenv("THE_DOME_URL") or os.getenv("DOME_APP_URL") or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    allowed = host in {
        "grok.com",
        "percfectai.com",
        "www.percfectai.com",
        "percfectstudios.onrender.com",
    } or host.endswith((".grok.com", ".grok-sandbox.com"))
    if not allowed:
        return ""
    return raw.split("#", 1)[0]


@app.route("/studios/the-dome")
@app.route("/studios/dome")
@app.route("/the-dome")
@login_required
def the_dome_page():
    """THE DOME — living 3D stage + silent director booth. Login required (3D private)."""
    return render_template(
        "the_dome.html",
        user=_studio_user_credits(),
        dome_url=_the_dome_embed_url(),
    )


@app.route("/studios/motion")
def studios_motion_alias():
    return redirect("/studios/percfectmotion")


@app.route("/percfectstudios/recent")
def recent_generations():
    try:
        res = supabase.table("generations")\
            .select("output_url,prompt,type")\
            .eq("type", "image")\
            .order("created_at", desc=True)\
            .limit(9)\
            .execute()
        return jsonify(res.data or [])
    except Exception:
        return jsonify([])


@app.route("/api/my-library")
def my_library():
    """Logged-in user's own media only: characters, photos, videos, motion backgrounds.

    Session cookie OR X-API-Key (Chrome extension / Kodi). Never wipe the whole
    characters list if one row fails serialize.
    """
    uid = None
    if current_user.is_authenticated:
        uid = current_user.id
    else:
        key = request.headers.get("X-API-Key")
        if key:
            try:
                res = (
                    supabase.table("users")
                    .select("id")
                    .or_(f"api_key1.eq.{key},api_key2.eq.{key}")
                    .limit(1)
                    .execute()
                )
                if res.data:
                    uid = res.data[0]["id"]
            except Exception:
                app.logger.exception("my-library API key lookup failed")
    if not uid:
        return jsonify({"error": "Not authenticated"}), 401
    characters = []
    photos = []
    videos = []
    backgrounds = []

    # ── Characters (same resilience as character_list) ──
    try:
        try:
            cres = (
                supabase.table("characters")
                .select("id,name,gender,images,primary_image_url,spin_video_url,prompt,created_at,versions,active_version_id")
                .eq("user_id", uid)
                .order("created_at", desc=True)
                .limit(400)
                .execute()
            )
        except Exception:
            cres = (
                supabase.table("characters")
                .select("id,name,gender,images,primary_image_url,spin_video_url,prompt,created_at")
                .eq("user_id", uid)
                .order("created_at", desc=True)
                .limit(400)
                .execute()
            )
        for c in (cres.data or []):
            try:
                ser = _serialize_character(c)
                imgs = [u for u in (ser.get("images") or []) if isinstance(u, str) and u]
                primary = ser.get("primary_image_url") or (imgs[0] if imgs else "") or c.get("primary_image_url") or ""
                if not primary:
                    # last resort: unwrap packed images field
                    shots, _v, _a = _split_images_field(c.get("images"))
                    primary = (shots[0] if shots else "") or ""
                    if shots and not imgs:
                        imgs = shots
                characters.append({
                    "kind": "character",
                    "id": ser.get("id") or c.get("id"),
                    "name": ser.get("name") or c.get("name") or "Unnamed",
                    "url": primary,
                    "primary_image_url": primary,
                    "images": imgs,
                    "spin_video_url": ser.get("spin_video_url") or c.get("spin_video_url"),
                    "gender": ser.get("gender") or c.get("gender"),
                    "prompt": ser.get("prompt") or c.get("prompt"),
                    "thumb": primary,
                    "versions": ser.get("versions") or [],
                    "active_version_id": ser.get("active_version_id") or "v1",
                })
            except Exception as e:
                app.logger.warning("my-library serialize character %s failed: %s", c.get("id"), e)
                primary = c.get("primary_image_url") or ""
                if not primary:
                    shots, _v, _a = _split_images_field(c.get("images"))
                    primary = shots[0] if shots else ""
                if not primary and not c.get("id"):
                    continue
                characters.append({
                    "kind": "character",
                    "id": c.get("id"),
                    "name": c.get("name") or "Unnamed",
                    "url": primary,
                    "primary_image_url": primary,
                    "images": [primary] if primary else [],
                    "spin_video_url": c.get("spin_video_url"),
                    "gender": c.get("gender"),
                    "prompt": c.get("prompt"),
                    "thumb": primary,
                    "versions": [],
                    "active_version_id": "v1",
                })
    except Exception:
        app.logger.exception("my-library characters query failed for user %s", uid)

    # ── Generations → photos / videos / backgrounds ──
    try:
        # Finish any videos that timed out here but completed on xAI's side
        _reclaim_pending_videos(uid)
    except Exception:
        app.logger.exception("my-library pending-video reclaim failed for user %s", uid)
    try:
        # source_page / chain_id may be missing until migrations run — fall back.
        try:
            gres = (
                supabase.table("generations")
                .select("id,type,prompt,output_url,preview_url,source_page,chain_id,created_at")
                .eq("user_id", uid)
                .order("created_at", desc=True)
                .limit(400)
                .execute()
            )
        except Exception:
            gres = (
                supabase.table("generations")
                .select("id,type,prompt,output_url,preview_url,created_at")
                .eq("user_id", uid)
                .order("created_at", desc=True)
                .limit(400)
                .execute()
            )
        for g in (gres.data or []):
            try:
                gtype = (g.get("type") or "").lower()
                url = g.get("output_url") or g.get("preview_url") or ""
                if not url:
                    continue
                # Still rendering on xAI / dead jobs — not showable media
                if gtype in ("video_pending", "video_failed") or url.startswith("xai-job://"):
                    continue
                prompt = g.get("prompt") or ""
                prev = (g.get("preview_url") or "").strip()
                # Video posters must be a real still — never the mp4 URL itself
                if gtype == "video":
                    thumb = prev if (prev and prev != url and not any(
                        ext in prev.lower() for ext in (".mp4", ".webm", ".mov")
                    )) else ""
                else:
                    thumb = prev or url
                from video_chains import parse_video_chain_id
                chain_id = parse_video_chain_id(g) or (str(g.get("id")) if gtype == "video" else "")
                item = {
                    "id": g.get("id"),
                    "url": url,
                    "thumb": thumb,
                    "preview_url": thumb if gtype == "video" else (prev or url),
                    "name": (prompt[:60] if prompt else gtype) or "media",
                    "prompt": prompt,
                    "type": gtype,
                    "created_at": g.get("created_at"),
                    "chain_id": chain_id or None,
                }
                if gtype == "image" and "motion filled background" in prompt.lower():
                    backgrounds.append({
                        **item,
                        "kind": "background",
                        "label": prompt.replace("Motion filled background:", "").strip() or "Motion scene",
                        "name": prompt.replace("Motion filled background:", "").strip() or "Motion scene",
                    })
                elif gtype == "video":
                    videos.append({**item, "kind": "video"})
                elif gtype == "image":
                    photos.append({**item, "kind": "photo"})
                else:
                    if any(ext in url.lower() for ext in (".mp4", ".webm", ".mov")):
                        videos.append({**item, "kind": "video"})
                    else:
                        photos.append({**item, "kind": "photo"})
            except Exception as e:
                app.logger.warning("my-library generation row %s failed: %s", g.get("id"), e)
    except Exception:
        app.logger.exception("my-library generations query failed for user %s", uid)

    cards = []
    try:
        cres = (
            supabase.table("characters")
            .select("id,name,gender,card_art_url,card_serial,primary_image_url,card_level,card_xp")
            .eq("user_id", uid)
            .order("created_at", desc=True)
            .limit(400)
            .execute()
        )
        for c in cres.data or []:
            url = (c.get("card_art_url") or "").strip()
            if not url:
                continue
            cards.append({
                "kind": "card",
                "id": c.get("id"),
                "name": c.get("name") or "Card",
                "url": url,
                "thumb": url,
                "serial": c.get("card_serial") or "",
                "gender": c.get("gender"),
                "xp": int(c.get("card_xp") or 0),
                "level": _card_level_from_xp(c.get("card_xp") or 0),
            })
    except Exception:
        app.logger.exception("my-library cards query failed for user %s", uid)

    # Full lists — client paginates (library page + sidebar). Counts match lengths.
    return jsonify({
        "characters": characters,
        "photos": photos,
        "videos": videos,
        "cards": cards,
        "backgrounds": backgrounds,
        "counts": {
            "characters": len(characters),
            "photos": len(photos),
            "videos": len(videos),
            "cards": len(cards),
            "backgrounds": len(backgrounds),
        },
    })



def _friendly_image_error(e) -> str:
    """Turn a raw xAI exception into a clear, user-facing reason. Credits are only
    charged on success, so a failure here never costs the user a credit — say so."""
    raw = str(e).lower()
    if any(k in raw for k in ("moderat", "policy", "safety", "flagged", "nsfw", "rejected",
                              "violat", "explicit", "blocked", "content filter", "not allowed")):
        return ("That prompt was rejected by the image provider's content filter, so no image "
                "was created. You were NOT charged a credit. Try rephrasing your prompt.")
    if "timeout" in raw or "timed out" in raw:
        return "The image provider timed out, so nothing was created. You were NOT charged — please try again."
    return "The image couldn't be generated. You were NOT charged a credit. Please try again."


# Photos size chip → xAI Imagine JSON `aspect_ratio`. Default auto. Never prompt text.
PHOTO_ASPECT_RATIOS = {
    "auto": "auto",
    "1:1": "1:1",
    "square": "1:1",
    "9:16": "9:16",
    "portrait": "9:16",
    "16:9": "16:9",
    "landscape": "16:9",
    "3:4": "3:4",
    "4:3": "4:3",
}


def _photo_aspect_ratio_from_request() -> str:
    raw = (request.form.get("aspect_ratio") or request.form.get("size") or "auto").strip()
    return PHOTO_ASPECT_RATIOS.get(raw) or PHOTO_ASPECT_RATIOS.get(raw.lower()) or "auto"


def _photo_remake_prompt_for_aspect(aspect: str) -> str:
    """Empty prompt + refs. Frame comes from xAI aspect_ratio, not this text."""
    return (
        "Resize this photo and upscale to 8k without stretching or squashing the subject. "
        "Preserve natural proportions and identity from the reference; "
        "pad the background if needed instead of distorting the body or face."
    )


def _photo_seed_prompt_for_aspect(aspect: str) -> str:
    """Empty prompt, no refs. Frame comes from xAI aspect_ratio, not this text."""
    return "Create a striking, highly detailed 8k image"


@app.route("/studios/library")
@app.route("/library")
@login_required
def library_page():
    """Full-page library — photos, characters, cards, videos. Quick Look + download."""
    return render_template("library_page.html")


@app.route("/api/my-library/download", methods=["POST"])
@login_required
def library_download_selected():
    """Zip selected library URLs (user's own media)."""
    import io as _io
    import zipfile

    body = request.get_json(silent=True) or {}
    urls = body.get("urls") or []
    if not isinstance(urls, list) or not urls:
        return jsonify({"error": "Select at least one item."}), 400
    buf = _io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, u in enumerate(urls[:80]):
            if not isinstance(u, str) or not u.startswith(("http://", "https://")):
                continue
            try:
                r = requests.get(u, timeout=60)
                r.raise_for_status()
                ext = "jpg"
                lu = u.lower().split("?")[0]
                ctype = (r.headers.get("Content-Type") or "").lower()
                if lu.endswith(".png") or "image/png" in ctype:
                    ext = "png"
                elif lu.endswith(".webp") or "image/webp" in ctype:
                    ext = "webp"
                elif lu.endswith(".gif") or "image/gif" in ctype:
                    ext = "gif"
                elif lu.endswith(".mp4") or "video/mp4" in ctype:
                    ext = "mp4"
                elif lu.endswith(".webm") or "video/webm" in ctype:
                    ext = "webm"
                elif lu.endswith(".mov") or "video/quicktime" in ctype:
                    ext = "mov"
                elif "video/" in ctype:
                    ext = "mp4"
                zf.writestr(f"percfect-{i + 1:02d}.{ext}", r.content)
                n += 1
            except Exception:
                app.logger.warning("library zip skip %s", u[:80])
    if n < 1:
        return jsonify({"error": "Could not download those files."}), 400
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="percfect-library.zip",
    )


@app.route("/percfectstudios/library", methods=["GET"])
@login_required
def studio_library():
    """Photos/Videos page gallery — list of generation rows for the logged-in user.

    Frontend expects a JSON array: [{id, type, output_url, prompt, created_at}, …]
    (not the /api/my-library bag). Missing this route left the page gallery empty
    even when images finished and appeared in the 📚 sidebar.
    """
    try:
        _reclaim_pending_videos(current_user.id)
    except Exception:
        app.logger.exception("studio_library pending-video reclaim failed")
    try:
        try:
            res = (
                supabase.table("generations")
                .select("id,type,prompt,output_url,preview_url,source_page,chain_id,created_at")
                .eq("user_id", current_user.id)
                .order("created_at", desc=True)
                .limit(120)
                .execute()
            )
        except Exception:
            # Live DB may lack source_page / chain_id until migration runs.
            res = (
                supabase.table("generations")
                .select("id,type,prompt,output_url,preview_url,created_at")
                .eq("user_id", current_user.id)
                .order("created_at", desc=True)
                .limit(120)
                .execute()
            )
    except Exception as e:
        app.logger.exception("studio_library query failed")
        return jsonify({"error": str(e)[:200]}), 500

    out = []
    from video_chains import parse_video_chain_id
    for g in res.data or []:
        url = g.get("output_url") or g.get("preview_url") or ""
        if not url:
            continue
        gtype = (g.get("type") or "image").lower()
        if gtype in ("video_pending", "video_failed") or url.startswith("xai-job://"):
            continue
        # Normalize exotic types to image/video for the studio grids
        if gtype not in ("image", "video"):
            if any(ext in url.lower() for ext in (".mp4", ".webm", ".mov")):
                gtype = "video"
            else:
                gtype = "image"
        prev = (g.get("preview_url") or "").strip()
        if gtype == "video":
            # Only expose a still poster — not the mp4 itself
            if prev == url or any(ext in prev.lower() for ext in (".mp4", ".webm", ".mov")):
                prev = ""
        else:
            prev = prev or url
        chain_id = parse_video_chain_id(g) or (str(g.get("id")) if gtype == "video" else None)
        out.append({
            "id": g.get("id"),
            "type": gtype,
            "output_url": url,
            "preview_url": prev,
            "thumb": prev,
            "prompt": g.get("prompt") or "",
            "created_at": g.get("created_at"),
            "chain_id": chain_id,
        })
    return jsonify(out)


@app.route("/percfectstudios/save-image", methods=["POST"])
@app.route("/studios/save-image", methods=["POST"])
@login_required
def studio_save_image():
    """Persist an uploaded still (e.g. Photos crop) into the user library."""
    f = request.files.get("image") or request.files.get("file")
    if not f:
        return jsonify({"error": "image required"}), 400
    raw = f.read() or b""
    if not raw:
        return jsonify({"error": "empty image"}), 400
    if len(raw) > 12 * 1024 * 1024:
        return jsonify({"error": "image too large (12MB max)"}), 400
    filename = (getattr(f, "filename", None) or "crop.jpg").lower()
    if filename.endswith(".png"):
        ext, ctype = "png", "image/png"
    elif filename.endswith(".webp"):
        ext, ctype = "webp", "image/webp"
    else:
        ext, ctype = "jpg", "image/jpeg"
    try:
        url = _persist_image_bytes(raw, ext=ext, content_type=ctype)
    except Exception as e:
        app.logger.exception("save-image persist failed")
        return jsonify({"error": str(e)[:200]}), 500
    prompt = (request.form.get("prompt") or "Cropped image").strip()[:500]
    try:
        row = supabase.table("generations").insert({
            "user_id": current_user.id,
            "type": "image",
            "prompt": prompt,
            "output_url": url,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }).execute()
        gen_id = (row.data or [{}])[0].get("id") if isinstance(row.data, list) else None
    except Exception as e:
        app.logger.exception("save-image insert failed")
        return jsonify({"ok": True, "url": url, "warn": str(e)[:120]})
    return jsonify({"ok": True, "url": url, "id": gen_id})


@app.route("/percfectstudios/delete-generation", methods=["POST"])
@login_required
def studio_delete_generation():
    """Delete one of the user's saved generations from the studio library grid."""
    raw = (
        request.form.get("id")
        or (request.get_json(silent=True) or {}).get("id")
        or ""
    )
    gen_id = str(raw).strip()
    if not gen_id:
        return jsonify({"error": "id required"}), 400
    try:
        supabase.table("generations").delete().eq("id", gen_id).eq(
            "user_id", current_user.id
        ).execute()
    except Exception as e:
        app.logger.exception("delete-generation failed")
        return jsonify({"error": str(e)[:200]}), 500
    return jsonify({"ok": True})


@app.route("/percfectstudios/generate-image", methods=["POST"])
@login_required
def generate_image():
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", current_user.id).single().execute()
    user_data = res.data

    prompt = request.form.get("prompt", "").strip()
    style = request.form.get("style", "")
    split_n = _parse_split_n(request.form.get("split_n") or request.form.get("split"))
    aspect = _photo_aspect_ratio_from_request()
    # Slot-stable refs first (need them to allow empty prompt remake)
    slots = _rehost_ref_slots(_get_form_reference_slots(MAX_REFERENCE_PHOTOS))
    has_refs = any(slots)
    has_style = _photo_style_is_set(style)

    # Empty prompt is OK when a size/ratio is selected (always), style, or refs:
    #  - refs → "Resize this photo and upscale to 8k…" (ratio-aware, no stretch)
    #  - no refs → seed image line for that ratio (style can still wrap on top)
    if not prompt:
        if has_refs:
            prompt = _photo_remake_prompt_for_aspect(aspect)
        elif has_style:
            prompt = ""  # _apply_style seeds subject + preset
        else:
            # Size chip alone (Auto / 1:1 / 9:16 / …) — still generate
            prompt = _photo_seed_prompt_for_aspect(aspect)

    # Split-screen (×4 / ×6 / ×8) even if the box was empty — phrase is the prompt.
    # Style is applied here server-side — does NOT rewrite the user's textarea.
    if split_n:
        prompt = _apply_split_screen_prompt(prompt, split_n)
    split_prompt = prompt
    # 📸1️⃣ → <IMAGE_1> for multi-ref edits (user never types engine tags)
    tagged = _normalize_image_ref_tags(_apply_style(split_prompt, style))
    if not (tagged or "").strip():
        tagged = _apply_style(_photo_seed_prompt_for_aspect(aspect), style)
    ref_images, full_prompt = _align_photo_prompt_and_refs(tagged, slots)
    source_image = ref_images[0] if ref_images else None
    cost = photo_generate_cost(len(ref_images))
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": f"Not enough credits. This generate needs {cost} "
                     f"(1 base + 1 per reference) — you have {bal}."
        }), 402

    payload = {
        "full_prompt": full_prompt,
        "source_image": source_image,
        "source_images": ref_images,
        "cost": cost,
        "is_admin": current_user.is_admin,
        "aspect_ratio": aspect,
        "split_n": split_n,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "image", payload)))


@app.route("/percfectstudios/generation-job/<job_id>", methods=["GET"])
@app.route("/studios/generation-job/<job_id>", methods=["GET"])
@login_required
def studio_generation_job(job_id: str):
    """Browser session poll for async studio jobs (character / image / video / arena).

    Failed jobs include an ``error`` message but must return HTTP 200 + status=failed.
    Returning 404 for any payload with ``error`` made the browser treat content-filter
    / xAI failures as "still starting" and poll for minutes (looked like a hung gen).
    """
    data = studio_jobs.status(job_id, current_user.id)
    # Only true "missing job" is 404 — terminal failed still has status=failed + error text
    if data.get("error") and str(data.get("status") or "").lower() not in (
        "failed",
        "error",
        "done",
        "completed",
        "success",
        "processing",
        "pending",
        "queued",
        "running",
    ):
        return jsonify(data), 404
    return jsonify(data)


@app.route("/percfectstudios/task-handlers", methods=["GET"])
def studio_task_handlers_list():
    """Registered backend generation task kinds (for ops/debug).

    key_count / slots refer to the IMAGE/VIDEO pool only (XAI_API_KEYS).
    Chat agents (Vanessa/Mira/Sal/Ashley) and TTS use separate envs and are
    not task-handler kinds — they never share this pool.
    """
    from studio_task_handlers import kinds
    from xai_keys import load_xai_keys
    registered = kinds()
    keys = load_xai_keys()
    # Capacity (not "currently busy") — min of configured concurrency and media keys
    capacity = min(studio_jobs.max_slots, len(keys) if keys else studio_jobs.max_slots)
    try:
        live = studio_jobs._stats() if hasattr(studio_jobs, "_stats") else {}
    except Exception:
        live = {}
    return jsonify({
        "handlers": registered,
        "handler_count": len(registered),
        "max_slots": studio_jobs.max_slots,
        # Legacy field name: means concurrent capacity, not in-flight count
        "active_slots": capacity,
        "slot_capacity": capacity,
        "key_count": len(keys),
        "key_pool": "image_video",
        "key_env": "XAI_API_KEYS",
        "silos": {
            "image_video": "XAI_API_KEYS (this key_count)",
            "chat_agents": "XAI_VANESSA / XAI_MIRA / XAI_SAL|DEBUG / XAI_ASHLEY|USER_SUPPORT",
            "tts": "XAI_TTS_API_KEY",
        },
        "jobs_live": live or None,
        "note": (
            "handler_count is how many job kinds exist; key_count is how many "
            "media keys can run image/video gens in parallel. Chat keys are separate."
        ),
    })


@app.route("/percfectstudios/generate-batch", methods=["POST"])
@login_required
def generate_batch():
    """Queue a batch of separate images (5 or 10). Poll generation-job for results."""
    try:
        raw_n = int(float(str(request.form.get("batch_n") or request.form.get("count") or "10").strip()))
    except (TypeError, ValueError):
        raw_n = 10
    # Only ×5 or ×10 from Photos UI
    batch_n = 5 if raw_n == 5 else 10
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select("picture_credits,video_credits,images_today").eq("id", current_user.id).single().execute()
    user_data = res.data

    prompt = request.form.get("prompt", "").strip()
    style = request.form.get("style", "")
    aspect = _photo_aspect_ratio_from_request()
    slots = _get_form_reference_slots(MAX_REFERENCE_PHOTOS)
    # Legacy single image_url form field → fill first empty slot
    if not any(slots):
        raw = (_get_form_image_url() or "").strip()
        if raw:
            slots[0] = raw
    slots = _rehost_ref_slots(slots)
    has_refs = any(slots)
    has_style = _photo_style_is_set(style)

    if not prompt:
        if has_refs:
            prompt = _photo_remake_prompt_for_aspect(aspect)
        elif has_style:
            prompt = ""  # style-only seed in _apply_style
        else:
            prompt = _photo_seed_prompt_for_aspect(aspect)

    # Same ref alignment as single generate (slot-stable + IMAGE_N remap)
    tagged = _normalize_image_ref_tags(_apply_style(prompt, style))
    if not (tagged or "").strip():
        tagged = _apply_style(_photo_seed_prompt_for_aspect(aspect), style)
    ref_images, full_prompt = _align_photo_prompt_and_refs(tagged, slots)
    source_image = ref_images[0] if ref_images else None

    # 1 credit per batch image (refs free in batch — matches handle_batch spend)
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < batch_n:
        return jsonify({"error": f"A batch of {batch_n} needs {batch_n} credits — you have "
                                 f"{bal}. Buy credits or redeem a coupon code."}), 402

    payload = {
        "full_prompt": full_prompt,
        "source_images": ref_images,
        "source_image": source_image,
        "batch_n": batch_n,
        "is_admin": current_user.is_admin,
        "aspect_ratio": aspect,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "batch", payload)))


@app.route("/percfectstudios/generate-video", methods=["POST"])
@login_required
def generate_video():
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", current_user.id).single().execute()
    user_data = res.data

    prompt = request.form.get("prompt", "").strip()
    # Slot-stable refs 0–3 (📸1️⃣–📸4️⃣). Rehost so xAI can fetch public URLs.
    try:
        slots = _rehost_ref_slots(_get_form_reference_slots(4))
    except Exception:
        slots = [None, None, None, None]
    # Legacy single image_file / image_url → slot 0 if empty
    legacy = _get_form_image_url()
    if legacy and not slots[0]:
        slots[0] = legacy

    # model: default grok (top). wan-2.2 = Replicate WAN under Extend only.
    model = (request.form.get("model") or "grok").strip().lower()

    if model in ("wan-2.2", "wan", "wan2.2", "12.2"):
        # Nick: WAN is fixed 200 seconds — no other choice
        duration = 200
    else:
        try:
            duration = int(request.form.get("duration", 6))
        except (TypeError, ValueError):
            duration = 6
        duration = snap_video_duration(duration, 6)

    # Normalize 📸1️⃣… → <IMAGE_N>, densify slots for xAI reference-to-video
    try:
        prompt = _normalize_image_ref_tags(prompt or "")
    except Exception:
        pass
    try:
        ref_images, prompt = _align_photo_prompt_and_refs(prompt or "", slots)
    except Exception:
        ref_images = [u for u in slots if u]
    image_url = ref_images[0] if len(ref_images) == 1 else (ref_images[0] if ref_images else None)
    # 2+ refs → real multi-ref (reference_images). 1 ref → start-frame image-to-video.
    reference_images = ref_images if len(ref_images) >= 2 else None
    n_refs = len(ref_images) if ref_images else 0

    cost = video_cost(duration, num_reference_images=n_refs)
    rate = video_rate_for_refs(n_refs)
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": f"Not enough credits. This {duration}s video needs {cost} credits "
                     f"({rate}/sec) — you have {bal}.",
        }), 402

    if not prompt and (image_url or reference_images):
        prompt = "animate this"
    if not prompt:
        return jsonify({"error": "Prompt is required."}), 400

    chain_id = (request.form.get("chain_id") or "").strip()
    source_id = (request.form.get("source_id") or "").strip()
    continue_chain = (request.form.get("continue_chain") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    payload = {
        "prompt": prompt,
        "image_url": image_url if not reference_images else None,
        "reference_images": reference_images,
        "duration": duration,
        "cost": cost,
        "is_admin": current_user.is_admin,
        "model": model,
        "chain_id": chain_id or None,
        "source_id": source_id or None,
        "continue_chain": continue_chain,
        "source_video_url": (request.form.get("source_video_url") or "").strip() or None,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "video", payload)))


@app.route("/percfectstudios/trim-video", methods=["POST"])
@login_required
def trim_video():
    """Free ffmpeg cut of the yellow keep-range. Replaces browser MediaRecorder trim."""
    reset_daily_if_needed(current_user.id)
    try:
        start = float(request.form.get("start") or 0)
        end = float(request.form.get("end") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Need start and end times."}), 400
    video_url = (request.form.get("video_url") or request.form.get("url") or "").strip()
    video_file = request.files.get("video_file") or request.files.get("file")
    content = b""
    if video_file and getattr(video_file, "filename", None):
        content = video_file.read()
        content = _ensure_mp4_bytes(content, filename=video_file.filename or "")
    elif video_url.startswith(("http://", "https://")):
        try:
            r = requests.get(video_url, timeout=90)
            r.raise_for_status()
            content = r.content
        except Exception:
            app.logger.exception("trim download failed")
            return jsonify({"error": "Could not load that video to trim."}), 400
    else:
        return jsonify({"error": "Drop or generate a source video first."}), 400
    if not content or len(content) < 100:
        return jsonify({"error": "Video file is empty."}), 400
    try:
        cut = _ffmpeg_trim_mp4(content, start, end)
        url = _persist_video_bytes(cut, content_type="video/mp4")
    except Exception as e:
        app.logger.exception("ffmpeg trim failed")
        return jsonify({"error": str(e) or "Trim failed."}), 500
    # Save trimmed clip into library under the same chain (trim cut logic unchanged).
    from video_chains import resolve_video_chain_id, insert_video_generation
    chain_id = resolve_video_chain_id(
        supabase,
        current_user.id,
        chain_id=(request.form.get("chain_id") or "").strip() or None,
        source_id=(request.form.get("source_id") or "").strip() or None,
        video_url=video_url if video_url.startswith(("http://", "https://")) else None,
    )
    prompt = (request.form.get("prompt") or "").strip() or (
        f"[trim {start:.1f}s–{end:.1f}s]"
    )
    if not prompt.startswith("[trim"):
        prompt = f"[trim {start:.1f}s–{end:.1f}s] {prompt}"
    saved = {}
    try:
        saved = insert_video_generation(
            supabase, current_user.id, prompt, url, chain_id=chain_id,
        )
    except Exception:
        app.logger.exception("trim library save failed")
    return jsonify({
        "ok": True,
        "url": url,
        "chain_id": saved.get("chain_id") or chain_id,
        "generation_id": saved.get("id"),
    })


def _read_posted_video_bytes():
    video_url = (request.form.get("video_url") or request.form.get("url") or "").strip()
    video_file = request.files.get("video_file") or request.files.get("file")
    if video_file and getattr(video_file, "filename", None):
        content = video_file.read()
        return _ensure_mp4_bytes(content, filename=video_file.filename or "")
    if video_url.startswith(("http://", "https://")):
        r = requests.get(video_url, timeout=90)
        r.raise_for_status()
        return r.content
    return b""


@app.route("/percfectstudios/merge-videos", methods=["POST"])
@login_required
def merge_videos():
    """Stitch clips in order into one MP4 (free ffmpeg)."""
    reset_daily_if_needed(current_user.id)
    urls = request.form.getlist("urls") or request.form.getlist("url")
    if not urls:
        body = request.get_json(silent=True) or {}
        raw = body.get("urls") or body.get("clips") or []
        if isinstance(raw, list):
            urls = [str(u).strip() for u in raw if u]
    urls = [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))]
    if len(urls) < 2:
        return jsonify({"error": "Add at least two clips, then Merge."}), 400
    parts = []
    try:
        for u in urls[:16]:
            r = requests.get(u, timeout=90)
            r.raise_for_status()
            parts.append(_ensure_mp4_bytes(r.content, filename=u))
        out = _ffmpeg_concat_mp4(parts)
        url = _persist_video_bytes(out, content_type="video/mp4")
    except Exception as e:
        app.logger.exception("merge videos failed")
        return jsonify({"error": str(e) or "Merge failed."}), 500
    return jsonify({"ok": True, "url": url})


@app.route("/percfectstudios/video-frame", methods=["POST"])
@login_required
def video_frame():
    """Screenshot one frame (free ffmpeg)."""
    reset_daily_if_needed(current_user.id)
    try:
        at_sec = float(request.form.get("time") or request.form.get("at") or 0)
    except (TypeError, ValueError):
        at_sec = 0.0
    try:
        content = _read_posted_video_bytes()
        if not content:
            return jsonify({"error": "Need a video."}), 400
        jpg = _ffmpeg_still_jpg(content, at_sec)
        url = _persist_image_bytes(jpg, ext="jpg", content_type="image/jpeg")
    except Exception as e:
        app.logger.exception("video frame grab failed")
        return jsonify({"error": str(e) or "Could not grab that frame."}), 500
    return jsonify({"ok": True, "url": url})


@app.route("/percfectstudios/extend-video", methods=["POST"])
@login_required
def extend_video():
    """Add a fixed 6-second continuation to an existing video via xAI's native
    extend. Costs video_cost(secs) credits. Used by both the studio and the
    character page (same cost, same behaviour)."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", current_user.id).single().execute()
    user_data = res.data

    video_url = (request.form.get("video_url") or "").strip()
    video_file = request.files.get("video_file")
    if not video_url and video_file and video_file.filename:
        try:
            raw = video_file.read()
            fn = (video_file.filename or "").lower()
            # Free local remux: browser trim is often webm; xAI extend needs real mp4
            raw = _ensure_mp4_bytes(raw, filename=fn)
            video_url = _persist_video_bytes(raw, content_type="video/mp4")
        except Exception:
            app.logger.exception("extend BYO upload failed")
            return jsonify({"error": "Could not upload your video — try a shorter MP4 or paste a URL."}), 500

    prompt = (request.form.get("prompt") or "").strip() \
        or "Continue the video naturally, keeping the same subject, motion, style and lighting."

    # User picks how many seconds to add (defaults to 6); clamp to a safe range.
    try:
        secs = int(request.form.get("duration", EXTEND_SECONDS))
    except (TypeError, ValueError):
        secs = EXTEND_SECONDS
    secs = snap_extend_duration(secs, EXTEND_SECONDS)

    if not video_url:
        return jsonify({"error": "No video to extend."}), 400

    cost = extend_video_cost(secs)
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        return jsonify({"error": f"Extending by {secs}s costs {cost} credits "
                                 f"({VIDEO_EXTEND_CREDITS_PER_SECOND}/sec) — you have {bal}. "
                                 f"Grab more credits or pick a shorter extend."}), 402

    chain_id = (request.form.get("chain_id") or "").strip()
    source_id = (request.form.get("source_id") or "").strip()
    payload = {
        "prompt": prompt,
        "video_url": video_url,
        "secs": secs,
        "cost": cost,
        "is_admin": current_user.is_admin,
        "chain_id": chain_id or None,
        "source_id": source_id or None,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "extend", payload)))


# ── Promo / Offers ────────────────────────────────────────
# Typos / spoken forms → real code in promo_codes
_PROMO_ALIASES = {
    "LAUNCHMOTION": "MOTIONLAUNCH",
    "MOTIONLAUCH": "MOTIONLAUNCH",
    "MOTIONLAUNH": "MOTIONLAUNCH",
    "MOITIONLAUNCH": "MOTIONLAUNCH",
    # Common typos Nick/users type: double-M, LUNCH not LAUNCH
    "MOTIONLUNCH": "MOTIONLAUNCH",
    "MMOTIONLUNCH": "MOTIONLAUNCH",
    "MMOTIONLAUNCH": "MOTIONLAUNCH",
    "MOTIONLAUNC": "MOTIONLAUNCH",
    "MOTION": "MOTIONLAUNCH",
    "LAUNCHWEEK": "LAUNCH",
    "SULTAN": "SULTANSPECIAL",
    "SULTANS": "SULTANSPECIAL",
    "DEVIANT": "DEVIANTVIP",
    "DEVIANTART": "DEVIANTVIP",
    "DAVIP": "DEVIANTVIP",
}

# Free promo codes — private (never list on public pages).
# One unified wallet: image_credits = total credits granted (video_credits always 0).
# Ladder matches product: Try pack = 75 credits · 1 credit = 1 image · ~6 credits = 1s video.
_CANONICAL_PROMO_CODES = {
    "LAUNCH": {
        "description": "Launch welcome — 25 wallet credits",
        "image_credits": 25,  # ~1/3 of Try pack
        "video_credits": 0,
        "max_uses": None,
        "max_uses_per_user": 1,
        "active": True,
    },
    "SULTANSPECIAL": {
        "description": "Sultan VIP — 50 wallet credits",
        "image_credits": 50,
        "video_credits": 0,
        "max_uses": None,
        "max_uses_per_user": 1,
        "active": True,
    },
    "DEVIANTVIP": {
        "description": "DeviantArt VIP — 75 wallet credits (full Try pack)",
        "image_credits": 75,  # equals Try pack
        "video_credits": 0,
        "max_uses": None,
        "max_uses_per_user": 1,
        "active": True,
    },
    "MOTIONLAUNCH": {
        "description": "Motion launch — 60 wallet credits (~10s video or 60 images)",
        "image_credits": 60,  # 10 × 6 credits/sec video rate
        "video_credits": 0,
        "max_uses": None,
        "max_uses_per_user": 1,
        "active": True,
    },
}


def _normalize_promo_code(code: str) -> str:
    """Uppercase, strip spaces/quotes/punctuation → letters+digits only."""
    raw = (code or "").upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "", raw)
    if not cleaned:
        return ""
    return _PROMO_ALIASES.get(cleaned, cleaned)


def _ensure_canonical_promo(code: str) -> Optional[dict]:
    """Upsert product-truth promo so DB amounts always match the ladder."""
    spec = _CANONICAL_PROMO_CODES.get(code)
    if not spec:
        return None
    row = {
        "code": code,
        "description": spec["description"],
        "image_credits": int(spec["image_credits"]),
        "video_credits": int(spec.get("video_credits") or 0),
        "max_uses": spec.get("max_uses"),
        "max_uses_per_user": int(spec.get("max_uses_per_user") or 1),
        "active": True,
    }
    try:
        # Prefer update-if-exists so we don't zero uses_count
        existing = (
            supabase.table("promo_codes")
            .select("id,uses_count")
            .eq("code", code)
            .limit(1)
            .execute()
        )
        rows = (existing.data if existing else None) or []
        if rows:
            supabase.table("promo_codes").update({
                "description": row["description"],
                "image_credits": row["image_credits"],
                "video_credits": row["video_credits"],
                "max_uses": row["max_uses"],
                "max_uses_per_user": row["max_uses_per_user"],
                "active": True,
            }).eq("code", code).execute()
        else:
            row["uses_count"] = 0
            supabase.table("promo_codes").insert(row).execute()
    except Exception as e:
        try:
            supabase.table("promo_codes").upsert({**row, "uses_count": 0}, on_conflict="code").execute()
        except Exception as e2:
            app.logger.warning("promo seed upsert failed %s: %s / %s", code, e, e2)
            return None
    try:
        res = (
            supabase.table("promo_codes")
            .select("*")
            .eq("code", code)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        rows = (res.data if res else None) or []
        return rows[0] if rows else None
    except Exception as e:
        app.logger.warning("promo seed re-read failed %s: %s", code, e)
        return None


def _lookup_stripe_promo(code: str):
    if not stripe.api_key:
        return None
    try:
        promos = stripe.PromotionCode.list(code=_normalize_promo_code(code), active=True, limit=1)
        if promos.data:
            return promos.data[0].id
    except Exception:
        pass
    return None


def _redeem_db_promo(user_id, code: str):
    normalized = _normalize_promo_code(code)
    if not normalized:
        return None, "Enter a promo code."

    # Avoid maybe_single() — empty result raises on some PostgREST clients → 500 Internal Error
    try:
        res = (
            supabase.table("promo_codes")
            .select("*")
            .eq("code", normalized)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        rows = res.data if res and getattr(res, "data", None) is not None else []
        if not isinstance(rows, list):
            rows = [rows] if rows else []
        promo = rows[0] if rows else None
    except Exception as e:
        app.logger.warning("promo lookup failed for %s: %s", normalized, e)
        return None, "Could not look up promo codes right now. Try again or email support@percfectai.com."

    if not promo and normalized in _CANONICAL_PROMO_CODES:
        promo = _ensure_canonical_promo(normalized)

    if not promo:
        # Friendly message — show what they typed (normalized) when useful
        typed = (code or "").strip() or normalized
        return None, f"The code “{typed}” doesn’t exist."

    if promo.get("expires_at"):
        try:
            expires = datetime.datetime.fromisoformat(str(promo["expires_at"]).replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=datetime.timezone.utc)
            if expires < datetime.datetime.now(datetime.timezone.utc):
                return None, f"The code “{normalized}” is expired."
        except Exception:
            pass

    max_uses = promo.get("max_uses")
    if max_uses is not None and (promo.get("uses_count") or 0) >= max_uses:
        return None, f"The code “{normalized}” is no longer available."

    try:
        prior = (
            supabase.table("promo_redemptions")
            .select("id")
            .eq("user_id", user_id)
            .eq("promo_code_id", promo["id"])
            .execute()
        )
        prior_rows = (prior.data if prior else None) or []
        if prior_rows and len(prior_rows) >= (promo.get("max_uses_per_user") or 1):
            return None, f"You already redeemed “{normalized}”."
    except Exception as e:
        app.logger.warning("promo prior check failed: %s", e)

    # Canonical product codes always grant the ladder amounts (fixes stale DB rows).
    canon = _CANONICAL_PROMO_CODES.get(normalized)
    if canon:
        img = int(canon["image_credits"])
        vid = int(canon.get("video_credits") or 0)
        # Keep DB row in sync so admin views match what users get
        try:
            supabase.table("promo_codes").update({
                "image_credits": img,
                "video_credits": vid,
                "description": canon["description"],
                "active": True,
                "max_uses_per_user": int(canon.get("max_uses_per_user") or 1),
            }).eq("id", promo["id"]).execute()
        except Exception as e:
            app.logger.warning("promo amount sync failed %s: %s", normalized, e)
    else:
        img = int(promo.get("image_credits") or 0)
        vid = int(promo.get("video_credits") or 0)
    if img <= 0 and vid <= 0:
        return None, f"The code “{normalized}” doesn’t exist."

    try:
        _grant_credits(user_id, img + vid)
    except Exception as e:
        app.logger.exception("promo grant failed user=%s code=%s: %s", user_id, normalized, e)
        return None, "Could not add credits. Try again or email support@percfectai.com."

    try:
        supabase.table("promo_redemptions").insert({
            "user_id": user_id,
            "promo_code_id": promo["id"],
        }).execute()
        supabase.table("promo_codes").update({
            "uses_count": (promo.get("uses_count") or 0) + 1,
        }).eq("id", promo["id"]).execute()
    except Exception as e:
        app.logger.warning("promo redemption row failed (credits may already be granted): %s", e)

    total = img + vid
    msg = f"Code {normalized} redeemed! Added {total} credits to your wallet."
    if promo.get("description"):
        msg = f"{promo['description']} — {msg}"
    return {"ok": True, "message": msg, "image_credits": img, "video_credits": vid, "code": normalized, "credits": total}, None


def _redeem_promo(user_id, code: str):
    try:
        result, db_err = _redeem_db_promo(user_id, code)
    except Exception as e:
        app.logger.exception("promo redeem crash: %s", e)
        return None, "Something went wrong redeeming that code. Try again or email support@percfectai.com."
    if result:
        return result, None
    if db_err:
        return None, db_err

    stripe_id = _lookup_stripe_promo(code)
    if stripe_id:
        session["stripe_promo_id"] = stripe_id
        session["stripe_promo_code"] = _normalize_promo_code(code)
        session.modified = True
        return {
            "ok": True,
            "checkout_only": True,
            "message": f"Discount code {_normalize_promo_code(code)} will apply at checkout.",
        }, None

    typed = (code or "").strip() or _normalize_promo_code(code)
    return None, f"The code “{typed}” doesn’t exist."


def _promo_return_url(*, ok: bool = False, message: str = "") -> str:
    """Safe post-redeem redirect. Never send users to a dead / blocked path."""
    dest = (request.form.get("redirect") or "").strip()
    # Settings offers tab
    if dest.startswith("/settings") or "settings" in (request.referrer or ""):
        base = url_for("account_settings") + "#offers"
        if message and not ok:
            # query before hash
            from urllib.parse import quote
            return url_for("account_settings") + "?promo_error=" + quote(message[:240]) + "#offers"
        if message and ok:
            from urllib.parse import quote
            return url_for("account_settings") + "?promo_ok=" + quote(message[:240]) + "#offers"
        return base
    # Default: buy credits offers block
    from urllib.parse import quote
    if message and not ok:
        return url_for("buy_credits") + "?promo_error=" + quote(message[:240])
    if message and ok:
        return url_for("buy_credits") + "?promo_ok=" + quote(message[:240])
    return url_for("buy_credits")


@app.route("/redeem-promo", methods=["POST"])
@app.route("/studios/redeem-promo", methods=["POST"])
@login_required
def redeem_promo():
    code = request.form.get("code", "").strip()
    if request.is_json:
        code = (request.get_json() or {}).get("code", code).strip()

    try:
        result, err = _redeem_promo(current_user.id, code)
    except Exception as e:
        app.logger.exception("redeem-promo route crash: %s", e)
        result, err = None, "Something went wrong. Try again or email support@percfectai.com."

    wants_json = request.is_json or "application/json" in request.headers.get("Accept", "")

    if err:
        if wants_json:
            return jsonify({"error": err}), 400
        flash(err, "danger")
        return redirect(_promo_return_url(ok=False, message=err))

    if wants_json:
        return jsonify(result)

    msg = (result or {}).get("message") or "Code redeemed."
    flash(msg, "success")
    return redirect(_promo_return_url(ok=True, message=msg))


# ── Stripe: Buy Credits ───────────────────────────────────
@app.route("/pricing")
def pricing_redirect():
    """Legacy/bot URL — real packs live on buy-credits (login) or homepage #pricing."""
    return redirect(url_for("buy_credits"))


@app.route("/buy-credits")
@login_required
def buy_credits():
    # Keep private promo rows in sync (amounts/descriptions). Never list codes in the template.
    for code in _CANONICAL_PROMO_CODES:
        try:
            _ensure_canonical_promo(code)
        except Exception:
            pass
    return render_template(
        "buy_credits.html",
        packages=CREDIT_PACKAGES,
        subscriptions=SUBSCRIPTION_PLANS,
        video_rate=VIDEO_CREDITS_PER_SECOND,
        stripe_pk=os.getenv("STRIPE_PUBLISHABLE_KEY"),
        checkout_promo=session.get("stripe_promo_code"),
    )


@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    package_key = request.form.get("package")
    pkg = CREDIT_PACKAGES.get(package_key)
    if not pkg:
        flash("Invalid package.", "danger")
        return redirect(url_for("buy_credits"))
    if not stripe.api_key:
        flash("Payments are not configured.", "danger")
        return redirect(url_for("buy_credits"))

    user_data = _load_settings_user(current_user.id)
    customer_id = _ensure_stripe_customer(user_data)
    base_url = _site_base_url()
    bonus_pct = _subscription_bonus_pct(current_user.id)
    grant_credits = topup_bonus_credits(pkg["credits"], bonus_pct)
    checkout_kwargs = {
        "payment_method_types": ["card"],
        "line_items": [package_line_item(pkg)],
        "mode": "payment",
        "success_url": f"{base_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}/buy-credits",
        "metadata": {
            "user_id": str(current_user.id),
            "package": package_key,
            "credits": str(grant_credits),
            "bonus_pct": str(bonus_pct),
        },
    }
    if customer_id:
        checkout_kwargs["customer"] = customer_id
    elif user_data.get("email"):
        checkout_kwargs["customer_email"] = user_data["email"]

    promo_id = session.pop("stripe_promo_id", None)
    if promo_id:
        checkout_kwargs["discounts"] = [{"promotion_code": promo_id}]
    elif request.form.get("promo_code"):
        stripe_id = _lookup_stripe_promo(request.form.get("promo_code"))
        if stripe_id:
            checkout_kwargs["discounts"] = [{"promotion_code": stripe_id}]

    try:
        session_stripe = stripe.checkout.Session.create(**checkout_kwargs)
    except Exception as e:
        app.logger.exception("create-checkout-session failed: %s", e)
        flash(f"Checkout failed: {e}", "danger")
        return redirect(url_for("buy_credits"))
    return redirect(session_stripe.url, code=303)


@app.route("/create-subscription-checkout", methods=["POST"])
@login_required
def create_subscription_checkout():
    plan_key = request.form.get("plan")
    plan = SUBSCRIPTION_PLANS.get(plan_key)
    if not plan:
        flash("Invalid subscription plan.", "danger")
        return redirect(url_for("buy_credits"))
    if not stripe.api_key:
        flash("Payments are not configured.", "danger")
        return redirect(url_for("buy_credits"))

    user_data = _load_settings_user(current_user.id)
    customer_id = _ensure_stripe_customer(user_data)
    base_url = _site_base_url()
    meta = {
        "user_id": str(current_user.id),
        "subscription_plan": plan_key,
        "credits": str(plan["credits_per_month"]),
    }
    checkout_kwargs = {
        "payment_method_types": ["card"],
        "line_items": [subscription_line_item(plan)],
        "mode": "subscription",
        "success_url": f"{base_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}/buy-credits",
        "metadata": meta,
        # So renewals (invoice.payment_succeeded) can find user + plan
        "subscription_data": {"metadata": meta},
    }
    if customer_id:
        checkout_kwargs["customer"] = customer_id
    elif user_data.get("email"):
        checkout_kwargs["customer_email"] = user_data["email"]

    promo_id = session.pop("stripe_promo_id", None)
    if promo_id:
        checkout_kwargs["discounts"] = [{"promotion_code": promo_id}]
    elif request.form.get("promo_code"):
        stripe_id = _lookup_stripe_promo(request.form.get("promo_code"))
        if stripe_id:
            checkout_kwargs["discounts"] = [{"promotion_code": stripe_id}]

    try:
        session_stripe = stripe.checkout.Session.create(**checkout_kwargs)
    except Exception as e:
        app.logger.exception("create-subscription-checkout failed: %s", e)
        flash(f"Subscription checkout failed: {e}", "danger")
        return redirect(url_for("buy_credits"))
    return redirect(session_stripe.url, code=303)


@app.route("/create-embedded-checkout-session", methods=["POST"])
@login_required
def create_embedded_checkout_session():
    """Stripe Embedded Checkout — pay in-page without losing builder state."""
    payload = request.get_json(silent=True) or {}
    package_key = request.form.get("package") or payload.get("package")
    pkg = CREDIT_PACKAGES.get(package_key)
    if not pkg:
        return jsonify({"error": "Invalid package."}), 400
    if not stripe.api_key:
        return jsonify({"error": "Payments are not configured."}), 503

    user_data = _load_settings_user(current_user.id)
    customer_id = _ensure_stripe_customer(user_data)
    base_url = _site_base_url()
    return_flow = request.form.get("return_flow") or payload.get("return_flow") or ""
    return_path = "/studios/percfectcharacter" if return_flow == "character_pack" else "/buy-credits"
    bonus_pct = _subscription_bonus_pct(current_user.id)
    grant_credits = topup_bonus_credits(pkg["credits"], bonus_pct)
    checkout_kwargs = {
        "payment_method_types": ["card"],
        "line_items": [package_line_item(pkg)],
        "mode": "payment",
        "ui_mode": "embedded",
        "return_url": f"{base_url}{return_path}?payment=complete&session_id={{CHECKOUT_SESSION_ID}}",
        "metadata": {
            "user_id": str(current_user.id),
            "package": package_key,
            "return_flow": return_flow,
            "credits": str(grant_credits),
            "bonus_pct": str(bonus_pct),
        },
    }
    if customer_id:
        checkout_kwargs["customer"] = customer_id
    elif user_data.get("email"):
        checkout_kwargs["customer_email"] = user_data["email"]

    promo_id = session.get("stripe_promo_id")
    if promo_id:
        checkout_kwargs["discounts"] = [{"promotion_code": promo_id}]
    else:
        code = request.form.get("promo_code") or payload.get("promo_code")
        if code:
            stripe_id = _lookup_stripe_promo(code)
            if stripe_id:
                checkout_kwargs["discounts"] = [{"promotion_code": stripe_id}]

    try:
        session_stripe = stripe.checkout.Session.create(**checkout_kwargs)
        return jsonify({"client_secret": session_stripe.client_secret})
    except Exception as e:
        app.logger.exception("embedded checkout failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/user-credits")
@login_required
def api_user_credits():
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select("picture_credits,video_credits").eq(
        "id", current_user.id
    ).single().execute()
    u = res.data or {}
    bal = _user_credits(u)
    return jsonify({
        "credits": bal,
        "picture_credits": bal,
        "video_credits": bal,
    })


def _grant_credits_once(payment_id, user_id, credits: int, *, package_key: str = "", meta: dict = None) -> bool:
    """Idempotent credit grant keyed on Stripe session or invoice id."""
    if not payment_id or user_id is None or credits <= 0:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False

    try:
        supabase.table("processed_payments").insert({
            "session_id": payment_id,
            "user_id": uid,
            "package": package_key or (meta or {}).get("subscription_plan") or "credits",
            "image_credits": int(credits),
            "video_credits": 0,
        }).execute()
    except Exception:
        return False

    try:
        _grant_credits(uid, int(credits))
        _safe_user_update(uid, {"has_purchased": True})
        plan = (meta or {}).get("subscription_plan")
        if plan:
            _safe_user_update(uid, {"stripe_subscription_plan": plan})
        return True
    except Exception:
        try:
            supabase.table("processed_payments").delete().eq("session_id", payment_id).execute()
        except Exception:
            pass
        raise


def _stripe_session_paid_amount_cents(session_obj) -> int:
    """Cents Stripe charged. Never trust the browser."""
    if not session_obj:
        return 0
    try:
        if isinstance(session_obj, dict):
            return int(session_obj.get("amount_total") or 0)
        return int(getattr(session_obj, "amount_total", None) or 0)
    except (TypeError, ValueError):
        return 0


def _credits_for_package(package_key: str, meta: dict = None) -> int:
    """Pack credits capped to known package + bonus (blocks metadata inflate)."""
    meta = meta or {}
    pkg = CREDIT_PACKAGES.get(package_key or "")
    if not pkg:
        return 0
    expected = topup_bonus_credits(pkg["credits"], int(meta.get("bonus_pct") or 0))
    claimed = int(meta.get("credits") or 0)
    if claimed <= 0:
        return expected
    return min(claimed, expected)


def _credits_for_subscription(plan_key: str, meta: dict = None) -> int:
    plan = SUBSCRIPTION_PLANS.get(plan_key or "")
    if not plan:
        return 0
    expected = int(plan["credits_per_month"])
    claimed = int((meta or {}).get("credits") or 0)
    if claimed <= 0:
        return expected
    return min(claimed, expected)


def _grant_purchase(session_id, user_id, package_key, meta=None, *, amount_total_cents: int = None) -> bool:
    """One-time pack — refuse $0 sessions (no free credits via Stripe 100% off)."""
    if not session_id or user_id is None:
        return False
    meta = meta or {}
    if amount_total_cents is not None and int(amount_total_cents) <= 0:
        app.logger.warning(
            "stripe grant blocked: $0 session %s package=%s user=%s",
            session_id, package_key, user_id,
        )
        return False
    credits = _credits_for_package(package_key or "", meta)
    if credits <= 0:
        return False
    return _grant_credits_once(session_id, user_id, credits, package_key=package_key or "", meta=meta)


def _grant_subscription(payment_id, user_id, plan_key, meta=None, *, amount_total_cents: int = None) -> bool:
    """Subscription grant — refuse $0 checkouts."""
    plan = SUBSCRIPTION_PLANS.get(plan_key or "")
    if not plan:
        return False
    if amount_total_cents is not None and int(amount_total_cents) <= 0:
        app.logger.warning(
            "stripe sub grant blocked: $0 %s plan=%s user=%s",
            payment_id, plan_key, user_id,
        )
        return False
    credits = _credits_for_subscription(plan_key or "", meta)
    return _grant_credits_once(
        payment_id, user_id, credits,
        package_key=f"sub:{plan_key}",
        meta={"subscription_plan": plan_key, **(meta or {})},
    )


@app.route("/payment-success")
@login_required
def payment_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return redirect(url_for("dashboard"))

    session = stripe.checkout.Session.retrieve(session_id)
    meta = session.metadata or {}
    if str(meta.get("user_id")) != str(current_user.id):
        return redirect(url_for("account_settings") + "#billing")

    if session.customer:
        _safe_user_update(current_user.id, {"stripe_customer_id": session.customer})

    amount_cents = _stripe_session_paid_amount_cents(session)
    granted = False
    credits_added = 0
    # Require real paid money — no no_payment_required / $0 grants
    if session.mode == "subscription" and session.payment_status == "paid":
        granted = _grant_subscription(
            session_id, current_user.id, meta.get("subscription_plan"), meta,
            amount_total_cents=amount_cents,
        )
        if granted:
            credits_added = _credits_for_subscription(meta.get("subscription_plan") or "", meta)
    elif session.payment_status == "paid":
        granted = _grant_purchase(
            session_id, current_user.id, meta.get("package"), meta,
            amount_total_cents=amount_cents,
        )
        if granted:
            credits_added = _credits_for_package(meta.get("package") or "", meta)

    if granted and credits_added:
        flash(f"Payment successful! Added {credits_added} credits to your wallet.", "success")
    elif session.payment_status == "paid" and amount_cents <= 0:
        flash("Checkout completed with $0 charged — no credits added. Contact support if this is wrong.", "warning")
    elif meta.get("package") or meta.get("subscription_plan"):
        flash("Payment received — your credits are on your account.", "info")

    return redirect(url_for("account_settings") + "#billing")


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not (STRIPE_WEBHOOK_SECRET or "").strip():
        app.logger.error("STRIPE_WEBHOOK_SECRET missing — refusing webhook")
        return "", 500

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return "", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {}) or {}
        sid = session.get("id")
        amount_cents = _stripe_session_paid_amount_cents(session)
        if session.get("mode") == "subscription":
            if session.get("payment_status") == "paid":
                _grant_subscription(
                    sid, meta.get("user_id"), meta.get("subscription_plan"), meta,
                    amount_total_cents=amount_cents,
                )
        elif session.get("payment_status") == "paid":
            _grant_purchase(
                sid, meta.get("user_id"), meta.get("package"), meta,
                amount_total_cents=amount_cents,
            )

    elif event["type"] == "invoice.payment_succeeded":
        inv = event["data"]["object"]
        if inv.get("billing_reason") == "subscription_cycle":
            sub_id = inv.get("subscription")
            meta = inv.get("metadata", {}) or {}
            user_id = meta.get("user_id")
            plan_key = meta.get("subscription_plan")
            if sub_id:
                try:
                    sub = stripe.Subscription.retrieve(sub_id)
                    sm = sub.get("metadata") or {}
                    user_id = user_id or sm.get("user_id")
                    plan_key = plan_key or sm.get("subscription_plan")
                except Exception:
                    pass
            if not user_id and inv.get("customer"):
                try:
                    ures = supabase.table("users").select("id,stripe_subscription_plan")\
                        .eq("stripe_customer_id", inv.get("customer")).limit(1).execute()
                    if ures.data:
                        user_id = ures.data[0]["id"]
                        plan_key = plan_key or ures.data[0].get("stripe_subscription_plan")
                except Exception:
                    pass
            plan = SUBSCRIPTION_PLANS.get(plan_key or "")
            amount_paid = 0
            try:
                amount_paid = int(inv.get("amount_paid") or 0)
            except (TypeError, ValueError):
                amount_paid = 0
            if user_id and plan and amount_paid > 0:
                inv_meta = {"credits": str(plan["credits_per_month"]), "subscription_plan": plan_key}
                _grant_subscription(
                    inv.get("id"), user_id, plan_key, inv_meta,
                    amount_total_cents=amount_paid,
                )
            elif user_id and plan and amount_paid <= 0:
                app.logger.warning(
                    "stripe renewal blocked: $0 invoice %s plan=%s user=%s",
                    inv.get("id"), plan_key, user_id,
                )

    return "", 200


# ── Kodi page ─────────────────────────────────────────────
@app.route("/kodi-setup")
@app.route("/kodi-page")
def kodi():
    """Kodi install guide — /kodi-setup; /kodi serves repo zip."""
    api_key = None
    if current_user.is_authenticated:
        res = supabase.table("users").select("api_key1").eq("id", current_user.id).single().execute()
        api_key = res.data.get("api_key1") if res.data else None
    return render_template("kodi.html", api_key=api_key)


# ── API key auth decorator ────────────────────────────────
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or (request.get_json(silent=True) or {}).get("api_key")
        if not key:
            return jsonify({"error": "API key required"}), 401
        res = supabase.table("users").select("*")\
            .or_(f"api_key1.eq.{key},api_key2.eq.{key}")\
            .limit(1).execute()
        if not res.data:
            return jsonify({"error": "Invalid API key"}), 401
        g.api_user = res.data[0]
        return f(*args, **kwargs)
    return decorated


# ── Kodi / external API ───────────────────────────────────
@app.route("/api/generate/image", methods=["POST"])
@require_api_key
def api_generate_image():
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "").strip()
    num_images = int(body.get("num_images", 10))
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    user = g.api_user
    payload = {"prompt": prompt, "num_images": num_images}
    return jsonify(async_payload(enqueue(studio_jobs, user["id"], "api_image", payload)))


@app.route("/api/generate/video", methods=["POST"])
@require_api_key
def api_generate_video():
    user = g.api_user
    bal = _user_credits(user)
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt", "").strip()
    image_url = body.get("image_url", "").strip() or None
    duration = int(body.get("duration", 6))
    duration = max(5, min(15, duration))
    cost = video_cost(duration)
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if bal < cost:
        return jsonify({"error": f"Not enough credits. Need {cost}, have {bal}."}), 402

    payload = {"prompt": prompt, "image_url": image_url, "duration": duration, "cost": cost}
    return jsonify(async_payload(enqueue(studio_jobs, user["id"], "api_video", payload)))


@app.route("/api/generation-job/<job_id>", methods=["GET"])
def api_generation_job(job_id: str):
    """Poll async job: logged-in browser session OR external X-API-Key (Kodi / API clients).

    Previously this route was API-key-only. The studio JS fell back here after a 404 on
    the session poll path and users saw \"API key required\" on normal character generate.
    """
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    else:
        key = request.headers.get("X-API-Key") or (request.get_json(silent=True) or {}).get("api_key")
        if not key:
            # Also accept ?api_key= for simple clients
            key = (request.args.get("api_key") or "").strip() or None
        if key:
            res = (
                supabase.table("users")
                .select("*")
                .or_(f"api_key1.eq.{key},api_key2.eq.{key}")
                .limit(1)
                .execute()
            )
            row = (res.data or [None])[0]
            if not row:
                return jsonify({"error": "Invalid API key"}), 401
            user_id = row["id"]
    if user_id is None:
        # Prefer login wording for browsers; API clients still understand this
        if request.headers.get("X-API-Key"):
            return jsonify({"error": "Invalid API key"}), 401
        return jsonify({"error": "Log in to continue."}), 401

    data = studio_jobs.status(job_id, user_id)
    # Same as session poll: failed jobs have error text but are not "not found"
    if data.get("error") and str(data.get("status") or "").lower() not in (
        "failed",
        "error",
        "done",
        "completed",
        "success",
        "processing",
        "pending",
        "queued",
        "running",
    ):
        return jsonify(data), 404
    return jsonify(data)


@app.route("/api/gallery", methods=["GET"])
@require_api_key
def api_gallery():
    user = g.api_user
    res = supabase.table("generations")\
        .select("*").eq("user_id", user["id"])\
        .order("created_at", desc=True).limit(50).execute()
    return jsonify(res.data)


# ── Kodi activation flow ─────────────────────────────────

@app.route("/kodi-activate")
def kodi_activate_page():
    device_code = request.args.get("device", "")
    return render_template("kodi_activate.html", device_code=device_code)


@app.route("/api/kodi/activate", methods=["POST"])
def kodi_activate_api():
    import random, string
    data = request.get_json() or {}
    action = data.get("action")
    device_code = data.get("device_code", "")

    if action == "signup":
        user, err = _do_register(
            data.get("username", "").strip(),
            data.get("password", ""),
            data.get("birthday", ""),
            ip=_get_client_ip(),
            email=data.get("email", "").strip().lower(),
        )
        if err:
            return jsonify({"error": err}), 400
    elif action == "login":
        user, err = _do_login(
            data.get("username", "").strip(),
            data.get("password", ""),
        )
        if err:
            return jsonify({"error": err}), 401
    else:
        return jsonify({"error": "Invalid action"}), 400

    try:
        # Generate 6-digit PIN
        pin = ''.join(random.choices(string.digits, k=6))
        expires = (datetime.datetime.now(datetime.timezone.utc)
                   + datetime.timedelta(minutes=10)).isoformat()

        # Store or update kodi session
        dc = device_code or str(uuid.uuid4())
        existing = supabase.table("kodi_sessions").select("id").eq("device_code", dc).execute()
        if existing.data:
            supabase.table("kodi_sessions").update({
                "user_id": user.id, "pin": pin, "activated": True,
                "expires_at": expires,
            }).eq("device_code", dc).execute()
        else:
            supabase.table("kodi_sessions").insert({
                "device_code": dc,
                "user_id": user.id, "pin": pin, "activated": True,
                "expires_at": expires,
            }).execute()

        # Get current credits
        res = supabase.table("users").select("picture_credits,video_credits,api_key1") \
            .eq("id", user.id).single().execute()
        credits = res.data or {}

        return jsonify({
            "pin": pin,
            "username": user.username,
            "image_credits": credits.get("picture_credits", 0),
            "video_credits": credits.get("video_credits", 0),
        })
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/api/kodi/verify", methods=["POST"])
def kodi_verify():
    """Fire Stick calls this with device_code + PIN to get api_key."""
    data = request.get_json() or {}
    device_code = data.get("device_code", "")
    pin = data.get("pin", "")

    session = supabase.table("kodi_sessions").select("*") \
        .eq("device_code", device_code).eq("pin", pin).execute()
    if not session.data:
        return jsonify({"error": "Invalid code. Try again."}), 401

    row = session.data[0]
    # Check expiry
    expires_str = str(row["expires_at"]).replace('Z', '+00:00')
    expires = datetime.datetime.fromisoformat(expires_str)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    if datetime.datetime.now(datetime.timezone.utc) > expires:
        return jsonify({"error": "Code expired. Please re-scan the QR code."}), 401

    # Mark activated
    supabase.table("kodi_sessions").update({"activated": True}) \
        .eq("id", row["id"]).execute()

    # Return api_key + credits
    user_res = supabase.table("users") \
        .select("api_key1,picture_credits,video_credits,username") \
        .eq("id", row["user_id"]).single().execute()
    u = user_res.data or {}

    return jsonify({
        "api_key": u.get("api_key1"),
        "username": u.get("username"),
        "image_credits": u.get("picture_credits", 0),
        "video_credits": u.get("video_credits", 0),
    })


@app.route("/api/kodi/poll/<device_code>")
def kodi_poll(device_code):
    """Fire Stick polls this while waiting for phone activation."""
    session = supabase.table("kodi_sessions").select("*") \
        .eq("device_code", device_code).execute()
    if not session.data:
        return jsonify({"status": "waiting"})

    row = session.data[0]
    expires_str = str(row["expires_at"]).replace('Z', '+00:00')
    expires = datetime.datetime.fromisoformat(expires_str)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    if datetime.datetime.now(datetime.timezone.utc) > expires:
        return jsonify({"status": "expired"})

    if not row.get("activated"):
        return jsonify({"status": "waiting"})

    user_res = supabase.table("users") \
        .select("api_key1,picture_credits,video_credits,username") \
        .eq("id", row["user_id"]).single().execute()
    u = user_res.data or {}

    return jsonify({
        "status": "activated",
        "api_key": u.get("api_key1"),
        "username": u.get("username"),
        "image_credits": u.get("picture_credits", 0),
        "video_credits": u.get("video_credits", 0),
    })


# In-memory TV prompt relay (device_code -> prompt text)
_tv_prompts = {}


@app.route("/api/tv/prompt", methods=["POST"])
def tv_send_prompt():
    data = request.get_json(silent=True) or {}
    device_code = (data.get("device_code") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    if not device_code or not prompt:
        return jsonify({"error": "device_code and prompt required"}), 400
    _tv_prompts[device_code] = prompt
    return jsonify({"ok": True})


@app.route("/api/tv/prompt/<device_code>")
def tv_get_prompt(device_code):
    prompt = _tv_prompts.pop(device_code, None)
    if prompt:
        return jsonify({"prompt": prompt})
    return jsonify({"prompt": None})


@app.route("/api/kodi/credits")
@require_api_key
def kodi_credits():
    """Fire Stick polls this for live credit balance."""
    u = g.api_user
    return jsonify({
        "image_credits": u.get("picture_credits", 0),
        "video_credits": u.get("video_credits", 0),
        "username": u.get("username"),
    })


def _build_princess_prompt(character, scene, style, extra=""):
    parts = [
        PRINCESS_STYLES.get(style, PRINCESS_STYLES["3d"]),
        PRINCESS_CHARACTERS.get(character, ""),
        PRINCESS_SCENES.get(scene, ""),
        extra.strip(),
        "masterpiece, best quality, sharp focus, beautiful composition",
    ]
    return ", ".join(p for p in parts if p)


def _princess_guest_remaining():
    today = datetime.date.today().isoformat()
    key = f"princess_uses_{today}"
    used = int(session.get(key, 0))
    return max(0, GUEST_PRINCESS_DAILY_LIMIT - used), used


def _increment_princess_guest_usage():
    today = datetime.date.today().isoformat()
    key = f"princess_uses_{today}"
    session[key] = int(session.get(key, 0)) + 1
    session.modified = True


@app.route("/percfectpictures")
def percfect_pictures():
    if not _princess_page_enabled():
        return redirect("/")
    return render_template("percfect_pictures.html")


def _render_princess_generator_page():
    if not _princess_page_enabled():
        return redirect("/")
    user_data = None
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        res = supabase.table("users").select("picture_credits,video_credits").eq(
            "id", current_user.id
        ).single().execute()
        user_data = res.data
    return render_template(
        "percfect_pictures2.html",
        user=user_data,
        princess_keys=PRINCESS_KEYS,
        page_path=request.path,
    )


@app.route("/percfectprincess")
@app.route("/percfectpictures2.0")
@app.route("/percfectpictures2")
@app.route("/percfectprincesses")
@app.route("/percper")
@app.route("/percfectper")
def princess_generator_page():
    # Princess + Pictures 2.0 taken down → coming soon (files kept in repo).
    return render_template("coming_soon.html")


# Unlisted subpage only — not linked from nav/homepage (iwat Perchance UI + paywall).
PP_PRIVATE_SLUG = "percfectslutstudios"


@app.route("/percfectstudios/session-info")
@app.route("/api/session-info")
def session_info():
    """Lightweight JSON: login, credits, admin (for static homepage Vanessa)."""
    if not current_user.is_authenticated:
        return jsonify({"logged_in": False, "is_admin": False})
    reset_daily_if_needed(current_user.id)
    is_admin = bool(getattr(current_user, "is_admin", False))
    credits = 0
    try:
        res = supabase.table("users").select("picture_credits,is_admin").eq(
            "id", current_user.id
        ).single().execute()
        row = res.data or {}
        credits = row.get("picture_credits", 0)
        if "is_admin" in row:
            is_admin = bool(row.get("is_admin"))
    except Exception:
        credits = int(getattr(current_user, "picture_credits", 0) or 0)
    return jsonify({
        "logged_in": True,
        "is_admin": is_admin,
        "picture_credits": credits,
    })


@app.route(f"/{PP_PRIVATE_SLUG}", strict_slashes=False)
def perfect_princess_private():
    """Unlisted private page — Perchance engine in iframe + paywall on parent."""
    if not _princess_page_enabled():
        return redirect("/")
    return render_template("percfectslutstudios_host.html")


@app.route("/percfectprincesses/generate", methods=["POST"])
def princess_generate():
    if not _princess_page_enabled():
        return jsonify({"error": "The princess generator has been taken down."}), 503
    if not current_user.is_authenticated:
        remaining, used = _princess_guest_remaining()
        if remaining <= 0:
            return jsonify({
                "error": f"Daily free limit reached ({GUEST_PRINCESS_DAILY_LIMIT}/day). Sign up free for unlimited princesses + studio access.",
                "limit_reached": True,
            }), 429

    character = request.form.get("character", "ariel")
    scene = request.form.get("scene", "castle")
    style = request.form.get("style", "3d")
    extra = request.form.get("prompt", "").strip()
    if character not in PRINCESS_CHARACTERS:
        character = "ariel"
    if scene not in PRINCESS_SCENES:
        scene = "castle"
    if style not in PRINCESS_STYLES:
        style = "3d"

    full_prompt = _build_princess_prompt(character, scene, style, extra)
    user_id = current_user.id if current_user.is_authenticated else 0
    payload = {
        "full_prompt": full_prompt,
        "guest": not current_user.is_authenticated,
    }
    if user_id:
        return jsonify(async_payload(enqueue(studio_jobs, user_id, "princess_image", payload)))
    # Guests: run inline (no user row) — still one handler path
    from studio_task_handlers import dispatch
    try:
        data = dispatch("princess_image", 0, payload)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Percfect Characters ───────────────────────────────────
def _load_bytes(url: str) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def _user_has_purchased(user_id) -> bool:
    try:
        res = supabase.table("users").select("has_purchased,is_admin").eq("id", user_id).single().execute()
        d = res.data or {}
        return bool(d.get("is_admin")) or bool(d.get("has_purchased"))
    except Exception:
        return False


# Embedded in characters.images JSON when DB columns versions/active_version_id
# are missing (migration 20260710_character_versions.sql not applied yet).
VERSIONS_META_FLAG = "__percfect_versions__"


def _parse_versions_field(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return raw if isinstance(raw, list) else []


def _split_images_field(raw):
    """Unpack shots + optional embedded version pack from characters.images.

    Returns (shot_urls: list[str], versions: list|None, active_version_id: str|None).
    Supports:
      - plain list of URL strings (legacy)
      - list of URLs + trailing meta dict {__percfect_versions__: true, versions, active_version_id}
      - dict {shots|images, versions, active_version_id}
    """
    if raw is None:
        return [], None, None
    if isinstance(raw, dict):
        shots = raw.get("shots") or raw.get("images") or []
        urls = [x for x in shots if isinstance(x, str) and x]
        vers = raw.get("versions")
        active = raw.get("active_version_id") or raw.get("active")
        return urls, (vers if isinstance(vers, list) else None), (str(active) if active else None)
    if not isinstance(raw, list):
        return [], None, None
    if raw and isinstance(raw[-1], dict) and raw[-1].get(VERSIONS_META_FLAG):
        meta = raw[-1]
        urls = [x for x in raw[:-1] if isinstance(x, str) and x]
        vers = meta.get("versions")
        active = meta.get("active_version_id") or meta.get("active")
        return urls, (vers if isinstance(vers, list) else None), (str(active) if active else None)
    return [x for x in raw if isinstance(x, str) and x], None, None


def _pack_images_field(shots, versions=None, active_version_id=None):
    """Store active look shots; when versions provided, append embed meta (no extra columns)."""
    urls = [x for x in (shots or []) if isinstance(x, str) and x]
    if not versions:
        return urls
    # Sanitize version image lists so we never nest meta objects
    clean_vers = []
    for v in versions:
        if not isinstance(v, dict):
            continue
        vimgs = [x for x in (v.get("images") or []) if isinstance(x, str) and x]
        primary = v.get("primary_image_url") or (vimgs[0] if vimgs else "")
        if not primary:
            continue
        clean_vers.append({
            "id": str(v.get("id") or f"v{len(clean_vers)+1}"),
            "label": (v.get("label") or v.get("id") or "Look")[:80],
            "images": vimgs if vimgs else [primary],
            "primary_image_url": primary,
            "spin_video_url": v.get("spin_video_url"),
            "created_at": v.get("created_at"),
        })
    meta = {
        VERSIONS_META_FLAG: True,
        "versions": clean_vers,
        "active_version_id": str(active_version_id or "v1"),
    }
    return urls + [meta]


def _hydrate_character_row(c: dict) -> dict:
    """Normalize a DB character row: plain shot list + versions/active from columns or embed."""
    if not c:
        return {}
    out = dict(c)
    shots, emb_vers, emb_active = _split_images_field(out.get("images"))
    out["images"] = shots
    col_vers = _parse_versions_field(out.get("versions"))
    if not col_vers and emb_vers:
        out["versions"] = emb_vers
    if not out.get("active_version_id") and emb_active:
        out["active_version_id"] = emb_active
    return out


def _character_versions(c: dict) -> list:
    """List of looks: v1 original + outfit versions. Always at least one entry."""
    if not c:
        return []
    c = _hydrate_character_row(c)
    vers = _parse_versions_field(c.get("versions"))
    cleaned = []
    for v in vers:
        if not isinstance(v, dict):
            continue
        vid = str(v.get("id") or "").strip() or f"v{len(cleaned)+1}"
        imgs = [x for x in (v.get("images") or []) if isinstance(x, str) and x]
        primary = v.get("primary_image_url") or (imgs[0] if imgs else "")
        if not primary and imgs:
            primary = imgs[0]
        if not primary:
            continue
        cleaned.append({
            "id": vid,
            "label": (v.get("label") or vid)[:80],
            "images": imgs if imgs else [primary],
            "primary_image_url": primary,
            "spin_video_url": v.get("spin_video_url"),
            "created_at": v.get("created_at"),
        })
    # Seed Original from top-level fields if missing
    if not any(v["id"] == "v1" for v in cleaned):
        primary = c.get("primary_image_url")
        imgs = [x for x in (c.get("images") or []) if isinstance(x, str) and x]
        if primary or imgs:
            cleaned.insert(0, {
                "id": "v1",
                "label": "Original",
                "images": imgs if imgs else ([primary] if primary else []),
                "primary_image_url": primary or (imgs[0] if imgs else None),
                "spin_video_url": c.get("spin_video_url"),
                "created_at": c.get("created_at"),
            })
    if not cleaned and c.get("primary_image_url"):
        cleaned = [{
            "id": "v1",
            "label": "Original",
            "images": [x for x in (c.get("images") or []) if isinstance(x, str) and x] or [c.get("primary_image_url")],
            "primary_image_url": c.get("primary_image_url"),
            "spin_video_url": c.get("spin_video_url"),
        }]
    return cleaned


def _resolve_character_version(c: dict, version_id: str = None) -> dict:
    """Active look for a character (images + primary + spin)."""
    c = _hydrate_character_row(c)
    vers = _character_versions(c)
    if not vers:
        shots = [x for x in (c.get("images") or []) if isinstance(x, str) and x]
        return {
            "id": "v1",
            "label": "Original",
            "images": shots,
            "primary_image_url": c.get("primary_image_url"),
            "spin_video_url": c.get("spin_video_url"),
        }
    want = (version_id or c.get("active_version_id") or "v1")
    want = str(want).strip()
    for v in vers:
        if str(v.get("id")) == want:
            return v
    return vers[0]


def _character_save_payload(shots, versions, active_version_id, primary=None, extra=None):
    """Build character update dicts: prefer real columns, always embed pack in images."""
    vers = list(versions or [])
    active_id = str(active_version_id or "v1")
    active = None
    for v in vers:
        if str(v.get("id")) == active_id:
            active = v
            break
    if active is None and vers:
        active = vers[0]
        active_id = str(active.get("id") or "v1")
    active = active or {}
    shot_list = [x for x in (shots or active.get("images") or []) if isinstance(x, str) and x]
    primary_url = primary or active.get("primary_image_url") or (shot_list[0] if shot_list else None)
    packed = _pack_images_field(shot_list, vers, active_id)
    base = {
        "images": packed,
        "primary_image_url": primary_url,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if extra:
        base.update(extra)
    # Full payload includes columns (may fail if migration not applied)
    with_cols = {
        **base,
        "versions": vers,
        "active_version_id": active_id,
    }
    return with_cols, base


def _update_character_row(char_id, user_id, with_cols: dict, fallback: dict):
    """Update character; fall back when versions columns are missing.

    supabase-py 2.5.x: update().eq() returns SyncFilterRequestBuilder without .select().
    Always update then re-read the row.
    """
    def _do_update(payload: dict):
        supabase.table("characters").update(payload).eq("id", char_id).eq(
            "user_id", user_id
        ).execute()

    try:
        _do_update(with_cols)
    except Exception as e:
        app.logger.warning("character update with versions columns failed: %s", e)
        try:
            _do_update(fallback)
        except Exception as e2:
            app.logger.exception("character update fallback failed: %s", e2)
            return None
    try:
        row = (
            supabase.table("characters")
            .select("*")
            .eq("id", char_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        saved = row.data if row else None
    except Exception:
        saved = None
    if saved is not None:
        saved = dict(saved)
        if "versions" in with_cols:
            saved["versions"] = with_cols["versions"]
        if "active_version_id" in with_cols:
            saved["active_version_id"] = with_cols["active_version_id"]
    return saved


def _primaries_for_ids(rows: dict, ids: list, version_ids: list = None) -> list:
    """Resolve primary stills for character id list + optional parallel version ids."""
    vids = list(version_ids or [])
    while len(vids) < len(ids):
        vids.append("")
    out = []
    for idx, i in enumerate(ids):
        key = str(i)
        if key not in rows:
            continue
        look = _resolve_character_version(rows[key], vids[idx] or None)
        url = look.get("primary_image_url")
        if url:
            out.append(url)
    return out


def _serialize_character(c: dict) -> dict:
    c = _hydrate_character_row(c)
    mp = c.get("motion_profile") or {}
    if not isinstance(mp, dict) or not mp.get("anchor"):
        mp = _default_motion_profile()
    vers = _character_versions(c)
    active = _resolve_character_version(c, c.get("active_version_id"))
    active_imgs = [x for x in (active.get("images") or []) if isinstance(x, str) and x]
    if not active_imgs:
        active_imgs = [x for x in (c.get("images") or []) if isinstance(x, str) and x]
    raw_prompt = c.get("prompt") or ""
    display_prompt = user_facing_character_prompt(raw_prompt)
    progress = character_card_progress(
        c, gender=c.get("gender") or "", name=c.get("name") or "", char_id=c.get("id"),
    )
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "gender": c.get("gender"),
        # Active look (backward compatible fields) — always plain URL lists
        "images": active_imgs,
        "primary_image_url": active.get("primary_image_url") or c.get("primary_image_url"),
        "spin_video_url": active.get("spin_video_url") if active.get("spin_video_url") is not None else c.get("spin_video_url"),
        "versions": vers,
        "active_version_id": active.get("id") or "v1",
        "motion_profile": mp,
        # Never leak full engine / xAI templates to roster · profile · library
        "prompt": display_prompt,
        # Card progression (levels 1–4 · abilities unlock)
        "card_level": progress.get("level") or 1,
        "card_xp": progress.get("xp") or 0,
        "card_xp_to_next": progress.get("xp_to_next"),
        "card_abilities": progress.get("abilities") or [],
    }


@app.route("/studios/percfectcharacter")
def percfect_character():
    """Character builder — full studio (base + library 📚 bottom-right). Mock shell at /characters-mock."""
    return percfect_character_legacy()


@app.route("/studios/percfectcharacter-mock")
def percfect_character_mock():
    return render_template(
        "characters_live.html",
        user=_studio_user_credits(),
    )


@app.route("/studios/percfectcharacter-legacy")
def percfect_character_legacy():
    user_data = None
    initial_characters = []
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        res = supabase.table("users").select(
            "picture_credits,video_credits,images_today,videos_today,has_purchased,is_admin"
        ).eq("id", current_user.id).single().execute()
        user_data = res.data or {}
        # Template badges: show unified wallet (one number for all studio spends)
        bal = _user_credits(user_data)
        user_data = dict(user_data)
        user_data["picture_credits"] = bal
        user_data["video_credits"] = bal
        try:
            cres = supabase.table("characters").select("*").eq(
                "user_id", current_user.id
            ).order("created_at", desc=True).execute()
            initial_characters = []
            for c in (cres.data or []):
                try:
                    initial_characters.append(_serialize_character(c))
                except Exception as e:
                    app.logger.warning("serialize character %s failed: %s", c.get("id"), e)
        except Exception:
            app.logger.exception("character page initial roster load failed")
            initial_characters = []
    return render_template(
        "percfect_character.html",
        user=user_data,
        initial_characters=initial_characters,
        is_admin=bool(current_user.is_authenticated and current_user.is_admin),
        pack_cost=character_pack_credit_cost(),
        packages=CREDIT_PACKAGES,
        stripe_pk=os.getenv("STRIPE_PUBLISHABLE_KEY"),
    )


@app.route("/studios/percfectcharacter/generate-one", methods=["POST"])
@login_required
def character_generate_one():
    """Step 1: generate a SINGLE shot for the user to approve.

    Percfect Precision (super_accuracy=1): **5 credits flat** — web-search portrait.
    Regular Generate: **1 credit flat** (one reference photo free).
    Characters allow **one** reference photo only (not multi-ref like Photos).
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}
    bal = _user_credits(u)

    super_accuracy = str(request.form.get("super_accuracy") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    description = request.form.get("description", "").strip()
    gender = request.form.get("gender", "").strip()

    # Characters product: max 1 reference photo
    ref_images = [] if super_accuracy else _get_form_reference_images(1)
    # Legacy single-field fallback
    if not ref_images and not super_accuracy:
        one = _get_form_image_url()
        if one:
            ref_images = [one]
    ref_images = [u for u in (ref_images or []) if u][:1]
    source_image = ref_images[0] if ref_images else None
    n_refs = len(ref_images)
    cost = character_generate_cost(n_refs, super_accuracy=super_accuracy)

    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": (
                f"{'Percfect Precision needs' if super_accuracy else 'You need'} {cost} "
                f"credit{'s' if cost != 1 else ''} — you have {bal}. "
                "Buy credits or redeem a coupon code."
            ),
            "needed": cost,
            "ref_count": n_refs,
            "percfect_precision": super_accuracy,
        }), 402

    # Precision may pass a seed already fetched (client inserted into ref slot)
    seed_image_url = (request.form.get("seed_image_url") or "").strip()
    search_query = (request.form.get("search_query") or "").strip()
    source_page_image = (request.form.get("source_page_image") or "").strip()

    if super_accuracy:
        # Prompt box text is Google-only (used on precision-seed). Generate needs seed photo
        # + gender; do not require description and do not pass it for xAI.
        if not seed_image_url and not description:
            return jsonify({
                "error": "Percfect Precision needs a name to search, or a seed photo already found.",
            }), 400
    elif not ref_images and not description:
        return jsonify({"error": "Upload photo(s) or describe your character."}), 400

    payload = {
        "source_image": source_image,
        "source_images": ref_images,
        # Precision gen: ignore frontend prompt text (empty). Seed step already searched.
        "description": "" if (super_accuracy and seed_image_url) else description,
        "gender": gender,
        "is_admin": current_user.is_admin,
        "super_accuracy": super_accuracy,
        "cost": cost,
        "ref_count": n_refs,
        "seed_image_url": seed_image_url if super_accuracy else "",
        "search_query": search_query if super_accuracy else "",
        "source_page_image": source_page_image if super_accuracy else "",
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_one", payload)))


@app.route("/studios/percfectcharacter/precision-seed", methods=["POST"])
@login_required
def character_precision_seed():
    """Percfect Precision step 1: search \"portrait of {name}\" → first usable seed URL.

    No charge. Client keeps seed in memory (magic), then auto-calls generate-one
    with super_accuracy=1 (5 credits).
    """
    description = request.form.get("description", "").strip()
    if not description:
        return jsonify({
            "error": "Percfect Precision needs the character name so we can search "
                     'for a picture of it. Type the name, then try again.',
        }), 400
    payload = {
        "description": description,
        "is_admin": current_user.is_admin,
    }
    return jsonify(
        async_payload(enqueue(studio_jobs, current_user.id, "character_precision_seed", payload))
    )


@app.route("/studios/percfectcharacter/pack", methods=["POST"])
@login_required
def character_pack():
    """After preview approve: 360 video FIRST (6s 480p), then 4 stills from that video.

    Cost: 1 image credit + 1× video_cost(6). Preview (1st shot) already charged few credits.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today,videos_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}

    primary = request.form.get("primary_image_url", "").strip()
    prompt = request.form.get("prompt", "").strip()
    gender = request.form.get("gender", "").strip()
    name = (request.form.get("name", "").strip() or "Unnamed Character")[:80]
    source_mode = request.form.get("source_mode", "describe").strip()
    if not primary:
        return jsonify({"error": "Generate a first shot first."}), 400

    pack_cost = character_pack_credit_cost()
    bal = _user_credits(u)
    if not current_user.is_admin and bal < pack_cost:
        return jsonify({
            "error": (
                f"Character pack needs {pack_cost} credits "
                f"(1 image + 6s video) — you have {bal}."
            ),
            "needed": pack_cost,
        }), 402

    payload = {
        "primary_image_url": primary,
        "prompt": prompt,
        "gender": gender,
        "name": name,
        "source_mode": source_mode,
        "is_admin": current_user.is_admin,
        "pack_cost": pack_cost,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_pack", payload)))


@app.route("/studios/percfectcharacter/finalize", methods=["POST"])
@login_required
def character_finalize():
    """Legacy: image-edit L/R/back. Prefer /pack (360 first → snapshot 4 from video)."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}

    primary = request.form.get("primary_image_url", "").strip()
    prompt = request.form.get("prompt", "").strip()
    gender = request.form.get("gender", "").strip()
    name = (request.form.get("name", "").strip() or "Unnamed Character")[:80]
    source_mode = request.form.get("source_mode", "describe").strip()
    if not primary:
        return jsonify({"error": "Approve a shot first."}), 400

    pack_cost = character_pack_credit_cost()
    bal = _user_credits(u)
    if not current_user.is_admin and bal < pack_cost:
        return jsonify({
            "error": f"You need {pack_cost} credits for the full character — you have {bal}.",
            "needed": pack_cost,
        }), 402

    # Prefer new pack path (360 first, then stills from video)
    payload = {
        "primary_image_url": primary,
        "prompt": prompt,
        "gender": gender,
        "name": name,
        "source_mode": source_mode,
        "is_admin": current_user.is_admin,
        "pack_cost": pack_cost,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_pack", payload)))


@app.route("/studios/percfectcharacter/refine", methods=["POST"])
@login_required
def character_refine():
    """Fix one of the 4 profile shots from a text note (e.g. 'ponytail not hair down').
    Edits just that pose; the frontend re-runs generate-spin afterward. Costs 1 image credit."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}

    char_id = request.form.get("character_id", "").strip()
    correction = request.form.get("correction", "").strip()
    try:
        slot = int(request.form.get("slot", "-1"))
    except ValueError:
        slot = -1
    if not correction:
        return jsonify({"error": "Describe what to change."}), 400

    cres = supabase.table("characters").select("*").eq("id", char_id).eq("user_id", current_user.id).maybe_single().execute()
    char = cres.data if cres else None
    if not char:
        return jsonify({"error": "Character not found."}), 404
    images = char.get("images") or []
    if slot < 0 or slot >= len(images):
        return jsonify({"error": "Pick which photo to fix."}), 400

    bal = _user_credits(u)
    if not current_user.is_admin and bal < 1:
        return jsonify({"error": f"You need 1 credit — you have {bal}. Buy credits or redeem a coupon code.", "needed": 1}), 402

    payload = {
        "char_id": char_id,
        "correction": correction,
        "slot": slot,
        "is_admin": current_user.is_admin,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_refine", payload)))


@app.route("/studios/percfectcharacter/restyle", methods=["POST"])
@login_required
def character_restyle():
    """Version 2+ on the same player card (outfit / look · 10 credits).

    Always full look — no separate prop tier (users just build another Version).
    Use /split-version for a separate card + 360 (30).
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}

    char_id = request.form.get("character_id", "").strip()
    change = (
        request.form.get("change")
        or request.form.get("outfit")
        or request.form.get("adjust")
        or ""
    ).strip()
    if not change:
        return jsonify({
            "error": "Describe the new outfit (e.g. red leather jacket and boots).",
        }), 400

    cres = (
        supabase.table("characters")
        .select("id,primary_image_url")
        .eq("id", char_id if not str(char_id).isdigit() else int(char_id))
        .eq("user_id", current_user.id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char or not char.get("primary_image_url"):
        # retry raw id if coerce path missed
        try:
            cres2 = (
                supabase.table("characters")
                .select("id,primary_image_url")
                .eq("id", int(char_id) if str(char_id).isdigit() else char_id)
                .eq("user_id", current_user.id)
                .limit(1)
                .execute()
            )
            char = (cres2.data or [None])[0]
        except Exception:
            char = None
    if not char or not char.get("primary_image_url"):
        return jsonify({"error": "Character not found."}), 404

    # Always full Version look (10) — prop/light tier removed
    cost = VERSION_FULL_COST
    bal = _user_credits(u)
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": f"New outfit needs {cost} credits — you have {bal}. Buy credits or redeem a coupon code.",
            "needed": cost,
        }), 402

    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id
    payload = {
        "char_id": cid,
        "change": change,
        "outfit": change,
        "tier": "full",
        "cost": cost,
        "is_admin": current_user.is_admin,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_restyle", payload)))


@app.route("/studios/percfectcharacter/split-version", methods=["POST"])
@login_required
def character_split_version():
    """Promote active (or chosen) Version look → NEW separate player card + 360 spin.

    Costs VERSION_SPLIT_COST (30). Original character and its Version list stay untouched.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today,videos_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}
    bal = _user_credits(u)
    cost = VERSION_SPLIT_COST
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": (
                f"Separate player card needs {cost} credits — you have {bal}. "
                "This clones the active outfit and builds its own 360° spin."
            ),
            "needed": cost,
        }), 402

    char_id = request.form.get("character_id", "").strip()
    version_id = (request.form.get("version_id") or "").strip() or None
    try:
        cid = int(char_id) if str(char_id).isdigit() else char_id
    except (TypeError, ValueError):
        cid = char_id

    payload = {
        "char_id": cid,
        "version_id": version_id,
        "cost": cost,
        "is_admin": current_user.is_admin,
        "name": (request.form.get("name") or "").strip()[:80],
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_split_version", payload)))


@app.route("/studios/percfectcharacter/generate-spin", methods=["POST"])
@login_required
def character_generate_spin():
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}

    char_id = request.form.get("character_id", "").strip()
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id
    cres = (
        supabase.table("characters")
        .select("*")
        .eq("id", cid)
        .eq("user_id", current_user.id)
        .limit(1)
        .execute()
    )
    char = (cres.data or [None])[0]
    if not char:
        return jsonify({"error": "Character not found."}), 404
    if not char.get("primary_image_url"):
        return jsonify({"error": "This character has no image."}), 400

    # Pack path (4 angles + 360): frontend sends pack_included=1 after approve —
    # spin is part of the pack gate; do not charge a second full video fee or 402
    # right after finalize spent angle credits.
    pack_raw = (request.form.get("pack_included") or request.form.get("pack") or "").strip().lower()
    pack_included = pack_raw in ("1", "true", "yes", "on")

    # Spin is 6s video → unified rate (credits per second)
    duration = CHARACTER_SPIN_DURATION_SEC
    cost = 0 if (pack_included or current_user.is_admin) else video_cost(duration)
    bal = _user_credits(user_data)
    if not current_user.is_admin and not pack_included and bal < cost:
        return jsonify({
            "error": f"360° spin needs {cost} credits ({VIDEO_CREDITS_PER_SECOND}/sec × {duration}s) — you have {bal}.",
            "needed": cost,
        }), 402

    # Ensure primary is publicly fetchable before queueing (fixes pack 360 after angles)
    try:
        fixed = _public_image_url_for_xai(char.get("primary_image_url") or "")
        if fixed and fixed != char.get("primary_image_url"):
            supabase.table("characters").update({"primary_image_url": fixed}).eq("id", cid).execute()
    except Exception as e:
        app.logger.warning("spin primary rehost skip: %s", e)

    payload = {
        "char_id": cid,
        # pack_included → skip wallet debit inside handle_spin (same as admin)
        "is_admin": bool(current_user.is_admin or pack_included),
        "cost": cost,
        "duration": duration,
        "pack_included": pack_included,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "spin", payload)))


@app.route("/studios/percfectcharacter/edit", methods=["POST"])
@login_required
def character_edit():
    """Rename / gender / prompt — free. Version 2 appearance goes through /restyle."""
    raw_id = request.form.get("character_id", "").strip()
    if not raw_id:
        return jsonify({"error": "Missing character id."}), 400
    try:
        char_id = int(raw_id)
    except (TypeError, ValueError):
        char_id = raw_id

    try:
        cres = (
            supabase.table("characters")
            .select("*")
            .eq("id", char_id)
            .eq("user_id", current_user.id)
            .limit(1)
            .execute()
        )
        char = (cres.data or [None])[0]
    except Exception as e:
        app.logger.exception("character edit load failed")
        return jsonify({"error": f"Could not load character: {e}"}), 500
    if not char:
        return jsonify({"error": "Character not found."}), 404

    updates = {}
    name = request.form.get("name", "").strip()
    gender = request.form.get("gender", "").strip()
    adjust = (
        request.form.get("adjust", "").strip()
        or request.form.get("change", "").strip()
        or request.form.get("outfit", "").strip()
    )
    if "prompt" in request.form:
        updates["prompt"] = (request.form.get("prompt") or "").strip()[:2000]
    if name:
        updates["name"] = name[:80]
    if gender:
        updates["gender"] = gender

    if adjust:
        # Version 2+ on same character — always full look (10 credits)
        reset_daily_if_needed(current_user.id)
        ures = supabase.table("users").select(
            "picture_credits,video_credits,images_today"
        ).eq("id", current_user.id).single().execute()
        u = ures.data or {}
        cost = VERSION_FULL_COST
        bal = _user_credits(u)
        if not current_user.is_admin and bal < cost:
            return jsonify({
                "error": f"New outfit needs {cost} credits — you have {bal}.",
                "needed": cost,
            }), 402
        payload = {
            "char_id": char_id,
            "change": adjust,
            "outfit": adjust,
            "adjust": adjust,
            "tier": "full",
            "cost": cost,
            "name": name,
            "gender": gender,
            "is_admin": current_user.is_admin,
        }
        return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "character_restyle", payload)))

    if not updates:
        return jsonify({"error": "Nothing to update. Type a name, then Save name."}), 400

    bare = dict(updates)
    try:
        supabase.table("characters").update(bare).eq("id", char_id).eq(
            "user_id", current_user.id
        ).execute()
    except Exception as e:
        app.logger.warning("character edit failed, retry without updated_at: %s", e)
        bare2 = {k: v for k, v in bare.items() if k != "updated_at"}
        try:
            supabase.table("characters").update(bare2).eq("id", char_id).eq(
                "user_id", current_user.id
            ).execute()
        except Exception as e2:
            app.logger.exception("character name/edit update failed")
            err = str(e2)
            if "select" in err.lower():
                err = "Could not save name (database update). Try again or hard-refresh."
            return jsonify({"error": err}), 500

    try:
        reread = (
            supabase.table("characters")
            .select("*")
            .eq("id", char_id)
            .eq("user_id", current_user.id)
            .limit(1)
            .execute()
        )
        saved = (reread.data or [None])[0]
    except Exception:
        saved = None
    if not saved:
        saved = dict(char)
        saved.update(updates)

    if updates.get("name"):
        saved = dict(saved)
        saved["name"] = updates["name"]

    try:
        character = _serialize_character(saved)
    except Exception:
        character = {
            "id": saved.get("id") or char_id,
            "name": saved.get("name") or updates.get("name") or "Unnamed",
            "gender": saved.get("gender"),
            "images": [x for x in (saved.get("images") or []) if isinstance(x, str)],
            "primary_image_url": saved.get("primary_image_url"),
            "spin_video_url": saved.get("spin_video_url"),
            "versions": [],
            "active_version_id": "v1",
            "prompt": saved.get("prompt"),
        }
    if updates.get("name"):
        character["name"] = updates["name"]
    return jsonify({"ok": True, "character": character})


@app.route("/studios/percfectcharacter/characters")
@login_required
def character_list():
    """Same roster as library — never 500 the whole list if one row is messy."""
    try:
        res = (
            supabase.table("characters")
            .select("*")
            .eq("user_id", current_user.id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        app.logger.exception("character_list select failed")
        return jsonify({"characters": [], "error": str(e)[:200]}), 500
    chars = []
    for c in (res.data or []):
        try:
            chars.append(_serialize_character(c))
        except Exception as e:
            app.logger.warning("serialize character %s failed: %s", c.get("id"), e)
            # Minimal safe row so Arena/Motion still see the character
            chars.append({
                "id": c.get("id"),
                "name": c.get("name") or "Unnamed",
                "gender": c.get("gender"),
                "images": c.get("images") or [],
                "primary_image_url": c.get("primary_image_url"),
                "spin_video_url": c.get("spin_video_url"),
                "versions": [{
                    "id": "v1",
                    "label": "Original",
                    "images": c.get("images") or [],
                    "primary_image_url": c.get("primary_image_url"),
                    "spin_video_url": c.get("spin_video_url"),
                }] if c.get("primary_image_url") else [],
                "active_version_id": "v1",
                "motion_profile": _default_motion_profile(),
            })
    return jsonify({"characters": chars, "can_download": _user_has_purchased(current_user.id)})


@app.route("/studios/percfectcharacter/delete", methods=["POST"])
@login_required
def character_delete():
    body = request.get_json(silent=True) or {}
    char_id = (
        request.form.get("character_id")
        or body.get("character_id")
        or body.get("id")
        or ""
    )
    char_id = str(char_id).strip()
    if not char_id:
        return jsonify({"error": "character_id required"}), 400
    try:
        supabase.table("characters").delete().eq("id", char_id).eq("user_id", current_user.id).execute()
    except Exception as e:
        app.logger.exception("character_delete failed")
        return jsonify({"error": str(e)[:200]}), 500
    return jsonify({"ok": True})


@app.route("/studios/percfectcharacter/set-version", methods=["POST"])
@login_required
def character_set_version():
    """Switch active outfit version on a character (v1 original / v2+ looks)."""
    body = request.get_json(silent=True) or {}
    char_id = str(body.get("character_id") or request.form.get("character_id") or "").strip()
    version_id = str(body.get("version_id") or request.form.get("version_id") or "").strip()
    if not char_id or not version_id:
        return jsonify({"error": "character_id and version_id required."}), 400
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id
    cres = (
        supabase.table("characters")
        .select("*")
        .eq("id", cid)
        .eq("user_id", current_user.id)
        .maybe_single()
        .execute()
    )
    char = cres.data if cres else None
    if not char:
        return jsonify({"error": "Character not found."}), 404
    char = _hydrate_character_row(char)
    vers = _character_versions(char)
    look = next((v for v in vers if str(v.get("id")) == str(version_id)), None)
    if not look:
        return jsonify({"error": f"Version {version_id} not found on this character."}), 404
    shots = [x for x in (look.get("images") or []) if isinstance(x, str) and x]
    with_cols, fallback = _character_save_payload(
        shots,
        vers,
        look.get("id") or version_id,
        primary=look.get("primary_image_url"),
    )
    saved = _update_character_row(cid, current_user.id, with_cols, fallback)
    if not saved:
        return jsonify({"error": "Could not switch version."}), 500
    return jsonify({"ok": True, "character": _serialize_character(saved), "version_id": look.get("id")})


@app.route("/studios/percfectcharacter/download/<int:char_id>")
@login_required
def character_download(char_id):
    import zipfile, re
    cres = supabase.table("characters").select("*").eq("id", char_id).eq("user_id", current_user.id).maybe_single().execute()
    char = cres.data if cres else None
    if not char:
        return jsonify({"error": "Character not found."}), 404
    if not _user_has_purchased(current_user.id):
        return jsonify({"error": "Buy credits to unlock downloading your character pack."}), 402

    name = (char.get("name") or "character").strip() or "character"
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "_") or "character"
    images = char.get("images") or []

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{safe}/info.txt",
                   f"Name: {name}\nGender: {char.get('gender','')}\nPrompt: {char.get('prompt','')}\n")
        for i, url in enumerate(images, 1):
            try:
                z.writestr(f"{safe}/shot{i}.jpg", _load_bytes(url))
            except Exception:
                pass
        spin = char.get("spin_video_url")
        if spin:
            try:
                z.writestr(f"{safe}/{safe}_360.mp4", _load_bytes(spin))
            except Exception:
                pass
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'})


# ── Premade character shop (buy finished characters with credits) ──

def _shop_catalog():
    catalog = char_shop.load_catalog(supabase, app.logger, fallback_path=_SHOP_FALLBACK)

    # Backfill PERCFECT watermarks for older listings that only stored clean masters
    try:
        changed = False
        for item in catalog.get("listings") or []:
            if item.get("active") is False:
                continue
            if item.get("preview_image_url"):
                continue
            try:
                char_shop.apply_shop_watermarks(item, supabase)
                changed = True
            except Exception as e:
                app.logger.warning("shop watermark backfill failed for %s: %s", item.get("id"), e)
        if changed:
            char_shop.save_catalog(
                supabase, catalog, app.logger, fallback_path=_SHOP_FALLBACK
            )
    except Exception:
        app.logger.exception("shop watermark backfill error")
    return catalog


@app.route("/studios/character-shop")
@app.route("/studios/premade-characters")
def character_shop_page():
    """Browse and buy premade characters (up to ~25 listings)."""
    user_data = None
    bal = 0
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        res = supabase.table("users").select(
            "picture_credits,video_credits,has_purchased,is_admin"
        ).eq("id", current_user.id).single().execute()
        user_data = res.data
        bal = _user_credits(user_data)
    catalog = _shop_catalog()
    listings = [char_shop.public_listing_view(x) for x in char_shop.active_listings(catalog)]
    return render_template(
        "character_shop.html",
        user=user_data,
        listings=listings,
        balance=bal,
        max_listings=int(catalog.get("max_listings") or char_shop.SHOP_MAX_DEFAULT),
        default_price=int(catalog.get("default_price_credits") or char_shop.SHOP_PRICE_DEFAULT),
        is_admin=bool(current_user.is_authenticated and current_user.is_admin),
    )


@app.route("/api/character-shop")
@app.route("/studios/character-shop/list")
def character_shop_api():
    catalog = _shop_catalog()
    listings = [char_shop.public_listing_view(x) for x in char_shop.active_listings(catalog)]
    return jsonify({
        "listings": listings,
        "count": len(listings),
        "max_listings": int(catalog.get("max_listings") or char_shop.SHOP_MAX_DEFAULT),
        "default_price_credits": int(catalog.get("default_price_credits") or char_shop.SHOP_PRICE_DEFAULT),
    })


@app.route("/api/character-shop/buy", methods=["POST"])
@app.route("/studios/character-shop/buy", methods=["POST"])
@login_required
def character_shop_buy():
    """Spend credits → clone premade snapshot onto buyer's roster."""
    reset_daily_if_needed(current_user.id)
    body = request.get_json(silent=True) or {}
    listing_id = str(body.get("listing_id") or request.form.get("listing_id") or "").strip()
    if not listing_id:
        return jsonify({"error": "Pick a character to buy."}), 400

    catalog = _shop_catalog()
    listing = char_shop.find_listing(catalog, listing_id)
    if not listing:
        return jsonify({"error": "That premade character is no longer available."}), 404

    # Product floor: 30 credits for now (Trading Cards / shop buy)
    price = max(
        int(TRADING_CARD_BUY_CREDITS),
        int(listing.get("price_credits") or char_shop.SHOP_PRICE_DEFAULT or TRADING_CARD_BUY_CREDITS),
    )
    res = supabase.table("users").select("picture_credits,video_credits").eq(
        "id", current_user.id
    ).single().execute()
    user_row = res.data or {}
    bal = _user_credits(user_row)
    if not current_user.is_admin and bal < price:
        return jsonify({
            "error": f"This card costs {price} credits — you have {bal}. Buy credits first.",
            "needed": price,
            "balance": bal,
        }), 402

    try:
        insert_row = char_shop.clone_insert_row(listing, current_user.id)
    except Exception as e:
        return jsonify({"error": str(e) or "Could not prepare character."}), 400

    # Charge first, then insert (refund on insert failure)
    if not current_user.is_admin:
        if not _spend_credits(current_user.id, price, user_row):
            return jsonify({"error": "Could not charge credits — try again."}), 402

    try:
        row = supabase.table("characters").insert(insert_row).execute()
        saved = (row.data or [None])[0]
        if not saved:
            raise Exception("Insert returned empty.")
    except Exception as e:
        app.logger.exception("shop buy insert failed")
        if not current_user.is_admin:
            try:
                _grant_credits(current_user.id, price)
            except Exception:
                pass
        return jsonify({"error": "Purchase failed — you were not charged. Try again."}), 500

    # Refresh balance
    res2 = supabase.table("users").select("picture_credits,video_credits").eq(
        "id", current_user.id
    ).single().execute()
    new_bal = _user_credits(res2.data)

    return jsonify({
        "ok": True,
        "character": _serialize_character(saved),
        "charged": 0 if current_user.is_admin else price,
        "balance": new_bal,
        "message": f"Added “{saved.get('name') or listing.get('name')}” to your roster.",
    })


@app.route("/api/character-shop/admin/publish", methods=["POST"])
@app.route("/studios/character-shop/admin/publish", methods=["POST"])
@login_required
def character_shop_publish():
    """Admin: list one of your characters for sale in the premade shop."""
    if not current_user.is_admin:
        return jsonify({"error": "Admin only."}), 403

    body = request.get_json(silent=True) or {}
    char_id = body.get("character_id") or request.form.get("character_id")
    blurb = (body.get("blurb") or request.form.get("blurb") or "").strip()
    try:
        price = int(body.get("price_credits") or request.form.get("price_credits")
                    or char_shop.SHOP_PRICE_DEFAULT)
    except (TypeError, ValueError):
        price = char_shop.SHOP_PRICE_DEFAULT
    featured = str(body.get("featured") or request.form.get("featured") or "").lower() in (
        "1", "true", "yes", "on",
    )
    if not char_id:
        return jsonify({"error": "character_id required."}), 400
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        cid = char_id

    cres = (
        supabase.table("characters")
        .select("*")
        .eq("id", cid)
        .eq("user_id", current_user.id)
        .maybe_single()
        .execute()
    )
    char = cres.data if cres else None
    if not char:
        # Admin may list any character they own; if not found under their id, try global by id for founders
        cres2 = supabase.table("characters").select("*").eq("id", cid).maybe_single().execute()
        char = cres2.data if cres2 else None
        if not char:
            return jsonify({"error": "Character not found."}), 404

    ser = _serialize_character(char)
    try:
        listing = char_shop.snapshot_from_serialized(
            ser,
            source_character_id=char.get("id"),
            price_credits=price,
            blurb=blurb,
            featured=featured,
            listed_by=current_user.id,
        )
        # Watermark previews for public shop; clean masters only on purchase
        listing = char_shop.apply_shop_watermarks(listing, supabase)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    catalog = _shop_catalog()
    try:
        catalog = char_shop.publish_listing(catalog, listing)
        char_shop.save_catalog(
            supabase, catalog, app.logger, fallback_path=_SHOP_FALLBACK
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "ok": True,
        "listing": char_shop.public_listing_view(listing),
        "count": len(char_shop.active_listings(catalog)),
        "max_listings": int(catalog.get("max_listings") or char_shop.SHOP_MAX_DEFAULT),
        "message": (
            f"Listed “{listing.get('name')}” for {listing.get('price_credits')} credits "
            f"(PERCFECT watermark on previews until purchased)."
        ),
    })


@app.route("/api/character-shop/admin/unlist", methods=["POST"])
@app.route("/studios/character-shop/admin/unlist", methods=["POST"])
@login_required
def character_shop_unlist():
    if not current_user.is_admin:
        return jsonify({"error": "Admin only."}), 403
    body = request.get_json(silent=True) or {}
    listing_id = str(body.get("listing_id") or request.form.get("listing_id") or "").strip()
    # Empty listing_id or "all" → unlist every active premade
    catalog = _shop_catalog()
    try:
        if not listing_id or listing_id.lower() in ("all", "*"):
            for item in catalog.get("listings") or []:
                if item.get("active") is not False:
                    item["active"] = False
                    item["unlisted_at"] = char_shop._now_iso()
        else:
            catalog = char_shop.unlist_listing(catalog, listing_id)
        char_shop.save_catalog(
            supabase, catalog, app.logger, fallback_path=_SHOP_FALLBACK
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "count": len(char_shop.active_listings(catalog))})


def _arena_page_context():
    """Shared context for live Arena + proto (full-page stage)."""
    user_data = None
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        try:
            res = supabase.table("users").select(
                "picture_credits,video_credits,has_purchased"
            ).eq("id", current_user.id).single().execute()
            user_data = res.data
        except Exception:
            user_data = None
    backgrounds = []
    for b in ARENA_BACKGROUNDS:
        row = dict(b)
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            img_path = os.path.join(app.static_folder or "static", "backgrounds", f"{b['key']}{ext}")
            if os.path.exists(img_path):
                row["image_url"] = f"/static/backgrounds/{b['key']}{ext}"
                break
        backgrounds.append(row)
    return dict(
        user=user_data,
        actions=ARENA_ACTIONS_MAIN,
        other_actions=ARENA_ACTIONS_OTHER,
        x18_action_keys=list(ARENA_ACTIONS_OTHER.keys()),
        x18_extra=ARENA_EXTRA_SCENE_CREDITS,
        scenarios=MOTION_SCENARIOS,
        backgrounds=backgrounds,
        video_rate=VIDEO_CREDITS_PER_SECOND,
    )


@app.route("/studios/percfectcharacter/arena")
def percfect_arena():
    # Full-page stage layout (was 500 on broken percfect_arena.html thrash).
    # Template: proto_arena_stage.html — one big Colosseum stage.
    return render_template("proto_arena_stage.html", **_arena_page_context())


MOTION_ANALYZER_URL = os.getenv(
    "MOTION_ANALYZER_URL", "https://percfect-motion-analyzer.onrender.com"
).rstrip("/")

# Motion 4.5 — async track jobs (disk-backed so multi-thread/worker polls find them).
# In-memory-only caused "started" + "Unknown job_id" at the same time when poll
# hit a different worker or process recycle.
_MOTION_JOB_TTL_SEC = 3600
_MOTION_ANALYZE_TIMEOUT = 600  # analyzer CPU can take several minutes
_MOTION_JOB_DIR = Path(os.environ.get("TMPDIR") or "/tmp") / "percfect_motion_jobs"


def _motion_job_path(job_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", job_id or "")[:32]
    return _MOTION_JOB_DIR / f"{safe}.json"


def _motion_job_save(job_id: str, job: dict):
    _MOTION_JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = _motion_job_path(job_id)
    tmp = path.with_suffix(".tmp")
    payload = dict(job)
    payload["job_id"] = job_id
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _motion_job_load(job_id: str):
    path = _motion_job_path(job_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _motion_jobs_cleanup():
    try:
        _MOTION_JOB_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.utcnow().timestamp()
        for path in _MOTION_JOB_DIR.glob("*.json"):
            try:
                age = now - path.stat().st_mtime
                if age > _MOTION_JOB_TTL_SEC:
                    path.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def _wake_motion_analyzer():
    """Ping analyzer health (cold start on Render can take 30–90s)."""
    try:
        requests.get(f"{MOTION_ANALYZER_URL}/health", timeout=90)
    except Exception:
        pass


def _post_motion_analyze(video_bytes: bytes, filename: str, content_type: str,
                         character_count: int, sample_every_n: int):
    """POST to analyzer with retries on 502/503/504 (Render wake / overload)."""
    form = {
        "character_count": str(character_count),
        "sample_every_n": str(sample_every_n),
    }
    last_err = "Motion analyzer unavailable."
    for attempt in range(4):
        if attempt:
            time.sleep(8 + attempt * 6)
            _wake_motion_analyzer()
        files = {
            "video": (
                filename or "upload.mp4",
                BytesIO(video_bytes),
                content_type or "video/mp4",
            ),
        }
        try:
            resp = requests.post(
                f"{MOTION_ANALYZER_URL}/analyze-motion",
                files=files,
                data=form,
                timeout=_MOTION_ANALYZE_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            last_err = (
                "Motion analysis timed out after 10 minutes — try a shorter clip "
                "(6–15s is ideal)."
            )
            continue
        except requests.exceptions.RequestException as e:
            last_err = f"Could not reach the motion analyzer: {e}"
            continue
        body = None
        try:
            body = resp.json()
        except ValueError:
            snippet = (resp.text or "").strip()[:160]
            last_err = (
                f"Motion analyzer returned an invalid response (HTTP {resp.status_code})."
                + (f" {snippet}" if snippet else "")
            )
            if resp.status_code in (502, 503, 504):
                continue
            return None, last_err
        if resp.status_code in (502, 503, 504):
            detail = ""
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("error") or ""
            last_err = (
                detail
                or f"Motion analyzer waking up or busy (HTTP {resp.status_code}). "
                "Wait ~1 min and retry."
            )
            continue
        if resp.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, list):
                detail = "; ".join(str(d.get("msg") or d) for d in detail)
            return None, detail or f"Analyzer error ({resp.status_code})."
        if not isinstance(body, dict):
            return None, "Analyzer returned unexpected payload."
        return body, None
    return None, last_err


def _run_motion_analyze_job(job_id: str, video_bytes: bytes, filename: str,
                            content_type: str, character_count: str, sample_every_n: str):
    """Background: char extract + BG extract + motion track via analyzer service."""
    job = _motion_job_load(job_id) or {
        "status": "processing",
        "created_ts": datetime.datetime.utcnow().timestamp(),
        "result": None,
        "error": None,
    }
    job["status"] = "processing"
    job["error"] = None
    _motion_job_save(job_id, job)
    try:
        try:
            cc = 2 if int(character_count) == 2 else 1
        except (TypeError, ValueError):
            cc = 1
        try:
            sn = max(1, min(5, int(sample_every_n or 4)))
        except (TypeError, ValueError):
            sn = 4
        body, err = _post_motion_analyze(
            video_bytes, filename, content_type, cc, sn,
        )
        if err:
            job["status"] = "failed"
            job["error"] = err
            _motion_job_save(job_id, job)
            return
        # Force success flag for client poller (some bodies omit it)
        body = dict(body)
        body["status"] = "success"
        body["proxy_job_id"] = job_id
        # Rehost plates + motion JSON to Supabase (analyzer /tmp is ephemeral —
        # without this, skeletal overlay 404s and fails immediately).
        try:
            body = _rehost_motion_result(body, job_id=job_id)
            body["assets_durable"] = True
        except Exception as e:
            app.logger.exception("motion asset rehost failed")
            body["assets_durable"] = False
            body["rehost_warning"] = str(e)[:200]
        # PoYo video BG removal ($0.0035/s) primary; MediaPipe plates as fallback.
        try:
            from motion_analyze_poyo import enrich_analysis_with_poyo_bg
            src_path = f"motion_src/{uuid.uuid4().hex}.mp4"
            supabase.storage.from_("previews").upload(
                src_path, video_bytes,
                file_options={"content-type": content_type or "video/mp4", "upsert": "true"},
            )
            public_source_url = f"{SUPABASE_URL}/storage/v1/object/public/previews/{src_path}"
            body = enrich_analysis_with_poyo_bg(
                body, public_source_url,
                rehost_video=lambda url, kind="video": _rehost_motion_asset(url, kind=kind),
            )
        except Exception as e:
            app.logger.warning("poyo bg enrich skipped: %s", e)
            body.setdefault("bg_removal_engine", "mediapipe")
        job["status"] = "success"
        job["result"] = body
        job["error"] = None
        _motion_job_save(job_id, job)
    except requests.exceptions.Timeout:
        job["status"] = "failed"
        job["error"] = (
            "Motion analysis timed out after 10 minutes — try a shorter clip "
            "(6–15s is ideal; full length is still preserved)."
        )
        _motion_job_save(job_id, job)
    except requests.exceptions.RequestException as e:
        job["status"] = "failed"
        job["error"] = f"Could not reach the motion analyzer: {e}"
        _motion_job_save(job_id, job)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"Motion analysis failed: {e}"
        _motion_job_save(job_id, job)


@app.route("/api/motion-health")
def motion_health():
    """Fast health for Motion page — never block the browser for 90s.

    Cold-start: return 200 {status:waking} quickly and ping the analyzer in a
    background thread so the client can start the upload without waiting.
    """
    import threading

    def _ping():
        try:
            requests.get(f"{MOTION_ANALYZER_URL}/health", timeout=120)
        except Exception:
            pass

    try:
        # Short timeout so the UI never freezes on cold start
        resp = requests.get(f"{MOTION_ANALYZER_URL}/health", timeout=4)
        try:
            body = resp.json()
        except ValueError:
            body = {"status": "ok" if resp.ok else "error"}
        if not isinstance(body, dict):
            body = {"raw": body}
        body["motion_product"] = "4.5"
        body["async_track"] = True
        body["proxy"] = "percfectstudios"
        return jsonify(body), (200 if resp.ok else resp.status_code)
    except requests.exceptions.Timeout:
        threading.Thread(target=_ping, daemon=True).start()
        return jsonify({
            "status": "waking",
            "motion_product": "4.5",
            "async_track": True,
            "message": "Analyzer cold-starting — upload can proceed.",
        }), 200
    except requests.exceptions.RequestException:
        threading.Thread(target=_ping, daemon=True).start()
        return jsonify({
            "status": "waking",
            "motion_product": "4.5",
            "async_track": True,
            "message": "Analyzer unreachable right now — retrying wake in background.",
        }), 200


@app.route("/api/analyze-motion", methods=["POST"])
def analyze_motion_proxy():
    """Motion 4.5 async track: return job_id immediately; client polls status.

    Runs character extract + background extract + motion skeleton on the analyzer
    microservice (CPU). Fixes v2 failure mode where the browser hung until proxy 504.
    """
    video = request.files.get("video")
    if not video:
        return jsonify({"detail": "No video file uploaded."}), 400
    try:
        video_bytes = video.read()
    except Exception:
        return jsonify({"detail": "Could not read uploaded video."}), 400
    if not video_bytes:
        return jsonify({"detail": "Empty video file."}), 400
    if len(video_bytes) > 55 * 1024 * 1024:
        return jsonify({"detail": "Video too large (max ~50MB)."}), 413

    _motion_jobs_cleanup()
    job_id = uuid.uuid4().hex[:12]
    character_count = request.form.get("character_count", "1")
    sample_every_n = request.form.get("sample_every_n", "1")
    _motion_job_save(job_id, {
        "status": "queued",
        "created_ts": datetime.datetime.utcnow().timestamp(),
        "result": None,
        "error": None,
    })
    import threading
    t = threading.Thread(
        target=_run_motion_analyze_job,
        args=(
            job_id,
            video_bytes,
            video.filename or "upload.mp4",
            video.content_type or "video/mp4",
            character_count,
            sample_every_n,
        ),
        daemon=True,
    )
    t.start()
    # Use 200 not 202 — some proxies/clients treat 202 oddly; body has status.
    return jsonify({
        "job_id": job_id,
        "status": "processing",
        "async": True,
        "motion_product": "4.5",
        "message": "Tracking started — poll /api/analyze-motion/status/<job_id>",
    }), 200


def _default_stage_json():
    """World-space 3D stage (green grid floor) — not a flat background composite."""
    return {
        "version": 1,
        "type": "3d_stage",
        "world": {
            "up": [0, 1, 0],
            "floor_y": 0,
            "grid": {"spacing": 1.0, "extent_x": 10, "extent_z": 10, "show_axes": True},
        },
        "camera": {
            "fov_deg": 50,
            "position": [0, 1.6, 5],
            "target": [0, 0, 0],
            "near": 0.1,
            "far": 100,
        },
        "floor_plane": {"normal": [0, 1, 0], "point": [0, 0, 0]},
        "calibration_source": "green_grid",
    }


@app.route("/api/calibrate-stage", methods=["POST", "GET"])
def calibrate_stage():
    """Return stage.json for Three.js world-space grid. Optional job_id loads analyzer stage."""
    job_id = (request.args.get("job_id") or "").strip()
    if request.is_json:
        body = request.get_json(silent=True) or {}
        job_id = job_id or (body.get("job_id") or "").strip()
    if job_id:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", job_id)[:32]
        job = _motion_job_load(job_id)
        stage_url = None
        if job and job.get("status") == "success":
            stage_url = (job.get("result") or {}).get("stage")
        if stage_url:
            if not str(stage_url).startswith("http"):
                stage_url = _motion_output_url(stage_url)
            try:
                r = requests.get(stage_url, timeout=60)
                r.raise_for_status()
                return jsonify(r.json())
            except Exception:
                pass
    return jsonify(_default_stage_json())


@app.route("/api/motion-data/<job_id>")
def motion_data_proxy(job_id):
    """Same-origin motion JSON for stage skeleton (avoids CORS + ephemeral analyzer URLs)."""
    _motion_jobs_cleanup()
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", job_id or "")[:32]
    track = (request.args.get("track") or "1").strip()
    cache_path = _MOTION_JOB_DIR / f"{safe}_motion_{track}.json"
    if cache_path.is_file():
        try:
            return jsonify(json.loads(cache_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    job = _motion_job_load(job_id)
    if not job or job.get("status") != "success":
        return jsonify({"error": "Motion job not ready."}), 404
    result = job.get("result") or {}
    key = "motion_data"
    if track == "2" and result.get("motion_data_2"):
        key = "motion_data_2"
    elif result.get("motion_data_1"):
        key = "motion_data_1" if track != "2" else "motion_data_2"
    url = result.get(key) or result.get("motion_data")
    if not url:
        return jsonify({"error": "No motion data for this job."}), 404
    if not str(url).startswith("http"):
        url = _motion_output_url(url)
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        payload = r.json()
        try:
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": f"Could not load motion JSON: {e}"}), 502


@app.route("/api/analyze-motion/status/<job_id>")
def analyze_motion_status(job_id):
    """Poll async track job (Motion 4.5). Always HTTP 200 with status field."""
    _motion_jobs_cleanup()
    job = _motion_job_load(job_id)
    if not job:
        return jsonify({
            "job_id": job_id,
            "status": "processing",  # brief race after start — client should keep polling
            "motion_product": "4.5",
            "detail": "Job not visible yet — retrying…",
        }), 200
    st = job.get("status") or "processing"
    if st in ("queued", "processing"):
        return jsonify({
            "job_id": job_id,
            "status": "processing",
            "motion_product": "4.5",
        }), 200
    if st == "failed":
        return jsonify({
            "job_id": job_id,
            "status": "failed",
            "detail": job.get("error") or "Motion analysis failed.",
            "motion_product": "4.5",
        }), 200
    # success
    result = dict(job.get("result") or {})
    result["status"] = "success"
    result["motion_product"] = "4.5"
    result["job_id"] = result.get("job_id") or job_id
    result["proxy_job_id"] = job_id
    if result.get("motion_data") or result.get("motion_data_1"):
        result["motion_data_proxy"] = f"/api/motion-data/{job_id}?track=1"
    if result.get("motion_data_2"):
        result["motion_data_2_proxy"] = f"/api/motion-data/{job_id}?track=2"
    return jsonify(result), 200


@app.route("/studios/percfectmotion")
def percfect_motion():
    """Percfect Motion 4.5 — extract · stage map · skeletal layover (no scene presets)."""
    user_data = None
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        res = supabase.table("users").select(
            "picture_credits,video_credits,has_purchased"
        ).eq("id", current_user.id).single().execute()
        user_data = res.data
    return render_template(
        "percfectmotion.html",
        user=user_data,
        video_credits_per_second=VIDEO_CREDITS_PER_SECOND,
        motion_version="4.5",
    )


@app.route("/studios/percfectmotion/generate", methods=["POST"])
@login_required
def motion_generate():
    """Motion studio generate: 1–2 roster characters + preset (or capture-informed) motion.

    Reuses Arena composite + async video job. Better than freeform tools: multi-angle
    roster lock, curated scenarios, green coordinate stage, dual capture assign.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data

    ids = [i.strip() for i in request.form.get("character_ids", "").split(",") if i.strip()]
    action = request.form.get("action", "").strip()
    if len(ids) < 1:
        return jsonify({"error": "Pick at least 1 character from your roster."}), 400
    if len(ids) > 2:
        return jsonify({"error": "Motion supports 1–2 characters (use The Arena for 3)."}), 400

    bg_mode = request.form.get("bg_mode", "preset")
    scene = None
    bg_image = None
    if bg_mode == "preset":
        key = request.form.get("bg_preset", "green_stage") or "green_stage"
        preset = ARENA_BG_BY_KEY.get(key)
        if preset:
            scene = preset.get("scene")
            bg_image = _load_background_image(preset["key"])
        if bg_image is None and key == "green_stage":
            scene = ARENA_BG_BY_KEY.get("green_stage", {}).get("scene") or scene
            bg_image = _load_background_image("green_stage")
    elif bg_mode == "text":
        scene = request.form.get("bg_text", "").strip() or None
    elif bg_mode == "upload":
        f = request.files.get("bg_file")
        if f and f.filename:
            try:
                bg_image = _load_image_any(_file_to_data_uri(f))
            except Exception:
                return jsonify({"error": "Couldn't read that background image."}), 400
    elif bg_mode == "none":
        scene = None
        bg_image = None

    # Capture path: optional freeform motion description (from BYO performance analysis).
    capture_note = (request.form.get("capture_motion_note") or "").strip()
    if action:
        prompt = character_action_prompt(action, scene, char_count=len(ids))
    elif capture_note:
        bg = scene.strip() if scene and scene.strip() else "on a clean background"
        if len(ids) == 1:
            prompt = _ACTION_BASE_SOLO.format(
                action=(
                    f"The character reenacts this performance motion with matching body "
                    f"language and timing: {capture_note[:500]}"
                ),
                bg=bg,
            )
        else:
            prompt = _ACTION_BASE.format(
                action=(
                    f"The characters reenact this dual performance with matching body "
                    f"language and timing: {capture_note[:500]}"
                ),
                bg=bg,
            )
    else:
        return jsonify({"error": "Pick a motion preset or finish custom capture."}), 400

    if not prompt:
        return jsonify({"error": "Could not build motion prompt."}), 400

    # Optional skeletal / mapping metadata for generation log (not charged extra).
    motion_meta = {
        "source": request.form.get("motion_source", "preset"),  # preset | capture
        "job_id": (request.form.get("analysis_job_id") or "").strip() or None,
        "character_count": len(ids),
        "sample_every_n": request.form.get("sample_every_n"),
    }

    try:
        duration = int(request.form.get("duration", 6))
    except (TypeError, ValueError):
        duration = 6
    duration = max(5, min(15, duration))
    cost = video_cost(duration)
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": (
                f"This needs {cost} credits ({duration}s @ {VIDEO_CREDITS_PER_SECOND}/sec) "
                f"— you have {bal}. Buy credits or redeem a coupon code."
            )
        }), 402

    cres = supabase.table("characters").select("*").in_("id", ids).eq(
        "user_id", current_user.id
    ).execute()
    rows = {str(c["id"]): c for c in (cres.data or [])}
    raw_vids = [v.strip() for v in (request.form.get("character_version_ids") or "").split(",")]
    primaries = _primaries_for_ids(rows, ids, raw_vids)
    if len(primaries) != len(ids):
        return jsonify({"error": "One or more characters could not be loaded."}), 400

    # Prefer green coordinate stage for motion when no BG chosen (mapping skill default).
    if bg_image is None and bg_mode == "preset":
        bg_image = _load_background_image("green_stage")

    try:
        composite = (
            composite_on_background(primaries, bg_image)
            if bg_image is not None
            else composite_characters(primaries)
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Enrich prompt with mapping anchors when profiles exist (skeletal-align hints for model).
    try:
        profiles = []
        for i in ids:
            if i not in rows:
                continue
            mp = rows[i].get("motion_profile") or _default_motion_profile()
            if isinstance(mp, dict) and mp.get("anchor"):
                a = mp["anchor"]
                profiles.append(
                    f"char feet_y={a.get('feet_y')}, body_h={a.get('body_height_norm')}"
                )
        if profiles:
            prompt = (
                prompt
                + " Ground feet on the floor plane; keep body proportions stable. "
                + " ".join(profiles[:2])
            )
    except Exception:
        pass

    if motion_meta.get("job_id"):
        prompt += (
            f" Match the extracted performance timing from motion capture job "
            f"{motion_meta['job_id']}."
        )

    payload = {
        "prompt": prompt,
        "composite": _persist_data_uri(composite),
        "duration": duration,
        "cost": cost,
        "is_admin": current_user.is_admin,
        "motion_meta": motion_meta,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "arena", payload)))


@app.route("/studios/percfectmotion/my-motions")
@login_required
def motion_my_motions():
    """Recent video generations for the Motion gallery."""
    try:
        res = (
            supabase.table("generations")
            .select("id,type,prompt,output_url,created_at")
            .eq("user_id", current_user.id)
            .eq("type", "video")
            .order("created_at", desc=True)
            .limit(24)
            .execute()
        )
        return jsonify({"motions": res.data or []})
    except Exception as e:
        return jsonify({"motions": [], "error": str(e)}), 200


def _motion_output_url(path_or_url: str) -> str:
    """Resolve analyzer /outputs/... path to absolute URL."""
    p = (path_or_url or "").strip()
    if not p:
        return ""
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if not p.startswith("/"):
        p = "/" + p
    return f"{MOTION_ANALYZER_URL}{p}"


def _rehost_motion_asset(path_or_url: str, *, kind: str = "bin",
                         cache_path: Path = None) -> str:
    """Download analyzer /outputs asset and rehost on Supabase so overlay survives.

    Analyzer stores files under ephemeral /tmp — Render restarts wipe them, so
    retarget would 404 immediately. Permanent public URL after rehost.
    """
    src = _motion_output_url(path_or_url)
    if not src:
        return ""
    if SUPABASE_URL and src.startswith(f"{SUPABASE_URL}/storage/"):
        return src
    try:
        r = requests.get(src, timeout=180)
        r.raise_for_status()
        data = r.content
        if cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(data)
            except Exception:
                pass
        min_bytes = 1 if (kind == "json" or str(src).endswith(".json")) else 32
        if not data or len(data) < min_bytes:
            return src
        if kind == "json" or src.endswith(".json"):
            ext, ctype, folder = "json", "application/json", "motion_json"
        elif kind == "video" or src.endswith((".mp4", ".webm", ".mov")):
            ext, ctype, folder = "mp4", "video/mp4", "motion_vid"
        else:
            ext, ctype, folder = "bin", "application/octet-stream", "motion_bin"
        path = f"{folder}/{uuid.uuid4().hex}.{ext}"
        supabase.storage.from_("previews").upload(
            path, data,
            file_options={"content-type": ctype, "upsert": "true"},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/previews/{path}"
    except Exception as e:
        app.logger.warning("motion rehost failed %s: %s", src[:120], e)
        return src


def _rehost_motion_result(body: dict, *, job_id: str = "") -> dict:
    """Rewrite analyzer result paths to durable Supabase URLs."""
    if not isinstance(body, dict):
        return body
    out = dict(body)
    video_keys = (
        "background_video", "character_video",
        "character_1_video", "character_2_video",
        "skeleton_overlay",
    )
    json_keys = (
        "motion_data", "motion_data_1", "motion_data_2", "metadata",
        "stage", "perimeter_track",
    )
    for k in video_keys:
        if out.get(k):
            out[k] = _rehost_motion_asset(out[k], kind="video")
    track_cache = {"motion_data": "1", "motion_data_1": "1", "motion_data_2": "2"}
    for k in json_keys:
        if out.get(k):
            cache = None
            if job_id and k in track_cache:
                safe = re.sub(r"[^a-zA-Z0-9_-]", "", job_id)[:32]
                cache = _MOTION_JOB_DIR / f"{safe}_motion_{track_cache[k]}.json"
            out[k] = _rehost_motion_asset(out[k], kind="json", cache_path=cache)
    # Absolute URLs so the browser / retarget never depend on analyzer host
    for k in list(out.keys()):
        if (
            k.endswith("_video")
            or k.startswith("motion_data")
            or k in ("metadata", "skeleton_overlay", "stage", "perimeter_track")
        ):
            if out.get(k) and not str(out[k]).startswith("http"):
                out[k] = _motion_output_url(out[k])
    return out


@app.route("/studios/percfectmotion/retarget", methods=["POST"])
@login_required
def motion_retarget():
    """Plug roster character(s) into an analyzed performance — they mimic the upload.

    CPU retarget: background plate + motion_data landmarks + keyed roster cutouts.
    No cloud video model, no GPU. Async job.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data

    raw_ids = [i.strip() for i in request.form.get("character_ids", "").split(",") if i.strip()]
    if len(raw_ids) < 1:
        return jsonify({"error": "Pick at least 1 roster character to plug into the video."}), 400
    if len(raw_ids) > 2:
        return jsonify({"error": "Retarget supports 1–2 characters."}), 400

    # Coerce numeric ids (Postgres int) while keeping UUID strings intact
    ids = []
    for i in raw_ids:
        try:
            ids.append(int(i))
        except (TypeError, ValueError):
            ids.append(i)

    bg_path = (request.form.get("background_video") or "").strip()
    md1 = (request.form.get("motion_data") or request.form.get("motion_data_1") or "").strip()
    md2 = (request.form.get("motion_data_2") or "").strip()
    if not bg_path or not md1:
        return jsonify({
            "error": "Missing analysis outputs. Upload a video and wait for capture to finish first.",
        }), 400

    dual = len(ids) == 2
    if dual and not md2:
        # Soft: allow single-track overlay with first character only
        dual = False
        ids = ids[:1]

    try:
        duration_sec = float(request.form.get("duration_sec") or 6)
    except (TypeError, ValueError):
        duration_sec = 6.0
    duration_sec = max(1.0, min(45.0, duration_sec))

    from motion_retarget import estimate_retarget_credits
    cost = estimate_retarget_credits(duration_sec, VIDEO_CREDITS_PER_SECOND)
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": (
                f"Retarget needs {cost} credits for this clip — you have {bal}. "
                "Buy credits or redeem a coupon."
            ),
            "needed": cost,
            "have": bal,
        }), 402

    if dual and len({str(x) for x in ids}) < 2:
        return jsonify({"error": "Pick two different roster characters for dual overlay."}), 400

    cres = supabase.table("characters").select("*").in_("id", ids).eq(
        "user_id", current_user.id
    ).execute()
    rows = {str(c["id"]): c for c in (cres.data or [])}
    raw_vids = [v.strip() for v in (request.form.get("character_version_ids") or "").split(",")]
    while len(raw_vids) < len(ids):
        raw_vids.append("")
    char_payload = []
    for idx, i in enumerate(ids):
        c = rows.get(str(i))
        if not c:
            return jsonify({
                "error": f"Could not load character id={i} from your roster. Re-pick from Library.",
            }), 400
        look = _resolve_character_version(c, raw_vids[idx] or None)
        primary = look.get("primary_image_url")
        if not primary:
            return jsonify({
                "error": f"Could not load character id={i} from your roster. Re-pick from Library.",
            }), 400
        char_payload.append({
            "id": c["id"],
            "name": c.get("name"),
            "primary_image_url": primary,
            "images": look.get("images") or [primary],
            "version_id": look.get("id") or "v1",
            "motion_profile": c.get("motion_profile") or _default_motion_profile(),
        })

    # Prefer absolute durable URLs (already rehosted after extract when possible)
    bg_url = bg_path if bg_path.startswith("http") else _motion_output_url(bg_path)
    md1_url = md1 if md1.startswith("http") else _motion_output_url(md1)
    md2_url = None
    if dual and md2:
        md2_url = md2 if md2.startswith("http") else _motion_output_url(md2)

    payload = {
        "characters": char_payload,
        "background_video": bg_url,
        "motion_data": md1_url,
        "motion_data_2": md2_url,
        "duration_sec": duration_sec,
        "fps": request.form.get("fps") or None,
        "analysis_job_id": (request.form.get("analysis_job_id") or "").strip() or None,
        "cost": cost,
        "is_admin": current_user.is_admin,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "motion_retarget", payload)))


@app.route("/studios/percfectmotion/build-character-preview", methods=["POST"])
@login_required
def motion_build_character_preview():
    """Step 1: first front photo only · 1 credit. User reviews before the 50-credit pack."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}
    bal = credit_balance(u)
    if not current_user.is_admin and bal < 1:
        return jsonify({
            "error": f"First photo needs 1 credit — you have {bal}.",
            "needed": 1,
            "have": bal,
        }), 402

    char_video = (request.form.get("character_video") or "").strip()
    if not char_video:
        return jsonify({"error": "Missing character extract video."}), 400
    name = (request.form.get("name") or "Motion Character").strip()[:80]
    gender = (request.form.get("gender") or "").strip()

    # Prefer durable URL if already absolute (rehosted extract)
    cv = char_video if char_video.startswith("http") else _motion_output_url(char_video)
    payload = {
        "character_video": cv,
        "name": name,
        "gender": gender,
        "is_admin": current_user.is_admin,
    }
    return jsonify(async_payload(
        enqueue(studio_jobs, current_user.id, "motion_build_character_preview", payload)
    ))


@app.route("/studios/percfectmotion/build-character", methods=["POST"])
@login_required
def motion_build_character():
    """Step 2: approved front → sides + back + 360 · CHARACTER_PACK_CREDIT_COST credits.

    Only call after user liked the preview photo — avoids wasting 50 credits on bad fronts.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}
    pack_cost = CHARACTER_PACK_CREDIT_COST
    bal = credit_balance(u)
    if not current_user.is_admin and bal < pack_cost:
        return jsonify({
            "error": (
                f"Full pack (sides + back + 360) needs {pack_cost} credits — you have {bal}. "
                "Buy credits or redeem a coupon code."
            ),
            "needed": pack_cost,
            "have": bal,
        }), 402

    primary = (request.form.get("primary_image_url") or request.form.get("url") or "").strip()
    if not primary:
        return jsonify({
            "error": "Approve a first photo first (generate preview, then Approve pack).",
        }), 400
    name = (request.form.get("name") or "Motion Character").strip()[:80]
    gender = (request.form.get("gender") or "").strip()
    prompt = (request.form.get("prompt") or "").strip()
    seed_url = (request.form.get("seed_url") or "").strip()
    seed_urls_raw = (request.form.get("seed_urls") or "").strip()
    seed_urls = [s for s in seed_urls_raw.split(",") if s.strip()] if seed_urls_raw else []

    payload = {
        "primary_image_url": primary,
        "prompt": prompt,
        "name": name,
        "gender": gender,
        "seed_url": seed_url,
        "seed_urls": seed_urls,
        "is_admin": current_user.is_admin,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "motion_build_character", payload)))


@app.route("/studios/percfectmotion/save-background", methods=["POST"])
@login_required
def motion_save_background():
    """Background plate → Studio photo fill-in-the-blanks → library Backgrounds + Arena.

    1 credit. Result is tagged for /api/my-library Backgrounds and Arena drag-drop.
    """
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}
    if not current_user.is_admin and credit_balance(u) < 1:
        return jsonify({
            "error": "Filling a background needs 1 credit.",
            "needed": 1,
            "have": credit_balance(u),
        }), 402

    bg_video = (request.form.get("background_video") or "").strip()
    if not bg_video:
        return jsonify({"error": "Missing background extract video."}), 400

    payload = {
        "background_video": _motion_output_url(bg_video),
        "is_admin": current_user.is_admin,
        "label": (request.form.get("label") or "Motion scene").strip()[:80],
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "motion_save_background", payload)))


STREETS_USER_AGENT = (
    "PercfectAI-GlobeSelect/1.0 (https://percfectai.com; support@percfectproposal.com)"
)
STREETS_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
STREETS_CAPTURE_WIDTH = 1280
STREETS_CAPTURE_HEIGHT = 720
STREETS_MIN_IMAGE_BYTES = 8000
STREETS_PREVIEW_WIDTH = 960
STREETS_PREVIEW_HEIGHT = 540
STREETS_PREVIEW_MIN_BYTES = 2500
_streets_chromium_ready = False


def _ensure_streets_chromium():
    """Install/locate Chromium on Render if the Docker layer was missed."""
    global _streets_chromium_ready
    if _streets_chromium_ready:
        return

    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if browsers_path and browsers_path != "0":
        root = Path(browsers_path)
        if root.exists() and any(root.glob("chromium-*/chrome-linux/chrome")):
            _streets_chromium_ready = True
            return

    import subprocess
    import sys

    if not browsers_path:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    try:
        from playwright._impl._driver import compute_driver_executable

        driver = compute_driver_executable()
        subprocess.run(
            [sys.executable, driver, "install", "chromium"],
            check=False,
            capture_output=True,
            timeout=180,
        )
    except Exception:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            timeout=180,
        )
    _streets_chromium_ready = True


def _streets_parse_view(data: dict):
    mode = (data.get("mode") or "streetview").strip().lower()
    if mode not in ("streetview", "street", "pano", ""):
        return None, ("Only Street View is allowed — no map or satellite.", 400)
    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (TypeError, ValueError):
        return None, ("Invalid map coordinates.", 400)
    heading = max(0, min(360, float(data.get("heading", 34))))
    pitch = max(-90, min(90, float(data.get("pitch", 10))))
    fov = max(10, min(120, float(data.get("fov", 90))))
    pano = (data.get("pano") or "").strip() or None
    return {
        "lat": lat,
        "lng": lng,
        "heading": heading,
        "pitch": pitch,
        "fov": fov,
        "pano": pano,
    }, None


def _streets_static_capture(data: dict, *, preview: bool = False):
    """Street View Static API — same pose as Maps JS iframe (second API key)."""
    if not GOOGLE_MAPS_SNAP_KEY:
        return None, None

    view, err = _streets_parse_view(data)
    if err:
        return None, err

    w = STREETS_PREVIEW_WIDTH if preview else STREETS_CAPTURE_WIDTH
    h = STREETS_PREVIEW_HEIGHT if preview else STREETS_CAPTURE_HEIGHT
    min_bytes = STREETS_PREVIEW_MIN_BYTES if preview else STREETS_MIN_IMAGE_BYTES
    params = {
        "size": f"{w}x{h}",
        "heading": view["heading"],
        "pitch": view["pitch"],
        "fov": view["fov"],
        "source": "outdoor",
        "key": GOOGLE_MAPS_SNAP_KEY,
    }
    if view["pano"]:
        params["pano"] = view["pano"]
    else:
        params["location"] = f"{view['lat']},{view['lng']}"

    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/streetview",
            params=params,
            timeout=45,
        )
    except requests.exceptions.RequestException:
        return None, ("Could not reach Google Street View Static API.", 502)

    if resp.status_code != 200 or not resp.content:
        return None, (
            "Snap demo key failed — enable Street View Static API on GOOGLE_MAPS_SNAP_DEMO_KEY.",
            400,
        )
    if len(resp.content) < min_bytes:
        return None, (
            "No Street View here — drag pegman to a blue street or try another spot.",
            400,
        )
    return resp.content, None


def _streets_capture(data: dict, *, preview: bool = False):
    """Demo key 2 — Street View Static API, same pose as iframe panorama."""
    image_bytes, err = _streets_static_capture(data, preview=preview)
    if image_bytes:
        return image_bytes, None
    if err:
        return None, err
    return None, (
        "Add GOOGLE_MAPS_SNAP_DEMO_KEY on Render (Street View Static API demo key).",
        503,
    )


def _streets_streetview_url(lat: float, lng: float, heading: float, pitch: float, fov: float) -> str:
    params = urllib.parse.urlencode({
        "api": "1",
        "map_action": "pano",
        "viewpoint": f"{lat},{lng}",
        "heading": heading,
        "pitch": pitch,
        "fov": fov,
    })
    return f"https://www.google.com/maps/@?{params}"


def _page_is_streetview(page) -> bool:
    """True only when Playwright landed on a panorama, not map/satellite."""
    url = (page.url or "").lower()
    if "map_action=pano" in url:
        return True
    if re.search(r"3a,\d+y", url) or "1e3" in url or "!1e1" in url or "!2e10" in url:
        return True
    try:
        if page.locator("canvas.widget-scene-canvas, #scene canvas, .widget-scene, canvas").count() > 0:
            return True
    except Exception:
        pass
    return False


def _streets_playwright_capture(data: dict, *, preview: bool = False):
    """Playwright fallback when GOOGLE_MAPS_SNAP_KEY is not configured."""
    view, err = _streets_parse_view(data)
    if err:
        return None, err
    lat, lng = view["lat"], view["lng"]
    heading, pitch, fov = view["heading"], view["pitch"], view["fov"]
    url = _streets_streetview_url(lat, lng, heading, pitch, fov)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, ("Playwright is not available on the server.", 503)

    _ensure_streets_chromium()
    cap_w = STREETS_PREVIEW_WIDTH if preview else STREETS_CAPTURE_WIDTH
    cap_h = STREETS_PREVIEW_HEIGHT if preview else STREETS_CAPTURE_HEIGHT
    min_bytes = STREETS_PREVIEW_MIN_BYTES if preview else STREETS_MIN_IMAGE_BYTES
    jpeg_q = 78 if preview else 88
    wait_ms = 5500 if preview else 7000

    last_err = ("Could not capture Street View — try again.", 500)
    for attempt in range(2):
        browser = None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": cap_w, "height": cap_h},
                    user_agent=STREETS_BROWSER_UA,
                    locale="en-US",
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(wait_ms if attempt == 0 else wait_ms + 4000)
                if not _page_is_streetview(page):
                    last_err = (
                        "Street View only — no coverage at this spot. "
                        "Search a city street or famous landmark.",
                        400,
                    )
                    browser.close()
                    continue
                page.evaluate("""() => {
                    document.querySelectorAll(
                        'header, [role="banner"], .scene-footer, #minimap, .app-viewcard-strip'
                    ).forEach(el => { el.style.visibility = 'hidden'; });
                }""")
                page.wait_for_timeout(400)
                image_bytes = page.screenshot(type="jpeg", quality=jpeg_q)
                browser.close()
                browser = None
                if image_bytes and len(image_bytes) >= min_bytes:
                    return image_bytes, None
                last_err = (
                    "No Street View here — search a city street or famous landmark.",
                    400,
                )
        except Exception as exc:
            app.logger.exception("Street View capture failed: %s", exc)
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            last_err = ("Could not capture Street View — try again.", 500)
    return None, last_err


def _streets_capture_via_worker(data: dict, *, preview: bool = False):
    """Run Playwright in a child process so gunicorn does not fight the browser."""
    import subprocess
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        json.dump(data, tmp)
        payload_path = tmp.name
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "scripts" / "street_capture_worker.py")]
    if preview:
        cmd.append("--preview")
    cmd.append(payload_path)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        raw = (proc.stdout or "").strip()
        if not raw:
            app.logger.error("Street worker empty output stderr=%s", proc.stderr[:500])
            return None, ("Could not capture Street View — try again.", 500)
        result = json.loads(raw)
        if result.get("error"):
            return None, (result["error"], int(result.get("status", 500)))
        image_b64 = result.get("image_b64")
        if not image_b64:
            return None, ("Could not capture Street View — try again.", 500)
        return base64.b64decode(image_b64), None
    except subprocess.TimeoutExpired:
        return None, ("Street View capture timed out — try again.", 504)
    except Exception as exc:
        app.logger.exception("Street worker failed: %s", exc)
        return None, ("Could not capture Street View — try again.", 500)
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass


@app.route("/studios/percfect-globe-snap")
@app.route("/studios/percfect-globe-snap/<path:_unused>")
def percfect_globe_snap_hidden(_unused=None):
    """Globe Snap hidden — kept in repo only; not linked anywhere."""
    abort(404)


@app.route("/studios/take-it-to-the-streets")
@app.route("/studios/take-it-to-the-streets/<path:_unused>")
def take_it_to_the_streets_redirect(_unused=None):
    """Retired — Globe Select lives on The Arena."""
    return redirect(url_for("percfect_arena"))


@app.route("/studios/percfectcharacter/arena/street-picker")
def arena_street_picker():
    """Google Maps JS iframe picker; snap uses GOOGLE_MAPS_SNAP_KEY (Static API)."""
    return render_template(
        "arena_street_picker.html",
        maps_iframe_key=GOOGLE_MAPS_IFRAME_KEY,
        maps_configured=bool(GOOGLE_MAPS_IFRAME_KEY),
        snap_configured=bool(GOOGLE_MAPS_SNAP_KEY),
    )


@app.route("/studios/percfectcharacter/arena/street-search")
def arena_street_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 6},
            headers={"User-Agent": STREETS_USER_AGENT},
            timeout=12,
        )
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.RequestException:
        return jsonify({"error": "Place search unavailable — try again."}), 502


@app.route("/studios/percfectcharacter/arena/street-preview")
def arena_street_preview():
    """Server-rendered Street View preview (Google blocks iframe embed)."""
    data = {
        "lat": request.args.get("lat"),
        "lng": request.args.get("lng"),
        "heading": request.args.get("heading", 34),
        "pitch": request.args.get("pitch", 10),
        "fov": request.args.get("fov", 90),
        "mode": "streetview",
    }
    image_bytes, err = _streets_capture(data, preview=True)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return Response(image_bytes, mimetype="image/jpeg")


@app.route("/studios/percfectcharacter/arena/street-capture", methods=["POST"])
def arena_street_capture():
    data = request.get_json(silent=True) or {}
    image_bytes, err = _streets_capture(data, preview=False)
    if err:
        return jsonify({"error": err[0]}), err[1]
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return jsonify({
        "image": f"data:image/jpeg;base64,{b64}",
        "filename": "globe-select.jpg",
    })


@app.route("/studios/percfectcharacter/arena/generate", methods=["POST"])
@login_required
def arena_generate():
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select("picture_credits,video_credits,videos_today").eq("id", current_user.id).single().execute()
    user_data = res.data

    ids = [i.strip() for i in request.form.get("character_ids", "").split(",") if i.strip()]
    action = request.form.get("action", "")
    if len(ids) < 2:
        return jsonify({"error": "Pick at least 2 characters."}), 400
    if len(ids) > 3:
        return jsonify({"error": "The Arena supports up to 3 characters."}), 400

    bg_mode = request.form.get("bg_mode", "none")
    scene = None
    bg_image = None
    if bg_mode == "preset":
        preset = ARENA_BG_BY_KEY.get(request.form.get("bg_preset", ""))
        if preset:
            scene = preset.get("scene")
            bg_image = _load_background_image(preset["key"])
    elif bg_mode == "text":
        scene = request.form.get("bg_text", "").strip() or None
    elif bg_mode == "upload":
        f = request.files.get("bg_file")
        if f and f.filename:
            try:
                bg_image = _load_image_any(_file_to_data_uri(f))
            except Exception:
                return jsonify({"error": "Couldn't read that background image."}), 400

    custom_action = (request.form.get("custom_action") or request.form.get("custom_prompt") or "").strip()
    if not action and custom_action:
        action = "custom"
    if not action:
        return jsonify({"error": "Pick an interaction or write a custom one."}), 400
    if (action or "").strip().lower() == "custom":
        if len(custom_action) < 8:
            return jsonify({"error": "Describe your custom interaction (a short sentence is enough)."}), 400
        if len(custom_action) > 500:
            custom_action = custom_action[:500]

    try:
        duration = int(request.form.get("duration", 6))
    except (TypeError, ValueError):
        duration = 6
    duration = max(5, min(15, duration))
    adult_surcharge = arena_adult_surcharge(action)
    cost = video_cost(duration) + adult_surcharge
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < cost:
        err_extra = f" (+{adult_surcharge})" if adult_surcharge else ""
        return jsonify({
            "error": f"This needs {cost} credits ({duration}s @ {VIDEO_CREDITS_PER_SECOND}/sec{err_extra}) — "
                     f"you have {bal}. Buy credits or redeem a coupon code.",
        }), 402

    cres = supabase.table("characters").select("*").in_("id", ids).eq("user_id", current_user.id).execute()
    rows = {str(c["id"]): c for c in (cres.data or [])}
    prompt, picked_action = arena_action_prompt(
        action, scene, rows=rows, ids=ids, custom_action=custom_action,
    )
    if not prompt:
        return jsonify({"error": "Pick an interaction or write a custom one."}), 400
    # Optional extra direction on top of a preset (not used for full custom)
    if (action or "").strip().lower() != "custom":
        extra = (request.form.get("custom_prompt") or "").strip()
        if extra and extra != custom_action:
            prompt = f"{prompt} Additional direction: {extra[:300]}"

    raw_vids = [v.strip() for v in (request.form.get("character_version_ids") or "").split(",")]
    primaries = _primaries_for_ids(rows, ids, raw_vids)
    if len(primaries) != len(ids):
        return jsonify({"error": "One or more characters could not be loaded."}), 400

    try:
        composite = composite_on_background(primaries, bg_image) if bg_image is not None \
            else composite_characters(primaries)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    payload = {
        "prompt": prompt,
        "composite": _persist_data_uri(composite),
        "duration": duration,
        "cost": cost,
        "is_admin": current_user.is_admin,
    }
    if is_lewd_random_action(action):
        payload["lewd_pick"] = picked_action
    job_id = enqueue(studio_jobs, current_user.id, "arena", payload)
    resp = async_payload(job_id)
    if is_lewd_random_action(action):
        resp["lewd_pick"] = picked_action
    return jsonify(resp)




@app.route("/percfectstudios/princess-batch", methods=["POST"])
@login_required
def princess_batch():
    """Legacy alias — same as perchance-generate (Playwright removed)."""
    return perchance_generate()


# ── Princess studio APIs ──────────────────────────────────

@app.route("/percfectstudios/princess-queue", methods=["POST"])
@login_required
def princess_queue():
    """Queue a Mac bot job: select princess → 18+ → Generate → blurred upload."""
    blocked = _princess_disabled_response()
    if blocked:
        return blocked
    princess_raw = (request.form.get("princess") or "").strip()
    princess_key = normalize_princess_key(princess_raw) if princess_raw else "Jasmine"
    count = min(10, max(1, int(request.form.get("count") or PRINCESS_DEFAULT_COUNT)))
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "user_id": current_user.id,
        "princess": princess_key,
        "count": count,
        "status": "pending",
        "results": [],
        "error": None,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    try:
        _save_princess_job(job)
    except Exception as e:
        return jsonify({"error": f"Could not queue job: {e}"}), 500
    return jsonify({"job_id": job_id, "status": "pending", "count": count, "princess": princess_key})


@app.route("/percfectstudios/princess-queue/<job_id>", methods=["GET"])
@login_required
def princess_queue_status(job_id: str):
    job = _load_princess_job(job_id)
    if not job or job.get("user_id") != current_user.id:
        return jsonify({"error": "Job not found."}), 404
    results = _job_results_for_user(int(job["user_id"]), job.get("created_at", ""))
    status = "pending"
    if _job_marker_exists(job_id, "done"):
        status = "done"
    elif _job_marker_exists(job_id, "failed"):
        status = "failed"
    elif _job_marker_exists(job_id, "claimed"):
        status = "processing"
    job = {**job, "status": status, "results": results}
    if status == "done" or len(results) >= int(job.get("count") or 1):
        job["status"] = "done"
    return jsonify(job)


@app.route("/percfectstudios/bot/job-next", methods=["GET"])
def bot_job_next():
    if not _bot_secret_ok():
        return jsonify({"error": "Forbidden."}), 403
    try:
        for job in _list_princess_jobs():
            job_id = job.get("id")
            if not job_id or job.get("status") != "pending":
                continue
            results = _job_results_for_user(int(job["user_id"]), job.get("created_at", ""))
            if len(results) >= int(job.get("count") or 1):
                continue
            job["status"] = "processing"
            return jsonify({"job": job})
        return jsonify({"job": None})
    except Exception as e:
        app.logger.exception("bot_job_next failed")
        return jsonify({"job": None})


@app.route("/percfectstudios/bot/job-upload", methods=["POST"])
def bot_job_upload():
    if not _bot_secret_ok():
        return jsonify({"error": "Forbidden."}), 403
    job_id = (request.form.get("job_id") or "").strip()
    job = _load_princess_job(job_id) if job_id else None
    if not job:
        return jsonify({"error": "Job not found."}), 404
    image_data = (request.form.get("image_data") or "").strip()
    if not image_data.startswith("data:"):
        return jsonify({"error": "image_data required."}), 400
    _header, _comma, b64 = image_data.partition(",")
    image_bytes = base64.b64decode(b64)
    princess = job.get("princess") or "Princess"
    stored = _perchance_store_generation_for_user(
        int(job["user_id"]),
        f"Percfect Princess — {princess}",
        image_bytes,
    )
    return jsonify(stored)


@app.route("/percfectstudios/bot/job-done", methods=["POST"])
def bot_job_done():
    if not _bot_secret_ok():
        return jsonify({"error": "Forbidden."}), 403
    data = request.get_json(silent=True) or {}
    job_id = (data.get("job_id") or request.form.get("job_id") or "").strip()
    job = _load_princess_job(job_id) if job_id else None
    if not job:
        return jsonify({"error": "Job not found."}), 404
    status = data.get("status") or request.form.get("status") or "done"
    try:
        marker = "done" if status == "done" else "failed"
        _write_job_marker(job_id, marker, {
            "id": job_id,
            "status": status,
            "error": data.get("error"),
            "finished_at": datetime.datetime.utcnow().isoformat(),
        })
    except Exception:
        pass
    return jsonify({"ok": True, "job_id": job_id, "status": status})


@app.route("/percfectstudios/percper-generate", methods=["POST"])
@login_required
def percper_generate():
    return perchance_generate()


@app.route("/percfectstudios/perchance-generate", methods=["POST"])
@login_required
def perchance_generate():
    """Princess image batch — blurred previews hosted on site; unlock costs credits."""
    blocked = _princess_disabled_response()
    if blocked:
        return blocked
    princess_raw = (request.form.get("princess") or "").strip()
    princess_key = normalize_princess_key(princess_raw) if princess_raw else ""
    prompt = (request.form.get("prompt") or "").strip()

    try:
        if princess_raw:
            count = min(10, max(1, int(request.form.get("count") or PRINCESS_DEFAULT_COUNT)))
            prompts = build_princess_prompts(princess_key, count)
        else:
            if not prompt:
                return jsonify({"error": "Prompt is required."}), 400
            ratio = (request.form.get("ratio") or "1024x1024").lower().replace(" ", "")
            if "x" in ratio:
                w_s, h_s = ratio.split("x", 1)
                width, height = int(w_s), int(h_s)
            else:
                width, height = 1024, 1024
            count = min(4, max(1, int(request.form.get("count") or 1)))
            prompts = [prompt] * count
            neg = ""

        results = []
        errors = []
        downloaded: list[tuple[str, bytes]] = []

        for idx, item_prompt in enumerate(prompts):
            try:
                if princess_raw:
                    image_bytes = _generate_princess_backend(item_prompt)
                else:
                    image_bytes = _generate_perchance(item_prompt, width, height, neg)
                downloaded.append((item_prompt, image_bytes))
            except Exception as item_err:
                errors.append(_user_facing_gen_error(str(item_err)))

        for item_prompt, image_bytes in downloaded:
            try:
                results.append(_perchance_store_generation(item_prompt, image_bytes))
            except Exception as item_err:
                errors.append(_user_facing_gen_error(str(item_err)))

        if not results:
            msg = errors[0] if errors else "Generation failed."
            return jsonify({"error": _user_facing_gen_error(msg)}), 500

        payload = {
            "results": results,
            "source": "princess" if princess_raw else "custom",
        }
        if princess_raw:
            payload["princess"] = princess_key
            if len(results) < count:
                payload["partial"] = True
        if len(results) == 1:
            payload["preview_url"] = results[0]["preview_url"]
            payload["generation_id"] = results[0]["generation_id"]
        if errors:
            payload["partial_errors"] = errors
        return jsonify(payload)

    except Exception as e:
        return jsonify({"error": _user_facing_gen_error(str(e))}), 500


@app.route("/percfectstudios/preview-capture", methods=["POST"])
@login_required
def preview_capture():
    """Download a studio image and store blurred preview for paywall."""
    blocked = _princess_disabled_response()
    if blocked:
        return blocked
    image_url = (request.form.get("image_url") or "").strip()
    image_data = (request.form.get("image_data") or "").strip()

    try:
        if image_data.startswith("data:"):
            _header, _comma, b64 = image_data.partition(",")
            image_bytes = base64.b64decode(b64)
        elif image_url:
            if not _is_allowed_perchance_image_url(image_url):
                return jsonify({"error": "Invalid image source."}), 400
            resp = requests.get(image_url, timeout=120, headers={"User-Agent": "PercfectStudios/1.0"})
            if not resp.ok:
                return jsonify({"error": f"Could not fetch image ({resp.status_code})."}), 502
            content_type = (resp.headers.get("content-type") or "").lower()
            if "image" not in content_type and not image_url.lower().split("?")[0].endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                return jsonify({"error": "URL did not return an image."}), 400
            image_bytes = resp.content
        else:
            return jsonify({"error": "image_url required."}), 400

        prompt = "Percfect Princess Studio"
        result = _perchance_store_generation(prompt, image_bytes, source_url=image_url)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/percfectstudios/perchance-capture", methods=["POST"])
@login_required
def perchance_capture_alias():
    """Legacy alias — same as preview-capture."""
    return preview_capture()


@app.route("/percfectstudios/my-previews")
@login_required
def my_previews():
    """Recent hosted perchance previews for the logged-in user."""
    blocked = _princess_disabled_response()
    if blocked:
        return blocked
    try:
        res = supabase.table("generations").select("id, preview_url, unlocked, created_at")\
            .eq("user_id", current_user.id)\
            .eq("source", "perchance")\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
        return jsonify({"previews": res.data or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/percfectstudios/preview-unlock", methods=["POST"])
@login_required
def preview_unlock():
    """Charge 1 picture credit and return a signed download URL for the original."""
    blocked = _princess_disabled_response()
    if blocked:
        return blocked
    gen_id = (request.form.get("generation_id") or "").strip()
    if not gen_id:
        return jsonify({"error": "generation_id required."}), 400

    res = supabase.table("generations").select("*")\
        .eq("id", gen_id).eq("user_id", current_user.id)\
        .eq("source", "perchance").maybe_single().execute()
    gen = res.data
    if not gen:
        return jsonify({"error": "Generation not found."}), 404

    if gen.get("unlocked"):
        return jsonify({"url": _rehost_download_url(int(gen_id))})

    credits_res = supabase.table("users").select("picture_credits")\
        .eq("id", current_user.id).single().execute()
    credits = (credits_res.data or {}).get("picture_credits", 0)
    if not current_user.is_admin and credits < 1:
        return jsonify({"error": "You need 1 image credit to unlock this."}), 402

    if not current_user.is_admin:
        supabase.table("users").update({"picture_credits": credits - 1})\
            .eq("id", current_user.id).execute()

    supabase.table("generations").update({"unlocked": True})\
        .eq("id", gen_id).execute()

    return jsonify({"url": _rehost_download_url(int(gen_id))})


@app.route("/percfectstudios/perchance-unlock", methods=["POST"])
@login_required
def perchance_unlock_alias():
    """Legacy alias — same as preview-unlock."""
    return preview_unlock()


@app.route("/percfectstudios/preview-download-zip", methods=["POST"])
@login_required
def preview_download_zip():
    """Zip unlocked originals for private-page batch download."""
    import zipfile

    blocked = _princess_disabled_response()
    if blocked:
        return blocked

    raw_ids = (request.form.get("generation_ids") or "").strip()
    if not raw_ids:
        return jsonify({"error": "No images selected."}), 400

    id_list = [int(p) for p in raw_ids.replace(" ", "").split(",") if p.isdigit()]
    if not id_list:
        return jsonify({"error": "No valid image IDs."}), 400

    rows = []
    locked = []
    for gen_id in id_list:
        res = supabase.table("generations").select("*")\
            .eq("id", gen_id).eq("user_id", current_user.id)\
            .eq("source", "perchance").maybe_single().execute()
        gen = res.data
        if not gen:
            continue
        if not gen.get("unlocked") and not current_user.is_admin:
            locked.append(gen_id)
            continue
        rows.append(gen)

    if locked:
        return jsonify({"error": f"Unlock {len(locked)} selected image(s) first (1 credit each)."}), 402
    if not rows:
        return jsonify({"error": "No unlocked images to download."}), 404

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, gen in enumerate(rows, 1):
            path = gen.get("output_url") or ""
            if not path:
                continue
            try:
                data = supabase.storage.from_("originals").download(path)
                zf.writestr(f"princess_{i}.jpg", data)
            except Exception:
                pass
    if not buf.tell():
        return jsonify({"error": "Could not build zip."}), 500

    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": 'attachment; filename="percfect-princess.zip"'},
    )





# ── Community chatroom ────────────────────────────────────
import re as _re

CHAT_RATE_MAX = 5          # max messages per window
CHAT_RATE_WINDOW = 10      # seconds
CHAT_AUTO_HIDE_REPORTS = 3 # hide a message once this many distinct users report it
_CHAT_URL_RE = _re.compile(r"(https?://|www\.)\S+", _re.IGNORECASE)
# Minimal slur/garbage screen — extend as needed.
CHAT_BANNED_WORDS = {"nigger", "faggot", "retard", "kike", "spic", "chink", "tranny"}


def _chat_clean(body: str):
    """Scrub links and screen banned words. Returns (clean_text, error)."""
    text = (body or "").strip()[:500]
    if not text:
        return None, "Empty message."
    low = text.lower()
    if any(w in low for w in CHAT_BANNED_WORDS):
        return None, "Your message was blocked for inappropriate language."
    text = _CHAT_URL_RE.sub("[link removed]", text)
    return text, None


def _chat_rate_limited(user_id) -> bool:
    try:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(seconds=CHAT_RATE_WINDOW)).isoformat()
        res = supabase.table("chat_messages").select("id", count="exact").eq(
            "user_id", user_id).gte("created_at", cutoff).execute()
        return (res.count or 0) >= CHAT_RATE_MAX
    except Exception:
        return False


@app.route("/studios/chatroom")
def chatroom():
    user_data = None
    if current_user.is_authenticated:
        reset_daily_if_needed(current_user.id)
        res = supabase.table("users").select("picture_credits,video_credits").eq("id", current_user.id).single().execute()
        user_data = res.data
    return render_template("chatroom.html", user=user_data,
                           is_admin=bool(current_user.is_authenticated and current_user.is_admin))


@app.route("/studios/chatroom/messages")
def chatroom_messages():
    """Poll endpoint. ?after=<id> returns only newer messages."""
    try:
        res = supabase.table("chat_messages").select(
            "id,username,body,type,media_url,created_at"
        ).eq("hidden", False).order("id", desc=True).limit(60).execute()
        msgs = list(reversed(res.data or []))
        after = request.args.get("after")
        if after:
            try:
                aid = int(after)
                msgs = [m for m in msgs if m["id"] > aid]
            except ValueError:
                pass
        return jsonify(msgs)
    except Exception:
        return jsonify([])


@app.route("/studios/chatroom/send", methods=["POST"])
@login_required
def chatroom_send():
    body, err = _chat_clean(request.form.get("body", ""))
    if err:
        return jsonify({"error": err}), 400
    if not current_user.is_admin and _chat_rate_limited(current_user.id):
        return jsonify({"error": "You're sending messages too fast — slow down a moment."}), 429
    try:
        row = supabase.table("chat_messages").insert({
            "user_id": current_user.id, "username": current_user.username,
            "body": body, "type": "text",
        }).execute()
        return jsonify(row.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/studios/chatroom/fight", methods=["POST"])
@login_required
def chatroom_fight():
    """Generate a fight clip between 2 of the user's characters and post it to the room."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,videos_today"
    ).eq("id", current_user.id).single().execute()
    u = res.data or {}

    ids = [i.strip() for i in request.form.get("character_ids", "").split(",") if i.strip()]
    if len(ids) != 2:
        return jsonify({"error": "Pick exactly 2 characters to fight."}), 400

    duration = 6
    cost = video_cost(duration)
    bal = _user_credits(u)
    if not current_user.is_admin and bal < cost:
        return jsonify({
            "error": f"A fight needs {cost} credits — you have {bal}. Buy credits or redeem a coupon code.",
            "needed": cost,
        }), 402

    cres = supabase.table("characters").select("*").in_("id", ids).eq("user_id", current_user.id).execute()
    rows = {str(c["id"]): c for c in (cres.data or [])}
    primaries = [rows[i]["primary_image_url"] for i in ids if i in rows and rows[i].get("primary_image_url")]
    names = [(rows[i].get("name") or "Character") for i in ids if i in rows]
    if len(primaries) != 2:
        return jsonify({"error": "Couldn't load both characters."}), 400

    payload = {
        "character_ids": ids,
        "is_admin": current_user.is_admin,
        "cost": cost,
        "duration": duration,
    }
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "fight", payload)))


@app.route("/studios/chatroom/report", methods=["POST"])
@login_required
def chatroom_report():
    try:
        mid = int(request.form.get("message_id", "0"))
    except ValueError:
        return jsonify({"error": "Bad message."}), 400
    if mid <= 0:
        return jsonify({"error": "Bad message."}), 400
    try:
        # One report per user per message (unique constraint).
        try:
            supabase.table("chat_reports").insert(
                {"message_id": mid, "reporter_user_id": current_user.id}).execute()
        except Exception:
            return jsonify({"ok": True, "already": True})  # already reported by this user

        cnt = supabase.table("chat_reports").select("id", count="exact").eq("message_id", mid).execute().count or 0
        update = {"report_count": cnt}
        if cnt >= CHAT_AUTO_HIDE_REPORTS:
            update["hidden"] = True
        supabase.table("chat_messages").update(update).eq("id", mid).execute()
        return jsonify({"ok": True, "hidden": cnt >= CHAT_AUTO_HIDE_REPORTS})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/studios/chatroom/delete", methods=["POST"])
@login_required
def chatroom_delete():
    if not current_user.is_admin:
        return jsonify({"error": "Admins only."}), 403
    try:
        mid = int(request.form.get("message_id", "0"))
    except ValueError:
        return jsonify({"error": "Bad message."}), 400
    supabase.table("chat_messages").update({"hidden": True}).eq("id", mid).execute()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════
# PICTURE PERCFECT — watermark + upscale + split, all in one (2026-07-06)
# Engine ported from Nick's proven local pipeline (SPLIT_SMART.py).
# ══════════════════════════════════════════════════════════════════
# picture_percfect removed in v2 — no watermark feature on site
def _pp_process(*a, **kw): raise NotImplementedError("Not available in v2")

PP_MAX_UPLOAD_MB = 25


@app.route("/studios/picturepercfect")
def picture_percfect_page():
    return render_template("picture_percfect.html",
                           user=current_user if current_user.is_authenticated else None)


@app.route("/studios/picturepercfect/process", methods=["POST"])
@login_required
def picture_percfect_process():
    """Process ONE photo (1 credit): optional smart split, upscale, watermark.
    Returns finished JPEGs as data URIs — nothing is stored server-side."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < 1:
        return jsonify({"error": f"No credits remaining (you have {bal}). Buy credits or redeem a coupon code."}), 402

    photo = request.files.get("photo")
    logo = request.files.get("logo")
    logo_url = request.form.get("logo_url", "").strip()
    if not photo:
        return jsonify({"error": "No photo uploaded."}), 400
    photo_bytes = photo.read()
    if len(photo_bytes) > PP_MAX_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"Photo too large (max {PP_MAX_UPLOAD_MB}MB)."}), 400

    if logo:
        logo_bytes = logo.read()
    elif logo_url:
        # a logo the user just generated with us — only fetch our own rehosted copy
        if not logo_url.startswith(_site_base_url()):
            return jsonify({"error": "Bad logo URL."}), 400
        r = requests.get(logo_url, timeout=30)
        if not r.ok:
            return jsonify({"error": "Could not load the generated logo."}), 400
        logo_bytes = r.content
    else:
        return jsonify({"error": "Upload a logo or generate one first."}), 400

    try:
        results = _pp_process(
            photo_bytes, logo_bytes,
            do_split=request.form.get("split", "1") == "1",
            do_upscale=request.form.get("upscale", "1") == "1",
            opacity=float(request.form.get("opacity", "0.75")),
            position=request.form.get("position", "bottom_right"),
            size_percent=int(request.form.get("size_percent", "25")),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Processing failed — is the photo a valid image?"}), 422

    if not current_user.is_admin:
        if not _apply_spend(
            current_user.id, user_data, 1,
            {"images_today": int(user_data.get("images_today") or 0) + 1},
        ):
            return jsonify({"error": "No credits remaining."}), 402

    images = ["data:image/jpeg;base64," + base64.b64encode(b).decode() for b in results]
    return jsonify({"ok": True, "count": len(images), "images": images,
                    "split_detected": len(images) > 1})


@app.route("/studios/picturepercfect/generate-logo", methods=["POST"])
@login_required
def picture_percfect_generate_logo():
    """Generate a watermark logo with AI (1 credit) — same engine as image gen."""
    reset_daily_if_needed(current_user.id)
    res = supabase.table("users").select(
        "picture_credits,video_credits,images_today"
    ).eq("id", current_user.id).single().execute()
    user_data = res.data or {}
    bal = _user_credits(user_data)
    if not current_user.is_admin and bal < 1:
        return jsonify({"error": f"No credits remaining (you have {bal})."}), 402

    brand = request.form.get("brand", "").strip()
    style = request.form.get("logo_style", "clean minimal").strip()
    if not brand:
        return jsonify({"error": "Tell us the brand/name for the logo."}), 400

    prompt = (f"professional watermark logo for '{brand}', {style} style, "
              f"high contrast, legible text, simple shapes, "
              f"designed to overlay on photos, plain solid background")
    payload = {"prompt": prompt, "is_admin": current_user.is_admin}
    return jsonify(async_payload(enqueue(studio_jobs, current_user.id, "picture_logo", payload)))


from percfect_posts_bp import percfect_posts_bp
app.register_blueprint(percfect_posts_bp)
from percfect_productions_bp import percfect_productions_bp
app.register_blueprint(percfect_productions_bp)
from percfect_api import api_bp
import percfect_api_3d  # noqa: F401  adds /api/v1/3d routes to api_bp before it registers
app.register_blueprint(api_bp)


@app.route("/re-up/api-keys")
@login_required
def reup_api_keys_page():
    """Percfect API keys: create (shown once), list by prefix, revoke."""
    return render_template("api_keys.html")
app.config["PLATFORM_XAI_KEY"] = os.environ.get("XAI_API_KEY") or os.environ.get("PLATFORM_XAI_KEY")

# Card Press Studio API (skills / describe / save / poses…) — always register at boot
try:
    import card_studio as _card_studio_mod

    _card_studio_mod.init_app(app)
except Exception:
    app.logger.exception("card_studio.init_app failed")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
