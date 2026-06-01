from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from p4p_core import Menu, OrderAccepted, OrderRejected, OrderRequest, build_cors_middleware_options, normalize_module_ids, utc_now
from p4p_core.constants import PROTOCOL_VERSION

from demo_node.config import OperatorStateUpdate
from demo_node.runtime import (
    DemoRuntime,
    node_accepts_orders,
    operator_state_payload,
    public_module_projection,
    registration_payload,
    sign_node_announcement,
    signed_heartbeat_payload,
    signed_node_manifest_request,
)


def header_value(value: str | None) -> str | None:
    return value if isinstance(value, str) else None


def require_operator_enabled(runtime: DemoRuntime) -> None:
    if not runtime.config.operator_enabled:
        raise HTTPException(status_code=404, detail="operator disabled")


def require_operator_token(
    runtime: DemoRuntime,
    authorization: str | None = Header(default=None),
    x_p4p_operator_token: str | None = Header(default=None),
) -> None:
    require_operator_enabled(runtime)
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


async def announce_registry(runtime: DemoRuntime, client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(f"{registry_url.rstrip('/')}/announce", json=sign_node_announcement(runtime))
    response.raise_for_status()


async def publish_manifest_registry(runtime: DemoRuntime, client: httpx.AsyncClient, registry_url: str) -> None:
    payload = signed_node_manifest_request(runtime=runtime)
    if payload is None:
        return
    response = await client.post(f"{registry_url.rstrip('/')}/node-manifest", json=payload)
    if response.status_code == status.HTTP_409_CONFLICT:
        return
    response.raise_for_status()


async def heartbeat_registry(runtime: DemoRuntime, client: httpx.AsyncClient, registry_url: str) -> None:
    response = await client.post(
        f"{registry_url.rstrip('/')}/heartbeat",
        json=signed_heartbeat_payload(runtime),
    )
    if response.status_code == status.HTTP_404_NOT_FOUND:
        await publish_manifest_registry(runtime, client, registry_url)
        await announce_registry(runtime, client, registry_url)
        response = await client.post(
            f"{registry_url.rstrip('/')}/heartbeat",
            json=signed_heartbeat_payload(runtime),
        )
    response.raise_for_status()


async def run_registry_cycle(runtime: DemoRuntime, *, force_announce: bool) -> None:
    registered: list[str] = []
    failed: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for registry_url in runtime.config.registry_urls:
            try:
                if force_announce:
                    await publish_manifest_registry(runtime, client, registry_url)
                    await announce_registry(runtime, client, registry_url)
                await heartbeat_registry(runtime, client, registry_url)
            except Exception as exc:
                failed[registry_url] = describe_http_error(exc)
                continue
            registered.append(registry_url)

    runtime.registration.update(registered, failed)


async def heartbeat_loop(runtime: DemoRuntime) -> None:
    while True:
        try:
            await run_registry_cycle(runtime, force_announce=False)
        except Exception as exc:
            print(f"[p4p-demo-node] heartbeat cycle failed: {exc}")
        await asyncio.sleep(runtime.config.heartbeat_interval_seconds)


def build_app_lifespan(runtime: DemoRuntime):
    @asynccontextmanager
    async def app_lifespan(_: FastAPI):
        try:
            await run_registry_cycle(runtime, force_announce=True)
            print(
                f"[p4p-demo-node] announced {runtime.node.node_id} to registries: "
                f"{', '.join(runtime.registration.registered_registries) or 'none'}"
            )
        except Exception as exc:
            print(f"[p4p-demo-node] startup cycle failed: {exc}")

        runtime.heartbeat_task = asyncio.create_task(heartbeat_loop(runtime))
        try:
            yield
        finally:
            if runtime.heartbeat_task is not None:
                runtime.heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await runtime.heartbeat_task
                runtime.heartbeat_task = None

    return app_lifespan


def health(runtime: DemoRuntime, response: Response) -> dict[str, Any]:
    ready = runtime.registration.ready()
    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "protocol_version": PROTOCOL_VERSION,
        "node_id": runtime.node.node_id,
        "order_mode": runtime.node.order_mode,
        "accepts_orders": node_accepts_orders(runtime),
        "node_public_key": runtime.config.node_public_key,
        "root_public_key": runtime.config.root_public_key,
        "delegation_role": runtime.node.delegation.role if runtime.node.delegation else None,
        "manifest_version": runtime.node_manifest.manifest_version if runtime.node_manifest else None,
        "manifest_key_status": runtime.node_manifest.keys[0].status if runtime.node_manifest else None,
        **public_module_projection(runtime),
        **registration_payload(runtime),
    }


