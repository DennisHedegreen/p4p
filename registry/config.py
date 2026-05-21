from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from p4p_core import RegistryEntry
from p4p_identity import load_or_create_private_key, public_key_from_private

from registry.models import (
    CuratedIndexPromotionPolicy,
    MirrorDiscoveryPolicy,
    MirrorUpstream,
    RegistryExportScope,
    RegistryMetadata,
)


def normalized_registry_url(value: str | object) -> str:
    return str(value).rstrip("/")


def load_backup_registries() -> list[RegistryEntry]:
    raw = os.environ.get("P4P_BACKUP_REGISTRIES")
    if not raw:
        return []

    parsed = json.loads(raw)
    return [RegistryEntry(**entry) for entry in parsed]


def load_mirror_upstream_list(env_key: str) -> list[MirrorUpstream]:
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return []

    if raw.startswith("["):
        parsed = json.loads(raw)
        values: list[MirrorUpstream] = []
        for entry in parsed:
            if isinstance(entry, str):
                values.append(MirrorUpstream(url=entry))
            else:
                values.append(MirrorUpstream(**entry))
        return values

    return [MirrorUpstream(url=value.strip()) for value in raw.split(",") if value.strip()]


def load_mirror_upstreams() -> list[MirrorUpstream]:
    return load_mirror_upstream_list("P4P_MIRROR_UPSTREAMS")


def load_mirror_trusted_upstreams() -> list[MirrorUpstream]:
    return load_mirror_upstream_list("P4P_MIRROR_TRUSTED_UPSTREAMS")


def resolve_mirror_discovery_policy(
    configured_upstreams: list[MirrorUpstream],
    trusted_upstreams: list[MirrorUpstream],
) -> MirrorDiscoveryPolicy:
    raw = os.environ.get("P4P_MIRROR_DISCOVERY_POLICY", "").strip()
    if raw:
        if raw not in {"trusted_only", "all_active"}:
            raise ValueError(
                "P4P_MIRROR_DISCOVERY_POLICY must be 'trusted_only' or 'all_active'"
            )
        return raw
    if trusted_upstreams or configured_upstreams:
        return "trusted_only"
    return "all_active"


def resolve_trusted_mirror_upstreams(
    *,
    configured_upstreams: list[MirrorUpstream],
    explicit_trusted_upstreams: list[MirrorUpstream],
) -> list[MirrorUpstream]:
    source = explicit_trusted_upstreams or configured_upstreams
    deduped: list[MirrorUpstream] = []
    seen: set[str] = set()
    for upstream in source:
        normalized = normalized_registry_url(upstream.url)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(upstream)
    return deduped


def resolve_registry_source_reexport_policy() -> RegistryExportScope:
    raw = os.environ.get("P4P_REGISTRY_SOURCE_REEXPORT_POLICY", "").strip()
    if not raw:
        return "local_only"
    if raw not in {"local_only", "local_plus_trusted_mirrors"}:
        raise ValueError(
            "P4P_REGISTRY_SOURCE_REEXPORT_POLICY must be 'local_only' or 'local_plus_trusted_mirrors'"
        )
    return raw


def resolve_curated_index_promotion_policy() -> CuratedIndexPromotionPolicy:
    raw = os.environ.get("P4P_CURATED_INDEX_PROMOTION_POLICY", "").strip()
    if not raw:
        return "manual_only"
    if raw not in {"manual_only", "trusted_mirrors"}:
        raise ValueError(
            "P4P_CURATED_INDEX_PROMOTION_POLICY must be 'manual_only' or 'trusted_mirrors'"
        )
    return raw


def load_registry_private_key() -> str | None:
    inline_private_key = os.environ.get("P4P_REGISTRY_PRIVATE_KEY", "").strip()
    if inline_private_key:
        return inline_private_key

    key_file = os.environ.get("P4P_REGISTRY_KEY_FILE", "").strip()
    if not key_file:
        return None
    return load_or_create_private_key(Path(key_file).expanduser())


def load_registry_metadata() -> RegistryMetadata:
    raw = os.environ.get("P4P_REGISTRY_METADATA", "").strip()
    if raw:
        return RegistryMetadata(**json.loads(raw))
    return RegistryMetadata()


@dataclass(frozen=True)
class RegistryConfig:
    registry_url: str
    registry_admin_token: str
    backup_registries: list[RegistryEntry]
    mirror_upstreams: list[MirrorUpstream]
    mirror_trusted_upstreams: list[MirrorUpstream]
    trusted_mirror_upstream_urls: set[str]
    mirror_discovery_policy: MirrorDiscoveryPolicy
    registry_source_reexport_policy: RegistryExportScope
    curated_index_promotion_policy: CuratedIndexPromotionPolicy
    mirror_sync_interval_seconds: int
    mirror_source_ttl_seconds: int
    registry_private_key: str | None
    registry_public_key: str | None
    registry_metadata: RegistryMetadata
    registry_db_path: str


def build_registry_config() -> RegistryConfig:
    registry_url = os.environ.get("P4P_REGISTRY_URL", "").strip()
    mirror_upstreams = load_mirror_upstreams()
    explicit_trusted = load_mirror_trusted_upstreams()
    mirror_trusted_upstreams = resolve_trusted_mirror_upstreams(
        configured_upstreams=mirror_upstreams,
        explicit_trusted_upstreams=explicit_trusted,
    )
    registry_private_key = load_registry_private_key()
    return RegistryConfig(
        registry_url=registry_url,
        registry_admin_token=os.environ.get("P4P_REGISTRY_ADMIN_TOKEN", "").strip(),
        backup_registries=load_backup_registries(),
        mirror_upstreams=mirror_upstreams,
        mirror_trusted_upstreams=mirror_trusted_upstreams,
        trusted_mirror_upstream_urls={
            normalized_registry_url(upstream.url) for upstream in mirror_trusted_upstreams
        },
        mirror_discovery_policy=resolve_mirror_discovery_policy(
            configured_upstreams=mirror_upstreams,
            trusted_upstreams=mirror_trusted_upstreams,
        ),
        registry_source_reexport_policy=resolve_registry_source_reexport_policy(),
        curated_index_promotion_policy=resolve_curated_index_promotion_policy(),
        mirror_sync_interval_seconds=max(
            0,
            int(os.environ.get("P4P_MIRROR_SYNC_INTERVAL_SECONDS", "60")),
        ),
        mirror_source_ttl_seconds=max(
            1,
            int(os.environ.get("P4P_MIRROR_SOURCE_TTL_SECONDS", "600")),
        ),
        registry_private_key=registry_private_key,
        registry_public_key=(
            public_key_from_private(registry_private_key) if registry_private_key else None
        ),
        registry_metadata=load_registry_metadata(),
        registry_db_path=(
            os.environ.get("P4P_REGISTRY_DB_PATH", ":memory:").strip() or ":memory:"
        ),
    )


__all__ = [
    "RegistryConfig",
    "build_registry_config",
    "load_backup_registries",
    "load_mirror_trusted_upstreams",
    "load_mirror_upstream_list",
    "load_mirror_upstreams",
    "load_registry_metadata",
    "load_registry_private_key",
    "resolve_curated_index_promotion_policy",
    "resolve_mirror_discovery_policy",
    "resolve_registry_source_reexport_policy",
    "resolve_trusted_mirror_upstreams",
]
