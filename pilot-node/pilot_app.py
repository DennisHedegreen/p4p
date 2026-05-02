from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import httpx

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_core import ModuleResultEvent, OrderItem, OrderRequest, OrderStatusUpdate

from pilot_node.config import OperatorStateUpdate
from pilot_node.routes import (
    build_app,
    operator_order_events as _operator_order_events,
    operator_orders as _operator_orders,
    operator_reannounce as _operator_reannounce,
    operator_state as _operator_state,
    operator_update_order as _operator_update_order,
    operator_update_state as _operator_update_state,
    public_info as _public_info,
    public_menu as _public_menu,
    public_order as _public_order,
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


def public_order(payload: OrderRequest):
    return _public_order(RUNTIME, payload)


def public_info():
    return _public_info(RUNTIME)


def operator_state(authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return _operator_state(RUNTIME)


async def operator_update_state(payload: OperatorStateUpdate, authorization=None, x_p4p_operator_token=None):
    _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )
    return await _operator_update_state(RUNTIME, payload)


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
    "OrderItem",
    "OrderRequest",
    "OrderStatusUpdate",
    "ModuleResultEvent",
    "REGISTRATION",
    "app",
    "httpx",
    "node_state",
    "operator_order_events",
    "operator_orders",
    "operator_reannounce",
    "operator_state",
    "operator_update_order",
    "operator_update_state",
    "public_info",
    "public_menu",
    "public_order",
    "root_index",
    "run_registry_cycle",
    "sqlite3",
    "store",
]
