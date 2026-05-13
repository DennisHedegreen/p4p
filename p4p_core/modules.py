from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


MODULES_ROOT = Path(__file__).resolve().parents[1] / "modules"
ALLOWED_DECLARATION_READINESS = {"planned", "test", "live"}


def _localized_text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        normalized: dict[str, str] = {}
        for key, raw_text in value.items():
            locale_id = str(key or "").strip().lower()
            text = str(raw_text or "").strip()
            if locale_id and text:
                normalized[locale_id] = text
        for candidate in ("en", "da"):
            text = normalized.get(candidate, "")
            if text:
                return text
        return next((text for text in normalized.values() if text), "")
    return ""


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    name: str
    description: str
    website: str
    public_key: str | None
    contact: str | None
    module_ids: tuple[str, ...]
    supported_lanes: tuple[str, ...]
    status: str
    signature: str | None
    source_path: Path = field(repr=False)
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, source_path: Path) -> "ProviderManifest":
        return cls(
            provider_id=str(payload["provider_id"]),
            name=_localized_text_from_value(payload.get("name")),
            description=_localized_text_from_value(payload.get("description")),
            website=str(payload["website"]),
            public_key=str(payload["public_key"]) if payload.get("public_key") is not None else None,
            contact=str(payload["contact"]) if payload.get("contact") is not None else None,
            module_ids=tuple(str(value) for value in payload.get("modules", [])),
            supported_lanes=tuple(str(value) for value in payload.get("supported_lanes", [])),
            status=str(payload.get("status", "")),
            signature=str(payload["signature"]) if payload.get("signature") is not None else None,
            source_path=source_path,
            raw=payload,
        )

    def contains_module(self, module_id: str) -> bool:
        return module_id in self.module_ids

    def supports_lane(self, lane: str) -> bool:
        return lane in self.supported_lanes


@dataclass(frozen=True)
class ModuleManifest:
    module_id: str
    provider_id: str
    version: str
    lane: str
    visibility: str
    blocking_policy: str
    capabilities: tuple[str, ...]
    data_access: tuple[str, ...]
    input_events: tuple[str, ...]
    output_events: tuple[str, ...]
    failure_modes: tuple[str, ...]
    suggested_fallbacks: dict[str, tuple[str, ...]]
    status: str
    description: str
    readiness: str
    operator_status: str
    source_path: Path = field(repr=False)
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, source_path: Path) -> "ModuleManifest":
        public_catalog = payload.get("public_catalog", {})
        readiness = str(public_catalog.get("readiness") or payload.get("status") or "planned").strip().lower()
        if readiness not in ALLOWED_DECLARATION_READINESS:
            readiness = "planned"

        raw_fallbacks = payload.get("suggested_fallbacks") or {}
        suggested_fallbacks: dict[str, tuple[str, ...]] = {}
        for event_name, module_ids in raw_fallbacks.items():
            suggested_fallbacks[str(event_name)] = tuple(
                str(module_id).strip() for module_id in module_ids if str(module_id).strip()
            )

        return cls(
            module_id=str(payload["module_id"]),
            provider_id=str(payload["provider_id"]),
            version=str(payload["version"]),
            lane=str(payload["lane"]),
            visibility=str(payload["visibility"]),
            blocking_policy=str(payload["blocking_policy"]),
            capabilities=tuple(str(value) for value in payload.get("capabilities", [])),
            data_access=tuple(str(value) for value in payload.get("data_access", [])),
            input_events=tuple(str(value) for value in payload.get("input_events", [])),
            output_events=tuple(str(value) for value in payload.get("output_events", [])),
            failure_modes=tuple(str(value) for value in payload.get("failure_modes", [])),
            suggested_fallbacks=suggested_fallbacks,
            status=str(payload.get("status", "")),
            description=_localized_text_from_value(payload.get("description")),
            readiness=readiness,
            operator_status=_localized_text_from_value(public_catalog.get("operator_status")) or "not enabled",
            source_path=source_path,
            raw=payload,
        )

    def is_public(self) -> bool:
        return self.visibility == "public"

    def fallbacks_for(self, event_name: str) -> tuple[str, ...]:
        return self.suggested_fallbacks.get(event_name, ())

    def accepts_event(self, event_name: str) -> bool:
        return event_name in self.input_events

    def emits_event(self, event_name: str) -> bool:
        return event_name in self.output_events

    def declares_failure_mode(self, event_name: str) -> bool:
        return event_name in self.failure_modes

    def node_declaration(self, *, status: str = "active") -> dict[str, object]:
        declaration: dict[str, object] = {
            "module_id": self.module_id,
            "provider_id": self.provider_id,
            "version": self.version,
            "status": status,
            "visibility": self.visibility,
            "readiness": self.readiness,
            "capabilities": list(self.capabilities),
            "data_access": list(self.data_access),
        }
        customer_notice = _localized_text_from_value(self.raw.get("public_catalog", {}).get("customer_notice"))
        if customer_notice:
            declaration["customer_notice"] = customer_notice
        return declaration


