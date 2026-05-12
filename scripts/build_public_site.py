from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

P4P_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = (
    P4P_ROOT.parent
    if (P4P_ROOT.parent / "private").exists() or (P4P_ROOT.parent / "public").exists()
    else P4P_ROOT
)
ROOT = WORKSPACE_ROOT
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_core import load_reference_provider_catalog
from module_catalog import (
    PublicCatalogUrls,
    localized_text,
    normalize_locale,
    public_module_catalog,
)

PRIVATE_SITE_DATA_PATH = ROOT / "private/data/p4p/site-data.json"
REPO_SITE_DATA_PATH = P4P_ROOT / "docs/site-data.json"
PRIVATE_SCREENSHOT_PACK_PATH = ROOT / "private/data/p4p/screenshot-pack.json"
REPO_SCREENSHOT_PACK_PATH = P4P_ROOT / "docs/screenshot-pack.json"
PUBLIC_ROOT = ROOT / "public/www/pizza4people"
PROTOCOLS_ROOT = ROOT / "public/www/protocols4people"
PRESS_ROOT = PUBLIC_ROOT / "press-kit"
MODULES_ROOT = P4P_ROOT / "modules"
TEMPLATE_ROOT = P4P_ROOT / "scripts/templates/public-site"
PUBLIC_CATALOG_URLS = PublicCatalogUrls()
PIZZA_SCREENSHOT_ROOT = PUBLIC_ROOT / "assets" / "screenshots"
PROTOCOLS_SCREENSHOT_ROOT = PROTOCOLS_ROOT / "assets" / "screenshots"

SCREENSHOT_STAGE_LABELS = {
    "next_gate": {
        "da": "Næste gate / pilot-node",
        "en": "Pilot-node / next gate",
    },
    "public_proof": {
        "da": "Offentligt proof",
        "en": "Public proof",
    },
}


def resolve_first_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Could not resolve required path from: {joined}")


SITE_DATA_PATH = resolve_first_existing_path(PRIVATE_SITE_DATA_PATH, REPO_SITE_DATA_PATH)
SCREENSHOT_PACK_PATH = resolve_first_existing_path(PRIVATE_SCREENSHOT_PACK_PATH, REPO_SCREENSHOT_PACK_PATH)
SCREENSHOT_PACK_BASE_ROOT = ROOT if SCREENSHOT_PACK_PATH == PRIVATE_SCREENSHOT_PACK_PATH else P4P_ROOT


def load_screenshot_pack() -> dict[str, object]:
    return json.loads(SCREENSHOT_PACK_PATH.read_text(encoding="utf-8"))


def public_localized_text(texts: dict[str, str] | None, locale: str) -> str:
    if not texts:
        return ""
    normalized_locale = str(locale or "").strip().lower()
    for candidate in (normalized_locale, "da", "en"):
        value = str(texts.get(candidate, "")).strip()
        if value:
            return value
    return next((str(value).strip() for value in texts.values() if str(value).strip()), "")


def screenshot_asset_source_root(pack: dict[str, object]) -> Path:
    defaults = pack.get("defaults", {})
    return SCREENSHOT_PACK_BASE_ROOT / str(defaults.get("public_asset_dir", "docs/assets/screenshots"))


def screenshot_stage_label(stage: str, *, locale: str) -> str:
    return public_localized_text(SCREENSHOT_STAGE_LABELS.get(stage, {}), locale)


def screenshot_entries(
    pack: dict[str, object],
    placement: str,
    *,
    locale: str,
    asset_prefix: str,
) -> list[dict[str, str]]:
    source_root = screenshot_asset_source_root(pack)
    entries: list[dict[str, str]] = []
    for entry in sorted(pack.get("screenshots", []), key=lambda row: row["display_order"]):
        if placement not in entry.get("placements", []):
            continue
        asset_name = str(entry.get("assets", {}).get("public", "")).strip()
        if not asset_name:
            continue
        asset_path = source_root / asset_name
        if not asset_path.exists():
            continue
        title = public_localized_text(entry.get("title", {}), locale)
        alt = public_localized_text(entry.get("alt", {}), locale)
        caption = public_localized_text(entry.get("captions", {}).get(placement, {}), locale)
        entries.append(
            {
                "id": str(entry["id"]),
                "asset_url": f"{asset_prefix}{asset_name}",
                "title": title,
                "alt": alt,
                "caption": caption,
                "stage": str(entry["stage"]),
                "stage_label": screenshot_stage_label(str(entry["stage"]), locale=locale),
                "route": str(entry.get("source", {}).get("path", "")),
            }
        )
    return entries


def screenshot_payload_entries(pack: dict[str, object], placement: str) -> list[dict[str, object]]:
    source_root = screenshot_asset_source_root(pack)
    payload_entries: list[dict[str, object]] = []
    for entry in sorted(pack.get("screenshots", []), key=lambda row: row["display_order"]):
        if placement not in entry.get("placements", []):
            continue
        asset_name = str(entry.get("assets", {}).get("public", "")).strip()
        if not asset_name:
            continue
        if not (source_root / asset_name).exists():
            continue
        payload_entries.append(
            {
                "id": str(entry["id"]),
                "asset_path": f"assets/screenshots/{asset_name}",
                "title": entry.get("title", {}),
                "alt": entry.get("alt", {}),
                "captions": entry.get("captions", {}).get(placement, {}),
                "stage": str(entry["stage"]),
                "route": str(entry.get("source", {}).get("path", "")),
            }
        )
    return payload_entries


def render_screenshot_cards(entries: list[dict[str, str]], *, card_class: str = "screenshot-card") -> str:
    rendered: list[str] = []
    for entry in entries:
        stage_class = " proof" if entry["stage"] == "public_proof" else ""
        route_html = (
            f'<span class="screenshot-route"><code>{escape(entry["route"])}</code></span>'
            if entry["route"]
            else ""
        )
        rendered.append(
            f"""        <figure class="{card_class}{stage_class}">
          <img src="{escape(entry["asset_url"])}" alt="{escape(entry["alt"])}">
          <figcaption>
            <span class="screenshot-stage">{escape(entry["stage_label"])}</span>
            <strong>{escape(entry["title"])}</strong>
            <p>{escape(entry["caption"])}</p>
            {route_html}
          </figcaption>
        </figure>"""
        )
    return "\n".join(rendered)


def copy_screenshot_assets(pack: dict[str, object]) -> None:
    source_root = screenshot_asset_source_root(pack)
    PIZZA_SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    PROTOCOLS_SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    for entry in pack.get("screenshots", []):
        asset_name = str(entry.get("assets", {}).get("public", "")).strip()
        if not asset_name:
            continue
        source_path = source_root / asset_name
        if not source_path.exists():
            continue
        shutil.copy2(source_path, PIZZA_SCREENSHOT_ROOT / asset_name)
        shutil.copy2(source_path, PROTOCOLS_SCREENSHOT_ROOT / asset_name)

OWNER_EXPLAINERS = [
    {
        "title": "You keep your own menu",
        "body": "Names, prices, categories, and active items stay with the restaurant node instead of living only inside a marketplace listing.",
    },
    {
        "title": "Orders go directly to the shop",
        "body": "The customer can discover through a registry, but the menu and order request go straight to the restaurant node.",
    },
    {
        "title": "Start with pickup and simple payment",
        "body": "The first live shape is intentionally small: controlled pickup ordering, with pay-at-pickup as the simple starting point.",
    },
    {
        "title": "Add tools without giving away ownership",
        "body": "Kitchen screen, print, notifications, stock checks, and later trust or payment modules can be added without turning the registry into the middleman.",
    },
]

MODULE_GROUPS = [
    {
        "id": "customer",
        "title": "What the customer sees",
        "intro": "These are the public surfaces a customer can actually open during discovery and ordering.",
    },
    {
        "id": "operator",
        "title": "What the shop uses behind the counter",
        "intro": "These are the restaurant-side tools for menu control, kitchen flow, stock, printing, and fallback alerts.",
    },
    {
        "id": "payment_trust",
        "title": "Payment and business trust",
        "intro": "This is where payment stays intentionally simple and where identity or business verification can later become reviewable.",
    },
    {
        "id": "internal",
        "title": "Internal tests and future extras",
        "intro": "These modules are not the live restaurant offer today. They are internal test scaffolding or planned next-step pieces.",
    },
]

