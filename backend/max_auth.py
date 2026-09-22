"""Server-side validation for MAX Mini App launch data."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import unquote


class MaxInitDataError(ValueError):
    """The launch data is missing, stale or cannot be verified."""


@dataclass(frozen=True)
class MaxUser:
    user_id: str
    first_name: str | None
    username: str | None


def _parse_pairs(init_data: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in init_data.split("&"):
        key, separator, value = item.partition("=")
        if not separator or not key or key in seen:
            raise MaxInitDataError("Invalid or duplicate MAX launch parameter")
        seen.add(key)
        pairs.append((key, unquote(value)))
    return pairs


def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int = 3600) -> MaxUser:
    """Verify raw window.WebApp.initData exactly as prescribed by MAX."""
    pairs = _parse_pairs(init_data)
    fields = dict(pairs)
    original_hash = fields.pop("hash", None)
    if not original_hash:
        raise MaxInitDataError("MAX launch data has no hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, original_hash):
        raise MaxInitDataError("MAX launch data signature is invalid")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, TypeError, ValueError) as error:
        raise MaxInitDataError("MAX launch data has no valid auth_date") from error
    if auth_date > time.time() + 60 or time.time() - auth_date > max_age_seconds:
        raise MaxInitDataError("MAX launch data has expired")

    try:
        user = json.loads(fields["user"])
        return MaxUser(
            user_id=str(user["id"]),
            first_name=user.get("first_name"),
            username=user.get("username"),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise MaxInitDataError("MAX launch data has no valid user") from error