@dataclass(frozen=True)
class ResolvedModules:
    manifests: tuple[ModuleManifest, ...]
    _by_id: dict[str, ModuleManifest] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_id", {manifest.module_id: manifest for manifest in self.manifests})

    def __contains__(self, module_id: str) -> bool:
        return module_id in self._by_id

    def contains(self, module_id: str) -> bool:
        return module_id in self

    def get(self, module_id: str) -> ModuleManifest | None:
        return self._by_id.get(module_id)

    @property
    def module_ids(self) -> tuple[str, ...]:
        return tuple(manifest.module_id for manifest in self.manifests)

    def public_module_ids(self) -> list[str]:
        return [manifest.module_id for manifest in self.manifests if manifest.is_public()]

    def declarations(self, *, status: str = "active") -> list[dict[str, object]]:
        return [manifest.node_declaration(status=status) for manifest in self.manifests]

    def public_declarations(self, *, status: str = "active") -> list[dict[str, object]]:
        return [manifest.node_declaration(status=status) for manifest in self.manifests if manifest.is_public()]


@lru_cache(maxsize=1)
def load_reference_provider_catalog() -> dict[str, ProviderManifest]:
    manifests: dict[str, ProviderManifest] = {}
    for provider_path in sorted(MODULES_ROOT.glob("*/provider.json")):
        payload = json.loads(provider_path.read_text(encoding="utf-8"))
        manifest = ProviderManifest.from_payload(payload, source_path=provider_path)
        existing = manifests.get(manifest.provider_id)
        if existing is None:
            manifests[manifest.provider_id] = manifest
            continue
        if existing.raw != manifest.raw:
            raise ValueError(
                "Provider manifest drift for "
                f"{manifest.provider_id}: {existing.source_path} != {provider_path}"
            )
    return manifests


def validate_reference_manifest_catalog(
    modules: dict[str, ModuleManifest],
    providers: dict[str, ProviderManifest],
) -> None:
    known_module_ids = set(modules)
    for provider in providers.values():
        unknown_module_ids = sorted(module_id for module_id in provider.module_ids if module_id not in known_module_ids)
        if unknown_module_ids:
            missing = ", ".join(unknown_module_ids)
            raise ValueError(f"Provider {provider.provider_id} declares unknown modules: {missing}")
        for module_id in provider.module_ids:
            module = modules[module_id]
            if module.provider_id != provider.provider_id:
                raise ValueError(
                    f"Provider {provider.provider_id} claims module {module_id}, "
                    f"but the module manifest points at provider {module.provider_id}"
                )

    for module in modules.values():
        provider = providers.get(module.provider_id)
        if provider is None:
            raise ValueError(f"Module {module.module_id} references unknown provider {module.provider_id}")
        if not provider.contains_module(module.module_id):
            raise ValueError(
                f"Module {module.module_id} is missing from provider manifest {provider.provider_id}"
            )
        if not provider.supports_lane(module.lane):
            raise ValueError(
                f"Provider {provider.provider_id} does not declare support for module lane {module.lane}"
            )


@lru_cache(maxsize=1)
def load_reference_module_catalog() -> dict[str, ModuleManifest]:
    manifests: dict[str, ModuleManifest] = {}
    for manifest_path in sorted(MODULES_ROOT.glob("*/module.json")):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ModuleManifest.from_payload(payload, source_path=manifest_path)
        if manifest.module_id in manifests:
            raise ValueError(f"Duplicate module manifest: {manifest.module_id}")
        manifests[manifest.module_id] = manifest
    validate_reference_manifest_catalog(manifests, load_reference_provider_catalog())
    return manifests


def normalize_module_ids(module_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_module_id in module_ids:
        module_id = raw_module_id.strip()
        if not module_id or module_id in seen:
            continue
        seen.add(module_id)
        normalized.append(module_id)
    return normalized


def resolve_enabled_modules(module_ids: list[str], *, strict: bool = True) -> ResolvedModules:
    catalog = load_reference_module_catalog()
    normalized: list[str] = []
    for module_id in normalize_module_ids(module_ids):
        if module_id not in catalog:
            if strict:
                known = ", ".join(sorted(catalog))
                raise ValueError(f"Unknown P4P module id: {module_id}. Known reference modules: {known}")
            continue
        normalized.append(module_id)
    return ResolvedModules(tuple(catalog[module_id] for module_id in normalized))


__all__ = [
    "ModuleManifest",
    "ProviderManifest",
    "ResolvedModules",
    "load_reference_provider_catalog",
    "load_reference_module_catalog",
    "normalize_module_ids",
    "resolve_enabled_modules",
    "validate_reference_manifest_catalog",
]