MODULE_PRESENTATION = {
    "p4p.menu.list": {
        "group": "customer",
        "title": "Simple online menu",
        "audience": "Customer side",
        "summary": "A customer opens a normal menu list and sends the order directly to the restaurant.",
        "owner_value": "You keep the menu basics on your own node instead of relying on a marketplace-owned list.",
        "touches": "Active items, prices, descriptions, and categories.",
        "not_owner": "It does not own payment, stock, or staff workflow.",
    },
    "p4p.menu.photo-map": {
        "group": "customer",
        "title": "Clickable photo-style menu",
        "audience": "Customer side",
        "summary": "A customer taps a paper-menu style surface instead of a plain item list.",
        "owner_value": "Useful if you want the customer surface to feel closer to a printed flyer or visual takeaway menu.",
        "touches": "Active items, prices, descriptions, and categories.",
        "not_owner": "It does not own OCR, payment, stock, or operator workflow.",
    },
    "p4p.customer.status": {
        "group": "customer",
        "title": "Order status page",
        "audience": "Customer side",
        "summary": "A customer can check whether the order was accepted, rejected, or is ready for pickup.",
        "owner_value": "Reduces the need for status phone calls when the restaurant updates the order state.",
        "touches": "Order status, estimated ready time, fulfillment type, and payment mode.",
        "not_owner": "It does not expose operator notes, customer contact data, or the full event log.",
    },
    "p4p.catalog.editor": {
        "group": "operator",
        "title": "Edit menu and prices",
        "audience": "Owner / operator side",
        "summary": "The restaurant can change names, prices, categories, and whether an item is active.",
        "owner_value": "This is the control surface that lets the shop own its own menu instead of waiting for a platform back office.",
        "touches": "Item ids, names, descriptions, prices, categories, and active/inactive state.",
        "not_owner": "It is not a customer-facing menu page.",
    },
    "p4p.catalog.import.ocr": {
        "group": "operator",
        "title": "Scan a paper menu",
        "audience": "Owner / operator side",
        "summary": "The restaurant can scan a paper menu into draft catalog rows before a human review.",
        "owner_value": "Useful when a shop starts from a printed takeaway card instead of rebuilding the whole menu by hand.",
        "touches": "Draft OCR item names, prices, categories, and source lines before catalog save.",
        "not_owner": "It does not become catalog truth by itself and it is not a customer-facing menu.",
    },
    "p4p.kitchen.screen": {
        "group": "operator",
        "title": "Kitchen order queue",
        "audience": "Owner / operator side",
        "summary": "Staff can see incoming orders and move them through kitchen states.",
        "owner_value": "Lets the restaurant turn direct orders into an actual working queue behind the counter.",
        "touches": "Order items, note, customer contact, fulfillment type, and order status.",
        "not_owner": "It is not public discovery and it does not own payment.",
    },
    "p4p.stock.basic": {
        "group": "operator",
        "title": "Final stock check",
        "audience": "Owner / operator side",
        "summary": "The system can do one last local stock check before the next order step continues.",
        "owner_value": "Helps stop the flow before the kitchen commits to something the shop no longer has.",
        "touches": "Order items and local stock state.",
        "not_owner": "It does not replace the menu or the kitchen workflow.",
    },
    "p4p.order.print": {
        "group": "operator",
        "title": "Print to kitchen or POS",
        "audience": "Owner / operator side",
        "summary": "Accepted orders can later be printed or forwarded to a restaurant-owned printer or POS surface.",
        "owner_value": "This is the bridge from a direct online order to a paper ticket or POS flow inside the shop.",
        "touches": "Order items, note, contact, and fulfillment type.",
        "not_owner": "It does not replace payment or public discovery.",
    },
    "p4p.order.print.backup": {
        "group": "operator",
        "title": "Backup printer path",
        "audience": "Counter / hardware side",
        "summary": "If the first printer path fails, the order can be rerouted to a second print target or local spool.",
        "owner_value": "Useful when a shop wants hardware redundancy before trusting direct orders during busy service.",
        "touches": "Order items, note, customer contact, fulfillment type, and backup printer target.",
        "not_owner": "It is fallback routing, not the main customer or kitchen workflow.",
    },
    "p4p.notify.email": {
        "group": "operator",
        "title": "Operator email alert",
        "audience": "Owner / operator side",
        "summary": "The system can send an email when an order needs attention or a printer flow fails.",
        "owner_value": "Useful as a fallback alert so the shop is not blind if another operator-side step fails.",
        "touches": "Order summary and the operator destination address.",
        "not_owner": "It is a fallback notification, not the main order surface.",
    },
    "p4p.notify.sms": {
        "group": "operator",
        "title": "Operator SMS alert",
        "audience": "Owner / operator side",
        "summary": "The system can send a short phone alert when an order or printer problem needs fast attention.",
        "owner_value": "Useful if the test hardware is noisy or partially unattended and the operator still needs a direct phone fallback.",
        "touches": "Order summary and the operator phone destination.",
        "not_owner": "It is a fallback notification, not the main order surface.",
    },
    "p4p.order.alert.basic": {
        "group": "operator",
        "title": "Bell or light alert",
        "audience": "Counter / hardware side",
        "summary": "A local box can ring, beep, or flash when a new order or hardware problem needs attention.",
        "owner_value": "Lets the hardware give an audible or visible cue without turning the alert layer into the actual order queue.",
        "touches": "Order summary, configured alert target, and urgency state.",
        "not_owner": "It does not accept orders, replace the kitchen queue, or settle payment.",
    },
    "p4p.pickup.board.basic": {
        "group": "operator",
        "title": "Ready-for-pickup board",
        "audience": "Counter / pickup side",
        "summary": "A simple local screen can show which direct orders are accepted or ready at the counter.",
        "owner_value": "Gives the shop a cheap customer-facing pickup signal without exposing the full operator dashboard.",
        "touches": "Order summary, public order status, estimated ready time, payment mode, and board target.",
        "not_owner": "It does not take new orders or replace the kitchen queue.",
    },
    "p4p.payment.cash": {
        "group": "payment_trust",
        "title": "Pay at pickup / cash",
        "audience": "Customer + operator side",
        "summary": "The restaurant can keep payment simple by taking cash or direct in-person payment outside the protocol.",
        "owner_value": "This is the easiest first live shape: order online, pay when the customer arrives.",
        "touches": "Order total and fulfillment type only.",
        "not_owner": "It does not hold card data, wallets, settlement, or merchant-of-record responsibility.",
    },
    "p4p.payment.mobilepay": {
        "group": "payment_trust",
        "title": "External MobilePay adapter",
        "audience": "Customer + operator side",
        "summary": "A future external adapter can expose a familiar MobilePay-style pay-at-pickup instruction without making P4P the payment processor.",
        "owner_value": "Lets pilot restaurants say whether an external MobilePay-style adapter is worth adding after cash-first feedback.",
        "touches": "Order total, fulfillment type, and operator payment destination.",
        "not_owner": "It does not make P4P hold funds, process cards, or become merchant of record.",
    },
    "p4p.trust.cvr-basic": {
        "group": "payment_trust",
        "title": "Business identity check",
        "audience": "Trust layer",
        "summary": "A later trust layer can connect a node identity claim to a Danish CVR lookup or trust claim.",
        "owner_value": "This is meant to make a restaurant identity more reviewable later without turning the registry into the authority.",
        "touches": "Declared CVR identifiers and public node identity data.",
        "not_owner": "It is not part of the live ordering loop today.",
    },
    "p4p.payment.godpay-mock": {
        "group": "internal",
        "title": "Fake payment tester",
        "audience": "Internal debug",
        "summary": "An internal mock can randomly accept or reject a test payment during local debugging.",
        "owner_value": "Not something a restaurant should read as a live offer. It exists to test ugly edge cases before any real payment direction exists.",
        "touches": "Order total only.",
        "not_owner": "It is not real money, not real settlement, and not a real provider.",
    },
    "p4p.payment.chaospay-mock": {
        "group": "internal",
        "title": "Ugly-case payment tester",
        "audience": "Internal debug",
        "summary": "An internal mock for timeouts, wrong amounts, duplicate callbacks, and other payment chaos scenarios.",
        "owner_value": "This exists to break things safely in local testing before any broader payment layer is discussed.",
        "touches": "Order total and order state.",
        "not_owner": "It is not real money, not real settlement, and not a live customer payment option.",
    },
}

