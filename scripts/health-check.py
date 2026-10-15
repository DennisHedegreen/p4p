#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Result:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        payload = json.loads(self.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        return payload


class CheckFailure(RuntimeError):
    pass


def request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None) -> Result:
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return Result(
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        return Result(
            exc.code,
            {key.lower(): value for key, value in exc.headers.items()},
            exc.read(),
        )
    except urllib.error.URLError as exc:
        raise CheckFailure(f"{url}: {exc.reason}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def normalized_url(value: str) -> str:
    return value.rstrip("/")


def origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}"


def json_get(url: str, label: str) -> dict[str, Any]:
    result = request(url)
    require(result.status == 200, f"{label}: expected HTTP 200, got {result.status}")
    try:
        return result.json()
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CheckFailure(f"{label}: invalid JSON response") from exc


def check_cors(url: str, allowed_origin: str, method: str, label: str) -> None:
    result = request(
        url,
        method="OPTIONS",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )
    require(result.status == 200, f"{label}: preflight returned HTTP {result.status}")
    actual = result.headers.get("access-control-allow-origin")
    require(actual == allowed_origin, f"{label}: origin {allowed_origin!r} was not allowed")


def check_security_headers(url: str, label: str) -> None:
    result = request(url)
    require(result.status == 200, f"{label}: expected HTTP 200, got {result.status}")
    expected = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "permissions-policy": "camera=(), microphone=(), geolocation=()",
    }
    for header, value in expected.items():
        require(result.headers.get(header) == value, f"{label}: missing or invalid {header}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a running P4P proof stack.")
    parser.add_argument("--mode", choices=("local", "hosted"), default="local")
    parser.add_argument("--client", default="http://127.0.0.1:8768")
    parser.add_argument("--registry-a", default="http://127.0.0.1:8000")
    parser.add_argument("--registry-b", default="http://127.0.0.1:8002")
    parser.add_argument("--node", default="http://127.0.0.1:8101")
    args = parser.parse_args()

    client = normalized_url(args.client)
    registry_a = normalized_url(args.registry_a)
    registry_b = normalized_url(args.registry_b)
    node = normalized_url(args.node)
    client_origin = origin(client)

    client_result = request(f"{client}/")
    require(client_result.status == 200, f"client: expected HTTP 200, got {client_result.status}")
    client_config = request(f"{client}/config.js")
    require(client_config.status == 200, "client config is unavailable")
    config_text = client_config.body.decode("utf-8", errors="replace")
    require(registry_a in config_text, "client config does not contain registry A")
    require(registry_b in config_text, "client config does not contain registry B")

    registry_payloads: list[dict[str, Any]] = []
    discovered_sets: list[set[str]] = []
    query = urllib.parse.urlencode(
        {"lat": "55.6517", "lng": "12.4126", "radius": "10", "category": "pizza", "country": "DK"}
    )
    for label, registry_url in (("registry A", registry_a), ("registry B", registry_b)):
        check_security_headers(f"{registry_url}/health", f"{label} security headers")
        health = json_get(f"{registry_url}/health", f"{label} health")
        require(health.get("status") == "ok", f"{label}: status is not ok")
        require(int(health.get("registered_nodes", 0)) >= 1, f"{label}: no registered node")
        if args.mode == "hosted":
            require(health.get("persistence_enabled") is True, f"{label}: persistence is disabled")
            require(health.get("storage_backend") == "sqlite", f"{label}: storage is not SQLite")
            require(health.get("registry_signing_enabled") is True, f"{label}: signing is disabled")
        registry_payloads.append(health)

        info = json_get(f"{registry_url}/registry-info", f"{label} info")
        advertised = {
            normalized_url(str(item.get("url", "")))
            for item in info.get("backups", [])
            if isinstance(item, dict)
        }
        require(registry_a in advertised, f"{label}: registry A missing from advertised backups")
        require(registry_b in advertised, f"{label}: registry B missing from advertised backups")

        discovery = json_get(f"{registry_url}/discover?{query}", f"{label} discovery")
        node_ids = {
            str(item.get("node_id"))
            for item in discovery.get("nodes", [])
            if isinstance(item, dict) and item.get("node_id")
        }
        require(node_ids, f"{label}: discovery returned no nodes")
        discovered_sets.append(node_ids)

    require(
        bool(discovered_sets[0] & discovered_sets[1]),
        "registries do not discover a common node",
    )

    check_security_headers(f"{node}/health", "node security headers")
    node_health = json_get(f"{node}/health", "node health")
    require(node_health.get("status") == "ready", "node is not ready")
    require(node_health.get("order_mode") == "test", "proof node is not in test mode")
    require(node_health.get("accepts_orders") is True, "proof node does not accept test orders")
    registered = {normalized_url(str(value)) for value in node_health.get("registered_registries", [])}
    require(registry_a in registered, "node is not registered with registry A")
    require(registry_b in registered, "node is not registered with registry B")

    menu = json_get(f"{node}/p4p/menu", "node menu")
    require(bool(menu.get("items")), "node menu is empty")
    operator = request(f"{node}/operator")
    require(operator.status == 404, f"public proof operator should be disabled, got HTTP {operator.status}")

    admin = request(f"{registry_a}/curated-overrides")
    expected_admin_statuses = {401} if args.mode == "hosted" else {401, 503}
    require(
        admin.status in expected_admin_statuses,
        f"registry admin surface should fail closed, got HTTP {admin.status}",
    )

    check_cors(f"{registry_a}/discover", client_origin, "GET", "registry CORS")
    check_cors(f"{node}/p4p/order", client_origin, "POST", "node CORS")

    print(
        json.dumps(
            {
                "status": "passed",
                "mode": args.mode,
                "client": client,
                "registry_a": registry_a,
                "registry_b": registry_b,
                "node": node,
                "common_node_ids": sorted(discovered_sets[0] & discovered_sets[1]),
                "registry_storage": [payload.get("storage_backend") for payload in registry_payloads],
                "registry_signing": [payload.get("registry_signing_enabled") for payload in registry_payloads],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailure as exc:
        print(f"P4P health check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
