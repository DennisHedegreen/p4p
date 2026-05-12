from __future__ import annotations

import asyncio
import html
import json
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from p4p_core import (
    Menu,
    MenuImportPreviewRequest,
    MenuImportPreviewResponse,
    MenuUpdate,
    ModuleManifest,
    ModuleResultEvent,
    OrderAccepted,
    OrderRejected,
    OrderRequest,
    OrderStatusUpdate,
    PublicOrderStatus,
    StoredOrder,
    build_cors_middleware_options,
    format_money_minor,
    utc_now,
)
from p4p_core.constants import PROTOCOL_VERSION
from module_catalog import (
    PublicCatalogUrls,
    locale_direction,
    localized_module_catalog,
    localized_text,
    normalize_locale,
    operator_locale_payload,
    shell_text,
)

from pilot_node.config import (
    OperatorModuleSetUpdate,
    OperatorModuleManifestImport,
    OperatorPaymentModuleUpdate,
    OperatorSetupUpdate,
    OperatorStateUpdate,
)
from pilot_node.execution import (
    CHAOSPAY_MOCK_MODULE_ID,
    CATALOG_EDITOR_MODULE_ID,
    CATALOG_IMPORT_OCR_MODULE_ID,
    CUSTOMER_STATUS_MODULE_ID,
    GODPAY_MOCK_MODULE_ID,
    KITCHEN_SCREEN_MODULE_ID,
    MENU_LIST_MODULE_ID,
    MENU_PHOTO_MAP_MODULE_ID,
    NOTIFY_EMAIL_MODULE_ID,
    PAYMENT_CASH_MODULE_ID,
    PRINT_MODULE_ID,
    STOCK_BASIC_MODULE_ID,
    build_result_event,
    process_accepted_order,
)
from pilot_node.hardware_lanes import (
    ORDER_ALERT_BASIC_MODULE_ID,
    ORDER_PRINT_BACKUP_MODULE_ID,
    PICKUP_BOARD_BASIC_MODULE_ID,
    pickup_board_entries,
    run_backup_print_self_test,
    run_order_alert_self_test,
)
from pilot_node.menu_import import preview_menu_import, preview_menu_import_from_image
from pilot_node.runtime import (
    PilotRuntime,
    desired_module_ids,
    desired_module_ids_updated_at,
    effective_flow_module_ids,
    effective_payment_module_id,
    enabled_module_declarations,
    module_is_payment,
    module_restart_required,
    node_accepts_orders,
    node_state,
    public_module_projection,
    public_module_declarations,
    registration_payload,
    set_setup_state,
    set_desired_module_ids,
    set_effective_payment_module_id,
    sign_node_announcement,
    signed_heartbeat_payload,
    setup_state,
)
from pilot_node.state_keys import ACTIVE_PAYMENT_MODULE_STATE_KEY


P4P_ROOT = Path(__file__).resolve().parents[1]
OPERATOR_ASSETS_ROOT = P4P_ROOT / "pilot-node" / "assets"
OPERATOR_WELCOME_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-welcome.html"
OPERATOR_SETUP_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-setup.html"
OPERATOR_OPERATIONS_HTML_PATH = P4P_ROOT / "pilot-node" / "operator.html"
OPERATOR_CATALOG_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-catalog.html"
OPERATOR_MODULES_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-modules.html"
OPERATOR_DISCOVER_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-discover.html"
OPERATOR_IMPORT_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-import.html"
OPERATOR_NODE_HTML_PATH = P4P_ROOT / "pilot-node" / "operator-node.html"
MODULE_HTML_PATH = P4P_ROOT / "pilot-node" / "module.html"
PICKUP_BOARD_HTML_PATH = P4P_ROOT / "pilot-node" / "pickup_board.html"
FOOD_IMAGE_FIXTURE_ROOT = P4P_ROOT / "docs" / "examples" / "food-image-fixtures"
MODULE_DOCS_ROOT = P4P_ROOT / "docs" / "modules"
PROVIDER_DOCS_ROOT = P4P_ROOT / "docs" / "providers"
GITHUB_BLOB_BASE_URL = "https://github.com/DennisHedegreen/p4p/blob/main"
PUBLIC_CATALOG_URLS = PublicCatalogUrls()


def header_value(value: str | None) -> str | None:
    return value if isinstance(value, str) else None


def request_prefers_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/xhtml+xml" in accept


def operator_locale(runtime: PilotRuntime) -> str:
    persisted = setup_state(runtime).get("operator_locale")
    return normalize_locale(str(persisted or ""))


def operator_page_copy(runtime: PilotRuntime, *, page_title_key: str) -> dict[str, str]:
    locale = operator_locale(runtime)
    return {
        "page_lang": locale,
        "page_dir": locale_direction(locale),
        "page_title": shell_text(locale, page_title_key),
        "nav_welcome": shell_text(locale, "nav.welcome"),
        "nav_setup": shell_text(locale, "nav.setup"),
        "nav_operations": shell_text(locale, "nav.operations"),
        "nav_catalog": shell_text(locale, "nav.catalog"),
        "nav_modules": shell_text(locale, "nav.modules"),
        "nav_discover": shell_text(locale, "nav.discover"),
        "nav_import": shell_text(locale, "nav.import"),
        "nav_node": shell_text(locale, "nav.node"),
        "toolbar_token_placeholder": shell_text(locale, "toolbar.token_placeholder"),
        "toolbar_use_token": shell_text(locale, "toolbar.use_token"),
        "toolbar_clear": shell_text(locale, "toolbar.clear"),
        "toolbar_refresh": shell_text(locale, "toolbar.refresh"),
        "toolbar_copy_json": shell_text(locale, "toolbar.copy_json"),
        "toolbar_waiting": shell_text(locale, "toolbar.waiting"),
    }


def render_operator_page(
    path: Path,
    runtime: PilotRuntime,
    *,
    page_title_key: str,
    extra_context: dict[str, str] | None = None,
) -> str:
    rendered = path.read_text(encoding="utf-8")
    context = operator_page_copy(runtime, page_title_key=page_title_key)
    if extra_context:
        context.update(extra_context)
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", html.escape(value))
    return rendered


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
            "food_image_fixture": "GET /p4p/assets/food-image-fixtures/{asset_path}",
            "menu_list": "GET /p4p/menu/list",
            "menu_photo_map": "GET /p4p/menu/photo-map",
            "order": "POST /p4p/order",
            "order_status_page": "GET /p4p/orders/{order_id}",
            "order_status_json": "GET /p4p/orders/{order_id}/status",
            "operator_welcome": "GET /operator/welcome",
            "operator_setup": "GET /operator/setup",
            "operator_gui": "GET /operator",
            "operator_catalog": "GET /operator/catalog",
            "operator_discover": "GET /operator/discover",
            "operator_import": "GET /operator/import",
            "operator_node": "GET /operator/node",
            "operator_module_view": "GET /operator/modules/view/{module_id}",
            "operator_module_detail": "GET /operator/modules/{module_id}",
            "operator_pickup_board": "GET /operator/pickup-board",
            "operator_state": "GET /operator/state",
            "operator_modules": "GET /operator/modules",
            "operator_module_imports": "GET /operator/modules/imports",
            "operator_import_manifest": "POST /operator/modules/import-manifest",
            "operator_delete_imported_manifest": "DELETE /operator/modules/imports/{module_id}",
            "operator_module_set": "PATCH /operator/modules/set",
            "operator_menu_import_preview": "POST /operator/menu/import-preview",
            "operator_menu_import_image_preview": "POST /operator/menu/import-image-preview",
            "operator_payment_module": "PATCH /operator/modules/payment",
            "operator_orders": "GET /operator/orders",
            "operator_reannounce": "POST /operator/reannounce",
        },
    }


def food_image_fixture(asset_path: str) -> FileResponse:
    requested = Path(asset_path)
    if requested.is_absolute() or ".." in requested.parts or requested.suffix.lower() != ".png":
        raise HTTPException(status_code=404, detail="Unknown fixture asset")
    target = (FOOD_IMAGE_FIXTURE_ROOT / requested).resolve()
    try:
        target.relative_to(FOOD_IMAGE_FIXTURE_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown fixture asset") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Unknown fixture asset")
    return FileResponse(target, media_type="image/png")


def operator_asset(asset_path: str) -> FileResponse:
    requested = Path(asset_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise HTTPException(status_code=404, detail="Unknown operator asset")
    target = (OPERATOR_ASSETS_ROOT / requested).resolve()
    try:
        target.relative_to(OPERATOR_ASSETS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown operator asset") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Unknown operator asset")
    media_type = {
        ".css": "text/css",
        ".js": "application/javascript",
    }.get(target.suffix.lower())
    return FileResponse(target, media_type=media_type)


def public_payment_methods(runtime: PilotRuntime) -> list[str]:
    payment_module_id = effective_payment_module_id(runtime)
    if payment_module_id == GODPAY_MOCK_MODULE_ID:
        return ["internal_godpay_mock"]
    if payment_module_id == CHAOSPAY_MOCK_MODULE_ID:
        return ["internal_chaospay_mock"]
    if payment_module_id and payment_module_id != PAYMENT_CASH_MODULE_ID:
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


def customer_status_module_enabled(runtime: PilotRuntime) -> bool:
    return CUSTOMER_STATUS_MODULE_ID in effective_flow_module_ids(runtime)


def menu_list_module_enabled(runtime: PilotRuntime) -> bool:
    return MENU_LIST_MODULE_ID in effective_flow_module_ids(runtime)


def menu_photo_map_module_enabled(runtime: PilotRuntime) -> bool:
    return MENU_PHOTO_MAP_MODULE_ID in effective_flow_module_ids(runtime)


def catalog_import_ocr_module_enabled(runtime: PilotRuntime) -> bool:
    return CATALOG_IMPORT_OCR_MODULE_ID in effective_flow_module_ids(runtime)


def public_order_status(runtime: PilotRuntime, order_id: str) -> PublicOrderStatus:
    if not customer_status_module_enabled(runtime):
        raise HTTPException(status_code=404, detail="Customer status module is not enabled")
    order = runtime.store.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Unknown order_id: {order_id}")
    status_payload = PublicOrderStatus(
        order_id=order.order_id,
        status=order.status,
        status_message=order.status_message,
        fulfillment=order.fulfillment,
        payment_method=order.payment_method,
        requested_at=order.requested_at,
        updated_at=order.updated_at,
        estimated_ready=order.estimated_ready,
    )
    checked_at = utc_now()
    action_id = f"order:{order.order_id}:customer-status:{checked_at.isoformat()}"
    runtime.store.record_order_event(
        build_result_event(
            runtime=runtime,
            event="ORDER_STATUS_VIEWED",
            source_module=CUSTOMER_STATUS_MODULE_ID,
            order=order,
            action_id=action_id,
            idempotency_key=action_id,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            metadata={
                "status": order.status,
                "public_surface": CUSTOMER_STATUS_MODULE_ID,
                "exposes_customer_contact": False,
                "exposes_customer_name": False,
                "exposes_order_note": False,
                "exposes_operator_events": False,
            },
        )
    )
    return status_payload


def public_order_status_page(runtime: PilotRuntime, order_id: str) -> str:
    status_payload = public_order_status(runtime, order_id)
    status_label = status_payload.status.replace("_", " ").title()
    message = status_payload.status_message or "No status message yet."
    estimated_ready = (
        status_payload.estimated_ready.isoformat()
        if status_payload.estimated_ready is not None
        else "Not set"
    )
    escaped_order_id = html.escape(status_payload.order_id, quote=True)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>P4P Order Status</title>
    <style>
      body {{
        margin: 0;
        background: #f4f6f5;
        color: #10201d;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      main {{
        max-width: 720px;
        margin: 0 auto;
        padding: 24px 14px;
      }}
      section {{
        background: #fff;
        border: 1px solid #cfd8d5;
        border-radius: 8px;
        padding: 18px;
      }}
      h1, p {{
        margin: 0;
      }}
      .status {{
        margin: 14px 0;
        font-size: 2rem;
        font-weight: 750;
      }}
      dl {{
        display: grid;
        grid-template-columns: minmax(120px, 0.45fr) minmax(0, 1fr);
        gap: 8px 12px;
      }}
      dt {{
        color: #51615d;
      }}
      dd {{
        margin: 0;
        word-break: break-word;
      }}
      a, button {{
        color: #00594f;
        font: inherit;
        font-weight: 650;
      }}
      button {{
        min-height: 42px;
        border: 1px solid #00796b;
        border-radius: 7px;
        background: #00796b;
        color: #fff;
        padding: 0 14px;
        cursor: pointer;
      }}
      .actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 16px;
        align-items: center;
      }}
      .notice {{
        margin-top: 14px;
        color: #51615d;
        font-size: 0.92rem;
      }}
    </style>
  </head>
  <body>
    <main>
      <section>
        <h1>Order status</h1>
        <p class="status">{html.escape(status_label)}</p>
        <dl>
          <dt>Order</dt>
          <dd>{escaped_order_id}</dd>
          <dt>Message</dt>
          <dd>{html.escape(message)}</dd>
          <dt>Estimated ready</dt>
          <dd>{html.escape(estimated_ready)}</dd>
          <dt>Fulfillment</dt>
          <dd>{html.escape(status_payload.fulfillment)}</dd>
          <dt>Payment</dt>
          <dd>{html.escape(status_payload.payment_method)}</dd>
          <dt>Updated</dt>
          <dd>{html.escape(status_payload.updated_at.isoformat())}</dd>
        </dl>
        <div class="actions">
          <form method="get" action="/p4p/orders/{escaped_order_id}">
            <button type="submit">Refresh status</button>
          </form>
          <a href="/p4p/orders/{escaped_order_id}/status">JSON status</a>
        </div>
        <p class="notice">{html.escape(status_payload.customer_notice)}</p>
      </section>
    </main>
  </body>