MODULE_READ_NEXT = {
    "p4p.menu.list": [
        {
            "title": "See what happens after the order",
            "body": "After the customer sends the order, the next useful public page is the status screen.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "Then look behind the counter",
            "body": "If you want the shop-side counterpart, open the menu-control page the restaurant uses.",
            "kind": "module",
            "target": "p4p.catalog.editor",
        },
        {
            "title": "Keep the payment edge small",
            "body": "The first live payment shape stays intentionally simple: order online, pay at pickup.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.menu.photo-map": [
        {
            "title": "See the plain menu baseline",
            "body": "This visual menu is easier to understand when you compare it to the simpler list version.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the customer follow-up",
            "body": "After the order is sent, the next customer-facing step is the status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "Keep the boundary in view",
            "body": "The visual menu still sits inside the same small payment boundary as the rest of the proof.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.customer.status": [
        {
            "title": "Start at the order surface first",
            "body": "If you landed here early, read the menu module first so the order-status page makes sense in context.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then look at the kitchen side",
            "body": "The status page only changes when the restaurant updates the order behind the counter.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Keep payment simple",
            "body": "The first live shape still avoids deeper payment handling and keeps the edge small.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.catalog.editor": [
        {
            "title": "See the public result",
            "body": "After the restaurant edits the menu, the simplest customer-facing result is the plain online menu.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the paper-menu helper",
            "body": "If the shop starts from a printed flyer, the OCR helper is the separate optional import surface beside the editor.",
            "kind": "module",
            "target": "p4p.catalog.import.ocr",
        },
        {
            "title": "See who currently provides this stack",
            "body": "The provider page explains the shared reference layer behind the current public tools.",
            "kind": "provider",
        },
    ],
    "p4p.catalog.import.ocr": [
        {
            "title": "See the catalog truth surface next",
            "body": "The OCR helper only creates drafts. The real local source of truth still lives in the catalog editor.",
            "kind": "module",
            "target": "p4p.catalog.editor",
        },
        {
            "title": "Then see the public result",
            "body": "After the operator reviews and saves imported items, the simplest customer-facing result is the plain online menu.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "See who currently provides this stack",
            "body": "The provider page explains the shared reference layer behind the current public tools.",
            "kind": "provider",
        },
    ],
    "p4p.kitchen.screen": [
        {
            "title": "See what the customer opens first",
            "body": "The kitchen queue is easier to read once you start from the direct customer menu surface.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the customer follow-up",
            "body": "The customer-side mirror of kitchen state changes is the order-status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "Keep the payment edge small",
            "body": "Even when the kitchen flow exists, the first live payment shape is still pay at pickup.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.stock.basic": [
        {
            "title": "See the queue this protects",
            "body": "The stock check only matters because the restaurant is already running an active order queue.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "See the menu control beside it",
            "body": "Stock checks make more sense when you read them next to the menu-control surface.",
            "kind": "module",
            "target": "p4p.catalog.editor",
        },
        {
            "title": "Keep the live boundary small",
            "body": "This extra operator check still sits inside a deliberately small first live payment edge.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.order.print": [
        {
            "title": "See the main kitchen flow first",
            "body": "Printing is a support surface. The main operator story still starts with the kitchen queue.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Then see the fallback alert",
            "body": "If a print path fails or stalls, the operator alert module is the next useful fallback.",
            "kind": "module",
            "target": "p4p.notify.email",
        },
        {
            "title": "See who currently provides the tools",
            "body": "The provider page explains the current shared source behind the operator-side extras.",
            "kind": "provider",
        },
    ],
    "p4p.order.print.backup": [
        {
            "title": "Start with the main print lane",
            "body": "The backup path only makes sense after you read the primary printer/POS lane.",
            "kind": "module",
            "target": "p4p.order.print",
        },
        {
            "title": "Then see the queue it protects",
            "body": "Fallback printing exists because the kitchen queue still needs a dependable handoff during service.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Keep the human fallback nearby",
            "body": "If both print paths fail, the next useful backup is a direct operator notification path.",
            "kind": "module",
            "target": "p4p.notify.sms",
        },
    ],
    "p4p.notify.email": [
        {
            "title": "See the main kitchen flow first",
            "body": "This email alert makes more sense when you first read the ordinary kitchen queue it supports.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Then see the print fallback beside it",
            "body": "Print and alert modules live in the same operator-support layer, not in the public customer loop.",
            "kind": "module",
            "target": "p4p.order.print",
        },
        {
            "title": "See who currently provides the tools",
            "body": "The provider page shows the current shared reference layer behind these support modules.",
            "kind": "provider",
        },
    ],
    "p4p.notify.sms": [
        {
            "title": "See the email fallback beside it",
            "body": "SMS is easiest to judge when you compare it to the simpler email fallback lane already in the stack.",
            "kind": "module",
            "target": "p4p.notify.email",
        },
        {
            "title": "Then see the queue it protects",
            "body": "Phone fallback only matters because the restaurant still has a real operator queue behind the alert.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "See who currently provides the tools",
            "body": "The provider page keeps the current pilot-feedback modules inside one clearly labeled reference stack.",
            "kind": "provider",
        },
    ],
    "p4p.order.alert.basic": [
        {
            "title": "See the main kitchen flow first",
            "body": "A bell or light alert only helps because there is still a real kitchen queue behind it.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Then compare it to the print lane",
            "body": "This alert lane becomes more concrete when you read it next to the primary print/POS handoff.",
            "kind": "module",
            "target": "p4p.order.print",
        },
        {
            "title": "Keep the phone fallback nearby",
            "body": "If a local bell or light path disappears, the next useful fallback is a phone notification lane.",
            "kind": "module",
            "target": "p4p.notify.sms",
        },
    ],
    "p4p.pickup.board.basic": [
        {
            "title": "Start with the customer order surface",
            "body": "The pickup board only matters after the customer has first seen the direct menu and submitted an order.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the status source behind it",
            "body": "The local pickup board is easier to judge when you compare it to the public order-status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "See the kitchen queue behind the board",
            "body": "The board only stays truthful if the operator queue is still the thing driving state changes.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
    ],
    "p4p.payment.cash": [
        {
            "title": "Start from the customer order surface",
            "body": "The payment edge only matters after the customer has first seen the direct menu.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the customer follow-up",
            "body": "After ordering and paying at pickup, the next customer-facing surface is the status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page keeps the current ownership and proof boundary explicit.",
            "kind": "provider",
        },
    ],
    "p4p.payment.mobilepay": [
        {
            "title": "Start from the cash baseline",
            "body": "This only makes sense after you read the simpler cash-first lane that defines the current live boundary.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "Then return to the customer order surface",
            "body": "The payment adapter still sits after the direct menu flow, not before it.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Keep the provider boundary explicit",
            "body": "The provider page keeps this as a planned adapter candidate, not a claim that P4P is processing money.",
            "kind": "provider",
        },
    ],
    "p4p.trust.cvr-basic": [
        {
            "title": "Keep the live order flow first",
            "body": "This trust direction sits after the basic ordering flow, not before it.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the simple live payment edge",
            "body": "The current real-world payment boundary is still much smaller than the later trust direction.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page explains what the current shared stack is and what it does not claim yet.",
            "kind": "provider",
        },
    ],
    "p4p.payment.godpay-mock": [
        {
            "title": "See the real live payment baseline",
            "body": "This mock only makes sense after you read the simple pay-at-pickup module that represents the current live edge.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page explains why this remains internal test scaffolding, not a public money claim.",
            "kind": "provider",
        },
        {
            "title": "Back to the full module catalog",
            "body": "If you want the broader shape again, return to the grouped module stack.",
            "kind": "catalog",
        },
    ],
    "p4p.payment.chaospay-mock": [
        {
            "title": "See the real live payment baseline",
            "body": "This ugly-case tester only makes sense after you read the small live payment shape it is meant to protect.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page explains why this remains internal failure testing, not a public payment promise.",
            "kind": "provider",
        },
        {
            "title": "Back to the full module catalog",
            "body": "If you want the broader module layout again, return to the grouped stack.",
            "kind": "catalog",
        },
    ],
}

PROVIDER_PRESENTATION = {
    "p4p.reference": {
        "summary": "Right now the public Pizza4People tools come from one shared reference provider inside the repo.",
        "owner_value": "The current menu, order, and operator pages come from one shared reference stack, not from a big live marketplace of outside vendors yet.",
        "what_it_is": "A shared reference provider for the first customer pages, operator tools, simple pay-at-pickup flow, and local test modules in the current proof.",
        "what_it_is_not": "Not a live certification authority, not a marketplace full of competing vendors, and not proof that every declared module is production-ready.",
        "current_shape": "One shared reference stack behind the current public site.",
        "not_yet": "No broad provider marketplace yet. No certification layer yet.",
    }
}

PRESS_MODULE_SPOTLIGHTS = [
    {
        "module_id": "p4p.catalog.editor",
        "title": {
            "dk": "Butikken styrer menu og priser",
            "en": "The shop keeps menu and prices",
        },
        "body": {
            "dk": "Butikken kan selv ændre varer, priser og hvad der er aktivt, i stedet for at vente på et platform-backoffice.",
            "en": "The shop can change items, prices, and what is active instead of waiting for a platform back office.",
        },
    },
    {
        "module_id": "p4p.menu.list",
        "title": {
            "dk": "Kunden kan bestille direkte",
            "en": "Customers can order direct",
        },
        "body": {
            "dk": "Kunden åbner en enkel menu og sender ordren direkte til butikken i stedet for gennem et marketplace-flow.",
            "en": "The customer opens a simple menu and sends the order straight to the shop instead of through a marketplace flow.",
        },
    },
    {
        "module_id": "p4p.customer.status",
        "title": {
            "dk": "Kunden kan selv se status",
            "en": "Customers can check order status",
        },
        "body": {
            "dk": "Når butikken opdaterer ordren, kan kunden selv se om den er accepteret eller klar, i stedet for at ringe.",
            "en": "When the shop updates the order, the customer can see whether it is accepted or ready instead of having to call.",
        },
    },
    {
        "module_id": "p4p.payment.cash",
        "title": {
            "dk": "Start med betaling ved afhentning",
            "en": "Start with pay at pickup",
        },
        "body": {
            "dk": "Den første live-model er bevidst enkel: bestil online, betal når kunden møder op.",
            "en": "The first live shape is deliberately simple: order online, pay when the customer arrives.",
        },
    },
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, str]) -> str:
    rendered = load_text(TEMPLATE_ROOT / name)
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", rendered)))
    if unresolved:
        raise ValueError(f"Unresolved template placeholders in {name}: {', '.join(unresolved)}")
    return rendered


def load_site_data() -> dict:
    return load_json(SITE_DATA_PATH)


def load_modules() -> list[dict]:
    modules: list[dict] = []
    for manifest_path in sorted(MODULES_ROOT.glob("*/module.json")):
        payload = load_json(manifest_path)
        public_catalog = payload.get("public_catalog", {})
        module_id = payload["module_id"]
        provider_id = payload["provider_id"]
        modules.append(
            {
                "module_id": module_id,
                "module_class": payload["module_class"],
                "lane": payload["lane"],
                "visibility": payload["visibility"],
                "provider_id": provider_id,
                "description": payload["description"],
                "function": public_catalog.get("function", payload["description"]),
                "data_access": public_catalog.get(
                    "data_access_summary",
                    ", ".join(payload.get("data_access", [])) or "Not declared yet.",
                ),
                "trust_status": public_catalog.get("trust_status", payload["status"]),
                "readiness": public_catalog.get("readiness", payload["status"]),
                "operator_status": public_catalog.get("operator_status", "not enabled"),
                "module_site_path": f"modules/{module_id}/",
                "provider_site_path": f"providers/{provider_id}/",
                "module_doc_url": f"https://github.com/DennisHedegreen/p4p/blob/main/docs/modules/{module_id}.md",
                "module_manifest_url": f"https://github.com/DennisHedegreen/p4p/blob/main/modules/{module_id}/module.json",
                "provider_doc_url": f"https://github.com/DennisHedegreen/p4p/blob/main/docs/providers/{provider_id}.md",
            }
        )
    return modules


def load_providers(modules: list[dict]) -> list[dict]:
    modules_by_provider: dict[str, list[dict]] = {}
    for module in modules:
        modules_by_provider.setdefault(module["provider_id"], []).append(module)

    providers: list[dict] = []
    for provider_id, manifest in sorted(load_reference_provider_catalog().items()):
        provider_modules = sorted(modules_by_provider.get(provider_id, []), key=lambda entry: entry["module_id"])
        manifest_relpath = manifest.source_path.relative_to(P4P_ROOT).as_posix()
        providers.append(
            {
                "provider_id": provider_id,
                "name": manifest.name,
                "description": manifest.description,
                "website": manifest.website,
                "status": manifest.status,
                "supported_lanes": list(manifest.supported_lanes),
                "module_ids": [entry["module_id"] for entry in provider_modules],
                "module_count": len(provider_modules),
                "provider_site_path": f"providers/{provider_id}/",
                "provider_doc_url": f"https://github.com/DennisHedegreen/p4p/blob/main/docs/providers/{provider_id}.md",
                "provider_manifest_url": f"https://github.com/DennisHedegreen/p4p/blob/main/{manifest_relpath}",
            }
        )
    return providers


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def module_page_path(module_id: str) -> Path:
    return PUBLIC_ROOT / "modules" / module_id / "index.html"


def provider_page_path(provider_id: str) -> Path:
    return PUBLIC_ROOT / "providers" / provider_id / "index.html"


def module_catalog_payload(site_data: dict, modules: list[dict]) -> dict:
    site_url = site_data["canonical_urls"]["site"]
    return {
        "catalog_name": "Pizza4People Module Catalog",
        "catalog_status": "generated from module manifests",
        "generated_at": site_data["generated_at"],
        "modules": [
            {
                "module_id": entry["module_id"],
                "provider_id": entry["provider_id"],
                "function": entry["function"],
                "data_access": entry["data_access"],
                "trust_status": entry["trust_status"],
                "readiness": entry["readiness"],
                "operator_status": entry["operator_status"],
                "module_page_url": f'{site_url}{entry["module_site_path"]}',
                "provider_page_url": f'{site_url}{entry["provider_site_path"]}',
                "module_doc_url": entry["module_doc_url"],
                "module_manifest_url": entry["module_manifest_url"],
                "provider_doc_url": entry["provider_doc_url"],
            }
            for entry in modules
        ],
    }


def provider_catalog_payload(site_data: dict, providers: list[dict]) -> dict:
    site_url = site_data["canonical_urls"]["site"]
    return {
        "catalog_name": "Pizza4People Provider Catalog",
        "catalog_status": "generated from provider manifests",
        "generated_at": site_data["generated_at"],
        "providers": [
            {
                "provider_id": entry["provider_id"],
                "name": entry["name"],
                "description": entry["description"],
                "website": entry["website"],
                "status": entry["status"],
                "supported_lanes": entry["supported_lanes"],
                "module_count": entry["module_count"],
                "module_ids": entry["module_ids"],
                "provider_page_url": f'{site_url}{entry["provider_site_path"]}',
                "provider_doc_url": entry["provider_doc_url"],
                "provider_manifest_url": entry["provider_manifest_url"],
            }
            for entry in providers
        ],
    }


PROTOCOLS_MODULE_UI = {
    "locale_label": {
        "da": "Sprog",
        "sv": "Språk",
        "tr": "Dil",
        "ar": "اللغة",
        "ku": "Ziman",
    },
    "modules_title": {
        "da": "Moduler til lokale butikker og direkte kontakt",
        "sv": "Moduler för lokala butiker och direkt kontakt",
        "tr": "Yerel dükkânlar ve doğrudan ilişki için modüller",
        "ar": "وحدات للمتاجر المحلية والعلاقة المباشرة",
        "ku": "Modul ji bo dikkanên herêmî û têkiliya rasterast",
    },
    "modules_lede": {
        "da": "Læs modul-familierne menneskeligt her. Brug operatoren lokalt til at vælge hvad din node faktisk skal køre.",
        "sv": "Läs modulfamiljerna mänskligt här. Använd operatören lokalt för att välja vad din nod faktiskt ska köra.",
        "tr": "Modül ailelerini burada insanvenligt okuyun. Düğümünüzün gerçekten ne çalıştıracağını seçmek için yerel operatörü kullanın.",
        "ar": "اقرأ عائلات الوحدات هنا بشكل إنساني. استخدم واجهة المشغّل محلياً لتختار ما الذي يجب أن تشغله عقدتك فعلاً.",
        "ku": "Li vir malbatên modulê bi awayekî merivane bixwîne. Operatorê herêmî bi kar bîne da ku tu hilbijêrî nodeya te bi rastî çi bixebitîne.",
    },
    "shop_title": {
        "da": "Shop er første familie",
        "sv": "Shop är den första familjen",
        "tr": "Shop ilk aile",
        "ar": "shop هي العائلة الأولى",
        "ku": "shop malbata yekem e",
    },
    "shop_lede": {
        "da": "Start med behov som menu, kundesider, betaling og lokal hardware i stedet for at starte med pizza som kategori.",
        "sv": "Börja med behov som meny, kundsidor, betalning och lokal hårdvara i stället för att börja med pizza som kategori.",
        "tr": "Kategori olarak pizzayla başlamak yerine menü, müşteri yüzleri, ödeme ve yerel donanım gibi ihtiyaçlarla başlayın.",
        "ar": "ابدأ بالاحتياجات مثل القائمة وواجهات الزبون والدفع والعتاد المحلي بدلاً من البدء بالبيتزا كفئة.",
        "ku": "Li şûna ku bi pizza wek kategori dest pê bikî, bi hewcedariyên wek menu, rûyên xerîdar, dravdan û hardwareya herêmî dest pê bike.",
    },
    "recommended": {
        "da": "Anbefalet baseline",
        "sv": "Rekommenderad baslinje",
        "tr": "Önerilen başlangıç seti",
        "ar": "الحد الأدنى الموصى به",
        "ku": "Bingehê pêşniyarkirî",
    },
    "browse": {
        "da": "Gennemse grupper",
        "sv": "Bläddra bland grupper",
        "tr": "Gruplara göz at",
        "ar": "تصفّح المجموعات",
        "ku": "Li koman bigere",
    },
    "open_proof": {
        "da": "Åbn proof-side",
        "sv": "Öppna proofsida",
        "tr": "Proof sayfasını aç",
        "ar": "افتح صفحة الإثبات",
        "ku": "Rûpela proof veke",
    },
    "open_doc": {
        "da": "Åbn modul-doc",
        "sv": "Öppna modul-doc",
        "tr": "Modül dokümanını aç",
        "ar": "افتح توثيق الوحدة",
        "ku": "Belgeya modulê veke",
    },
    "open_manifest": {
        "da": "Åbn manifest",
        "sv": "Öppna manifest",
        "tr": "Manifesti aç",
        "ar": "افتح المانيفست",
        "ku": "Manifestê veke",
    },
    "open_shop": {
        "da": "Åbn shop-familien",
        "sv": "Öppna shop-familjen",
        "tr": "Shop ailesini aç",
        "ar": "افتح عائلة shop",
        "ku": "Malbata shop veke",
    },
    "screenshots": {
        "da": "Lokale flader",
        "sv": "Lokala ytor",
        "tr": "Yerel yüzeyler",
        "ar": "الأسطح المحلية",
        "ku": "Rûberên herêmî",
    },
    "screenshots_catalog_lede": {
        "da": "Det offentlige modul-katalog ender på en lokal node, hvor butikken kan læse og styre modulerne selv.",
        "sv": "Den offentliga modulkatalogen landar på en lokal nod där butiken kan läsa och styra modulerna själv.",
        "tr": "Açık modül kataloğu, dükkânın modülleri yerel düğümde okuyup yönetebildiği yere bağlanır.",
        "ar": "ينتهي كتالوج الوحدات العام على عقدة محلية حيث يمكن للمتجر قراءة الوحدات والتحكم بها بنفسه.",
        "ku": "Kataloga giştî ya modulê di nodeyek herêmî de bi dawî dibe ku firotgeh dikare modulan bixwîne û bi xwe bi rê ve bibe.",
    },
    "screenshots_shop_lede": {
        "da": "Shop-familien bliver først rigtig, når offentlig forklaring, lokal discover, import og modulvalg hænger sammen.",
        "sv": "Shop-familjen blir först verklig när offentlig förklaring, lokal discovery, import och modulval hänger ihop.",
        "tr": "Shop ailesi ancak açık açıklama, yerel keşif, içe aktarma ve modül seçimi birlikte çalışınca gerçek olur.",
        "ar": "تصبح عائلة shop حقيقية حين تتماسك الشروح العامة مع الاكتشاف المحلي والاستيراد واختيار الوحدات.",
        "ku": "Malbata shop tenê dema ku ravekirina giştî, discover ya herêmî, import û hilbijartina modulê bi hev re bixebitin rast dibe.",
    },
    "stage_next_gate": {
        "da": "Næste gate / pilot-node",
        "sv": "Nästa steg / pilot-nod",
        "tr": "Sonraki kapı / pilot düğüm",
        "ar": "البوابة التالية / عقدة تجريبية",
        "ku": "Deriyê din / nodeya pilotê",
    },
    "stage_public_proof": {
        "da": "Offentligt proof",
        "sv": "Offentligt bevis",
        "tr": "Kamusal kanıt",
        "ar": "إثبات عام",
        "ku": "Proofa giştî",
    },
}


def protocols_text(key: str, locale: str) -> str:
    return localized_text(PROTOCOLS_MODULE_UI.get(key), locale)


def protocols_modules_shell(
    *,
    page_kind: str,
    page_title: str,
    base_path: str,
    payload: dict[str, object],
) -> str:
    catalog_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(page_title)}</title>
  <link rel="stylesheet" href="{escape(base_path)}style.css">
  <style>
    .modules-shell {{
      width: min(1120px, calc(100% - 2rem));
      margin: 0 auto;
      padding-bottom: 4rem;
    }}
    .modules-hero, .modules-section, .module-grid, .module-card, .module-meta, .module-actions, .locale-row {{
      display: grid;
      gap: 0.9rem;
    }}
    .modules-hero {{
      padding: 1.5rem 0 2rem;
    }}
    .locale-row {{
      align-items: end;
      max-width: 14rem;
    }}
    .locale-row select {{
      min-height: 2.7rem;
      border-radius: 0.8rem;
      border: 1px solid rgba(219, 232, 216, 0.24);
      background: rgba(18, 26, 24, 0.9);
      color: var(--text);
      padding: 0 0.8rem;
      font: inherit;
    }}
    .modules-section {{
      margin-top: 1.5rem;
      padding: 1.15rem;
      border: 1px solid var(--line);
      border-radius: 1rem;
      background: rgba(18, 26, 24, 0.78);
    }}
    .module-grid {{
      grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr));
    }}
    .module-card {{
      padding: 1rem;
      border: 1px solid var(--line);
      border-radius: 0.9rem;
      background: rgba(23, 35, 31, 0.85);
    }}
    .module-meta {{
      grid-template-columns: repeat(auto-fit, minmax(7rem, auto));
    }}
    .module-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 1.8rem;
      padding: 0 0.65rem;
      border-radius: 999px;
      background: rgba(123, 224, 196, 0.12);
      color: var(--mint);
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .module-actions {{
      grid-template-columns: repeat(auto-fit, minmax(10rem, auto));
    }}
    .module-actions a {{
      display: inline-flex;
      justify-content: center;
      align-items: center;
      min-height: 2.45rem;
      padding: 0 0.9rem;
      border: 1px solid rgba(123, 224, 196, 0.32);
      border-radius: 999px;
      text-decoration: none;
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }}
    .module-actions a:hover {{
      border-color: rgba(123, 224, 196, 0.55);
      background: rgba(123, 224, 196, 0.06);
    }}
    .screenshot-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
      gap: 1rem;
    }}
    .screenshot-card {{
      display: grid;
      gap: 0.75rem;
      padding: 0.9rem;
      border: 1px solid var(--line);
      border-radius: 0.9rem;
      background: rgba(23, 35, 31, 0.85);
    }}
    .screenshot-card img {{
      display: block;
      width: 100%;
      height: auto;
      border-radius: 0.85rem;
      border: 1px solid rgba(219, 232, 216, 0.14);
    }}
    .screenshot-card figcaption {{
      display: grid;
      gap: 0.45rem;
      margin: 0;
    }}
    .screenshot-stage {{
      display: inline-flex;
      width: fit-content;
      min-height: 1.7rem;
      align-items: center;
      padding: 0 0.7rem;
      border-radius: 999px;
      background: rgba(123, 224, 196, 0.12);
      color: var(--mint);
      font-family: var(--mono);
      font-size: 0.7rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }}
    .screenshot-stage.proof {{
      background: rgba(233, 189, 99, 0.16);
      color: var(--gold);
    }}
    .screenshot-route {{
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.72rem;
    }}
    .modules-subnav {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.8rem;
    }}
    .modules-subnav a {{
      display: inline-flex;
      align-items: center;
      min-height: 2.3rem;
      padding: 0 0.8rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      text-decoration: none;
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <a class="brand" href="{escape(base_path)}" aria-label="Protocols4People home">
      <span class="brand-mark">P4P</span>
      <span class="brand-copy">Protocols4People</span>
    </a>
    <nav class="top-nav" aria-label="Primary navigation">
      <a href="{escape(base_path)}">Home</a>
      <a href="{escape(base_path)}modules/">Modules</a>
      <a href="{escape(base_path)}modules/shop/">Shop</a>
      <a href="https://pizza4people.com/" rel="noopener noreferrer">Pizza4People</a>
    </nav>
  </header>
  <main id="main" class="modules-shell" data-page-kind="{escape(page_kind)}">
    <section class="modules-hero">
      <p class="section-kicker" id="hero-kicker"></p>
      <h1 id="hero-title"></h1>
      <p class="hero-lede" id="hero-lede"></p>
      <div class="modules-subnav">
        <a id="hero-shop-link" href="{escape(base_path)}modules/shop/"></a>
        <a href="https://pizza4people.com/modules/" rel="noopener noreferrer">Pizza4People proof</a>
        <a href="https://github.com/DennisHedegreen/p4p" rel="noopener noreferrer">Public GitHub</a>
      </div>
      <label class="locale-row">
        <span id="locale-label"></span>
        <select id="locale-switcher"></select>
      </label>
    </section>

    <section class="modules-section" aria-labelledby="recommended-title">
      <p class="section-kicker" id="recommended-kicker"></p>
      <h2 id="recommended-title"></h2>
      <div id="recommended-grid" class="module-grid"></div>
    </section>

    <section class="modules-section" aria-labelledby="browse-title">
      <p class="section-kicker" id="browse-kicker"></p>
      <h2 id="browse-title"></h2>
      <div id="category-sections"></div>
    </section>

    <section class="modules-section" id="screenshots-section" aria-labelledby="screens-title" hidden>
      <p class="section-kicker" id="screens-kicker"></p>
      <h2 id="screens-title"></h2>
      <p class="hero-lede" id="screens-lede"></p>
      <div id="screens-grid" class="screenshot-grid"></div>
    </section>
  </main>
  <script id="module-catalog-payload" type="application/json">{catalog_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById("module-catalog-payload").textContent);
    const ui = {json.dumps(PROTOCOLS_MODULE_UI, ensure_ascii=False)};
    const pageKind = document.querySelector("main").dataset.pageKind;
    const basePath = {json.dumps(base_path)};
    const localeSwitcher = document.getElementById("locale-switcher");

    function normalizeLocale(locale) {{
      const supported = new Set(payload.supported_locales || []);
      return supported.has(locale) ? locale : (payload.default_locale || "da");
    }}

    function localizedText(map, locale) {{
      if (!map) return "";
      return map[locale] || map[payload.default_locale] || map.en || Object.values(map)[0] || "";
    }}

    function uiText(key, locale) {{
      return localizedText(ui[key], locale);
    }}

    function currentLocale() {{
      const params = new URLSearchParams(window.location.search);
      return normalizeLocale(params.get("lang"));
    }}

    function setLocaleParam(locale) {{
      const params = new URLSearchParams(window.location.search);
      params.set("lang", locale);
      const url = `${{window.location.pathname}}?${{params.toString()}}`;
      window.history.replaceState({{}}, "", url);
    }}

    function renderModuleCard(entry, locale) {{
      return `
        <article class="module-card">
          <div>
            <h3>${{entry.title[locale] || entry.title.da || entry.module_id}}</h3>
            <p>${{entry.summary[locale] || entry.summary.da || ""}}</p>
          </div>
          <div class="module-meta">
            <span class="module-badge">${{localizedText(entry.category.title, locale)}}</span>
            <span class="module-badge">${{entry.readiness}}</span>
            <span class="module-badge">${{entry.visibility}}</span>
          </div>
          <div class="module-actions">
            <a href="${{entry.proof_page_url}}" target="_blank" rel="noopener noreferrer">${{uiText("open_proof", locale)}}</a>
            <a href="${{entry.module_doc_url}}" target="_blank" rel="noopener noreferrer">${{uiText("open_doc", locale)}}</a>
            <a href="${{entry.module_manifest_url}}" target="_blank" rel="noopener noreferrer">${{uiText("open_manifest", locale)}}</a>
          </div>
        </article>
      `;
    }}

    function renderScreenshotCard(entry, locale) {{
      const stageKey = entry.stage === "public_proof" ? "stage_public_proof" : "stage_next_gate";
      const stageClass = entry.stage === "public_proof" ? "proof" : "";
      return `
        <figure class="screenshot-card">
          <img src="${{basePath}}${{entry.asset_path}}" alt="${{localizedText(entry.alt, locale)}}" loading="lazy">
          <figcaption>
            <span class="screenshot-stage ${{stageClass}}">${{uiText(stageKey, locale)}}</span>
            <strong>${{localizedText(entry.title, locale)}}</strong>
            <p>${{localizedText(entry.captions, locale)}}</p>
            <span class="screenshot-route"><code>${{entry.route}}</code></span>
          </figcaption>
        </figure>
      `;
    }}

    function render(locale) {{
      const family = payload.families[0];
      const categories = payload.categories;
      const modules = payload.modules;
      const screenshotSections = payload.screenshot_sections || {{}};
      document.documentElement.lang = locale;
      document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
      document.title = pageKind === "shop" ? uiText("shop_title", locale) : uiText("modules_title", locale);

      document.getElementById("hero-kicker").textContent = pageKind === "shop" ? localizedText(family.title, locale) : uiText("browse", locale);
      document.getElementById("hero-title").textContent = pageKind === "shop" ? uiText("shop_title", locale) : uiText("modules_title", locale);
      document.getElementById("hero-lede").textContent = pageKind === "shop" ? uiText("shop_lede", locale) : uiText("modules_lede", locale);
      document.getElementById("hero-shop-link").textContent = uiText("open_shop", locale);
      document.getElementById("locale-label").textContent = uiText("locale_label", locale);
      document.getElementById("recommended-kicker").textContent = localizedText(family.title, locale);
      document.getElementById("recommended-title").textContent = uiText("recommended", locale);
      document.getElementById("browse-kicker").textContent = localizedText(family.title, locale);
      document.getElementById("browse-title").textContent = uiText("browse", locale);

      localeSwitcher.innerHTML = "";
      (payload.locales || []).forEach((choice) => {{
        const option = document.createElement("option");
        option.value = choice.id;
        option.textContent = choice.native_label || choice.label || choice.id;
        localeSwitcher.appendChild(option);
      }});
      localeSwitcher.value = locale;

      const recommendedIds = new Set(family.recommended_module_ids || []);
      const recommended = modules.filter((entry) => recommendedIds.has(entry.module_id));
      document.getElementById("recommended-grid").innerHTML = recommended.map((entry) => renderModuleCard(entry, locale)).join("");

      document.getElementById("category-sections").innerHTML = categories.map((category) => {{
        const categoryModules = modules.filter((entry) => entry.category_id === category.id);
        return `
          <section class="modules-section">
            <h3>${{localizedText(category.title, locale)}}</h3>
            <p>${{localizedText(category.summary, locale)}}</p>
            <div class="module-grid">
              ${{categoryModules.map((entry) => renderModuleCard(entry, locale)).join("")}}
            </div>
          </section>
        `;
      }}).join("");

      const screenshots = pageKind === "shop" ? (screenshotSections.protocols_shop || []) : (screenshotSections.protocols_catalog || []);
      const screenshotsSection = document.getElementById("screenshots-section");
      if (screenshots.length) {{
        screenshotsSection.hidden = false;
        document.getElementById("screens-kicker").textContent = uiText("screenshots", locale);
        document.getElementById("screens-title").textContent = pageKind === "shop" ? uiText("shop_title", locale) : uiText("modules_title", locale);
        document.getElementById("screens-lede").textContent = pageKind === "shop" ? uiText("screenshots_shop_lede", locale) : uiText("screenshots_catalog_lede", locale);
        document.getElementById("screens-grid").innerHTML = screenshots.map((entry) => renderScreenshotCard(entry, locale)).join("");
      }} else {{
        screenshotsSection.hidden = true;
        document.getElementById("screens-grid").innerHTML = "";
      }}
    }}

    localeSwitcher.addEventListener("change", (event) => {{
      const locale = normalizeLocale(event.target.value);
      setLocaleParam(locale);
      render(locale);
    }});

    render(currentLocale());
  </script>
</body>
</html>"""


def render_press_facts(facts: list[dict], urls: dict) -> str:
    items = []
    for fact in facts:
        body = escape(fact["body"])
        body = body.replace("Danish", '<a href="press-kit/">Danish</a>')
        body = body.replace("English", '<a href="press-kit/en.html">English</a>')
        body = body.replace("proof site", f'<a href="{escape(urls["site"])}">proof site</a>')
        body = body.replace("public repo", f'<a href="{escape(urls["repo"])}">public repo</a>')
        body = body.replace("public main repo", f'<a href="{escape(urls["repo"])}">public main repo</a>')
        body = body.replace("repo README", f'<a href="{escape(urls["repo_readme"])}">repo README</a>')
        body = body.replace("proof note", f'<a href="{escape(urls["repo_proof"])}">proof note</a>')
        body = body.replace("SPEC.md", f'<a href="{escape(urls["repo_spec"])}">SPEC.md</a>')
        body = body.replace(
            "release notes",
            f'<a href="{escape(urls["repo_release_notes"])}">release notes</a>',
        )
        items.append(
            f"""        <article>
          <h3>{escape(fact["title"])}</h3>
          <p>{body}</p>
        </article>"""
        )
    return "\n".join(items)


def render_plain_cards(items: list[dict]) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            f"""        <article class="plain-card">
          <span class="plain-number">{index}</span>
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_owner_cards() -> str:
    cards = []
    for item in OWNER_EXPLAINERS:
        cards.append(
            f"""        <article class="owner-card">
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_proof_steps(items: list[dict]) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            f"""        <article class="proof-step">
          <span class="step-number">{index:02d}</span>
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_list_items(items: list[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    inner = "\n".join(f"          <li>{escape(item)}</li>" for item in items)
    return f"<{tag}>\n{inner}\n        </{tag}>"


def render_modules(modules: list[dict]) -> str:
    cards = []
    for entry in modules:
        live_class = " module-live" if entry["readiness"] in {"test", "live"} else ""
        cards.append(
            f"""        <article class="module-card{live_class}">
          <div class="module-head">
            <h3>{escape(entry["module_id"])}</h3>
            <span>{escape(entry["readiness"])}</span>
          </div>
          <p>{escape(entry["function"])}</p>
          <dl>
            <div><dt>Provider</dt><dd><a href="{escape(entry["provider_doc_url"])}" rel="noopener noreferrer">{escape(entry["provider_id"])}</a></dd></div>
            <div><dt>Data</dt><dd>{escape(entry["data_access"])}</dd></div>
            <div><dt>Trust</dt><dd>{escape(entry["trust_status"])}</dd></div>
            <div><dt>Operator</dt><dd>{escape(entry["operator_status"])}</dd></div>
          </dl>
          <p class="module-links"><a href="{escape(entry["module_doc_url"])}" rel="noopener noreferrer">Read module page</a> <span>/</span> <a href="{escape(entry["provider_doc_url"])}" rel="noopener noreferrer">Read provider page</a> <span>/</span> <a href="{escape(entry["module_manifest_url"])}" rel="noopener noreferrer">Open manifest</a></p>
        </article>"""
        )
    return "\n".join(cards)


def module_state(entry: dict) -> tuple[str, str]:
    module_id = entry["module_id"]
    if "mock" in module_id:
        return ("Internal test only", "state-internal")
    if entry["lane"] == "trust":
        return ("Trust direction", "state-planned")
    if entry["readiness"] == "planned":
        return ("Planned next", "state-planned")
    if entry["visibility"] == "public":
        return ("Shown in proof", "state-proof")
    if entry["visibility"] == "operator_only":
        return ("Operator-side prototype", "state-operator")
    return ("Prototype", "state-proof")


def module_presentation(entry: dict) -> dict[str, str]:
    fallback = {
        "group": "internal",
        "title": entry["module_id"],
        "audience": "Reference layer",
        "summary": entry["function"],
        "owner_value": entry["description"],
        "touches": entry["data_access"],
        "not_owner": "This module is only described at reference level right now.",
    }
    payload = dict(fallback)
    payload.update(MODULE_PRESENTATION.get(entry["module_id"], {}))
    return payload


def provider_presentation(entry: dict) -> dict[str, str]:
    fallback = {
        "summary": entry["description"],
        "owner_value": "This provider is part of the current reference catalog and should be read as a declared source of modules, not as a marketplace authority.",
        "what_it_is": entry["description"],
        "what_it_is_not": "Not a certification authority and not proof that all declared modules are live.",
        "current_shape": "A declared source of the current reference modules.",
        "not_yet": "Not a broad vendor marketplace or certification layer.",
    }
    payload = dict(fallback)
    payload.update(PROVIDER_PRESENTATION.get(entry["provider_id"], {}))
    return payload


def provider_state(entry: dict) -> tuple[str, str]:
    status = entry["status"]
    if status == "unsigned-reference":
        return ("Shared reference stack", "state-proof")
    if status == "planned":
        return ("Planned provider", "state-planned")
    return ("Prototype provider", "state-proof")


def provider_focus_modules(entry: dict, modules_by_id: dict[str, dict], *, path_prefix: str) -> str:
    preferred = [
        "p4p.catalog.editor",
        "p4p.menu.list",
        "p4p.customer.status",
        "p4p.payment.cash",
    ]
    selected: list[str] = []
    for module_id in preferred + entry["module_ids"]:
        if module_id in selected:
            continue
        module_entry = modules_by_id.get(module_id)
        if module_entry is None:
            continue
        presentation = module_presentation(module_entry)
        if presentation["group"] == "internal":
            continue
        selected.append(module_id)
        if len(selected) == 4:
            break

    items: list[str] = []
    for module_id in selected:
        module_entry = modules_by_id[module_id]
        module_view = module_presentation(module_entry)
        items.append(
            f"""                <li><a href="{escape(path_prefix)}{escape(module_id)}/">{escape(module_view["title"])}</a> <span>{escape(module_view["summary"])}</span></li>"""
        )
    return "\n".join(items)


def provider_module_groups(entry: dict, modules_by_id: dict[str, dict]) -> str:
    items_by_group: dict[str, list[str]] = {group["id"]: [] for group in MODULE_GROUPS}
    for module_id in entry["module_ids"]:
        module_entry = modules_by_id.get(module_id)
        if module_entry is None:
            continue
        module_view = module_presentation(module_entry)
        state_label, _ = module_state(module_entry)
        items_by_group.setdefault(module_view["group"], []).append(
            f"""            <li><a href="../../modules/{escape(module_id)}/">{escape(module_view["title"])}</a><span>{escape(module_view["summary"])} {escape(state_label)}.</span></li>"""
        )

    sections: list[str] = []
    for group in MODULE_GROUPS:
        group_items = items_by_group.get(group["id"], [])
        if not group_items:
            continue
        sections.append(
            f"""        <article class="provider-module-group">
          <h3>{escape(group["title"])}</h3>
          <p>{escape(group["intro"])}</p>
          <ul class="provider-module-list">
{chr(10).join(group_items)}
          </ul>
        </article>"""
        )
    return "\n".join(sections)


def render_module_groups(
    modules: list[dict],
    *,
    module_prefix: str,
    provider_prefix: str,
    open_modules: set[str] | None = None,
) -> str:
    module_lookup = {entry["module_id"]: entry for entry in modules}
    output: list[str] = []
    default_open = {"p4p.menu.list", "p4p.catalog.editor", "p4p.payment.cash"}
    open_module_ids = open_modules if open_modules is not None else default_open

    for group in MODULE_GROUPS:
        items: list[str] = []
        for module_id, mapped in MODULE_PRESENTATION.items():
            if mapped["group"] != group["id"]:
                continue
            entry = module_lookup.get(module_id)
            if entry is None:
                continue
            presentation = module_presentation(entry)
            state_label, state_class = module_state(entry)
            open_attr = " open" if module_id in open_module_ids else ""
            items.append(
                f"""          <details class="module-item {state_class}"{open_attr}>
            <summary>
              <div class="module-summary">
                <div class="module-summary-copy">
                  <p class="module-audience">{escape(presentation["audience"])}</p>
                  <h3>{escape(presentation["title"])}</h3>
                  <p>{escape(presentation["summary"])}</p>
                </div>
                <div class="module-summary-side">
                  <span class="module-state-badge">{escape(state_label)}</span>
                  <span class="module-toggle-hint">Click for details</span>
                </div>
              </div>
            </summary>
            <div class="module-body">
              <p class="module-owner-line"><strong>For a pizzeria:</strong> {escape(presentation["owner_value"])}</p>
              <dl>
                <div><dt>Touches</dt><dd>{escape(presentation["touches"])}</dd></div>
                <div><dt>Does not own</dt><dd>{escape(presentation["not_owner"])}</dd></div>
                <div><dt>Current state</dt><dd>{escape(entry["operator_status"])}</dd></div>
                <div><dt>Technical id</dt><dd><code>{escape(entry["module_id"])}</code></dd></div>
              </dl>
              <p class="module-links">More info: <a href="{escape(module_prefix)}{escape(entry["module_id"])}/">Open full module page</a> <span>/</span> <a href="{escape(provider_prefix)}{escape(entry["provider_id"])}/">Open provider page</a> <span>/</span> <a href="{escape(entry["module_manifest_url"])}" rel="noopener noreferrer">Open manifest</a></p>
            </div>
          </details>"""
            )

        output.append(
            f"""        <section class="module-group">
          <div class="module-group-header">
            <p class="section-kicker">{escape(group["title"])}</p>
            <p>{escape(group["intro"])}</p>
          </div>
          <div class="module-stack">
{chr(10).join(items)}
          </div>
        </section>"""
        )

    return "\n".join(output)


def render_module_route_cards() -> str:
    routes = [
        {
            "title": "Start with the customer side",
            "body": "If you want to understand the visible public proof first, start with the menu and status pages the customer actually sees.",
            "links": [
                ("Simple online menu", "p4p.menu.list"),
                ("Order status page", "p4p.customer.status"),
            ],
        },
        {
            "title": "Then read the shop-side tools",
            "body": "If you want to understand what a pizzeria actually controls, jump to the catalog editor and kitchen queue before the deeper technical layers.",
            "links": [
                ("Edit menu and prices", "p4p.catalog.editor"),
                ("Kitchen order queue", "p4p.kitchen.screen"),
            ],
        },
        {
            "title": "Keep the boundary in view",
            "body": "If you want the practical edge of the current proof, read the simple payment path and the provider page together.",
            "links": [
                ("Pay at pickup / cash", "p4p.payment.cash"),
                ("Current provider page", "../providers/p4p.reference/"),
            ],
        },
    ]
    cards: list[str] = []
    for route in routes:
        link_rows: list[str] = []
        for label, target in route["links"]:
            href = target if target.startswith("../") else f"{target}/"
            link_rows.append(f'<a href="{escape(href)}">{escape(label)}</a>')
        cards.append(
            f"""        <article class="module-route-card">
          <h3>{escape(route["title"])}</h3>
          <p>{escape(route["body"])}</p>
          <div class="source-list">
            {' '.join(link_rows)}
          </div>
        </article>"""
        )
    return "\n".join(cards)


def render_module_read_next(entry: dict, modules_by_id: dict[str, dict]) -> str:
    cards: list[str] = []
    for route in MODULE_READ_NEXT.get(entry["module_id"], []):
        kind = route["kind"]
        if kind == "module":
            target_entry = modules_by_id[route["target"]]
            target_title = module_presentation(target_entry)["title"]
            href = f'../{route["target"]}/'
            link_label = f"Open {target_title}"
        elif kind == "provider":
            href = f'../../providers/{entry["provider_id"]}/'
            link_label = "Open provider page"
        else:
            href = "../"
            link_label = "Open module catalog"
        cards.append(
            f"""        <article class="module-route-card">
          <h3>{escape(route["title"])}</h3>
          <p>{escape(route["body"])}</p>
          <div class="source-list">
            <a href="{escape(href)}">{escape(link_label)}</a>
          </div>
        </article>"""
        )
    return "\n".join(cards)


def render_module_reader_cards(repo_url: str) -> str:
    repo_prefix = f"{repo_url.rstrip('/')}/blob/main/"
    cards = [
        {
            "title": "If you run a shop",
            "body": (
                "Start with the customer menu, the shop-side catalog, and the simple pay-at-pickup lane. "
                "Read modules as optional tools around the order flow, not as protocol theory."
            ),
            "links": [
                ("Open customer menu page", "p4p.menu.list/"),
                ("Open shop catalog page", "p4p.catalog.editor/"),
                ("Open simple payment page", "p4p.payment.cash/"),
            ],
        },
        {
            "title": "If you build software",
            "body": (
                "Start with the dumb-safe module explanation, then the community builder guide, then one small hardware lane "
                "so you can see what a narrow module looks like before reading the heavier contracts."
            ),
            "links": [
                ("Open simple module guide", f"{repo_prefix}docs/MODULES-START-HERE.md"),
                ("Open builder guide", f"{repo_prefix}docs/COMMUNITY-MODULES.md"),
                ("Open backup-print example", "p4p.order.print.backup/"),
            ],
        },
        {
            "title": "If you are skeptical",
            "body": (
                "Start with the review packet, then inspect the payment boundary and the two new pilot hardware lanes. "
                "The useful question is whether the core stays small while the extras stay honest and optional."
            ),
            "links": [
                ("Open review packet", f"{repo_prefix}REVIEW-ME.md"),
                ("Open payment boundary page", "p4p.payment.cash/"),
                ("Open pickup-board page", "p4p.pickup.board.basic/"),
            ],
        },
    ]
    rendered = []
    for card in cards:
        links = []
        for label, href in card["links"]:
            rel = ' rel="noopener noreferrer"' if href.startswith("http") else ""
            links.append(f'<a href="{escape(href)}"{rel}>{escape(label)}</a>')
        rendered.append(
            f"""        <article class="module-route-card">
          <h3>{escape(card["title"])}</h3>
          <p>{escape(card["body"])}</p>
          <div class="source-list">
            {' <span>/</span> '.join(links)}
          </div>
        </article>"""
        )
    return "\n".join(rendered)


def modules_html(site_data: dict, modules: list[dict], providers: list[dict]) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    return render_template(
        "modules.html",
        {
            "generated_comment": f"Generated from P4P module manifests on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "canonical_url": escape(f'{urls["site"]}modules/'),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "module_count": escape(str(len(modules))),
            "provider_count": escape(str(len(providers))),
            "module_reader_cards_html": render_module_reader_cards(urls["repo"]),
            "module_route_cards_html": render_module_route_cards(),
            "module_groups_html": render_module_groups(
                modules,
                module_prefix="",
                provider_prefix="../providers/",
                open_modules={"p4p.menu.list", "p4p.catalog.editor", "p4p.payment.cash", "p4p.customer.status"},
            ),
            "contact_email": escape(contact["email"]),
        },
    )


def module_page_html(site_data: dict, entry: dict, modules_by_id: dict[str, dict]) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    presentation = module_presentation(entry)
    state_label, state_class = module_state(entry)
    group = next((group for group in MODULE_GROUPS if group["id"] == presentation["group"]), MODULE_GROUPS[-1])
    return render_template(
        "module-page.html",
        {
            "generated_comment": f'Generated module page for {entry["module_id"]} on {datetime.now(timezone.utc).isoformat()}',
            "author_name": escape(contact["name"]),
            "canonical_url": escape(f'{urls["site"]}modules/{entry["module_id"]}/'),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "module_title": escape(presentation["title"]),
            "module_audience": escape(presentation["audience"]),
            "module_summary": escape(presentation["summary"]),
            "module_owner_value": escape(presentation["owner_value"]),
            "module_touches": escape(presentation["touches"]),
            "module_not_owner": escape(presentation["not_owner"]),
            "module_state": escape(state_label),
            "module_state_class": escape(state_class),
            "module_current_state": escape(entry["operator_status"]),
            "module_id": escape(entry["module_id"]),
            "module_group_title": escape(group["title"]),
            "module_group_intro": escape(group["intro"]),
            "module_data_access": escape(entry["data_access"]),
            "module_read_next_html": render_module_read_next(entry, modules_by_id),
            "module_catalog_url": escape("../"),
            "module_provider_catalog_url": escape("../../providers/"),
            "module_provider_page_url": escape(f'../../providers/{entry["provider_id"]}/'),
            "module_github_doc_url": escape(entry["module_doc_url"]),
            "module_manifest_url": escape(entry["module_manifest_url"]),
            "module_provider_doc_url": escape(entry["provider_doc_url"]),
        },
    )


def provider_page_html(site_data: dict, entry: dict, modules_by_id: dict[str, dict]) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    presentation = provider_presentation(entry)
    state_label, state_class = provider_state(entry)
    return render_template(
        "provider-page.html",
        {
            "generated_comment": f'Generated provider page for {entry["provider_id"]} on {datetime.now(timezone.utc).isoformat()}',
            "author_name": escape(contact["name"]),
            "canonical_url": escape(f'{urls["site"]}providers/{entry["provider_id"]}/'),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "provider_id": escape(entry["provider_id"]),
            "provider_name": escape(entry["name"]),
            "provider_state_label": escape(state_label),
            "provider_state_class": escape(state_class),
            "provider_status": escape(entry["status"]),
            "provider_summary": escape(presentation["summary"]),
            "provider_owner_value": escape(presentation["owner_value"]),
            "provider_what_it_is": escape(presentation["what_it_is"]),
            "provider_what_it_is_not": escape(presentation["what_it_is_not"]),
            "provider_current_shape": escape(presentation["current_shape"]),
            "provider_not_yet": escape(presentation["not_yet"]),
            "provider_website": escape(entry["website"]),
            "provider_lanes": escape(", ".join(entry["supported_lanes"])),
            "provider_module_count": escape(str(entry["module_count"])),
            "provider_focus_modules_html": provider_focus_modules(
                entry,
                modules_by_id,
                path_prefix="../../modules/",
            ),
            "provider_module_groups_html": provider_module_groups(entry, modules_by_id),
            "provider_catalog_url": escape("../"),
            "provider_doc_url": escape(entry["provider_doc_url"]),
            "provider_manifest_url": escape(entry["provider_manifest_url"]),
        },
    )


def render_providers(providers: list[dict], modules_by_id: dict[str, dict]) -> str:
    cards = []
    for index, entry in enumerate(providers):
        presentation = provider_presentation(entry)
        state_label, state_class = provider_state(entry)
        open_attr = " open" if index == 0 else ""
        cards.append(
            f"""        <details class="module-item provider-item {escape(state_class)}"{open_attr}>
          <summary>
            <div class="module-summary">
              <div class="module-summary-copy">
                <p class="module-audience">Current tool source</p>
                <h3>{escape(entry["name"])}</h3>
                <p>{escape(presentation["summary"])}</p>
              </div>
              <div class="module-summary-side">
                <span class="module-state-badge">{escape(state_label)}</span>
                <span class="module-toggle-hint">Click for details</span>
              </div>
            </div>
          </summary>
          <div class="module-body">
            <p class="module-owner-line"><strong>For a pizzeria:</strong> {escape(presentation["owner_value"])}</p>
            <dl>
              <div><dt>Current shape</dt><dd>{escape(presentation["current_shape"])}</dd></div>
              <div><dt>What this is not</dt><dd>{escape(presentation["not_yet"])}</dd></div>
              <div><dt>Module count</dt><dd>{escape(str(entry["module_count"]))}</dd></div>
              <div><dt>Technical id</dt><dd><code>{escape(entry["provider_id"])}</code></dd></div>
            </dl>
            <div class="provider-focus">
              <p class="provider-focus-label">Good first pages for a shop</p>
              <ul class="provider-focus-list">
{provider_focus_modules(entry, modules_by_id, path_prefix="../modules/")}
              </ul>
            </div>
            <p class="module-links">More info: <a href="{escape(entry["provider_id"])}/">Open full provider page</a> <span>/</span> <a href="{escape(entry["provider_doc_url"])}" rel="noopener noreferrer">GitHub provider reference</a> <span>/</span> <a href="{escape(entry["provider_manifest_url"])}" rel="noopener noreferrer">Open provider manifest</a></p>
          </div>
        </details>"""
        )
    return "\n".join(cards)


def render_trace(items: list[str]) -> str:
    return "\n".join(f'          <span role="listitem">{escape(item)}</span>' for item in items)


def render_gate(items: list[dict]) -> str:
    rendered = []
    for item in items:
        checked = " checked" if item["done"] else ""
        rendered.append(
            f'        <label><input type="checkbox"{checked} disabled> {escape(item["label"])}</label>'
        )
    return "\n".join(rendered)


def render_roadmap(items: list[str]) -> str:
    rows = []
    for item in items:
        number, body = item.split(". ", 1)
        rows.append(f"        <li><strong>{escape(number)}.</strong> {escape(body)}</li>")
    return "\n".join(rows)


def render_press_badges(labels: list[str]) -> str:
    output = []
    for label in labels:
        badge_class = " warn" if "Ikke" in label or "Not" in label else ""
        output.append(f'            <span class="badge{badge_class}">{escape(label)}</span>')
    return "\n".join(output)


def render_press_points(points: list[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    inner = "\n".join(f"            <li>{escape(point)}</li>" for point in points)
    return f"<{tag}>\n{inner}\n          </{tag}>"


def render_press_angles(items: list[dict]) -> str:
    cards = []
    for item in items:
        cards.append(
            f"""        <div class="card">
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </div>"""
        )
    return "\n".join(cards)


def render_press_module_cards(*, lang: str) -> str:
    cards = []
    open_label = "Åbn modulsiden" if lang == "dk" else "Open module page"
    for item in PRESS_MODULE_SPOTLIGHTS:
        module_id = item["module_id"]
        cards.append(
            f"""        <div class="card">
          <h3>{escape(item["title"][lang])}</h3>
          <p>{escape(item["body"][lang])}</p>
          <div class="source-list">
            <a href="../modules/{escape(module_id)}/">{escape(open_label)}</a>
          </div>
        </div>"""
        )
    return "\n".join(cards)


def homepage_html(
    site_data: dict,
    modules: list[dict],
    providers: list[dict],
    *,
    screenshot_pack: dict[str, object],
) -> str:
    home = site_data["homepage"]
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    next_gate_entries = screenshot_entries(
        screenshot_pack,
        "pizza_home",
        locale="en",
        asset_prefix="assets/screenshots/",
    )
    return render_template(
        "homepage.html",
        {
            "generated_comment": f"Generated from site-data + P4P/modules on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "site_url": escape(urls["site"]),
            "hero_eyebrow": escape(home["eyebrow"]),
            "hero_title": escape(home["title"]),
            "hero_lede": escape(home["lede"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "notice": escape(home["notice"]),
            "just_eat_source_url": escape(urls["just_eat_source"]),
            "owner_cards_html": render_owner_cards(),
            "press_heading": escape(home["press_heading"]),
            "press_lede": escape(home["press_lede"]),
            "press_facts_html": render_press_facts(home["press_facts"], urls),
            "story_heading": escape(home["story_heading"]),
            "story_body": escape(home["story_body"]),
            "one_sentence": escape(home["one_sentence"]),
            "plain_cards_html": render_plain_cards(home["plain_demo"]),
            "problem_heading": escape(home["problem_heading"]),
            "problem_body_1": escape(home["problem_body"][0]),
            "problem_body_2": escape(home["problem_body"][1]),
            "proof_steps_html": render_proof_steps(home["proof_steps"]),
            "takeaway_heading": escape(home["takeaway_heading"]),
            "takeaway_body": escape(home["takeaway_body"]),
            "proves_list_html": render_list_items(home["proves"]),
            "does_not_prove_list_html": render_list_items(home["does_not_prove"]),
            "trust_heading": escape(home["trust_heading"]),
            "trust_body": escape(home["trust_body"]),
            "trace_html": render_trace(home["trace"]),
            "module_groups_html": render_module_groups(
                modules,
                module_prefix="modules/",
                provider_prefix="providers/",
                open_modules={"p4p.menu.list", "p4p.catalog.editor", "p4p.payment.cash"},
            ),
            "provider_count": escape(str(len(providers))),
            "proof_gate_heading": escape(home["proof_gate_heading"]),
            "gate_html": render_gate(home["proof_gate"]),
            "roadmap_html": render_roadmap(home["roadmap"]),
            "pilot_gallery_html": render_screenshot_cards(next_gate_entries, card_class="screenshot-card compact"),
            "contact_email": escape(contact["email"]),
            "footer_status": escape(home["footer_status"]),
        },
    )


def press_kit_html(
    site_data: dict,
    modules: list[dict],
    providers: list[dict],
    *,
    lang: str,
    screenshot_pack: dict[str, object],
) -> str:
    data = site_data["press_kit"][lang]
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    is_dk = lang == "dk"
    locale = "da" if is_dk else "en"
    press_entries = screenshot_entries(
        screenshot_pack,
        "pizza_press",
        locale=locale,
        asset_prefix="../assets/screenshots/",
    )
    return render_template(
        "press-kit.html",
        {
            "lang_attr": "da" if is_dk else "en",
            "author_name": escape(contact["name"]),
            "page_title": escape("Pizza4People Pressekit" if is_dk else "Pizza4People Press Kit"),
            "page_description": escape(
                "Kort pressekit for Pizza4People: et offentligt open-protocol proof for direkte restaurant-kunde discovery og ordering."
                if is_dk
                else "Press kit for Pizza4People: an open protocol proof for direct restaurant-customer discovery and ordering."
            ),
            "canonical_url": escape(urls["press_kit_dk"] if is_dk else urls["press_kit_en"]),
            "press_style": load_text(TEMPLATE_ROOT / "press-style.css").strip(),
            "topbar_label": escape(data["topbar_label"]),
            "date_label": escape(data["date_label"]),
            "kicker": escape(data["kicker"]),
            "headline": escape(data["headline"]),
            "lede": escape(data["lede"]),
            "badges_html": render_press_badges(data["badges"]),
            "quote": escape(data["quote"]),
            "other_lang_link": escape("en.html" if is_dk else "index.html"),
            "other_lang_label": escape("English version" if is_dk else "Dansk version"),
            "contact_name": escape(contact["name"]),
            "contact_org": escape(contact["org"]),
            "contact_email": escape(contact["email"]),
            "why_now_label": escape("Hvorfor nu" if is_dk else "Why now"),
            "why_now_heading": escape(data["why_now_heading"]),
            "why_now_body_html": "\n".join(
                f"          <p>{escape(paragraph)}</p>" for paragraph in data["why_now_body"]
            ),
            "journalist_box_label": escape(
                "Hvad en journalist kan skrive nu" if is_dk else "What can be written now"
            ),
            "journalist_bullets_html": render_press_points(data["journalist_bullets"]),
            "source_note": escape(data["source_note"]),
            "system_label": escape("Systemet på én side" if is_dk else "System in one page"),
            "system_heading": escape(data["system_heading"]),
            "client_flow_text": escape(
                "Finder restauranter, viser menu, sender ordre."
                if is_dk
                else "Finds restaurants, renders menus, sends orders."
            ),
            "registry_flow_text": escape(
                "Discovery, heartbeat, offentlig node-metadata."
                if is_dk
                else "Discovery, heartbeat and public node metadata."
            ),
            "node_flow_label": escape("Restaurant node" if is_dk else "Restaurant node"),
            "node_flow_text": escape(
                "Menu, ordreendpoint, status, identitet og operator-kontrol."
                if is_dk
                else "Menu, order endpoint, status, identity and operator control."
            ),
            "flow_caption": escape(
                "Registry bruges til discovery. Menu og ordre går direkte fra client til restaurant node."
                if is_dk
                else "Registry is used for discovery. Menu and order flow go directly from client to restaurant node."
            ),
            "layers_label": escape("Lagene" if is_dk else "Layers"),
            "layers_heading": escape(data["layers_heading"]),
            "module_intro": escape(
                "Her er den korte butikslæsning af den nuværende stack. De fulde modul- og providersider ligger på selve Pizza4People-sitet."
                if is_dk
                else "This is the short shop-owner reading of the current stack. Full module and provider pages live on the Pizza4People site itself."
            ),
            "module_cards_html": render_press_module_cards(lang=lang),
            "module_footer_html": (
                f'Fuld lokal læsesti: <a href="{escape(urls["site"])}modules/p4p.menu.list/">modulsider</a> og '
                f'<a href="{escape(urls["site"])}providers/">providersider</a>.'
                if is_dk
                else f'Full local reading path: <a href="{escape(urls["site"])}modules/p4p.menu.list/">module pages</a> and '
                f'<a href="{escape(urls["site"])}providers/">provider pages</a>.'
            ),
            "status_label": escape("Nuværende status" if is_dk else "Current status"),
            "status_heading": escape(data["status_heading"]),
            "current_status_title": escape(data["current_status_title"]),
            "current_status_items_html": render_press_points(data["current_status_items"]),
            "next_test_title": escape(data["next_test_title"]),
            "next_test_items_html": render_press_points(data["next_test_items"], ordered=True),
            "screenshots_label": escape("Pilot-flader" if is_dk else "Pilot surfaces"),
            "screenshots_heading": escape(
                "Sådan ser den lokale node ud i den kontrollerede pilot"
                if is_dk
                else "What the local node looks like in the controlled pilot"
            ),
            "screenshots_lede": escape(
                "Det her er ikke det nuværende v0.1-proof. Det er den næste gate: de lokale driftsrum og modulflader, som restauranten selv kontrollerer."
                if is_dk
                else "This is not the current v0.1 proof. It is the next gate: the local control rooms and module surfaces the restaurant owns itself."
            ),
            "screenshots_html": render_screenshot_cards(press_entries, card_class="press-screenshot-card"),
            "primary_registry_text": escape(
                "Første discovery-endpoint." if is_dk else "First discovery endpoint."
            ),
            "backup_registry_text": escape(
                "Separat server, så discovery kan failover."
                if is_dk
                else "Separate server for discovery failover."
            ),
            "pilot_node_label": escape("Restaurant-owned node"),
            "pilot_node_text": escape(
                "Menu, order mode, order state og operator-kontrol."
                if is_dk
                else "Menu, order mode, order state and operator control."
            ),
            "pilot_client_text": escape(
                "Finder via registry. Taler direkte med node efter discovery."
                if is_dk
                else "Finds via registry. Talks directly to node after discovery."
            ),
            "verification_label": escape("Teknisk verifikation" if is_dk else "Technical verification"),
            "verification_heading": escape(data["verification_heading"]),
            "verification_body_html": "\n".join(
                f"          <p>{escape(paragraph)}</p>"
                for paragraph in data["verification_body"]
            ),
            "press_angles_label": escape("Pressevinkler" if is_dk else "Press angles"),
            "press_angles_heading": escape(data["press_angles_heading"]),
            "press_angles_html": render_press_angles(data["press_angles"]),
            "site_url": escape(urls["site"]),
            "umbrella_url": escape(urls["umbrella"]),
            "repo_url": escape(urls["repo"]),
            "just_eat_source_url": escape(urls["just_eat_source"]),
            "status_line": escape(data["status_line"]),
        },
    )


def providers_html(site_data: dict, providers: list[dict], modules_by_id: dict[str, dict]) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    return render_template(
        "providers.html",
        {
            "generated_comment": f"Generated from P4P provider manifests on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "canonical_url": escape(f'{urls["site"]}providers/'),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "provider_count": escape(str(len(providers))),
            "providers_html": render_providers(providers, modules_by_id),
            "contact_email": escape(contact["email"]),
        },
    )


def write_protocols_module_catalog(*, screenshot_pack: dict[str, object]) -> None:
    catalog_payload = public_module_catalog(urls=PUBLIC_CATALOG_URLS)
    catalog_payload["screenshot_sections"] = {
        "protocols_catalog": screenshot_payload_entries(screenshot_pack, "protocols_catalog"),
        "protocols_shop": screenshot_payload_entries(screenshot_pack, "protocols_shop"),
    }
    write_text(
        PROTOCOLS_ROOT / "modules.json",
        json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n",
    )
    write_text(
        PROTOCOLS_ROOT / "modules/index.html",
        protocols_modules_shell(
            page_kind="catalog",
            page_title="Protocols4People Modules",
            base_path="../",
            payload=catalog_payload,
        ),
    )
    write_text(
        PROTOCOLS_ROOT / "modules/shop/index.html",
        protocols_modules_shell(
            page_kind="shop",
            page_title="Protocols4People Shop Modules",
            base_path="../../",
            payload=catalog_payload,
        ),
    )


def build() -> None:
    site_data = load_site_data()
    screenshot_pack = load_screenshot_pack()
    copy_screenshot_assets(screenshot_pack)
    modules = load_modules()
    providers = load_providers(modules)
    modules_by_id = {entry["module_id"]: entry for entry in modules}
    write_text(
        PUBLIC_ROOT / "modules.json",
        json.dumps(module_catalog_payload(site_data, modules), indent=2) + "\n",
    )
    write_text(
        PUBLIC_ROOT / "providers.json",
        json.dumps(provider_catalog_payload(site_data, providers), indent=2) + "\n",
    )
    write_text(PUBLIC_ROOT / "index.html", homepage_html(site_data, modules, providers, screenshot_pack=screenshot_pack))
    write_text(PUBLIC_ROOT / "modules/index.html", modules_html(site_data, modules, providers))
    write_text(PUBLIC_ROOT / "providers/index.html", providers_html(site_data, providers, modules_by_id))
    for entry in modules:
        write_text(module_page_path(entry["module_id"]), module_page_html(site_data, entry, modules_by_id))
    for entry in providers:
        write_text(provider_page_path(entry["provider_id"]), provider_page_html(site_data, entry, modules_by_id))
    write_text(PRESS_ROOT / "index.html", press_kit_html(site_data, modules, providers, lang="dk", screenshot_pack=screenshot_pack))
    write_text(PRESS_ROOT / "en.html", press_kit_html(site_data, modules, providers, lang="en", screenshot_pack=screenshot_pack))
    write_protocols_module_catalog(screenshot_pack=screenshot_pack)


if __name__ == "__main__":
    build()
