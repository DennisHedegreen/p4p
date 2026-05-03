from __future__ import annotations

import asyncio
import html
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from p4p_core import (
    Menu,
    MenuUpdate,
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

from pilot_node.config import OperatorPaymentModuleUpdate, OperatorStateUpdate
from pilot_node.execution import (
    CHAOSPAY_MOCK_MODULE_ID,
    CATALOG_EDITOR_MODULE_ID,
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
from pilot_node.runtime import (
    PilotRuntime,
    effective_flow_module_ids,
    effective_payment_module_id,
    enabled_module_declarations,
    node_accepts_orders,
    node_state,
    public_module_projection,
    public_module_declarations,
    registration_payload,
    set_effective_payment_module_id,
    sign_node_announcement,
    signed_heartbeat_payload,
)


OPERATOR_HTML_PATH = Path(__file__).resolve().parents[1] / "pilot-node" / "operator.html"


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
            "menu_list": "GET /p4p/menu/list",
            "menu_photo_map": "GET /p4p/menu/photo-map",
            "order": "POST /p4p/order",
            "order_status_page": "GET /p4p/orders/{order_id}",
            "order_status_json": "GET /p4p/orders/{order_id}/status",
            "operator_gui": "GET /operator",
            "operator_state": "GET /operator/state",
            "operator_modules": "GET /operator/modules",
            "operator_payment_module": "PATCH /operator/modules/payment",
            "operator_orders": "GET /operator/orders",
            "operator_reannounce": "POST /operator/reannounce",
        },
    }


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
                cards.append(
                    f"""
          <article class="item" data-item-id="{html.escape(item.id, quote=True)}" data-price="{item.price}">
            <div>
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
        padding: 12px 0;
        border-top: 1px solid #e4ebe8;
      }}
      .item:first-of-type {{
        border-top: 0;
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
            regions.append(
                f"""
              <button
                type="button"
                class="hotspot"
                data-photo-map-item-id="{html.escape(item.id, quote=True)}"
                data-price="{item.price}"
                data-region-index="{index}"
                aria-pressed="false"
              >
                <span class="region-number">{index}</span>
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
      .hotspot[aria-pressed="true"] {{
        border-color: #00796b;
        background: #ecf8f5;
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
        "node": node.model_dump(mode="json", exclude_none=True),
        "accepts_orders": node_accepts_orders(runtime, node),
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
    return OPERATOR_HTML_PATH.read_text(encoding="utf-8")


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
BUILTIN_OPERATOR_SURFACE_MODULE_IDS = frozenset({CATALOG_EDITOR_MODULE_ID, KITCHEN_SCREEN_MODULE_ID})
BUILTIN_CUSTOMER_SURFACE_MODULE_IDS = frozenset(
    {CUSTOMER_STATUS_MODULE_ID, MENU_LIST_MODULE_ID, MENU_PHOTO_MAP_MODULE_ID}
)


def operator_module_entry(runtime: PilotRuntime, manifest) -> dict[str, Any]:
    lane = module_execution_lane(manifest)
    active = module_active(runtime, manifest)
    configured, missing_configuration = module_configuration(runtime, manifest)
    implementation = "builtin_reference" if manifest.module_id in BUILTIN_EXECUTOR_MODULE_IDS else "external_http"
    if manifest.module_id in BUILTIN_OPERATOR_SURFACE_MODULE_IDS:
        implementation = "builtin_operator_surface"
    if manifest.module_id in BUILTIN_CUSTOMER_SURFACE_MODULE_IDS:
        implementation = "builtin_customer_surface"
    if manifest.module_id == GODPAY_MOCK_MODULE_ID:
        implementation = "internal_mock"
    if manifest.module_id == CHAOSPAY_MOCK_MODULE_ID:
        implementation = "internal_mock_planned"
    if (
        manifest.module_id not in BUILTIN_EXECUTOR_MODULE_IDS
        and manifest.module_id not in BUILTIN_OPERATOR_SURFACE_MODULE_IDS
        and manifest.module_id not in BUILTIN_CUSTOMER_SURFACE_MODULE_IDS
        and lane != "payment"
        and not module_entrypoint(manifest)
    ):
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
        "configuration": module_operator_configuration(runtime, manifest),
        "suggested_fallbacks": {
            event_name: list(module_ids)
            for event_name, module_ids in manifest.suggested_fallbacks.items()
        },
        **health,
    }


def module_operator_configuration(runtime: PilotRuntime, manifest) -> dict[str, Any]:
    if manifest.module_id == GODPAY_MOCK_MODULE_ID:
        return {
            "success_threshold": runtime.config.godpay_success_threshold,
            "seeded": bool(runtime.config.godpay_seed),
            "forced_roll": runtime.config.godpay_force_roll,
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
    active_payment_module_id = effective_payment_module_id(runtime)
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
                "active_module_id": active_payment_module_id if lane == "payment" else None,
                "modules": [],
            },
        )
        lane_payload["modules"].append(entry)

    return {
        "node_id": runtime.config.node_id,
        "checked_at": utc_now().isoformat(),
        "active_by_lane": {
            "payment": active_payment_module_id or None,
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


def operator_update_payment_module(
    runtime: PilotRuntime,
    payload: OperatorPaymentModuleUpdate,
) -> dict[str, Any]:
    set_effective_payment_module_id(runtime, payload.module_id)
    return operator_modules(runtime)


def operator_menu(runtime: PilotRuntime) -> Menu:
    return runtime.store.menu(include_inactive=True)


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

    @app.patch("/operator/modules/payment")
    def operator_update_payment_module_route(
        payload: OperatorPaymentModuleUpdate,
        authorization: str | None = Header(default=None),
        x_p4p_operator_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(authorization=authorization, x_p4p_operator_token=x_p4p_operator_token)
        return operator_update_payment_module(runtime, payload)

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
    "operator_gui",
    "operator_modules",
    "operator_order_events",
    "node_state",
    "operator_orders",
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