</html>"""


def public_menu_list_page(runtime: PilotRuntime) -> str:
    if not menu_list_module_enabled(runtime):
        raise HTTPException(status_code=404, detail="Menu list module is not enabled")

    menu = public_menu(runtime)
    node = node_state(runtime)
    accepts_orders = node_accepts_orders(runtime, node)
    status_links_enabled = customer_status_module_enabled(runtime)
    checked_at = utc_now()
    action_id = f"menu-list:{checked_at.isoformat()}:view"
    runtime.store.record_order_event(
        ModuleResultEvent(
            event="CUSTOMER_MENU_VIEWED",
            source_module=MENU_LIST_MODULE_ID,
            order_id=None,
            action_id=action_id,
            idempotency_key=action_id,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            timestamp=checked_at,
            metadata={
                "active_item_count": len(menu.items),
                "category_count": len({item.category for item in menu.items}),
                "accepts_orders": accepts_orders,
                "public_surface": MENU_LIST_MODULE_ID,
                "reads_catalog_truth": True,
                "exposes_inactive_items": False,
                "owns_catalog_truth": False,
            },
        )
    )

    grouped: dict[str, list[Any]] = {}
    for item in menu.items:
        grouped.setdefault(item.category, []).append(item)

    if not menu.items:
        menu_html = '<p class="empty">No active menu items right now.</p>'
    else:
        sections: list[str] = []
        for category, items in grouped.items():
            cards: list[str] = []
            for item in items:
                price_label = html.escape(format_money_minor(item.price, menu.currency))
                item_name = html.escape(item.name, quote=True)
                image_html = (
                    f"""
            <img class="item-image" src="{html.escape(item.image_url, quote=True)}" alt="{item_name}" loading="lazy">"""
                    if item.image_url
                    else ""
                )
                item_class = "item has-image" if item.image_url else "item"
                cards.append(
                    f"""
          <article class="{item_class}" data-item-id="{html.escape(item.id, quote=True)}" data-price="{item.price}">
            {image_html}
            <div class="item-copy">
              <h3>{html.escape(item.name)}</h3>
              <p>{html.escape(item.description)}</p>
              <span>{price_label}</span>
            </div>
            <div class="stepper" aria-label="Quantity for {html.escape(item.name, quote=True)}">
              <button type="button" data-action="decrease" aria-label="Decrease {html.escape(item.name, quote=True)}">-</button>
              <output>0</output>
              <button type="button" data-action="increase" aria-label="Increase {html.escape(item.name, quote=True)}">+</button>
            </div>
          </article>"""
                )
            sections.append(
                f"""
        <section class="category" aria-labelledby="category-{html.escape(category, quote=True)}">
          <h2 id="category-{html.escape(category, quote=True)}">{html.escape(category.replace("-", " ").title())}</h2>
          {''.join(cards)}
        </section>"""
            )
        menu_html = "\n".join(sections)

    order_disabled = not accepts_orders or not menu.items
    disabled_attr = " disabled" if order_disabled else ""
    status_notice = (
        "Ordering is enabled for this node."
        if accepts_orders
        else f"This node is currently {html.escape(node.order_mode)}; menu viewing is available but ordering is disabled."
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>P4P Menu</title>
    <style>
      :root {{
        color-scheme: light;
      }}
      body {{
        margin: 0;
        background: #f5f7f6;
        color: #10201d;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      main {{
        max-width: 960px;
        margin: 0 auto;
        padding: 24px 14px 48px;
      }}
      header {{
        margin-bottom: 18px;
      }}
      h1, h2, h3, p {{
        margin: 0;
      }}
      h1 {{
        font-size: clamp(2rem, 5vw, 3.6rem);
        line-height: 1;
        max-width: 760px;
      }}
      .lede {{
        margin-top: 12px;
        max-width: 720px;
        color: #51615d;
      }}
      .layout {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
        gap: 18px;
        align-items: start;
      }}
      .category, .checkout {{
        background: #fff;
        border: 1px solid #cfd8d5;
        border-radius: 8px;
        padding: 16px;
      }}
      .category + .category {{
        margin-top: 14px;
      }}
      .category h2 {{
        font-size: 1rem;
        margin-bottom: 10px;
        text-transform: uppercase;
        letter-spacing: 0;
        color: #51615d;
      }}
      .item {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        align-items: center;
        padding: 12px 0;
        border-top: 1px solid #e4ebe8;
      }}
      .item.has-image {{
        grid-template-columns: 96px minmax(0, 1fr) auto;
      }}
      .item:first-of-type {{
        border-top: 0;
      }}
      .item-image {{
        width: 96px;
        aspect-ratio: 1;
        border-radius: 8px;
        object-fit: cover;
        background: #eef2f1;
      }}
      .item h3 {{
        font-size: 1rem;
      }}
      .item p {{
        margin-top: 4px;
        color: #51615d;
      }}
      .item span {{
        display: inline-block;
        margin-top: 6px;
        font-weight: 750;
      }}
      .stepper {{
        display: grid;
        grid-template-columns: 42px 42px 42px;
        align-items: center;
        min-width: 126px;
        height: 42px;
      }}
      .stepper button, button[type="submit"] {{
        border: 1px solid #00796b;
        background: #00796b;
        color: #fff;
        border-radius: 7px;
        min-height: 42px;
        font: inherit;
        font-weight: 750;
        cursor: pointer;
      }}
      .stepper button:first-child {{
        background: #fff;
        color: #00796b;
      }}
      .stepper output {{
        text-align: center;
        font-weight: 750;
      }}
      .checkout {{
        position: sticky;
        top: 12px;
      }}
      label {{
        display: block;
        margin-top: 12px;
        font-size: 0.9rem;
        font-weight: 650;
        color: #344541;
      }}
      input, textarea {{
        box-sizing: border-box;
        width: 100%;
        margin-top: 5px;
        border: 1px solid #cfd8d5;
        border-radius: 7px;
        min-height: 42px;
        padding: 9px 10px;
        font: inherit;
      }}
      textarea {{
        min-height: 76px;
        resize: vertical;
      }}
      .summary {{
        margin-top: 12px;
        padding: 12px;
        background: #f5f7f6;
        border: 1px solid #e1e8e5;
        border-radius: 8px;
      }}
      .total {{
        font-size: 1.5rem;
        font-weight: 800;
      }}
      .notice, .result {{
        margin-top: 10px;
        color: #51615d;
        font-size: 0.93rem;
      }}
      .result a {{
        color: #00594f;
        font-weight: 750;
      }}
      button[type="submit"] {{
        width: 100%;
        margin-top: 14px;
      }}
      button:disabled {{
        opacity: 0.45;
        cursor: not-allowed;
      }}
      .empty {{
        background: #fff;
        border: 1px solid #cfd8d5;
        border-radius: 8px;
        padding: 16px;
      }}
      @media (max-width: 760px) {{
        .layout {{
          grid-template-columns: 1fr;
        }}
        .checkout {{
          position: static;
        }}
      }}
      @media (max-width: 560px) {{
        .item.has-image {{
          grid-template-columns: 72px minmax(0, 1fr);
        }}
        .item-image {{
          width: 72px;
        }}
        .item .stepper {{
          grid-column: 1 / -1;
          justify-self: end;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <h1>Menu</h1>
        <p class="lede">Classic list view from the restaurant-owned catalog. Prices and item ids come from the node; this surface only builds an order request.</p>
      </header>
      <div class="layout">
        <div>{menu_html}</div>
        <form class="checkout" id="order-form">
          <h2>Order</h2>
          <p class="notice">{status_notice}</p>
          <label>
            Name
            <input name="customer_name" autocomplete="name" required{disabled_attr}>
          </label>
          <label>
            Phone or contact
            <input name="customer_contact" autocomplete="tel" required{disabled_attr}>
          </label>
          <label>
            Note
            <textarea name="note"{disabled_attr}></textarea>
          </label>
          <div class="summary" aria-live="polite">
            <p>Total</p>
            <p class="total" id="total">{html.escape(format_money_minor(0, menu.currency))}</p>
            <p id="selected-count">No items selected</p>
          </div>
          <button id="submit-order" type="submit"{disabled_attr}>Send order</button>
          <p class="result" id="result" role="status"></p>
        </form>
      </div>
    </main>
    <script>
      const canOrder = {str(accepts_orders and bool(menu.items)).lower()};
      const statusLinksEnabled = {str(status_links_enabled).lower()};
      const currency = "{html.escape(menu.currency, quote=True)}";
      const zeroDecimalCurrencies = new Set(["BIF","CLP","DJF","GNF","ISK","JPY","KMF","KRW","PYG","RWF","UGX","VND","VUV","XAF","XOF","XPF"]);
      const threeDecimalCurrencies = new Set(["BHD","IQD","JOD","KWD","LYD","OMR","TND"]);
      const cards = Array.from(document.querySelectorAll("[data-item-id]"));
      const form = document.getElementById("order-form");
      const submit = document.getElementById("submit-order");
      const total = document.getElementById("total");
      const selectedCount = document.getElementById("selected-count");
      const result = document.getElementById("result");

      function quantity(card) {{
        return Number(card.querySelector("output").textContent || "0");
      }}

      function setQuantity(card, value) {{
        card.querySelector("output").textContent = String(Math.max(0, value));
      }}

      function selectedItems() {{
        return cards
          .map((card) => ({{ id: card.dataset.itemId, quantity: quantity(card), price: Number(card.dataset.price) }}))
          .filter((item) => item.quantity > 0);
      }}

      function formatMoneyMinor(amount, code) {{
        const digits = zeroDecimalCurrencies.has(code) ? 0 : threeDecimalCurrencies.has(code) ? 3 : 2;
        const factor = 10 ** digits;
        return `${{(amount / factor).toFixed(digits)}} ${{code}}`;
      }}

      function updateSummary() {{
        const items = selectedItems();
        const amount = items.reduce((sum, item) => sum + item.quantity * item.price, 0);
        const count = items.reduce((sum, item) => sum + item.quantity, 0);
        total.textContent = formatMoneyMinor(amount, currency);
        selectedCount.textContent = count === 0 ? "No items selected" : `${{count}} item${{count === 1 ? "" : "s"}} selected`;
        submit.disabled = !canOrder || count === 0;
      }}

      cards.forEach((card) => {{
        card.addEventListener("click", (event) => {{
          const action = event.target instanceof HTMLElement ? event.target.dataset.action : "";
          if (!action) return;
          const next = quantity(card) + (action === "increase" ? 1 : -1);
          setQuantity(card, next);
          updateSummary();
        }});
      }});

      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const items = selectedItems().map((item) => ({{ id: item.id, quantity: item.quantity }}));
        if (!items.length) {{
          result.textContent = "Choose at least one item first.";
          return;
        }}
        submit.disabled = true;
        result.textContent = "Sending order.";
        const data = new FormData(form);
        const payload = {{
          customer_name: String(data.get("customer_name") || "").trim(),
          customer_contact: String(data.get("customer_contact") || "").trim(),
          fulfillment: "pickup",
          items,
          note: String(data.get("note") || "").trim(),
          client_version: "p4p-menu-list-0.1"
        }};
        try {{
          const response = await fetch("/p4p/order", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});
          const body = await response.json();
          if (!response.ok || body.accepted === false) {{
            throw new Error(body.message || body.detail || body.reason || "Order was rejected.");
          }}
          const statusLink = statusLinksEnabled ? ` <a href="/p4p/orders/${{encodeURIComponent(body.order_id)}}">Check status</a>` : "";
          result.innerHTML = `Order accepted: <strong>${{body.order_id}}</strong>.${{statusLink}}`;
        }} catch (error) {{
          result.textContent = error instanceof Error ? error.message : "Order failed.";
        }} finally {{
          updateSummary();
        }}
      }});

      updateSummary();
    </script>
  </body>
</html>"""


