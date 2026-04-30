#!/usr/bin/env python3
"""Small P4P node interoperability checker.

The checker is intentionally dependency-free so an independent implementer can
run it from a plain Python install before connecting to a shared registry.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


ORDER_MODES = {"disabled", "menu_only", "test", "live"}
SAFE_ORDER_MODES = {"disabled", "menu_only", "test"}
MODULE_STATUSES = {"active", "fallback_only", "disabled"}
MODULE_VISIBILITIES = {"public", "operator_only", "trust_only"}
MODULE_READINESS = {"planned", "test", "live"}


@dataclass
class CheckResult:
    level: str
    name: str
    message: str


def _is_string_list(value: Any, *, allow_empty: bool = True) -> bool:
    if not isinstance(value, list):
        return False
    for entry in value:
        if not isinstance(entry, str):
            return False
        if not allow_empty and not entry:
            return False
    return True


def normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("node URL is required")
    return url.rstrip("/")


def join_url(base_url: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}/{path.lstrip('/')}"


def fetch_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return response.status, json.loads(data)
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8")
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = {"raw": data}
        return exc.code, parsed


def validate_info(info: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    mode = info.get("order_mode", "disabled")
    if mode not in ORDER_MODES:
        results.append(CheckResult("FAIL", "info.order_mode", f"invalid order_mode {mode!r}"))
    else:
        results.append(CheckResult("PASS", "info.order_mode", f"order_mode={mode}"))

    protocol_version = info.get("protocol_version")
    if protocol_version == "0.1":
        results.append(CheckResult("PASS", "info.protocol_version", "protocol_version=0.1"))
    elif protocol_version is None:
        results.append(CheckResult("WARN", "info.protocol_version", "missing protocol_version; recommended for interop"))
    else:
        results.append(CheckResult("WARN", "info.protocol_version", f"unexpected protocol_version={protocol_version!r}"))

    for field in ("node_id", "name", "endpoint"):
        if info.get(field):
            results.append(CheckResult("PASS", f"info.{field}", "present"))
        else:
            results.append(CheckResult("WARN", f"info.{field}", "missing; recommended for independent interop tests"))

    results.extend(validate_module_projection(info, path="info"))
    return results


def validate_module_projection(payload: dict[str, Any], *, path: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    modules = payload.get("modules")
    declarations = payload.get("module_declarations")
    undeclared_modules = payload.get("undeclared_modules")

    if modules is None and declarations is None and undeclared_modules is None:
        return results

    normalized_modules: list[str] = []
    if modules is None:
        results.append(CheckResult("WARN", f"{path}.modules", "missing; raw module ids are recommended when richer declarations are exposed"))
    elif not _is_string_list(modules, allow_empty=False):
        results.append(CheckResult("FAIL", f"{path}.modules", "must be an array of non-empty strings"))
    else:
        normalized_modules = list(modules)
        results.append(CheckResult("PASS", f"{path}.modules", f"{len(normalized_modules)} public module id(s)"))

    declared_ids: list[str] = []
    if declarations is not None:
        if not isinstance(declarations, list):
            results.append(CheckResult("FAIL", f"{path}.module_declarations", "must be an array when present"))
        else:
            declaration_failures = 0
            for index, declaration in enumerate(declarations):
                if not isinstance(declaration, dict):
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}]", "entry must be an object"))
                    continue
                module_id = declaration.get("module_id")
                provider_id = declaration.get("provider_id")
                version = declaration.get("version")
                status = declaration.get("status")
                visibility = declaration.get("visibility")
                readiness = declaration.get("readiness")
                capabilities = declaration.get("capabilities")
                data_access = declaration.get("data_access", [])
                customer_notice = declaration.get("customer_notice")

                if not isinstance(module_id, str) or not module_id:
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].module_id", "must be a non-empty string"))
                else:
                    declared_ids.append(module_id)
                if not isinstance(provider_id, str) or not provider_id:
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].provider_id", "must be a non-empty string"))
                if not isinstance(version, str) or not version:
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].version", "must be a non-empty string"))
                if status not in MODULE_STATUSES:
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].status", "must be active, fallback_only, or disabled"))
                if visibility not in MODULE_VISIBILITIES:
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].visibility", "must be public, operator_only, or trust_only"))
                if readiness not in MODULE_READINESS:
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].readiness", "must be planned, test, or live"))
                if not _is_string_list(capabilities, allow_empty=False):
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].capabilities", "must be a non-empty array of strings"))
                if not _is_string_list(data_access):
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].data_access", "must be an array of strings"))
                if customer_notice is not None and (not isinstance(customer_notice, str) or not customer_notice):
                    declaration_failures += 1
                    results.append(CheckResult("FAIL", f"{path}.module_declarations[{index}].customer_notice", "must be a non-empty string when present"))

            if declaration_failures == 0:
                results.append(CheckResult("PASS", f"{path}.module_declarations", f"{len(declarations)} manifest-backed declaration(s)"))

    normalized_undeclared: list[str] = []
    if undeclared_modules is not None:
        if not _is_string_list(undeclared_modules, allow_empty=False):
            results.append(CheckResult("FAIL", f"{path}.undeclared_modules", "must be an array of non-empty strings when present"))
        else:
            normalized_undeclared = list(undeclared_modules)
            results.append(CheckResult("PASS", f"{path}.undeclared_modules", f"{len(normalized_undeclared)} opaque compatibility module id(s)"))

    if normalized_modules and declared_ids:
        missing = [module_id for module_id in declared_ids if module_id not in normalized_modules]
        if missing:
            results.append(CheckResult("FAIL", f"{path}.module_declarations", f"declared module ids missing from {path}.modules: {', '.join(missing)}"))
    if normalized_modules and normalized_undeclared:
        missing = [module_id for module_id in normalized_undeclared if module_id not in normalized_modules]
        if missing:
            results.append(CheckResult("FAIL", f"{path}.undeclared_modules", f"opaque module ids missing from {path}.modules: {', '.join(missing)}"))
    if declared_ids and normalized_undeclared:
        overlap = sorted(set(declared_ids).intersection(normalized_undeclared))
        if overlap:
            results.append(CheckResult("FAIL", f"{path}.undeclared_modules", f"module ids cannot be both declared and opaque: {', '.join(overlap)}"))

    return results


def validate_menu(menu: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    if menu.get("currency") == "DKK":
        results.append(CheckResult("PASS", "menu.currency", "currency=DKK"))
    else:
        results.append(CheckResult("FAIL", "menu.currency", "currency must be DKK in v0.1"))

    if isinstance(menu.get("updated_at"), str) and menu["updated_at"]:
        results.append(CheckResult("PASS", "menu.updated_at", "present"))
    else:
        results.append(CheckResult("FAIL", "menu.updated_at", "missing or not a string"))

    items = menu.get("items")
    if not isinstance(items, list) or not items:
        results.append(CheckResult("FAIL", "menu.items", "items must be a non-empty array"))
        return results

    results.append(CheckResult("PASS", "menu.items", f"{len(items)} item(s)"))
    required = {"id": str, "name": str, "description": str, "price": int, "category": str}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            results.append(CheckResult("FAIL", f"menu.items[{index}]", "item must be an object"))
            continue
        for field, expected_type in required.items():
            value = item.get(field)
            if not isinstance(value, expected_type):
                results.append(CheckResult("FAIL", f"menu.items[{index}].{field}", f"expected {expected_type.__name__}"))
        if isinstance(item.get("price"), int) and item["price"] < 0:
            results.append(CheckResult("FAIL", f"menu.items[{index}].price", "price must be >= 0"))
    return results


def build_test_order(menu: dict[str, Any]) -> dict[str, Any]:
    items = menu.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ValueError("cannot build test order without at least one menu item")
    item_id = items[0].get("id")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("first menu item has no usable id")
    return {
        "customer_name": "P4P Interop Test",
        "customer_contact": "+4500000000",
        "fulfillment": "pickup",
        "items": [{"id": item_id, "quantity": 1}],
        "note": "Interop test order. Ignore if received during testing.",
        "client_version": "p4p-node-checker-0.1",
    }


def validate_order_response(response: dict[str, Any], expected_accept: bool | None) -> list[CheckResult]:
    accepted = response.get("accepted")
    if not isinstance(accepted, bool):
        return [CheckResult("FAIL", "order.accepted", "response must include boolean accepted")]

    results: list[CheckResult] = []
    if expected_accept is not None and accepted is not expected_accept:
        results.append(CheckResult("FAIL", "order.accepted", f"expected accepted={expected_accept}, got {accepted}"))
    else:
        results.append(CheckResult("PASS", "order.accepted", f"accepted={accepted}"))

    if accepted:
        for field in ("order_id", "estimated_ready", "message"):
            if isinstance(response.get(field), str) and response[field]:
                results.append(CheckResult("PASS", f"order.{field}", "present"))
            else:
                results.append(CheckResult("FAIL", f"order.{field}", "missing or not a string"))
    else:
        for field in ("reason", "message"):
            if isinstance(response.get(field), str) and response[field]:
                results.append(CheckResult("PASS", f"order.{field}", "present"))
            else:
                results.append(CheckResult("FAIL", f"order.{field}", "missing or not a string"))
    return results


def run_checks(base_url: str, *, timeout: float, test_order: bool, allow_live_order: bool) -> list[CheckResult]:
    results: list[CheckResult] = []
    info: dict[str, Any] = {}
    menu: dict[str, Any] = {}

    status, payload = fetch_json(join_url(base_url, "info"), timeout=timeout)
    if 200 <= status < 300 and isinstance(payload, dict):
        info = payload
        results.append(CheckResult("PASS", "GET /info", f"HTTP {status}"))
        results.extend(validate_info(info))
    else:
        results.append(CheckResult("WARN", "GET /info", f"HTTP {status}; optional in v0.1 but recommended"))

    status, payload = fetch_json(join_url(base_url, "menu"), timeout=timeout)
    if 200 <= status < 300 and isinstance(payload, dict):
        menu = payload
        results.append(CheckResult("PASS", "GET /menu", f"HTTP {status}"))
        results.extend(validate_menu(menu))
    else:
        results.append(CheckResult("FAIL", "GET /menu", f"HTTP {status}; node must expose menu"))
        return results

    if not test_order:
        results.append(CheckResult("WARN", "POST /order", "skipped; pass --test-order to exercise order behavior"))
        return results

    mode = info.get("order_mode", "disabled")
    if mode == "live" and not allow_live_order:
        results.append(CheckResult("WARN", "POST /order", "skipped because order_mode=live; pass --allow-live-order if intentional"))
        return results
    if mode not in SAFE_ORDER_MODES and not allow_live_order:
        results.append(CheckResult("WARN", "POST /order", f"skipped for unsafe or unknown order_mode={mode!r}"))
        return results

    order = build_test_order(menu)
    status, payload = fetch_json(join_url(base_url, "order"), method="POST", payload=order, timeout=timeout)
    if not isinstance(payload, dict):
        results.append(CheckResult("FAIL", "POST /order", f"HTTP {status}; JSON object response required"))
        return results

    expected_accept = True if mode == "test" else False if mode in {"disabled", "menu_only"} else None
    if 200 <= status < 300:
        results.append(CheckResult("PASS", "POST /order", f"HTTP {status}"))
    else:
        results.append(CheckResult("WARN", "POST /order", f"HTTP {status}; prefer JSON order response in v0.1"))
    results.extend(validate_order_response(payload, expected_accept))
    return results


def print_results(results: list[CheckResult]) -> None:
    for result in results:
        print(f"[{result.level}] {result.name}: {result.message}")
    summary = {level: sum(1 for result in results if result.level == level) for level in ("PASS", "WARN", "FAIL")}
    print(f"\nSummary: {summary['PASS']} pass, {summary['WARN']} warn, {summary['FAIL']} fail")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a P4P node endpoint for basic v0.1 interoperability.")
    parser.add_argument("--node-url", required=True, help="Node API base URL, for example http://127.0.0.1:8101/p4p")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    parser.add_argument("--test-order", action="store_true", help="Send one interop test order or expected rejection")
    parser.add_argument("--allow-live-order", action="store_true", help="Allow --test-order even when info reports order_mode=live")
    args = parser.parse_args(argv)

    try:
        results = run_checks(
            args.node_url,
            timeout=args.timeout,
            test_order=args.test_order,
            allow_live_order=args.allow_live_order,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should report operational failure clearly.
        print(f"[FAIL] checker: {exc}", file=sys.stderr)
        return 2

    print_results(results)
    return 1 if any(result.level == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
