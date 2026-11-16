#!/usr/bin/env python3
"""Read-only readiness check for one controlled P4P restaurant pilot."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


BASELINE_MODULES = {
    "p4p.catalog.editor",
    "p4p.menu.list",
    "p4p.customer.status",
    "p4p.kitchen.screen",
    "p4p.payment.cash",
}


@dataclass(frozen=True)
class CheckResult:
    level: str
    name: str
    message: str


def normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("node URL is required")
    return normalized


def fetch_json(
    url: str,
    *,
    token: str | None = None,
    timeout: float = 8.0,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-P4P-Operator-Token"] = token
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        return exc.code, payload


def result(condition: bool, name: str, success: str, failure: str) -> CheckResult:
    return CheckResult("PASS" if condition else "FAIL", name, success if condition else failure)


def _object_payload(status: int, payload: Any, name: str) -> tuple[list[CheckResult], dict[str, Any]]:
    valid = status == 200 and isinstance(payload, dict)
    return (
        [result(valid, name, "HTTP 200 JSON object", f"expected HTTP 200 JSON object, got HTTP {status}")],
        payload if valid else {},
    )


def run_checks(
    base_url: str,
    *,
    operator_token: str,
    expected_mode: str = "menu_only",
    timeout: float = 8.0,
) -> list[CheckResult]:
    base = normalize_base_url(base_url)
    results: list[CheckResult] = []

    health_status, health_payload = fetch_json(f"{base}/health", timeout=timeout)
    health_results, health = _object_payload(health_status, health_payload, "GET /health")
    results.extend(health_results)
    if health:
        results.append(result(
            health.get("status") == "ready",
            "health.ready",
            "node reports ready",
            f"node reports status={health.get('status')!r}",
        ))
        configured = health.get("configured_registries")
        registered = health.get("registered_registries")
        failed = health.get("failed_registries")
        configured_set = set(configured) if isinstance(configured, list) else set()
        registered_set = set(registered) if isinstance(registered, list) else set()
        results.append(result(
            len(configured_set) >= 2,
            "health.dual_registry_config",
            f"{len(configured_set)} registries configured",
            "fewer than two registries are configured",
        ))
        results.append(result(
            bool(configured_set) and registered_set == configured_set,
            "health.dual_registry_registration",
            "all configured registries are registered",
            f"configured={sorted(configured_set)}, registered={sorted(registered_set)}",
        ))
        results.append(result(
            isinstance(failed, dict) and not failed,
            "health.registry_failures",
            "no registry failures reported",
            f"registry failures reported: {failed!r}",
        ))

    info_status, info_payload = fetch_json(f"{base}/p4p/info", timeout=timeout)
    info_results, info = _object_payload(info_status, info_payload, "GET /p4p/info")
    results.extend(info_results)
    if info:
        results.append(result(
            info.get("order_mode") == expected_mode,
            "public.order_mode",
            f"order_mode={expected_mode}",
            f"expected order_mode={expected_mode}, got {info.get('order_mode')!r}",
        ))
        results.append(result(
            info.get("fulfillment") == ["pickup"],
            "public.fulfillment",
            "pickup is the only fulfillment mode",
            f"expected pickup-only fulfillment, got {info.get('fulfillment')!r}",
        ))
        results.append(result(
            info.get("payment_methods") == ["pay_at_pickup"],
            "public.payment",
            "pay_at_pickup is the only public payment method",
            f"expected pay_at_pickup only, got {info.get('payment_methods')!r}",
        ))

    menu_status, menu_payload = fetch_json(f"{base}/p4p/menu", timeout=timeout)
    menu_results, menu = _object_payload(menu_status, menu_payload, "GET /p4p/menu")
    results.extend(menu_results)
    if menu:
        items = menu.get("items")
        valid_items = isinstance(items, list) and bool(items)
        results.append(result(
            valid_items,
            "menu.items",
            f"{len(items)} active item(s)" if isinstance(items, list) else "active menu present",
            "menu must contain at least one active item",
        ))
        valid_prices = valid_items and all(
            isinstance(item, dict)
            and isinstance(item.get("price"), int)
            and not isinstance(item.get("price"), bool)
            and item["price"] >= 0
            for item in items
        )
        results.append(result(
            valid_prices,
            "menu.prices",
            "all active prices are non-negative integer minor units",
            "one or more active items have an invalid price",
        ))

    unauth_status, _ = fetch_json(f"{base}/operator/state", timeout=timeout)
    results.append(result(
        unauth_status == 401,
        "operator.auth_boundary",
        "operator state rejects unauthenticated access",
        f"expected HTTP 401 without token, got HTTP {unauth_status}",
    ))

    state_status, state_payload = fetch_json(
        f"{base}/operator/state", token=operator_token, timeout=timeout
    )
    state_results, state = _object_payload(state_status, state_payload, "GET /operator/state")
    results.extend(state_results)
    if state:
        node = state.get("node") if isinstance(state.get("node"), dict) else {}
        results.append(result(
            node.get("order_mode") == expected_mode,
            "operator.order_mode",
            f"operator state agrees on order_mode={expected_mode}",
            f"operator state reports order_mode={node.get('order_mode')!r}",
        ))
        expected_accepts_orders = expected_mode == "live"
        results.append(result(
            state.get("accepts_orders") is expected_accepts_orders,
            "operator.accepts_orders",
            f"accepts_orders={expected_accepts_orders}",
            f"expected accepts_orders={expected_accepts_orders}, got {state.get('accepts_orders')!r}",
        ))
        enabled = set(state.get("enabled_modules") or [])
        missing = sorted(BASELINE_MODULES - enabled)
        results.append(result(
            not missing,
            "operator.baseline_modules",
            "baseline pilot modules are running",
            f"missing running module(s): {', '.join(missing)}",
        ))
        active_payment = (state.get("active_by_lane") or {}).get("payment")
        results.append(result(
            active_payment == "p4p.payment.cash",
            "operator.payment_lane",
            "cash/pay-at-pickup lane is active",
            f"expected p4p.payment.cash, got {active_payment!r}",
        ))

    setup_status, setup_payload = fetch_json(
        f"{base}/operator/setup", token=operator_token, timeout=timeout
    )
    setup_results, setup = _object_payload(setup_status, setup_payload, "GET /operator/setup")
    results.extend(setup_results)
    if setup:
        summary = setup.get("summary") if isinstance(setup.get("summary"), dict) else {}
        readiness_key = "ready_for_live" if expected_mode == "live" else "ready_for_menu_only"
        results.append(result(
            summary.get(readiness_key) is True,
            f"setup.{readiness_key}",
            f"setup reports {readiness_key}=true",
            f"setup is not ready: {summary!r}",
        ))
        modules = setup.get("modules") if isinstance(setup.get("modules"), dict) else {}
        results.append(result(
            modules.get("restart_required") is False,
            "setup.restart_required",
            "running and desired module sets match",
            "module changes are waiting for a node restart",
        ))

    orders_status, orders_payload = fetch_json(
        f"{base}/operator/orders", token=operator_token, timeout=timeout
    )
    orders_ok = orders_status == 200 and isinstance(orders_payload, list)
    results.append(result(
        orders_ok,
        "GET /operator/orders",
        f"operator order queue is readable ({len(orders_payload)} stored order(s))"
        if isinstance(orders_payload, list)
        else "operator order queue is readable",
        f"expected HTTP 200 JSON array, got HTTP {orders_status}",
    ))
    return results


def print_results(results: list[CheckResult], *, json_output: bool) -> None:
    summary = {
        level: sum(1 for entry in results if entry.level == level)
        for level in ("PASS", "WARN", "FAIL")
    }
    if json_output:
        print(json.dumps({"summary": summary, "checks": [asdict(entry) for entry in results]}, indent=2))
        return
    for entry in results:
        print(f"[{entry.level}] {entry.name}: {entry.message}")
    print(f"\nSummary: {summary['PASS']} pass, {summary['WARN']} warn, {summary['FAIL']} fail")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only readiness check for one controlled P4P restaurant pilot."
    )
    parser.add_argument("--node-url", required=True, help="Pilot node base URL")
    parser.add_argument(
        "--operator-token-env",
        default="P4P_OPERATOR_TOKEN",
        help="Environment variable containing the operator token",
    )
    parser.add_argument("--expect-mode", choices=("menu_only", "live"), default="menu_only")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true", help="Print a machine-readable receipt")
    args = parser.parse_args(argv)

    token = os.environ.get(args.operator_token_env, "").strip()
    if not token:
        print(
            f"[FAIL] operator token: environment variable {args.operator_token_env} is empty",
            file=sys.stderr,
        )
        return 2
    try:
        results = run_checks(
            args.node_url,
            operator_token=token,
            expected_mode=args.expect_mode,
            timeout=args.timeout,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] checker: {exc}", file=sys.stderr)
        return 2

    print_results(results, json_output=args.json)
    return 1 if any(entry.level == "FAIL" for entry in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
