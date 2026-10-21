"""Perchance Princess — configuration, prompt builder, key normalisation.

Exports consumed by app.py for the princess generator feature.
"""

# ── URL for the Perchance image‑generation endpoint ──────────────
PERCHANCE_URL = "https://perchance.org/ai-text-to-image-generator"

# ── Display‑name → slug mapping (keys shown in UI dropdowns) ─────
PRINCESSES = {
    "Ariel":      "ariel",
    "Belle":      "belle",
    "Jasmine":    "jasmine",
    "Rapunzel":   "rapunzel",
    "Elsa":       "elsa",
    "Aurora":     "aurora",
    "Cinderella": "cinderella",
    "Moana":      "moana",
    "Tiana":      "tiana",
    "Mulan":      "mulan",
}

# Ordered list of display names for template dropdowns
PRINCESS_KEYS = list(PRINCESSES.keys())

# ── Defaults ─────────────────────────────────────────────────────
DEFAULT_COUNT = 4
DEFAULT_SIZE = "768x768"

# ── Negative prompt (shared across all princess generations) ─────
NEG_PROMPT = (
    "ugly, deformed, bad anatomy, disfigured, poorly drawn face, "
    "mutation, mutated, extra limbs, extra fingers, blurry, "
    "low quality, worst quality, watermark, text, signature"
)

# ── Character prompt fragments (mirror app.py PRINCESS_CHARACTERS) ─
_CHARACTER_PROMPTS = {
    "ariel":      "Ariel-inspired mermaid princess, flowing vibrant red hair, seashell crown, ocean sparkle",
    "belle":      "Belle-inspired princess, golden ball gown, warm brown hair, elegant and bookish charm",
    "jasmine":    "Jasmine-inspired princess, teal outfit, long black hair, Arabian palace aesthetic",
    "rapunzel":   "Rapunzel-inspired princess, impossibly long golden braid, purple dress, lantern glow",
    "elsa":       "Elsa-inspired ice queen princess, shimmering blue gown, snowflake magic, platinum braid",
    "aurora":     "Aurora-inspired sleeping beauty princess, pink flowing gown, soft rose-gold hair",
    "cinderella": "Cinderella-inspired princess, sparkling blue ball gown, glass slippers, midnight magic",
    "moana":      "Moana-inspired island princess, ocean waves, bold spirit, tropical flower accents",
    "tiana":      "Tiana-inspired princess, emerald green gown, New Orleans elegance, warm golden lighting",
    "mulan":      "Mulan-inspired warrior princess, crimson and gold, fierce grace, cherry blossom petals",
}

_SCENE_PROMPTS = {
    "castle":    "inside a grand fairy tale castle ballroom with crystal chandeliers",
    "forest":    "enchanted forest clearing with glowing fireflies and magical mist",
    "garden":    "royal rose garden at golden hour with butterflies and soft petals",
    "ocean":     "moonlit ocean shore with bioluminescent waves and starry sky",
    "ballroom":  "lavish palace ballroom during a royal celebration",
    "throne":    "ornate throne room with stained glass windows and velvet banners",
}

_STYLE_PROMPTS = {
    "3d":        "highly detailed 3D CGI render, cinematic volumetric lighting, ultra realistic skin texture, 8k masterpiece",
    "anime":     "anime illustration style, vibrant colors, clean linework, studio quality shading",
    "fantasy":   "epic fantasy art, painterly brushstrokes, dramatic rim lighting, storybook illustration",
    "cinematic": "cinematic portrait photography, shallow depth of field, film grain, golden hour glow",
}

_SCENES_LIST = list(_SCENE_PROMPTS.keys())


def normalize_princess_key(raw: str) -> str:
    """Normalize user input to a canonical princess slug (lowercase)."""
    if not raw:
        return "jasmine"
    key = raw.strip().lower()
    if key in _CHARACTER_PROMPTS:
        return key
    # Try matching display name
    for display, slug in PRINCESSES.items():
        if display.lower() == key:
            return slug
    # Partial match fallback
    for slug in _CHARACTER_PROMPTS:
        if slug.startswith(key):
            return slug
    return "jasmine"


def build_princess_prompt(
    princess_key: str,
    scene: str = "castle",
    style: str = "3d",
    extra: str = "",
) -> str:
    """Build a single princess image prompt."""
    parts = [
        _STYLE_PROMPTS.get(style, _STYLE_PROMPTS["3d"]),
        _CHARACTER_PROMPTS.get(princess_key, _CHARACTER_PROMPTS["jasmine"]),
        _SCENE_PROMPTS.get(scene, ""),
        extra.strip() if extra else "",
        "masterpiece, best quality, sharp focus, beautiful composition",
    ]
    return ", ".join(p for p in parts if p)


def build_princess_prompts(princess_key: str, count: int = 4) -> list[str]:
    """Build *count* varied princess prompts for batch generation.

    Cycles through scenes so each image in a batch looks different.
    """
    prompts: list[str] = []
    for i in range(count):
        scene = _SCENES_LIST[i % len(_SCENES_LIST)]
        prompts.append(build_princess_prompt(princess_key, scene=scene))
    return prompts
