from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from p4p_core import (
    env_float,
    env_list,
    env_path,
    env_str,
    load_reference_module_catalog,
    load_registry_urls,
    normalize_currency_code,
    normalize_module_ids,
)
from p4p_core.constants import OrderMode
from p4p_identity import load_or_create_private_key, public_key_from_private


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


class OperatorStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool
    order_mode: OrderMode
    modules: list[str] = Field(default_factory=list)

    @field_validator("modules")
    @classmethod
    def normalize_modules(cls, values: list[str]) -> list[str]:
        return normalize_module_ids(values)


@dataclass(frozen=True)
class DemoConfig:
    node_base_url: str
    heartbeat_interval_seconds: int
    readiness_stale_after_seconds: int
    order_modes: tuple[str, ...]
    reference_modules: tuple[str, ...]
    operator_html: Path
    registry_urls: list[str]
    node_private_key: str
    node_public_key: str
    root_private_key: str | None
    root_public_key: str | None
    operator_enabled: bool
    operator_token: str
    node_id: str
    node_name: str
    node_lat: float
    node_lng: float
    node_country: str
    node_city: str
    node_categories: list[str]
    node_open: bool
    node_order_mode: str
    node_modules: list[str]
    menu_currency: str
    menu_item_1_id: str
    menu_item_1_name: str
    menu_item_1_description: str
    menu_item_1_price: int
    menu_item_2_id: str
    menu_item_2_name: str
    menu_item_2_description: str
    menu_item_2_price: int


def build_demo_config() -> DemoConfig:
    heartbeat_interval_seconds = int(os.environ.get("P4P_HEARTBEAT_INTERVAL_SECONDS", "60"))
    node_private_key = load_node_private_key()
    root_private_key = load_root_private_key()
    reference_modules = tuple(
        sorted(
            manifest.module_id
            for manifest in load_reference_module_catalog().values()
            if manifest.is_public()
        )
    )
    return DemoConfig(
        node_base_url=os.environ.get("P4P_NODE_BASE_URL", "http://127.0.0.1:8001"),
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        readiness_stale_after_seconds=heartbeat_interval_seconds + 5,
        order_modes=("disabled", "menu_only", "test", "live"),
        reference_modules=reference_modules,
        operator_html=Path(__file__).resolve().parents[1] / "demo-node/operator.html",
        registry_urls=load_registry_urls(),
        node_private_key=node_private_key,
        node_public_key=public_key_from_private(node_private_key),
        root_private_key=root_private_key,
        root_public_key=public_key_from_private(root_private_key) if root_private_key else None,
        operator_enabled=env_str("P4P_OPERATOR_ENABLED", "false").lower() == "true",
        operator_token=os.environ.get("P4P_OPERATOR_TOKEN", "").strip(),
        node_id=env_str("P4P_NODE_ID", "dk-brondby-test-001"),
        node_name=env_str("P4P_NODE_NAME", "P4P Test Pizzeria"),
        node_lat=env_float("P4P_NODE_LAT", 55.6517),
        node_lng=env_float("P4P_NODE_LNG", 12.4126),
        node_country=env_str("P4P_NODE_COUNTRY", "DK"),
        node_city=env_str("P4P_NODE_CITY", "Brondby"),
        node_categories=env_list("P4P_NODE_CATEGORIES", ["pizza", "kebab"]),
        node_open=env_str("P4P_NODE_OPEN", "true").lower() == "true",
        node_order_mode=env_str("P4P_NODE_ORDER_MODE", "test"),
        node_modules=normalize_module_ids(env_list("P4P_NODE_MODULES", [])),
        menu_currency=normalize_currency_code(env_str("P4P_MENU_CURRENCY", "DKK")),
        menu_item_1_id=env_str("P4P_MENU_ITEM_1_ID", "margherita"),
        menu_item_1_name=env_str("P4P_MENU_ITEM_1_NAME", "Margherita"),
        menu_item_1_description=env_str("P4P_MENU_ITEM_1_DESCRIPTION", "Tomat, mozzarella, oregano"),
        menu_item_1_price=int(env_str("P4P_MENU_ITEM_1_PRICE", "7500")),
        menu_item_2_id=env_str("P4P_MENU_ITEM_2_ID", "vesuvio"),
        menu_item_2_name=env_str("P4P_MENU_ITEM_2_NAME", "Vesuvio"),
        menu_item_2_description=env_str("P4P_MENU_ITEM_2_DESCRIPTION", "Tomat, ost, skinke"),
        menu_item_2_price=int(env_str("P4P_MENU_ITEM_2_PRICE", "8500")),
    )


__all__ = [
    "DemoConfig",
    "OperatorStateUpdate",
    "build_demo_config",
    "load_node_private_key",
    "load_root_private_key",
]
