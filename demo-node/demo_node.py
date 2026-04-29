from __future__ import annotations

import asyncio
import os
import re
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_identity import load_or_create_private_key, public_key_from_private, sign_payload


PROTOCOL_VERSION = "0.1"
NODE_BASE_URL = os.environ.get("P4P_NODE_BASE_URL", "http://127.0.0.1:8001")
HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("P4P_HEARTBEAT_INTERVAL_SECONDS", "60"))
# A node is only "ready" while the latest successful registry cycle is still current.
READINESS_STALE_AFTER_SECONDS = HEARTBEAT_INTERVAL_SECONDS + 5
ORDER_MODES = ("disabled", "menu_only", "test", "live")
REFERENCE_MODULES = ("p4p.payment.cash",)
OPERATOR_HTML = Path(__file__).resolve().parent / "operator.html"
OrderMode = Literal["disabled", "menu_only", "test", "live"]
DelegationRole = Literal["primary", "backup"]
DelegationCapability = Literal["announce", "heartbeat"]
ManifestKeyStatus = Literal["active", "revoked"]
NODE_ID_PATTERN = r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3,}$"
CATEGORY_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def load_node_private_key() -> str:
    env_private_key = os.environ.get("P4P_NODE_PRIVATE_KEY", "").strip()
    if env_private_key:
        return env_private_key
    return load_or_create_private_key(env_path("P4P_NODE_KEY_FILE"))


def load_root_private_key() -> str | None:
    env_private_key = os.environ.get("P4P_NODE_ROOT_PRIVATE_KEY", "").strip()
    if env_private_key:
        return env_private_key
    root_path = env_path("P4P_NODE_ROOT_KEY_FILE")
    if root_path is None:
        return None
    return load_or_create_private_key(root_path)


def load_registry_urls() -> list[str]:
    raw = os.environ.get("P4P_REGISTRY_URLS")
    if raw:
        values = [value.strip() for value in raw.split(",") if value.strip()]
    else:
        values = [env_str("P4P_REGISTRY_URL", "http://127.0.0.1:8000")]

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


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

    node_id: str = Field(pattern=NODE_ID_PATTERN)
    root_public_key: str = Field(pattern=r"^ed25519:")
    manifest_version: int = Field(ge=1)
    issued_at: str
    keys: list[NodeManifestKey] = Field(min_length=1)
    signature: str = Field(pattern=r"^ed25519:")


class NodeRootRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(pattern=NODE_ID_PATTERN)
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

    node_id: str = Field(pattern=NODE_ID_PATTERN)
    name: str
    location: Location
    country: str
    city: str
    categories: list[str]
    endpoint: HttpUrl
    open: bool
    order_mode: OrderMode
    modules: list[str]
    node_public_key: str | None = None
    delegation: NodeDelegation | None = None
    signed_at: str | None = None
    signature: str | None = None
    protocol_version: str = PROTOCOL_VERSION

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme == "https":
            return value
        if value.scheme == "http" and value.host in {"127.0.0.1", "localhost"}:
            return value
        raise ValueError(
            "endpoint must use https unless it is loopback http for local reference development"
        )

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
                raise ValueError(
                    "categories must use lowercase canonical tokens matching ^[a-z0-9][a-z0-9-]*$"
                )
        return values


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    price: int = Field(ge=0)
    category: str