def public_menu_photo_map_page(runtime: PilotRuntime) -> str:
    if not menu_photo_map_module_enabled(runtime):
        raise HTTPException(status_code=404, detail="Photo map menu module is not enabled")

    menu = public_menu(runtime)
    node = node_state(runtime)
    accepts_orders = node_accepts_orders(runtime, node)
    status_links_enabled = customer_status_module_enabled(runtime)
    checked_at = utc_now()
    action_id = f"menu-photo-map:{checked_at.isoformat()}:view"
    runtime.store.record_order_event(
        ModuleResultEvent(
            event="CUSTOMER_MENU_VIEWED",
            source_module=MENU_PHOTO_MAP_MODULE_ID,
            order_id=None,
            action_id=action_id,
            idempotency_key=action_id,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="none",
            timestamp=checked_at,
            metadata={
                "active_item_count": len(menu.items),
                "category_count": len({item.category for item in menu.items}),
                "region_count": len(menu.items),
                "accepts_orders": accepts_orders,
                "public_surface": MENU_PHOTO_MAP_MODULE_ID,
                "map_mode": "catalog-derived-regions",
                "reads_catalog_truth": True,
                "exposes_inactive_items": False,
                "owns_catalog_truth": False,
                "owns_photo_source": False,
            },
        )
    )

    if not menu.items:
        map_html = '<p class="empty">No active menu items right now.</p>'
    else:
        regions: list[str] = []
        for index, item in enumerate(menu.items, start=1):
            price_label = html.escape(format_money_minor(item.price, menu.currency))
            item_name = html.escape(item.name, quote=True)
            image_html = (
                f"""
                <img class="region-photo" src="{html.escape(item.image_url, quote=True)}" alt="{item_name}" loading="lazy">"""
                if item.image_url
                else ""
            )
            hotspot_class = "hotspot has-image" if item.image_url else "hotspot"
            regions.append(
                f"""
              <button
                type="button"
                class="{hotspot_class}"
                data-photo-map-item-id="{html.escape(item.id, quote=True)}"
                data-price="{item.price}"
                data-region-index="{index}"
                aria-pressed="false"
              >
                <span class="region-number">{index}</span>
                {image_html}
                <span class="region-copy">
                  <strong>{html.escape(item.name)}</strong>
                  <small>{html.escape(item.description)}</small>
                  <em>{price_label}</em>
                </span>
                <span class="region-qty" aria-label="Selected quantity">0</span>
              </button>"""
            )
        map_html = f"""
          <section class="photo-map" aria-label="Clickable paper menu map" data-photo-map-mode="catalog-derived-regions">
            <div class="paper">
              <div class="paper-head">
                <p>Paper menu map</p>
                <span>{len(menu.items)} active regions</span>
              </div>
              <div class="regions">
                {''.join(regions)}
              </div>
            </div>
          </section>"""

    order_disabled = not accepts_orders or not menu.items
    disabled_attr = " disabled" if order_disabled else ""
    status_notice = (
        "Tap a menu area to add it to the order."
        if accepts_orders
        else f"This node is currently {html.escape(node.order_mode)}; menu viewing is available but ordering is disabled."
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>P4P Photo Map Menu</title>
    <style>
      :root {{
        color-scheme: light;
      }}
      body {{
        margin: 0;
        background: #eef2f1;
        color: #10201d;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      main {{
        max-width: 1080px;
        margin: 0 auto;
        padding: 24px 14px 48px;
      }}
      header {{
        margin-bottom: 18px;
      }}
      h1, h2, p {{
        margin: 0;
      }}
      h1 {{
        font-size: clamp(2rem, 5vw, 3.5rem);
        line-height: 1;
        max-width: 760px;
      }}
      .lede {{
        margin-top: 12px;
        max-width: 760px;
        color: #51615d;
      }}
      .layout {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
        gap: 18px;
        align-items: start;
      }}
      .photo-map, .checkout {{
        background: #fff;
        border: 1px solid #cfd8d5;
        border-radius: 8px;
        padding: 16px;
      }}
      .paper {{
        min-height: 560px;
        background: #fffdf6;
        border: 1px solid #d8d0bf;
        box-shadow: 0 10px 28px rgba(16, 32, 29, 0.08);
        padding: 18px;
      }}
      .paper-head {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        border-bottom: 2px solid #10201d;
        padding-bottom: 10px;
        margin-bottom: 14px;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0;
      }}
      .paper-head span {{
        color: #51615d;
        font-weight: 650;
        text-transform: none;
      }}
      .regions {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
        gap: 10px;
      }}
      .hotspot {{
        display: grid;
        grid-template-columns: 34px minmax(0, 1fr) 34px;
        gap: 10px;
        align-items: center;
        min-height: 92px;
        width: 100%;
        border: 1px solid #d8d0bf;
        border-radius: 7px;
        background: rgba(255, 255, 255, 0.72);
        color: inherit;
        padding: 10px;
        font: inherit;
        text-align: left;
        cursor: pointer;
      }}
      .hotspot.has-image {{
        grid-template-columns: 34px 76px minmax(0, 1fr) 34px;
      }}
      .hotspot[aria-pressed="true"] {{
        border-color: #00796b;
        background: #ecf8f5;
      }}
      .region-photo {{
        width: 76px;
        aspect-ratio: 1;
        border-radius: 7px;
        object-fit: cover;
        background: #eef2f1;
      }}
      .region-number, .region-qty {{
        display: grid;
        place-items: center;
        min-width: 34px;
        height: 34px;
        border-radius: 50%;
        font-weight: 800;
      }}
      .region-number {{
        background: #10201d;
        color: #fff;
      }}
      .region-qty {{
        background: #00796b;
        color: #fff;
      }}
      .region-copy {{
        display: grid;
        gap: 4px;
        min-width: 0;
      }}
      .region-copy strong, .region-copy small {{
        overflow-wrap: anywhere;
      }}
      .region-copy small {{
        color: #51615d;
      }}
      .region-copy em {{
        font-style: normal;
        font-weight: 800;
      }}
      .checkout {{
        position: sticky;
        top: 12px;
      }}
      label {{
        display: block;
        margin-top: 12px;
        font-size: 0.9rem;
        font-weight: 650;
        color: #344541;
      }}
      input, textarea {{
        box-sizing: border-box;
        width: 100%;
        margin-top: 5px;
        border: 1px solid #cfd8d5;
        border-radius: 7px;
        min-height: 42px;
        padding: 9px 10px;
        font: inherit;
      }}
      textarea {{
        min-height: 76px;
        resize: vertical;
      }}
      .summary {{
        margin-top: 12px;
        padding: 12px;
        background: #f5f7f6;
        border: 1px solid #e1e8e5;
        border-radius: 8px;
      }}
      .total {{
        font-size: 1.5rem;
        font-weight: 800;
      }}
      .selected-list {{
        display: grid;
        gap: 8px;
        margin-top: 10px;
      }}
      .selected-row {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 8px;
        align-items: center;
      }}
      .selected-row button, button[type="submit"] {{
        border: 1px solid #00796b;
        background: #00796b;
        color: #fff;
        border-radius: 7px;
        min-height: 38px;
        font: inherit;
        font-weight: 750;
        cursor: pointer;
      }}
      .selected-row button {{
        background: #fff;
        color: #00796b;
        padding: 0 10px;
      }}
      .notice, .result {{
        margin-top: 10px;
        color: #51615d;
        font-size: 0.93rem;
      }}
      .result a {{
        color: #00594f;
        font-weight: 750;
      }}
      button[type="submit"] {{
        width: 100%;
        min-height: 42px;
        margin-top: 14px;
      }}
      button:disabled {{
        opacity: 0.45;
        cursor: not-allowed;
      }}
      .empty {{
        background: #fff;
        border: 1px solid #cfd8d5;
        border-radius: 8px;
        padding: 16px;
      }}
      @media (max-width: 780px) {{
        .layout {{
          grid-template-columns: 1fr;
        }}
        .checkout {{
          position: static;
        }}
      }}
      @media (max-width: 560px) {{
        .hotspot.has-image {{
          grid-template-columns: 32px 62px minmax(0, 1fr);
        }}
        .region-photo {{
          width: 62px;
        }}
        .hotspot.has-image .region-qty {{
          grid-column: 1 / -1;
          justify-self: end;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <h1>Photo Map Menu</h1>
        <p class="lede">Clickable paper-menu style view from the restaurant-owned catalog. This reference module maps active catalog items to visual regions; it does not own the catalog, prices, inventory, or payment.</p>
      </header>
      <div class="layout">
        <div>{map_html}</div>
        <form class="checkout" id="order-form">
          <h2>Order</h2>
          <p class="notice">{status_notice}</p>
          <label>
            Name
            <input name="customer_name" autocomplete="name" required{disabled_attr}>
          </label>
          <label>
            Phone or contact
            <input name="customer_contact" autocomplete="tel" required{disabled_attr}>
          </label>
          <label>
            Note
            <textarea name="note"{disabled_attr}></textarea>
          </label>
          <div class="summary" aria-live="polite">
            <p>Total</p>
            <p class="total" id="total">{html.escape(format_money_minor(0, menu.currency))}</p>
            <p id="selected-count">No areas selected</p>
            <div class="selected-list" id="selected-list"></div>
          </div>
          <button id="submit-order" type="submit"{disabled_attr}>Send order</button>
          <p class="result" id="result" role="status"></p>
        </form>
      </div>
    </main>
    <script>
      const canOrder = {str(accepts_orders and bool(menu.items)).lower()};
      const statusLinksEnabled = {str(status_links_enabled).lower()};
      const currency = "{html.escape(menu.currency, quote=True)}";
      const zeroDecimalCurrencies = new Set(["BIF","CLP","DJF","GNF","ISK","JPY","KMF","KRW","PYG","RWF","UGX","VND","VUV","XAF","XOF","XPF"]);
      const threeDecimalCurrencies = new Set(["BHD","IQD","JOD","KWD","LYD","OMR","TND"]);
      const hotspots = Array.from(document.querySelectorAll("[data-photo-map-item-id]"));
      const form = document.getElementById("order-form");
      const submit = document.getElementById("submit-order");
      const total = document.getElementById("total");
      const selectedCount = document.getElementById("selected-count");
      const selectedList = document.getElementById("selected-list");
      const result = document.getElementById("result");

      function quantity(button) {{
        return Number(button.querySelector(".region-qty").textContent || "0");
      }}

      function setQuantity(button, value) {{
        const next = Math.max(0, value);
        button.querySelector(".region-qty").textContent = String(next);
        button.setAttribute("aria-pressed", next > 0 ? "true" : "false");
      }}

      function selectedItems() {{
        return hotspots
          .map((button) => ({{
            id: button.dataset.photoMapItemId,
            quantity: quantity(button),
            price: Number(button.dataset.price),
            name: button.querySelector("strong").textContent || button.dataset.photoMapItemId
          }}))
          .filter((item) => item.quantity > 0);
      }}

      function formatMoneyMinor(amount, code) {{
        const digits = zeroDecimalCurrencies.has(code) ? 0 : threeDecimalCurrencies.has(code) ? 3 : 2;
        const factor = 10 ** digits;
        return `${{(amount / factor).toFixed(digits)}} ${{code}}`;
      }}

      function updateSummary() {{
        const items = selectedItems();
        const amount = items.reduce((sum, item) => sum + item.quantity * item.price, 0);
        const count = items.reduce((sum, item) => sum + item.quantity, 0);
        total.textContent = formatMoneyMinor(amount, currency);
        selectedCount.textContent = count === 0 ? "No areas selected" : `${{count}} item${{count === 1 ? "" : "s"}} selected`;
        selectedList.innerHTML = items.map((item) => `
          <div class="selected-row">
            <span>${{item.quantity}} x ${{item.name}}</span>
            <button type="button" data-remove-item="${{item.id}}">Remove</button>
          </div>
        `).join("");
        submit.disabled = !canOrder || count === 0;
      }}

      hotspots.forEach((button) => {{
        button.addEventListener("click", () => {{
          setQuantity(button, quantity(button) + 1);
          updateSummary();
        }});
      }});

      selectedList.addEventListener("click", (event) => {{
        const target = event.target instanceof HTMLElement ? event.target : null;
        const itemId = target ? target.dataset.removeItem : "";
        if (!itemId) return;
        const button = hotspots.find((candidate) => candidate.dataset.photoMapItemId === itemId);
        if (!button) return;
        setQuantity(button, quantity(button) - 1);
        updateSummary();
      }});

      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const items = selectedItems().map((item) => ({{ id: item.id, quantity: item.quantity }}));
        if (!items.length) {{
          result.textContent = "Choose at least one menu area first.";
          return;
        }}
        submit.disabled = true;
        result.textContent = "Sending order.";
        const data = new FormData(form);
        const payload = {{
          customer_name: String(data.get("customer_name") || "").trim(),
          customer_contact: String(data.get("customer_contact") || "").trim(),
          fulfillment: "pickup",
          items,
          note: String(data.get("note") || "").trim(),
          client_version: "p4p-menu-photo-map-0.1"
        }};
        try {{
          const response = await fetch("/p4p/order", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});
          const body = await response.json();
          if (!response.ok || body.accepted === false) {{
            throw new Error(body.message || body.detail || body.reason || "Order was rejected.");
          }}
          const statusLink = statusLinksEnabled ? ` <a href="/p4p/orders/${{encodeURIComponent(body.order_id)}}">Check status</a>` : "";
          result.innerHTML = `Order accepted: <strong>${{body.order_id}}</strong>.${{statusLink}}`;
        }} catch (error) {{
          result.textContent = error instanceof Error ? error.message : "Order failed.";
        }} finally {{
          updateSummary();
        }}
      }});

      updateSummary();
    </script>
  </body>
