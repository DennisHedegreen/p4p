from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_identity import load_or_create_private_key, public_key_from_private, sign_payload


PROTOCOL_VERSION = "0.1"
HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("P4P_HEARTBEAT_INTERVAL_SECONDS", "60"))
READINESS_STALE_AFTER_SECONDS = HEARTBEAT_INTERVAL_SECONDS + 10
NODE_BASE_URL = os.environ.get("P4P_NODE_BASE_URL", "http://127.0.0.1:8201")
NODE_ID_PATTERN = r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3,}$"
CATEGORY_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
OrderMode = Literal["disabled", "menu_only", "test", "live"]
OrderStatus = Literal["new", "accepted", "rejected", "ready", "completed", "cancelled"]


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


def load_registry_urls() -> list[str]:
    raw = os.environ.get("P4P_REGISTRY_URLS")
    values = [value.strip() for value in raw.split(",") if value.strip()] if raw else [
        env_str("P4P_REGISTRY_URL", "http://127.0.0.1:8000")
    ]

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def load_node_private_key() -> str:
    inline = os.environ.get("P4P_NODE_PRIVATE_KEY", "").strip()
    if inline:
        return inline
    return load_or_create_private_key(env_path("P4P_NODE_KEY_FILE"))


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class NodeDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(pattern=NODE_ID_PATTERN)
    name: str = Field(min_length=1)
    location: Location
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str = Field(min_length=1)
    categories: list[str]
    endpoint: HttpUrl
    open: bool
    order_mode: OrderMode
    modules: list[str] = Field(default_factory=list)
    node_public_key: str | None = None
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
        raise ValueError("endpoint must use https unless it is loopback http")

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(CATEGORY_PATTERN, value):
                raise ValueError("categories must use lowercase canonical tokens")
        return values


class MenuItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=CATEGORY_PATTERN)
    name: str = Field(min_length=1)
    description: str = ""
    price: int = Field(ge=0)
    category: str = Field(pattern=CATEGORY_PATTERN)
    active: bool = True


class Menu(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = "DKK"
    updated_at: datetime
    items: list[MenuItem]


class MenuUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MenuItem] = Field(min_length=1)


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
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


class OperatorStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool | None = None
    order_mode: OrderMode | None = None


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    status_message: str | None = None
    estimated_ready_minutes: int | None = Field(default=None, ge=0, le=240)


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


class PilotStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path.strip() or ":memory:"
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS menu_items (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    sort_order INTEGER NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    customer_contact TEXT NOT NULL,
                    fulfillment TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    note TEXT NOT NULL,
                    client_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    status_message TEXT,
                    requested_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    estimated_ready TEXT
                )
                """
            )
        self._seed_menu_if_empty()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _seed_menu_if_empty(self) -> None:
        with self._lock:
            count = self._connection.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]
            if count:
                return
            self.replace_menu(
                [
                    MenuItem(
                        id="kebab-pita",
                        name=env_str("P4P_MENU_ITEM_1_NAME", "Kebab pita"),
                        description=env_str("P4P_MENU_ITEM_1_DESCRIPTION", "Kebab, salat, dressing"),
                        price=int(env_str("P4P_MENU_ITEM_1_PRICE", "65")),
                        category="kebab",
                    ),
                    MenuItem(
                        id="durum-kebab",
                        name=env_str("P4P_MENU_ITEM_2_NAME", "Durum kebab"),
                        description=env_str("P4P_MENU_ITEM_2_DESCRIPTION", "Kebab, salat, dressing"),
                        price=int(env_str("P4P_MENU_ITEM_2_PRICE", "75")),
                        category="kebab",
                    ),
                ]
            )

    def get_state(self, key: str, default: str) -> str:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM state WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row["value"]) if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO state(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def menu(self, *, include_inactive: bool = False) -> Menu:
        with self._lock:
            query = "SELECT * FROM menu_items"
            if not include_inactive:
                query += " WHERE active = 1"
            query += " ORDER BY sort_order, id"
            rows = self._connection.execute(query).fetchall()
            return Menu(
                updated_at=utc_now(),
                items=[
                    MenuItem(
                        id=row["id"],
                        name=row["name"],
                        description=row["description"],
                        price=row["price"],
                        category=row["category"],
                        active=bool(row["active"]),
                    )
                    for row in rows
                ],
            )

    def replace_menu(self, items: list[MenuItem]) -> Menu:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM menu_items")
            for index, item in enumerate(items):
                self._connection.execute(
                    """
                    INSERT INTO menu_items(
                        id, name, description, price, category, active, sort_order
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.name,
                        item.description,
                        item.price,
                        item.category,
                        1 if item.active else 0,
                        index,
                    ),
                )
        return self.menu(include_inactive=True)

    def active_menu_item_ids(self) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM menu_items WHERE active = 1"
            ).fetchall()
            return {str(row["id"]) for row in rows}

    def create_order(self, payload: OrderRequest) -> StoredOrder:
        with self._lock, self._connection:
            active_ids = self.active_menu_item_ids()
            unknown = [item.id for item in payload.items if item.id not in active_ids]
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown or inactive menu item: {unknown[0]}",
                )
            now = utc_now()
            order = StoredOrder(
                order_id=f"p4p-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}",
                customer_name=payload.customer_name,
                customer_contact=payload.customer_contact,
                fulfillment=payload.fulfillment,
                items=payload.items,
                note=payload.note,
                client_version=payload.client_version,
                status="new",
                requested_at=now,
                updated_at=now,
                estimated_ready=now + timedelta(minutes=20),
            )
            self._connection.execute(
                """
                INSERT INTO orders(
                    order_id, customer_name, customer_contact, fulfillment, items_json,
                    note, client_version, status, payment_method, status_message,
                    requested_at, updated_at, estimated_ready
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.customer_name,
                    order.customer_contact,
                    order.fulfillment,
                    json.dumps([item.model_dump(mode="json") for item in order.items]),
                    order.note,
                    order.client_version,
                    order.status,
                    order.payment_method,
                    order.status_message,
                    serialize_datetime(order.requested_at),
                    serialize_datetime(order.updated_at),
                    serialize_datetime(order.estimated_ready),
                ),
            )
            return order

    def list_orders(self, *, limit: int = 100) -> list[StoredOrder]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM orders ORDER BY requested_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_order(row) for row in rows]

    def get_order(self, order_id: str) -> StoredOrder | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return self._row_to_order(row) if row else None

    def update_order_status(self, order_id: str, payload: OrderStatusUpdate) -> StoredOrder:
        with self._lock, self._connection:
            existing = self.get_order(order_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Unknown order_id: {order_id}")
            now = utc_now()
            estimated_ready = (
                now + timedelta(minutes=payload.estimated_ready_minutes)
                if payload.estimated_ready_minutes is not None
                else existing.estimated_ready
            )
            self._connection.execute(
                """
                UPDATE orders
                SET status = ?, status_message = ?, updated_at = ?, estimated_ready = ?
                WHERE order_id = ?
                """,
                (
                    payload.status,
                    payload.status_message,
                    serialize_datetime(now),
                    serialize_datetime(estimated_ready),
                    order_id,
                ),
            )
            updated = self.get_order(order_id)
            assert updated is not None
            return updated

    def _row_to_order(self, row: sqlite3.Row) -> StoredOrder:
        return StoredOrder(
            order_id=row["order_id"],
            customer_name=row["customer_name"],
            customer_contact=row["customer_contact"],
            fulfillment=row["fulfillment"],
            items=[OrderItem(**item) for item in json.loads(row["items_json"])],
            note=row["note"],
            client_version=row["client_version"],
            status=row["status"],
            payment_method=row["payment_method"],
            status_message=row["status_message"],
            requested_at=parse_datetime(row["requested_at"]) or utc_now(),
            updated_at=parse_datetime(row["updated_at"]) or utc_now(),
            estimated_ready=parse_datetime(row["estimated_ready"]),
        )


REGISTRY_URLS = load_registry_urls()
NODE_PRIVATE_KEY = load_node_private_key()
NODE_PUBLIC_KEY = public_key_from_private(NODE_PRIVATE_KEY)
OPERATOR_TOKEN = os.environ.get("P4P_OPERATOR_TOKEN", "").strip()
NODE_ID = env_str("P4P_NODE_ID", "dk-brondby-kebab-001")
NODE_NAME = env_str("P4P_NODE_NAME", "P4P Pilot Kebab")
NODE_LAT = env_float("P4P_NODE_LAT", 55.6517)
NODE_LNG = env_float("P4P_NODE_LNG", 12.4126)
NODE_COUNTRY = env_str("P4P_NODE_COUNTRY", "DK")
NODE_CITY = env_str("P4P_NODE_CITY", "Brondby")
NODE_CATEGORIES = env_list("P4P_NODE_CATEGORIES", ["kebab"])
NODE_OPEN_DEFAULT = env_str("P4P_NODE_OPEN", "true").lower() == "true"
NODE_ORDER_MODE_DEFAULT = env_str("P4P_NODE_ORDER_MODE", "menu_only")
NODE_MODULES = env_list("P4P_NODE_MODULES", ["p4p.payment.cash"])
store = PilotStore(os.environ.get("P4P_PILOT_NODE_DB_PATH", ":memory:"))
REGISTRATION = RegistrationSnapshot(configured_registries=REGISTRY_URLS.copy())


def node_state() -> NodeDescriptor:
    return NodeDescriptor(
        node_id=NODE_ID,
        name=NODE_NAME,
        location=Location(
            lat=NODE_LAT,
            lng=NODE_LNG,
        ),
        country=NODE_COUNTRY,
        city=NODE_CITY,
        categories=NODE_CATEGORIES,
        endpoint=f"{NODE_BASE_URL.rstrip('/')}/p4p",
        open=store.get_state("open", "true" if NODE_OPEN_DEFAULT else "false").lower() == "true",
        order_mode=store.get_state("order_mode", NODE_ORDER_MODE_DEFAULT),
        modules=NODE_MODULES,
        node_public_key=NODE_PUBLIC_KEY,
    )


def node_accepts_orders(node: NodeDescriptor | None = None) -> bool:
    effective = node or node_state()
    return effective.open and effective.order_mode in {"test", "live"}


def sign_node_announcement() -> dict[str, Any]:
    node = node_state()
    node.signed_at = utc_now().isoformat()
    node.signature = None
    payload = node.model_dump(mode="json", exclude_none=True)
    node.signature = sign_payload(payload, NODE_PRIVATE_KEY)
    return node.model_dump(mode="json", exclude_none=True)


def signed_heartbeat_payload() -> dict[str, Any]:
    node = node_state()
    payload: dict[str, Any] = {
        "node_id": node.node_id,
        "open": node.open,
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
        "last_cycle_finished_at": serialize_datetime(REGISTRATION.last_cycle_finished_at),
    }


def header_value(value: str | None) -> str | None:
    return value if isinstance(value, str) else None


def require_operator_token(
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> None:
    if not OPERATOR_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator token is not configured",
        )
    authorization = header_value(authorization)
    token = header_value(x_p4p_operator_token)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not secrets.compare_digest(token, OPERATOR_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")


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


async def heartbeat_registry(client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(
        f"{registry_url.rstrip('/')}/heartbeat",
        json=signed_heartbeat_payload(),
    )
    if response.status_code == status.HTTP_404_NOT_FOUND:
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
            print(f"[p4p-pilot-node] heartbeat cycle failed: {exc}")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    task: asyncio.Task[None] | None = None
    try:
        await run_registry_cycle(force_announce=True)
        task = asyncio.create_task(heartbeat_loop())
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        store.close()


app = FastAPI(
    title="P4P Pilot Node",
    version=PROTOCOL_VERSION,
    summary="Restaurant-owned node for the P4P live pilot.",
    lifespan=app_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(response: Response) -> dict[str, Any]:
    ready = REGISTRATION.ready()
    node = node_state()
    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "protocol_version": PROTOCOL_VERSION,
        "node_id": node.node_id,
        "open": node.open,
        "order_mode": node.order_mode,
        "accepts_orders": node_accepts_orders(node),
        "operator_configured": bool(OPERATOR_TOKEN),
        "node_public_key": NODE_PUBLIC_KEY,
        **registration_payload(),
    }


@app.get("/p4p/menu", response_model=Menu)
def public_menu() -> Menu:
    return store.menu()


@app.post("/p4p/order", response_model=OrderAccepted | OrderRejected)
def public_order(payload: OrderRequest) -> OrderAccepted | OrderRejected:
    node = node_state()
    if not node.open:
        return OrderRejected(reason="closed", message="Restaurant is closed.")
    if node.order_mode not in {"test", "live"}:
        return OrderRejected(
            reason="orders_disabled",
            message="Restaurant is not accepting orders right now.",
        )
    order = store.create_order(payload)
    return OrderAccepted(
        order_id=order.order_id,
        estimated_ready=order.estimated_ready or (utc_now() + timedelta(minutes=20)),
        message="Order received. Pay at pickup.",
    )


@app.get("/p4p/info")
def public_info() -> dict[str, Any]:
    node = node_state()
    return {
        "node_id": node.node_id,
        "open": node.open,
        "order_mode": node.order_mode,
        "accepts_orders": node_accepts_orders(node),
        "payment_methods": ["pay_at_pickup"],
        "fulfillment": ["pickup"],
        "node_public_key": NODE_PUBLIC_KEY,
    }


@app.get("/operator/state")
def operator_state(
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    node = node_state()
    return {
        "node": node.model_dump(mode="json", exclude_none=True),
        "accepts_orders": node_accepts_orders(node),
        "registry": registration_payload(),
    }


@app.patch("/operator/state")
async def operator_update_state(
    payload: OperatorStateUpdate,
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    if payload.open is not None:
        store.set_state("open", "true" if payload.open else "false")
    if payload.order_mode is not None:
        store.set_state("order_mode", payload.order_mode)
    await run_registry_cycle(force_announce=True)
    node = node_state()
    return {
        "node": node.model_dump(mode="json", exclude_none=True),
        "accepts_orders": node_accepts_orders(node),
        "registry": registration_payload(),
    }


@app.get("/operator/menu", response_model=Menu)
def operator_menu(
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> Menu:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    return store.menu(include_inactive=True)


@app.put("/operator/menu", response_model=Menu)
def operator_replace_menu(
    payload: MenuUpdate,
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> Menu:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    return store.replace_menu(payload.items)


@app.get("/operator/orders", response_model=list[StoredOrder])
def operator_orders(
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> list[StoredOrder]:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    return store.list_orders()


@app.patch("/operator/orders/{order_id}", response_model=StoredOrder)
def operator_update_order(
    order_id: str,
    payload: OrderStatusUpdate,
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> StoredOrder:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    return store.update_order_status(order_id, payload)


@app.post("/operator/reannounce")
async def operator_reannounce(
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_operator_token(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
    await run_registry_cycle(force_announce=True)
    return registration_payload()