def operator(runtime: DemoRuntime) -> str:
    require_operator_enabled(runtime)
    return runtime.config.operator_html.read_text(encoding="utf-8")


def operator_state(runtime: DemoRuntime) -> dict[str, Any]:
    return operator_state_payload(runtime)


async def operator_update_state(runtime: DemoRuntime, payload: OperatorStateUpdate) -> dict[str, Any]:
    runtime.node.open = payload.open
    runtime.node.order_mode = payload.order_mode
    runtime.node.modules = normalize_module_ids(payload.modules)
    await run_registry_cycle(runtime, force_announce=True)
    return operator_state_payload(runtime)


async def operator_reannounce(runtime: DemoRuntime) -> dict[str, Any]:
    await run_registry_cycle(runtime, force_announce=True)
    return operator_state_payload(runtime)


def menu(runtime: DemoRuntime) -> Menu:
    return runtime.menu


def order(runtime: DemoRuntime, payload: OrderRequest) -> OrderAccepted | OrderRejected:
    if not runtime.node.open:
        return OrderRejected(reason="closed", message="Vi lukker om 5 minutter.")
    if not node_accepts_orders(runtime):
        return OrderRejected(reason="orders_disabled", message="Denne node modtager ikke ordre endnu.")
    ready_at = utc_now() + timedelta(minutes=20)
    print("[p4p-demo-node] order received:", payload.model_dump())
    return OrderAccepted(
        order_id=f"test-{utc_now().strftime('%Y-%m-%d-%H%M%S')}",
        estimated_ready=ready_at,
        message="Bestilling modtaget. Klar til afhentning om 20 minutter.",
    )


def info(runtime: DemoRuntime) -> dict[str, Any]:
    return {
        "opening_hours": "11:00-22:00",
        "payment_methods": ["pay_on_pickup"],
        "fulfillment": ["pickup"],
        "node_id": runtime.node.node_id,
        "open": runtime.node.open,
        "order_mode": runtime.node.order_mode,
        "accepts_orders": node_accepts_orders(runtime),
        "node_public_key": runtime.config.node_public_key,
        "root_public_key": runtime.config.root_public_key,
        "delegation_role": runtime.node.delegation.role if runtime.node.delegation else None,
        "manifest_version": runtime.node_manifest.manifest_version if runtime.node_manifest else None,
        "manifest_key_status": runtime.node_manifest.keys[0].status if runtime.node_manifest else None,
        **public_module_projection(runtime),
        "operator_url": f"{runtime.config.node_base_url.rstrip('/')}/operator"
        if runtime.config.operator_enabled
        else None,
    }


def build_app(runtime: DemoRuntime) -> FastAPI:
    app = FastAPI(
        title="P4P Demo Node",
        version=PROTOCOL_VERSION,
        summary="Reference restaurant node for the P4P v0.1 protocol.",
        lifespan=build_app_lifespan(runtime),
    )
    app.add_middleware(CORSMiddleware, **build_cors_middleware_options())

    def operator_dependency(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> None:
        require_operator_token(
            runtime,
            authorization=authorization,
            x_p4p_operator_token=x_p4p_operator_token,
        )

    @app.get("/health")
    def health_route(response: Response) -> dict[str, Any]:
        return health(runtime, response)

    @app.get("/operator", response_class=HTMLResponse)
    def operator_route(_: None = Depends(operator_dependency)) -> str:
        return operator(runtime)

    @app.get("/operator/state")
    def operator_state_route(_: None = Depends(operator_dependency)) -> dict[str, Any]:
        return operator_state(runtime)

    @app.post("/operator/state")
    async def operator_update_state_route(
        payload: OperatorStateUpdate,
        _: None = Depends(operator_dependency),
    ) -> dict[str, Any]:
        return await operator_update_state(runtime, payload)

    @app.post("/operator/reannounce")
    async def operator_reannounce_route(_: None = Depends(operator_dependency)) -> dict[str, Any]:
        return await operator_reannounce(runtime)

    @app.get("/p4p/menu", response_model=Menu)
    def menu_route() -> Menu:
        return menu(runtime)

    @app.post("/p4p/order", response_model=OrderAccepted | OrderRejected)
    def order_route(payload: OrderRequest) -> OrderAccepted | OrderRejected:
        return order(runtime, payload)

    @app.get("/p4p/info")
    def info_route() -> dict[str, Any]:
        return info(runtime)

    return app


__all__ = [
    "build_app",
    "build_app_lifespan",
    "announce_registry",
    "describe_http_error",
    "health",
    "httpx",
    "info",
    "menu",
    "operator",
    "operator_reannounce",
    "operator_state",
    "operator_update_state",
    "order",
    "require_operator_enabled",
    "require_operator_token",
    "run_registry_cycle",
]
