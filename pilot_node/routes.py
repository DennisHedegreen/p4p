from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from p4p_core import (
    Menu,
    MenuUpdate,
    ModuleResultEvent,
    OrderAccepted,
    OrderRejected,
    OrderRequest,
    OrderStatusUpdate,
    StoredOrder,
    build_cors_middleware_options,
    utc_now,
)
from p4p_core.constants import PROTOCOL_VERSION

from pilot_node.config import OperatorStateUpdate
from pilot_node.execution import (
    NOTIFY_EMAIL_MODULE_ID,
    PAYMENT_CASH_MODULE_ID,
    PRINT_MODULE_ID,
    STOCK_BASIC_MODULE_ID,
    process_accepted_order,
)
from pilot_node.runtime import (
    PilotRuntime,
    enabled_module_declarations,
    node_accepts_orders,
    node_state,
    public_module_projection,
    public_module_declarations,
    registration_payload,
    sign_node_announcement,
    signed_heartbeat_payload,
)


def header_value(value: str | None) -> str | None:
    return value if isinstance(value, str) else None


def require_operator_token(
    runtime: PilotRuntime,
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> None:
    if not runtime.config.operator_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator token is not configured",
        )
    authorization = header_value(authorization)
    token = header_value(x_p4p_operator_token)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not secrets.compare_digest(token, runtime.config.operator_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")


def describe_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text.strip()
        return f"{exc.response.status_code} {detail}".strip()
    return str(exc)


async def announce_registry(runtime: PilotRuntime, client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(f"{registry_url.rstrip('/')}/announce", json=sign_node_announcement(runtime))
    response.raise_for_status()


async def heartbeat_registry(runtime: PilotRuntime, client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(
        f"{registry_url.rstrip('/')}/heartbeat",
        json=signed_heartbeat_payload(runtime),
    )
    if response.status_code == status.HTTP_404_NOT_FOUND:
        await announce_registry(runtime, client, registry_url)
        response = await client.post(
            f"{registry_url.rstrip('/')}/heartbeat",
            json=signed_heartbeat_payload(runtime),
        )
    response.raise_for_status()


async def run_registry_cycle(runtime: PilotRuntime, *, force_announce: bool) -> None:
    registered: list[str] = []
    failed: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for registry_url in runtime.config.registry_urls:
            try:
                if force_announce:
                    await announce_registry(runtime, client, registry_url)
                await heartbeat_registry(runtime, client, registry_url)
            except Exception as exc:
                failed[registry_url] = describe_http_error(exc)
                continue
            registered.append(registry_url)
    runtime.registration.update(registered, failed)


async def heartbeat_loop(runtime: PilotRuntime) -> None:
    while True:
        try:
            await run_registry_cycle(runtime, force_announce=False)
        except Exception as exc:
            print(f"[p4p-pilot-node] heartbeat cycle failed: {exc}")
        await asyncio.sleep(runtime.config.heartbeat_interval_seconds)


def build_app_lifespan(runtime: PilotRuntime):
    @asynccontextmanager
    async def app_lifespan(_: FastAPI):
        try:
            await run_registry_cycle(runtime, force_announce=True)
            runtime.heartbeat_task = asyncio.create_task(heartbeat_loop(runtime))
            yield
        finally:
            if runtime.heartbeat_task is not None:
                runtime.heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await runtime.heartbeat_task
                runtime.heartbeat_task = None
            runtime.store.close()

    return app_lifespan


def public_menu(runtime: PilotRuntime) -> Menu:
    return runtime.store.menu()


def root_index(runtime: PilotRuntime) -> dict[str, Any]:
    node = node_state(runtime)
    return {
        "service": "p4p-pilot-node",
        "node_id": node.node_id,
        "open": node.open,
        "order_mode": node.order_mode,
        "accepts_orders": node_accepts_orders(runtime, node),
        "endpoints": {
            "health": "GET /health",
            "info": "GET /p4p/info",
            "menu": "GET /p4p/menu",
            "order": "POST /p4p/order",
            "operator_state": "GET /operator/state",
            "operator_modules": "GET /operator/modules",
            "operator_orders": "GET /operator/orders",
            "operator_reannounce": "POST /operator/reannounce",
        },
    }


def public_payment_methods(runtime: PilotRuntime) -> list[str]:
    if runtime.config.payment_module_id and runtime.config.payment_module_id != PAYMENT_CASH_MODULE_ID:
        return ["external_test_payment"]
    return ["pay_at_pickup"]


def public_order(runtime: PilotRuntime, payload: OrderRequest) -> OrderAccepted | OrderRejected:
    node = node_state(runtime)
    if not node.open:
        return OrderRejected(reason="closed", message="Restaurant is closed.")
    if node.order_mode not in {"test", "live"}:
        return OrderRejected(reason="orders_disabled", message="Restaurant is not accepting orders right now.")
    order = runtime.store.create_order(payload)
    order = process_accepted_order(runtime, order)
    return OrderAccepted(
        order_id=order.order_id,
        estimated_ready=order.estimated_ready or (utc_now() + timedelta(minutes=20)),
        message=order.status_message or "Order received.",
    )


def public_info(runtime: PilotRuntime) -> dict[str, Any]:
    node = node_state(runtime)
    return {
        "node_id": node.node_id,
        "open": node.open,
        "order_mode": node.order_mode,
        "accepts_orders": node_accepts_orders(runtime, node),
        "payment_methods": public_payment_methods(runtime),
        "fulfillment": ["pickup"],
        "node_public_key": runtime.config.node_public_key,
        **public_module_projection(runtime),
    }


def operator_state(runtime: PilotRuntime) -> dict[str, Any]:
    node = node_state(runtime)
    return {
        "node": node.model_dump(mode="json", exclude_none=True),
        "accepts_orders": node_accepts_orders(runtime, node),
        "enabled_modules": runtime.config.node_modules,
        "public_modules": runtime.config.public_node_modules,
        "module_declarations": enabled_module_declarations(runtime),
        "public_module_declarations": public_module_declarations(runtime),
        "undeclared_modules": runtime.config.undeclared_node_modules,
        "registry": registration_payload(runtime),
    }


def module_execution_lane(manifest) -> str:
    module_class = str(manifest.raw.get("module_class") or manifest.raw.get("type") or "").strip()
    if module_class == "payment":
        return "payment"
    return manifest.lane


def module_entrypoint(manifest) -> str:
    entrypoint = manifest.raw.get("entrypoint")
    return entrypoint.strip() if isinstance(entrypoint, str) else ""


def external_health_url(entrypoint: str) -> str:
    parts = urlsplit(entrypoint)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/health"


def module_configuration(runtime: PilotRuntime, manifest) -> tuple[bool, list[str]]:
    lane = module_execution_lane(manifest)
    if lane != "payment":
        return True, []
    if manifest.module_id == PAYMENT_CASH_MODULE_ID:
        return True, []

    missing: list[str] = []
    entrypoint = module_entrypoint(manifest)
    if manifest.module_id == runtime.config.payment_module_id:
        if not runtime.config.payment_external_url:
            missing.append("payment_external_url")
        if not runtime.config.payment_external_customer_user_id:
            missing.append("payment_external_customer_user_id")
    elif not entrypoint:
        missing.append("entrypoint")

    return not missing, missing


def module_active(runtime: PilotRuntime, manifest) -> bool:
    if module_execution_lane(manifest) == "payment":
        return manifest.module_id == runtime.config.payment_module_id
    return manifest.module_id in runtime.config.flow_module_ids


def module_health(runtime: PilotRuntime, manifest, *, active: bool, configured: bool) -> dict[str, Any]:
    if manifest.module_id == PAYMENT_CASH_MODULE_ID:
        return {
            "health": "available",
            "health_reason": "builtin_reference_module",
            "health_url": None,
            "last_checked_at": None,
        }
    if module_execution_lane(manifest) != "payment":
        return {
            "health": "available",
            "health_reason": "enabled_manifest",
            "health_url": None,
            "last_checked_at": None,
        }
    if not active:
        return {
            "health": "not_checked",
            "health_reason": "module_not_active",
            "health_url": None,
            "last_checked_at": None,
        }
    if not configured:
        return {
            "health": "not_configured",
            "health_reason": "required_configuration_missing",
            "health_url": None,
            "last_checked_at": None,
        }

    health_url = external_health_url(runtime.config.payment_external_url or module_entrypoint(manifest))
    checked_at = utc_now().isoformat()
    if not health_url:
        return {
            "health": "unknown",
            "health_reason": "no_health_endpoint",
            "health_url": None,
            "last_checked_at": checked_at,
        }

    try:
        timeout = min(max(runtime.config.payment_external_timeout_seconds, 0.25), 2.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.get(health_url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {
            "health": "down",
            "health_reason": describe_http_error(exc),
            "health_url": health_url,
            "last_checked_at": checked_at,
        }

    if isinstance(payload, dict) and payload.get("ok") is True:
        return {
            "health": "up",
            "health_reason": "external_health_ok",
            "health_url": health_url,
            "last_checked_at": checked_at,
        }
    return {
        "health": "degraded",
        "health_reason": "external_health_did_not_report_ok",
        "health_url": health_url,
        "last_checked_at": checked_at,
    }


BUILTIN_EXECUTOR_MODULE_IDS = frozenset(
    {
        PAYMENT_CASH_MODULE_ID,
        PRINT_MODULE_ID,
        STOCK_BASIC_MODULE_ID,
        NOTIFY_EMAIL_MODULE_ID,
    }
)


def operator_module_entry(runtime: PilotRuntime, manifest) -> dict[str, Any]:
    lane = module_execution_lane(manifest)
    active = module_active(runtime, manifest)
    configured, missing_configuration = module_configuration(runtime, manifest)
    implementation = "builtin_reference" if manifest.module_id in BUILTIN_EXECUTOR_MODULE_IDS else "external_http"
    if manifest.module_id not in BUILTIN_EXECUTOR_MODULE_IDS and lane != "payment" and not module_entrypoint(manifest):
        implementation = "manifest_only"
    executable = active and configured and implementation != "manifest_only"
    health = module_health(runtime, manifest, active=active, configured=configured)
    return {
        "module_id": manifest.module_id,
        "provider_id": manifest.provider_id,
        "version": manifest.version,
        "lane": lane,
        "declared": True,
        "active": active,
        "configured": configured,
        "executable": executable,
        "implementation": implementation,
        "visibility": manifest.visibility,
        "readiness": manifest.readiness,
        "status": manifest.status,
        "description": manifest.description,
        "operator_status": manifest.operator_status,
        "missing_configuration": missing_configuration,
        "suggested_fallbacks": {
            event_name: list(module_ids)
            for event_name, module_ids in manifest.suggested_fallbacks.items()
        },
        **health,
    }


def undeclared_module_entry(runtime: PilotRuntime, module_id: str) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "provider_id": None,
        "version": None,
        "lane": "unknown",
        "declared": False,
        "active": False,
        "configured": False,
        "executable": False,
        "implementation": "undeclared",
        "visibility": "operator_only",
        "readiness": "unknown",
        "status": "undeclared",
        "description": "Enabled by this node, but no local or reference manifest was loaded.",
        "operator_status": "manifest required before execution or public declaration",
        "missing_configuration": ["module_manifest"],
        "health": "undeclared",
        "health_reason": "module_manifest_missing",
        "health_url": None,
        "last_checked_at": None,
        "suggested_fallbacks": {},
    }


def operator_modules(runtime: PilotRuntime) -> dict[str, Any]:
    declared = [
        operator_module_entry(runtime, manifest)
        for manifest in runtime.config.resolved_modules.manifests
    ]
    undeclared = [
        undeclared_module_entry(runtime, module_id)
        for module_id in runtime.config.undeclared_node_modules
    ]
    modules = declared + undeclared
    lanes: dict[str, dict[str, Any]] = {}
    for entry in modules:
        lane = str(entry["lane"])
        lane_payload = lanes.setdefault(
            lane,
            {
                "active_module_id": runtime.config.payment_module_id if lane == "payment" else None,
                "modules": [],
            },
        )
        lane_payload["modules"].append(entry)

    return {
        "node_id": runtime.config.node_id,
        "checked_at": utc_now().isoformat(),
        "active_by_lane": {
            "payment": runtime.config.payment_module_id or None,
        },
        "modules": modules,
        "lanes": lanes,
        "undeclared_modules": undeclared,
    }


async def operator_update_state(runtime: PilotRuntime, payload: OperatorStateUpdate) -> dict[str, Any]:
    if payload.open is not None:
        runtime.store.set_state("open", "true" if payload.open else "false")
    if payload.order_mode is not None:
        runtime.store.set_state("order_mode", payload.order_mode)
    await run_registry_cycle(runtime, force_announce=True)
    return operator_state(runtime)


def operator_menu(runtime: PilotRuntime) -> Menu:
    return runtime.store.menu(include_inactive=True)


def operator_replace_menu(runtime: PilotRuntime, payload: MenuUpdate) -> Menu:
    return runtime.store.replace_menu(payload.items)


def operator_orders(runtime: PilotRuntime) -> list[StoredOrder]:
    return runtime.store.list_orders()


def operator_order_events(runtime: PilotRuntime, order_id: str) -> list[ModuleResultEvent]:
    if runtime.store.get_order(order_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown order_id: {order_id}")
    return runtime.store.list_order_events(order_id)


def operator_update_order(
    runtime: PilotRuntime,
    order_id: str,
    payload: OrderStatusUpdate,
) -> StoredOrder:
    return runtime.store.update_order_status(order_id, payload)


async def operator_reannounce(runtime: PilotRuntime) -> dict[str, Any]:
    await run_registry_cycle(runtime, force_announce=True)
    return registration_payload(runtime)


def build_app(runtime: PilotRuntime) -> FastAPI:
    app = FastAPI(
        title="P4P Pilot Node",
        version=PROTOCOL_VERSION,
        summary="Restaurant-owned node for the P4P live pilot.",
        lifespan=build_app_lifespan(runtime),
    )
    app.add_middleware(CORSMiddleware, **build_cors_middleware_options())

    def require_auth(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> None:
        require_operator_token(
            runtime,
            authorization=authorization,
            x_p4p_operator_token=x_p4p_operator_token,
        )

    @app.get("/")
    def root_index_route() -> dict[str, Any]:
        return root_index(runtime)

    @app.get("/health")
    def health(response: Response) -> dict[str, Any]:
        ready = runtime.registration.ready()
        node = node_state(runtime)
        response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if ready else "not_ready",
            "protocol_version": PROTOCOL_VERSION,
            "node_id": node.node_id,
            "open": node.open,
            "order_mode": node.order_mode,
            "accepts_orders": node_accepts_orders(runtime, node),
            "operator_configured": bool(runtime.config.operator_token),
            "node_public_key": runtime.config.node_public_key,
            **public_module_projection(runtime),
            **registration_payload(runtime),
        }

    @app.get("/p4p/menu", response_model=Menu)
    def public_menu_route() -> Menu:
        return public_menu(runtime)

    @app.post("/p4p/order", response_model=OrderAccepted | OrderRejected)
    def public_order_route(payload: OrderRequest) -> OrderAccepted | OrderRejected:
        return public_order(runtime, payload)

    @app.get("/p4p/info")
    def public_info_route() -> dict[str, Any]:
        return public_info(runtime)

    @app.get("/operator/state")
    def operator_state_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_state(runtime)

    @app.get("/operator/modules")
    def operator_modules_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_modules(runtime)

    @app.patch("/operator/state")
    async def operator_update_state_route(
        payload: OperatorStateUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return await operator_update_state(runtime, payload)

    @app.get("/operator/menu", response_model=Menu)
    def operator_menu_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Menu:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_menu(runtime)

    @app.put("/operator/menu", response_model=Menu)
    def operator_replace_menu_route(
        payload: MenuUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Menu:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_replace_menu(runtime, payload)

    @app.get("/operator/orders", response_model=list[StoredOrder])
    def operator_orders_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> list[StoredOrder]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_orders(runtime)

    @app.get("/operator/orders/{order_id}/events", response_model=list[ModuleResultEvent])
    def operator_order_events_route(
        order_id: str,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> list[ModuleResultEvent]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_order_events(runtime, order_id)

    @app.patch("/operator/orders/{order_id}", response_model=StoredOrder)
    def operator_update_order_route(
        order_id: str,
        payload: OrderStatusUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> StoredOrder:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_update_order(runtime, order_id, payload)

    @app.post("/operator/reannounce")
    async def operator_reannounce_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return await operator_reannounce(runtime)

    return app


__all__ = [
    "build_app",
    "httpx",
    "operator_modules",
    "operator_order_events",
    "node_state",
    "operator_orders",
    "operator_reannounce",
    "operator_state",
    "operator_update_order",
    "operator_update_state",
    "public_info",
    "public_menu",
    "public_order",
    "require_operator_token",
    "root_index",
    "run_registry_cycle",
]
