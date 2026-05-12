from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from p4p_core import (
    ModuleManifest,
    ResolvedModules,
    env_float,
    env_list,
    env_path,
    env_str,
    load_reference_module_catalog,
    load_registry_urls,
    normalize_currency_code,
    normalize_module_ids,
    resolve_enabled_modules,
)
from p4p_core.constants import OrderMode
from p4p_identity import load_or_create_private_key, public_key_from_private

from pilot_node.hardware_profiles import resolve_hardware_profile
from pilot_node.print_drivers import normalize_cut_mode
from pilot_node.state_keys import DESIRED_MODULE_IDS_STATE_KEY


def load_node_private_key() -> str:
    inline = os.environ.get("P4P_NODE_PRIVATE_KEY", "").strip()
    if inline:
        return inline
    return load_or_create_private_key(env_path("P4P_NODE_KEY_FILE"))


class OperatorStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool | None = None
    order_mode: OrderMode | None = None


class OperatorPaymentModuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str


class OperatorModuleSetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_ids: list[str]


class OperatorSetupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_locale: str | None = None
    hardware_profile: str | None = None
    hardware_base_profile: str | None = None
    hardware_enabled_addons: list[str] | None = None
    catalog_ready: bool | None = None
    local_tests_run: bool | None = None


class OperatorModuleManifestImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str
    manifest_json: str


@dataclass(frozen=True)
class PilotConfig:
    heartbeat_interval_seconds: int
    readiness_stale_after_seconds: int
    node_base_url: str
    registry_urls: list[str]
    node_private_key: str
    node_public_key: str
    operator_token: str
    node_id: str
    node_name: str
    node_lat: float
    node_lng: float
    node_country: str
    node_city: str
    node_categories: list[str]
    node_open_default: bool
    node_order_mode_default: str
    node_modules: list[str]
    available_resolved_modules: ResolvedModules
    public_node_modules: list[str]
    undeclared_node_modules: list[str]
    resolved_modules: ResolvedModules
    hardware_profile: str
    hardware_profile_customized: bool
    print_module_target: str
    print_module_driver: str
    print_module_mode: str
    print_spool_dir: str
    print_device_path: str
    print_escpos_cut_mode: str
    backup_print_target: str
    backup_print_driver: str
    backup_print_spool_dir: str
    backup_print_device_path: str
    backup_print_escpos_cut_mode: str
    print_sensor_source: str
    print_sensor_status_path: str
    print_sensor_serial_path: str
    print_sensor_precheck: str
    print_sensor_postcheck: str
    alert_target: str
    alert_mode: str
    pickup_board_target: str
    stock_module_mode: str
    stock_unavailable_item_ids: list[str]
    flow_module_ids: tuple[str, ...]
    external_module_manifest_paths: list[str]
    payment_module_id: str
    payment_cash_mode: str
    payment_external_url: str
    payment_external_customer_user_id: str
    payment_external_merchant_id: str
    payment_external_currency: str
    payment_external_auto_confirm: bool
    payment_external_timeout_seconds: float
    godpay_success_threshold: int
    godpay_seed: str
    godpay_force_roll: int | None
    notify_email_mode: str
    db_path: str
    menu_currency: str
    menu_item_1_id: str
    menu_item_1_name: str
    menu_item_1_description: str
    menu_item_1_price: int
    menu_item_1_category: str
    menu_item_1_image_url: str
    menu_item_2_id: str
    menu_item_2_name: str
    menu_item_2_description: str
    menu_item_2_price: int
    menu_item_2_category: str
    menu_item_2_image_url: str


def _is_payment_manifest(manifest: ModuleManifest) -> bool:
    module_class = str(manifest.raw.get("module_class") or manifest.raw.get("type") or "").strip()
    return module_class == "payment"


def _load_external_module_manifests(
    paths: list[str],
) -> tuple[ModuleManifest, ...]:
    if not paths:
        return ()

    manifests: list[ModuleManifest] = []
    seen: set[str] = set()
    for raw_path in paths:
        manifest_path = Path(raw_path).expanduser()
        if not manifest_path.is_absolute():
            manifest_path = Path.cwd() / manifest_path
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"External module manifest must be a JSON object: {manifest_path}")
        manifest = ModuleManifest.from_payload(payload, source_path=manifest_path)
        if manifest.module_id in seen:
            raise ValueError(f"Duplicate external module manifest: {manifest.module_id}")
        seen.add(manifest.module_id)
        manifests.append(manifest)
    return tuple(manifests)


