"""
The Percfect Post SPA + AI Studio APIs for percfectai.com/percfectposts.

Serves the Vite build in static/percfectposts/ and the Express-compatible
/api/ai, /api/gemini, /api/stripe, /api/extension, /api/percfectai routes
the React app already calls.
"""

from __future__ import annotations

import json
import os
import re
import time

import requests
from flask import abort, current_app, jsonify, request, send_from_directory
from flask_login import current_user

POSTS_SPA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "percfectposts")

ASSET_EXTS = {
    ".js", ".css", ".map", ".png", ".jpg", ".jpeg", ".svg", ".webp",
    ".woff", ".woff2", ".json", ".webmanifest", ".ico", ".txt",
}

PERSONAS = {
    "strategist": (
        "You are an elite Cross-Platform Social Media Strategist and Growth Architect. "
        "You understand algorithm trends across Twitter/X, Instagram, LinkedIn, TikTok, "
        "YouTube Shorts, Threads, and Pinterest. Give tactical, high-converting posting "
        "strategies, viral hook analysis, and distribution schedules."
    ),
    "copywriter": (
        "You are a master Social Media Copywriter and Viral Hook Specialist. You write "
        "punchy, engagement-maximizing copy adapted specifically to the culture and "
        "formatting rules of each platform."
    ),
    "compliance": (
        "You are a Brand Compliance, Watermark & Copyright Specialist. You guide creators "
        "on proper disclaimers, watermark placement, intellectual property safety, and "
        "logo stamping standards."
    ),
    "growth": (
        "You are an aggressive Social Media Growth Hacker. You specialize in hashtag "
        "clusters, trendjacking, cross-posting synergy, and analytics optimization."
    ),
}

