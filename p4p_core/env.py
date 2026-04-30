from __future__ import annotations

import os
from pathlib import Path


def env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw is not None else default


def env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [value.strip() for value in raw.split(",") if value.strip()]


def env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def normalized_registry_url(url: str) -> str:
    return url.strip().rstrip("/")


def load_registry_urls() -> list[str]:
    raw = os.environ.get("P4P_REGISTRY_URLS")
    values = [value.strip() for value in raw.split(",") if value.strip()] if raw else [
        env_str("P4P_REGISTRY_URL", "http://127.0.0.1:8000")
    ]

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalized_registry_url(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