def _choose_payment_module_id(
    manifests: tuple[ModuleManifest, ...],
    *,
    configured_module_id: str,
) -> str:
    if configured_module_id:
        configured_manifest = next(
            (manifest for manifest in manifests if manifest.module_id == configured_module_id),
            None,
        )
        if configured_manifest is None or not _is_payment_manifest(configured_manifest):
            raise ValueError(
                "P4P_PAYMENT_MODULE_ID must name an enabled reference or imported payment module"
            )
        return configured_module_id
    for manifest in manifests:
        if _is_payment_manifest(manifest):
            return manifest.module_id
    return ""


def _flow_module_ids(
    manifests: tuple[ModuleManifest, ...],
    *,
    payment_module_id: str,
) -> tuple[str, ...]:
    module_ids: list[str] = []
    for manifest in manifests:
        if _is_payment_manifest(manifest) and payment_module_id and manifest.module_id != payment_module_id:
            continue
        module_ids.append(manifest.module_id)
    return tuple(module_ids)


def _env_int_range(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return min(max(parsed, minimum), maximum)


def _read_persisted_desired_module_ids(db_path: str) -> list[str] | None:
    normalized_path = db_path.strip()
    if not normalized_path or normalized_path == ":memory:":
        return None
    path = Path(normalized_path)
    if not path.exists():
        return None

    try:
        connection = sqlite3.connect(normalized_path)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            "SELECT value FROM state WHERE key = ?",
            (DESIRED_MODULE_IDS_STATE_KEY,),
        ).fetchone()
    except sqlite3.Error:
        connection.close()
        return None
    connection.close()

    if not row:
        return None

    raw_value = str(row[0] or "").strip()
    if not raw_value:
        return None
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    return normalize_module_ids([str(value) for value in payload])


