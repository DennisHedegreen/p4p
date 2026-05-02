from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from p4p_core import ResolvedModules, env_float, env_list, env_path, env_str, load_registry_urls, resolve_enabled_modules
from p4p_core.constants import OrderMode
from p4p_identity import load_or_create_private_key, public_key_from_private

from pilot_node.hardware_profiles import resolve_hardware_profile


def load_node_private_key() -> str:
    inline = os.environ.get("P4P_NODE_PRIVATE_KEY", "").strip()
    if inline:
        return inline
    return load_or_create_private_key(env_path("P4P_NODE_KEY_FILE"))


class OperatorStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool | None = None
    order_mode: OrderMode | None = None


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
    public_node_modules: list[str]
    resolved_modules: ResolvedModules
    hardware_profile: str
    hardware_profile_customized: bool
    print_module_target: str
    print_module_driver: str
    print_module_mode: str
    print_spool_dir: str
    print_device_path: str
    print_escpos_cut_mode: str
    print_sensor_source: str
    print_sensor_status_path: str
    print_sensor_serial_path: str
    print_sensor_precheck: str
    print_sensor_postcheck: str
    stock_module_mode: str
    stock_unavailable_item_ids: list[str]
    payment_cash_mode: str
    notify_email_mode: str
    db_path: str
    menu_item_1_name: str
    menu_item_1_description: str
    menu_item_1_price: int
    menu_item_2_name: str
    menu_item_2_description: str
    menu_item_2_price: int


def build_pilot_config() -> PilotConfig:
    heartbeat_interval_seconds = int(os.environ.get("P4P_HEARTBEAT_INTERVAL_SECONDS", "60"))
    node_private_key = load_node_private_key()
    resolved_modules = resolve_enabled_modules(env_list("P4P_NODE_MODULES", ["p4p.payment.cash"]))

    hardware_profile = resolve_hardware_profile(env_str("P4P_HARDWARE_PROFILE", "reference_printer"))
    print_module_target = env_str("P4P_PRINT_MODULE_TARGET", hardware_profile.print_module_target)
    print_module_driver = env_str("P4P_PRINT_MODULE_DRIVER", hardware_profile.print_module_driver)
    print_escpos_cut_mode = env_str("P4P_PRINT_ESCPOS_CUT_MODE", hardware_profile.print_escpos_cut_mode)
    print_sensor_source = env_str("P4P_PRINT_SENSOR_SOURCE", hardware_profile.print_sensor_source)
    hardware_profile_customized = any(
        (
            print_module_target != hardware_profile.print_module_target,
            print_module_driver != hardware_profile.print_module_driver,
            print_escpos_cut_mode != hardware_profile.print_escpos_cut_mode,
            print_sensor_source != hardware_profile.print_sensor_source,
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
        node_id=env_str("P4P_NODE_ID", "dk-brondby-kebab-001"),
        node_name=env_str("P4P_NODE_NAME", "P4P Pilot Kebab"),
        node_lat=env_float("P4P_NODE_LAT", 55.6517),
        node_lng=env_float("P4P_NODE_LNG", 12.4126),
        node_country=env_str("P4P_NODE_COUNTRY", "DK"),
        node_city=env_str("P4P_NODE_CITY", "Brondby"),
        node_categories=env_list("P4P_NODE_CATEGORIES", ["kebab"]),
        node_open_default=env_str("P4P_NODE_OPEN", "true").lower() == "true",
        node_order_mode_default=env_str("P4P_NODE_ORDER_MODE", "menu_only"),
        node_modules=list(resolved_modules.module_ids),
        public_node_modules=resolved_modules.public_module_ids(),
        resolved_modules=resolved_modules,
        hardware_profile=hardware_profile.profile_id,
        hardware_profile_customized=hardware_profile_customized,
        print_module_target=print_module_target,
        print_module_driver=print_module_driver,
        print_module_mode=env_str("P4P_PRINT_MODULE_MODE", "confirmed"),
        print_spool_dir=os.environ.get("P4P_PRINT_SPOOL_DIR", "").strip(),
        print_device_path=os.environ.get("P4P_PRINT_DEVICE_PATH", "").strip(),
        print_escpos_cut_mode=print_escpos_cut_mode,
        print_sensor_source=print_sensor_source,
        print_sensor_status_path=os.environ.get("P4P_PRINT_SENSOR_STATUS_PATH", "").strip(),
        print_sensor_serial_path=os.environ.get("P4P_PRINT_SENSOR_SERIAL_PATH", "").strip(),
        print_sensor_precheck=env_str("P4P_PRINT_SENSOR_PRECHECK", "ok"),
        print_sensor_postcheck=env_str("P4P_PRINT_SENSOR_POSTCHECK", "confirmed"),
        stock_module_mode=env_str("P4P_STOCK_MODULE_MODE", "validated"),
        stock_unavailable_item_ids=env_list("P4P_STOCK_UNAVAILABLE_ITEM_IDS", []),
        payment_cash_mode=env_str("P4P_PAYMENT_CASH_MODE", "pay_at_pickup"),
        notify_email_mode=env_str("P4P_NOTIFY_EMAIL_MODE", "sent"),
        db_path=os.environ.get("P4P_PILOT_NODE_DB_PATH", ":memory:"),
        menu_item_1_name=env_str("P4P_MENU_ITEM_1_NAME", "Kebab pita"),
        menu_item_1_description=env_str("P4P_MENU_ITEM_1_DESCRIPTION", "Kebab, salat, dressing"),
        menu_item_1_price=int(env_str("P4P_MENU_ITEM_1_PRICE", "65")),
        menu_item_2_name=env_str("P4P_MENU_ITEM_2_NAME", "Durum kebab"),
        menu_item_2_description=env_str("P4P_MENU_ITEM_2_DESCRIPTION", "Kebab, salat, dressing"),
        menu_item_2_price=int(env_str("P4P_MENU_ITEM_2_PRICE", "75")),
    )


__all__ = ["OperatorStateUpdate", "PilotConfig", "build_pilot_config", "load_node_private_key"]