</html>"""


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
    active_payment_module_id = effective_payment_module_id(runtime)
    return {
        "locale": operator_locale_payload(operator_locale(runtime)),
        "node": node.model_dump(mode="json", exclude_none=True),
        "accepts_orders": node_accepts_orders(runtime, node),
        "hardware": {
            "profile": runtime.config.hardware_profile,
            "customized": runtime.config.hardware_profile_customized,
            "print": {
                "target": runtime.config.print_module_target,
                "driver": runtime.config.print_module_driver,
                "sensor_source": runtime.config.print_sensor_source,
            },
            "backup_print": {
                "target": runtime.config.backup_print_target,
                "driver": runtime.config.backup_print_driver,
            },
            "alert": {
                "target": runtime.config.alert_target,
                "mode": runtime.config.alert_mode,
            },
            "pickup_board": {
                "target": runtime.config.pickup_board_target,
            },
        },
        "enabled_modules": runtime.config.node_modules,
        "public_modules": runtime.config.public_node_modules,
        "module_declarations": enabled_module_declarations(runtime),
        "public_module_declarations": public_module_declarations(runtime),
        "undeclared_modules": runtime.config.undeclared_node_modules,
        "active_by_lane": {
            "payment": active_payment_module_id or None,
        },
        "registry": registration_payload(runtime),
    }


def operator_gui(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_OPERATIONS_HTML_PATH,
        runtime,
        page_title_key="page.operations.title",
    )


def operator_welcome_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_WELCOME_HTML_PATH,
        runtime,
        page_title_key="page.welcome.title",
    )


def operator_setup_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_SETUP_HTML_PATH,
        runtime,
        page_title_key="page.setup.title",
    )


SETUP_HARDWARE_STEP_ID = "hardware_profile_confirmed"
SETUP_CATALOG_STEP_ID = "catalog_reviewed"
SETUP_LOCAL_TESTS_STEP_ID = "local_tests_run"
SETUP_BASELINE_MODULE_IDS = (
    CATALOG_EDITOR_MODULE_ID,
    MENU_LIST_MODULE_ID,
    CUSTOMER_STATUS_MODULE_ID,
    PAYMENT_CASH_MODULE_ID,
)
SETUP_RECOMMENDED_MODULE_IDS = (KITCHEN_SCREEN_MODULE_ID,)


def operator_setup(runtime: PilotRuntime) -> dict[str, Any]:
    modules = operator_modules(runtime)
    node = operator_state(runtime)
    menu = operator_menu(runtime)
    persisted = setup_state(runtime)
    locale = operator_locale(runtime)

    current = set(modules.get("current_module_ids") or [])
    desired = set(modules.get("desired_module_ids") or [])
    menu_count = len(menu.items)
    payment_module_id = str(modules.get("active_by_lane", {}).get("payment") or "").strip()
    completed_steps = set(str(step).strip() for step in persisted.get("completed_steps") or [])
    hardware_profile_confirmed = bool(
        persisted.get("hardware_base_profile") or persisted.get("hardware_profile")
    )
    catalog_reviewed = bool(persisted.get("catalog_ready")) and menu_count > 0
    local_tests_done = SETUP_LOCAL_TESTS_STEP_ID in completed_steps
    baseline_desired = all(module_id in desired for module_id in SETUP_BASELINE_MODULE_IDS)
    baseline_current = all(module_id in current for module_id in SETUP_BASELINE_MODULE_IDS)
    kitchen_current = all(module_id in current for module_id in SETUP_RECOMMENDED_MODULE_IDS)
    restart_required = bool(modules.get("restart_required"))
    order_mode = str(node.get("node", {}).get("order_mode") or "").strip()
    accepts_orders = bool(node.get("accepts_orders"))

    checklist = [
        {
            "id": "baseline_modules",
            "title": localized_text(
                {
                    "da": "Vælg grundmoduler",
                    "sv": "Välj grundmoduler",
                    "tr": "Temel modülleri seç",
                    "ar": "اختر الوحدات الأساسية",
                    "ku": "Modulên bingehîn hilbijêre",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": "Noden bør mindst have katalog, menuliste, kundestatus og én betalingsbane.",
                    "sv": "Noden bör minst ha katalog, menylista, kundstatus och en betalningsbana.",
                    "tr": "Düğüm en az katalog, menü listesi, müşteri durumu ve bir ödeme hattına sahip olmalıdır.",
                    "ar": "يجب أن تحتوي العقدة على الأقل على الكتالوج وقائمة الطعام وحالة الزبون ومسار دفع واحد.",
                    "ku": "Divê node herî kêm katalog, lîsteya menu, statûya xerîdar û yek rêya dravdanê hebe.",
                },
                locale,
            ),
            "done": baseline_desired,
            "href": "/operator/modules",
            "source": "runtime",
        },
        {
            "id": SETUP_HARDWARE_STEP_ID,
            "title": localized_text(
                {
                    "da": "Bekræft hardwareform",
                    "sv": "Bekräfta hårdvaruform",
                    "tr": "Donanım şeklini doğrula",
                    "ar": "أكّد شكل العتاد",
                    "ku": "Forma hardwareê piştrast bike",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": f"Nuværende runtime-hardwareprofil: {runtime.config.hardware_profile}. Bekræft hvilken hardwareform denne node skal køre i.",
                    "sv": f"Nuvarande runtime-hårdvaruprofil: {runtime.config.hardware_profile}. Bekräfta vilken hårdvaruform denna nod ska köra i.",
                    "tr": f"Geçerli çalışma zamanı donanım profili: {runtime.config.hardware_profile}. Bu düğümün hangi donanım şeklinde çalışacağını doğrulayın.",
                    "ar": f"ملف عتاد وقت التشغيل الحالي: {runtime.config.hardware_profile}. أكّد شكل العتاد الذي يفترض أن تعمل عليه هذه العقدة.",
                    "ku": f"Profîla hardware ya heyî ya runtime: {runtime.config.hardware_profile}. Forma hardware ya ku ev node dê lê bixebite piştrast bike.",
                },
                locale,
            ),
            "done": hardware_profile_confirmed,
            "href": "/operator/setup",
            "source": "manual",
        },
        {
            "id": "payment_lane",
            "title": localized_text(
                {
                    "da": "Vælg betalingsbane",
                    "sv": "Välj betalningsbana",
                    "tr": "Ödeme hattı seç",
                    "ar": "اختر مسار الدفع",
                    "ku": "Rêya dravdanê hilbijêre",
                },
                locale,
            ),
            "detail": payment_module_id
            and localized_text(
                {
                    "da": f"Nuværende aktive betalingsbane: {payment_module_id}.",
                    "sv": f"Nuvarande aktiva betalningsbana: {payment_module_id}.",
                    "tr": f"Geçerli etkin ödeme hattı: {payment_module_id}.",
                    "ar": f"مسار الدفع النشط الحالي: {payment_module_id}.",
                    "ku": f"Rêya dravdanê ya heyî ya çalak: {payment_module_id}.",
                },
                locale,
            )
            or localized_text(
                {
                    "da": "Vælg den betalingsbane, der skal være aktiv på denne node.",
                    "sv": "Välj den betalningsbana som ska vara aktiv på denna nod.",
                    "tr": "Bu düğümde etkin olması gereken ödeme hattını seçin.",
                    "ar": "اختر مسار الدفع الذي يجب أن يكون نشطاً على هذه العقدة.",
                    "ku": "Rêya dravdanê ya ku divê li ser vê nodeyê çalak be hilbijêre.",
                },
                locale,
            ),
            "done": bool(payment_module_id),
            "href": "/operator/modules",
            "source": "runtime",
        },
        {
            "id": "first_menu_added",
            "title": localized_text(
                {
                    "da": "Læg første menu ind",
                    "sv": "Lägg in första menyn",
                    "tr": "İlk menüyü ekle",
                    "ar": "أضف أول قائمة",
                    "ku": "Menuya yekem têxe",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": f"{menu_count} katalogvare(r) gemt lige nu.",
                    "sv": f"{menu_count} katalogobjekt lagrat just nu.",
                    "tr": f"Şu anda {menu_count} katalog öğesi kayıtlı.",
                    "ar": f"هناك {menu_count} عنصر/عناصر كتالوج محفوظة الآن.",
                    "ku": f"Niha {menu_count} tişt/tîştên katalogê hatiye tomar kirin.",
                },
                locale,
            ),
            "done": menu_count > 0,
            "href": "/operator/catalog",
            "source": "runtime",
        },
        {
            "id": SETUP_CATALOG_STEP_ID,
            "title": localized_text(
                {
                    "da": "Gennemgå menuen på noden",
                    "sv": "Granska menyn på noden",
                    "tr": "Düğümdaki menüyü gözden geçir",
                    "ar": "راجع القائمة على العقدة",
                    "ku": "Menuya li ser nodeyê binirxîne",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": "Brug dette, når den første rigtige menu er gennemgået og klar til at blive vist i butikken.",
                    "sv": "Använd detta när den första riktiga menyn har granskats och är redo att visas i butiken.",
                    "tr": "İlk gerçek menü gözden geçirilip dükkânda gösterilmeye hazır olduğunda bunu kullanın.",
                    "ar": "استخدم هذا عندما تتم مراجعة أول قائمة حقيقية وتصبح جاهزة للعرض في المتجر.",
                    "ku": "Dema ku menuya rastîn a yekem hate binirxandin û amade ye ku li dikanê were nîşandan, vê bikar bîne.",
                },
                locale,
            ),
            "done": catalog_reviewed,
            "href": "/operator/catalog",
            "source": "manual",
        },
        {
            "id": SETUP_LOCAL_TESTS_STEP_ID,
            "title": localized_text(
                {
                    "da": "Kør lokale tests",
                    "sv": "Kör lokala tester",
                    "tr": "Yerel testleri çalıştır",
                    "ar": "شغّل الاختبارات المحلية",
                    "ku": "Testên herêmî bixebitîne",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": "Bekræft operatorflader og lokale hardwarehjælpere før pilotbrug.",
                    "sv": "Bekräfta operatörsytor och lokala hårdvaruhjälpare före pilotbruk.",
                    "tr": "Pilot kullanımından önce operatör yüzlerini ve yerel donanım yardımcılarını doğrulayın.",
                    "ar": "أكّد واجهات المشغّل ومساعدات العتاد المحلية قبل الاستخدام التجريبي.",
                    "ku": "Berî bikaranîna pilot, rûyên operatorê û alîkarên herêmî yên hardwareê piştrast bike.",
                },
                locale,
            ),
            "done": local_tests_done,
            "href": "/operator/setup",
            "source": "manual",
        },
        {
            "id": "restart_completed",
            "title": localized_text(
                {
                    "da": "Genstart hvis moduler er ændret",
                    "sv": "Starta om om moduler ändrades",
                    "tr": "Modüller değiştiyse yeniden başlat",
                    "ar": "أعد التشغيل إذا تغيّرت الوحدات",
                    "ku": "Heke modul guhertin, ji nû ve dest pê bike",
                },
                locale,
            ),
            "detail": restart_required
            and localized_text(
                {
                    "da": "Det ønskede modulset er gemt, men den kørende runtime mangler stadig en genstart.",
                    "sv": "Det önskade modulsetet är sparat, men den körande runtimen behöver fortfarande en omstart.",
                    "tr": "İstenen modül seti kaydedildi, ancak çalışan çalışma zamanı hâlâ yeniden başlatılmalı.",
                    "ar": "تم حفظ مجموعة الوحدات المطلوبة، لكن وقت التشغيل الحالي ما زال يحتاج إلى إعادة تشغيل.",
                    "ku": "Koma modulên daxwazkirî hat tomar kirin, lê runtimeya ku dimeşe hîn jî pêdivî bi destpêkkirina nû heye.",
                },
                locale,
            )
            or localized_text(
                {
                    "da": "Den kørende runtime matcher allerede det ønskede modulset.",
                    "sv": "Den körande runtimen matchar redan det önskade modulsetet.",
                    "tr": "Çalışan çalışma zamanı zaten istenen modül setiyle eşleşiyor.",
                    "ar": "وقت التشغيل الحالي يطابق بالفعل مجموعة الوحدات المطلوبة.",
                    "ku": "Runtimeya ku dimeşe jixwe bi koma modulên daxwazkirî re li hev dike.",
                },
                locale,
            ),
            "done": not restart_required,
            "href": "/operator/modules",
            "source": "runtime",
        },
        {
            "id": "operations_room_present",
            "title": localized_text(
                {
                    "da": "Tjek driftsrummet",
                    "sv": "Kontrollera driftrummet",
                    "tr": "Operasyon odasını kontrol et",
                    "ar": "افحص غرفة التشغيل",
                    "ku": "Jora çalakiyê kontrol bike",
                },
                locale,
            ),
            "detail": kitchen_current
            and localized_text(
                {
                    "da": "Køkken- og ordrehåndtering er allerede med i det kørende sæt.",
                    "sv": "Kök- och orderhantering finns redan i den körande uppsättningen.",
                    "tr": "Mutfak ve sipariş yönetimi zaten çalışan sette mevcut.",
                    "ar": "المطبخ ومعالجة الطلبات موجودان بالفعل في المجموعة العاملة.",
                    "ku": "Birêvebirina metbex û ferman jixwe di koma dimeşe de heye.",
                },
                locale,
            )
            or localized_text(
                {
                    "da": "Køkkenhåndtering er ikke i det kørende sæt endnu.",
                    "sv": "Kökshantering finns inte i den körande uppsättningen ännu.",
                    "tr": "Mutfak yönetimi henüz çalışan sette değil.",
                    "ar": "معالجة المطبخ ليست ضمن المجموعة العاملة بعد.",
                    "ku": "Birêvebirina metbex hîn di koma dimeşe de tune.",
                },
                locale,
            ),
            "done": kitchen_current,
            "href": "/operator",
            "source": "runtime",
        },
        {
            "id": "ready_for_menu_only",
            "title": localized_text(
                {
                    "da": "Klar til menu_only-pilot",
                    "sv": "Redo för menu_only-pilot",
                    "tr": "menu_only pilotuna hazır",
                    "ar": "جاهز لمرحلة menu_only",
                    "ku": "Ji bo pilotê menu_only amade ye",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": "Brug menu_only først mens du tester menu, flader og lokal hardware.",
                    "sv": "Använd menu_only först medan du testar meny, ytor och lokal hårdvara.",
                    "tr": "Menü, yüzler ve yerel donanımı test ederken önce menu_only kullanın.",
                    "ar": "استخدم menu_only أولاً أثناء اختبار القائمة والواجهات والعتاد المحلي.",
                    "ku": "Dema tu menu, rûy û hardwareya herêmî test dikî, pêşî menu_only bi kar bîne.",
                },
                locale,
            ),
            "done": baseline_current
            and hardware_profile_confirmed
            and bool(payment_module_id)
            and menu_count > 0
            and catalog_reviewed
            and local_tests_done
            and not restart_required
            and order_mode == "menu_only",
            "href": "/operator",
            "source": "computed",
        },
        {
            "id": "ready_for_live",
            "title": localized_text(
                {
                    "da": "Klar til live senere",
                    "sv": "Redo för live senare",
                    "tr": "Daha sonra live için hazır",
                    "ar": "جاهز للانتقال إلى live لاحقاً",
                    "ku": "Ji bo live paşê amade ye",
                },
                locale,
            ),
            "detail": localized_text(
                {
                    "da": "Gå kun til live når butikken udtrykkeligt vil acceptere rigtige ordrer.",
                    "sv": "Gå bara till live när butiken uttryckligen vill ta emot riktiga order.",
                    "tr": "Yalnızca dükkân açıkça gerçek siparişleri kabul etmek istediğinde live moduna geçin.",
                    "ar": "انتقل إلى live فقط عندما يريد المتجر صراحةً قبول طلبات حقيقية.",
                    "ku": "Tenê dema ku dikan bi eşkere bixwaze fermana rast qebûl bike, derbasî live bibe.",
                },
                locale,
            ),
            "done": baseline_current
            and hardware_profile_confirmed
            and bool(payment_module_id)
            and menu_count > 0
            and catalog_reviewed
            and local_tests_done
            and not restart_required
            and accepts_orders
            and order_mode == "live",
            "href": "/operator",
            "source": "computed",
        },
    ]
    done_count = sum(1 for item in checklist if item["done"])
    ready_for_menu_only = next(item["done"] for item in checklist if item["id"] == "ready_for_menu_only")
    ready_for_live = next(item["done"] for item in checklist if item["id"] == "ready_for_live")

    return {
        "node_id": modules.get("node_id") or node.get("node", {}).get("node_id"),
        "locale": operator_locale_payload(locale),
        "setup": persisted,
        "hardware_profiles": persisted.get("available_hardware_profiles") or [runtime.config.hardware_profile],
        "hardware_base_profiles": persisted.get("hardware_base_profiles") or [],
        "hardware_addons": persisted.get("hardware_addons") or [],
        "modules": modules,
        "state": node,
        "menu": menu.model_dump(mode="json"),
        "checklist": checklist,
        "summary": {
            "done_count": done_count,
            "total_steps": len(checklist),
            "ready_for_menu_only": ready_for_menu_only,
            "ready_for_live": ready_for_live,
            "status": "live-ready" if ready_for_live else "menu_only-ready" if ready_for_menu_only else "incomplete",
        },
    }


def operator_update_setup(runtime: PilotRuntime, payload: OperatorSetupUpdate) -> dict[str, Any]:
    set_setup_state(
        runtime,
        operator_locale=payload.operator_locale,
        hardware_profile=payload.hardware_profile,
        hardware_base_profile=payload.hardware_base_profile,
        hardware_enabled_addons=payload.hardware_enabled_addons,
        catalog_ready=payload.catalog_ready,
        local_tests_run=payload.local_tests_run,
    )
    summary = operator_setup(runtime)
    setup_complete = bool(summary["summary"]["ready_for_menu_only"])
    set_setup_state(runtime, completed=setup_complete)
    return operator_setup(runtime)


def operator_catalog_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_CATALOG_HTML_PATH,
        runtime,
        page_title_key="page.catalog.title",
    )


def operator_modules_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_MODULES_HTML_PATH,
        runtime,
        page_title_key="page.modules.title",
    )


def operator_discover_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_DISCOVER_HTML_PATH,
        runtime,
        page_title_key="page.discover.title",
    )


def operator_import_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_IMPORT_HTML_PATH,
        runtime,
        page_title_key="page.import.title",
    )


def operator_node_page(runtime: PilotRuntime) -> str:
    return render_operator_page(
        OPERATOR_NODE_HTML_PATH,
        runtime,
        page_title_key="page.node.title",
    )


def operator_module_view_page(runtime: PilotRuntime, module_id: str) -> str:
    normalized_module_id = module_id.strip()
    if not normalized_module_id:
        raise HTTPException(status_code=404, detail="Unknown module_id")
    if normalized_module_id not in current_module_ids(runtime) and known_module_manifest(runtime, normalized_module_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown module_id: {normalized_module_id}")
    return render_operator_page(
        MODULE_HTML_PATH,
        runtime,
        page_title_key="page.modules.title",
    )


def operator_pickup_board_page(runtime: PilotRuntime) -> str:
    if PICKUP_BOARD_BASIC_MODULE_ID not in effective_flow_module_ids(runtime):
        raise HTTPException(status_code=404, detail="Pickup board module is not enabled")
    return PICKUP_BOARD_HTML_PATH.read_text(encoding="utf-8")


def operator_pickup_board_data(runtime: PilotRuntime) -> dict[str, Any]:
    if PICKUP_BOARD_BASIC_MODULE_ID not in effective_flow_module_ids(runtime):
        raise HTTPException(status_code=404, detail="Pickup board module is not enabled")
    if not runtime.config.pickup_board_target:
        raise HTTPException(status_code=503, detail="Pickup board target is not configured")
    return {
        "node_id": runtime.config.node_id,
        "target": runtime.config.pickup_board_target,
        "checked_at": utc_now().isoformat(),
        "orders": pickup_board_entries(runtime.store.list_orders(limit=100)),
    }


def current_module_ids(runtime: PilotRuntime) -> list[str]:
    return list(runtime.config.node_modules)


def known_module_manifest(runtime: PilotRuntime, module_id: str):
    return runtime.config.available_resolved_modules.get(module_id.strip())


def module_requires(manifest) -> list[str]:
    raw_requires = manifest.raw.get("requires") or []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw_requires:
        module_id = str(value).strip()
        if not module_id or module_id in seen:
            continue
        normalized.append(module_id)
        seen.add(module_id)
    return normalized


def transitive_module_requires(runtime: PilotRuntime, module_id: str) -> list[str]:
    required: list[str] = []
    seen: set[str] = set()
    stack = [module_id]
    while stack:
        current_module_id = stack.pop()
        manifest = known_module_manifest(runtime, current_module_id)
        if manifest is None:
            continue
        for dependency_module_id in module_requires(manifest):
            if dependency_module_id in seen:
                continue
            seen.add(dependency_module_id)
            required.append(dependency_module_id)
            stack.append(dependency_module_id)
    return required


def module_dependents(runtime: PilotRuntime, module_id: str) -> list[str]:
    dependents: list[str] = []
    for manifest in runtime.config.available_resolved_modules.manifests:
        if manifest.module_id == module_id:
            continue
        if module_id in transitive_module_requires(runtime, manifest.module_id):
            dependents.append(manifest.module_id)
    return dependents


def desired_payment_module_id(runtime: PilotRuntime) -> str | None:
    raw_selected = runtime.store.get_state(ACTIVE_PAYMENT_MODULE_STATE_KEY, "").strip()
    desired_ids = desired_module_ids(runtime)
    if raw_selected and raw_selected in desired_ids:
        manifest = known_module_manifest(runtime, raw_selected)
        if manifest is not None and module_is_payment(manifest):
            return raw_selected
    for module_id in desired_ids:
        manifest = known_module_manifest(runtime, module_id)
        if manifest is not None and module_is_payment(manifest):
            return module_id
    return None


def module_doc_source_path(module_id: str) -> Path:
    return MODULE_DOCS_ROOT / f"{module_id}.md"


def provider_doc_source_path(provider_id: str | None) -> Path:
    if provider_id:
        specific = PROVIDER_DOCS_ROOT / f"{provider_id}.md"
        if specific.is_file():
            return specific
    return PROVIDER_DOCS_ROOT / "README.md"


def github_blob_url(path: Path) -> str:
    relative = path.relative_to(P4P_ROOT).as_posix()
    return f"{GITHUB_BLOB_BASE_URL}/{relative}"


def markdown_heading_sections(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current_heading: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_heading = line[3:].strip()
            sections[current_heading] = []
            continue
        if current_heading is not None:
            sections[current_heading].append(line)
    return {
        heading: "\n".join(lines).strip()
        for heading, lines in sections.items()
        if "\n".join(lines).strip()
    }


def module_doc_payload(module_id: str, provider_id: str | None) -> dict[str, Any]:
    module_doc_path = module_doc_source_path(module_id)
    provider_doc_path = provider_doc_source_path(provider_id)
    manifest_path = P4P_ROOT / "modules" / module_id / "module.json"
    provider_manifest_path = P4P_ROOT / "modules" / module_id / "provider.json"
    sections = markdown_heading_sections(module_doc_path)
    return {
        "sections": {
            "payment_boundary": sections.get("Payment Boundary", ""),
            "purpose": sections.get("Purpose", ""),
            "what_it_does": sections.get("What It Does", "") or sections.get("What It Would Do", ""),
            "what_it_does_not_own": sections.get("What It Does Not Own", ""),
            "current_readiness": sections.get("Current Readiness", ""),
            "local_test_path": sections.get("Local Test Path", ""),
        },
        "links": {
            "module_doc_url": github_blob_url(module_doc_path) if module_doc_path.is_file() else None,
            "module_manifest_url": github_blob_url(manifest_path) if manifest_path.is_file() else None,
            "provider_doc_url": github_blob_url(provider_doc_path) if provider_doc_path.is_file() else None,
            "provider_manifest_url": (
                github_blob_url(provider_manifest_path) if provider_manifest_path.is_file() else None
            ),
        },
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


def _hardware_driver_missing_configuration(driver_id: str, *, spool_dir: str, device_path: str) -> list[str]:
    normalized = driver_id.strip().lower()
    if normalized == "file_spool" and not spool_dir.strip():
        return ["backup_print_spool_dir"]
    if normalized in {"device_path", "escpos_raw"} and not device_path.strip():
        return ["backup_print_device_path"]
    return []


def module_configuration(runtime: PilotRuntime, manifest) -> tuple[bool, list[str]]:
    if manifest.module_id == ORDER_PRINT_BACKUP_MODULE_ID:
        missing: list[str] = []
        if not runtime.config.backup_print_target:
            missing.append("backup_print_target")
        missing.extend(
            _hardware_driver_missing_configuration(
                runtime.config.backup_print_driver,
                spool_dir=runtime.config.backup_print_spool_dir,
                device_path=runtime.config.backup_print_device_path,
            )
        )
        return not missing, missing
    if manifest.module_id == ORDER_ALERT_BASIC_MODULE_ID:
        missing = []
        if not runtime.config.alert_target:
            missing.append("alert_target")
        return not missing, missing
    if manifest.module_id == PICKUP_BOARD_BASIC_MODULE_ID:
        missing = []
        if not runtime.config.pickup_board_target:
            missing.append("pickup_board_target")
        return not missing, missing

    lane = module_execution_lane(manifest)
    if lane != "payment":
        return True, []
    if manifest.module_id in {PAYMENT_CASH_MODULE_ID, GODPAY_MOCK_MODULE_ID}:
        return True, []
    if manifest.module_id == CHAOSPAY_MOCK_MODULE_ID:
        return False, ["chaospay_scenario_executor"]

    missing: list[str] = []
    entrypoint = module_entrypoint(manifest)
    if manifest.module_id == effective_payment_module_id(runtime):
        if not runtime.config.payment_external_url:
            missing.append("payment_external_url")
        if not runtime.config.payment_external_customer_user_id:
            missing.append("payment_external_customer_user_id")
    elif not entrypoint:
        missing.append("entrypoint")

    return not missing, missing


def module_active(runtime: PilotRuntime, manifest) -> bool:
    if module_execution_lane(manifest) == "payment":
        return manifest.module_id == effective_payment_module_id(runtime)
    return manifest.module_id in effective_flow_module_ids(runtime)


def module_health(runtime: PilotRuntime, manifest, *, active: bool, configured: bool) -> dict[str, Any]:
    if manifest.module_id == PAYMENT_CASH_MODULE_ID:
        return {
            "health": "available",
            "health_reason": "builtin_reference_module",
            "health_url": None,
            "last_checked_at": None,
        }
    if manifest.module_id == GODPAY_MOCK_MODULE_ID:
        return {
            "health": "available",
            "health_reason": "internal_mock_available",
            "health_url": None,
            "last_checked_at": None,
        }
    if manifest.module_id == CHAOSPAY_MOCK_MODULE_ID:
        return {
            "health": "not_configured",
            "health_reason": "chaospay_scenario_executor_not_enabled",
            "health_url": None,
            "last_checked_at": None,
        }
    if manifest.module_id in {ORDER_PRINT_BACKUP_MODULE_ID, ORDER_ALERT_BASIC_MODULE_ID, PICKUP_BOARD_BASIC_MODULE_ID}:
        if not configured:
            return {
                "health": "not_configured",
                "health_reason": "required_configuration_missing",
                "health_url": None,
                "last_checked_at": None,
            }
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
        GODPAY_MOCK_MODULE_ID,
        PRINT_MODULE_ID,
        STOCK_BASIC_MODULE_ID,
        NOTIFY_EMAIL_MODULE_ID,
    }
)
BUILTIN_OPERATOR_SURFACE_MODULE_IDS = frozenset(
    {CATALOG_EDITOR_MODULE_ID, CATALOG_IMPORT_OCR_MODULE_ID, KITCHEN_SCREEN_MODULE_ID, PICKUP_BOARD_BASIC_MODULE_ID}
)
BUILTIN_CUSTOMER_SURFACE_MODULE_IDS = frozenset(
    {CUSTOMER_STATUS_MODULE_ID, MENU_LIST_MODULE_ID, MENU_PHOTO_MAP_MODULE_ID}
)
BUILTIN_HARDWARE_PROBE_MODULE_IDS = frozenset({ORDER_PRINT_BACKUP_MODULE_ID, ORDER_ALERT_BASIC_MODULE_ID})


def operator_module_entry(
    runtime: PilotRuntime,
    manifest,
    *,
    enabled_now: bool,
    desired_enabled: bool,
) -> dict[str, Any]:
    lane = module_execution_lane(manifest)
    active = module_active(runtime, manifest)
    configured, missing_configuration = module_configuration(runtime, manifest)
    implementation = "builtin_reference" if manifest.module_id in BUILTIN_EXECUTOR_MODULE_IDS else "external_http"
    if manifest.module_id in BUILTIN_OPERATOR_SURFACE_MODULE_IDS:
        implementation = "builtin_operator_surface"
    if manifest.module_id in BUILTIN_CUSTOMER_SURFACE_MODULE_IDS:
        implementation = "builtin_customer_surface"
    if manifest.module_id in BUILTIN_HARDWARE_PROBE_MODULE_IDS:
        implementation = "builtin_hardware_probe"
    if manifest.module_id == GODPAY_MOCK_MODULE_ID:
        implementation = "internal_mock"
    if manifest.module_id == CHAOSPAY_MOCK_MODULE_ID:
        implementation = "internal_mock_planned"
    if (
        manifest.module_id not in BUILTIN_EXECUTOR_MODULE_IDS
        and manifest.module_id not in BUILTIN_OPERATOR_SURFACE_MODULE_IDS
        and manifest.module_id not in BUILTIN_CUSTOMER_SURFACE_MODULE_IDS
        and manifest.module_id not in BUILTIN_HARDWARE_PROBE_MODULE_IDS
        and lane != "payment"
        and not module_entrypoint(manifest)
    ):
        implementation = "manifest_only"
    executable = active and configured and implementation != "manifest_only"
    health = module_health(runtime, manifest, active=active, configured=configured)
    public_catalog = manifest.raw.get("public_catalog") or {}
    return {
        "module_id": manifest.module_id,
        "provider_id": manifest.provider_id,
        "version": manifest.version,
        "lane": lane,
        "module_class": str(manifest.raw.get("module_class") or ""),
        "module_type": str(manifest.raw.get("type") or ""),
        "declared": True,
        "enabled_now": enabled_now,
        "desired_enabled": desired_enabled,
        "restart_pending": enabled_now != desired_enabled,
        "active": active,
        "configured": configured,
        "executable": executable,
        "implementation": implementation,
        "visibility": manifest.visibility,
        "readiness": manifest.readiness,
        "status": manifest.status,
        "description": manifest.description,
        "operator_status": manifest.operator_status,
        "depends_on": module_requires(manifest),
        "dependents": module_dependents(runtime, manifest.module_id),
        "owner_function": str(public_catalog.get("function") or "").strip(),
        "data_access_summary": str(public_catalog.get("data_access_summary") or "").strip(),
        "trust_status": str(public_catalog.get("trust_status") or "").strip(),
        "data_access": list(manifest.data_access),
        "input_events": list(manifest.input_events),
        "output_events": list(manifest.output_events),
        "failure_modes": list(manifest.failure_modes),
        "missing_configuration": missing_configuration,
        "configuration": module_operator_configuration(runtime, manifest),
        "suggested_fallbacks": {
            event_name: list(module_ids)
            for event_name, module_ids in manifest.suggested_fallbacks.items()
        },
        **health,
    }


def module_operator_configuration(runtime: PilotRuntime, manifest) -> dict[str, Any]:
    if manifest.module_id == ORDER_PRINT_BACKUP_MODULE_ID:
        return {
            "target": runtime.config.backup_print_target,
            "driver": runtime.config.backup_print_driver,
            "spool_dir": runtime.config.backup_print_spool_dir,
            "device_path": runtime.config.backup_print_device_path,
            "self_test_path": f"/operator/modules/{ORDER_PRINT_BACKUP_MODULE_ID}/self-test",
        }
    if manifest.module_id == ORDER_ALERT_BASIC_MODULE_ID:
        return {
            "target": runtime.config.alert_target,
            "mode": runtime.config.alert_mode,
            "self_test_path": f"/operator/modules/{ORDER_ALERT_BASIC_MODULE_ID}/self-test",
        }
    if manifest.module_id == PICKUP_BOARD_BASIC_MODULE_ID:
        return {
            "target": runtime.config.pickup_board_target,
            "view_url": "/operator/pickup-board",
            "data_url": "/operator/pickup-board/data",
            "self_test_path": f"/operator/modules/{PICKUP_BOARD_BASIC_MODULE_ID}/self-test",
        }
    if manifest.module_id == GODPAY_MOCK_MODULE_ID:
        return {
            "success_threshold": runtime.config.godpay_success_threshold,
            "seeded": bool(runtime.config.godpay_seed),
            "forced_roll": runtime.config.godpay_force_roll,
        }
    if manifest.module_id == CATALOG_IMPORT_OCR_MODULE_ID:
        return {
            "preview_text_path": "/operator/menu/import-preview",
            "preview_image_path": "/operator/menu/import-image-preview",
            "ui_panel": "catalog_import",
            "draft_only": True,
        }
    if manifest.module_id == CHAOSPAY_MOCK_MODULE_ID:
        return {
            "status": "planned",
            "scenarios": [
                "instant_success",
                "user_cancelled",
                "provider_timeout",
                "duplicate_callback",
                "late_callback_after_expiry",
                "wrong_amount",
                "wrong_currency",
                "invalid_signature",
                "paid_after_cancelled",
                "merchant_confirms_without_payment",
                "out_of_order_status",
                "conflicting_duplicate_callback",
            ],
        }
    return {}


def undeclared_module_entry(runtime: PilotRuntime, module_id: str) -> dict[str, Any]:
    desired_ids = desired_module_ids(runtime)
    return {
        "module_id": module_id,
        "provider_id": None,
        "version": None,
        "lane": "unknown",
        "module_class": "unknown",
        "module_type": "unknown",
        "declared": False,
        "enabled_now": True,
        "desired_enabled": module_id in desired_ids,
        "restart_pending": (module_id in desired_ids) is False,
        "active": False,
        "configured": False,
        "executable": False,
        "implementation": "undeclared",
        "visibility": "operator_only",
        "readiness": "unknown",
        "status": "undeclared",
        "description": "Enabled by this node, but no local or reference manifest was loaded.",
        "operator_status": "manifest required before execution or public declaration",
        "depends_on": [],
        "dependents": [],
        "owner_function": "",
        "data_access_summary": "",
        "trust_status": "",
        "data_access": [],
        "input_events": [],
        "output_events": [],
        "failure_modes": [],
        "missing_configuration": ["module_manifest"],
        "configuration": {},
        "health": "undeclared",
        "health_reason": "module_manifest_missing",
        "health_url": None,
        "last_checked_at": None,
        "suggested_fallbacks": {},
    }


def module_catalog_summary(runtime: PilotRuntime) -> dict[str, Any]:
    locale = operator_locale(runtime)
    active_payment_module_id = effective_payment_module_id(runtime)
    desired_payment_id = desired_payment_module_id(runtime)
    desired_ids = desired_module_ids(runtime)
    current_ids = current_module_ids(runtime)
    declared = [
        operator_module_entry(
            runtime,
            manifest,
            enabled_now=True,
            desired_enabled=manifest.module_id in desired_ids,
        )
        for manifest in runtime.config.resolved_modules.manifests
    ]
    undeclared = [
        undeclared_module_entry(runtime, module_id)
        for module_id in runtime.config.undeclared_node_modules
    ]
    modules = declared + undeclared
    available_modules = [
        operator_module_entry(
            runtime,
            manifest,
            enabled_now=False,
            desired_enabled=manifest.module_id in desired_ids,
        )
        for manifest in runtime.config.available_resolved_modules.manifests
        if manifest.module_id not in current_ids
    ]
    lanes: dict[str, dict[str, Any]] = {}
    for entry in modules:
        lane = str(entry["lane"])
        lane_payload = lanes.setdefault(
            lane,
            {
                "active_module_id": active_payment_module_id if lane == "payment" else None,
                "modules": [],
            },
        )
        lane_payload["modules"].append(entry)

    return {
        "node_id": runtime.config.node_id,
        "checked_at": utc_now().isoformat(),
        "locale": operator_locale_payload(locale),
        "current_module_ids": current_ids,
        "desired_module_ids": desired_ids,
        "desired_module_ids_updated_at": desired_module_ids_updated_at(runtime),
        "restart_required": module_restart_required(runtime),
        "discover": {
            "public_catalog_url": f"{PUBLIC_CATALOG_URLS.protocols_site_url.rstrip('/')}/modules/",
            "shop_family_url": f"{PUBLIC_CATALOG_URLS.protocols_site_url.rstrip('/')}/modules/shop/",
            "operator_discover_url": "/operator/discover",
            "operator_import_url": "/operator/import",
        },
        "active_by_lane": {
            "payment": active_payment_module_id or None,
        },
        "desired_active_by_lane": {
            "payment": desired_payment_id,
        },
        "modules": modules,
        "available_modules": available_modules,
        "lanes": lanes,
        "undeclared_modules": undeclared,
        "imported_manifest_count": 0,
        "imported_manifests": [],
    }


def operator_modules(runtime: PilotRuntime) -> dict[str, Any]:
    summary = module_catalog_summary(runtime)
    imported = imported_manifest_summaries(runtime)
    summary["imported_manifest_count"] = len(imported)
    summary["imported_manifests"] = imported
    return summary


def _imported_manifest_title(manifest, locale: str) -> str:
    public_catalog = manifest.raw.get("public_catalog") or {}
    raw_title = public_catalog.get("title")
    if isinstance(raw_title, dict):
        title = localized_text({str(key): str(value) for key, value in raw_title.items()}, locale)
        if title:
            return title
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    return manifest.module_id


def _imported_manifest_summary_text(manifest, locale: str) -> str:
    public_catalog = manifest.raw.get("public_catalog") or {}
    raw_summary = public_catalog.get("summary")
    if isinstance(raw_summary, dict):
        summary = localized_text({str(key): str(value) for key, value in raw_summary.items()}, locale)
        if summary:
            return summary
    if isinstance(raw_summary, str) and raw_summary.strip():
        return raw_summary.strip()
    return manifest.description.strip()


def _imported_manifest_summary(runtime: PilotRuntime, record: dict[str, str]) -> dict[str, Any]:
    locale = operator_locale(runtime)
    try:
        payload = json.loads(record["manifest_json"])
        if not isinstance(payload, dict):
            raise ValueError("Imported manifest must be a JSON object")
        manifest = ModuleManifest.from_payload(
            payload,
            source_path=Path(record["source_name"] or f"{record['module_id']}.json"),
        )
    except Exception:
        return {
            "module_id": record["module_id"],
            "provider_id": record["provider_id"],
            "version": record["version"],
            "title": record["module_id"],
            "short_description": "",
            "source_type": record["source_type"],
            "source_name": record["source_name"],
            "imported_at": record["imported_at"],
            "updated_at": record["updated_at"],
            "validation_status": record["validation_status"],
            "validation_error": record["validation_error"] or "Stored manifest could not be parsed again.",
            "runnable_now": False,
            "selectable_for_desired_set": False,
            "blocked_reason": "metadata_only_phase",
        }

    return {
        "module_id": manifest.module_id,
        "provider_id": manifest.provider_id,
        "version": manifest.version,
        "title": _imported_manifest_title(manifest, locale),
        "short_description": _imported_manifest_summary_text(manifest, locale),
        "source_type": record["source_type"],
        "source_name": record["source_name"],
        "imported_at": record["imported_at"],
        "updated_at": record["updated_at"],
        "validation_status": record["validation_status"],
        "validation_error": record["validation_error"] or None,
        "runnable_now": False,
        "selectable_for_desired_set": False,
        "blocked_reason": "metadata_only_phase",
    }


def imported_manifest_summaries(runtime: PilotRuntime) -> list[dict[str, Any]]:
    return [
        _imported_manifest_summary(runtime, record)
        for record in runtime.store.list_imported_module_manifest_records()
    ]


def operator_import(runtime: PilotRuntime) -> dict[str, Any]:
    modules = operator_modules(runtime)
    return {
        "node_id": runtime.config.node_id,
        "checked_at": modules["checked_at"],
        "locale": modules["locale"],
        "current_module_ids": modules["current_module_ids"],
        "desired_module_ids": modules["desired_module_ids"],
        "restart_required": modules["restart_required"],
        "imported_manifest_count": modules["imported_manifest_count"],
        "imported_manifests": modules["imported_manifests"],
        "links": {
            "discover_url": "/operator/discover",
            "modules_url": "/operator/modules",
            "public_catalog_url": modules["discover"]["public_catalog_url"],
        },
    }


def operator_imported_manifests(runtime: PilotRuntime) -> dict[str, Any]:
    return operator_import(runtime)


def _imported_module_id_collision(runtime: PilotRuntime, module_id: str) -> bool:
    return module_id in set(runtime.config.available_resolved_modules.module_ids)


def operator_import_module_manifest(
    runtime: PilotRuntime,
    *,
    source_name: str,
    content_bytes: bytes,
) -> dict[str, Any]:
    normalized_source_name = source_name.strip()
    if not normalized_source_name:
        raise HTTPException(status_code=400, detail="source_name must include a filename")
    if not content_bytes:
        raise HTTPException(status_code=400, detail="manifest_json must not be empty")

    try:
        payload = json.loads(content_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="manifest_json must be valid UTF-8 JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="manifest_json must contain one JSON object")

    try:
        manifest = ModuleManifest.from_payload(payload, source_path=Path(normalized_source_name))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid module manifest: {exc}") from exc

    module_id = manifest.module_id.strip()
    provider_id = manifest.provider_id.strip()
    version = manifest.version.strip()
    if not module_id:
        raise HTTPException(status_code=400, detail="module manifest must include a non-empty module_id")
    if not provider_id:
        raise HTTPException(status_code=400, detail="module manifest must include a non-empty provider_id")
    if not version:
        raise HTTPException(status_code=400, detail="module manifest must include a non-empty version")

    existing_import = runtime.store.get_imported_module_manifest_record(module_id)
    if existing_import is None and _imported_module_id_collision(runtime, module_id):
        raise HTTPException(
            status_code=400,
            detail=f"Imported manifest shadows a reference or env-backed module: {module_id}",
        )

    record = runtime.store.upsert_imported_module_manifest_record(
        module_id=module_id,
        provider_id=provider_id,
        version=version,
        source_name=normalized_source_name,
        manifest_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        validation_status="validated",
        validation_error="",
    )
    return {
        "replaced": existing_import is not None,
        "manifest": _imported_manifest_summary(runtime, record),
        "imported_manifest_count": len(runtime.store.list_imported_module_manifest_records()),
    }


def operator_delete_imported_module_manifest(runtime: PilotRuntime, module_id: str) -> dict[str, Any]:
    normalized_module_id = module_id.strip()
    if not normalized_module_id:
        raise HTTPException(status_code=404, detail="Imported manifest not found")
    removed = runtime.store.delete_imported_module_manifest_record(normalized_module_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Imported manifest not found: {normalized_module_id}")
    return {
        "removed": True,
        "module_id": normalized_module_id,
        "imported_manifest_count": len(runtime.store.list_imported_module_manifest_records()),
    }


def operator_discover(runtime: PilotRuntime) -> dict[str, Any]:
    locale = operator_locale(runtime)
    summary = module_catalog_summary(runtime)
    catalog = localized_module_catalog(locale, urls=PUBLIC_CATALOG_URLS)
    current_lookup = {entry["module_id"]: entry for entry in summary["modules"]}
    available_lookup = {entry["module_id"]: entry for entry in summary["available_modules"]}
    current_ids = set(summary["current_module_ids"])
    desired_ids = set(summary["desired_module_ids"])

    discover_modules: list[dict[str, Any]] = []
    for entry in catalog["modules"]:
        module_id = entry["module_id"]
        operator_entry = current_lookup.get(module_id) or available_lookup.get(module_id)
        discover_modules.append(
            {
                **entry,
                "enabled_now": module_id in current_ids,
                "desired_enabled": module_id in desired_ids,
                "health": operator_entry.get("health") if operator_entry else "available",
                "health_reason": operator_entry.get("health_reason") if operator_entry else "public_catalog_entry",
                "open_module_url": f"/operator/modules/view/{module_id}",
            }
        )

    recommended_lookup = {
        entry["module_id"]: entry
        for entry in discover_modules
        if entry["module_id"] in set(catalog["family"]["recommended_module_ids"])
    }
    recommended_modules = [
        recommended_lookup[module_id]
        for module_id in catalog["family"]["recommended_module_ids"]
        if module_id in recommended_lookup
    ]

    categories: list[dict[str, Any]] = []
    for category in catalog["categories"]:
        category_modules = [
            entry for entry in discover_modules if entry["category_id"] == category["id"]
        ]
        categories.append(
            {
                **category,
                "module_count": len(category_modules),
                "modules": category_modules,
            }
        )

    return {
        "node_id": runtime.config.node_id,
        "checked_at": summary["checked_at"],
        "locale": operator_locale_payload(locale),
        "family": catalog["family"],
        "categories": categories,
        "modules": discover_modules,
        "recommended_modules": recommended_modules,
        "current_modules": summary["modules"],
        "current_module_ids": summary["current_module_ids"],
        "desired_module_ids": summary["desired_module_ids"],
        "restart_required": summary["restart_required"],
        "links": {
            "public_catalog_url": summary["discover"]["public_catalog_url"],
            "shop_family_url": summary["discover"]["shop_family_url"],
            "modules_room_url": "/operator/modules",
            "import_room_url": "/operator/import",
        },
    }


def operator_node(runtime: PilotRuntime) -> dict[str, Any]:
    locale = operator_locale(runtime)
    setup = setup_state(runtime)
    state = operator_state(runtime)
    modules = module_catalog_summary(runtime)
    completed_steps = [str(step).strip() for step in setup.get("completed_steps") or [] if str(step).strip()]
    return {
        "node_id": runtime.config.node_id,
        "checked_at": modules["checked_at"],
        "locale": operator_locale_payload(locale),
        "state": state,
        "modules": {
            "current_module_ids": modules["current_module_ids"],
            "desired_module_ids": modules["desired_module_ids"],
            "desired_module_ids_updated_at": modules["desired_module_ids_updated_at"],
            "restart_required": modules["restart_required"],
            "active_by_lane": modules["active_by_lane"],
        },
        "hardware": {
            "runtime_profile": runtime.config.hardware_profile,
            "runtime_base_profile": setup.get("runtime_hardware_base_profile"),
            "runtime_enabled_addons": list(setup.get("runtime_hardware_enabled_addons") or []),
            "confirmed_bundle_profile": setup.get("hardware_profile"),
            "confirmed_base_profile": setup.get("hardware_base_profile"),
            "confirmed_enabled_addons": list(setup.get("hardware_enabled_addons") or []),
        },
        "setup": {
            "completed": bool(setup.get("completed")),
            "completed_steps": completed_steps,
            "catalog_ready": bool(setup.get("catalog_ready")),
            "local_tests_run": "local_tests_run" in set(completed_steps),
            "started_at": setup.get("started_at"),
            "completed_at": setup.get("completed_at"),
            "last_reviewed_at": setup.get("last_reviewed_at"),
        },
        "links": {
            "public_catalog_url": modules["discover"]["public_catalog_url"],
            "shop_family_url": modules["discover"]["shop_family_url"],
            "discover_url": "/operator/discover",
            "modules_url": "/operator/modules",
            "setup_url": "/operator/setup",
            "discover_room_url": "/operator/discover",
            "modules_room_url": "/operator/modules",
            "setup_room_url": "/operator/setup",
        },
    }


def module_detail_entry(runtime: PilotRuntime, module_id: str) -> dict[str, Any]:
    normalized_module_id = module_id.strip()
    if not normalized_module_id:
        raise HTTPException(status_code=404, detail="Unknown module_id")

    summary = module_catalog_summary(runtime)
    for entry in summary["modules"]:
        if entry["module_id"] == normalized_module_id:
            doc_payload = module_doc_payload(normalized_module_id, entry.get("provider_id"))
            return {
                "node_id": runtime.config.node_id,
                "checked_at": summary["checked_at"],
                "locale": summary["locale"],
                "current_module_ids": summary["current_module_ids"],
                "desired_module_ids": summary["desired_module_ids"],
                "desired_module_ids_updated_at": summary["desired_module_ids_updated_at"],
                "restart_required": summary["restart_required"],
                "active_by_lane": summary["active_by_lane"],
                "desired_active_by_lane": summary["desired_active_by_lane"],
                "module": entry,
                "documentation": doc_payload,
            }
    manifest = known_module_manifest(runtime, normalized_module_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Unknown module_id: {normalized_module_id}")
    entry = operator_module_entry(
        runtime,
        manifest,
        enabled_now=False,
        desired_enabled=normalized_module_id in summary["desired_module_ids"],
    )
    return {
        "node_id": runtime.config.node_id,
        "checked_at": summary["checked_at"],
        "locale": summary["locale"],
        "current_module_ids": summary["current_module_ids"],
        "desired_module_ids": summary["desired_module_ids"],
        "desired_module_ids_updated_at": summary["desired_module_ids_updated_at"],
        "restart_required": summary["restart_required"],
        "active_by_lane": summary["active_by_lane"],
        "desired_active_by_lane": summary["desired_active_by_lane"],
        "module": entry,
        "documentation": module_doc_payload(normalized_module_id, manifest.provider_id),
    }


def _module_ids_still_requiring(runtime: PilotRuntime, module_id: str, desired_ids: list[str]) -> list[str]:
    blockers: list[str] = []
    desired_set = set(desired_ids)
    for candidate_module_id in desired_ids:
        if candidate_module_id == module_id:
            continue
        required_module_ids = transitive_module_requires(runtime, candidate_module_id)
        if module_id in required_module_ids and candidate_module_id in desired_set:
            blockers.append(candidate_module_id)
    return blockers


def _expand_required_module_ids(runtime: PilotRuntime, requested_module_ids: list[str]) -> list[str]:
    expanded = list(requested_module_ids)
    seen = set(expanded)
    index = 0
    while index < len(expanded):
        manifest = known_module_manifest(runtime, expanded[index])
        index += 1
        if manifest is None:
            continue
        for dependency_module_id in module_requires(manifest):
            dependency_manifest = known_module_manifest(runtime, dependency_module_id)
            if dependency_manifest is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Module {manifest.module_id} requires unknown module: "
                        f"{dependency_module_id}"
                    ),
                )
            if dependency_module_id in seen:
                continue
            seen.add(dependency_module_id)
            expanded.append(dependency_module_id)
    return expanded


def operator_update_module_set(
    runtime: PilotRuntime,
    payload: OperatorModuleSetUpdate,
) -> dict[str, Any]:
    requested_ids = [str(module_id).strip() for module_id in payload.module_ids]
    normalized_requested_ids: list[str] = []
    seen: set[str] = set()
    for module_id in requested_ids:
        if not module_id or module_id in seen:
            continue
        normalized_requested_ids.append(module_id)
        seen.add(module_id)

    if not normalized_requested_ids:
        raise HTTPException(status_code=400, detail="module_ids must not be empty")

    unknown_module_ids = [
        module_id for module_id in normalized_requested_ids
        if known_module_manifest(runtime, module_id) is None
    ]
    if unknown_module_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown module_id: {unknown_module_ids[0]}",
        )

    current_desired_ids = desired_module_ids(runtime)
    removed_module_ids = [module_id for module_id in current_desired_ids if module_id not in normalized_requested_ids]
    for removed_module_id in removed_module_ids:
        blockers = _module_ids_still_requiring(runtime, removed_module_id, normalized_requested_ids)
        if blockers:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot disable {removed_module_id} while other desired modules still depend on it: "
                    f"{', '.join(blockers)}"
                ),
            )

    expanded_ids = _expand_required_module_ids(runtime, normalized_requested_ids)
    payment_module_ids = [
        module_id for module_id in expanded_ids
        if (manifest := known_module_manifest(runtime, module_id)) is not None and module_is_payment(manifest)
    ]
    if not payment_module_ids:
        raise HTTPException(
            status_code=400,
            detail="Desired module set must include at least one payment module",
        )

    persisted_payment_module_id = runtime.store.get_state(ACTIVE_PAYMENT_MODULE_STATE_KEY, "").strip()
    if persisted_payment_module_id not in payment_module_ids:
        runtime.store.set_state(ACTIVE_PAYMENT_MODULE_STATE_KEY, payment_module_ids[0])

    set_desired_module_ids(runtime, expanded_ids)
    return module_catalog_summary(runtime)


async def operator_update_state(runtime: PilotRuntime, payload: OperatorStateUpdate) -> dict[str, Any]:
    if payload.open is not None:
        runtime.store.set_state("open", "true" if payload.open else "false")
    if payload.order_mode is not None:
        runtime.store.set_state("order_mode", payload.order_mode)
    await run_registry_cycle(runtime, force_announce=True)
    return operator_state(runtime)


def operator_update_payment_module(
    runtime: PilotRuntime,
    payload: OperatorPaymentModuleUpdate,
) -> dict[str, Any]:
    set_effective_payment_module_id(runtime, payload.module_id)
    return operator_modules(runtime)


def operator_menu(runtime: PilotRuntime) -> Menu:
    return runtime.store.menu(include_inactive=True)


def operator_module_self_test(runtime: PilotRuntime, module_id: str) -> dict[str, Any]:
    normalized_module_id = module_id.strip()
    if normalized_module_id not in effective_flow_module_ids(runtime):
        raise HTTPException(status_code=404, detail=f"Module is not enabled: {normalized_module_id}")

    manifest = runtime.config.resolved_modules.get(normalized_module_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Unknown module_id: {normalized_module_id}")

    configured, missing_configuration = module_configuration(runtime, manifest)
    if not configured:
        raise HTTPException(
            status_code=400,
            detail=f"Module is missing required configuration: {', '.join(missing_configuration)}",
        )

    if normalized_module_id == ORDER_PRINT_BACKUP_MODULE_ID:
        return run_backup_print_self_test(runtime.config)
    if normalized_module_id == ORDER_ALERT_BASIC_MODULE_ID:
        return run_order_alert_self_test(runtime.config)
    if normalized_module_id == PICKUP_BOARD_BASIC_MODULE_ID:
        board = operator_pickup_board_data(runtime)
        return {
            "module_id": PICKUP_BOARD_BASIC_MODULE_ID,
            "events": ["OUTBOUND_ACTION_REQUESTED", "ACTION_COMPLETED"],
            "success": True,
            "outcome": "SUCCESS",
            "target": runtime.config.pickup_board_target,
            "view_url": "/operator/pickup-board",
            "order_count": len(board["orders"]),
            "checked_at": board["checked_at"],
        }

    raise HTTPException(status_code=404, detail=f"Self-test is not available for module: {normalized_module_id}")


def operator_replace_menu(runtime: PilotRuntime, payload: MenuUpdate) -> Menu:
    updated_menu = runtime.store.replace_menu(payload.items)
    if CATALOG_EDITOR_MODULE_ID in effective_flow_module_ids(runtime):
        checked_at = utc_now()
        action_id = f"catalog:{checked_at.isoformat()}:replace"
        runtime.store.record_order_event(
            ModuleResultEvent(
                event="CATALOG_UPDATED",
                source_module=CATALOG_EDITOR_MODULE_ID,
                order_id=None,
                action_id=action_id,
                idempotency_key=action_id,
                outcome="SUCCESS",
                severity="low",
                retryable=False,
                side_effect_state="confirmed",
                timestamp=checked_at,
                metadata={
                    "item_count": len(updated_menu.items),
                    "active_item_count": sum(1 for item in updated_menu.items if item.active),
                    "operator_surface": CATALOG_EDITOR_MODULE_ID,
                    "contract_phase": "result",
                },
            )
        )
    return updated_menu


def operator_menu_import_preview(
    runtime: PilotRuntime,
    payload: MenuImportPreviewRequest,
) -> MenuImportPreviewResponse:
    if not catalog_import_ocr_module_enabled(runtime):
        raise HTTPException(status_code=404, detail="Catalog OCR import module is not enabled")
    return preview_menu_import(payload)


def operator_menu_import_image_preview(
    runtime: PilotRuntime,
    *,
    image_bytes: bytes,
    source_name: str = "",
) -> MenuImportPreviewResponse:
    if not catalog_import_ocr_module_enabled(runtime):
        raise HTTPException(status_code=404, detail="Catalog OCR import module is not enabled")
    try:
        return preview_menu_import_from_image(image_bytes=image_bytes, source_name=source_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    previous_order = runtime.store.get_order(order_id)
    if previous_order is None:
        raise HTTPException(status_code=404, detail=f"Unknown order_id: {order_id}")
    updated_order = runtime.store.update_order_status(order_id, payload)
    if KITCHEN_SCREEN_MODULE_ID not in effective_flow_module_ids(runtime):
        return updated_order
    action_id = (
        f"order:{updated_order.order_id}:kitchen-status:"
        f"{updated_order.status}:{updated_order.updated_at.isoformat()}"
    )
    runtime.store.record_order_event(
        build_result_event(
            runtime=runtime,
            event="ORDER_STATUS_UPDATED",
            source_module=KITCHEN_SCREEN_MODULE_ID,
            order=updated_order,
            action_id=action_id,
            idempotency_key=action_id,
            outcome="SUCCESS",
            severity="low",
            retryable=False,
            side_effect_state="confirmed",
            metadata={
                "previous_status": previous_order.status,
                "next_status": updated_order.status,
                "status_message": updated_order.status_message,
                "estimated_ready": (
                    updated_order.estimated_ready.isoformat()
                    if updated_order.estimated_ready is not None
                    else None
                ),
                "operator_surface": KITCHEN_SCREEN_MODULE_ID,
            },
        )
    )
    return updated_order


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

    @app.get("/p4p/assets/food-image-fixtures/{asset_path:path}", response_class=FileResponse)
    def food_image_fixture_route(asset_path: str) -> FileResponse:
        return food_image_fixture(asset_path)

    @app.get("/operator/assets/{asset_path:path}", response_class=FileResponse)
    def operator_asset_route(asset_path: str) -> FileResponse:
        return operator_asset(asset_path)

    @app.get("/p4p/menu/list", response_class=HTMLResponse)
    def public_menu_list_page_route() -> str:
        return public_menu_list_page(runtime)

    @app.get("/p4p/menu/photo-map", response_class=HTMLResponse)
    def public_menu_photo_map_page_route() -> str:
        return public_menu_photo_map_page(runtime)

    @app.post("/p4p/order", response_model=OrderAccepted | OrderRejected)
    def public_order_route(payload: OrderRequest) -> OrderAccepted | OrderRejected:
        return public_order(runtime, payload)

    @app.get("/p4p/orders/{order_id}", response_class=HTMLResponse)
    def public_order_status_page_route(order_id: str) -> str:
        return public_order_status_page(runtime, order_id)

    @app.get("/p4p/orders/{order_id}/status", response_model=PublicOrderStatus)
    def public_order_status_route(order_id: str) -> PublicOrderStatus:
        return public_order_status(runtime, order_id)

    @app.get("/p4p/info")
    def public_info_route() -> dict[str, Any]:
        return public_info(runtime)

    @app.get("/operator", response_class=HTMLResponse)
    def operator_gui_route() -> str:
        return operator_gui(runtime)

    @app.get("/operator/welcome", response_class=HTMLResponse)
    def operator_welcome_route() -> str:
        return operator_welcome_page(runtime)

    @app.get("/operator/setup", response_model=None)
    def operator_setup_route(
        request: Request,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Any:
        if request_prefers_html(request):
            return HTMLResponse(operator_setup_page(runtime))
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_setup(runtime)

    @app.get("/operator/catalog", response_class=HTMLResponse)
    def operator_catalog_route() -> str:
        return operator_catalog_page(runtime)

    @app.get("/operator/discover", response_model=None)
    def operator_discover_route(
        request: Request,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Any:
        if request_prefers_html(request):
            return HTMLResponse(operator_discover_page(runtime))
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_discover(runtime)

    @app.get("/operator/import", response_model=None)
    def operator_import_route(
        request: Request,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Any:
        if request_prefers_html(request):
            return HTMLResponse(operator_import_page(runtime))
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_import(runtime)

    @app.get("/operator/node", response_model=None)
    def operator_node_route(
        request: Request,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Any:
        if request_prefers_html(request):
            return HTMLResponse(operator_node_page(runtime))
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_node(runtime)

    @app.get("/operator/modules", response_model=None)
    def operator_modules_route(
        request: Request,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> Any:
        if request_prefers_html(request):
            return HTMLResponse(operator_modules_page(runtime))
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_modules(runtime)

    @app.get("/operator/modules/view/{module_id}", response_class=HTMLResponse)
    def operator_module_view_route(module_id: str) -> str:
        return operator_module_view_page(runtime, module_id)

    @app.get("/operator/pickup-board", response_class=HTMLResponse)
    def operator_pickup_board_route() -> str:
        return operator_pickup_board_page(runtime)

    @app.get("/operator/state")
    def operator_state_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_state(runtime)

    @app.get("/operator/modules/{module_id}")
    def operator_module_detail_route(
        module_id: str,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return module_detail_entry(runtime, module_id)

    @app.get("/operator/modules/imports")
    def operator_module_imports_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_imported_manifests(runtime)

    @app.post("/operator/modules/import-manifest")
    def operator_import_manifest_route(
        payload: OperatorModuleManifestImport,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_import_module_manifest(
            runtime,
            source_name=payload.source_name,
            content_bytes=payload.manifest_json.encode("utf-8"),
        )

    @app.delete("/operator/modules/imports/{module_id}")
    def operator_delete_imported_manifest_route(
        module_id: str,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_delete_imported_module_manifest(runtime, module_id)

    @app.get("/operator/pickup-board/data")
    def operator_pickup_board_data_route(
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_pickup_board_data(runtime)

    @app.post("/operator/modules/{module_id}/self-test")
    def operator_module_self_test_route(
        module_id: str,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_module_self_test(runtime, module_id)

    @app.patch("/operator/modules/payment")
    def operator_update_payment_module_route(
        payload: OperatorPaymentModuleUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_update_payment_module(runtime, payload)

    @app.patch("/operator/modules/set")
    def operator_update_module_set_route(
        payload: OperatorModuleSetUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_update_module_set(runtime, payload)

    @app.patch("/operator/setup")
    def operator_update_setup_route(
        payload: OperatorSetupUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_update_setup(runtime, payload)

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

    @app.post("/operator/menu/import-preview", response_model=MenuImportPreviewResponse)
    def operator_menu_import_preview_route(
        payload: MenuImportPreviewRequest,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> MenuImportPreviewResponse:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_menu_import_preview(runtime, payload)

    @app.post("/operator/menu/import-image-preview", response_model=MenuImportPreviewResponse)
    async def operator_menu_import_image_preview_route(
        request: Request,
        source_name: str = "",
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> MenuImportPreviewResponse:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_menu_import_image_preview(
            runtime,
            image_bytes=await request.body(),
            source_name=source_name,
        )

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
    "operator_catalog_page",
    "operator_discover",
    "operator_discover_page",
    "operator_gui",
    "operator_node",
    "operator_node_page",
    "operator_setup",
    "operator_setup_page",
    "operator_update_setup",
    "operator_welcome_page",
    "operator_menu",
    "operator_menu_import_image_preview",
    "operator_menu_import_preview",
    "operator_module_self_test",
    "operator_modules",
    "operator_modules_page",
    "operator_order_events",
    "node_state",
    "operator_orders",
    "operator_pickup_board_data",
    "operator_pickup_board_page",
    "operator_reannounce",
    "operator_state",
    "operator_update_payment_module",
    "operator_update_order",
    "operator_update_state",
    "public_info",
    "public_menu",
    "public_order",
    "public_order_status",
    "public_order_status_page",
    "require_operator_token",
    "root_index",
    "run_registry_cycle",
]
