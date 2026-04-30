from __future__ import annotations

import json
import os
from typing import Any

from .constants import DEFAULT_LOOPBACK_CORS_REGEX


def _parse_origin_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    if raw == "*":
        raise ValueError("Use an explicit origin allowlist instead of '*'.")
    if raw.startswith("["):
        parsed = json.loads(raw)
        return [str(value).strip() for value in parsed if str(value).strip()]
    return [value.strip() for value in raw.split(",") if value.strip()]


def build_cors_middleware_options(env_key: str = "P4P_CORS_ALLOW_ORIGINS") -> dict[str, Any]:
    raw = os.environ.get(env_key, "")
    allow_origins = _parse_origin_list(raw)
    options: dict[str, Any] = {
        "allow_credentials": False,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if allow_origins:
        options["allow_origins"] = allow_origins
    else:
        options["allow_origins"] = []
        options["allow_origin_regex"] = DEFAULT_LOOPBACK_CORS_REGEX
    return options