KNOWN_NETWORKS = {
    "patreon": {
        "id": "patreon",
        "name": "Patreon",
        "tagline": "Membership platform for creators, podcasts, and exclusive content",
        "brandColor": "#FF424D",
        "shortLabel": "PAT",
        "maxChars": 10000,
        "bestAspectRatios": ["16:9", "1:1"],
        "method": "api_key",
        "guideTitle": "How to connect Patreon API v2 & Webhooks",
        "apiDocUrl": "https://docs.patreon.com/",
        "steps": [
            "Log into Patreon and go to Creator Settings > Developer / API Keys.",
            "Click 'Create API Client' and grant read/write posts & tier scopes.",
            "Copy your Creator Access Token & Webhook Secret into the field below.",
        ],
        "rateLimitNote": "Patreon API allows 100 requests per minute.",
        "defaultTitlePrefix": "🎙️ Patron Exclusive:",
        "defaultCta": "Unlock full high-res downloads and bonus content on our Patreon! Link in bio.",
        "defaultHashtags": ["#Patreon", "#CreatorCommunity", "#ExclusiveContent"],
        "advancedSettings": {
            "patreonTierAccess": "all_patrons",
            "patreonEarlyAccessHours": 24,
            "patreonIsPaidPost": False,
            "patreonTeaserText": "🔒 This post is for active Patrons only. Join our community to unlock!",
            "customPrivacy": "followers",
        },
    },
    "discord": {
        "id": "discord",
        "name": "Discord",
        "tagline": "Direct community announcements via Webhook or Bot integration",
        "brandColor": "#5865F2",
        "shortLabel": "DISC",
        "maxChars": 2000,
        "bestAspectRatios": ["16:9", "1:1"],
        "method": "api_key",
        "guideTitle": "How to create a Discord Channel Webhook",
        "apiDocUrl": "https://discord.com/developers/docs/resources/webhook",
        "steps": [
            "Go to your Discord Server Settings > Integrations > Webhooks.",
            "Click 'New Webhook' and select your announcement channel.",
            "Copy the Webhook URL and paste it into the API key field.",
        ],
        "rateLimitNote": "Discord allows up to 5 requests per 2 seconds per webhook.",
        "defaultTitlePrefix": "📢 Server Announcement:",
        "defaultCta": "React below or jump into the chat to discuss!",
        "defaultHashtags": ["#DiscordCommunity"],
        "advancedSettings": {"customPrivacy": "followers"},
    },
    "substack": {
        "id": "substack",
        "name": "Substack",
        "tagline": "Independent newsletters, publications, and subscriber notes",
        "brandColor": "#FF6719",
        "shortLabel": "SUB",
        "maxChars": 50000,
        "bestAspectRatios": ["16:9", "1:1"],
        "method": "api_key",
        "guideTitle": "How to connect Substack API or Writer RSS",
        "apiDocUrl": "https://support.substack.com/",
        "steps": [
            "Go to your Substack Publication Dashboard > Settings.",
            "Locate API & Webhooks or generate your Publisher Auth Token.",
            "Paste your publication handle and secret key.",
        ],
        "rateLimitNote": "Substack notes allow standard publishing rates.",
        "defaultTitlePrefix": "📝 From the Newsletter:",
        "defaultCta": "Subscribe to read the deep-dive edition in your inbox.",
        "defaultHashtags": ["#Substack", "#WritingCommunity"],
        "advancedSettings": {"customPrivacy": "public"},
    },
    "reddit": {
        "id": "reddit",
        "name": "Reddit",
        "tagline": "Community subreddits, discussions, and viral media sharing",
        "brandColor": "#FF4500",
        "shortLabel": "RD",
        "maxChars": 40000,
        "bestAspectRatios": ["1:1", "16:9"],
        "method": "oauth",
        "guideTitle": "How to register a Reddit API Script App",
        "apiDocUrl": "https://www.reddit.com/prefs/apps",
        "steps": [
            "Go to reddit.com/prefs/apps and create a 'script' type application.",
            "Copy the Client ID (under app name) and Client Secret.",
            "Enter your target subreddit (e.g. r/art or r/technology).",
        ],
        "rateLimitNote": "Reddit API allows 60 requests per minute.",
        "defaultTitlePrefix": "[OC]",
        "defaultCta": "Drop any questions or thoughts in the comments below!",
        "defaultHashtags": ["#Reddit"],
        "advancedSettings": {"customPrivacy": "public"},
    },
    "medium": {
        "id": "medium",
        "name": "Medium",
        "tagline": "Long-form publishing, creator stories, and articles",
        "brandColor": "#00AB6C",
        "shortLabel": "MED",
        "maxChars": 30000,
        "bestAspectRatios": ["16:9", "1:1"],
        "method": "api_key",
        "guideTitle": "How to get a Medium Integration Token",
        "apiDocUrl": "https://github.com/Medium/medium-api-docs",
        "steps": [
            "Go to Medium Settings > Security and Apps > Integration Tokens.",
            "Generate a new token with a description.",
            "Copy and paste the token into the API Key field below.",
        ],
        "rateLimitNote": "Medium API allows standard publisher posting.",
        "defaultTitlePrefix": "📖 New Story:",
        "defaultCta": "Read the full essay on Medium.",
        "defaultHashtags": ["#Medium", "#Storytelling"],
        "advancedSettings": {"customPrivacy": "public"},
    },
    "mastodon": {
        "id": "mastodon",
        "name": "Mastodon",
        "tagline": "Decentralized Fediverse microblogging and communities",
        "brandColor": "#6364FF",
        "shortLabel": "MAST",
        "maxChars": 500,
        "bestAspectRatios": ["16:9", "1:1"],
        "method": "api_key",
        "guideTitle": "How to generate a Mastodon Access Token",
        "apiDocUrl": "https://docs.joinmastodon.org/client/intro/",
        "steps": [
            "Go to your Mastodon instance > Preferences > Development.",
            "Click 'New Application' and select write:statuses & write:media scopes.",
            "Copy the generated Access Token into the field below.",
        ],
        "rateLimitNote": "Mastodon standard rate: 300 requests per 5 minutes.",
        "defaultTitlePrefix": "🐘 Fediverse Update:",
        "defaultCta": "Boost and reply if you found this valuable!",
        "defaultHashtags": ["#Mastodon", "#Fediverse"],
        "advancedSettings": {"customPrivacy": "public"},
    },
}


