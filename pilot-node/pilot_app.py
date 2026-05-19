from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import httpx

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_core import (
    Menu,
    MenuImportPreviewRequest,
    MenuImportPreviewResponse,
    MenuItem,
    MenuUpdate,
    ModuleResultEvent,
    OrderItem,
    OrderRequest,
    OrderStatusUpdate,
    PublicOrderStatus,
)

from pilot_node.config import (
    OperatorModuleSetUpdate,
    OperatorPaymentModuleUpdate,
    OperatorSetupUpdate,
    OperatorStateUpdate,
)
from pilot_node.routes import (
    build_app,
    operator_catalog_page as _operator_catalog_page,
    operator_discover as _operator_discover,
    operator_discover_page as _operator_discover_page,
    operator_gui as _operator_gui,
    operator_import as _operator_import,
    operator_import_page as _operator_import_page,
    operator_import_module_manifest as _operator_import_module_manifest,
    operator_delete_imported_module_manifest as _operator_delete_imported_module_manifest,
    operator_imported_manifests as _operator_imported_manifests,
    operator_node as _operator_node,
    operator_node_page as _operator_node_page,
    operator_setup as _operator_setup,
    operator_setup_page as _operator_setup_page,
    operator_update_setup as _operator_update_setup,
    operator_welcome_page as _operator_welcome_page,
    module_detail_entry as _module_detail_entry,
    operator_menu as _operator_menu,
    operator_menu_import_image_preview as _operator_menu_import_image_preview,
    operator_menu_import_preview as _operator_menu_import_preview,
    operator_module_self_test as _operator_module_self_test,
    operator_modules_page as _operator_modules_page,
    operator_module_view_page as _operator_module_view_page,
    operator_modules as _operator_modules,
    operator_order_events as _operator_order_events,
    operator_orders as _operator_orders,
    operator_pickup_board_data as _operator_pickup_board_data,
    operator_pickup_board_page as _operator_pickup_board_page,
    operator_replace_menu as _operator_replace_menu,
    operator_reannounce as _operator_reannounce,
    operator_state as _operator_state,
    operator_update_order as _operator_update_order,
    operator_update_module_set as _operator_update_module_set,
    operator_update_payment_module as _operator_update_payment_module,
    operator_update_state as _operator_update_state,
    public_info as _public_info,
    public_menu as _public_menu,
    public_menu_list_page as _public_menu_list_page,
    public_menu_photo_map_page as _public_menu_photo_map_page,
    public_order as _public_order,
    public_order_status as _public_order_status,
    public_order_status_page as _public_order_status_page,
    require_operator_token as _require_operator_token,
    root_index as _root_index,
    run_registry_cycle as _run_registry_cycle,
)
from pilot_node.runtime import build_pilot_runtime, node_state as _node_state


RUNTIME = build_pilot_runtime()

REGISTRATION = RUNTIME.registration
store = RUNTIME.store

app = build_app(RUNTIME)


def node_state():
    return _node_state(RUNTIME)


def root_index():
    return _root_index(RUNTIME)


async def run_registry_cycle(*, force_announce: bool):
    return await _run_registry_cycle(RUNTIME, force_announce=force_announce)


def public_menu():
    return _public_menu(RUNTIME)


def public_menu_list_page(*, locale: str | None = None) -> str:
    return _public_menu_list_page(RUNTIME, locale=locale)


def public_menu_photo_map_page(*, locale: str | None = None) -> str:
    return _public_menu_photo_map_page(RUNTIME, locale=locale)


def public_order(payload: OrderRequest, *, locale: str | None = None):
    return _public_order(RUNTIME, payload, locale=locale)


def public_order_status(order_id: str) -> PublicOrderStatus:
    return _public_order_status(RUNTIME, order_id)


def public_order_status_page(order_id: str, *, locale: str | None = None) -> str:
    return _public_order_status_page(RUNTIME, order_id, locale=locale)


def public_info():
    return _public_info(RUNTIME)


