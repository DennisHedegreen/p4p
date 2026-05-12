from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .constants import (
    CATEGORY_PATTERN,
    NODE_ID_PATTERN,
    PROTOCOL_VERSION,
    DelegationCapability,
    DelegationRole,
    ManifestKeyStatus,
    OrderMode,
    OrderStatus,
)
from .money import CURRENCY_CODE_PATTERN, normalize_currency_code
from .time import utc_now


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class NodeDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_public_key: str = Field(pattern=r"^ed25519:")
    issued_at: str
    expires_at: str | None = None
    role: DelegationRole = Field(default="primary")
    capabilities: list[DelegationCapability] = Field(default_factory=lambda: ["announce", "heartbeat"])
    signature: str = Field(pattern=r"^ed25519:")

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[DelegationCapability]) -> list[DelegationCapability]:
        normalized: list[DelegationCapability] = []
        seen: set[DelegationCapability] = set()
        for value in values:
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        if not normalized:
            raise ValueError("delegation capabilities must not be empty")
        return normalized


class NodeManifestKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_public_key: str = Field(pattern=r"^ed25519:")
    role: DelegationRole = Field(default="primary")
    capabilities: list[DelegationCapability] = Field(default_factory=lambda: ["announce", "heartbeat"])
    status: ManifestKeyStatus = Field(default="active")
    expires_at: str | None = None

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[DelegationCapability]) -> list[DelegationCapability]:
        normalized: list[DelegationCapability] = []
        seen: set[DelegationCapability] = set()
        for value in values:
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        if not normalized:
            raise ValueError("manifest key capabilities must not be empty")
        return normalized


class NodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    root_public_key: str = Field(pattern=r"^ed25519:")
    manifest_version: int = Field(ge=1)
    issued_at: str
    keys: list[NodeManifestKey] = Field(min_length=1)
    signature: str = Field(pattern=r"^ed25519:")

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, values: list[NodeManifestKey]) -> list[NodeManifestKey]:
        seen: set[str] = set()
        for value in values:
            if value.node_public_key in seen:
                raise ValueError("manifest keys must be unique by node_public_key")
            seen.add(value.node_public_key)
        return values


class NodeRootRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    previous_root_public_key: str = Field(pattern=r"^ed25519:")
    next_root_public_key: str = Field(pattern=r"^ed25519:")
    rotated_at: str
    signature: str = Field(pattern=r"^ed25519:")


class NodeManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: NodeManifest
    root_rotation: NodeRootRotation | None = None


class NodeDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    name: str = Field(min_length=1)
    location: Location
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str = Field(min_length=1)
    categories: list[str] = Field(default_factory=list)
    endpoint: HttpUrl
    open: bool
    order_mode: OrderMode = Field(default="disabled")
    modules: list[str] = Field(default_factory=list)
    node_public_key: str | None = None
    delegation: NodeDelegation | None = None
    signed_at: str | None = None
    signature: str | None = None
    protocol_version: str = Field(default=PROTOCOL_VERSION)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme == "https":
            return value
        if value.scheme == "http" and value.host in {"127.0.0.1", "localhost"}:
            return value
        raise ValueError("endpoint must use https unless it is loopback http")

    @field_validator("node_public_key")
    @classmethod
    def validate_public_key(cls, value: str | None) -> str | None:
        if value is None or value.startswith("ed25519:"):
            return value
        raise ValueError("node_public_key must start with ed25519:")

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, value: str | None) -> str | None:
        if value is None or value.startswith("ed25519:"):
            return value
        raise ValueError("signature must start with ed25519:")

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(CATEGORY_PATTERN, value):
                raise ValueError("categories must use lowercase canonical tokens")
        return values


class NodeModuleDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(pattern=r"^[a-z0-9]+(?:\.[a-z0-9-]+)+$")
    provider_id: str = Field(pattern=r"^[a-z0-9]+(?:\.[a-z0-9-]+)+$")
    version: str = Field(min_length=1)
    status: Literal["active", "fallback_only", "disabled"] = Field(default="active")
    visibility: Literal["public", "operator_only", "trust_only"]
    readiness: Literal["planned", "test", "live"]
    capabilities: list[str] = Field(min_length=1)
    data_access: list[str] = Field(default_factory=list)
    customer_notice: str | None = None


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=CATEGORY_PATTERN)
    name: str = Field(min_length=1)
    description: str = ""
    price: int = Field(ge=0, description="Integer minor units in the menu currency")
    category: str = Field(pattern=CATEGORY_PATTERN)
    active: bool = True
    image_url: str | None = Field(
        default=None,
        description="Optional item image URL or same-origin path supplied by the node/operator.",
    )

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if any(character.isspace() for character in normalized):
            raise ValueError("image_url must not contain whitespace")
        if normalized.startswith(("https://", "http://", "/")):
            return normalized
        raise ValueError("image_url must be http(s) or a same-origin absolute path")