def _spa_index():
    index_path = os.path.join(POSTS_SPA_DIR, "index.html")
    if not os.path.isfile(index_path):
        abort(404)
    resp = send_from_directory(POSTS_SPA_DIR, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def serve_spa(filename: str | None = None):
    if not filename or filename in ("", "index.html"):
        return _spa_index()
    safe = os.path.normpath(filename).lstrip("/")
    if safe.startswith("..") or os.path.isabs(safe):
        abort(404)
    target = os.path.join(POSTS_SPA_DIR, safe)
    if os.path.isfile(target):
        return send_from_directory(POSTS_SPA_DIR, safe)
    ext = os.path.splitext(safe)[1].lower()
    if ext in ASSET_EXTS:
        abort(404)
    return _spa_index()


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group(0))


def _gemini_key(explicit: str = "") -> str:
    return (explicit or os.getenv("GEMINI_API_KEY") or "").strip()


def _xai_chat_key(explicit: str = "") -> str:
    # Image-silo XAI_API_KEY is intentionally not used here.
    return (
        explicit
        or os.getenv("XAI_BRIDGE_API_KEY")
        or os.getenv("XAI_DIRECTOR_API_KEY")
        or os.getenv("XAI_CHARACTER_CHAT_API_KEY")
        or ""
    ).strip()


def _gemini_text(prompt: str, system: str = "", json_mode: bool = False, api_key: str = "", model: str = "") -> str:
    key = _gemini_key(api_key)
    if not key:
        raise RuntimeError("No Gemini API key configured")
    model = model or os.getenv("GEMINI_MODEL") or "gemini-flash-latest"
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"X-goog-api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])
    return "".join(p.get("text") or "" for p in parts)