def operator_state(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_state(RUNTIME)


def operator_gui():
    return _operator_gui(RUNTIME)


def operator_welcome_page() -> str:
    return _operator_welcome_page(RUNTIME)


def operator_setup_page() -> str:
    return _operator_setup_page(RUNTIME)


def operator_setup(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_setup(RUNTIME)


def operator_catalog_page() -> str:
    return _operator_catalog_page(RUNTIME)


def operator_discover_page() -> str:
    return _operator_discover_page(RUNTIME)


def operator_discover(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_discover(RUNTIME)


def operator_import_page() -> str:
    return _operator_import_page(RUNTIME)


def operator_import(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_import(RUNTIME)


def operator_imported_manifests(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_imported_manifests(RUNTIME)


def operator_import_module_manifest(
    *,
    source_name: str,
    content_bytes: bytes,
    authorization=None,
    x_p4p_operator_token=None,
):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_import_module_manifest(
        RUNTIME,
        source_name=source_name,
        content_bytes=content_bytes,
    )


def operator_delete_imported_module_manifest(module_id: str, authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_delete_imported_module_manifest(RUNTIME, module_id)


def operator_node_page() -> str:
    return _operator_node_page(RUNTIME)


def operator_node(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_node(RUNTIME)


def operator_module_view_page(module_id: str) -> str:
    return _operator_module_view_page(RUNTIME, module_id)


def operator_modules_page() -> str:
    return _operator_modules_page(RUNTIME)


def operator_modules(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_modules(RUNTIME)


def operator_module_detail(module_id: str, authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _module_detail_entry(RUNTIME, module_id)


def operator_menu(authorization=None, x_p4p_operator_token=None) -> Menu:
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_menu(RUNTIME)


def operator_pickup_board_page() -> str:
    return _operator_pickup_board_page(RUNTIME)


def operator_pickup_board_data(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_pickup_board_data(RUNTIME)


def operator_replace_menu(payload: MenuUpdate, authorization=None, x_p4p_operator_token=None) -> Menu:
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_replace_menu(RUNTIME, payload)


def operator_menu_import_preview(
    payload: MenuImportPreviewRequest,
    authorization=None,
    x_p4p_operator_token=None,
) -> MenuImportPreviewResponse:
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_menu_import_preview(RUNTIME, payload)


def operator_menu_import_image_preview(
    image_bytes: bytes,
    *,
    source_name: str = "",
    authorization=None,
    x_p4p_operator_token=None,
) -> MenuImportPreviewResponse:
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_menu_import_image_preview(RUNTIME, image_bytes=image_bytes, source_name=source_name)


async def operator_update_state(payload: OperatorStateUpdate, authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return await _operator_update_state(RUNTIME, payload)


def operator_update_setup(
    payload: OperatorSetupUpdate,
    authorization=None,
    x_p4p_operator_token=None,
):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_update_setup(RUNTIME, payload)


def operator_update_payment_module(
    payload: OperatorPaymentModuleUpdate,
    authorization=None,
    x_p4p_operator_token=None,
):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_update_payment_module(RUNTIME, payload)


def operator_update_module_set(
    payload: OperatorModuleSetUpdate,
    authorization=None,
    x_p4p_operator_token=None,
):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_update_module_set(RUNTIME, payload)


def operator_orders(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_orders(RUNTIME)


def operator_order_events(
    order_id: str,
    authorization=None,
    x_p4p_operator_token=None,
) -> list[ModuleResultEvent]:
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_order_events(RUNTIME, order_id)


def operator_module_self_test(module_id: str, authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_module_self_test(RUNTIME, module_id)


def operator_update_order(order_id: str, payload: OrderStatusUpdate, authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_update_order(RUNTIME, order_id, payload)


async def operator_reannounce(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return await _operator_reannounce(RUNTIME)


__all__ = [
    "Menu",
    "MenuImportPreviewRequest",
    "MenuImportPreviewResponse",
    "MenuItem",
    "MenuUpdate",
    "OrderItem",
    "OrderRequest",
    "OrderStatusUpdate",
    "ModuleResultEvent",
    "OperatorModuleSetUpdate",
    "OperatorPaymentModuleUpdate",
    "OperatorSetupUpdate",
    "PublicOrderStatus",
    "REGISTRATION",
    "app",
    "httpx",
    "node_state",
    "operator_catalog_page",
    "operator_discover",
    "operator_discover_page",
    "operator_gui",
    "operator_import",
    "operator_import_page",
    "operator_imported_manifests",
    "operator_import_module_manifest",
    "operator_delete_imported_module_manifest",
    "operator_node",
    "operator_node_page",
    "operator_setup",
    "operator_setup_page",
    "operator_welcome_page",
    "operator_module_detail",
    "operator_menu",
    "operator_menu_import_image_preview",
    "operator_menu_import_preview",
    "operator_module_self_test",
    "operator_modules_page",
    "operator_module_view_page",
    "operator_modules",
    "operator_order_events",
    "operator_orders",
    "operator_pickup_board_data",
    "operator_pickup_board_page",
    "operator_replace_menu",
    "operator_reannounce",
    "operator_state",
    "operator_update_setup",
    "operator_update_module_set",
    "operator_update_order",
    "operator_update_payment_module",
    "operator_update_state",
    "public_info",
    "public_menu",
    "public_menu_list_page",
    "public_menu_photo_map_page",
    "public_order",
    "public_order_status",
    "public_order_status_page",
    "root_index",
    "run_registry_cycle",
    "sqlite3",
    "store",
]
