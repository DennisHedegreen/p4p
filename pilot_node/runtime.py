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
    ModuleManifest,
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
from pilot_node.hardware_profiles import (
    hardware_profile_state,
    list_hardware_addons,
    list_hardware_base_profiles,
    list_hardware_profiles,
    profile_id_from_state,
)
from module_catalog import DEFAULT_LOCALE, normalize_locale, operator_locale_payload
from pilot_node.state_keys import (
    ACTIVE_PAYMENT_MODULE_STATE_KEY,
    DESIRED_MODULE_IDS_STATE_KEY,
    DESIRED_MODULE_IDS_UPDATED_AT_STATE_KEY,
    SETUP_CATALOG_READY_STATE_KEY,
    SETUP_COMPLETED_AT_STATE_KEY,
    SETUP_COMPLETED_STEPS_STATE_KEY,
    SETUP_HARDWARE_BASE_PROFILE_STATE_KEY,
    SETUP_HARDWARE_ENABLED_ADDONS_STATE_KEY,
    SETUP_HARDWARE_PROFILE_STATE_KEY,
    SETUP_LAST_REVIEWED_AT_STATE_KEY,
    SETUP_OPERATOR_LOCALE_STATE_KEY,
    SETUP_PAYMENT_MODULE_STATE_KEY,
    SETUP_SELF_TEST_RESULTS_STATE_KEY,
    SETUP_STARTED_AT_STATE_KEY,
)


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
                    image_url TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL
                )
                """
            )
            self._ensure_menu_item_columns()
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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS imported_module_manifests (
                    module_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    validation_error TEXT NOT NULL
                )
                """
            )
        self._seed_menu_if_empty()

    def _ensure_menu_item_columns(self) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(menu_items)").fetchall()
        }
        if "image_url" not in columns:
            self._connection.execute("ALTER TABLE menu_items ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")

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
                        id=self._config.menu_item_1_id,
                        name=self._config.menu_item_1_name,
                        description=self._config.menu_item_1_description,
                        price=self._config.menu_item_1_price,
                        category=self._config.menu_item_1_category,
                        image_url=self._config.menu_item_1_image_url,
                    ),
                    MenuItem(
                        id=self._config.menu_item_2_id,
                        name=self._config.menu_item_2_name,
                        description=self._config.menu_item_2_description,
                        price=self._config.menu_item_2_price,
                        category=self._config.menu_item_2_category,
                        image_url=self._config.menu_item_2_image_url,
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
                currency=self._config.menu_currency,
                updated_at=utc_now(),
                items=[
                    MenuItem(
                        id=row["id"],
                        name=row["name"],
                        description=row["description"],
                        price=row["price"],
                        category=row["category"],
                        active=bool(row["active"]),
                        image_url=str(row["image_url"] or "") or None,
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
                        id, name, description, price, category, active, image_url, sort_order
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.name,
                        item.description,
                        item.price,
                        item.category,
                        1 if item.active else 0,
                        item.image_url or "",
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

    def list_imported_module_manifest_records(self) -> list[dict[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT
                    module_id,
                    provider_id,
                    version,
                    source_type,
                    source_name,
                    manifest_json,
                    imported_at,
                    updated_at,
                    validation_status,
                    validation_error
                FROM imported_module_manifests
                ORDER BY updated_at DESC, module_id ASC
                """
            ).fetchall()
            return [self._row_to_imported_module_manifest_record(row) for row in rows]

    def get_imported_module_manifest_record(self, module_id: str) -> dict[str, str] | None:
        normalized_module_id = module_id.strip()
        if not normalized_module_id:
            return None
        with self._lock:
            row = self._connection.execute(
                """
                SELECT
                    module_id,
                    provider_id,
                    version,
                    source_type,
                    source_name,
                    manifest_json,
                    imported_at,
                    updated_at,
                    validation_status,
                    validation_error
                FROM imported_module_manifests
                WHERE module_id = ?
                """,
                (normalized_module_id,),
            ).fetchone()
            return self._row_to_imported_module_manifest_record(row) if row else None

    def upsert_imported_module_manifest_record(
        self,
        *,
        module_id: str,
        provider_id: str,
        version: str,
        source_name: str,
        manifest_json: str,
        validation_status: str,
        validation_error: str,
    ) -> dict[str, str]:
        normalized_module_id = module_id.strip()
        normalized_provider_id = provider_id.strip()
        normalized_version = version.strip()
        normalized_source_name = source_name.strip()
        normalized_manifest_json = manifest_json.strip()
        normalized_validation_status = validation_status.strip()
        normalized_validation_error = validation_error.strip()
        now = utc_now().isoformat()
        with self._lock, self._connection:
            existing = self.get_imported_module_manifest_record(normalized_module_id)
            imported_at = existing["imported_at"] if existing else now
            self._connection.execute(
                """
                INSERT INTO imported_module_manifests(
                    module_id,
                    provider_id,
                    version,
                    source_type,
                    source_name,
                    manifest_json,
                    imported_at,
                    updated_at,
                    validation_status,
                    validation_error
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(module_id) DO UPDATE SET
                    provider_id=excluded.provider_id,
                    version=excluded.version,
                    source_type=excluded.source_type,
                    source_name=excluded.source_name,
                    manifest_json=excluded.manifest_json,
                    updated_at=excluded.updated_at,
                    validation_status=excluded.validation_status,
                    validation_error=excluded.validation_error
                """,
                (
                    normalized_module_id,
                    normalized_provider_id,
                    normalized_version,
                    "local_upload",
                    normalized_source_name,
                    normalized_manifest_json,
                    imported_at,
                    now,
                    normalized_validation_status,
                    normalized_validation_error,
                ),
            )
        record = self.get_imported_module_manifest_record(normalized_module_id)
        assert record is not None
        return record

    def delete_imported_module_manifest_record(self, module_id: str) -> bool:
        normalized_module_id = module_id.strip()
        if not normalized_module_id:
            return False
        with self._lock, self._connection:
            result = self._connection.execute(
                "DELETE FROM imported_module_manifests WHERE module_id = ?",
                (normalized_module_id,),
            )
            return result.rowcount > 0

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

    def _row_to_imported_module_manifest_record(self, row: sqlite3.Row) -> dict[str, str]:
        return {
            "module_id": str(row["module_id"]),
            "provider_id": str(row["provider_id"]),
            "version": str(row["version"]),
            "source_type": str(row["source_type"]),
            "source_name": str(row["source_name"]),
            "manifest_json": str(row["manifest_json"]),
            "imported_at": str(row["imported_at"]),
            "updated_at": str(row["updated_at"]),
            "validation_status": str(row["validation_status"]),
            "validation_error": str(row["validation_error"]),
        }


@dataclass
class PilotRuntime:
    config: PilotConfig
    store: PilotStore
    registration: RegistrationSnapshot
    heartbeat_task: asyncio.Task[None] | None = None


def module_is_payment(manifest: ModuleManifest) -> bool:
    module_class = str(manifest.raw.get("module_class") or manifest.raw.get("type") or "").strip()
    return module_class == "payment"


def _payment_module_manifest(runtime: PilotRuntime, module_id: str) -> ModuleManifest | None:
    normalized_module_id = module_id.strip()
    if not normalized_module_id:
        return None
    manifest = runtime.config.resolved_modules.get(normalized_module_id)
    if manifest is None or not module_is_payment(manifest):
        return None
    return manifest


def effective_payment_module_id(runtime: PilotRuntime) -> str:
    persisted_module_id = runtime.store.get_state(ACTIVE_PAYMENT_MODULE_STATE_KEY, "").strip()
    if _payment_module_manifest(runtime, persisted_module_id) is not None:
        return persisted_module_id
    configured_module_id = runtime.config.payment_module_id.strip()
    if _payment_module_manifest(runtime, configured_module_id) is not None:
        return configured_module_id
    return ""


def desired_module_ids(runtime: PilotRuntime) -> list[str]:
    raw_value = runtime.store.get_state(DESIRED_MODULE_IDS_STATE_KEY, "").strip()
    if raw_value:
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            normalized: list[str] = []
            seen: set[str] = set()
            for value in payload:
                module_id = str(value).strip()
                if not module_id or module_id in seen:
                    continue
                normalized.append(module_id)
                seen.add(module_id)
            if normalized:
                return normalized
    return list(runtime.config.node_modules)


def desired_module_ids_updated_at(runtime: PilotRuntime) -> str | None:
    value = runtime.store.get_state(DESIRED_MODULE_IDS_UPDATED_AT_STATE_KEY, "").strip()
    return value or None


def set_desired_module_ids(runtime: PilotRuntime, module_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_module_id in module_ids:
        module_id = str(raw_module_id).strip()
        if not module_id or module_id in seen:
            continue
        normalized.append(module_id)
        seen.add(module_id)
    runtime.store.set_state(DESIRED_MODULE_IDS_STATE_KEY, json.dumps(normalized))
    runtime.store.set_state(DESIRED_MODULE_IDS_UPDATED_AT_STATE_KEY, utc_now().isoformat())
    return normalized


def module_restart_required(runtime: PilotRuntime) -> bool:
    return desired_module_ids(runtime) != list(runtime.config.node_modules)


def _state_json_list(runtime: PilotRuntime, key: str) -> list[str]:
    raw_value = runtime.store.get_state(key, "").strip()
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in payload:
        item = str(value).strip()
        if not item or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return normalized


def _state_json_object(runtime: PilotRuntime, key: str) -> dict[str, bool]:
    raw_value = runtime.store.get_state(key, "").strip()
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, bool] = {}
    for raw_key, raw_value in payload.items():
        key_text = str(raw_key).strip()
        if not key_text:
            continue
        normalized[key_text] = bool(raw_value)
    return normalized


def setup_completed_steps(runtime: PilotRuntime) -> list[str]:
    return _state_json_list(runtime, SETUP_COMPLETED_STEPS_STATE_KEY)


def setup_state(runtime: PilotRuntime) -> dict[str, object]:
    payment_module_id = effective_payment_module_id(runtime)
    configured_profile_ids = [profile.profile_id for profile in list_hardware_profiles()]
    runtime_hardware = hardware_profile_state(runtime.config.hardware_profile)
    stored_operator_locale = normalize_locale(
        runtime.store.get_state(SETUP_OPERATOR_LOCALE_STATE_KEY, DEFAULT_LOCALE).strip() or DEFAULT_LOCALE
    )
    stored_hardware_profile = runtime.store.get_state(SETUP_HARDWARE_PROFILE_STATE_KEY, "").strip() or None
    stored_hardware_base_profile = runtime.store.get_state(
        SETUP_HARDWARE_BASE_PROFILE_STATE_KEY, ""
    ).strip() or None
    stored_hardware_enabled_addons = _state_json_list(runtime, SETUP_HARDWARE_ENABLED_ADDONS_STATE_KEY)
    derived_hardware_profile = (
        profile_id_from_state(stored_hardware_base_profile or "", stored_hardware_enabled_addons)
        if stored_hardware_base_profile
        else None
    )
    return {
        "started_at": runtime.store.get_state(SETUP_STARTED_AT_STATE_KEY, "").strip() or None,
        "completed_at": runtime.store.get_state(SETUP_COMPLETED_AT_STATE_KEY, "").strip() or None,
        "last_reviewed_at": runtime.store.get_state(SETUP_LAST_REVIEWED_AT_STATE_KEY, "").strip() or None,
        "operator_locale": stored_operator_locale,
        "locale": operator_locale_payload(stored_operator_locale),
        "hardware_profile": stored_hardware_profile or derived_hardware_profile,
        "runtime_hardware_profile": runtime.config.hardware_profile,
        "hardware_base_profile": stored_hardware_base_profile,
        "runtime_hardware_base_profile": str(runtime_hardware["base_profile"]),
        "hardware_enabled_addons": stored_hardware_enabled_addons,
        "runtime_hardware_enabled_addons": list(runtime_hardware["enabled_addons"]),
        "available_hardware_profiles": configured_profile_ids,
        "hardware_base_profiles": list_hardware_base_profiles(),
        "hardware_addons": list_hardware_addons(),
        "payment_module_id": runtime.store.get_state(SETUP_PAYMENT_MODULE_STATE_KEY, "").strip() or payment_module_id or None,
        "catalog_ready": runtime.store.get_state(SETUP_CATALOG_READY_STATE_KEY, "").strip() == "true",
        "completed_steps": setup_completed_steps(runtime),
        "self_test_results": _state_json_object(runtime, SETUP_SELF_TEST_RESULTS_STATE_KEY),
    }


def _set_setup_completed_step(runtime: PilotRuntime, step_id: str, enabled: bool) -> list[str]:
    normalized_step_id = step_id.strip()
    steps = setup_completed_steps(runtime)
    if enabled:
        if normalized_step_id and normalized_step_id not in steps:
            steps.append(normalized_step_id)
    else:
        steps = [step for step in steps if step != normalized_step_id]
    runtime.store.set_state(SETUP_COMPLETED_STEPS_STATE_KEY, json.dumps(steps))
    return steps


def set_setup_state(
    runtime: PilotRuntime,
    *,
    operator_locale: str | None = None,
    hardware_profile: str | None = None,
    hardware_base_profile: str | None = None,
    hardware_enabled_addons: list[str] | None = None,
    catalog_ready: bool | None = None,
    local_tests_run: bool | None = None,
    completed: bool | None = None,
) -> dict[str, object]:
    now = utc_now().isoformat()
    if not runtime.store.get_state(SETUP_STARTED_AT_STATE_KEY, "").strip():
        runtime.store.set_state(SETUP_STARTED_AT_STATE_KEY, now)
    runtime.store.set_state(SETUP_LAST_REVIEWED_AT_STATE_KEY, now)

    if operator_locale is not None:
        runtime.store.set_state(
            SETUP_OPERATOR_LOCALE_STATE_KEY,
            normalize_locale(operator_locale),
        )

    normalized_hardware_base_profile: str | None = None
    normalized_hardware_enabled_addons: list[str] | None = None

    if hardware_profile is not None:
        normalized_hardware_profile = hardware_profile.strip()
        available_profile_ids = {profile.profile_id for profile in list_hardware_profiles()}
        if normalized_hardware_profile and normalized_hardware_profile not in available_profile_ids:
            raise HTTPException(status_code=400, detail=f"Unknown hardware_profile: {normalized_hardware_profile}")
        runtime.store.set_state(SETUP_HARDWARE_PROFILE_STATE_KEY, normalized_hardware_profile)
        if normalized_hardware_profile:
            profile_state = hardware_profile_state(normalized_hardware_profile)
            if hardware_base_profile is None:
                normalized_hardware_base_profile = str(profile_state["base_profile"])
            if hardware_enabled_addons is None:
                normalized_hardware_enabled_addons = list(profile_state["enabled_addons"])
        else:
            if hardware_base_profile is None:
                normalized_hardware_base_profile = ""
            if hardware_enabled_addons is None:
                normalized_hardware_enabled_addons = []

    if hardware_base_profile is not None:
        normalized_hardware_base_profile = hardware_base_profile.strip()

    if normalized_hardware_base_profile is not None:
        available_base_profile_ids = {
            str(item["id"]).strip() for item in list_hardware_base_profiles()
        }
        if normalized_hardware_base_profile and normalized_hardware_base_profile not in available_base_profile_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown hardware_base_profile: {normalized_hardware_base_profile}",
            )
        runtime.store.set_state(SETUP_HARDWARE_BASE_PROFILE_STATE_KEY, normalized_hardware_base_profile)
        _set_setup_completed_step(
            runtime,
            "hardware_profile_confirmed",
            bool(normalized_hardware_base_profile),
        )

    if hardware_enabled_addons is not None:
        normalized_hardware_enabled_addons = []
        seen_addons: set[str] = set()
        allowed_addon_ids = {str(item["id"]).strip() for item in list_hardware_addons()}
        for raw_addon_id in hardware_enabled_addons:
            addon_id = str(raw_addon_id).strip()
            if not addon_id or addon_id in seen_addons:
                continue
            if addon_id not in allowed_addon_ids:
                raise HTTPException(status_code=400, detail=f"Unknown hardware_addon: {addon_id}")
            normalized_hardware_enabled_addons.append(addon_id)
            seen_addons.add(addon_id)

    if normalized_hardware_enabled_addons is not None:
        runtime.store.set_state(
            SETUP_HARDWARE_ENABLED_ADDONS_STATE_KEY,
            json.dumps(normalized_hardware_enabled_addons),
        )

    if normalized_hardware_base_profile is not None or normalized_hardware_enabled_addons is not None:
        current_base_profile = runtime.store.get_state(SETUP_HARDWARE_BASE_PROFILE_STATE_KEY, "").strip()
        current_addons = _state_json_list(runtime, SETUP_HARDWARE_ENABLED_ADDONS_STATE_KEY)
        derived_profile_id = (
            profile_id_from_state(current_base_profile, current_addons) if current_base_profile else None
        )
        runtime.store.set_state(SETUP_HARDWARE_PROFILE_STATE_KEY, derived_profile_id or "")

    if catalog_ready is not None:
        runtime.store.set_state(SETUP_CATALOG_READY_STATE_KEY, "true" if catalog_ready else "false")
        _set_setup_completed_step(runtime, "catalog_reviewed", bool(catalog_ready))

    if local_tests_run is not None:
        _set_setup_completed_step(runtime, "local_tests_run", bool(local_tests_run))

    payment_module_id = effective_payment_module_id(runtime)
    runtime.store.set_state(SETUP_PAYMENT_MODULE_STATE_KEY, payment_module_id)

    if completed is True:
        runtime.store.set_state(SETUP_COMPLETED_AT_STATE_KEY, now)
    elif completed is False:
        runtime.store.set_state(SETUP_COMPLETED_AT_STATE_KEY, "")

    return setup_state(runtime)


def effective_flow_module_ids(runtime: PilotRuntime) -> tuple[str, ...]:
    active_payment_module_id = effective_payment_module_id(runtime)
    module_ids: list[str] = []
    for manifest in runtime.config.resolved_modules.manifests:
        if module_is_payment(manifest):
            if not active_payment_module_id or manifest.module_id != active_payment_module_id:
                continue
        module_ids.append(manifest.module_id)
    return tuple(module_ids)


def set_effective_payment_module_id(runtime: PilotRuntime, module_id: str) -> str:
    normalized_module_id = module_id.strip()
    if not normalized_module_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="module_id must not be blank")
    manifest = runtime.config.resolved_modules.get(normalized_module_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown module_id: {normalized_module_id}")
    if not module_is_payment(manifest):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Module is not a payment module: {normalized_module_id}",
        )
    runtime.store.set_state(ACTIVE_PAYMENT_MODULE_STATE_KEY, normalized_module_id)
    return normalized_module_id


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
    "desired_module_ids",
    "desired_module_ids_updated_at",
    "effective_flow_module_ids",
    "effective_payment_module_id",
    "enabled_module_declarations",
    "module_restart_required",
    "module_is_payment",
    "node_accepts_orders",
    "node_state",
    "public_module_projection",
    "public_module_declarations",
    "registration_payload",
    "set_desired_module_ids",
    "set_effective_payment_module_id",
    "sign_node_announcement",
    "signed_heartbeat_payload",
]
