import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import HTTPException, Request

from aivi.config import Settings

COOKIE_NAME = "aivi_session"


def authenticate(username: str, password: str, settings: Settings) -> bool:
    return secrets.compare_digest(username, settings.admin_username) and secrets.compare_digest(
        password, settings.admin_password
    )


def issue_session(username: str, settings: Settings) -> str:
    payload = {
        "sub": username,
        "exp": int(time.time()) + settings.session_hours * 3600,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.session_secret.encode(), encoded.encode(), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def session_user(token: str, settings: Settings) -> str | None:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(
            settings.session_secret.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected):
            return None
        payload = json.loads(_decode(encoded))
        if int(payload["exp"]) < int(time.time()):
            return None
        return str(payload["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def require_session(request: Request) -> str:
    user = session_user(
        request.cookies.get(COOKIE_NAME, ""),
        request.app.state.settings,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in")
    return user


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