class Menu(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(default="DKK", pattern=CURRENCY_CODE_PATTERN)
    updated_at: datetime
    items: list[MenuItem]

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return normalize_currency_code(str(value))


class MenuUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MenuItem] = Field(min_length=1)


class MenuImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    source_name: str = ""


class MenuImportPreviewCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: MenuItem
    source_line: str = Field(min_length=1)
    source_price_text: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] = Field(default="medium")


class MenuImportPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["ocr_text", "ocr_image"] = Field(default="ocr_text")
    source_name: str = ""
    parsed_at: datetime
    candidates: list[MenuImportPreviewCandidate]
    ignored_lines: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extracted_text: str | None = None
    ocr_line_count: int | None = None


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=CATEGORY_PATTERN)
    quantity: int = Field(ge=1)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=1)
    customer_contact: str = Field(min_length=1)
    fulfillment: str = Field(default="pickup", pattern=r"^pickup$")
    items: list[OrderItem] = Field(min_length=1)
    note: str = ""
    client_version: str = Field(min_length=1)


class OrderAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool = True
    order_id: str
    estimated_ready: datetime
    message: str


class OrderRejected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool = False
    reason: str
    message: str


class StoredOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    customer_name: str
    customer_contact: str
    fulfillment: str
    items: list[OrderItem]
    note: str
    client_version: str
    status: OrderStatus
    payment_method: str = "pay_at_pickup"
    status_message: str | None = None
    requested_at: datetime
    updated_at: datetime
    estimated_ready: datetime | None = None


class PublicOrderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    status: OrderStatus
    status_message: str | None = None
    fulfillment: str
    payment_method: str
    requested_at: datetime
    updated_at: datetime
    estimated_ready: datetime | None = None
    customer_notice: str = (
        "Keep your order id private. This prototype status lookup does not expose "
        "customer contact data or operator-only order notes."
    )


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    status_message: str | None = None
    estimated_ready_minutes: int | None = Field(default=None, ge=0, le=240)


class ModuleResultEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    source_module: str = Field(pattern=r"^[a-z0-9]+(?:\.[a-z0-9-]+)+$")
    order_id: str | None = None
    action_id: str = Field(min_length=1)
    idempotency_key: str | None = None
    outcome: Literal[
        "SUCCESS",
        "FAILED_RETRYABLE",
        "FAILED_PERMANENT",
        "TIMEOUT_UNKNOWN",
        "UNAVAILABLE",
        "NEEDS_INPUT",
        "NEEDS_HUMAN",
    ]
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]+$")
    severity: Literal["low", "medium", "high", "critical"]
    retryable: bool
    side_effect_state: Literal["none", "confirmed", "unknown"]
    timestamp: datetime
    metadata: dict[str, Any] | None = None


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    open: bool
    signed_at: str | None = None
    signature: str | None = None

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, value: str | None) -> str | None:
        if value is None or value.startswith("ed25519:"):
            return value
        raise ValueError("signature must start with ed25519:")


class AnnounceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)


class RegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: int = Field(ge=0)
    url: HttpUrl


@dataclass
class RegistrationSnapshot:
    configured_registries: list[str]
    stale_after_seconds: int
    registered_registries: list[str] = field(default_factory=list)
    failed_registries: dict[str, str] = field(default_factory=dict)
    last_cycle_finished_at: datetime | None = None

    def ready(self) -> bool:
        if not self.registered_registries or self.last_cycle_finished_at is None:
            return False
        return utc_now() - self.last_cycle_finished_at <= timedelta(seconds=self.stale_after_seconds)

    def update(self, registered: list[str], failed: dict[str, str]) -> None:
        self.registered_registries = registered
        self.failed_registries = failed
        self.last_cycle_finished_at = utc_now()
