"""Unified Percfect credit wallet.

One balance for everything:
  • 1 credit = 1 image generate/unlock
  • VIDEO_CREDITS_PER_SECOND — base gen 0–1 ref (default 3 → 6s = 18)
  • VIDEO_REF_CREDITS_PER_SECOND — multi-ref 2–4 (default 6 → 6s = 36)
  • VIDEO_EXTEND_CREDITS_PER_SECOND — extend (default 6 → +6s = 36)
  • Trim free (local)

Legacy DB columns picture_credits + video_credits are merged for display and spend.
New purchases add to picture_credits (video_credits still honored on read).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

IMAGE_CREDIT_COST = 1
# Photos still: each attached reference photo adds this on top of the base generate
REFERENCE_PHOTO_CREDIT_COST = 1
MAX_REFERENCE_PHOTOS = 3  # Photos 1️⃣📸2️⃣📸3️⃣📸
# Percfect Precision (character super-accuracy path) — flat 5, no per-ref surcharge
PERCFECT_PRECISION_COST = 5
MAX_VIDEO_REFERENCE_PHOTOS = 4


def character_generate_cost(num_reference_photos: int = 0, *, super_accuracy: bool = False) -> int:
    """Character front generate cost.

    - Regular Generate: **1 credit flat** (reference photos do not add credits)
    - Percfect Precision (super_accuracy): **5 credits flat**
    """
    if super_accuracy:
        return int(PERCFECT_PRECISION_COST)
    return int(IMAGE_CREDIT_COST)


def photo_generate_cost(num_reference_photos: int = 0) -> int:
    """Percfect Pictures — 1 base + 1 per ref (max 3 → 4). Independent of Characters."""
    n = max(0, min(int(MAX_REFERENCE_PHOTOS), int(num_reference_photos or 0)))
    if n <= 0:
        return IMAGE_CREDIT_COST
    return IMAGE_CREDIT_COST + (REFERENCE_PHOTO_CREDIT_COST * n)


def _video_rate() -> int:
    """Base gen 0–1 ref. Nick: 3/s → 6s = 18."""
    try:
        return max(1, min(20, int(os.getenv("PERCFECT_VIDEO_CREDITS_PER_SECOND", "3"))))
    except (TypeError, ValueError):
        return 3


def _video_ref_rate() -> int:
    """Multi-ref 2–4. Nick: 6/s → 6s = 36."""
    try:
        r = int(os.getenv("PERCFECT_VIDEO_REF_CREDITS_PER_SECOND", "6"))
    except (TypeError, ValueError):
        r = 6
    return max(_video_rate(), min(20, r))


def _video_extend_rate() -> int:
    """Extend. Nick: 6/s → +6s = 36."""
    try:
        return max(1, min(20, int(os.getenv("PERCFECT_VIDEO_EXTEND_CREDITS_PER_SECOND", "6"))))
    except (TypeError, ValueError):
        return 6


VIDEO_CREDITS_PER_SECOND = _video_rate()
VIDEO_REF_CREDITS_PER_SECOND = _video_ref_rate()
VIDEO_EXTEND_CREDITS_PER_SECOND = _video_extend_rate()

# Battle Cards tickets (separate from credits)
BATTLE_TICKET_COST = {6: 5, 10: 7, 15: 15}   # entry fee by duration
BATTLE_TICKET_WIN = {6: 8, 10: 12, 15: 24}    # level-matched base win (handoff 4.2)
# Gap = opponent level − your level. Farming down pays less than the entry (handoff 4.3).
TICKET_GAP_MULT = {3: 3.0, 2: 2.0, 1: 1.5, 0: 1.0, -1: 0.6, -2: 0.4, -3: 0.25}
DAILY_FREE_TICKETS = 2
CREDITS_PER_TICKET = 5  # buy tickets with credits


def battle_ticket_cost(duration: int) -> int:
    d = int(duration or 6)
    if d <= 6:
        return BATTLE_TICKET_COST[6]
    if d <= 10:
        return BATTLE_TICKET_COST[10]
    return BATTLE_TICKET_COST[15]


def battle_ticket_win(duration: int) -> int:
    d = int(duration or 6)
    if d <= 6:
        return BATTLE_TICKET_WIN[6]
    if d <= 10:
        return BATTLE_TICKET_WIN[10]
    return BATTLE_TICKET_WIN[15]


def battle_ticket_payout(duration: int, my_level: int, opp_level: int) -> int:
    """Win payout: base × gap multiplier, rounded (handoff 4.4 table)."""
    gap = max(-3, min(3, int(opp_level) - int(my_level)))
    return int(battle_ticket_win(duration) * TICKET_GAP_MULT[gap] + 0.5)


def battle_loss_refund(duration: int, my_level: int, opp_level: int) -> int:
    """Losing while fighting upward refunds half the entry, rounded down (handoff 4.5)."""
    return battle_ticket_cost(duration) // 2 if int(opp_level) > int(my_level) else 0

# Generate lengths only (never 5). Extend uses VIDEO_EXTEND_OPTIONS.
VIDEO_DURATION_OPTIONS = (6, 10, 15)
VIDEO_EXTEND_OPTIONS = (6, 8, 10)


def snap_video_duration(seconds, default: int = 6) -> int:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return 6 if default not in VIDEO_DURATION_OPTIONS else int(default)
    if s in VIDEO_DURATION_OPTIONS:
        return s
    return min(VIDEO_DURATION_OPTIONS, key=lambda x: abs(x - s))


def snap_extend_duration(seconds, default: int = 6) -> int:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return 6 if default not in VIDEO_EXTEND_OPTIONS else int(default)
    if s in VIDEO_EXTEND_OPTIONS:
        return s
    return min(VIDEO_EXTEND_OPTIONS, key=lambda x: abs(x - s))


def image_cost(count: int = 1) -> int:
    return IMAGE_CREDIT_COST * max(1, int(count))


def video_rate_for_refs(num_reference_images: int = 0) -> int:
    n = max(0, min(int(MAX_VIDEO_REFERENCE_PHOTOS), int(num_reference_images or 0)))
    if n >= 2:
        return int(VIDEO_REF_CREDITS_PER_SECOND)
    return int(VIDEO_CREDITS_PER_SECOND)


def video_cost(seconds: int, num_reference_images: int = 0) -> int:
    """Generate cost. 0–1 ref = base rate; 2+ refs = multi rate. Not extend."""
    return max(1, int(seconds)) * video_rate_for_refs(num_reference_images)


def extend_video_cost(seconds: int) -> int:
    """Extend cost. Default 6/s → +6 = 36."""
    return max(1, int(seconds)) * int(VIDEO_EXTEND_CREDITS_PER_SECOND)

# ── One-time packs (no subscription) ─────────────────────
# Session = ~5-hour creative binge at mixed image + short-video pace.
CREDIT_PACKAGES: Dict[str, Dict[str, Any]] = {
    "try": {
        "name": "Try",
        "price": 700,       # $7
        "credits": 75,
        "tagline": "Quick taste",
        "price_id": None,
    },
    "session": {
        "name": "Session Pass",
        "price": 2900,      # $29
        "credits": 400,
        "tagline": "~5-hour creative session",
        "featured": True,
        "price_id": None,
    },
    "power": {
        "name": "Power",
        "price": 5900,      # $59
        "credits": 900,
        "tagline": "Weekend warrior",
        "price_id": None,
    },
    "marathon": {
        "name": "Marathon",
        "price": 9900,      # $99
        "credits": 1800,
        "tagline": "Maximum runway",
        "price_id": None,
    },
}

# ── Monthly subscriptions ────────────────────────────────
SUBSCRIPTION_PLANS: Dict[str, Dict[str, Any]] = {
    "creator": {
        "name": "Creator",
        "price": 1900,      # $19/mo
        "credits_per_month": 300,
        "topup_bonus_pct": 15,
        "tagline": "Steady creator flow",
        "price_id": None,
    },
    "pro": {
        "name": "Pro",
        "price": 3900,      # $39/mo
        "credits_per_month": 750,
        "topup_bonus_pct": 25,
        "tagline": "Daily production",
        "featured": True,
        "price_id": None,
    },
    "studio": {
        "name": "Studio",
        "price": 7900,      # $79/mo
        "credits_per_month": 2000,
        "topup_bonus_pct": 35,
        "tagline": "Team-scale output",
        "price_id": None,
    },
}

# Legacy Stripe Dashboard Price IDs (STRIPE_PRICE_STARTER / CREATOR / PRO, STRIPE_SUB_*)
# were often STALE (e.g. old $5/$10/$25 packs) while the buy-credits UI showed
# Try $7 / Session $29 / Power $59. Checkout then charged the wrong amount.
# Default: NEVER attach them — always charge unit_amount from this file.
# Opt-in only if you have verified Dashboard prices match CREDIT_PACKAGES exactly:
#   STRIPE_USE_DASHBOARD_PRICE_IDS=1
_LEGACY_PRICE_ENV = {
    "try": "STRIPE_PRICE_STARTER",
    "session": "STRIPE_PRICE_CREATOR",  # misnamed env — was old "Creator" pack, not Session
    "power": "STRIPE_PRICE_PRO",
}


def attach_stripe_price_ids() -> None:
    """Optionally bind Dashboard price IDs. Off by default so UI amount = charge amount."""
    import os
    raw = (os.getenv("STRIPE_USE_DASHBOARD_PRICE_IDS") or "").strip().lower()
    if raw not in ("1", "true", "yes"):
        # Ensure no stale price_id from a previous attach in-process
        for pkg in CREDIT_PACKAGES.values():
            pkg["price_id"] = None
        for plan in SUBSCRIPTION_PLANS.values():
            plan["price_id"] = None
        return
    for key, env_name in _LEGACY_PRICE_ENV.items():
        if key in CREDIT_PACKAGES:
            pid = (os.getenv(env_name) or "").strip()
            if pid:
                CREDIT_PACKAGES[key]["price_id"] = pid
    for key in SUBSCRIPTION_PLANS:
        pid = (os.getenv(f"STRIPE_SUB_{key.upper()}") or "").strip()
        if pid:
            SUBSCRIPTION_PLANS[key]["price_id"] = pid


def credit_balance(row: Optional[Dict[str, Any]]) -> int:
    if not row:
        return 0
    return int(row.get("picture_credits") or 0) + int(row.get("video_credits") or 0)


def deduct_update(row: Dict[str, Any], amount: int) -> Optional[Dict[str, int]]:
    """Return new picture_credits/video_credits after spending amount, or None if short."""
    amount = int(amount)
    if amount <= 0:
        return {
            "picture_credits": int(row.get("picture_credits") or 0),
            "video_credits": int(row.get("video_credits") or 0),
        }
    pic = int(row.get("picture_credits") or 0)
    vid = int(row.get("video_credits") or 0)
    total = pic + vid
    if total < amount:
        return None
    from_pic = min(pic, amount)
    from_vid = amount - from_pic
    return {
        "picture_credits": pic - from_pic,
        "video_credits": vid - from_vid,
    }


def add_credits_update(row: Dict[str, Any], amount: int) -> Dict[str, int]:
    """Add credits to wallet (consolidates into picture_credits)."""
    amount = int(amount)
    pic = int(row.get("picture_credits") or 0) + int(row.get("video_credits") or 0) + amount
    return {"picture_credits": pic, "video_credits": 0}


def topup_bonus_credits(base_credits: int, bonus_pct: int) -> int:
    if bonus_pct <= 0:
        return int(base_credits)
    return int(base_credits) + int(round(int(base_credits) * bonus_pct / 100))


def package_line_item(pkg: Dict[str, Any]) -> Dict[str, Any]:
    if pkg.get("price_id"):
        return {"price": pkg["price_id"], "quantity": 1}
    return {
        "price_data": {
            "currency": "usd",
            "unit_amount": int(pkg["price"]),
            "product_data": {
                "name": f"PercfectAI — {pkg['name']} ({pkg['credits']} credits)",
                "description": pkg.get("tagline") or "One-time credit top-up",
            },
        },
        "quantity": 1,
    }


def subscription_line_item(plan: Dict[str, Any]) -> Dict[str, Any]:
    if plan.get("price_id"):
        return {"price": plan["price_id"], "quantity": 1}
    return {
        "price_data": {
            "currency": "usd",
            "unit_amount": int(plan["price"]),
            "recurring": {"interval": "month"},
            "product_data": {
                "name": f"PercfectAI {plan['name']} — {plan['credits_per_month']} credits/mo",
                "description": plan.get("tagline") or "Monthly subscription",
            },
        },
        "quantity": 1,
    }