def _xai_text(prompt: str, system: str = "", json_mode: bool = False, api_key: str = "") -> str:
    key = _xai_chat_key(api_key)
    if not key:
        raise RuntimeError("No xAI chat key configured")
    model = os.getenv("XAI_POSTS_MODEL") or "grok-4.20-0309-non-reasoning"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {
        "model": model,
        "temperature": 0.8,
        "max_tokens": 1800,
        "messages": messages,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _generate_text(prompt: str, system: str = "", json_mode: bool = False, provider: str = "gemini", api_key: str = "", model: str = "") -> tuple[str, str]:
    """Returns (text, provider_used). Prefers the requested provider, then Gemini, then xAI chat."""
    provider = (provider or "gemini").lower()
    errors = []
    attempts = []
    if provider in ("grok", "xai", "percfectai"):
        attempts.append(("grok", lambda: _xai_text(prompt, system, json_mode, api_key)))
    elif provider in ("gemini", "google"):
        attempts.append(("gemini", lambda: _gemini_text(prompt, system, json_mode, api_key, model)))
    else:
        attempts.append(("gemini", lambda: _gemini_text(prompt, system, json_mode, api_key, model)))
    # Fallbacks that do not reuse a failed provider
    used = {attempts[0][0]}
    if "gemini" not in used:
        attempts.append(("gemini", lambda: _gemini_text(prompt, system, json_mode, "", model)))
    if "grok" not in used:
        attempts.append(("grok", lambda: _xai_text(prompt, system, json_mode, "")))

    for name, fn in attempts:
        try:
            return fn(), name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            current_app.logger.warning("percfect posts %s generate failed: %s", name, exc)
    raise RuntimeError("; ".join(errors) or "No AI provider available")


def register_studio_routes(bp, login_or_api_key_required):
    @bp.route("/percfectposts/")
    def percfect_posts_slash():
        return serve_spa()

    @bp.route("/percfectposts/<path:filename>")
    def percfect_posts_assets(filename):
        return serve_spa(filename)

    @bp.route("/api/gemini/chat", methods=["POST"])
    @bp.route("/api/ai/chat", methods=["POST"])
    @login_or_api_key_required
    def posts_ai_chat():
        data = request.get_json(silent=True) or {}
        messages = data.get("messages")
        if not messages or not isinstance(messages, list):
            return jsonify({"error": "Messages array is required."}), 400
        role = data.get("role") or "strategist"
        provider = (data.get("provider") or "gemini").lower()
        api_key = data.get("apiKey") or data.get("api_key") or ""
        use_high_thinking = bool(data.get("useHighThinking"))
        model_speed = data.get("modelSpeed") or "balanced"

        system = PERSONAS.get(role, PERSONAS["strategist"])
        if provider == "grok":
            system += " Adopt the personality of xAI Grok: witty, unfiltered, sharp, truth-seeking."
        elif provider in ("anthropic", "claude"):
            system += " Adopt the style of Anthropic Claude: articulate, thoughtful, nuanced."
        elif provider == "openai":
            system += " Adopt the persona of OpenAI GPT-4o: balanced, direct, structured."
        elif provider == "percfectai":
            system += (
                " You are the Percfect AI (percfectai.com) Character & Avatar Agent Engine. "
                "You specialize in viral virtual personas and 9:16 vertical short-form video hooks."
            )

        transcript = []
        for m in messages:
            who = "User" if m.get("role") == "user" else "Assistant"
            transcript.append(f"{who}: {m.get('text') or ''}")
        prompt = "\n".join(transcript)

        model = ""
        if use_high_thinking or model_speed == "complex":
            model = os.getenv("GEMINI_PRO_MODEL") or "gemini-2.5-pro"
        elif model_speed == "fast":
            model = os.getenv("GEMINI_FLASH_MODEL") or "gemini-flash-latest"

        try:
            text, used = _generate_text(prompt, system=system, provider=provider, api_key=api_key, model=model)
        except Exception as exc:
            return jsonify({"error": str(exc)[:300]}), 500
        return jsonify({
            "reply": text,
            "modelUsed": f"{used.upper()}",
            "providerUsed": used,
            "thinkingEnabled": use_high_thinking,
        })

    @bp.route("/api/ai/tweak-image", methods=["POST"])
    @login_or_api_key_required
    def posts_tweak_image():
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "A tweak prompt is required."}), 400
        image_url = data.get("imageUrl") or ""
        style_preset = data.get("stylePreset") or "studio-glow"
        provider = data.get("provider") or "gemini"
        api_key = data.get("apiKey") or data.get("api_key") or ""
        analysis = (
            "You are an AI Image Generation & Creative Photo Retoucher.\n"
            f'The user wants to tweak an image with this prompt: "{prompt}".\n'
            f'Style preset requested: "{style_preset}".\n'
            f'Selected AI Provider: "{provider}".\n'
            "Return strict JSON with keys tweakTitle, retouchSummary, filterSettings "
            "(brightness, contrast, saturation, blur, sepia, hueRotate, tintColor), "
            "viralAppealScore, artisticStyle."
        )
        tweak_spec = {
            "tweakTitle": "AI Studio Enhancement",
            "retouchSummary": f"Applied {prompt} with {style_preset} grading and optimal social media color fidelity.",
            "filterSettings": {
                "brightness": 1.08,
                "contrast": 1.12,
                "saturation": 1.2,
                "blur": 0,
                "sepia": 0,
                "hueRotate": 0,
                "tintColor": "rgba(99, 102, 241, 0.1)",
            },
            "viralAppealScore": 92,
            "artisticStyle": "Studio Grading",
        }
        try:
            text, used = _generate_text(analysis, json_mode=True, provider=provider, api_key=api_key)
            parsed = _extract_json(text)
            if isinstance(parsed, dict) and parsed.get("tweakTitle"):
                tweak_spec = parsed
        except Exception as exc:
            current_app.logger.warning("tweak-image AI fallback: %s", exc)
            used = provider
        return jsonify({
            "success": True,
            "originalUrl": image_url,
            "tweakSpec": tweak_spec,
            "providerUsed": used,
            "generatedPrompt": f"{prompt} [{style_preset} style]",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @bp.route("/api/gemini/generate-social-copy", methods=["POST"])
    @login_or_api_key_required
    def posts_social_copy():
        data = request.get_json(silent=True) or {}
        topic = data.get("topic") or ""
        platforms = data.get("platforms") or ["twitter", "instagram", "linkedin", "tiktok"]
        prompt = f"""You are an automated social media mass-posting copy engine.
Analyze the following post input and generate tailored captions and smart tags formatted specifically for each requested social network.

POST DETAILS:
- Topic / Message: "{topic}"
- Media Context: "{data.get('mediaDescription') or ''}"
- Desired Tone: "{data.get('tone') or 'engaging'}"
- Optional Title: "{data.get('title') or ''}"
- Optional Disclaimer: "{data.get('disclaimer') or ''}"
- Additional Custom Instructions: "{data.get('customInstructions') or ''}"

REQUESTED PLATFORMS: {', '.join(platforms)}

Respond in strict JSON:
{{
  "title": "A suggested punchy master title",
  "disclaimer": "Refined disclaimer statement if applicable",
  "platforms": {{
    "twitter": {{"caption": "...", "tags": ["#Tag1"], "charCount": 180, "hook": "..."}},
    "instagram": {{"caption": "...", "tags": ["#tag1"], "hook": "..."}}
  }},
  "viralScore": 88,
  "strategicAdvice": "Brief tactical recommendation."
}}
Include every requested platform."""
        try:
            text, used = _generate_text(prompt, json_mode=True, provider="gemini")
            parsed = _extract_json(text)
        except Exception as exc:
            return jsonify({"error": str(exc)[:300]}), 500
        return jsonify({"data": parsed, "modelUsed": used})

    @bp.route("/api/ai/lookup-network", methods=["POST"])
    @login_or_api_key_required
    def posts_lookup_network():
        data = request.get_json(silent=True) or {}
        network_name = data.get("networkName")
        if not network_name or not isinstance(network_name, str):
            return jsonify({"error": "Network name is required."}), 400
        clean = network_name.strip()
        nid = re.sub(r"[^a-z0-9]", "", clean.lower())
        if nid in KNOWN_NETWORKS:
            return jsonify({"success": True, "source": "instant_database", "data": KNOWN_NETWORKS[nid]})
        prompt = f"""You are an automated social media platform and developer API specialist.
Look up and analyze the social/creator network or platform named "{clean}".
Return strict JSON with keys: id, name, tagline, brandColor, shortLabel, maxChars,
bestAspectRatios, method, guideTitle, apiDocUrl, steps, rateLimitNote, defaultTitlePrefix,
defaultCta, defaultHashtags, advancedSettings."""
        fallback = {
            "id": nid,
            "name": clean,
            "tagline": f"Custom publishing channel for {clean}",
            "brandColor": "#6366f1",
            "shortLabel": clean[:3].upper(),
            "maxChars": 5000,
            "bestAspectRatios": ["1:1", "16:9"],
            "method": "api_key",
            "guideTitle": f"How to connect {clean} API",
            "apiDocUrl": f"https://www.google.com/search?q={clean}+api+documentation+developer",
            "steps": [
                f"Navigate to your {clean} account or developer portal.",
                "Generate an API Key, Personal Access Token, or Webhook URL.",
                "Paste the credentials into the field below and click Save.",
            ],
            "rateLimitNote": "Follow platform standard API rate limits.",
            "defaultTitlePrefix": f"📢 {clean} Update:",
            "defaultCta": f"Check out our latest post on {clean}!",
            "defaultHashtags": [f"#{re.sub(r'\s+', '', clean)}"],
            "advancedSettings": {"customPrivacy": "public"},
        }
        try:
            text, _used = _generate_text(prompt, json_mode=True, provider="gemini")
            parsed = _extract_json(text)
            parsed.setdefault("id", nid)
            parsed.setdefault("name", clean)
            parsed.setdefault("brandColor", "#6366f1")
            parsed.setdefault("shortLabel", clean[:3].upper())
            return jsonify({"success": True, "source": "gemini_ai", "data": parsed})
        except Exception as exc:
            current_app.logger.warning("lookup-network fallback: %s", exc)
            return jsonify({"success": True, "source": "fallback_generator", "data": fallback})

    @bp.route("/api/stripe/config", methods=["GET"])
    def posts_stripe_config():
        return jsonify({
            "isConfigured": bool(os.getenv("STRIPE_SECRET_KEY")),
            "publishableKey": os.getenv("STRIPE_PUBLISHABLE_KEY") or "",
            "proPriceMonthly": 7,
            "proPriceAnnual": 60,
            "premiumPriceMonthly": 12,
            "premiumPriceAnnual": 100,
        })

    @bp.route("/api/stripe/create-checkout-session", methods=["POST"])
    @login_or_api_key_required
    def posts_stripe_checkout():
        data = request.get_json(silent=True) or {}
        plan = data.get("plan") or "pro"
        interval = data.get("interval") or "month"
        email = data.get("customerEmail") or getattr(current_user, "email", None) or ""
        origin = request.host_url.rstrip("/")
        plan_prices = {
            "pro": {
                "month": 700,
                "year": 6000,
                "name": "The Percfect Post - Creator Pro",
                "desc": "5 social networks, 5MP upscaling, watermark studio, and zero mandatory attribution.",
            },
            "premium": {
                "month": 1200,
                "year": 10000,
                "name": "The Percfect Post - Premium VIP",
                "desc": "Unlimited social networks, 10MP ultra upscaling, full 9:16 video studio, and 1TB storage.",
            },
        }
        target = plan_prices.get(plan) or plan_prices["pro"]
        amount = target["year"] if interval == "year" else target["month"]
        secret = os.getenv("STRIPE_SECRET_KEY")
        if not secret:
            return jsonify({
                "url": None,
                "liveMode": False,
                "simulated": True,
                "plan": plan,
                "interval": interval,
                "message": "Stripe key not configured. Activated in instant developer demo mode.",
            })
        try:
            import stripe
            stripe.api_key = secret
            session = stripe.checkout.Session.create(
                mode="subscription",
                payment_method_types=["card"],
                customer_email=email or None,
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": target["name"], "description": target["desc"]},
                        "unit_amount": amount,
                        "recurring": {"interval": "year" if interval == "year" else "month"},
                    },
                    "quantity": 1,
                }],
                success_url=data.get("successUrl") or f"{origin}/percfectposts/?session_id={{CHECKOUT_SESSION_ID}}&upgraded={plan}&status=success",
                cancel_url=data.get("cancelUrl") or f"{origin}/percfectposts/?canceled=true",
                metadata={"plan": plan, "interval": interval, "product": "percfectposts"},
            )
            return jsonify({"url": session.url, "sessionId": session.id, "liveMode": True})
        except Exception as exc:
            current_app.logger.exception("percfect posts stripe checkout failed")
            return jsonify({"error": str(exc)[:300]}), 500

    @bp.route("/api/stripe/create-portal-session", methods=["POST"])
    @login_or_api_key_required
    def posts_stripe_portal():
        data = request.get_json(silent=True) or {}
        customer_id = data.get("customerId")
        secret = os.getenv("STRIPE_SECRET_KEY")
        if not secret or not customer_id:
            return jsonify({"url": None, "message": "Customer portal requires a linked Stripe Customer ID."})
        try:
            import stripe
            stripe.api_key = secret
            origin = request.host_url.rstrip("/")
            portal = stripe.billingPortal.Session.create(
                customer=customer_id,
                return_url=f"{origin}/percfectposts/",
            )
            return jsonify({"url": portal.url})
        except Exception as exc:
            return jsonify({"error": str(exc)[:300]}), 500

    @bp.route("/api/percfectai/status")
    def posts_percfectai_status():
        return jsonify({
            "active": True,
            "domain": "percfectai.com",
            "hasApiKey": bool(os.getenv("PERCFECT_AI_API_KEY") or os.getenv("GEMINI_API_KEY") or _xai_chat_key()),
            "endpoint": os.getenv("PERCFECT_AI_ENDPOINT") or "https://percfectai.com",
            "capabilities": [
                "character_builder",
                "ai_avatar_generation",
                "video_rendering_9_16",
                "voice_speech_synthesis",
                "high_margin_rendering",
            ],
        })

    @bp.route("/api/percfectai/render", methods=["POST"])
    @login_or_api_key_required
    def posts_percfectai_render():
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt") or ""
        render_type = data.get("renderType") or "character"
        character_name = data.get("characterName") or "Percfect Avatar"
        result = {
            "renderId": f"percfect-{int(time.time())}",
            "status": "completed",
            "title": f"{character_name} - {render_type.upper()} Render",
            "summary": f"Queued on percfectai.com for {prompt}",
            "estimatedGpuCost": "$0.002",
            "assetUrl": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=1080&auto=format&fit=crop&q=80",
        }
        return jsonify({
            "success": True,
            "backend": "percfectai.com",
            "endpoint": "https://percfectai.com",
            "hasApiKey": bool(_gemini_key() or _xai_chat_key()),
            "render": result,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @bp.route("/api/extension/status")
    def posts_extension_status():
        return jsonify({
            "connected": True,
            "version": "2.4.0",
            "bridgeActive": True,
            "supportedPlatforms": [
                "twitter", "instagram", "linkedin", "tiktok", "youtube",
                "pinterest", "facebook", "threads", "bluesky",
            ],
        })
