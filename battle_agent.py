"""Battle Cards live referee + storyteller (Battle Cards Build Spec, 2026-09-19, section 7).

Order of events on every fight:
  1. Real dice, rolled in code with `secrets`: one blue die (side 0, left) and one red die (side 1, right).
  2. The tested rules engine (`app._battle_resolve`) rules on those dice: skills, stats, level effects.
     Tickets and XP follow this ruling, so a wrong story can never move money.
  3. The live AI brain (Gemini first, else the xAI chat key: `card_studio._brain_json`) narrates the fight
     moment by moment for the chosen length. That story IS the video prompt, and it must agree with the ruling.
  4. Dice, stat inputs, the ruling and the agent's output are logged to `battle_log`.

AGENT_PROMPT is Claude's wording (derived from the spec). Nick can replace it.
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Optional

log = logging.getLogger("battle_agent")
_rng = secrets.SystemRandom()

COLORS = ("blue", "red")
BEATS = {6: "2", 10: "3", 15: "4 to 5"}

AGENT_PROMPT = (
    "You are the referee and storyteller for Percfect Battle Cards. Real dice were already rolled in code "
    "and the rulebook has already ruled on them, so the winner is decided. Your job is to narrate the fight "
    "moment by moment as a short cinematic video set in the arena given in the facts, the BLUE-side fighter on the left "
    "against the RED-side fighter on the right. You are given both fighters (level, stats, unlocked skills), "
    "the dice each side rolled, which skill each side triggered, who was favored and by how much, the ruled "
    "winner, and the video length. "
    "Return ONLY JSON: {\"winner\": \"blue\" or \"red\", \"beats\": [short strings], \"video_prompt\": string}. "
    "Rules: 1) The winner MUST be the ruled winner. 2) Show every triggered skill happening the way that "
    "character does it (the skill's story is the action to film; adapt it, never contradict it). A side that "
    "rolled a 5 triggers nothing. 3) Read the matchup: a favored fighter looks dominant; if the underdog is the "
    "ruled winner, make it feel like an upset; a close fight should feel close. 4) Match the pacing to the "
    "length: 6 seconds = 2 beats, 10 seconds = 3 beats, 15 seconds = 4 to 5 beats. 5) Never reuse stock "
    "phrasing: vary the styles, camera and rhythm every time. 6) video_prompt is one paragraph, at most 900 "
    "characters, telling the whole fight in order; call them 'the blue-side fighter on the left, <name>' and "
    "'the red-side fighter on the right, <name>'; end on the winner standing victorious. For a team battle "
    "(several duels) tell the duels quickly, in order, then the team result. 7) In the video there is no "
    "on-screen text, no numbers, no stat bars, no dice and no gore. 8) If a finisher line is given, that is "
    "exactly how the winner ends the fight; film it."
)


# ── stats ────────────────────────────────────────────────────────────────────────────────────
def card_stats(row: dict) -> Optional[dict]:
    """The stats the creator set in Card Studio (characters.card_stats). None if never set (all zero)."""
    raw = (row or {}).get("card_stats")
    if not isinstance(raw, list):
        return None
    out: dict[str, int] = {}
    for s in raw:
        if isinstance(s, dict) and s.get("key") is not None:
            try:
                out[str(s["key"])] = max(0, min(100, int(s.get("value") or 0)))
            except (TypeError, ValueError):
                pass
    return out if len(out) >= 4 and sum(out.values()) > 0 else None


def scale_stats(stats: dict, target_total: int) -> dict:
    """Scale a stat block so its total is about target_total (keeps the house card a fair match)."""
    total = sum(stats.values()) or 1
    f = max(1, target_total) / total
    return {k: max(1, min(100, round(v * f))) for k, v in stats.items()}


def _favored(blue: dict, red: dict) -> tuple:
    """(side, margin) before any skills. A level is worth about 40 stat points."""
    score = (sum(blue["stats"].values()) - sum(red["stats"].values())) + 40 * (blue["level"] - red["level"])
    if score == 0:
        return "even", "razor-thin"
    gap = abs(score)
    return ("blue" if score > 0 else "red"), ("slight" if gap <= 15 else "moderate" if gap <= 60 else "large")


# ── one duel ─────────────────────────────────────────────────────────────────────────────────
def _skill_view(f: dict, level: int) -> dict:
    s = (f.get("skills") or [{}] * 4)[level - 1] if 0 < level <= len(f.get("skills") or []) else {}
    return {
        "level": level,
        "name": s.get("name") or f"Level {level}",
        "effect": s.get("effect") or "",
        "story": s.get("text") or "",
    }


def _duel(blue: dict, red: dict, finisher: str) -> dict:
    import app as app_mod

    rolls = [_rng.randint(1, 6), _rng.randint(1, 6)]  # real randomness, never the model's
    ruling = app_mod._battle_resolve(blue, red, finisher, rolls=rolls)
    fin = [bool(x) for x in ruling["finisher"]]
    fav, margin = _favored(blue, red)

    def triggered(i: int, f: dict) -> Optional[dict]:
        level = 4 if fin[i] else int(ruling["skills"][i] or 0)
        return _skill_view(f, level) if level else None

    return {
        "blue": blue["id"],
        "red": red["id"],
        "dice": {"blue": rolls[0], "red": rolls[1]},
        "skills": {"blue": triggered(0, blue), "red": triggered(1, red)},
        "finisher": {"blue": fin[0], "red": fin[1]},
        "winner_side": int(ruling["side"]),
        "totals": ruling["totals"],
        "story": ruling["story"],
        "favored": fav,
        "margin": margin,
    }


# ── the agent ────────────────────────────────────────────────────────────────────────────────
def _facts(duels: list, records: list, duration: int, finisher: str, mode: str) -> dict:
    def side(f: dict) -> dict:
        return {
            "name": f["name"],
            "level": f["level"],
            "stats": f["stats"],
            "unlocked_skills": [_skill_view(f, i) for i in range(1, f["level"] + 1)],
        }

    out: dict[str, Any] = {
        "mode": mode,
        "video_seconds": duration,
        "beats_to_write": BEATS.get(duration, "2 to 3"),
        "duels": [],
    }
    for (b, r), rec in zip(duels, records):
        out["duels"].append({
            "blue": side(b),
            "red": side(r),
            "dice": rec["dice"],
            "skill_triggered": rec["skills"],
            "level_4_finisher": rec["finisher"],
            "favored": rec["favored"],
            "favored_margin": rec["margin"],
            "ruled_winner": COLORS[rec["winner_side"]],
            "totals_after_skills": {"blue": rec["totals"][0], "red": rec["totals"][1]},
        })
    if any(any(rec["finisher"].values()) for rec in records) and finisher:
        out["finisher_line"] = finisher
    return out


def _narrate(facts: dict, want: str, images: list) -> Optional[dict]:
    """Ask the brain for the story. Must name the ruled winner; one retry, then None."""
    from card_studio import _brain_json, _writer_key

    note = ""
    for _ in range(2):
        try:
            out = _brain_json(AGENT_PROMPT, json.dumps(facts, ensure_ascii=False) + note, _writer_key(), images, max_tokens=2000)
        except Exception:
            log.exception("battle agent call failed")
            return None
        prompt = str(out.get("video_prompt") or "").strip()
        beats = [str(b).strip() for b in (out.get("beats") or []) if str(b).strip()]
        if out.get("winner") == want and len(prompt) >= 80 and beats:
            return {"video_prompt": prompt[:1200], "beats": beats[:8]}
        note = f"\n\nYour last answer was rejected. The ruled winner is {want}; the story must end with {want} winning."
    log.warning("battle agent never agreed with the ruling (%s)", want)
    return None


def _fallback(duels: list, records: list, duration: int, arena: str = "inside a stone Roman Colosseum") -> dict:
    names = ", ".join(f"{b['name']} (blue, left) vs {r['name']} (red, right)" for b, r in duels)
    story = " ".join(rec["story"] for rec in records)
    return {
        "video_prompt": (
            f"A cinematic {duration}-second duel {arena}: {names}. {story} "
            "Dramatic lighting, no on-screen text, no gore."
        )[:1200],
        "beats": [rec["story"] for rec in records],
    }


def resolve_battle(duels: list, duration: int, finisher: str = "", mode: str = "human", arena: str = "") -> dict:
    """Roll, rule, narrate. duels = [(blue_fighter, red_fighter), ...] (one duel, or three for teams)."""
    records = [_duel(b, r, finisher) for b, r in duels]
    if len(records) == 1:
        winner_side = records[0]["winner_side"]
    else:  # team battle: majority of the duels
        winner_side = 0 if sum(1 for rec in records if rec["winner_side"] == 0) * 2 > len(records) else 1
    images = []
    if len(duels) == 1:
        images = [f["portrait"] for f in duels[0] if f.get("portrait", "").startswith("http")]
    arena = arena or "inside a stone Roman Colosseum"
    facts = _facts(duels, records, duration, finisher, mode)
    facts["arena"] = arena
    story = _narrate(facts, COLORS[winner_side], images)
    agent_ok = story is not None
    if story is None:
        story = _fallback(duels, records, duration, arena)
    return {
        "duels": records,
        "winner_side": winner_side,
        "video_prompt": story["video_prompt"],
        "beats": story["beats"],
        "agent_ok": agent_ok,
    }


# ── log ──────────────────────────────────────────────────────────────────────────────────────
def log_battle(user_id: int, mode: str, duration: int, duels: list, outcome: dict, money: dict) -> None:
    """Raw dice + stat inputs beside the agent's output, so any disputed result can be checked."""
    try:
        import app as app_mod

        app_mod.supabase.table("battle_log").insert({
            "user_id": user_id,
            "mode": mode,
            "duration": duration,
            "fighters": [[{k: f[k] for k in ("id", "name", "level", "stats")} for f in pair] for pair in duels],
            "dice": [d["dice"] for d in outcome["duels"]],
            "ruling": [
                {"winner_side": d["winner_side"], "totals": d["totals"], "finisher": d["finisher"],
                 "skills": {c: (d["skills"][c] or {}).get("level") for c in COLORS}}
                for d in outcome["duels"]
            ],
            "agent": {"ok": outcome["agent_ok"], "beats": outcome["beats"], "video_prompt": outcome["video_prompt"]},
            "winner_side": outcome["winner_side"],
            "money": money,
        }).execute()
    except Exception:
        log.warning("battle_log insert failed", exc_info=True)
