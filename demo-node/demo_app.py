from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import httpx

P4P_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = Path(__file__).resolve().parent / "app"
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from p4p_core import OrderAccepted, OrderItem, OrderRejected, OrderRequest, utc_now
from p4p_identity import sign_payload

from demo_node.config import OperatorStateUpdate
from demo_node.routes import (
    build_app,
    health as _health,
    info as _info,
    menu as _menu,
    operator as _operator,
    operator_reannounce as _operator_reannounce,
    operator_state as _operator_state,
    operator_update_state as _operator_update_state,
    order as _order,
    require_operator_token as _require_operator_token,
    run_registry_cycle as _run_registry_cycle,
)
from demo_node.runtime import (
    build_demo_runtime,
    build_node_delegation as _build_node_delegation,
    build_node_manifest as _build_node_manifest,
    build_root_rotation as _build_root_rotation,
    sign_node_announcement as _sign_node_announcement,
    signed_heartbeat_payload as _signed_heartbeat_payload,
    signed_node_manifest_request as _signed_node_manifest_request,
)


RUNTIME = build_demo_runtime()

NODE = RUNTIME.node
NODE_MANIFEST = RUNTIME.node_manifest
NODE_PRIVATE_KEY = RUNTIME.config.node_private_key
NODE_PUBLIC_KEY = RUNTIME.config.node_public_key
ROOT_PRIVATE_KEY = RUNTIME.config.root_private_key
ROOT_PUBLIC_KEY = RUNTIME.config.root_public_key
REGISTRY_URLS = RUNTIME.config.registry_urls
REGISTRATION = RUNTIME.registration
OPERATOR_ENABLED = RUNTIME.config.operator_enabled
OPERATOR_TOKEN = RUNTIME.config.operator_token

app = build_app(RUNTIME)


def build_node_delegation(**kwargs):
    return _build_node_delegation(runtime=RUNTIME, **kwargs)


def build_node_manifest(**kwargs):
    return _build_node_manifest(runtime=RUNTIME, **kwargs)


def build_root_rotation(**kwargs):
    return _build_root_rotation(runtime=RUNTIME, **kwargs)


def sign_node_announcement():
    return _sign_node_announcement(RUNTIME)


def signed_heartbeat_payload():
    return _signed_heartbeat_payload(RUNTIME)


def signed_node_manifest_request(**kwargs):
    return _signed_node_manifest_request(runtime=RUNTIME, **kwargs)


async def run_registry_cycle(*, force_announce: bool):
    return await _run_registry_cycle(RUNTIME, force_announce=force_announce)


def require_operator_token(authorization=None, x_p4p_operator_token=None):
    return _require_operator_token(
        RUNTIME,
        authorization=authorization,
        x_p4p_operator_token=x_p4p_operator_token,
    )


def health(response):
    return _health(RUNTIME, response)


def operator():
    return _operator(RUNTIME)


def operator_state():
    return _operator_state(RUNTIME)


async def operator_update_state(payload: OperatorStateUpdate):
    return await _operator_update_state(RUNTIME, payload)


async def operator_reannounce():
    return await _operator_reannounce(RUNTIME)


def menu():
    return _menu(RUNTIME)


def order(payload: OrderRequest) -> OrderAccepted | OrderRejected:
    return _order(RUNTIME, payload)


def info():
    return _info(RUNTIME)


__all__ = [
    "NODE",
    "NODE_MANIFEST",
    "NODE_PRIVATE_KEY",
    "NODE_PUBLIC_KEY",
    "OPERATOR_ENABLED",
    "OPERATOR_TOKEN",
    "OrderItem",
    "OrderRequest",
    "OperatorStateUpdate",
    "REGISTRATION",
    "REGISTRY_URLS",
    "ROOT_PRIVATE_KEY",
    "ROOT_PUBLIC_KEY",
    "app",
    "build_node_delegation",
    "build_node_manifest",
    "build_root_rotation",
    "health",
    "httpx",
    "info",
    "menu",
    "operator",
    "operator_reannounce",
    "operator_state",
    "operator_update_state",
    "order",
    "require_operator_token",
    "run_registry_cycle",
    "sign_node_announcement",
    "sign_payload",
    "signed_heartbeat_payload",
    "signed_node_manifest_request",
    "timedelta",
    "utc_now",
]
