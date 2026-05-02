from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status

from p4p_core import (
    Location,
    Menu,
    MenuItem,
    ModuleResultEvent,
    NodeDescriptor,
    OrderItem,
    OrderRequest,
    OrderStatusUpdate,
    RegistrationSnapshot,
    StoredOrder,
    parse_datetime,
    serialize_datetime,
    utc_now,
)
from p4p_identity import sign_payload

from pilot_node.config import PilotConfig, build_pilot_config


class PilotStore:
    def __init__(self, db_path: str, *, config: PilotConfig) -> None:
        self._config = config
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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT,
                    action_id TEXT NOT NULL,
                    source_module TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
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
                        name=self._config.menu_item_1_name,
                        description=self._config.menu_item_1_description,
                        price=self._config.menu_item_1_price,
                        category="kebab",
                    ),
                    MenuItem(
                        id="durum-kebab",
                        name=self._config.menu_item_2_name,
                        description=self._config.menu_item_2_description,
                        price=self._config.menu_item_2_price,
                        category="kebab",
                    ),
                ]
            )

    def get_state(self, key: str, default: str) -> str:
        with self._lock:
            row = self._connection.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
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
            rows = self._connection.execute("SELECT id FROM menu_items WHERE active = 1").fetchall()
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

    def record_order_event(self, event: ModuleResultEvent) -> ModuleResultEvent:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO order_events(order_id, action_id, source_module, event_json, recorded_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    event.order_id,
                    event.action_id,
                    event.source_module,
                    json.dumps(event.model_dump(mode="json", exclude_none=True)),
                    serialize_datetime(event.timestamp),
                ),
            )
        return event

    def list_order_events(self, order_id: str, *, limit: int = 100) -> list[ModuleResultEvent]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_json
                FROM order_events
                WHERE order_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (order_id, limit),
            ).fetchall()
            return [ModuleResultEvent(**json.loads(str(row["event_json"]))) for row in rows]

    def get_order(self, order_id: str) -> StoredOrder | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
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

    def update_order_payment_method(self, order_id: str, payment_method: str) -> StoredOrder:
        normalized_payment_method = payment_method.strip()
        if not normalized_payment_method:
            raise HTTPException(status_code=400, detail="payment_method must not be blank")
        with self._lock, self._connection:
            if self.get_order(order_id) is None:
                raise HTTPException(status_code=404, detail=f"Unknown order_id: {order_id}")
            now = utc_now()
            self._connection.execute(
                """
                UPDATE orders
                SET payment_method = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (
                    normalized_payment_method,
                    serialize_datetime(now),
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


@dataclass
class PilotRuntime:
    config: PilotConfig
    store: PilotStore
    registration: RegistrationSnapshot
    heartbeat_task: asyncio.Task[None] | None = None


def node_state(runtime: PilotRuntime) -> NodeDescriptor:
    return NodeDescriptor(
        node_id=runtime.config.node_id,
        name=runtime.config.node_name,
        location=Location(lat=runtime.config.node_lat, lng=runtime.config.node_lng),
        country=runtime.config.node_country,
        city=runtime.config.node_city,
        categories=runtime.config.node_categories,
        endpoint=f"{runtime.config.node_base_url.rstrip('/')}/p4p",
        open=runtime.store.get_state(
            "open",
            "true" if runtime.config.node_open_default else "false",
        ).lower()
        == "true",
        order_mode=runtime.store.get_state("order_mode", runtime.config.node_order_mode_default),
        modules=runtime.config.public_node_modules,
        node_public_key=runtime.config.node_public_key,
    )


def enabled_module_declarations(runtime: PilotRuntime) -> list[dict[str, object]]:
    return runtime.config.resolved_modules.declarations()


def public_module_declarations(runtime: PilotRuntime) -> list[dict[str, object]]:
    return runtime.config.resolved_modules.public_declarations()


def public_module_projection(runtime: PilotRuntime) -> dict[str, object]:
    return {
        "modules": list(runtime.config.public_node_modules),
        "module_declarations": public_module_declarations(runtime),
        "undeclared_modules": [],
    }


def node_accepts_orders(runtime: PilotRuntime, node: NodeDescriptor | None = None) -> bool:
    effective = node or node_state(runtime)
    return effective.open and effective.order_mode in {"test", "live"}


def sign_node_announcement(runtime: PilotRuntime) -> dict[str, object]:
    node = node_state(runtime)
    node.signed_at = utc_now().isoformat()
    node.signature = None
    payload = node.model_dump(mode="json", exclude_none=True)
    node.signature = sign_payload(payload, runtime.config.node_private_key)
    return node.model_dump(mode="json", exclude_none=True)


def signed_heartbeat_payload(runtime: PilotRuntime) -> dict[str, object]:
    node = node_state(runtime)
    payload: dict[str, object] = {
        "node_id": node.node_id,
        "open": node.open,
        "signed_at": utc_now().isoformat(),
    }
    payload["signature"] = sign_payload(payload, runtime.config.node_private_key)
    return payload


def registration_payload(runtime: PilotRuntime) -> dict[str, object]:
    return {
        "ready": runtime.registration.ready(),
        "configured_registries": runtime.registration.configured_registries,
        "registered_registries": runtime.registration.registered_registries,
        "failed_registries": runtime.registration.failed_registries,
        "last_cycle_finished_at": serialize_datetime(runtime.registration.last_cycle_finished_at),
    }


def build_pilot_runtime(config: PilotConfig | None = None) -> PilotRuntime:
    effective_config = config or build_pilot_config()
    return PilotRuntime(
        config=effective_config,
        store=PilotStore(effective_config.db_path, config=effective_config),
        registration=RegistrationSnapshot(
            configured_registries=effective_config.registry_urls.copy(),
            stale_after_seconds=effective_config.readiness_stale_after_seconds,
        ),
    )


__all__ = [
    "PilotRuntime",
    "PilotStore",
    "build_pilot_runtime",
    "enabled_module_declarations",
    "node_accepts_orders",
    "node_state",
    "public_module_projection",
    "public_module_declarations",
    "registration_payload",
    "sign_node_announcement",
    "signed_heartbeat_payload",
]