def build_pilot_config() -> PilotConfig:
    heartbeat_interval_seconds = int(os.environ.get("P4P_HEARTBEAT_INTERVAL_SECONDS", "60"))
    node_private_key = load_node_private_key()
    node_id = env_str("P4P_NODE_ID", "dk-brondby-kebab-001")
    db_path = os.environ.get("P4P_PILOT_NODE_DB_PATH", ":memory:")
    env_node_modules = normalize_module_ids(env_list("P4P_NODE_MODULES", ["p4p.payment.cash"]))
    persisted_node_modules = _read_persisted_desired_module_ids(db_path)
    node_modules = persisted_node_modules or env_node_modules
    external_module_manifest_paths = env_list("P4P_EXTERNAL_MODULE_MANIFESTS", [])
    reference_catalog = load_reference_module_catalog()
    external_modules = _load_external_module_manifests(external_module_manifest_paths)
    reference_module_by_id = dict(reference_catalog)
    external_module_by_id = {manifest.module_id: manifest for manifest in external_modules}
    duplicate_module_ids = sorted(set(reference_module_by_id) & set(external_module_by_id))
    if duplicate_module_ids:
        raise ValueError(f"External module manifests shadow reference modules: {', '.join(duplicate_module_ids)}")
    all_manifest_by_id = reference_module_by_id | external_module_by_id
    available_resolved_modules = ResolvedModules(
        tuple(all_manifest_by_id[module_id] for module_id in all_manifest_by_id)
    )
    resolved_modules = ResolvedModules(
        tuple(all_manifest_by_id[module_id] for module_id in node_modules if module_id in all_manifest_by_id)
    )
    payment_module_id = _choose_payment_module_id(
        resolved_modules.manifests,
        configured_module_id=env_str("P4P_PAYMENT_MODULE_ID", "").strip(),
    )
    selected_payment_manifest = resolved_modules.get(payment_module_id) if payment_module_id else None
    manifest_entrypoint = ""
    if selected_payment_manifest is not None:
        raw_entrypoint = selected_payment_manifest.raw.get("entrypoint")
        if isinstance(raw_entrypoint, str):
            manifest_entrypoint = raw_entrypoint.strip()
    declared_module_ids = set(resolved_modules.module_ids)
    undeclared_node_modules = [module_id for module_id in node_modules if module_id not in declared_module_ids]

    hardware_profile = resolve_hardware_profile(env_str("P4P_HARDWARE_PROFILE", "reference_printer"))
    print_module_target = env_str("P4P_PRINT_MODULE_TARGET", hardware_profile.print_module_target)
    print_module_driver = env_str("P4P_PRINT_MODULE_DRIVER", hardware_profile.print_module_driver)
    print_escpos_cut_mode = env_str("P4P_PRINT_ESCPOS_CUT_MODE", hardware_profile.print_escpos_cut_mode)
    print_sensor_source = env_str("P4P_PRINT_SENSOR_SOURCE", hardware_profile.print_sensor_source)
    backup_print_target = env_str("P4P_BACKUP_PRINT_TARGET", hardware_profile.backup_print_target).strip()
    backup_print_driver = env_str("P4P_BACKUP_PRINT_DRIVER", hardware_profile.backup_print_driver).strip()
    alert_target = env_str("P4P_ALERT_TARGET", hardware_profile.alert_target).strip()
    alert_mode = env_str("P4P_ALERT_MODE", hardware_profile.alert_mode).strip()
    pickup_board_target = env_str("P4P_PICKUP_BOARD_TARGET", hardware_profile.pickup_board_target).strip()
    hardware_profile_customized = any(
        (
            print_module_target != hardware_profile.print_module_target,
            print_module_driver != hardware_profile.print_module_driver,
            print_escpos_cut_mode != hardware_profile.print_escpos_cut_mode,
            print_sensor_source != hardware_profile.print_sensor_source,
            backup_print_target != hardware_profile.backup_print_target,
            backup_print_driver != hardware_profile.backup_print_driver,
            alert_target != hardware_profile.alert_target,
            alert_mode != hardware_profile.alert_mode,
            pickup_board_target != hardware_profile.pickup_board_target,
        )
    )

    return PilotConfig(
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        readiness_stale_after_seconds=heartbeat_interval_seconds + 10,
        node_base_url=os.environ.get("P4P_NODE_BASE_URL", "http://127.0.0.1:8201"),
        registry_urls=load_registry_urls(),
        node_private_key=node_private_key,
        node_public_key=public_key_from_private(node_private_key),
        operator_token=os.environ.get("P4P_OPERATOR_TOKEN", "").strip(),
        node_id=node_id,
        node_name=env_str("P4P_NODE_NAME", "P4P Pilot Kebab"),
        node_lat=env_float("P4P_NODE_LAT", 55.6517),
        node_lng=env_float("P4P_NODE_LNG", 12.4126),
        node_country=env_str("P4P_NODE_COUNTRY", "DK"),
        node_city=env_str("P4P_NODE_CITY", "Brondby"),
        node_categories=env_list("P4P_NODE_CATEGORIES", ["kebab"]),
        node_open_default=env_str("P4P_NODE_OPEN", "true").lower() == "true",
        node_order_mode_default=env_str("P4P_NODE_ORDER_MODE", "menu_only"),
        node_modules=node_modules,
        available_resolved_modules=available_resolved_modules,
        public_node_modules=resolved_modules.public_module_ids(),
        undeclared_node_modules=undeclared_node_modules,
        resolved_modules=resolved_modules,
        hardware_profile=hardware_profile.profile_id,
        hardware_profile_customized=hardware_profile_customized,
        print_module_target=print_module_target,
        print_module_driver=print_module_driver,
        print_module_mode=env_str("P4P_PRINT_MODULE_MODE", "confirmed"),
        print_spool_dir=os.environ.get("P4P_PRINT_SPOOL_DIR", "").strip(),
        print_device_path=os.environ.get("P4P_PRINT_DEVICE_PATH", "").strip(),
        print_escpos_cut_mode=print_escpos_cut_mode,
        backup_print_target=backup_print_target,
        backup_print_driver=backup_print_driver,
        backup_print_spool_dir=os.environ.get("P4P_BACKUP_PRINT_SPOOL_DIR", "").strip(),
        backup_print_device_path=os.environ.get("P4P_BACKUP_PRINT_DEVICE_PATH", "").strip(),
        backup_print_escpos_cut_mode=normalize_cut_mode(env_str("P4P_BACKUP_PRINT_ESCPOS_CUT_MODE", "partial")),
        print_sensor_source=print_sensor_source,
        print_sensor_status_path=os.environ.get("P4P_PRINT_SENSOR_STATUS_PATH", "").strip(),
        print_sensor_serial_path=os.environ.get("P4P_PRINT_SENSOR_SERIAL_PATH", "").strip(),
        print_sensor_precheck=env_str("P4P_PRINT_SENSOR_PRECHECK", "ok"),
        print_sensor_postcheck=env_str("P4P_PRINT_SENSOR_POSTCHECK", "confirmed"),
        alert_target=alert_target,
        alert_mode=alert_mode,
        pickup_board_target=pickup_board_target,
        stock_module_mode=env_str("P4P_STOCK_MODULE_MODE", "validated"),
        stock_unavailable_item_ids=env_list("P4P_STOCK_UNAVAILABLE_ITEM_IDS", []),
        flow_module_ids=_flow_module_ids(resolved_modules.manifests, payment_module_id=payment_module_id),
        external_module_manifest_paths=external_module_manifest_paths,
        payment_module_id=payment_module_id,
        payment_cash_mode=env_str("P4P_PAYMENT_CASH_MODE", "pay_at_pickup"),
        payment_external_url=env_str("P4P_PAYMENT_EXTERNAL_URL", manifest_entrypoint).strip(),
        payment_external_customer_user_id=env_str("P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID", "").strip(),
        payment_external_merchant_id=env_str("P4P_PAYMENT_EXTERNAL_MERCHANT_ID", node_id).strip() or node_id,
        payment_external_currency=env_str("P4P_PAYMENT_EXTERNAL_CURRENCY", "PIZZACOIN").strip() or "PIZZACOIN",
        payment_external_auto_confirm=(
            env_str("P4P_PAYMENT_EXTERNAL_AUTO_CONFIRM", "true").strip().lower()
            not in {"0", "false", "no"}
        ),
        payment_external_timeout_seconds=env_float("P4P_PAYMENT_EXTERNAL_TIMEOUT_SECONDS", 5.0),
        godpay_success_threshold=_env_int_range("P4P_GODPAY_SUCCESS_THRESHOLD", 50, minimum=0, maximum=100),
        godpay_seed=env_str("P4P_GODPAY_SEED", "").strip(),
        godpay_force_roll=(
            _env_int_range("P4P_GODPAY_FORCE_ROLL", 0, minimum=0, maximum=100) or None
        ),
        notify_email_mode=env_str("P4P_NOTIFY_EMAIL_MODE", "sent"),
        db_path=db_path,
        menu_currency=normalize_currency_code(env_str("P4P_MENU_CURRENCY", "DKK")),
        menu_item_1_id=env_str("P4P_MENU_ITEM_1_ID", "kebab-pita"),
        menu_item_1_name=env_str("P4P_MENU_ITEM_1_NAME", "Kebab pita"),
        menu_item_1_description=env_str("P4P_MENU_ITEM_1_DESCRIPTION", "Kebab, salat, dressing"),
        menu_item_1_price=int(env_str("P4P_MENU_ITEM_1_PRICE", "6500")),
        menu_item_1_category=env_str("P4P_MENU_ITEM_1_CATEGORY", "kebab"),
        menu_item_1_image_url=env_str("P4P_MENU_ITEM_1_IMAGE_URL", "").strip(),
        menu_item_2_id=env_str("P4P_MENU_ITEM_2_ID", "durum-kebab"),
        menu_item_2_name=env_str("P4P_MENU_ITEM_2_NAME", "Durum kebab"),
        menu_item_2_description=env_str("P4P_MENU_ITEM_2_DESCRIPTION", "Kebab, salat, dressing"),
        menu_item_2_price=int(env_str("P4P_MENU_ITEM_2_PRICE", "7500")),
        menu_item_2_category=env_str("P4P_MENU_ITEM_2_CATEGORY", "kebab"),
        menu_item_2_image_url=env_str("P4P_MENU_ITEM_2_IMAGE_URL", "").strip(),
    )


__all__ = [
    "OperatorModuleSetUpdate",
    "OperatorPaymentModuleUpdate",
    "OperatorStateUpdate",
    "PilotConfig",
    "build_pilot_config",
    "load_node_private_key",
]