class Menu(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = "DKK"
    updated_at: datetime
    items: list[MenuItem]


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    quantity: int = Field(ge=1)


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str
    customer_contact: str
    fulfillment: str = Field(pattern=r"^pickup$")
    items: list[OrderItem]
    note: str
    client_version: str


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


class OperatorStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool
    order_mode: OrderMode
    modules: list[str] = Field(default_factory=list)

    @field_validator("modules")
    @classmethod
    def normalize_modules(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            module_id = value.strip()
            if not module_id or module_id in seen:
                continue
            normalized.append(module_id)
            seen.add(module_id)
        return normalized


@dataclass
class RegistrationSnapshot:
    configured_registries: list[str]
    registered_registries: list[str] = field(default_factory=list)
    failed_registries: dict[str, str] = field(default_factory=dict)
    last_cycle_finished_at: datetime | None = None

    def ready(self) -> bool:
        if not self.registered_registries or self.last_cycle_finished_at is None:
            return False
        return utc_now() - self.last_cycle_finished_at <= timedelta(
            seconds=READINESS_STALE_AFTER_SECONDS
        )

    def update(self, registered: list[str], failed: dict[str, str]) -> None:
        self.registered_registries = registered
        self.failed_registries = failed
        self.last_cycle_finished_at = utc_now()


REGISTRY_URLS = load_registry_urls()
NODE_PRIVATE_KEY = load_node_private_key()
NODE_PUBLIC_KEY = public_key_from_private(NODE_PRIVATE_KEY)
ROOT_PRIVATE_KEY = load_root_private_key()
ROOT_PUBLIC_KEY = public_key_from_private(ROOT_PRIVATE_KEY) if ROOT_PRIVATE_KEY else None
OPERATOR_ENABLED = env_str("P4P_OPERATOR_ENABLED", "true").lower() == "true"
NODE = NodeDescriptor(
    node_id=env_str("P4P_NODE_ID", "dk-brondby-test-001"),
    name=env_str("P4P_NODE_NAME", "P4P Test Pizzeria"),
    location=Location(
        lat=env_float("P4P_NODE_LAT", 55.6517),
        lng=env_float("P4P_NODE_LNG", 12.4126),
    ),
    country=env_str("P4P_NODE_COUNTRY", "DK"),
    city=env_str("P4P_NODE_CITY", "Brondby"),
    categories=env_list("P4P_NODE_CATEGORIES", ["pizza", "kebab"]),
    endpoint=f"{NODE_BASE_URL.rstrip('/')}/p4p",
    open=env_str("P4P_NODE_OPEN", "true").lower() == "true",
    order_mode=env_str("P4P_NODE_ORDER_MODE", "test"),
    modules=env_list("P4P_NODE_MODULES", []),
    node_public_key=NODE_PUBLIC_KEY,
)


def delegation_payload(*, delegation: NodeDelegation) -> dict[str, Any]:
    return {
        "node_id": NODE.node_id,
        "node_public_key": NODE_PUBLIC_KEY,
        "root_public_key": delegation.root_public_key,
        "issued_at": delegation.issued_at,
        "expires_at": delegation.expires_at,
        "role": delegation.role,
        "capabilities": delegation.capabilities,
    }


def build_node_delegation(
    *,
    root_private_key: str | None = None,
    root_public_key: str | None = None,
    issued_at: str | None = None,
    expires_at: str | None = None,
    role: DelegationRole | None = None,
    capabilities: list[DelegationCapability] | None = None,
) -> NodeDelegation | None:
    effective_root_private_key = root_private_key or ROOT_PRIVATE_KEY
    effective_root_public_key = root_public_key or ROOT_PUBLIC_KEY

    if not effective_root_private_key or not effective_root_public_key:
        return None

    delegation_data: dict[str, Any] = {
        "root_public_key": effective_root_public_key,
        "issued_at": issued_at or (os.environ.get("P4P_NODE_DELEGATION_ISSUED_AT", "").strip() or utc_now().isoformat()),
        "expires_at": expires_at if expires_at is not None else (os.environ.get("P4P_NODE_DELEGATION_EXPIRES_AT", "").strip() or None),
        "role": role or env_str("P4P_NODE_DELEGATION_ROLE", "primary"),
        "capabilities": capabilities or env_list(
            "P4P_NODE_DELEGATION_CAPABILITIES",
            ["announce", "heartbeat"],
        ),
    }
    unsigned_delegation = NodeDelegation(signature="ed25519:placeholder", **delegation_data)
    delegation_data["signature"] = sign_payload(
        delegation_payload(delegation=unsigned_delegation),
        effective_root_private_key,
    )
    return NodeDelegation(**delegation_data)


NODE.delegation = build_node_delegation()


def node_manifest_payload(*, manifest: NodeManifest) -> dict[str, Any]:
    return {
        "node_id": manifest.node_id,
        "root_public_key": manifest.root_public_key,
        "manifest_version": manifest.manifest_version,
        "issued_at": manifest.issued_at,
        "keys": [entry.model_dump(mode="json", exclude_none=True) for entry in manifest.keys],
    }


def root_rotation_payload(*, rotation: NodeRootRotation) -> dict[str, Any]:
    return {
        "node_id": rotation.node_id,
        "previous_root_public_key": rotation.previous_root_public_key,
        "next_root_public_key": rotation.next_root_public_key,
        "rotated_at": rotation.rotated_at,
    }


def build_node_manifest(
    *,
    root_private_key: str | None = None,
    root_public_key: str | None = None,
    node_public_key: str | None = None,
    manifest_version: int | None = None,
    issued_at: str | None = None,
    key_status: ManifestKeyStatus | None = None,
    key_expires_at: str | None = None,
    role: DelegationRole | None = None,
    capabilities: list[DelegationCapability] | None = None,
) -> NodeManifest | None:
    effective_root_private_key = root_private_key or ROOT_PRIVATE_KEY
    effective_root_public_key = root_public_key or ROOT_PUBLIC_KEY
    effective_node_public_key = node_public_key or NODE_PUBLIC_KEY

    if not effective_root_private_key or not effective_root_public_key:
        return None

    manifest_key = NodeManifestKey(
        node_public_key=effective_node_public_key,
        role=role or (NODE.delegation.role if NODE.delegation else "primary"),
        capabilities=capabilities or (
            NODE.delegation.capabilities if NODE.delegation else ["announce", "heartbeat"]
        ),
        status=key_status or env_str("P4P_NODE_MANIFEST_KEY_STATUS", "active"),
        expires_at=(
            key_expires_at
            if key_expires_at is not None
            else (os.environ.get("P4P_NODE_MANIFEST_KEY_EXPIRES_AT", "").strip() or None)
        )
        or (NODE.delegation.expires_at if NODE.delegation else None),
    )
    manifest_data: dict[str, Any] = {
        "node_id": NODE.node_id,
        "root_public_key": effective_root_public_key,
        "manifest_version": (
            manifest_version
            if manifest_version is not None
            else int(env_str("P4P_NODE_MANIFEST_VERSION", "1"))
        ),
        "issued_at": (
            issued_at
            if issued_at is not None
            else (
                os.environ.get("P4P_NODE_MANIFEST_ISSUED_AT", "").strip()
                or (NODE.delegation.issued_at if NODE.delegation else utc_now().isoformat())
            )
        ),
        "keys": [manifest_key.model_dump(mode="json", exclude_none=True)],
    }
    unsigned_manifest = NodeManifest(signature="ed25519:placeholder", **manifest_data)
    manifest_data["signature"] = sign_payload(
        node_manifest_payload(manifest=unsigned_manifest),
        effective_root_private_key,
    )
    return NodeManifest(**manifest_data)


def build_root_rotation(
    *,
    previous_root_private_key: str,
    previous_root_public_key: str,
    next_root_public_key: str,
    rotated_at: str | None = None,
) -> NodeRootRotation:
    rotation_data: dict[str, Any] = {
        "node_id": NODE.node_id,
        "previous_root_public_key": previous_root_public_key,
        "next_root_public_key": next_root_public_key,
        "rotated_at": rotated_at or utc_now().isoformat(),
    }
    unsigned_rotation = NodeRootRotation(signature="ed25519:placeholder", **rotation_data)
    rotation_data["signature"] = sign_payload(
        root_rotation_payload(rotation=unsigned_rotation),
        previous_root_private_key,
    )
    return NodeRootRotation(**rotation_data)


NODE_MANIFEST = build_node_manifest()


def signed_node_manifest_request(
    *,
    manifest: NodeManifest | None = None,
    root_rotation: NodeRootRotation | None = None,
) -> dict[str, Any] | None:
    effective_manifest = manifest or NODE_MANIFEST
    if effective_manifest is None:
        return None
    payload = NodeManifestRequest(manifest=effective_manifest, root_rotation=root_rotation)
    return payload.model_dump(mode="json", exclude_none=True)

MENU = Menu(
    updated_at=utc_now(),
    items=[
        MenuItem(
            id=env_str("P4P_MENU_ITEM_1_ID", "margherita"),
            name=env_str("P4P_MENU_ITEM_1_NAME", "Margherita"),
            description=env_str("P4P_MENU_ITEM_1_DESCRIPTION", "Tomat, mozzarella, oregano"),
            price=int(env_str("P4P_MENU_ITEM_1_PRICE", "75")),
            category="pizza",
        ),
        MenuItem(
            id=env_str("P4P_MENU_ITEM_2_ID", "vesuvio"),
            name=env_str("P4P_MENU_ITEM_2_NAME", "Vesuvio"),
            description=env_str("P4P_MENU_ITEM_2_DESCRIPTION", "Tomat, ost, skinke"),
            price=int(env_str("P4P_MENU_ITEM_2_PRICE", "85")),
            category="pizza",
        ),
    ],
)

REGISTRATION = RegistrationSnapshot(configured_registries=REGISTRY_URLS.copy())

app = FastAPI(
    title="P4P Demo Node",
    version=PROTOCOL_VERSION,
    summary="Reference restaurant node for the P4P v0.1 protocol.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_heartbeat_task: asyncio.Task[None] | None = None


def node_accepts_orders() -> bool:
    return NODE.order_mode in {"test", "live"}


def sign_node_announcement() -> dict[str, Any]:
    NODE.node_public_key = NODE_PUBLIC_KEY
    NODE.signed_at = utc_now().isoformat()
    NODE.signature = None
    payload = NODE.model_dump(mode="json", exclude_none=True)
    NODE.signature = sign_payload(payload, NODE_PRIVATE_KEY)
    return NODE.model_dump(mode="json", exclude_none=True)


def signed_heartbeat_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": NODE.node_id,
        "open": NODE.open,
        "signed_at": utc_now().isoformat(),
    }
    payload["signature"] = sign_payload(payload, NODE_PRIVATE_KEY)
    return payload


def registration_payload() -> dict[str, Any]:
    return {
        "ready": REGISTRATION.ready(),
        "configured_registries": REGISTRATION.configured_registries,
        "registered_registries": REGISTRATION.registered_registries,
        "failed_registries": REGISTRATION.failed_registries,
        "last_cycle_finished_at": (
            REGISTRATION.last_cycle_finished_at.isoformat()
            if REGISTRATION.last_cycle_finished_at
            else None
        ),
    }


def operator_state_payload() -> dict[str, Any]:
    return {
        "node": NODE.model_dump(mode="json"),
        "accepts_orders": node_accepts_orders(),
        "identity": {
            "key_type": "ed25519",
            "node_public_key": NODE_PUBLIC_KEY,
            "root_public_key": ROOT_PUBLIC_KEY,
            "delegation_role": NODE.delegation.role if NODE.delegation else None,
            "manifest_version": NODE_MANIFEST.manifest_version if NODE_MANIFEST else None,
            "manifest_key_status": NODE_MANIFEST.keys[0].status if NODE_MANIFEST else None,
            "signed_announcements": True,
        },
        "available_order_modes": list(ORDER_MODES),
        "available_modules": sorted(set(REFERENCE_MODULES).union(NODE.modules)),
        "registry": registration_payload(),
    }


def require_operator_enabled() -> None:
    if not OPERATOR_ENABLED:
        raise HTTPException(status_code=404, detail="operator disabled")


def describe_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text.strip()
        return f"{exc.response.status_code} {detail}".strip()
    return str(exc)


async def announce_registry(client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(
        f"{registry_url.rstrip('/')}/announce",
        json=sign_node_announcement(),
    )
    response.raise_for_status()


async def publish_manifest_registry(client: httpx.AsyncClient, registry_url: str) -> None:
    payload = signed_node_manifest_request()
    if payload is None:
        return
    response = await client.post(
        f"{registry_url.rstrip('/')}/node-manifest",
        json=payload,
    )
    if response.status_code == status.HTTP_409_CONFLICT:
        return
    response.raise_for_status()


async def heartbeat_registry(client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(
        f"{registry_url.rstrip('/')}/heartbeat",
        json=signed_heartbeat_payload(),
    )
    if response.status_code == status.HTTP_404_NOT_FOUND:
        await publish_manifest_registry(client, registry_url)
        await announce_registry(client, registry_url)
        response = await client.post(
            f"{registry_url.rstrip('/')}/heartbeat",
            json=signed_heartbeat_payload(),
        )
    response.raise_for_status()


async def run_registry_cycle(*, force_announce: bool) -> None:
    registered: list[str] = []
    failed: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for registry_url in REGISTRY_URLS:
            try:
                if force_announce:
                    await publish_manifest_registry(client, registry_url)
                    await announce_registry(client, registry_url)
                await heartbeat_registry(client, registry_url)
            except Exception as exc:
                failed[registry_url] = describe_http_error(exc)
                continue
            registered.append(registry_url)

    REGISTRATION.update(registered, failed)


async def heartbeat_loop() -> None:
    while True:
        try:
            await run_registry_cycle(force_announce=False)
        except Exception as exc:
            print(f"[p4p-demo-node] heartbeat cycle failed: {exc}")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup() -> None:
    global _heartbeat_task

    try:
        await run_registry_cycle(force_announce=True)
        print(
            f"[p4p-demo-node] announced {NODE.node_id} to registries: "
            f"{', '.join(REGISTRATION.registered_registries) or 'none'}"
        )
    except Exception as exc:
        print(f"[p4p-demo-node] startup cycle failed: {exc}")

    _heartbeat_task = asyncio.create_task(heartbeat_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    global _heartbeat_task

    if _heartbeat_task is None:
        return
    _heartbeat_task.cancel()
    with suppress(asyncio.CancelledError):
        await _heartbeat_task


@app.get("/health")
def health(response: Response) -> dict[str, Any]:
    ready = REGISTRATION.ready()
    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "protocol_version": PROTOCOL_VERSION,
        "node_id": NODE.node_id,
        "order_mode": NODE.order_mode,
        "accepts_orders": node_accepts_orders(),
        "node_public_key": NODE_PUBLIC_KEY,
        "root_public_key": ROOT_PUBLIC_KEY,
        "delegation_role": NODE.delegation.role if NODE.delegation else None,
        "manifest_version": NODE_MANIFEST.manifest_version if NODE_MANIFEST else None,
        "manifest_key_status": NODE_MANIFEST.keys[0].status if NODE_MANIFEST else None,
        **registration_payload(),
    }


@app.get("/operator", response_class=HTMLResponse)
def operator() -> str:
    require_operator_enabled()
    return OPERATOR_HTML.read_text(encoding="utf-8")


@app.get("/operator/state")
def operator_state() -> dict[str, Any]:
    require_operator_enabled()
    return operator_state_payload()


@app.post("/operator/state")
async def operator_update_state(payload: OperatorStateUpdate) -> dict[str, Any]:
    require_operator_enabled()
    NODE.open = payload.open
    NODE.order_mode = payload.order_mode
    NODE.modules = payload.modules
    await run_registry_cycle(force_announce=True)
    return operator_state_payload()


@app.post("/operator/reannounce")
async def operator_reannounce() -> dict[str, Any]:
    require_operator_enabled()
    await run_registry_cycle(force_announce=True)
    return operator_state_payload()


@app.get("/p4p/menu", response_model=Menu)
def menu() -> Menu:
    return MENU


@app.post("/p4p/order", response_model=OrderAccepted | OrderRejected)
def order(payload: OrderRequest) -> OrderAccepted | OrderRejected:
    if not NODE.open:
        return OrderRejected(reason="closed", message="Vi lukker om 5 minutter.")
    if not node_accepts_orders():
        return OrderRejected(
            reason="orders_disabled",
            message="Denne node modtager ikke ordre endnu.",
        )
    ready_at = utc_now() + timedelta(minutes=20)
    print("[p4p-demo-node] order received:", payload.model_dump())
    return OrderAccepted(
        order_id=f"test-{utc_now().strftime('%Y-%m-%d-%H%M%S')}",
        estimated_ready=ready_at,
        message="Bestilling modtaget. Klar til afhentning om 20 minutter.",
    )


@app.get("/p4p/info")
def info() -> dict[str, Any]:
    return {
        "opening_hours": "11:00-22:00",
        "payment_methods": ["pay_on_pickup"],
        "fulfillment": ["pickup"],
        "node_id": NODE.node_id,
        "open": NODE.open,
        "order_mode": NODE.order_mode,
        "accepts_orders": node_accepts_orders(),
        "node_public_key": NODE_PUBLIC_KEY,
        "root_public_key": ROOT_PUBLIC_KEY,
        "delegation_role": NODE.delegation.role if NODE.delegation else None,
        "manifest_version": NODE_MANIFEST.manifest_version if NODE_MANIFEST else None,
        "manifest_key_status": NODE_MANIFEST.keys[0].status if NODE_MANIFEST else None,
        "operator_url": f"{NODE_BASE_URL.rstrip('/')}/operator" if OPERATOR_ENABLED else None,
    }
