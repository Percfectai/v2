"""
Encrypt/decrypt helpers for user-pasted AI provider keys.

Requires: pip install cryptography
Requires an env var AI_KEY_ENCRYPTION_SECRET — a urlsafe-base64 32-byte key.
Generate one once with:

    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Put the output in your .env / Render env vars as AI_KEY_ENCRYPTION_SECRET.
Losing this secret means every stored key must be re-pasted by every user —
back it up the same way you back up the Stripe/webhook secrets.
"""

import os

from cryptography.fernet import Fernet, InvalidToken

_secret = os.environ.get("AI_KEY_ENCRYPTION_SECRET")
_fernet = Fernet(_secret.encode()) if _secret else None


def encrypt_key(raw_key: str) -> str:
    if not _fernet:
        raise RuntimeError("AI_KEY_ENCRYPTION_SECRET is not set — cannot store keys.")
    return _fernet.encrypt(raw_key.encode()).decode()


def decrypt_key(token: str) -> str | None:
    if not _fernet or not token:
        return None
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None
