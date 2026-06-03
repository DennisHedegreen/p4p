from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request


REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_COUNTER = 0


def load_module(relative_path: str, env: dict[str, str] | None = None):
    global _MODULE_COUNTER

    _MODULE_COUNTER += 1
    module_path = REPO_ROOT / relative_path
    module_name = f"p4p_test_module_{_MODULE_COUNTER}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module

    with patch.dict(os.environ, env or {}, clear=False):
        spec.loader.exec_module(module)

    return module


class RegistryBridgeAsyncClient:
    def __init__(self, routes: dict[str, object], failures: set[str] | None = None) -> None:
        self.routes = routes
        self.failures = failures or set()

    async def __aenter__(self) -> "RegistryBridgeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request("POST", url)
        parts = urlsplit(url)
        base_url = f"{parts.scheme}://{parts.netloc}"
        path = parts.path

        if base_url in self.failures:
            raise httpx.ConnectError("registry unavailable", request=request)

        registry = self.routes.get(base_url)
        if registry is None:
            raise httpx.ConnectError("unknown registry", request=request)

        try:
            if path == "/announce":
                result = registry.announce(registry.Node(**json))
            elif path == "/heartbeat":
                result = registry.heartbeat(registry.HeartbeatRequest(**json))
            elif path == "/node-manifest":
                result = registry.node_manifest(registry.NodeManifestRequest(**json))
            else:
                return httpx.Response(404, request=request, text="unknown path")
        except HTTPException as exc:
            return httpx.Response(exc.status_code, request=request, text=str(exc.detail))

        return httpx.Response(200, request=request, json=result.model_dump(mode="json"))


class FailingAsyncClient:
    async def __aenter__(self) -> "FailingAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
        raise httpx.ConnectError("registry unavailable", request=httpx.Request("POST", url))


class RegistrySourceAsyncClient:
    def __init__(self, routes: dict[str, object], failures: set[str] | None = None) -> None:
        self.routes = routes
        self.failures = failures or set()

    async def __aenter__(self) -> "RegistrySourceAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        parts = urlsplit(url)
        base_url = f"{parts.scheme}://{parts.netloc}"
        path = parts.path

        if base_url in self.failures:
            raise httpx.ConnectError("registry unavailable", request=request)

        registry = self.routes.get(base_url)
        if registry is None:
            raise httpx.ConnectError("unknown registry", request=request)

        if path != "/registry-source":
            return httpx.Response(404, request=request, text="unknown path")

        result = registry.registry_source(SimpleNamespace(base_url=base_url))
        return httpx.Response(200, request=request, json=result.model_dump(mode="json"))


class ExternalPaymentClient:
    def __init__(self, *, confirmed: bool = True) -> None:
        self.confirmed = confirmed
        self.posts: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> "ExternalPaymentClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, json: dict[str, object]) -> httpx.Response:
        self.posts.append((url, json))
        request = httpx.Request("POST", url)
        if url.endswith("/confirm"):
            event = (
                {
                    "event": "PAYMENT_MODE_CHANGED",
                    "source_module": "local.pizzacoin.wallet",
                    "outcome": "SUCCESS",
                    "side_effect_state": "confirmed",
                }
                if self.confirmed
                else {
                    "event": "PAYMENT_FAILED",
                    "source_module": "local.pizzacoin.wallet",
                    "outcome": "FAILED_PERMANENT",
                    "reason_code": "INSUFFICIENT_TEST_BALANCE",
                    "side_effect_state": "none",
                }
            )
            return httpx.Response(
                200,
                request=request,
                json={
                    "payment_id": "pay_test_001",
                    "status": "confirmed" if self.confirmed else "failed",
                    "event": event,
                },
            )
        return httpx.Response(
            201,
            request=request,
            json={
                "payment_id": "pay_test_001",
                "status": "requires_confirmation",
            },
        )


class ModuleHealthClient:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.gets: list[str] = []

    def __enter__(self) -> "ModuleHealthClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str) -> httpx.Response:
        self.gets.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json={"ok": self.ok})


class NodeControlClient:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def __enter__(self) -> "NodeControlClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        self.calls.append((url, headers))
        request = httpx.Request("GET", url, headers=headers)
        route = self.routes.get(url)
        if route is None:
            raise httpx.ConnectError("unmapped route", request=request)
        if isinstance(route, Exception):
            raise route
        status_code, payload = route
        return httpx.Response(status_code, request=request, json=payload)


class P4PTruthfulnessTests(unittest.TestCase):
    def make_registry_metadata(self, **overrides) -> str:
        payload = {
            "registry_type": "local",
            "capabilities": {
                "can_onboard_nodes": True,
                "can_relay_sources": True,
                "can_curate_active_index": False,
                "can_moderate_directory": False,
                "can_issue_trust_claims": False,
                "can_reexport_sources": False,
            },
            "scope": {},
        }

        for key, value in overrides.items():
            if key == "capabilities":
                payload["capabilities"].update(value)
            elif key == "scope":
                payload["scope"].update(value)
            else:
                payload[key] = value

        return json.dumps(payload)

    def make_signed_node_payload(self, demo_module, **overrides):
        payload = demo_module.NODE.model_dump(mode="json", exclude_none=True)
        payload.pop("signature", None)
        payload["node_public_key"] = demo_module.NODE_PUBLIC_KEY
        payload["signed_at"] = overrides.pop("signed_at", demo_module.utc_now().isoformat())
        payload.update(overrides)
        payload["signature"] = demo_module.sign_payload(payload, demo_module.NODE_PRIVATE_KEY)
        return payload

    def make_signed_heartbeat_payload(self, demo_module, **overrides):
        payload = {
            "node_id": demo_module.NODE.node_id,
            "open": overrides.pop("open", demo_module.NODE.open),
            "signed_at": overrides.pop("signed_at", demo_module.utc_now().isoformat()),
        }
        payload.update(overrides)
        payload["signature"] = demo_module.sign_payload(payload, demo_module.NODE_PRIVATE_KEY)
        return payload

    def make_registry_admin_env(self) -> dict[str, str]:
        return {"P4P_REGISTRY_ADMIN_TOKEN": "registry-admin-secret"}

    def registry_admin_authorization(self) -> str:
        return "Bearer registry-admin-secret"

    def make_node_manifest_request(self, demo_module, **kwargs):
        manifest = kwargs.pop("manifest", None)
        root_rotation = kwargs.pop("root_rotation", None)
        if manifest is None:
            manifest = demo_module.build_node_manifest(**kwargs)
        payload = demo_module.signed_node_manifest_request(
            manifest=manifest,
            root_rotation=root_rotation,
        )
        assert payload is not None
        return payload

    def make_order_request(self, demo_module):
        return demo_module.OrderRequest(
            customer_name="Anna Hansen",
            customer_contact="+4512345678",
            fulfillment="pickup",
            items=[demo_module.OrderItem(id="margherita", quantity=2)],
            note="No onions",
            client_version="p4p-web-0.1",
        )

    def make_pilot_order_request(self, pilot_module, item_id: str = "kebab-pita"):
        return pilot_module.OrderRequest(
            customer_name="Anna Hansen",
            customer_contact="+4512345678",
            fulfillment="pickup",
            items=[pilot_module.OrderItem(id=item_id, quantity=1)],
            note="Pickup order",
            client_version="p4p-web-0.1",
        )

    def test_money_contract_uses_minor_units_and_iso_menu_currency(self) -> None:
        from p4p_core import Menu, MenuItem, format_money_minor, utc_now

        menu = Menu(
            currency="eur",
            updated_at=utc_now(),
            items=[
                MenuItem(
                    id="margherita",
                    name="Margherita",
                    description="Test item",
                    price=1299,
                    category="pizza",
                )
            ],
        )

        self.assertEqual(menu.currency, "EUR")
        self.assertEqual(format_money_minor(6500, "DKK"), "65.00 DKK")
        self.assertEqual(format_money_minor(1299, "USD"), "12.99 USD")
        self.assertEqual(format_money_minor(1200, "JPY"), "1200 JPY")
        self.assertIsNone(menu.items[0].image_url)
        self.assertEqual(
            MenuItem(
                id="durum-kebab",
                name="Durum kebab",
                description="Test item",
                price=7900,
                category="kebab",
                image_url=" /p4p/assets/food-image-fixtures/dishes/dish-durum-kebab.png ",
            ).image_url,
            "/p4p/assets/food-image-fixtures/dishes/dish-durum-kebab.png",
        )
        with self.assertRaises(ValidationError):
            MenuItem(
                id="bad-image",
                name="Bad image",
                description="Test item",
                price=100,
                category="pizza",
                image_url="assets/dish.png",
            )
        with self.assertRaises(ValidationError):
            Menu(currency="PIZZACOIN", updated_at=utc_now(), items=[])

    def test_single_registry_fallback_still_works(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_REGISTRY_URL": "http://solo-registry.test",
                "P4P_REGISTRY_URLS": "",
            },
        )

        self.assertEqual(demo.REGISTRY_URLS, ["http://solo-registry.test"])

    def test_node_can_announce_opaque_module_ids(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_MODULES": "p4p.payment.cash,p4p.delivery.pickup",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))
        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(demo.NODE.modules, ["p4p.payment.cash", "p4p.delivery.pickup"])
        self.assertEqual(discover_result.nodes[0].modules, demo.NODE.modules)

    def test_demo_operator_state_declares_known_modules_without_rejecting_opaque_ids(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_MODULES": "p4p.payment.cash,p4p.delivery.pickup",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        state = demo.operator_state()

        self.assertEqual(state["enabled_modules"], ["p4p.payment.cash", "p4p.delivery.pickup"])
        self.assertEqual(state["public_modules"], ["p4p.payment.cash", "p4p.delivery.pickup"])
        self.assertEqual(
            [entry["module_id"] for entry in state["module_declarations"]],
            ["p4p.payment.cash"],
        )
        self.assertEqual(
            [entry["module_id"] for entry in state["public_module_declarations"]],
            ["p4p.payment.cash"],
        )
        self.assertEqual(state["undeclared_modules"], ["p4p.delivery.pickup"])
        self.assertIn("p4p.payment.cash", state["available_modules"])
        self.assertIn("p4p.delivery.pickup", state["available_modules"])

    def test_demo_health_and_info_project_known_and_opaque_modules(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_MODULES": "p4p.payment.cash,p4p.delivery.pickup",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        response = Response()
        health = demo.health(response)
        info = demo.info()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(health["modules"], ["p4p.payment.cash", "p4p.delivery.pickup"])
        self.assertEqual(
            [entry["module_id"] for entry in health["module_declarations"]],
            ["p4p.payment.cash"],
        )
        self.assertEqual(health["undeclared_modules"], ["p4p.delivery.pickup"])
        self.assertEqual(info["modules"], ["p4p.payment.cash", "p4p.delivery.pickup"])
        self.assertEqual(
            [entry["module_id"] for entry in info["module_declarations"]],
            ["p4p.payment.cash"],
        )
        self.assertEqual(info["undeclared_modules"], ["p4p.delivery.pickup"])

    def test_directory_declares_known_modules_without_widening_discover(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_MODULES": "p4p.payment.cash,p4p.delivery.pickup",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))
        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(discover_result.nodes[0].modules, ["p4p.payment.cash", "p4p.delivery.pickup"])
        self.assertNotIn("module_declarations", discover_result.nodes[0].model_dump(mode="json", exclude_none=True))
        self.assertEqual(
            [entry.module_id for entry in directory_result.nodes[0].module_declarations],
            ["p4p.payment.cash"],
        )
        self.assertEqual(directory_result.nodes[0].undeclared_modules, ["p4p.delivery.pickup"])

    def test_directory_starts_from_same_visible_nodes_as_discover(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual([node.node_id for node in discover_result.nodes], [demo.NODE.node_id])
        self.assertEqual(
            [node.node_id for node in directory_result.nodes],
            [node.node_id for node in discover_result.nodes],
        )

    def test_root_delegation_accepts_valid_operational_node_and_exposes_role(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_DELEGATION_ROLE": "backup",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))
        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertIsNotNone(discover_result.nodes[0].delegation)
        self.assertEqual(discover_result.nodes[0].delegation.role, "backup")
        self.assertEqual(discover_result.nodes[0].source_kind, "local")
        self.assertEqual(
            discover_result.nodes[0].delegation.root_public_key,
            demo.ROOT_PUBLIC_KEY,
        )

    def test_demo_node_with_root_key_publishes_manifest_to_registries(self) -> None:
        primary = load_module("registry/main.py")
        backup = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_REGISTRY_URLS": "http://primary-registry.test,http://backup-registry.test",
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )
        routes = {
            "http://primary-registry.test": primary,
            "http://backup-registry.test": backup,
        }

        with patch.object(demo.httpx, "AsyncClient", new=lambda *args, **kwargs: RegistryBridgeAsyncClient(routes)):
            asyncio.run(demo.run_registry_cycle(force_announce=True))

        primary_manifest = primary.store.get_manifest(demo.NODE.node_id)
        backup_manifest = backup.store.get_manifest(demo.NODE.node_id)

        self.assertIsNotNone(primary_manifest)
        self.assertIsNotNone(backup_manifest)
        assert primary_manifest is not None
        self.assertEqual(primary_manifest.manifest.root_public_key, demo.ROOT_PUBLIC_KEY)
        self.assertEqual(primary_manifest.manifest.manifest_version, 1)

    def test_invalid_root_delegation_signature_is_rejected(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        payload = copy.deepcopy(demo.sign_node_announcement())
        payload["delegation"]["role"] = "backup"
        payload["signature"] = demo.sign_payload(payload, demo.NODE_PRIVATE_KEY)

        with self.assertRaises(HTTPException) as delegation_error:
            registry.announce(registry.Node(**payload))

        self.assertEqual(delegation_error.exception.status_code, 400)
        self.assertEqual(delegation_error.exception.detail, "Invalid node delegation signature")

    def test_delegation_expiry_is_enforced(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_DELEGATION_ISSUED_AT": "2026-04-28T10:00:00Z",
                "P4P_NODE_DELEGATION_EXPIRES_AT": "2026-04-28T11:00:00Z",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        with self.assertRaises(HTTPException) as delegation_error:
            registry.announce(registry.Node(**demo.sign_node_announcement()))

        self.assertEqual(delegation_error.exception.status_code, 403)
        self.assertEqual(delegation_error.exception.detail, "Delegation has expired")

    def test_node_manifest_revocation_blocks_discovery_and_heartbeat(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.node_manifest(
            registry.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=(demo.utc_now() + demo.timedelta(seconds=1)).isoformat(),
                    key_status="revoked",
                )
            )
        )

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        with self.assertRaises(HTTPException) as heartbeat_error:
            registry.heartbeat(registry.HeartbeatRequest(**demo.signed_heartbeat_payload()))

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(heartbeat_error.exception.status_code, 403)
        self.assertEqual(
            heartbeat_error.exception.detail,
            "node_public_key has been revoked in current node manifest",
        )

    def test_manifest_protected_unsigned_node_is_rejected_locally(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        unsigned_payload = demo.NODE.model_dump(mode="json", exclude_none=True)
        unsigned_payload.pop("node_public_key", None)
        unsigned_payload.pop("signed_at", None)
        unsigned_payload.pop("signature", None)
        unsigned_payload.pop("delegation", None)

        with self.assertRaises(HTTPException) as announce_error:
            registry.announce(registry.Node(**unsigned_payload))

        self.assertEqual(announce_error.exception.status_code, 403)
        self.assertEqual(
            announce_error.exception.detail,
            "This node_id is protected by a current node manifest",
        )

    def test_manifest_protected_unsigned_legacy_state_is_hidden_and_cannot_heartbeat(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        unsigned_payload = demo.NODE.model_dump(mode="json", exclude_none=True)
        unsigned_payload.pop("node_public_key", None)
        unsigned_payload.pop("signed_at", None)
        unsigned_payload.pop("signature", None)
        unsigned_payload.pop("delegation", None)
        registry.store._nodes[demo.NODE.node_id] = registry.StoredNode(
            node=registry.Node(**unsigned_payload),
            last_seen=registry.utc_now(),
            last_signed_event_at=None,
        )

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        source_snapshot = registry.registry_source(SimpleNamespace(base_url="http://127.0.0.1:8001/"))

        with self.assertRaises(HTTPException) as heartbeat_error:
            registry.heartbeat(
                registry.HeartbeatRequest(
                    node_id=demo.NODE.node_id,
                    open=False,
                )
            )

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(source_snapshot.nodes, [])
        self.assertEqual(registry.health()["registered_nodes"], 0)
        self.assertEqual(heartbeat_error.exception.status_code, 403)
        self.assertEqual(
            heartbeat_error.exception.detail,
            "Current node manifest requires signed heartbeat updates",
        )

    def test_hidden_manifest_legacy_state_cannot_receive_directory_or_trust_claims(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    }
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        unsigned_payload = demo.NODE.model_dump(mode="json", exclude_none=True)
        unsigned_payload.pop("node_public_key", None)
        unsigned_payload.pop("signed_at", None)
        unsigned_payload.pop("signature", None)
        unsigned_payload.pop("delegation", None)
        registry.store._nodes[demo.NODE.node_id] = registry.StoredNode(
            node=registry.Node(**unsigned_payload),
            last_seen=registry.utc_now(),
            last_signed_event_at=None,
        )

        with self.assertRaises(HTTPException) as directory_claim_error:
            registry.directory_claim(
                registry.DirectoryClaimRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                    reason="Should not attach to hidden legacy state",
                ),
                authorization=self.registry_admin_authorization(),
            )
        with self.assertRaises(HTTPException) as trust_claim_error:
            registry.trust_claim_issue(
                registry.TrustClaimIssueRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                ),
                SimpleNamespace(base_url="https://local.registry.test/"),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(directory_claim_error.exception.status_code, 404)
        self.assertEqual(
            directory_claim_error.exception.detail,
            "Cannot set a directory claim for an unknown node_id",
        )
        self.assertEqual(trust_claim_error.exception.status_code, 404)
        self.assertEqual(
            trust_claim_error.exception.detail,
            "Cannot issue a trust claim for an unknown node_id",
        )
        self.assertEqual(registry.health()["active_directory_claims"], 0)
        self.assertEqual(registry.health()["active_trust_claims"], 0)

    def test_root_rotation_allows_new_root_manifest_and_delegation(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        old_root_private_key = identity.generate_private_key()
        new_root_private_key = identity.generate_private_key()
        new_root_public_key = identity.public_key_from_private(new_root_private_key)
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": old_root_private_key,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))

        rotation = demo.build_root_rotation(
            previous_root_private_key=old_root_private_key,
            previous_root_public_key=demo.ROOT_PUBLIC_KEY,
            next_root_public_key=new_root_public_key,
            rotated_at=(demo.utc_now() + demo.timedelta(seconds=1)).isoformat(),
        )
        rotated_manifest = demo.build_node_manifest(
            root_private_key=new_root_private_key,
            root_public_key=new_root_public_key,
            manifest_version=2,
            issued_at=(demo.utc_now() + demo.timedelta(seconds=2)).isoformat(),
        )
        assert rotated_manifest is not None
        registry.node_manifest(
            registry.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest=rotated_manifest,
                    root_rotation=rotation,
                )
            )
        )

        rotated_delegation = demo.build_node_delegation(
            root_private_key=new_root_private_key,
            root_public_key=new_root_public_key,
            issued_at=(demo.utc_now() + demo.timedelta(seconds=2)).isoformat(),
        )
        rotated_payload = self.make_signed_node_payload(
            demo,
            delegation=rotated_delegation.model_dump(mode="json", exclude_none=True),
            signed_at=(demo.utc_now() + demo.timedelta(seconds=3)).isoformat(),
        )
        registry.announce(registry.Node(**rotated_payload))

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].delegation.root_public_key, new_root_public_key)

    def test_invalid_root_rotation_signature_is_rejected(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        old_root_private_key = identity.generate_private_key()
        wrong_root_private_key = identity.generate_private_key()
        new_root_private_key = identity.generate_private_key()
        new_root_public_key = identity.public_key_from_private(new_root_private_key)
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": old_root_private_key,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )

        rotation = demo.build_root_rotation(
            previous_root_private_key=wrong_root_private_key,
            previous_root_public_key=demo.ROOT_PUBLIC_KEY,
            next_root_public_key=new_root_public_key,
            rotated_at=(demo.utc_now() + demo.timedelta(seconds=1)).isoformat(),
        )
        rotated_manifest = demo.build_node_manifest(
            root_private_key=new_root_private_key,
            root_public_key=new_root_public_key,
            manifest_version=2,
            issued_at=(demo.utc_now() + demo.timedelta(seconds=2)).isoformat(),
        )
        assert rotated_manifest is not None

        with self.assertRaises(HTTPException) as rotation_error:
            registry.node_manifest(
                registry.NodeManifestRequest(
                    **self.make_node_manifest_request(
                        demo,
                        manifest=rotated_manifest,
                        root_rotation=rotation,
                    )
                )
            )

        self.assertEqual(rotation_error.exception.status_code, 400)
        self.assertEqual(rotation_error.exception.detail, "Invalid root rotation signature")

    def test_node_control_snapshot_aggregates_registry_and_operator_truth(self) -> None:
        control = load_module(
            "node-control/node_control.py",
            {
                "P4P_NODE_CONTROL_REGISTRY_URLS": "http://registry-a.test,http://registry-b.test",
                "P4P_NODE_CONTROL_OPERATOR_TOKENS": json.dumps({"dk-pizza-001": "operator-secret"}),
            },
        )
        app_module = sys.modules[f"{control.__name__}_app"]
        client = NodeControlClient(
            {
                "http://registry-a.test/health": (200, {"status": "ok", "registered_nodes": 1}),
                "http://registry-a.test/registry-source": (
                    200,
                    {
                        "registry_url": "http://registry-a.test",
                        "nodes": [
                            {
                                "node": {
                                    "node_id": "dk-pizza-001",
                                    "name": "Pilot Pizza A",
                                    "endpoint": "http://127.0.0.1:8201",
                                    "country": "DK",
                                    "city": "Brondby",
                                    "categories": ["pizza"],
                                    "open": True,
                                    "order_mode": "live",
                                    "modules": ["p4p.payment.cash", "p4p.order.print.backup"],
                                },
                                "last_seen": "2026-05-07T10:00:00Z",
                            }
                        ],
                    },
                ),
                "http://registry-b.test/health": (200, {"status": "ok", "registered_nodes": 1}),
                "http://registry-b.test/registry-source": (
                    200,
                    {
                        "registry_url": "http://registry-b.test",
                        "nodes": [
                            {
                                "node": {
                                    "node_id": "dk-pizza-001",
                                    "name": "Pilot Pizza A",
                                    "endpoint": "http://127.0.0.1:8201",
                                    "country": "DK",
                                    "city": "Brondby",
                                    "categories": ["pizza"],
                                    "open": True,
                                    "order_mode": "live",
                                    "modules": ["p4p.payment.cash", "p4p.order.print.backup"],
                                },
                                "last_seen": "2026-05-07T10:00:30Z",
                            }
                        ],
                    },
                ),
                "http://127.0.0.1:8201/health": (
                    200,
                    {
                        "status": "ready",
                        "node_id": "dk-pizza-001",
                        "open": True,
                        "order_mode": "live",
                        "accepts_orders": True,
                    },
                ),
                "http://127.0.0.1:8201/p4p/info": (
                    200,
                    {
                        "node_id": "dk-pizza-001",
                        "accepts_orders": True,
                        "payment_methods": ["pay_at_pickup"],
                    },
                ),
                "http://127.0.0.1:8201/operator/state": (
                    200,
                    {
                        "hardware": {
                            "profile": "box_v1_counter",
                            "customized": False,
                            "print": {
                                "target": "printer",
                                "driver": "escpos_raw",
                                "sensor_source": "serial_status",
                            },
                            "backup_print": {
                                "target": "backup_spool",
                                "driver": "file_spool",
                            },
                            "alert": {
                                "target": "counter_bell",
                                "mode": "completed",
                            },
                            "pickup_board": {
                                "target": "counter_screen",
                            },
                        },
                        "enabled_modules": ["p4p.payment.cash", "p4p.order.print.backup"],
                        "public_modules": ["p4p.payment.cash"],
                        "undeclared_modules": ["local.printer.spool"],
                        "active_by_lane": {"payment": "p4p.payment.cash"},
                        "registry": {
                            "ready": True,
                            "registered_registries": ["http://registry-a.test", "http://registry-b.test"],
                            "failed_registries": {},
                        },
                    },
                ),
                "http://127.0.0.1:8201/operator/modules": (
                    200,
                    {
                        "active_by_lane": {"payment": "p4p.payment.cash"},
                        "modules": [
                            {
                                "module_id": "p4p.payment.cash",
                                "lane": "payment",
                                "health": "available",
                                "implementation": "builtin_reference",
                            },
                            {
                                "module_id": "p4p.order.print.backup",
                                "lane": "operator",
                                "health": "available",
                                "implementation": "builtin_hardware_probe",
                            },
                        ],
                    },
                ),
            }
        )

        with patch.object(app_module.httpx, "Client", new=lambda *args, **kwargs: client):
            snapshot = control.collect_control_snapshot()

        self.assertEqual(snapshot["summary"]["configured_registries"], 2)
        self.assertEqual(snapshot["summary"]["reachable_registries"], 2)
        self.assertEqual(snapshot["summary"]["unique_nodes"], 1)
        node = snapshot["nodes"][0]
        self.assertEqual(node["node_id"], "dk-pizza-001")
        self.assertEqual(node["observed_by"], 2)
        self.assertEqual(node["public_probe"]["status"], "ready")
        self.assertEqual(node["operator_probe"]["access"], "ok")
        self.assertEqual(node["hardware"]["profile"], "box_v1_counter")
        self.assertEqual(node["active_by_lane"]["payment"], "p4p.payment.cash")
        self.assertEqual(node["module_health_counts"]["available"], 2)
        html = control.dashboard_html(snapshot, selected_node_id="dk-pizza-001")
        self.assertIn("P4P Node Control", html)
        self.assertIn("Registry truth stays narrow.", html)
        self.assertIn("box_v1_counter", html)
        self.assertIn("Pilot Pizza A", html)

    def test_node_control_reads_public_health_without_operator_token(self) -> None:
        control = load_module(
            "node-control/node_control.py",
            {
                "P4P_NODE_CONTROL_REGISTRY_URLS": "http://registry-a.test",
            },
        )
        app_module = sys.modules[f"{control.__name__}_app"]
        client = NodeControlClient(
            {
                "http://registry-a.test/health": (200, {"status": "ok", "registered_nodes": 1}),
                "http://registry-a.test/registry-source": (
                    200,
                    {
                        "registry_url": "http://registry-a.test",
                        "nodes": [
                            {
                                "node": {
                                    "node_id": "dk-pizza-002",
                                    "name": "Pilot Pizza B",
                                    "endpoint": "http://127.0.0.1:8202",
                                    "country": "DK",
                                    "city": "Copenhagen",
                                    "categories": ["pizza"],
                                    "open": False,
                                    "order_mode": "menu_only",
                                    "modules": ["p4p.payment.cash"],
                                },
                                "last_seen": "2026-05-07T10:01:00Z",
                            }
                        ],
                    },
                ),
                "http://127.0.0.1:8202/health": (
                    503,
                    {
                        "status": "not_ready",
                        "node_id": "dk-pizza-002",
                        "open": False,
                        "order_mode": "menu_only",
                        "accepts_orders": False,
                    },
                ),
                "http://127.0.0.1:8202/p4p/info": (
                    200,
                    {
                        "node_id": "dk-pizza-002",
                        "accepts_orders": False,
                        "payment_methods": ["pay_at_pickup"],
                    },
                ),
            }
        )

        with patch.object(app_module.httpx, "Client", new=lambda *args, **kwargs: client):
            snapshot = control.collect_control_snapshot()

        node = snapshot["nodes"][0]
        self.assertEqual(node["public_probe"]["status"], "not_ready")
        self.assertEqual(node["operator_probe"]["access"], "not_configured")
        self.assertFalse(any("/operator/" in url for url, _headers in client.calls))

    def test_missing_order_mode_defaults_to_disabled(self) -> None:
        registry = load_module("registry/main.py")

        node = registry.Node(
            node_id="dk-brondby-legacy-001",
            name="Legacy Pizzeria",
            location=registry.Location(lat=55.6517, lng=12.4126),
            country="DK",
            city="Brondby",
            categories=["pizza"],
            endpoint="http://127.0.0.1:8101/p4p",
            open=True,
            modules=[],
            protocol_version="0.1",
        )

        self.assertEqual(node.order_mode, "disabled")

    def test_node_id_and_categories_use_canonical_tokens(self) -> None:
        registry = load_module("registry/main.py")

        with self.assertRaises(ValidationError):
            registry.Node(
                node_id="DK-Brondby-Test-001",
                name="Legacy Pizzeria",
                location=registry.Location(lat=55.6517, lng=12.4126),
                country="DK",
                city="Brondby",
                categories=["pizza"],
                endpoint="http://127.0.0.1:8101/p4p",
                open=True,
                modules=[],
                protocol_version="0.1",
            )

        with self.assertRaises(ValidationError):
            registry.Node(
                node_id="dk-brondby-test-001",
                name="Legacy Pizzeria",
                location=registry.Location(lat=55.6517, lng=12.4126),
                country="DK",
                city="Brondby",
                categories=["Pizza"],
                endpoint="http://127.0.0.1:8101/p4p",
                open=True,
                modules=[],
                protocol_version="0.1",
            )

    def test_dual_registration_makes_node_discoverable_in_both_registries(self) -> None:
        primary = load_module("registry/main.py")
        backup = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_REGISTRY_URLS": "http://primary-registry.test,http://backup-registry.test",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        routes = {
            "http://primary-registry.test": primary,
            "http://backup-registry.test": backup,
        }

        with patch.object(demo.httpx, "AsyncClient", new=lambda *args, **kwargs: RegistryBridgeAsyncClient(routes)):
            asyncio.run(demo.run_registry_cycle(force_announce=True))

        self.assertEqual(
            demo.REGISTRATION.registered_registries,
            ["http://primary-registry.test", "http://backup-registry.test"],
        )
        self.assertEqual(demo.REGISTRATION.failed_registries, {})

        primary_result = primary.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        backup_result = backup.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(len(primary_result.nodes), 1)
        self.assertEqual(len(backup_result.nodes), 1)
        self.assertEqual(primary_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(backup_result.nodes[0].node_id, demo.NODE.node_id)

        response = Response()
        health = demo.health(response)
        order_response = demo.order(self.make_order_request(demo))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(health["status"], "ready")
        self.assertEqual(
            health["registered_registries"],
            ["http://primary-registry.test", "http://backup-registry.test"],
        )
        self.assertTrue(order_response.accepted)

    def test_closed_node_is_not_discoverable_and_rejects_orders(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_OPEN": "false",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))
        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        order_response = demo.order(self.make_order_request(demo))

        self.assertEqual(discover_result.nodes, [])
        self.assertFalse(order_response.accepted)
        self.assertEqual(order_response.reason, "closed")
        self.assertEqual(order_response.message, "Vi lukker om 5 minutter.")

    def test_menu_only_node_is_discoverable_but_rejects_orders(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ORDER_MODE": "menu_only",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))
        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        order_response = demo.order(self.make_order_request(demo))

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].order_mode, "menu_only")
        self.assertFalse(order_response.accepted)
        self.assertEqual(order_response.reason, "orders_disabled")
        self.assertEqual(order_response.message, "Denne node modtager ikke ordre endnu.")

    def test_signed_node_id_rejects_unsigned_or_tampered_updates(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        signed_node = demo.sign_node_announcement()
        registry.announce(registry.Node(**signed_node))

        unsigned_update = {
            key: value
            for key, value in signed_node.items()
            if key not in {"node_public_key", "signed_at", "signature"}
        }
        unsigned_update["name"] = "Hijacked Pizzeria"

        with self.assertRaises(HTTPException) as unsigned_error:
            registry.announce(registry.Node(**unsigned_update))

        self.assertEqual(unsigned_error.exception.status_code, 403)

        tampered_update = dict(signed_node)
        tampered_update["name"] = "Hijacked Pizzeria"

        with self.assertRaises(HTTPException) as tampered_error:
            registry.announce(registry.Node(**tampered_update))

        self.assertEqual(tampered_error.exception.status_code, 400)
        self.assertEqual(len(registry.identity_log().events), 1)

    def test_signed_node_rejects_replayed_older_announcement(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        base_time = demo.utc_now()
        first_payload = self.make_signed_node_payload(
            demo,
            signed_at=(base_time - demo.timedelta(seconds=2)).isoformat(),
        )
        newer_payload = self.make_signed_node_payload(
            demo,
            name="P4P Test Pizzeria Updated",
            signed_at=(base_time - demo.timedelta(seconds=1)).isoformat(),
        )

        registry.announce(registry.Node(**first_payload))
        registry.announce(registry.Node(**newer_payload))

        with self.assertRaises(HTTPException) as replay_error:
            registry.announce(registry.Node(**first_payload))

        self.assertEqual(replay_error.exception.status_code, 409)

    def test_identity_log_records_signed_announcements_without_private_keys(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        signed_node = demo.sign_node_announcement()
        registry.announce(registry.Node(**signed_node))
        log = registry.identity_log()

        self.assertEqual(len(log.records), 1)
        self.assertEqual(len(log.events), 1)
        self.assertEqual(log.records[0].node_id, signed_node["node_id"])
        self.assertEqual(log.records[0].node_public_key, signed_node["node_public_key"])
        self.assertEqual(log.records[0].scope, "loopback")
        self.assertEqual(log.records[0].event_count, 1)
        self.assertEqual(log.events[0].event_type, "signed_announcement")
        self.assertEqual(log.events[0].announcement_signature, signed_node["signature"])
        self.assertEqual(log.events[0].scope, "loopback")

        serialized = json.dumps(log.model_dump(mode="json"))
        self.assertNotIn("private_key", serialized)
        self.assertNotIn(demo.NODE_PRIVATE_KEY, serialized)

    def test_registry_persists_manifest_node_state_and_identity_log_across_restart(self) -> None:
        identity = load_module("p4p_identity.py")
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "registry.sqlite3")
            registry = load_module(
                "registry/main.py",
                {
                    "P4P_REGISTRY_DB_PATH": db_path,
                },
            )
            demo = load_module(
                "demo-node/demo_node.py",
                {
                    "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
                },
            )
            base_time = demo.utc_now()

            registry.node_manifest(
                registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
            )
            registry.announce(
                registry.Node(
                    **self.make_signed_node_payload(
                        demo,
                        signed_at=(base_time - demo.timedelta(seconds=1)).isoformat(),
                    )
                )
            )
            registry.heartbeat(
                registry.HeartbeatRequest(
                    **self.make_signed_heartbeat_payload(
                        demo,
                        open=False,
                        signed_at=base_time.isoformat(),
                    )
                )
            )
            registry.store.close()

            reloaded = load_module(
                "registry/main.py",
                {
                    "P4P_REGISTRY_DB_PATH": db_path,
                },
            )

            self.assertEqual(reloaded.health()["storage_backend"], "sqlite")
            self.assertTrue(reloaded.health()["persistence_enabled"])

            stored = reloaded.store.get(demo.NODE.node_id)
            manifest = reloaded.store.get_manifest(demo.NODE.node_id)
            log = reloaded.identity_log()

            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertFalse(stored.node.open)
            self.assertIsNotNone(stored.last_signed_event_at)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertEqual(manifest.manifest.manifest_version, 1)
            self.assertEqual(len(log.records), 1)
            self.assertEqual(len(log.events), 1)
            self.assertEqual(log.records[0].status, "active")
            self.assertEqual(log.events[0].node_id, demo.NODE.node_id)

            reloaded.store.close()

    def test_registry_source_exports_signed_snapshot_for_mirroring(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))

        snapshot = registry.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        serialized = snapshot.model_dump(mode="json", exclude_none=True)

        self.assertEqual(str(snapshot.registry_url), "https://registry-a.pizza4people.com/")
        self.assertEqual(snapshot.registry_metadata.registry_type, "local")
        self.assertEqual(snapshot.export_scope, "local_only")
        self.assertEqual(snapshot.storage_backend, "memory")
        self.assertEqual(snapshot.latest_identity_event_id, 1)
        self.assertEqual(len(snapshot.nodes), 1)
        self.assertEqual(len(snapshot.manifests), 1)
        self.assertEqual(len(snapshot.identity_records), 1)
        self.assertEqual(len(snapshot.identity_events), 1)
        self.assertTrue(registry.health()["registry_signing_enabled"])
        self.assertIsNotNone(snapshot.registry_public_key)
        self.assertIsNotNone(snapshot.signature)
        self.assertTrue(
            identity.verify_payload(
                serialized,
                snapshot.registry_public_key,
                snapshot.signature,
            )
        )

    def test_signed_registry_source_export_requires_configured_registry_url(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )

        with self.assertRaises(HTTPException) as export_error:
            registry.registry_source(SimpleNamespace(base_url="https://spoofed.example/"))

        self.assertEqual(export_error.exception.status_code, 503)
        self.assertEqual(
            export_error.exception.detail,
            "Signed registry source export requires P4P_REGISTRY_URL",
        )

    def test_registry_source_export_hides_signed_node_without_current_manifest(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))

        snapshot = registry.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        self.assertEqual(snapshot.nodes, [])
        self.assertEqual(len(snapshot.identity_records), 1)
        self.assertEqual(len(snapshot.identity_events), 1)

    def test_unsigned_registry_source_export_without_configured_url_requires_loopback_base(self) -> None:
        registry = load_module("registry/main.py")

        with self.assertRaises(HTTPException) as export_error:
            registry.registry_source(SimpleNamespace(base_url="https://spoofed.example/"))

        self.assertEqual(export_error.exception.status_code, 503)
        self.assertEqual(
            export_error.exception.detail,
            "Unsigned registry source export without P4P_REGISTRY_URL requires a loopback request base",
        )

    def test_trusted_import_stays_raw_only_without_promotion_policy(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        imported = mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )
        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirrors = mirror.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertTrue(imported.verified_signature)
        self.assertEqual(imported.imported_nodes, 1)
        self.assertEqual(mirror.health()["mirrored_registries"], 1)
        self.assertEqual(mirror.health()["mirrored_nodes"], 1)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(mirror.health()["mirror_discovery_policy"], "all_active")
        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(len(mirrors.sources), 1)
        self.assertEqual(len(promotions.records), 1)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "manual_only_policy")
        self.assertEqual(promotions.records[0].promoted_node_ids, [])
        self.assertTrue(mirrors.sources[0].discovery_eligible)
        self.assertEqual(mirrors.sources[0].discovery_basis, "all_active_policy")
        self.assertTrue(mirrors.sources[0].verified_signature)

    def test_public_unsigned_registry_source_is_rejected_for_import(self) -> None:
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
            },
        )
        mirror = load_module("registry/main.py", self.make_registry_admin_env())

        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        with self.assertRaises(HTTPException) as import_error:
            mirror.registry_source_import(
                snapshot,
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 403)
        self.assertEqual(
            import_error.exception.detail,
            "Public registry source import requires registry signature",
        )

    def test_public_registry_rejects_unsigned_loopback_source_import(self) -> None:
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8001",
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True}
                ),
            },
        )

        snapshot = source.registry_source(SimpleNamespace(base_url="http://127.0.0.1:8001"))

        with self.assertRaises(HTTPException) as import_error:
            mirror.registry_source_import(
                snapshot,
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 403)
        self.assertEqual(
            import_error.exception.detail,
            "Unsigned loopback registry sources are only allowed for local loopback reference development",
        )

    def test_local_loopback_registry_allows_unsigned_loopback_source_import(self) -> None:
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8001",
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8010",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True}
                ),
            },
        )

        snapshot = source.registry_source(SimpleNamespace(base_url="http://127.0.0.1:8001"))
        imported = mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )
        mirrors = mirror.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertFalse(imported.verified_signature)
        self.assertEqual(imported.imported_nodes, 0)
        self.assertEqual(len(mirrors.sources), 1)
        self.assertFalse(mirrors.sources[0].verified_signature)
        self.assertEqual(str(mirrors.sources[0].registry_url), "http://127.0.0.1:8001/")

    def test_local_loopback_registry_rejects_its_own_unsigned_snapshot_without_canonical_url(self) -> None:
        registry = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True}
                ),
            },
        )

        snapshot = registry.registry_source(SimpleNamespace(base_url="http://127.0.0.1:8001/"))

        with self.assertRaises(HTTPException) as import_error:
            registry.registry_source_import(
                snapshot,
                SimpleNamespace(base_url="http://127.0.0.1:8001/"),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 409)
        self.assertEqual(
            import_error.exception.detail,
            "Registry cannot import its own source snapshot",
        )

    def test_unsigned_trusted_loopback_source_stays_hidden_in_trusted_only_status(self) -> None:
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8001",
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8010",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "http://127.0.0.1:8001",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )

        snapshot = source.registry_source(SimpleNamespace(base_url="http://127.0.0.1:8001"))
        imported = mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )
        mirror_status = mirror.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertFalse(imported.verified_signature)
        self.assertEqual(mirror.health()["mirrored_registries"], 1)
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(len(promotions.records), 1)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "unverified_source")
        self.assertEqual(len(mirror_status.sources), 1)
        self.assertFalse(mirror_status.sources[0].verified_signature)
        self.assertFalse(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(mirror_status.sources[0].discovery_basis, "not_trusted")

    def test_unsigned_loopback_relay_cannot_reexport_nested_sources(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8003",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8010",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True}
                ),
            },
        )

        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="http://127.0.0.1:8003"))

        self.assertIsNone(relay_snapshot.registry_public_key)
        self.assertIsNone(relay_snapshot.signature)
        self.assertIsNotNone(relay_snapshot.mirrored_sources)

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                relay_snapshot,
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 403)
        self.assertEqual(
            import_error.exception.detail,
            "Re-exported mirrored sources require a verified relay signature",
        )

    def test_relayed_source_preserves_nested_import_time_for_freshness(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        stale_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        nested_exported_at = relay_snapshot.exported_at - relay.timedelta(seconds=602)
        stale_import_time = relay_snapshot.exported_at - relay.timedelta(seconds=601)
        stale_payload["mirrored_sources"][0]["snapshot"]["exported_at"] = nested_exported_at.isoformat()
        stale_payload["mirrored_sources"][0]["snapshot"]["nodes"][0]["last_seen"] = (
            nested_exported_at.isoformat()
        )
        stale_payload["mirrored_sources"][0]["snapshot"]["nodes"][0]["last_signed_event_at"] = (
            nested_exported_at.isoformat()
        )
        stale_payload["mirrored_sources"][0]["snapshot"]["nodes"][0]["node"]["signed_at"] = (
            nested_exported_at.isoformat()
        )
        stale_node = stale_payload["mirrored_sources"][0]["snapshot"]["nodes"][0]["node"]
        stale_node["signature"] = demo.sign_payload(stale_node, demo.NODE_PRIVATE_KEY)
        stale_payload["mirrored_sources"][0]["snapshot"]["manifests"][0]["stored_at"] = (
            nested_exported_at.isoformat()
        )
        stale_payload["mirrored_sources"][0]["snapshot"]["manifests"][0]["manifest"]["issued_at"] = (
            nested_exported_at.isoformat()
        )
        stale_payload["mirrored_sources"][0]["snapshot"]["manifests"][0]["manifest"]["signature"] = (
            identity.sign_payload(
                source.manifest_payload(
                    source.NodeManifest(
                        **stale_payload["mirrored_sources"][0]["snapshot"]["manifests"][0]["manifest"]
                    )
                ),
                demo.ROOT_PRIVATE_KEY,
            )
        )
        stale_node_hash = source.announcement_hash(source.Node(**stale_node))
        for event in stale_payload["mirrored_sources"][0]["snapshot"]["identity_events"]:
            event["recorded_at"] = nested_exported_at.isoformat()
            event["signed_at"] = nested_exported_at.isoformat()
            event["announcement_signature"] = stale_node["signature"]
            event["announcement_hash"] = stale_node_hash
        for record in stale_payload["mirrored_sources"][0]["snapshot"]["identity_records"]:
            record["first_seen"] = nested_exported_at.isoformat()
            record["last_seen"] = nested_exported_at.isoformat()
        nested_canonical = source.RegistrySourceSnapshot(**stale_payload["mirrored_sources"][0]["snapshot"])
        stale_payload["mirrored_sources"][0]["snapshot"]["signature"] = identity.sign_payload(
            nested_canonical.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )
        stale_payload["mirrored_sources"][0]["imported_at"] = stale_import_time.isoformat()
        canonical_payload = relay.RegistrySourceResponse(**stale_payload)
        stale_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            relay.REGISTRY_PRIVATE_KEY,
        )

        downstream.registry_source_import(
            downstream.RegistrySourceResponse(**stale_payload),
            authorization=self.registry_admin_authorization(),
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = downstream.curated_promotions(authorization=self.registry_admin_authorization())
        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        mirror_status_by_url = {str(entry.registry_url): entry for entry in mirror_status.sources}
        self.assertIn("https://registry-a.pizza4people.com/", mirror_status_by_url)
        self.assertFalse(mirror_status_by_url["https://registry-a.pizza4people.com/"].active)
        self.assertFalse(mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_eligible)
        self.assertEqual(
            mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_basis,
            "expired",
        )
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "expired")
        self.assertEqual(discover_result.nodes, [])

    def test_relayed_source_keeps_relayed_basis_even_when_source_url_is_trusted(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-a.pizza4people.com,https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        relay.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        downstream.registry_source_import(
            relay.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = downstream.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].source_discovery_basis, "trusted_relayed_upstream")
        self.assertEqual(
            str(discover_result.nodes[0].source_relay_registry_url),
            "https://umbrella.protocols4people.com/",
        )
        mirror_status_by_url = {str(entry.registry_url): entry for entry in mirror_status.sources}
        self.assertEqual(
            mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_basis,
            "trusted_relayed_upstream",
        )
        self.assertEqual(promotions.records[0].decision_basis, "trusted_relayed_upstream")

    def test_relay_snapshot_with_changed_nested_source_is_not_treated_as_unchanged(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        relay.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        first_relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        downstream.registry_source_import(
            first_relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )

        closed_heartbeat = self.make_signed_heartbeat_payload(demo, open=False)
        source.heartbeat(source.HeartbeatRequest(**closed_heartbeat))
        relay.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        second_relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        second_import = downstream.registry_source_import(
            second_relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertEqual(second_import.imported_relayed_sources, 1)
        self.assertEqual(discover_result.nodes, [])
        mirror_status_by_url = {str(entry.registry_url): entry for entry in mirror_status.sources}
        self.assertIn("https://registry-a.pizza4people.com/", mirror_status_by_url)
        self.assertEqual(
            str(mirror_status_by_url["https://registry-a.pizza4people.com/"].relayed_by_registry_url),
            "https://umbrella.protocols4people.com/",
        )

    def test_registry_rejects_import_of_its_own_source_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True}
                ),
            },
        )

        snapshot = registry.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        with self.assertRaises(HTTPException) as import_error:
            registry.registry_source_import(
                snapshot,
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 409)
        self.assertEqual(
            import_error.exception.detail,
            "Registry cannot import its own source snapshot",
        )

    def test_manual_import_of_unchanged_registry_source_stays_strict(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )
        with self.assertRaises(HTTPException) as import_error:
            mirror.registry_source_import(
                source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 409)
        self.assertEqual(
            import_error.exception.detail,
            "Imported registry source must be newer than the cached snapshot",
        )

    def test_registry_sync_fetches_configured_upstream_and_updates_sync_status(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )
        routes = {
            "https://registry-a.pizza4people.com": source,
        }

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))

        with patch.object(
            mirror.httpx,
            "AsyncClient",
            new=lambda *args, **kwargs: RegistrySourceAsyncClient(routes),
        ):
            sync_result = asyncio.run(
                mirror.registry_sync(authorization=self.registry_admin_authorization())
            )

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        sync_status = mirror.registry_sync_status(authorization=self.registry_admin_authorization())

        self.assertEqual(len(sync_result.upstreams), 1)
        self.assertEqual(sync_result.upstreams[0].status, "imported")
        self.assertTrue(sync_result.upstreams[0].verified_signature)
        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(discover_result.nodes[0].source_kind, "mirrored")
        self.assertEqual(discover_result.nodes[0].source_discovery_basis, "trusted_upstream")
        self.assertIsNone(discover_result.nodes[0].source_relay_registry_url)
        self.assertEqual(len(sync_status.configured_upstreams), 1)
        self.assertEqual(sync_status.registry_metadata.registry_type, "local")
        self.assertEqual(len(sync_status.trusted_upstreams), 1)
        self.assertEqual(sync_status.curated_index_promotion_policy, "trusted_mirrors")
        self.assertEqual(sync_status.curated_promotion_records, 1)
        self.assertEqual(sync_status.curated_promoted_sources, 1)
        self.assertEqual(sync_status.curated_denied_sources, 0)
        self.assertEqual(sync_status.mirror_discovery_policy, "trusted_only")
        self.assertEqual(sync_status.sync_interval_seconds, 0)
        self.assertIsNotNone(sync_status.last_run_at)
        self.assertEqual(sync_status.last_results[0].status, "imported")

    def test_registry_sync_skips_unchanged_upstream_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )
        routes = {
            "https://registry-a.pizza4people.com": source,
        }

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))

        with patch.object(
            mirror.httpx,
            "AsyncClient",
            new=lambda *args, **kwargs: RegistrySourceAsyncClient(routes),
        ):
            first_sync = asyncio.run(
                mirror.registry_sync(authorization=self.registry_admin_authorization())
            )
            second_sync = asyncio.run(
                mirror.registry_sync(authorization=self.registry_admin_authorization())
            )

        sync_status = mirror.registry_sync_status(authorization=self.registry_admin_authorization())

        self.assertEqual(first_sync.upstreams[0].status, "imported")
        self.assertEqual(second_sync.upstreams[0].status, "skipped")
        self.assertEqual(second_sync.upstreams[0].detail, "Skipped unchanged mirror snapshot")
        self.assertEqual(sync_status.last_results[0].status, "skipped")

    def test_policy_approved_trusted_import_is_promoted_to_curated_index(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(mirror.health()["curated_active_index_entries"], 1)
        self.assertEqual(mirror.health()["curated_promoted_sources"], 1)
        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(
            str(discover_result.nodes[0].source_registry_url),
            "https://registry-a.pizza4people.com/",
        )
        self.assertIsNotNone(discover_result.nodes[0].source_snapshot_hash)
        self.assertIsNotNone(discover_result.nodes[0].source_exported_at)
        self.assertIsNotNone(discover_result.nodes[0].source_imported_at)
        self.assertEqual(discover_result.nodes[0].source_freshness_state, "fresh")
        self.assertEqual(len(promotions.records), 1)
        self.assertEqual(promotions.records[0].decision, "promote")
        self.assertEqual(promotions.records[0].decision_basis, "trusted_upstream")
        self.assertEqual(promotions.records[0].promoted_node_ids, [demo.NODE.node_id])

    def test_manual_deny_override_hides_trusted_promoted_source(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        override = mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="deny",
                reason="Temporary local hold",
                set_by="ops",
            ),
            authorization=self.registry_admin_authorization(),
        )
        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())
        overrides = mirror.curated_overrides(authorization=self.registry_admin_authorization())

        self.assertEqual(override.override.decision, "deny")
        self.assertEqual(override.override.reason, "Temporary local hold")
        self.assertEqual(len(discover_result.nodes), 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(mirror.health()["curated_override_records"], 1)
        self.assertEqual(mirror.health()["active_curated_overrides"], 1)
        self.assertEqual(len(overrides.records), 1)
        self.assertEqual(overrides.records[0].decision, "deny")
        self.assertEqual(len(promotions.records), 1)
        self.assertEqual(promotions.records[0].automatic_decision, "promote")
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_origin, "manual")
        self.assertEqual(promotions.records[0].decision_basis, "manual_override_deny")
        self.assertEqual(promotions.records[0].override_decision, "deny")
        self.assertEqual(promotions.records[0].override_set_by, "ops")
        self.assertEqual(promotions.records[0].promoted_node_ids, [])

    def test_manual_allow_override_promotes_valid_untrusted_source(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-b.pizza4people.com",
                "P4P_MIRROR_UPSTREAMS": "",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        before_override = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="allow",
                reason="Local scope approved this upstream",
                set_by="country-curator",
            ),
            authorization=self.registry_admin_authorization(),
        )
        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(before_override.nodes, [])
        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(discover_result.nodes[0].source_discovery_basis, "manual_override_allow")
        self.assertIsNone(discover_result.nodes[0].source_relay_registry_url)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 1)
        self.assertEqual(mirror.health()["curated_override_records"], 1)
        self.assertEqual(promotions.records[0].automatic_decision, "deny")
        self.assertEqual(promotions.records[0].automatic_decision_basis, "untrusted_upstream")
        self.assertEqual(promotions.records[0].decision, "promote")
        self.assertEqual(promotions.records[0].decision_origin, "manual")
        self.assertEqual(promotions.records[0].decision_basis, "manual_override_allow")
        self.assertEqual(promotions.records[0].override_decision, "allow")
        self.assertEqual(promotions.records[0].promoted_node_ids, [demo.NODE.node_id])

    def test_registry_source_can_reexport_trusted_mirror_snapshots_without_flattening(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )

        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        self.assertEqual(str(relay_snapshot.registry_url), "https://umbrella.protocols4people.com/")
        self.assertEqual(relay_snapshot.registry_metadata.registry_type, "umbrella")
        self.assertEqual(relay_snapshot.export_scope, "local_plus_trusted_mirrors")
        self.assertEqual(relay.health()["registry_source_reexport_policy"], "local_plus_trusted_mirrors")
        self.assertEqual(relay.health()["reexportable_mirrored_registries"], 1)
        self.assertEqual(len(relay_snapshot.nodes), 0)
        self.assertEqual(len(relay_snapshot.mirrored_sources), 1)
        self.assertEqual(
            str(relay_snapshot.mirrored_sources[0].snapshot.registry_url),
            "https://registry-a.pizza4people.com/",
        )
        self.assertEqual(relay_snapshot.mirrored_sources[0].snapshot.export_scope, "local_only")
        self.assertTrue(relay_snapshot.mirrored_sources[0].verified_signature)
        self.assertTrue(relay_snapshot.mirrored_sources[0].discovery_eligible)
        self.assertEqual(relay_snapshot.mirrored_sources[0].discovery_basis, "trusted_upstream")
        self.assertEqual(
            str(relay_snapshot.mirrored_sources[0].relayed_by_registry_url),
            "https://umbrella.protocols4people.com/",
        )

    def test_health_reexportable_mirrored_registries_counts_trusted_sources_even_without_visible_nodes(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.heartbeat(source.HeartbeatRequest(**self.make_signed_heartbeat_payload(demo, open=False)))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )

        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        imported = downstream.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )

        self.assertEqual(relay.health()["reexportable_mirrored_registries"], 1)
        self.assertEqual(relay.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(imported.imported_relayed_sources, 1)
        self.assertEqual(len(relay_snapshot.mirrored_sources), 1)
        self.assertFalse(relay_snapshot.mirrored_sources[0].discovery_eligible)
        self.assertEqual(
            relay_snapshot.mirrored_sources[0].discovery_basis,
            "trusted_upstream_no_visible_nodes",
        )
        self.assertTrue(relay_snapshot.mirrored_sources[0].verified_signature)

    def test_registry_source_import_skips_reordered_mirrored_sources_as_unchanged(self) -> None:
        identity = load_module("p4p_identity.py")
        source_a = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        source_b = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-b.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": (
                    "https://registry-a.pizza4people.com,https://registry-b.pizza4people.com"
                ),
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())

        relay.registry_source_import(
            source_b.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        relay.registry_source_import(
            source_a.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        self.assertEqual(
            [
                str(item.snapshot.registry_url)
                for item in relay_snapshot.mirrored_sources
            ],
            [
                "https://registry-a.pizza4people.com/",
                "https://registry-b.pizza4people.com/",
            ],
        )

        downstream.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )

        reordered_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        reordered_payload["exported_at"] = (
            relay_snapshot.exported_at + relay.timedelta(seconds=1)
        ).isoformat()
        reordered_payload["mirrored_sources"] = list(reversed(reordered_payload["mirrored_sources"]))
        reordered_payload.pop("signature", None)
        canonical_payload = relay.RegistrySourceResponse(**reordered_payload)
        reordered_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            relay.REGISTRY_PRIVATE_KEY,
        )
        reordered_snapshot = downstream.RegistrySourceResponse(**reordered_payload)

        verified_signature = downstream.require_valid_registry_source(reordered_snapshot)
        outcome = downstream.store.import_source_with_outcome(
            reordered_snapshot,
            verified_signature=verified_signature,
            allow_stale_skip=True,
        )

        self.assertFalse(outcome.stored_top_level)
        self.assertEqual(outcome.detail, "Skipped unchanged mirror snapshot")

    def test_registry_source_import_skips_reordered_top_level_sets_as_unchanged(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo_a = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ID": "dk-brondby-alpha-001",
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8101",
            },
        )
        demo_b = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ID": "dk-brondby-beta-001",
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8102",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo_a, manifest_version=1))
        )
        source.announce(source.Node(**demo_a.sign_node_announcement()))
        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo_b, manifest_version=1))
        )
        source.announce(source.Node(**demo_b.sign_node_announcement()))

        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        downstream.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )

        reordered_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        reordered_payload["exported_at"] = (
            source_snapshot.exported_at + source.timedelta(seconds=1)
        ).isoformat()
        reordered_payload["nodes"] = list(reversed(reordered_payload["nodes"]))
        reordered_payload["manifests"] = list(reversed(reordered_payload["manifests"]))
        reordered_payload["identity_records"] = list(reversed(reordered_payload["identity_records"]))
        reordered_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**reordered_payload)
        reordered_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )
        reordered_snapshot = downstream.RegistrySourceResponse(**reordered_payload)

        verified_signature = downstream.require_valid_registry_source(reordered_snapshot)
        outcome = downstream.store.import_source_with_outcome(
            reordered_snapshot,
            verified_signature=verified_signature,
            allow_stale_skip=True,
        )

        self.assertFalse(outcome.stored_top_level)
        self.assertEqual(outcome.detail, "Skipped unchanged mirror snapshot")

    def test_registry_source_import_rejects_reexport_snapshot_without_reexport_capability(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["registry_metadata"] = json.loads(
            self.make_registry_metadata(
                registry_type="umbrella",
                capabilities={"can_reexport_sources": False},
            )
        )
        invalid_payload.pop("signature", None)
        invalid_payload["signature"] = identity.sign_payload(
            invalid_payload,
            relay.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                relay.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 403)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source export_scope=local_plus_trusted_mirrors requires can_reexport_sources capability",
        )

    def test_registry_source_import_rejects_reexport_with_unsigned_nested_loopback_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["mirrored_sources"][0]["snapshot"]["registry_url"] = "http://127.0.0.1:8001"
        invalid_payload["mirrored_sources"][0]["snapshot"].pop("registry_public_key", None)
        invalid_payload["mirrored_sources"][0]["snapshot"].pop("signature", None)
        invalid_payload.pop("signature", None)
        canonical_payload = relay.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            relay.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                relay.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 403)
        self.assertEqual(
            import_error.exception.detail,
            "Re-exported mirrored source must carry a verified upstream signature",
        )

    def test_registry_source_import_rejects_duplicate_nested_mirrored_source_urls(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["mirrored_sources"].append(copy.deepcopy(invalid_payload["mirrored_sources"][0]))
        invalid_payload.pop("signature", None)
        canonical_payload = relay.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            relay.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                relay.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Re-exported mirrored sources must not repeat the same registry_url",
        )

    def test_registry_source_import_rejects_duplicate_node_ids_in_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        duplicate_node = copy.deepcopy(invalid_payload["nodes"][0])
        duplicate_node["node"]["name"] = "Conflicting duplicate proof lane"
        invalid_payload["nodes"].append(duplicate_node)
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source snapshot must not repeat node_id values",
        )

    def test_registry_source_import_rejects_duplicate_manifest_node_ids_in_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://mirror.example",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        revoked_manifest = self.make_node_manifest_request(
            demo,
            manifest_version=2,
            key_status="revoked",
        )["manifest"]
        invalid_payload["manifests"].append(
            {
                "manifest": revoked_manifest,
                "stored_at": invalid_payload["manifests"][0]["stored_at"],
            }
        )
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source snapshot must not repeat manifest node_id values",
        )

    def test_registry_source_import_rejects_future_node_last_signed_event_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["last_signed_event_at"] = "2035-01-01T00:00:00+00:00"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "nodes[].last_signed_event_at is too far in the future",
        )

    def test_registry_source_import_rejects_node_last_signed_event_at_older_than_announcement(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["last_signed_event_at"] = "2025-01-01T00:00:00+00:00"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source nodes last_signed_event_at must not be earlier than node.signed_at",
        )

    def test_registry_source_import_rejects_node_last_seen_later_than_exported_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["last_seen"] = (
            source_snapshot.exported_at + source.timedelta(seconds=1)
        ).isoformat()
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source nodes last_seen cannot be later than exported_at",
        )

    def test_registry_source_import_rejects_node_last_signed_event_at_later_than_exported_at(
        self,
    ) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["last_signed_event_at"] = (
            source_snapshot.exported_at + source.timedelta(seconds=1)
        ).isoformat()
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source nodes last_signed_event_at cannot be later than exported_at",
        )

    def test_registry_source_import_rejects_signed_node_without_last_signed_event_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0].pop("last_signed_event_at", None)
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source signed nodes must include last_signed_event_at",
        )

    def test_registry_source_import_rejects_manifest_stored_at_later_than_exported_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["manifests"][0]["stored_at"] = (
            source_snapshot.exported_at + source.timedelta(seconds=1)
        ).isoformat()
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source manifests stored_at cannot be later than exported_at",
        )

    def test_registry_source_import_rejects_invalid_embedded_manifest_signature(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["manifests"][0]["manifest"]["manifest_version"] = 99
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(import_error.exception.detail, "Invalid node manifest signature")

    def test_registry_source_import_rejects_manifest_issued_at_later_than_stored_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        later_than_stored = (source_snapshot.exported_at + source.timedelta(seconds=1)).isoformat()
        invalid_payload["manifests"][0]["manifest"]["issued_at"] = later_than_stored
        invalid_payload["manifests"][0]["manifest"]["signature"] = identity.sign_payload(
            source.manifest_payload(source.NodeManifest(**invalid_payload["manifests"][0]["manifest"])),
            demo.ROOT_PRIVATE_KEY,
        )
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source manifests stored_at cannot be earlier than manifest.issued_at",
        )

    def test_registry_source_import_rejects_signed_node_without_identity_record(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"] = []
        invalid_payload["identity_events"] = []
        invalid_payload["latest_identity_event_id"] = None
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source signed nodes must have matching identity_records",
        )

    def test_registry_source_export_hides_revoked_signed_node_from_top_level_nodes(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.node_manifest(
            registry.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=registry.utc_now().isoformat(),
                    key_status="revoked",
                )
            )
        )

        source_snapshot = registry.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        self.assertEqual(source_snapshot.nodes, [])
        self.assertEqual(len(source_snapshot.manifests), 1)
        self.assertEqual(source_snapshot.manifests[0].manifest.keys[0].status, "revoked")

    def test_registry_source_import_rejects_signed_node_hidden_by_current_manifest(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        visible_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        source.node_manifest(
            source.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=source.utc_now().isoformat(),
                    key_status="revoked",
                )
            )
        )
        revoked_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = revoked_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"] = [visible_snapshot.nodes[0].model_dump(mode="json", exclude_none=True)]
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source signed nodes must be current-manifest-visible",
        )

    def test_registry_source_import_rejects_unsigned_node_under_current_manifest(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["node"].pop("node_public_key", None)
        invalid_payload["nodes"][0]["node"].pop("delegation", None)
        invalid_payload["nodes"][0]["node"].pop("signed_at", None)
        invalid_payload["nodes"][0]["node"].pop("signature", None)
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source manifest-protected nodes must be signed",
        )

    def test_registry_source_import_rejects_invalid_current_announcement_signature(
        self,
    ) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["node"]["name"] = "Forged current node name"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source signed nodes must carry a valid current announcement signature or later signed open-state drift",
        )

    def test_registry_source_import_rejects_forged_current_announcement_after_signed_heartbeat(
        self,
    ) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.heartbeat(
            source.HeartbeatRequest(
                **self.make_signed_heartbeat_payload(
                    demo,
                    open=False,
                    signed_at=source.utc_now().isoformat(),
                )
            )
        )
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["node"]["name"] = "Forged after heartbeat"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source signed nodes must carry a valid current announcement signature or later signed open-state drift",
        )

    def test_registry_source_import_rejects_signed_node_last_seen_earlier_than_last_signed_event_at(
        self,
    ) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["nodes"][0]["last_seen"] = (
            source_snapshot.nodes[0].last_signed_event_at - source.timedelta(seconds=1)
        ).isoformat()
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source nodes last_seen must not be earlier than last_signed_event_at",
        )

    def test_registry_source_import_rejects_identity_event_recorded_at_later_than_exported_at(
        self,
    ) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        later_than_export = (source_snapshot.exported_at + source.timedelta(seconds=1)).isoformat()
        invalid_payload["identity_events"][0]["recorded_at"] = later_than_export
        invalid_payload["identity_records"][0]["first_seen"] = later_than_export
        invalid_payload["identity_records"][0]["last_seen"] = later_than_export
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events recorded_at cannot be later than exported_at",
        )

    def test_registry_source_import_rejects_identity_event_signed_at_later_than_recorded_at(
        self,
    ) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_events"][0]["signed_at"] = (
            source_snapshot.exported_at + source.timedelta(seconds=1)
        ).isoformat()
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events signed_at cannot be later than recorded_at",
        )

    def test_registry_source_import_rejects_replayed_identity_event(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        replayed_event = copy.deepcopy(invalid_payload["identity_events"][0])
        replayed_event["event_id"] = 2
        invalid_payload["identity_events"].append(replayed_event)
        invalid_payload["latest_identity_event_id"] = 2
        invalid_payload["identity_records"][0]["event_count"] = 2
        invalid_payload["identity_records"][0]["last_seen"] = replayed_event["recorded_at"]
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events must not repeat the same signed event",
        )

    def test_registry_source_import_rejects_gapped_identity_event_ids(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_events"][1]["event_id"] = 3
        invalid_payload["latest_identity_event_id"] = 3
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events must be contiguous by event_id",
        )

    def test_registry_source_import_rejects_mismatched_latest_identity_event_id(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["latest_identity_event_id"] = invalid_payload["latest_identity_event_id"] + 98
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source latest_identity_event_id must match the last identity event_id",
        )

    def test_registry_source_import_rejects_out_of_order_identity_events(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_events"] = list(reversed(invalid_payload["identity_events"]))
        invalid_payload["latest_identity_event_id"] = invalid_payload["identity_events"][-1]["event_id"]
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events must be strictly increasing by event_id",
        )

    def test_registry_source_import_rejects_duplicate_identity_record_keys(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"].append(copy.deepcopy(invalid_payload["identity_records"][0]))
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source snapshot must not repeat identity record keys",
        )

    def test_registry_source_import_rejects_mismatched_identity_record_event_count(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"][0]["event_count"] = 999
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_records event_count must match identity_events",
        )

    def test_registry_source_import_rejects_mismatched_identity_record_first_seen(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"][0]["first_seen"] = "2025-01-01T00:00:00+00:00"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_records first_seen must match identity_events",
        )

    def test_registry_source_import_rejects_mismatched_identity_record_scope(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"][0]["scope"] = "public"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_records scope must match the latest identity event",
        )

    def test_registry_source_import_rejects_mismatched_identity_record_status_for_active_manifest_key(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"][0]["status"] = "revoked"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_records status must match current manifest key status",
        )

    def test_registry_source_import_rejects_missing_identity_records_for_events(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["identity_records"] = []
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events must have matching identity_records",
        )

    def test_registry_source_import_rejects_event_key_without_matching_identity_record(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        extra_event = copy.deepcopy(invalid_payload["identity_events"][0])
        extra_event["event_id"] = invalid_payload["latest_identity_event_id"] + 1
        extra_event["node_public_key"] = "ed25519:" + ("a" * 64)
        invalid_payload["identity_events"].append(extra_event)
        invalid_payload["latest_identity_event_id"] = extra_event["event_id"]
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events must have matching identity_records",
        )

    def test_registry_source_import_rejects_out_of_order_identity_event_recorded_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source.announce(source.Node(**self.make_signed_node_payload(demo, name="Second signed name")))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        late_recorded_at = invalid_payload["identity_events"][0]["recorded_at"]
        early_recorded_at = "2025-01-01T00:00:00+00:00"
        invalid_payload["identity_events"][0]["recorded_at"] = late_recorded_at
        invalid_payload["identity_events"][1]["recorded_at"] = early_recorded_at
        invalid_payload["identity_events"][1]["signed_at"] = early_recorded_at
        invalid_payload["identity_records"][0]["first_seen"] = early_recorded_at
        invalid_payload["identity_records"][0]["last_seen"] = late_recorded_at
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_events recorded_at must be nondecreasing by event_id",
        )

    def test_registry_source_import_rejects_future_identity_event_recorded_at(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        future_recorded_at = "2035-01-01T00:00:00+00:00"
        invalid_payload["identity_events"][0]["recorded_at"] = future_recorded_at
        invalid_payload["identity_records"][0]["first_seen"] = future_recorded_at
        invalid_payload["identity_records"][0]["last_seen"] = future_recorded_at
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "identity_events[].recorded_at is too far in the future",
        )

    def test_registry_source_import_rejects_active_identity_record_when_manifest_revokes_key(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        downstream = load_module("registry/main.py", self.make_registry_admin_env())
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = source_snapshot.model_dump(mode="json", exclude_none=True)
        invalid_payload["manifests"][0]["manifest"]["keys"][0]["status"] = "revoked"
        invalid_payload["manifests"][0]["manifest"]["signature"] = identity.sign_payload(
            source.manifest_payload(source.NodeManifest(**invalid_payload["manifests"][0]["manifest"])),
            demo.ROOT_PRIVATE_KEY,
        )
        invalid_payload["identity_records"][0]["status"] = "active"
        invalid_payload.pop("signature", None)
        canonical_payload = source.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            source.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Registry source identity_records status must match current manifest key status",
        )

    def test_registry_source_import_rejects_self_nested_relay_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        base_snapshot = {
            key: value
            for key, value in invalid_payload.items()
            if key not in {"mirrored_sources", "signature"}
        }
        base_snapshot["export_scope"] = "local_only"
        invalid_payload["mirrored_sources"][0]["snapshot"] = base_snapshot
        invalid_payload["mirrored_sources"][0]["imported_at"] = invalid_payload["exported_at"]
        invalid_payload.pop("signature", None)
        nested_canonical = relay.RegistrySourceSnapshot(**invalid_payload["mirrored_sources"][0]["snapshot"])
        invalid_payload["mirrored_sources"][0]["snapshot"] = nested_canonical.model_dump(
            mode="json",
            exclude_none=True,
        )
        invalid_payload["mirrored_sources"][0]["snapshot"]["signature"] = identity.sign_payload(
            invalid_payload["mirrored_sources"][0]["snapshot"],
            relay.REGISTRY_PRIVATE_KEY,
        )
        canonical_payload = relay.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            relay.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                relay.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Re-exported mirrored sources must not point back to the relay registry_url itself",
        )

    def test_registry_source_import_rejects_reexport_with_impossible_nested_import_time(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        invalid_payload = relay_snapshot.model_dump(mode="json", exclude_none=True)
        nested_exported_at = relay_snapshot.mirrored_sources[0].snapshot.exported_at
        invalid_payload["mirrored_sources"][0]["imported_at"] = (
            nested_exported_at - relay.timedelta(seconds=1)
        ).isoformat()
        invalid_payload.pop("signature", None)
        canonical_payload = relay.RegistrySourceResponse(**invalid_payload)
        invalid_payload["signature"] = identity.sign_payload(
            canonical_payload.model_dump(mode="json", exclude_none=True),
            relay.REGISTRY_PRIVATE_KEY,
        )

        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                relay.RegistrySourceResponse(**invalid_payload),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(import_error.exception.status_code, 400)
        self.assertEqual(
            import_error.exception.detail,
            "Re-exported mirrored source imported_at cannot be earlier than nested exported_at",
        )

    def test_reexported_trusted_mirror_can_be_imported_via_trusted_umbrella(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        relay.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        imported = downstream.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = downstream.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(imported.imported_relayed_sources, 1)
        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(discover_result.nodes[0].source_kind, "mirrored")
        self.assertEqual(discover_result.nodes[0].source_discovery_basis, "trusted_relayed_upstream")
        self.assertEqual(
            str(discover_result.nodes[0].source_registry_url),
            "https://registry-a.pizza4people.com/",
        )
        self.assertEqual(
            str(discover_result.nodes[0].source_relay_registry_url),
            "https://umbrella.protocols4people.com/",
        )
        relayed_records = [
            record for record in promotions.records if record.source_relay_registry_url is not None
        ]
        self.assertEqual(len(relayed_records), 1)
        self.assertEqual(relayed_records[0].decision, "promote")
        self.assertEqual(relayed_records[0].decision_basis, "trusted_relayed_upstream")
        self.assertEqual(relayed_records[0].promoted_node_ids, [demo.NODE.node_id])

        mirror_status_by_url = {
            str(entry.registry_url): entry for entry in mirror_status.sources
        }
        self.assertIn("https://umbrella.protocols4people.com/", mirror_status_by_url)
        self.assertIn("https://registry-a.pizza4people.com/", mirror_status_by_url)
        self.assertEqual(
            str(mirror_status_by_url["https://registry-a.pizza4people.com/"].relayed_by_registry_url),
            "https://umbrella.protocols4people.com/",
        )
        self.assertTrue(mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_eligible)
        self.assertEqual(
            mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_basis,
            "trusted_relayed_upstream",
        )

    def test_relayed_registry_source_skips_nested_snapshot_of_self(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                **self.make_registry_admin_env(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        relay.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        imported = source.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        mirror_status = source.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertEqual(imported.imported_relayed_sources, 0)
        self.assertEqual(imported.imported_nodes, 0)
        self.assertEqual(len(source.store._mirror_sources), 1)
        self.assertEqual(len(mirror_status.sources), 1)
        self.assertEqual(
            str(mirror_status.sources[0].registry_url),
            "https://umbrella.protocols4people.com/",
        )

    def test_direct_import_outranks_relaxed_copy_of_same_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-a.pizza4people.com,https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        downstream.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        downstream.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )

        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].source_discovery_basis, "trusted_upstream")
        self.assertIsNone(discover_result.nodes[0].source_relay_registry_url)
        mirror_status_by_url = {str(entry.registry_url): entry for entry in mirror_status.sources}
        self.assertIn("https://registry-a.pizza4people.com/", mirror_status_by_url)
        self.assertIsNone(mirror_status_by_url["https://registry-a.pizza4people.com/"].relayed_by_registry_url)
        self.assertEqual(
            mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_basis,
            "trusted_upstream",
        )

    def test_untrusted_direct_import_does_not_clobber_trusted_relay_of_same_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        source_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            source_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        downstream.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        with self.assertRaises(HTTPException) as import_error:
            downstream.registry_source_import(
                source_snapshot,
                authorization=self.registry_admin_authorization(),
            )

        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertEqual(import_error.exception.status_code, 409)
        self.assertEqual(
            import_error.exception.detail,
            "Imported registry source must be newer than the cached snapshot",
        )
        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].source_discovery_basis, "trusted_relayed_upstream")
        self.assertEqual(
            str(discover_result.nodes[0].source_relay_registry_url),
            "https://umbrella.protocols4people.com/",
        )
        mirror_status_by_url = {str(entry.registry_url): entry for entry in mirror_status.sources}
        self.assertIn("https://registry-a.pizza4people.com/", mirror_status_by_url)
        self.assertEqual(
            str(mirror_status_by_url["https://registry-a.pizza4people.com/"].relayed_by_registry_url),
            "https://umbrella.protocols4people.com/",
        )
        self.assertEqual(
            mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_basis,
            "trusted_relayed_upstream",
        )

    def test_older_relayed_copy_does_not_overwrite_fresher_direct_snapshot(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        relay = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": True},
                ),
            },
        )
        downstream = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-a.pizza4people.com,https://umbrella.protocols4people.com",
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        older_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay.registry_source_import(
            older_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        fresher_direct_snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        direct_import = downstream.registry_source_import(
            fresher_direct_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        relayed_import = downstream.registry_source_import(
            relay_snapshot,
            authorization=self.registry_admin_authorization(),
        )
        mirror_status = downstream.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertEqual(direct_import.imported_nodes, 1)
        self.assertEqual(relayed_import.imported_relayed_sources, 0)
        mirror_status_by_url = {str(entry.registry_url): entry for entry in mirror_status.sources}
        self.assertIn("https://registry-a.pizza4people.com/", mirror_status_by_url)
        self.assertIsNone(mirror_status_by_url["https://registry-a.pizza4people.com/"].relayed_by_registry_url)
        self.assertEqual(
            mirror_status_by_url["https://registry-a.pizza4people.com/"].discovery_basis,
            "trusted_upstream",
        )

    def test_untrusted_mirror_source_stays_cached_but_hidden_in_trusted_only_mode(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_DISCOVERY_POLICY": "trusted_only",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "https://registry-b.pizza4people.com",
                "P4P_MIRROR_UPSTREAMS": "",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())
        sync_status = mirror.registry_sync_status(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["mirrored_registries"], 1)
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(mirror.health()["curated_denied_sources"], 1)
        self.assertEqual(mirror.health()["mirror_discovery_policy"], "trusted_only")
        self.assertEqual(len(sync_status.trusted_upstreams), 1)
        self.assertEqual(str(sync_status.trusted_upstreams[0].url), "https://registry-b.pizza4people.com/")
        self.assertEqual(sync_status.mirror_discovery_policy, "trusted_only")
        self.assertEqual(len(promotions.records), 1)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "untrusted_upstream")
        self.assertTrue(mirror_status.sources[0].active)
        self.assertFalse(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(mirror_status.sources[0].discovery_basis, "not_trusted")

    def test_revoked_upstream_source_is_demoted_from_curated_active_index(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        promoted_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        self.assertEqual(len(promoted_result.nodes), 1)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 1)
        self.assertEqual(
            mirror.curated_promotions(authorization=self.registry_admin_authorization()).records[0].decision,
            "promote",
        )

        source.node_manifest(
            source.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=source.utc_now().isoformat(),
                    key_status="revoked",
                )
            )
        )
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors(authorization=self.registry_admin_authorization())

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(
            mirror.curated_promotions(authorization=self.registry_admin_authorization()).records[0].decision,
            "deny",
        )
        self.assertEqual(
            mirror.curated_promotions(authorization=self.registry_admin_authorization()).records[0].decision_basis,
            "no_visible_nodes",
        )
        self.assertEqual(
            mirror.curated_promotions(authorization=self.registry_admin_authorization()).records[0].promoted_node_ids,
            [],
        )
        self.assertFalse(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(mirror_status.sources[0].discovery_basis, "no_visible_nodes")

    def test_expired_mirror_source_is_hidden_from_discovery(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_SOURCE_TTL_SECONDS": "1",
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        mirror.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )

        stored = next(iter(mirror.store._mirror_sources.values()))
        stored.imported_at = mirror.utc_now() - mirror.timedelta(seconds=2)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["mirrored_registries"], 0)
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "expired")
        self.assertFalse(mirror_status.sources[0].active)
        self.assertFalse(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(mirror_status.sources[0].discovery_basis, "expired")

    def test_registry_sync_status_refreshes_curated_counts_for_expired_source(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_SOURCE_TTL_SECONDS": "1",
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        stored = next(iter(mirror.store._mirror_sources.values()))
        stored.imported_at = mirror.utc_now() - mirror.timedelta(seconds=2)

        sync_status = mirror.registry_sync_status(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(sync_status.curated_promotion_records, 1)
        self.assertEqual(sync_status.curated_promoted_sources, 0)
        self.assertEqual(sync_status.curated_denied_sources, 1)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "expired")

    def test_stale_mirrored_node_is_not_treated_as_visible_for_status_or_promotion(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        stored = next(iter(mirror.store._mirror_sources.values()))
        stored.snapshot.nodes[0].last_seen = mirror.utc_now() - mirror.timedelta(seconds=181)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "no_visible_nodes")
        self.assertEqual(promotions.records[0].promoted_node_ids, [])
        self.assertFalse(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(mirror_status.sources[0].discovery_basis, "no_visible_nodes")

    def test_health_discoverable_mirrored_nodes_counts_only_visible_nodes(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo_a = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ID": "dk-brondby-alpha-001",
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8101",
            },
        )
        demo_b = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ID": "dk-brondby-beta-001",
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8102",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo_a, manifest_version=1))
        )
        source.announce(source.Node(**demo_a.sign_node_announcement()))
        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo_b, manifest_version=1))
        )
        source.announce(source.Node(**demo_b.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        stored = next(iter(mirror.store._mirror_sources.values()))
        stale_node = next(item for item in stored.snapshot.nodes if item.node.node_id == demo_b.NODE.node_id)
        stale_node.last_seen = mirror.utc_now() - mirror.timedelta(seconds=181)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors(authorization=self.registry_admin_authorization())
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual([item.node_id for item in discover_result.nodes], [demo_a.NODE.node_id])
        self.assertEqual(mirror.health()["mirrored_nodes"], 2)
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 1)
        self.assertEqual(mirror.health()["discoverable_mirrored_nodes"], 1)
        self.assertTrue(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(promotions.records[0].promoted_node_ids, [demo_a.NODE.node_id])

    def test_manual_allow_override_does_not_bypass_stale_source(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_SOURCE_TTL_SECONDS": "1",
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="allow",
                reason="Still valid only while source is fresh",
                set_by="ops",
            ),
            authorization=self.registry_admin_authorization(),
        )

        stored = next(iter(mirror.store._mirror_sources.values()))
        stored.imported_at = mirror.utc_now() - mirror.timedelta(seconds=2)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_origin, "automatic")
        self.assertEqual(promotions.records[0].decision_basis, "expired")
        self.assertEqual(promotions.records[0].override_decision, "allow")
        self.assertEqual(promotions.records[0].promoted_node_ids, [])

    def test_manual_allow_override_does_not_bypass_revoked_source(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        mirror = load_module(
            "registry/main.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )

        source.node_manifest(
            source.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=source.utc_now().isoformat(),
                    key_status="revoked",
                )
            )
        )
        mirror.registry_source_import(
            source.registry_source(SimpleNamespace(base_url="https://ignored.example/")),
            authorization=self.registry_admin_authorization(),
        )
        mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="allow",
                reason="Manual allow must not bypass revoked source",
                set_by="ops",
            ),
            authorization=self.registry_admin_authorization(),
        )

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions(authorization=self.registry_admin_authorization())

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_origin, "automatic")
        self.assertEqual(promotions.records[0].decision_basis, "no_visible_nodes")
        self.assertEqual(promotions.records[0].override_decision, "allow")
        self.assertEqual(promotions.records[0].promoted_node_ids, [])

    def test_directory_hidden_claim_hides_node_without_changing_discover(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True, "can_moderate_directory": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.directory_claim(
            registry.DirectoryClaimRequest(
                node_id=demo.NODE.node_id,
                claims=["hidden"],
                reason="Removed from moderated directory",
                set_by="editorial",
            ),
            authorization=self.registry_admin_authorization(),
        )

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        claims = registry.directory_claims(authorization=self.registry_admin_authorization())

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(discover_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(directory_result.nodes, [])
        self.assertEqual(registry.health()["directory_claim_records"], 1)
        self.assertEqual(registry.health()["active_directory_claims"], 1)
        self.assertEqual(len(claims.records), 1)
        self.assertEqual(claims.records[0].claims, ["hidden"])

    def test_directory_verified_claim_annotates_directory_view(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True, "can_moderate_directory": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.directory_claim(
            registry.DirectoryClaimRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed", "verified"],
                reason="Checked by local trust group",
                set_by="trust-group",
            ),
            authorization=self.registry_admin_authorization(),
        )

        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(len(directory_result.nodes), 1)
        self.assertEqual(directory_result.nodes[0].node_id, demo.NODE.node_id)
        self.assertEqual(directory_result.nodes[0].directory_claims, ["reviewed", "verified"])
        self.assertEqual(directory_result.nodes[0].directory_reason, "Checked by local trust group")
        self.assertEqual(directory_result.nodes[0].directory_set_by, "trust-group")

    def test_directory_local_only_claim_is_hidden_outside_local_scope(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_URL": "https://country.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="country",
                    scope={"country_code": "DK"},
                    capabilities={
                        "can_curate_active_index": True,
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    }
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.directory_claim(
            registry.DirectoryClaimRequest(
                node_id=demo.NODE.node_id,
                claims=["local_only"],
                reason="Keep this node in local directories only",
                set_by="country-curator",
            ),
            authorization=self.registry_admin_authorization(),
        )
        registry.trust_claim_issue(
            registry.TrustClaimIssueRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed"],
                reason="This trust note should stay inactive while the node is local-only here",
            ),
            SimpleNamespace(base_url="https://country.registry.test/"),
            authorization=self.registry_admin_authorization(),
        )

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(directory_result.nodes, [])
        self.assertEqual(registry.health()["directory_claim_records"], 1)
        self.assertEqual(registry.health()["active_directory_claims"], 1)
        self.assertEqual(registry.health()["trust_claim_records"], 1)
        self.assertEqual(registry.health()["active_trust_claims"], 0)

    def test_expired_directory_claim_is_ignored(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True, "can_moderate_directory": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.directory_claim(
            registry.DirectoryClaimRequest(
                node_id=demo.NODE.node_id,
                claims=["hidden"],
                reason="Temporary hide",
                set_by="ops",
                expires_at=registry.utc_now() + registry.timedelta(seconds=1),
            ),
            authorization=self.registry_admin_authorization(),
        )
        stored_claim = registry.store._directory_claims[demo.NODE.node_id]
        stored_claim.expires_at = registry.utc_now() - registry.timedelta(seconds=1)

        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(len(directory_result.nodes), 1)
        self.assertEqual(directory_result.nodes[0].directory_claims, [])

    def test_signed_trust_claim_can_be_issued_imported_and_projected_in_directory(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        issuer = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://issuer.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": issuer_private_key,
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_issue_trust_claims": True}
                ),
            },
        )
        directory = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://directory.registry.test",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_moderate_directory": True}
                ),
            },
        )
        demo = load_module("demo-node/demo_node.py")

        signed_node = demo.sign_node_announcement()
        issuer.announce(issuer.Node(**signed_node))
        directory.announce(directory.Node(**signed_node))

        issued = issuer.trust_claim_issue(
            issuer.TrustClaimIssueRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed"],
                reason="Checked by umbrella trust group",
                expires_at=issuer.utc_now() + issuer.timedelta(days=30),
            ),
            SimpleNamespace(base_url="https://issuer.registry.test/"),
            authorization=self.registry_admin_authorization(),
        )
        imported = directory.trust_claim_import(
            issued.claim,
            authorization=self.registry_admin_authorization(),
        )

        directory_result = directory.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        discover_result = directory.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        trust_claims = directory.trust_claims(authorization=self.registry_admin_authorization())

        self.assertEqual(str(imported.issuer_registry_url), "https://issuer.registry.test/")
        self.assertEqual(imported.node_id, demo.NODE.node_id)
        self.assertEqual(len(directory_result.nodes), 1)
        self.assertEqual(directory_result.nodes[0].trust_claims, ["reviewed"])
        self.assertEqual(
            [str(item) for item in directory_result.nodes[0].trust_claim_issuers],
            ["https://issuer.registry.test/"],
        )
        self.assertNotIn("trust_claims", discover_result.nodes[0].model_dump(mode="json", exclude_none=True))
        self.assertEqual(len(trust_claims.records), 1)
        self.assertEqual(str(trust_claims.records[0].issuer_registry_url), "https://issuer.registry.test/")
        self.assertEqual(directory.health()["trust_claim_records"], 1)
        self.assertEqual(directory.health()["active_trust_claims"], 1)

    def test_health_active_claim_counts_hide_claims_for_nodes_no_longer_current(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    }
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.directory_claim(
            registry.DirectoryClaimRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed"],
                reason="Current node before revoke",
            ),
            authorization=self.registry_admin_authorization(),
        )
        registry.trust_claim_issue(
            registry.TrustClaimIssueRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed"],
            ),
            SimpleNamespace(base_url="https://local.registry.test/"),
            authorization=self.registry_admin_authorization(),
        )

        self.assertEqual(registry.health()["active_directory_claims"], 1)
        self.assertEqual(registry.health()["active_trust_claims"], 1)

        registry.node_manifest(
            registry.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=registry.utc_now().isoformat(),
                    key_status="revoked",
                )
            )
        )

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(directory_result.nodes, [])
        self.assertEqual(registry.health()["directory_claim_records"], 1)
        self.assertEqual(registry.health()["trust_claim_records"], 1)
        self.assertEqual(registry.health()["active_directory_claims"], 0)
        self.assertEqual(registry.health()["active_trust_claims"], 0)

    def test_health_active_claim_counts_hide_claims_for_closed_local_node(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    }
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.directory_claim(
            registry.DirectoryClaimRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed"],
                reason="Current node before close",
            ),
            authorization=self.registry_admin_authorization(),
        )
        registry.trust_claim_issue(
            registry.TrustClaimIssueRequest(
                node_id=demo.NODE.node_id,
                claims=["reviewed"],
            ),
            SimpleNamespace(base_url="https://local.registry.test/"),
            authorization=self.registry_admin_authorization(),
        )

        self.assertEqual(registry.health()["active_directory_claims"], 1)
        self.assertEqual(registry.health()["active_trust_claims"], 1)

        registry.heartbeat(
            registry.HeartbeatRequest(**self.make_signed_heartbeat_payload(demo, open=False))
        )

        discover_result = registry.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        directory_result = registry.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(directory_result.nodes, [])
        self.assertEqual(registry.health()["directory_claim_records"], 1)
        self.assertEqual(registry.health()["trust_claim_records"], 1)
        self.assertEqual(registry.health()["active_directory_claims"], 0)
        self.assertEqual(registry.health()["active_trust_claims"], 0)

    def test_invalid_trust_claim_signature_is_rejected(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        directory = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_moderate_directory": True}
                ),
            },
        )
        demo = load_module("demo-node/demo_node.py")

        directory.announce(directory.Node(**demo.sign_node_announcement()))

        claim_payload = {
            "issuer_registry_url": "https://issuer.registry.test",
            "issuer_registry_public_key": identity.public_key_from_private(issuer_private_key),
            "node_id": demo.NODE.node_id,
            "claims": ["reviewed"],
            "reason": "Original reason",
            "issued_at": directory.utc_now().isoformat(),
            "expires_at": (directory.utc_now() + directory.timedelta(days=7)).isoformat(),
        }
        unsigned = directory.TrustClaimRecord(
            **{
                **claim_payload,
                "signature": "ed25519:pending",
            }
        )
        signature = identity.sign_payload(directory.trust_claim_payload(unsigned), issuer_private_key)
        tampered = directory.TrustClaimRecord(
            **{
                **directory.trust_claim_payload(unsigned),
                "reason": "Tampered after signing",
                "signature": signature,
            }
        )

        with self.assertRaises(HTTPException) as trust_claim_error:
            directory.trust_claim_import(
                tampered,
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(trust_claim_error.exception.status_code, 400)
        self.assertEqual(trust_claim_error.exception.detail, "Invalid trust claim signature")

    def test_imported_trust_claim_requires_current_target_node(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        directory = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_moderate_directory": True}
                ),
            },
        )
        missing_node_id = "dk-missing-pizza-001"

        claim_payload = {
            "issuer_registry_url": "https://issuer.registry.test",
            "issuer_registry_public_key": identity.public_key_from_private(issuer_private_key),
            "node_id": missing_node_id,
            "claims": ["reviewed"],
            "reason": "External claim without current local target",
            "issued_at": directory.utc_now().isoformat(),
            "expires_at": (directory.utc_now() + directory.timedelta(days=7)).isoformat(),
        }
        unsigned = directory.TrustClaimRecord(
            **{
                **claim_payload,
                "signature": "ed25519:pending",
            }
        )
        signed_claim = directory.TrustClaimRecord(
            **{
                **directory.trust_claim_payload(unsigned),
                "signature": identity.sign_payload(
                    directory.trust_claim_payload(unsigned),
                    issuer_private_key,
                ),
            }
        )

        with self.assertRaises(HTTPException) as trust_claim_error:
            directory.trust_claim_import(
                signed_claim,
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(trust_claim_error.exception.status_code, 404)
        self.assertEqual(
            trust_claim_error.exception.detail,
            "Cannot import a trust claim for an unknown node_id",
        )
        self.assertEqual(directory.health()["trust_claim_records"], 0)
        self.assertEqual(directory.health()["active_trust_claims"], 0)

    def test_directory_claim_rejects_closed_local_node_without_current_truth(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_moderate_directory": True}
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.heartbeat(
            registry.HeartbeatRequest(**self.make_signed_heartbeat_payload(demo, open=False))
        )

        with self.assertRaises(HTTPException) as directory_claim_error:
            registry.directory_claim(
                registry.DirectoryClaimRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                    reason="Should fail after close",
                ),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(directory_claim_error.exception.status_code, 404)
        self.assertEqual(
            directory_claim_error.exception.detail,
            "Cannot set a directory claim for an unknown node_id",
        )
        self.assertEqual(registry.health()["directory_claim_records"], 0)
        self.assertEqual(registry.health()["active_directory_claims"], 0)

    def test_trust_claim_issue_rejects_revoked_local_node_without_current_truth(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": issuer_private_key,
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    }
                ),
            },
        )
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.node_manifest(
            registry.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        registry.announce(registry.Node(**demo.sign_node_announcement()))
        registry.node_manifest(
            registry.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=registry.utc_now().isoformat(),
                    key_status="revoked",
                )
            )
        )

        with self.assertRaises(HTTPException) as trust_claim_error:
            registry.trust_claim_issue(
                registry.TrustClaimIssueRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                ),
                SimpleNamespace(base_url="https://local.registry.test/"),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(trust_claim_error.exception.status_code, 404)
        self.assertEqual(
            trust_claim_error.exception.detail,
            "Cannot issue a trust claim for an unknown node_id",
        )
        self.assertEqual(registry.health()["trust_claim_records"], 0)
        self.assertEqual(registry.health()["active_trust_claims"], 0)

    def test_expired_trust_claim_is_ignored_in_directory(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        directory = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_moderate_directory": True}
                ),
            },
        )
        demo = load_module("demo-node/demo_node.py")

        directory.announce(directory.Node(**demo.sign_node_announcement()))

        issued_at = directory.utc_now() - directory.timedelta(days=2)
        expires_at = directory.utc_now() - directory.timedelta(days=1)
        expired_payload = {
            "issuer_registry_url": "https://issuer.registry.test",
            "issuer_registry_public_key": identity.public_key_from_private(issuer_private_key),
            "node_id": demo.NODE.node_id,
            "claims": ["verified"],
            "reason": "Old certification snapshot",
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        unsigned = directory.TrustClaimRecord(
            **{
                **expired_payload,
                "signature": "ed25519:pending",
            }
        )
        expired_claim = directory.TrustClaimRecord(
            **{
                **directory.trust_claim_payload(unsigned),
                "signature": identity.sign_payload(
                    directory.trust_claim_payload(unsigned),
                    issuer_private_key,
                ),
            }
        )

        directory.trust_claim_import(
            expired_claim,
            authorization=self.registry_admin_authorization(),
        )
        directory_result = directory.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        trust_claims = directory.trust_claims(authorization=self.registry_admin_authorization())

        self.assertEqual(len(directory_result.nodes), 1)
        self.assertEqual(directory_result.nodes[0].trust_claims, [])
        self.assertEqual(len(trust_claims.records), 1)

    def test_trust_claim_issue_requires_can_issue_trust_claims(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": issuer_private_key,
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(),
            },
        )
        demo = load_module("demo-node/demo_node.py")

        registry.announce(registry.Node(**demo.sign_node_announcement()))

        with self.assertRaises(HTTPException) as trust_claim_error:
            registry.trust_claim_issue(
                registry.TrustClaimIssueRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                ),
                SimpleNamespace(base_url="https://local.registry.test/"),
                authorization=self.registry_admin_authorization(),
            )

        self.assertEqual(trust_claim_error.exception.status_code, 403)
        self.assertEqual(
            trust_claim_error.exception.detail,
            "This registry is not allowed to issue signed trust claims",
        )

    def test_registry_admin_write_routes_require_admin_token(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_relay_sources": True,
                        "can_curate_active_index": True,
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    },
                ),
            },
        )
        demo = load_module("demo-node/demo_node.py")

        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        with self.assertRaises(HTTPException) as import_error:
            registry.registry_source_import(snapshot)
        with self.assertRaises(HTTPException) as import_wrong_error:
            registry.registry_source_import(snapshot, authorization="Bearer wrong-secret")
        with self.assertRaises(HTTPException) as override_error:
            registry.curated_override(
                registry.CuratedOverrideRequest(
                    source_registry_url="https://registry-a.pizza4people.com",
                    decision="deny",
                    reason="Unauthorized test",
                )
            )
        with self.assertRaises(HTTPException) as directory_claim_error:
            registry.directory_claim(
                registry.DirectoryClaimRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                    reason="Unauthorized test",
                )
            )
        with self.assertRaises(HTTPException) as trust_claim_error:
            registry.trust_claim_issue(
                registry.TrustClaimIssueRequest(node_id=demo.NODE.node_id, claims=["reviewed"]),
                SimpleNamespace(base_url="https://local.registry.test/"),
            )
        with self.assertRaises(HTTPException) as sync_error:
            asyncio.run(registry.registry_sync())

        self.assertEqual(import_error.exception.status_code, 401)
        self.assertEqual(import_wrong_error.exception.status_code, 401)
        self.assertEqual(override_error.exception.status_code, 401)
        self.assertEqual(directory_claim_error.exception.status_code, 401)
        self.assertEqual(trust_claim_error.exception.status_code, 401)
        self.assertEqual(sync_error.exception.status_code, 401)

    def test_registry_admin_write_routes_fail_closed_without_configured_token(self) -> None:
        identity = load_module("p4p_identity.py")
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True},
                ),
            },
        )
        demo = load_module("demo-node/demo_node.py")

        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        with self.assertRaises(HTTPException) as import_error:
            registry.registry_source_import(snapshot)
        with self.assertRaises(HTTPException) as override_error:
            registry.curated_override(
                registry.CuratedOverrideRequest(
                    source_registry_url="https://registry-a.pizza4people.com",
                    decision="deny",
                    reason="Token missing",
                )
            )

        self.assertEqual(import_error.exception.status_code, 503)
        self.assertEqual(import_error.exception.detail, "Registry admin token is not configured")
        self.assertEqual(override_error.exception.status_code, 503)
        self.assertEqual(override_error.exception.detail, "Registry admin token is not configured")

    def test_registry_admin_read_routes_require_admin_token(self) -> None:
        registry = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_curate_active_index": True,
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    },
                ),
            },
        )

        read_calls = (
            lambda: registry.registry_mirrors(),
            lambda: registry.curated_promotions(),
            lambda: registry.curated_overrides(),
            lambda: registry.directory_claims(),
            lambda: registry.trust_claims(),
            lambda: registry.registry_sync_status(),
        )
        for call in read_calls:
            with self.assertRaises(HTTPException) as read_error:
                call()
            self.assertEqual(read_error.exception.status_code, 401)
            self.assertEqual(read_error.exception.detail, "Invalid registry admin token")

        self.assertEqual(
            registry.registry_mirrors(authorization=self.registry_admin_authorization()).sources,
            [],
        )
        self.assertEqual(
            registry.registry_sync_status(authorization=self.registry_admin_authorization()).last_results,
            [],
        )

    def test_registry_admin_read_routes_fail_closed_without_configured_token(self) -> None:
        registry = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": True},
                ),
            },
        )

        with self.assertRaises(HTTPException) as promotions_error:
            registry.curated_promotions()
        with self.assertRaises(HTTPException) as sync_status_error:
            registry.registry_sync_status()

        self.assertEqual(promotions_error.exception.status_code, 503)
        self.assertEqual(promotions_error.exception.detail, "Registry admin token is not configured")
        self.assertEqual(sync_status_error.exception.status_code, 503)
        self.assertEqual(sync_status_error.exception.detail, "Registry admin token is not configured")

    def test_registry_http_public_surfaces_stay_open_while_admin_reads_require_token(self) -> None:
        identity = load_module("p4p_identity.py")
        registry_app = load_module(
            "registry/registry_app.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                "P4P_REGISTRY_DB_PATH": ":memory:",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_curate_active_index": True,
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    },
                ),
            },
        )

        with TestClient(registry_app.app) as client:
            health = client.get("/health")
            identity_log = client.get("/identity-log")
            registry_source = client.get("/registry-source")
            registry_info = client.get("/registry-info")
            admin_read = client.get("/registry-mirrors")
            admin_read_ok = client.get(
                "/registry-mirrors",
                headers={"Authorization": self.registry_admin_authorization()},
            )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(identity_log.status_code, 200)
        self.assertIn("records", identity_log.json())
        self.assertEqual(registry_source.status_code, 200)
        self.assertIn("registry_url", registry_source.json())
        self.assertEqual(registry_info.status_code, 200)
        self.assertEqual(admin_read.status_code, 401)
        self.assertEqual(admin_read.json()["detail"], "Invalid registry admin token")
        self.assertEqual(admin_read_ok.status_code, 200)
        self.assertEqual(admin_read_ok.json()["sources"], [])

    def test_registry_http_signed_outputs_require_configured_registry_url(self) -> None:
        identity = load_module("p4p_identity.py")
        registry_app = load_module(
            "registry/registry_app.py",
            {
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                "P4P_REGISTRY_DB_PATH": ":memory:",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_issue_trust_claims": True},
                ),
            },
        )

        with TestClient(registry_app.app) as client:
            registry_source = client.get(
                "/registry-source",
                headers={"Host": "spoofed.example"},
            )
            trust_claim_issue = client.post(
                "/trust-claims",
                headers={
                    "Authorization": self.registry_admin_authorization(),
                    "Host": "spoofed.example",
                },
                json={
                    "node_id": "dk-test-001",
                    "claims": ["reviewed"],
                },
            )

        self.assertEqual(registry_source.status_code, 503)
        self.assertEqual(
            registry_source.json()["detail"],
            "Signed registry source export requires P4P_REGISTRY_URL",
        )
        self.assertEqual(trust_claim_issue.status_code, 503)
        self.assertEqual(
            trust_claim_issue.json()["detail"],
            "Signed trust claim issuance requires P4P_REGISTRY_URL",
        )

    def test_registry_http_unsigned_registry_source_export_rejects_public_host_fallback(self) -> None:
        registry_app = load_module(
            "registry/registry_app.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                "P4P_REGISTRY_DB_PATH": ":memory:",
            },
        )

        with TestClient(registry_app.app) as client:
            registry_source = client.get(
                "/registry-source",
                headers={"Host": "spoofed.example"},
            )

        self.assertEqual(registry_source.status_code, 503)
        self.assertEqual(
            registry_source.json()["detail"],
            "Unsigned registry source export without P4P_REGISTRY_URL requires a loopback request base",
        )

    def test_registry_http_loopback_self_import_is_rejected_without_canonical_url(self) -> None:
        registry_app = load_module(
            "registry/registry_app.py",
            {
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                "P4P_REGISTRY_DB_PATH": ":memory:",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )

        with TestClient(registry_app.app) as client:
            registry_source = client.get(
                "/registry-source",
                headers={"Host": "127.0.0.1:8001"},
            )
            self_import = client.post(
                "/registry-source/import",
                headers={
                    "Authorization": self.registry_admin_authorization(),
                    "Host": "127.0.0.1:8001",
                },
                json=registry_source.json(),
            )

        self.assertEqual(registry_source.status_code, 200)
        self.assertEqual(self_import.status_code, 409)
        self.assertEqual(
            self_import.json()["detail"],
            "Registry cannot import its own source snapshot",
        )

    def test_registry_app_startup_stays_hermetic_when_mirror_interval_is_zero(self) -> None:
        identity = load_module("p4p_identity.py")
        registry_app = load_module(
            "registry/registry_app.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "https://registry-a.pizza4people.com",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                "P4P_REGISTRY_DB_PATH": ":memory:",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_relay_sources": True},
                ),
            },
        )

        def fail_async_client(*args, **kwargs):
            raise AssertionError("Mirror sync should not start automatically when interval is 0")

        with patch.object(registry_app.httpx, "AsyncClient", new=fail_async_client):
            with TestClient(registry_app.app) as client:
                health = client.get("/health")
                sync_status = client.get(
                    "/registry-sync",
                    headers={"Authorization": self.registry_admin_authorization()},
                )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(sync_status.status_code, 200)
        self.assertEqual(sync_status.json()["last_results"], [])

    def test_registry_http_admin_token_headers_work_for_write_and_read_routes(self) -> None:
        identity = load_module("p4p_identity.py")
        registry_app = load_module(
            "registry/registry_app.py",
            {
                "P4P_REGISTRY_URL": "https://local.registry.test",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_MIRROR_UPSTREAMS": "",
                "P4P_MIRROR_TRUSTED_UPSTREAMS": "",
                "P4P_MIRROR_SYNC_INTERVAL_SECONDS": "0",
                "P4P_REGISTRY_DB_PATH": ":memory:",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_relay_sources": True,
                        "can_curate_active_index": True,
                        "can_moderate_directory": True,
                        "can_issue_trust_claims": True,
                    },
                ),
            },
        )

        with TestClient(registry_app.app) as client:
            blocked_sync = client.post("/registry-sync")
            sync_via_token_header = client.post(
                "/registry-sync",
                headers={"X-P4P-Registry-Token": "registry-admin-secret"},
            )
            sync_status_via_bearer = client.get(
                "/registry-sync",
                headers={"Authorization": self.registry_admin_authorization()},
            )

        self.assertEqual(blocked_sync.status_code, 401)
        self.assertEqual(blocked_sync.json()["detail"], "Invalid registry admin token")
        self.assertEqual(sync_via_token_header.status_code, 200)
        self.assertEqual(sync_via_token_header.json()["upstreams"], [])
        self.assertEqual(sync_status_via_bearer.status_code, 200)
        self.assertEqual(sync_status_via_bearer.json()["last_results"], [])

    def test_scope_and_capability_gating_blocks_onboard_relay_and_reexport(self) -> None:
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )
        source = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://registry-a.pizza4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
            },
        )
        locked_onboard = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="country",
                    scope={"country_code": "DK"},
                    capabilities={"can_onboard_nodes": False},
                )
            },
        )
        locked_relay = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="vertical",
                    scope={"vertical_id": "pizza4people"},
                    capabilities={"can_relay_sources": False},
                )
            },
        )
        locked_reexport = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://umbrella.protocols4people.com",
                "P4P_REGISTRY_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_REGISTRY_SOURCE_REEXPORT_POLICY": "local_plus_trusted_mirrors",
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="umbrella",
                    capabilities={"can_reexport_sources": False},
                ),
            },
        )
        locked_curate = load_module(
            "registry/main.py",
            {
                "P4P_CURATED_INDEX_PROMOTION_POLICY": "trusted_mirrors",
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": False},
                ),
            },
        )
        locked_moderation = load_module(
            "registry/main.py",
            {
                **self.make_registry_admin_env(),
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={
                        "can_curate_active_index": True,
                        "can_moderate_directory": False,
                    },
                ),
            },
        )

        source.node_manifest(
            source.NodeManifestRequest(**self.make_node_manifest_request(demo, manifest_version=1))
        )
        source.announce(source.Node(**demo.sign_node_announcement()))
        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        with self.assertRaises(HTTPException) as onboard_error:
            locked_onboard.announce(locked_onboard.Node(**demo.sign_node_announcement()))
        with self.assertRaises(HTTPException) as relay_error:
            locked_relay.registry_source_import(
                snapshot,
                authorization=self.registry_admin_authorization(),
            )
        with self.assertRaises(HTTPException) as reexport_error:
            locked_reexport.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        locked_curate.registry_source_import(
            snapshot,
            authorization=self.registry_admin_authorization(),
        )
        with self.assertRaises(HTTPException) as override_error:
            locked_curate.curated_override(
                locked_curate.CuratedOverrideRequest(
                    source_registry_url="https://registry-a.pizza4people.com",
                    decision="allow",
                    reason="Not allowed here",
                ),
                authorization=self.registry_admin_authorization(),
            )
        with self.assertRaises(HTTPException) as directory_claim_error:
            locked_moderation.directory_claim(
                locked_moderation.DirectoryClaimRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                    reason="Not allowed here either",
                ),
                authorization=self.registry_admin_authorization(),
            )
        curated_result = locked_curate.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(onboard_error.exception.status_code, 403)
        self.assertEqual(onboard_error.exception.detail, "This registry is not allowed to onboard nodes")
        self.assertEqual(relay_error.exception.status_code, 403)
        self.assertEqual(relay_error.exception.detail, "This registry is not allowed to relay upstream sources")
        self.assertEqual(reexport_error.exception.status_code, 403)
        self.assertEqual(reexport_error.exception.detail, "This registry is not allowed to re-export sources")
        self.assertEqual(override_error.exception.status_code, 403)
        self.assertEqual(
            override_error.exception.detail,
            "This registry is not allowed to curate a discoverable active index",
        )
        self.assertEqual(directory_claim_error.exception.status_code, 403)
        self.assertEqual(
            directory_claim_error.exception.detail,
            "This registry is not allowed to moderate a public directory",
        )
        self.assertEqual(curated_result.nodes, [])
        self.assertEqual(locked_curate.health()["curated_active_index_entries"], 0)
        self.assertEqual(
            locked_curate.curated_promotions(authorization=self.registry_admin_authorization()).records[0].decision_basis,
            "curation_disabled",
        )

    def test_identity_log_ignores_unsigned_legacy_nodes(self) -> None:
        registry = load_module("registry/main.py")

        registry.announce(
            registry.Node(
                node_id="dk-brondby-legacy-001",
                name="Legacy Pizzeria",
                location=registry.Location(lat=55.6517, lng=12.4126),
                country="DK",
                city="Brondby",
                categories=["pizza"],
                endpoint="http://127.0.0.1:8101/p4p",
                open=True,
                modules=[],
                protocol_version="0.1",
            )
        )

        log = registry.identity_log()

        self.assertEqual(log.records, [])
        self.assertEqual(log.events, [])

    def test_signed_heartbeat_rejects_tampering(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))
        heartbeat = demo.signed_heartbeat_payload()
        registry.heartbeat(registry.HeartbeatRequest(**heartbeat))

        tampered_heartbeat = dict(heartbeat)
        tampered_heartbeat["open"] = not heartbeat["open"]

        with self.assertRaises(HTTPException) as tampered_error:
            registry.heartbeat(registry.HeartbeatRequest(**tampered_heartbeat))

        self.assertEqual(tampered_error.exception.status_code, 400)

    def test_delegation_capabilities_apply_to_heartbeat(self) -> None:
        registry = load_module("registry/main.py")
        identity = load_module("p4p_identity.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_ROOT_PRIVATE_KEY": identity.generate_private_key(),
                "P4P_NODE_DELEGATION_CAPABILITIES": "announce",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        registry.announce(registry.Node(**demo.sign_node_announcement()))

        with self.assertRaises(HTTPException) as heartbeat_error:
            registry.heartbeat(registry.HeartbeatRequest(**demo.signed_heartbeat_payload()))

        self.assertEqual(heartbeat_error.exception.status_code, 403)
        self.assertEqual(heartbeat_error.exception.detail, "Delegation does not allow heartbeat")

    def test_signed_heartbeat_rejects_replayed_older_state(self) -> None:
        registry = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        base_time = demo.utc_now()
        registry.announce(
            registry.Node(
                **self.make_signed_node_payload(
                    demo,
                    signed_at=(base_time - demo.timedelta(seconds=3)).isoformat(),
                )
            )
        )
        first_heartbeat = self.make_signed_heartbeat_payload(
            demo,
            signed_at=(base_time - demo.timedelta(seconds=2)).isoformat(),
        )
        newer_heartbeat = self.make_signed_heartbeat_payload(
            demo,
            open=False,
            signed_at=(base_time - demo.timedelta(seconds=1)).isoformat(),
        )

        registry.heartbeat(registry.HeartbeatRequest(**first_heartbeat))
        registry.heartbeat(registry.HeartbeatRequest(**newer_heartbeat))

        with self.assertRaises(HTTPException) as replay_error:
            registry.heartbeat(registry.HeartbeatRequest(**first_heartbeat))

        self.assertEqual(replay_error.exception.status_code, 409)

    def test_operator_can_change_node_state_and_reannounce(self) -> None:
        primary = load_module("registry/main.py")
        backup = load_module("registry/main.py")
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_REGISTRY_URLS": "http://primary-registry.test,http://backup-registry.test",
                "P4P_NODE_MODULES": "p4p.payment.cash",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )
        routes = {
            "http://primary-registry.test": primary,
            "http://backup-registry.test": backup,
        }

        update = demo.OperatorStateUpdate(
            open=True,
            order_mode="menu_only",
            modules=["p4p.payment.cash", " p4p.trust.cvr ", "p4p.payment.cash", ""],
        )

        with patch.object(demo.httpx, "AsyncClient", new=lambda *args, **kwargs: RegistryBridgeAsyncClient(routes)):
            state = asyncio.run(demo.operator_update_state(update))

        self.assertTrue(demo.NODE.open)
        self.assertEqual(demo.NODE.order_mode, "menu_only")
        self.assertEqual(demo.NODE.modules, ["p4p.payment.cash", "p4p.trust.cvr"])
        self.assertFalse(state["accepts_orders"])
        self.assertEqual(
            state["registry"]["registered_registries"],
            ["http://primary-registry.test", "http://backup-registry.test"],
        )

        primary_result = primary.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        backup_result = backup.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(primary_result.nodes[0].order_mode, "menu_only")
        self.assertEqual(backup_result.nodes[0].modules, ["p4p.payment.cash", "p4p.trust.cvr"])

    def test_operator_can_be_disabled_for_public_proof(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_OPERATOR_ENABLED": "false",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        with self.assertRaises(HTTPException) as operator_error:
            demo.operator()

        self.assertEqual(operator_error.exception.status_code, 404)
        self.assertIsNone(demo.info()["operator_url"])

    def test_health_returns_503_when_no_registry_cycle_succeeds(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_REGISTRY_URLS": "http://primary-registry.test,http://backup-registry.test",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        with patch.object(demo.httpx, "AsyncClient", new=lambda *args, **kwargs: FailingAsyncClient()):
            asyncio.run(demo.run_registry_cycle(force_announce=True))

        response = Response()
        health = demo.health(response)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(health["status"], "not_ready")
        self.assertEqual(health["registered_registries"], [])
        self.assertEqual(
            set(health["failed_registries"]),
            {"http://primary-registry.test", "http://backup-registry.test"},
        )

    def test_lab_status_marks_running_but_unready_nodes_as_unusable(self) -> None:
        lab = load_module("lab/app.py")
        manager = lab.ProcessManager()

        class FakeProcess:
            pid = 4242

            def poll(self):
                return None

        service = lab.ManagedProcess(
            name="node-1",
            port=8101,
            kind="node",
            cwd=Path("."),
            command=["python"],
            env={},
        )
        service.process = FakeProcess()
        service.started_at = 1.0
        manager._services[service.name] = service

        with patch.object(
            manager,
            "_probe_node_health",
            return_value=(
                False,
                503,
                {
                    "status": "not_ready",
                    "configured_registries": ["http://primary-registry.test"],
                    "registered_registries": [],
                    "failed_registries": {"http://primary-registry.test": "registry unavailable"},
                },
            ),
        ):
            status = manager.status()

        node_status = status["services"][0]
        self.assertTrue(node_status["running"])
        self.assertFalse(node_status["usable"])
        self.assertEqual(node_status["operator_url"], "http://127.0.0.1:8101/operator")
        self.assertEqual(node_status["health_status_code"], 503)
        self.assertEqual(node_status["health"]["status"], "not_ready")

    def test_lab_client_server_targets_client_root_and_root_link(self) -> None:
        lab = load_module("lab/app.py")
        manager = lab.ProcessManager()

        with patch.object(manager, "_spawn", side_effect=lambda service: service) as spawn:
            service = manager.start_client_server()

        spawn.assert_called_once()
        self.assertEqual(service.cwd, lab.CLIENT_ROOT)
        self.assertEqual(
            service.command,
            [sys.executable, "-m", "http.server", "8765", "--directory", str(lab.CLIENT_ROOT)],
        )
        self.assertEqual(lab.links()["client"], "http://127.0.0.1:8765/")
        self.assertEqual(
            lab.links()["primary_directory"],
            "http://127.0.0.1:8000/directory?lat=55.6517&lng=12.4126&radius=50",
        )
        self.assertEqual(
            lab.links()["backup_directory"],
            "http://127.0.0.1:8002/directory?lat=55.6517&lng=12.4126&radius=50",
        )

    def test_lab_nodes_advertise_reference_cash_module(self) -> None:
        lab = load_module("lab/app.py")
        manager = lab.ProcessManager()

        with patch.object(manager, "_spawn", side_effect=lambda service: service) as spawn:
            service = manager.start_node(name="node-1", port=8101, node_index=1)

        spawn.assert_called_once()
        self.assertEqual(service.env["P4P_NODE_KEY_FILE"], "/tmp/p4p-lab-node-001-identity.json")
        self.assertEqual(service.env["P4P_NODE_ROOT_KEY_FILE"], "/tmp/p4p-lab-node-001-root.json")
        self.assertEqual(service.env["P4P_NODE_DELEGATION_ROLE"], "primary")
        self.assertEqual(service.env["P4P_NODE_MODULES"], "p4p.payment.cash")
        self.assertEqual(service.env["P4P_NODE_ORDER_MODE"], "test")

    def test_lab_projection_includes_profiles_fixtures_flows_and_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            projection = lab.scenario_projection(config)

        self.assertEqual(projection["version"], "0.2-lab-v2")
        self.assertIn("secondary-registry", projection["services"])
        self.assertIn("registry_profiles", projection)
        self.assertIn("node_profiles", projection)
        self.assertIn("node_templates", projection)
        self.assertIn("node_instances", projection)
        self.assertIn("customer_fixtures", projection)
        self.assertIn("customer_fixture_instances", projection)
        self.assertIn("flow_scenarios", projection)
        self.assertIn("legacy_scenarios", projection)
        self.assertEqual(projection["registry_profiles"][0]["id"], "main-open")
        self.assertEqual(projection["node_profiles"][0]["id"], "pizza-shop")
        self.assertEqual(projection["node_templates"][0]["id"], "pizza-shop")
        self.assertEqual(projection["node_instances"][0]["id"], "pizza-shop")
        self.assertEqual(
            projection["node_profiles"][0]["public_shop_url"],
            "http://127.0.0.1:8595/p4p/menu/list",
        )
        self.assertEqual(projection["customer_fixtures"][0]["id"], "pickup-basic")
        self.assertEqual(projection["customer_fixture_instances"], [])
        self.assertEqual(projection["flow_scenarios"][0]["id"], "single-pizza-order")
        self.assertEqual(projection["legacy_scenarios"][0]["id"], "pilot-photo-map-menu")

    def test_lab_topology_projection_attaches_registry_lanes_templates_and_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            projection = lab.topology_projection(config)

        self.assertIn("registry_profiles", projection)
        self.assertEqual(projection["registry_profiles"][0]["id"], "main-open")
        self.assertEqual(projection["registry_profiles"][1]["id"], "main-open-backup")
        main_open = next(item for item in projection["registry_profiles"] if item["id"] == "main-open")
        dk_curated = next(item for item in projection["registry_profiles"] if item["id"] == "dk-p4p-curated")
        main_backup = next(item for item in projection["registry_profiles"] if item["id"] == "main-open-backup")

        self.assertEqual(main_open["service"]["name"], "primary-registry")
        self.assertEqual(main_open["service"]["port"], 8000)
        self.assertEqual(dk_curated["service"]["name"], "secondary-registry")
        self.assertEqual(dk_curated["curation_mode"], "curated")
        self.assertEqual(main_backup["backup_for"], "main-open")
        self.assertIn("Registry info", {link["label"] for link in main_open["layer_links"]})
        self.assertIn("pizza-shop", {item["id"] for item in main_open["attached_node_templates"]})
        self.assertIn("pizza-shop", {item["id"] for item in main_open["attached_node_instances"]})
        self.assertTrue(next(item for item in main_open["attached_node_templates"] if item["id"] == "pizza-shop")["registry_targeted"])
        self.assertTrue(next(item for item in dk_curated["attached_node_templates"] if item["id"] == "pizza-shop")["visibility_expected"])
        self.assertEqual(next(item for item in main_open["attached_node_instances"] if item["id"] == "pizza-shop")["public_surface_key"], "public_shop")
        self.assertTrue(any(profile["id"] == "main-open" for profile in dk_curated["upstream_profiles"]))

    def test_lab_registry_profile_overrides_feed_scenario_and_topology_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            override = lab.state_store.update_registry_profile_override(
                config=config,
                profile_id="dk-p4p-curated",
                title="DK Pizza4People Curated Lane",
                description="Local curated lane for Danish Pizza4People testing.",
                upstreams=["main-open-backup"],
                announce_policy="approval-before-lane",
                discover_policy="filtered-local-priority",
                notes=["Local test curation only.", "Does not rewrite registry runtime."],
            )

            scenario = lab.scenario_projection(config)
            topology = lab.topology_projection(config)

        self.assertEqual(override["profile_id"], "dk-p4p-curated")
        self.assertEqual(override["upstreams"], ["main-open-backup"])
        scenario_profile = next(item for item in scenario["registry_profiles"] if item["id"] == "dk-p4p-curated")
        self.assertTrue(scenario_profile["override_active"])
        self.assertEqual(scenario_profile["title"], "DK Pizza4People Curated Lane")
        self.assertEqual(scenario_profile["announce_policy"], "approval-before-lane")
        self.assertEqual(scenario_profile["discover_policy"], "filtered-local-priority")
        self.assertEqual(scenario_profile["upstreams"], ["main-open-backup"])
        self.assertEqual(scenario_profile["notes"][0], "Local test curation only.")
        topology_profile = next(item for item in topology["registry_profiles"] if item["id"] == "dk-p4p-curated")
        self.assertTrue(topology_profile["override_active"])
        self.assertEqual(topology_profile["upstream_profiles"][0]["id"], "main-open-backup")

    def test_lab_can_create_registry_lane_instance_and_target_it_from_generated_node_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            lane = lab.state_store.create_registry_lane_instance(
                config=config,
                template=config.registry_profiles["dk-p4p-curated"],
                instance_id="dk-curated-local-001",
                title="DK Curated Local 001",
                description="Generated curated lane for local testing.",
                notes=["Starts as a local generated lane."],
            )
            self.assertEqual(lane["template_id"], "dk-p4p-curated")
            self.assertEqual(lane["service_name"], "registry-lane-dk-curated-local-001")
            self.assertGreaterEqual(lane["port"], 8010)
            self.assertEqual(lane["launch_mode"], "generated_lane")

            updated_lane = lab.state_store.update_registry_lane_instance(
                config=config,
                instance_id="dk-curated-local-001",
                title="DK Curated Local 001",
                description="Generated curated lane for topology tests.",
                upstreams=["main-open-backup"],
                announce_policy="approval-before-lane",
                discover_policy="filtered-local-priority",
                notes=["Curated local lane."],
            )
            self.assertEqual(updated_lane["upstreams"], ["main-open-backup"])
            self.assertEqual(updated_lane["announce_policy"], "approval-before-lane")

            created_instance = lab.state_store.create_node_instance(
                config=config,
                template=config.node_profiles["pizza-shop"],
                instance_id="pizza-shop-curated-001",
                title="Pizza Shop Curated 001",
                description="Generated node instance for registry-lane targeting.",
                notes="",
            )
            self.assertEqual(created_instance["launch_mode"], "generated_instance")

            node_instance = lab.state_store.update_node_instance(
                config=config,
                instance_id="pizza-shop-curated-001",
                title="Pizza Shop Curated 001",
                description="Generated runtime instance with local targeting.",
                notes="",
                registry_targets=["main-open", "dk-curated-local-001"],
                visibility_expectations=["dk-p4p-curated", "dk-curated-local-001"],
                module_ids=["p4p.menu.list", "p4p.payment.cash"],
                menu_seed={"items": []},
                node_id="pizza-shop-curated-001",
                city="Brondby",
                country="DK",
                categories=["pizza"],
                order_mode="menu_only",
                public_surface_key="public_shop",
            )
            self.assertIn("dk-curated-local-001", node_instance["registry_targets"])

            definition = lab._build_node_instance_service_definition(config, node_instance)
            self.assertIn(
                f"http://127.0.0.1:{updated_lane['port']}",
                definition.env["P4P_REGISTRY_URLS"],
            )

            topology = lab.topology_projection(config)
            generated_lane = next(item for item in topology["registry_profiles"] if item["id"] == "dk-curated-local-001")
            self.assertTrue(generated_lane["generated"])
            self.assertEqual(generated_lane["service"]["port"], updated_lane["port"])
            self.assertEqual(generated_lane["upstream_profiles"][0]["id"], "main-open-backup")
            self.assertIn("pizza-shop-curated-001", {item["id"] for item in generated_lane["attached_node_instances"]})

    def test_lab_state_store_seeds_and_creates_node_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            seeded = lab.state_store.list_node_instances()
            self.assertIn("pizza-shop", {item["id"] for item in seeded})
            self.assertTrue(next(item for item in seeded if item["id"] == "pizza-shop")["launchable_now"])

            created = lab.state_store.create_node_instance(
                config=config,
                template=config.node_profiles["pizza-shop"],
                instance_id="pizza-shop-custom-001",
                title="Custom Pizza Draft",
                description="Generated instance for runtime launch.",
                notes="Saved through state store.",
            )

            self.assertEqual(created["template_id"], "pizza-shop")
            self.assertTrue(created["launchable_now"])
            self.assertEqual(created["launch_mode"], "generated_instance")
            self.assertEqual(created["service_name"], "instance-pizza-shop-custom-001")
            self.assertEqual(created["node_id"], "pizza-shop-custom-001")
            self.assertEqual(created["city"], "Brondby")
            self.assertEqual(created["country"], "DK")
            self.assertEqual(created["categories"], ["pizza"])
            self.assertEqual(created["order_mode"], "live")
            self.assertEqual(created["public_surface_key"], "public_shop")
            self.assertEqual(created["operator_token"], "lab-pizza-shop-custom-001")
            self.assertIn("p4p.catalog.editor", created["module_ids"])
            self.assertEqual(created["menu_seed"]["currency"], "DKK")
            self.assertEqual(created["menu_seed"]["items"][0]["id"], "margherita")
            self.assertIsInstance(created["port"], int)
            self.assertGreaterEqual(created["port"], 8700)
            self.assertIn("pizza-shop-custom-001", {item["id"] for item in lab.state_store.list_node_instances()})

            updated = lab.state_store.update_node_instance(
                config=config,
                instance_id="pizza-shop-custom-001",
                title="Custom Pizza DK Curated",
                description="Updated generated instance.",
                notes="Owns its own lane choices now.",
                registry_targets=["dk-p4p-curated"],
                visibility_expectations=["dk-p4p-curated", "main-open"],
                module_ids=["p4p.menu.list", "p4p.customer.status"],
                menu_seed={
                    "currency": "DKK",
                    "items": [
                        {
                            "id": "lab-special",
                            "name": "Lab Special",
                            "description": "Instance-owned menu item.",
                            "category": "pizza",
                            "price_minor": 9900,
                            "image_url": "",
                        }
                    ],
                },
                node_id="dk-custom-pizza-001",
                city="Copenhagen",
                country="dk",
                categories=["pizza", "late-night"],
                order_mode="test",
                public_surface_key="menu_json",
            )

            self.assertEqual(updated["title"], "Custom Pizza DK Curated")
            self.assertEqual(updated["node_id"], "dk-custom-pizza-001")
            self.assertEqual(updated["city"], "Copenhagen")
            self.assertEqual(updated["country"], "DK")
            self.assertEqual(updated["categories"], ["pizza", "late-night"])
            self.assertEqual(updated["order_mode"], "test")
            self.assertEqual(updated["public_surface_key"], "menu_json")
            self.assertEqual(updated["registry_targets"], ["dk-p4p-curated"])
            self.assertEqual(updated["visibility_expectations"], ["dk-p4p-curated", "main-open"])
            self.assertEqual(updated["module_ids"], ["p4p.menu.list", "p4p.customer.status"])
            self.assertEqual(updated["menu_seed"]["items"][0]["id"], "lab-special")
            self.assertEqual(updated["public_shop_url"], updated["customer_urls"]["menu_json"])

    def test_lab_server_inventory_projects_ports_layers_and_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            inventory = lab.server_inventory_projection(config)

        servers = {item["name"]: item for item in inventory["servers"]}
        pizza_server = servers["pilot-pizza-shop"]
        self.assertEqual(pizza_server["port"], 8595)
        self.assertEqual(pizza_server["attached_node_templates"][0]["id"], "pizza-shop")
        self.assertIn("pizza-shop", {item["id"] for item in pizza_server["attached_node_instances"]})
        self.assertIn("pizza-shop public shop", {link["label"] for link in pizza_server["layer_links"]})
        group_ids = {group["id"] for group in inventory["groups"]}
        self.assertEqual(group_ids, {"registry-stack", "node-runtimes", "live-layers"})
        registry_group = next(group for group in inventory["groups"] if group["id"] == "registry-stack")
        self.assertIn("primary-registry", registry_group["service_names"])
        self.assertEqual([action["id"] for action in registry_group["actions"]], ["start", "stop", "restart", "recover"])
        node_group = next(group for group in inventory["groups"] if group["id"] == "node-runtimes")
        self.assertIn("pilot-pizza-shop", node_group["service_names"])
        self.assertTrue(node_group["truth_owner_stories"])
        self.assertIn("Seeded node template Pizza shop", node_group["truth_owner_stories"])
        live_group = next(group for group in inventory["groups"] if group["id"] == "live-layers")
        self.assertFalse(live_group["actions"])
        self.assertTrue(live_group["links"])
        self.assertEqual(pizza_server["action_target"]["type"], "service")
        self.assertIn("primary-registry", pizza_server["dependency_service_names"])
        self.assertEqual(pizza_server["binding"]["kind"], "node-template")
        self.assertFalse(pizza_server["binding"]["can_rebind"])
        self.assertTrue(node_group["plan"]["dependencies_first"])
        self.assertIn("primary-registry", node_group["plan"]["start_order"])
        self.assertIn("pilot-pizza-shop", node_group["plan"]["start_order"])
        self.assertIn("pilot-pizza-shop", node_group["plan"]["stop_order"])
        self.assertEqual(node_group["plan"]["rebind_owner_stories"], [])

    def test_lab_control_rooms_projection_turns_server_groups_into_room_stories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            projection = lab.control_rooms_projection(config)

        room_ids = {room["id"] for room in projection["rooms"]}
        self.assertEqual(room_ids, {"registry-stack", "node-runtimes", "live-layers"})
        self.assertEqual(projection["summary"]["room_count"], 3)
        self.assertEqual(projection["summary"]["actionable_room_count"], 2)
        self.assertEqual(projection["summary"]["dependency_room_count"], 2)

        registry_room = next(room for room in projection["rooms"] if room["id"] == "registry-stack")
        self.assertEqual(registry_room["kind"], "registry-room")
        self.assertTrue(registry_room["actionable"])
        self.assertIn("discovery backbone", registry_room["room_story"])
        self.assertIn("Bring this room up in order", registry_room["start_story"])

        node_room = next(room for room in projection["rooms"] if room["id"] == "node-runtimes")
        self.assertEqual(node_room["kind"], "runtime-room")
        self.assertIn("operator and public shop lanes", node_room["room_story"])
        self.assertTrue(node_room["truth_owner_stories"])
        self.assertIn("Seeded node template Pizza shop", node_room["truth_owner_stories"])

        live_room = next(room for room in projection["rooms"] if room["id"] == "live-layers")
        self.assertEqual(live_room["kind"], "reading-room")
        self.assertFalse(live_room["actionable"])
        self.assertIn("does not start anything directly", live_room["start_story"])
        self.assertTrue(live_room["links"])

    def test_lab_nodes_room_projection_turns_templates_instances_and_surfaces_into_node_workbench(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            projection = lab.nodes_room_projection(config)

        self.assertEqual(projection["summary"]["template_count"], len(config.node_profiles))
        self.assertEqual(projection["summary"]["instance_count"], len(projection["node_instances"]))
        self.assertGreater(projection["summary"]["surface_count"], 0)
        self.assertGreater(projection["summary"]["primary_surface_count"], 0)
        self.assertIn("shop", projection["filters"]["families"])
        self.assertIn("live", projection["filters"]["order_modes"])
        self.assertIn("main-open", projection["filters"]["registry_lanes"])
        self.assertIn("template", projection["filters"]["owner_kinds"])
        self.assertIn("instance", projection["filters"]["owner_kinds"])
        self.assertIn("public_shop", projection["filters"]["surface_keys"])

        pizza_template = next(item for item in projection["node_templates"] if item["id"] == "pizza-shop")
        self.assertEqual(pizza_template["owner_story"], "Seeded node template Pizza shop")
        self.assertEqual(pizza_template["service_name"], "pilot-pizza-shop")
        self.assertIn("Announces", pizza_template["registry_story"])
        self.assertIn("public lane", pizza_template["open_first_story"])

        seeded_instance = next(item for item in projection["node_instances"] if item["id"] == "pizza-shop")
        self.assertEqual(seeded_instance["launch_mode"], "seeded_service")
        self.assertEqual(seeded_instance["public_surface_key"], "public_shop")
        self.assertIn("runtime", seeded_instance["runtime_story"].lower())
        self.assertIn("node instance", seeded_instance["owner_story"].lower())

        template_surface = next(
            item
            for item in projection["customer_surfaces"]
            if item["owner_kind"] == "template" and item["owner_id"] == "pizza-shop" and item["primary"]
        )
        self.assertEqual(template_surface["surface_key"], "public_shop")
        self.assertTrue(template_surface["surface_url"].startswith("http://127.0.0.1:8595/"))

        instance_surface = next(
            item
            for item in projection["customer_surfaces"]
            if item["owner_kind"] == "instance" and item["owner_id"] == "pizza-shop" and item["primary"]
        )
        self.assertEqual(instance_surface["surface_key"], "public_shop")
        self.assertIn("main-open", instance_surface["registry_targets"])

    def test_lab_server_group_action_starts_members_via_action_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            group_projection = {
                "servers": [],
                "groups": [
                    {
                        "id": "registry-stack",
                        "actions": [{"id": "start"}],
                        "members": [
                            {"action_target": {"type": "service", "id": "primary-registry"}},
                            {"action_target": {"type": "service", "id": "backup-registry"}},
                        ],
                    }
                ],
            }
            with (
                patch.object(lab, "server_inventory_projection", side_effect=[group_projection, group_projection]),
                patch.object(lab, "_start_server_action_target") as start_target,
                patch.object(lab.manager, "status", return_value={"services": []}),
            ):
                payload = lab.api_server_group_action("registry-stack", "start")

        self.assertEqual(payload["groups"][0]["id"], "registry-stack")
        self.assertEqual(start_target.call_count, 2)
        self.assertEqual(start_target.call_args_list[0].args[1], {"type": "service", "id": "primary-registry"})
        self.assertEqual(start_target.call_args_list[1].args[1], {"type": "service", "id": "backup-registry"})

    def test_lab_server_group_action_starts_node_dependencies_before_runtime_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            group_projection = {
                "servers": [],
                "groups": [
                    {
                        "id": "node-runtimes",
                        "actions": [{"id": "start"}],
                        "dependency_service_names": ["primary-registry", "backup-registry"],
                        "plan": {
                            "start_order": ["primary-registry", "backup-registry", "pilot-pizza-shop"],
                            "stop_order": ["pilot-pizza-shop"],
                            "dependencies_first": True,
                            "rebind_owner_stories": ["Generated node instance Pizza Shop Bind"],
                        },
                        "members": [
                            {
                                "name": "pilot-pizza-shop",
                                "action_target": {"type": "service", "id": "pilot-pizza-shop"},
                                "binding": {"owner_story": "Generated node instance Pizza Shop Bind", "can_rebind": True},
                            },
                        ],
                        "truth_owner_stories": ["Generated node instance Pizza Shop Bind"],
                    }
                ],
            }
            with (
                patch.object(lab, "server_inventory_projection", side_effect=[group_projection, group_projection]),
                patch.object(lab, "_start_server_action_target") as start_target,
                patch.object(lab.manager, "status", return_value={"services": []}),
            ):
                payload = lab.api_server_group_action("node-runtimes", "start")

        self.assertEqual(payload["groups"][0]["id"], "node-runtimes")
        self.assertEqual(start_target.call_args_list[0].args[1], {"type": "service", "id": "primary-registry"})
        self.assertEqual(start_target.call_args_list[1].args[1], {"type": "service", "id": "backup-registry"})
        self.assertEqual(start_target.call_args_list[2].args[1], {"type": "service", "id": "pilot-pizza-shop"})

    def test_lab_recover_server_action_forgets_stale_external_then_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            service = lab.ManagedProcess(
                name="primary-registry",
                port=8000,
                kind="registry",
                cwd=lab.REGISTRY_ROOT,
                command=["echo", "ignored"],
                env={},
                external=True,
            )
            lab.manager._services["primary-registry"] = service

            with (
                patch.object(lab.manager, "get_service_status", return_value={"name": "primary-registry", "running": True, "usable": False}),
                patch.object(lab, "_start_server_action_target") as start_target,
            ):
                lab._recover_server_action_target(config, {"type": "service", "id": "primary-registry"})

        self.assertIsNone(lab.manager.get_managed("primary-registry"))
        self.assertEqual(start_target.call_args.args[1], {"type": "service", "id": "primary-registry"})

    def test_lab_rebind_server_action_forgets_conflicting_port_owner_then_adopts_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            instance = lab.state_store.create_node_instance(
                config=config,
                template=config.node_profiles["pizza-shop"],
                instance_id="pizza-shop-custom-bind",
                title="Pizza Shop Bind",
                description="",
                notes="",
            )
            stale_owner = lab.ManagedProcess(
                name="orphan-pizza-owner",
                port=instance["port"],
                kind="pilot-node",
                cwd=lab.PILOT_NODE_ROOT,
                command=["echo", "ignored"],
                env={},
                external=True,
            )
            lab.manager._services["orphan-pizza-owner"] = stale_owner

            with patch.object(lab.manager, "adopt_existing_service") as adopt_service:
                lab._rebind_server_action_target(config, {"type": "node-instance", "id": instance["id"]})

        self.assertIsNone(lab.manager.get_managed("orphan-pizza-owner"))
        self.assertIsNone(lab.manager.get_managed(instance["service_name"]))
        definition = adopt_service.call_args.args[0]
        self.assertEqual(definition.name, instance["service_name"])
        self.assertEqual(definition.port, instance["port"])

    def test_lab_can_build_and_start_generated_node_instance_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            created = lab.state_store.create_node_instance(
                config=config,
                template=config.node_profiles["pizza-shop"],
                instance_id="pizza-shop-custom-002",
                title="Custom Pizza Launchable",
                description="Launchable generated node instance.",
                notes="Runtime generation test.",
            )

            created = lab.state_store.update_node_instance(
                config=config,
                instance_id="pizza-shop-custom-002",
                title="Custom Pizza Launchable",
                description="Launchable generated node instance.",
                notes="Runtime generation test.",
                registry_targets=["dk-p4p-curated", "main-open"],
                visibility_expectations=["dk-p4p-curated"],
                module_ids=["p4p.menu.list", "p4p.customer.status", "p4p.payment.cash"],
                menu_seed={
                    "currency": "DKK",
                    "items": [
                        {
                            "id": "deep-pan",
                            "name": "Deep Pan",
                            "description": "Generated instance menu override.",
                            "category": "pizza",
                            "price_minor": 12300,
                            "image_url": "",
                        }
                    ],
                },
                node_id="dk-generated-pizza-002",
                city="Roskilde",
                country="dk",
                categories=["pizza", "deep-pan"],
                order_mode="menu_only",
                public_surface_key="menu_json",
            )

            definition = lab._build_node_instance_service_definition(config, created)

        self.assertEqual(definition.name, "instance-pizza-shop-custom-002")
        self.assertEqual(definition.port, created["port"])
        self.assertEqual(definition.env["P4P_NODE_ID"], "dk-generated-pizza-002")
        self.assertEqual(definition.env["P4P_NODE_NAME"], "Custom Pizza Launchable")
        self.assertEqual(definition.env["P4P_NODE_CITY"], "Roskilde")
        self.assertEqual(definition.env["P4P_NODE_COUNTRY"], "DK")
        self.assertEqual(definition.env["P4P_NODE_CATEGORIES"], "pizza,deep-pan")
        self.assertEqual(definition.env["P4P_NODE_ORDER_MODE"], "menu_only")
        self.assertEqual(definition.env["P4P_OPERATOR_TOKEN"], "lab-pizza-shop-custom-002")
        self.assertEqual(definition.env["P4P_REGISTRY_URL"], "http://127.0.0.1:8001")
        self.assertEqual(
            definition.env["P4P_REGISTRY_URLS"],
            "http://127.0.0.1:8001,http://127.0.0.1:8000",
        )
        self.assertEqual(definition.env["P4P_NODE_MODULES"], "p4p.menu.list,p4p.customer.status,p4p.payment.cash")
        self.assertEqual(definition.env["P4P_MENU_ITEM_1_ID"], "deep-pan")
        self.assertEqual(definition.env["P4P_MENU_ITEM_1_PRICE"], "12300")
        self.assertEqual(definition.health_url, f"http://127.0.0.1:{created['port']}/")
        self.assertTrue(any(link["label"] == "Generated public shop" for link in definition.links))
        self.assertEqual(created["public_surface_key"], "menu_json")
        self.assertEqual(created["public_shop_url"], created["customer_urls"]["menu_json"])

    def test_lab_process_manager_adopts_existing_service_when_port_is_already_live(self) -> None:
        lab = load_module("lab/app.py")
        manager = lab.ProcessManager()
        definition = lab.LabServiceDefinition(
            name="external-pizza-shop",
            kind="pilot-node",
            description="Already running outside lab manager.",
            cwd="{pilot_node_root}",
            command=["{python}", "-m", "http.server", "9999"],
            env={},
            port=8595,
            health_url="http://127.0.0.1:8595/",
        )

        with (
            patch.object(manager, "_probe_url_health", return_value=(True, 200, {"status": "ready"})),
            patch.object(manager, "_spawn") as spawn,
        ):
            service = manager.start_configured_service(definition)

        self.assertTrue(service.external)
        self.assertEqual(service.name, "external-pizza-shop")
        self.assertIn("adopted existing service", service.logs[-1])
        self.assertIs(manager._services["external-pizza-shop"], service)
        spawn.assert_not_called()

    def test_lab_process_manager_status_uses_snapshot_when_services_change_during_projection(self) -> None:
        lab = load_module("lab/app.py")
        manager = lab.ProcessManager()
        service = lab.ManagedProcess(
            name="mutating-service",
            port=9999,
            kind="registry",
            cwd=lab.LAB_ROOT,
            command=["echo", "test"],
            env={},
            external=True,
        )
        manager._services["mutating-service"] = service

        def project_and_mutate(current_service):
            manager._services["late-added"] = lab.ManagedProcess(
                name="late-added",
                port=10000,
                kind="registry",
                cwd=lab.LAB_ROOT,
                command=["echo", "late"],
                env={},
                external=True,
            )
            return {
                "name": current_service.name,
                "kind": current_service.kind,
                "port": current_service.port,
            }

        with patch.object(manager, "_project_service_status", side_effect=project_and_mutate):
            payload = manager.status()

        self.assertEqual(payload["services"][0]["name"], "mutating-service")
        self.assertIn("late-added", manager._services)

    def test_lab_customer_fixture_runner_records_order_and_status(self) -> None:
        lab = load_module("lab/app.py")
        config = lab.load_lab_config()
        lab.run_store = lab.RunStore()

        with (
            patch.object(lab.manager, "start_configured_service") as start_service,
            patch.object(
                lab,
                "_wait_for_service_ready",
                return_value={"name": "pilot-pizza-shop", "running": True, "usable": True},
            ),
            patch.object(
                lab,
                "_http_json_request",
                side_effect=[
                    (200, {"currency": "DKK", "items": [{"id": "margherita"}, {"id": "pepperoni"}]}),
                    (
                        200,
                        {
                            "accepted": True,
                            "order_id": "ord-test-1",
                            "estimated_ready": "2026-05-14T00:00:00Z",
                            "message": "ok",
                        },
                    ),
                    (200, {"order_id": "ord-test-1", "status": "accepted"}),
                ],
            ),
        ):
            run = lab.run_customer_fixture(config, "pickup-basic")

        start_service.assert_called_once()
        self.assertTrue(run["success"])
        self.assertEqual(run["order_id"], "ord-test-1")
        self.assertEqual(run["owner_story"], "Seeded node template Pizza shop")
        self.assertEqual(run["public_surface_key"], "list_menu")
        self.assertIn("main-open", run["registry_targets"])
        self.assertEqual(run["status_payload"]["status"], "accepted")
        self.assertEqual(lab.run_store.list()[0]["run_id"], run["run_id"])

    def test_lab_customer_fixture_instance_can_target_generated_node_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            lab.run_store = lab.RunStore()

            created_instance = lab.state_store.create_node_instance(
                config=config,
                template=config.node_profiles["pizza-shop"],
                instance_id="pizza-shop-fixture-001",
                title="Pizza Shop Fixture 001",
                description="Generated node instance for local fixture tests.",
                notes="",
            )
            fixture = lab.state_store.create_customer_fixture_instance(
                config=config,
                instance_id="local-pizza-fixture-001",
                title="Local Pizza Fixture 001",
                description="Generated local fixture against a generated node instance.",
                target_ref="pizza-shop-fixture-001",
                menu_surface="list_menu",
                order_request={
                    "customer_name": "Anna Hansen",
                    "customer_contact": "+4512345678",
                    "fulfillment": "pickup",
                    "items": [{"id": "margherita", "quantity": 1}],
                    "note": "No onions",
                },
                poll_status={"enabled": True, "attempts": 3, "interval_ms": 10},
                expected={"accepted": True, "final_status": "accepted"},
            )

            self.assertEqual(fixture["id"], "local-pizza-fixture-001")
            self.assertTrue(fixture["generated"])
            self.assertEqual(fixture["target_profile"], "pizza-shop-fixture-001")

            with (
                patch.object(lab.manager, "start_configured_service"),
                patch.object(
                    lab,
                    "_wait_for_service_ready",
                    return_value={"name": created_instance["service_name"], "running": True, "usable": True},
                ),
                patch.object(
                    lab,
                    "_http_json_request",
                    side_effect=[
                        (200, {"currency": "DKK", "items": [{"id": "margherita"}]}),
                        (
                            200,
                            {
                                "accepted": True,
                                "order_id": "ord-local-fixture-1",
                                "estimated_ready": "2026-05-14T00:00:00Z",
                                "message": "ok",
                            },
                        ),
                        (200, {"order_id": "ord-local-fixture-1", "status": "accepted"}),
                    ],
                ),
            ):
                run = lab.run_customer_fixture(config, "local-pizza-fixture-001")

            self.assertTrue(run["success"])
            self.assertEqual(run["fixture_id"], "local-pizza-fixture-001")
            self.assertEqual(run["profile_id"], "pizza-shop-fixture-001")
            self.assertEqual(run["owner_story"], "Generated node instance Pizza Shop Fixture 001")
            self.assertEqual(run["public_surface_key"], "list_menu")
            self.assertEqual(run["order_id"], "ord-local-fixture-1")

    def test_lab_flow_scenario_can_stop_primary_and_keep_backup(self) -> None:
        lab = load_module("lab/app.py")
        config = lab.load_lab_config()
        lab.run_store = lab.RunStore()
        stopped: set[str] = set()

        def fake_status(name: str):
            if name == "primary-registry":
                running = name not in stopped
                return {"name": name, "running": running, "usable": running}
            if name in {"secondary-registry", "backup-registry", "curated-backup-registry", "pilot-pizza-shop"}:
                return {"name": name, "running": True, "usable": True}
            return None

        with (
            patch.object(lab.manager, "start_configured_service"),
            patch.object(
                lab,
                "_wait_for_service_ready",
                return_value={"running": True, "usable": True},
            ),
            patch.object(lab.manager, "get_service_status", side_effect=fake_status),
            patch.object(lab.manager, "stop", side_effect=lambda name: stopped.add(name)),
        ):
            run = lab.run_flow_scenario(config, "fail-primary-keep-backup")

        self.assertTrue(run["success"])
        self.assertIn("primary-registry", stopped)
        self.assertTrue(all(item["success"] for item in run["checks"]))

    def test_lab_flow_scenario_instance_can_target_generated_node_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()
            lab.run_store = lab.RunStore()

            created_instance = lab.state_store.create_node_instance(
                config=config,
                template=config.node_profiles["pizza-shop"],
                instance_id="pizza-shop-flow-001",
                title="Pizza Shop Flow 001",
                description="Generated node instance for local flow tests.",
                notes="",
            )
            flow = lab.state_store.create_flow_scenario_instance(
                config=config,
                instance_id="local-pizza-flow-001",
                title="Local Pizza Flow 001",
                description="Generated local flow against a generated node instance.",
                services=["primary-registry"],
                node_refs=["pizza-shop-flow-001"],
                fixture_runs=[{"fixture_id": "pickup-basic", "profile_id": "pizza-shop-flow-001"}],
                notes=["Local flow test."],
            )

            self.assertEqual(flow["id"], "local-pizza-flow-001")
            self.assertTrue(flow["generated"])
            self.assertEqual(flow["node_profiles"], ["pizza-shop-flow-001"])

            def fake_status(name: str):
                if name == "primary-registry":
                    return {"name": name, "running": True, "usable": True}
                if name == created_instance["service_name"]:
                    return {"name": name, "running": True, "usable": True}
                return None

            with (
                patch.object(lab.manager, "start_configured_service"),
                patch.object(
                    lab,
                    "_wait_for_service_ready",
                    return_value={"running": True, "usable": True},
                ),
                patch.object(lab.manager, "get_service_status", side_effect=fake_status),
                patch.object(
                    lab,
                    "_http_json_request",
                    side_effect=[
                        (200, {"currency": "DKK", "items": [{"id": "margherita"}]}),
                        (
                            200,
                            {
                                "accepted": True,
                                "order_id": "ord-flow-local-1",
                                "estimated_ready": "2026-05-14T00:00:00Z",
                                "message": "ok",
                            },
                        ),
                        (200, {"order_id": "ord-flow-local-1", "status": "accepted"}),
                    ],
                ),
            ):
                run = lab.run_flow_scenario_instance(config, "local-pizza-flow-001")

            self.assertTrue(run["success"])
            self.assertEqual(run["kind"], "flow_scenario_instance")
            self.assertEqual(run["scenario_id"], "local-pizza-flow-001")
            self.assertIn("pizza-shop-flow-001", run["node_profiles"])
            self.assertEqual(run["resolved_targets"][0]["owner_story"], "Generated node instance Pizza Shop Flow 001")
            self.assertEqual(run["resolved_targets"][0]["public_surface_key"], "public_shop")
            self.assertTrue(all(item["success"] for item in run["checks"]))

    def test_lab_flow_scenario_instance_can_store_explicit_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"P4P_LAB_STATE_DB_PATH": str(Path(tmpdir) / "lab-state.sqlite3")}
            lab = load_module("lab/app.py", env)
            config = lab.load_lab_config()

            flow = lab.state_store.create_flow_scenario_instance(
                config=config,
                instance_id="local-explicit-checks-001",
                title="Local Explicit Checks 001",
                description="Generated local flow with explicit checks.",
                services=["primary-registry"],
                node_refs=["pizza-shop"],
                fixture_runs=[{"fixture_id": "pickup-basic", "profile_id": "pizza-shop"}],
                notes=["Explicit checks are local truth."],
                checks=[
                    {"kind": "service_running", "service": "primary-registry"},
                    {"kind": "fixture_succeeded", "fixture_id": "pickup-basic", "profile_id": "pizza-shop"},
                ],
            )

            self.assertEqual(flow["id"], "local-explicit-checks-001")
            self.assertEqual(
                flow["checks"],
                [
                    {"kind": "service_running", "service": "primary-registry", "fixture_id": None, "profile_id": None},
                    {"kind": "fixture_succeeded", "service": None, "fixture_id": "pickup-basic", "profile_id": "pizza-shop"},
                ],
            )

    def test_lab_runs_api_summarizes_owner_and_layer_truth(self) -> None:
        lab = load_module("lab/app.py")
        config = lab.load_lab_config()
        lab.run_store = lab.RunStore()

        with (
            patch.object(lab.manager, "start_configured_service"),
            patch.object(
                lab,
                "_wait_for_service_ready",
                return_value={"name": "pilot-pizza-shop", "running": True, "usable": True},
            ),
            patch.object(
                lab,
                "_http_json_request",
                side_effect=[
                    (200, {"currency": "DKK", "items": [{"id": "margherita"}]}),
                    (
                        200,
                        {
                            "accepted": True,
                            "order_id": "ord-summary-1",
                            "estimated_ready": "2026-05-14T00:00:00Z",
                            "message": "ok",
                        },
                    ),
                    (200, {"order_id": "ord-summary-1", "status": "accepted"}),
                ],
            ),
        ):
            lab.run_customer_fixture(config, "pickup-basic")

        payload = lab.api_runs()
        self.assertEqual(payload["summary"]["total_runs"], 1)
        self.assertEqual(payload["summary"]["success_count"], 1)
        self.assertEqual(payload["summary"]["failed_count"], 0)
        self.assertEqual(payload["summary"]["kinds"]["customer_fixture"], 1)
        self.assertIn("Seeded node template Pizza shop", payload["summary"]["owner_stories"])
        self.assertIn("list_menu", payload["summary"]["surface_keys"])
        self.assertIn("main-open", payload["summary"]["registry_lanes"])

    def test_lab_runs_room_projection_projects_human_run_story(self) -> None:
        lab = load_module("lab/app.py")
        lab.run_store = lab.RunStore()
        lab.run_store.record(
            {
                "kind": "flow_scenario",
                "run_id": "run-flow-1",
                "title": "Single Pizza Order",
                "success": True,
                "resolved_targets": [
                    {
                        "id": "pizza-shop",
                        "owner_story": "Seeded node template Pizza shop",
                        "public_surface_key": "list_menu",
                        "registry_targets": ["main-open"],
                        "visibility_expectations": ["dk-p4p-curated"],
                    }
                ],
                "checks": [{"kind": "service_usable"}],
            }
        )

        payload = lab.runs_room_projection()

        self.assertEqual(payload["summary"]["total_runs"], 1)
        self.assertEqual(payload["summary"]["latest_run_title"], "Single Pizza Order")
        self.assertIn("local owner", payload["summary"]["latest_run_story"])
        self.assertEqual(payload["filters"]["outcomes"][0]["id"], "success")
        self.assertEqual(payload["filters"]["kinds"][0]["label"], "Flow Scenario")
        self.assertEqual(payload["filters"]["owners"][0]["id"], "Seeded node template Pizza shop")
        self.assertEqual(payload["proof_lanes"][0]["owner_story"], "Seeded node template Pizza shop")
        self.assertEqual(payload["proof_lanes"][0]["run_count"], 1)
        self.assertEqual(payload["proof_lanes"][0]["surface_labels"], ["List Menu"])
        self.assertEqual(payload["runs"][0]["owner_stories"], ["Seeded node template Pizza shop"])
        self.assertEqual(payload["runs"][0]["surface_labels"], ["List Menu"])
        self.assertIn("main-open", payload["runs"][0]["registry_lanes"])
        self.assertIn("dk-p4p-curated", payload["runs"][0]["registry_lanes"])
        self.assertIn("This flow tested 1 local owner", payload["runs"][0]["run_story"])

    def test_pilot_node_defaults_to_menu_only_and_rejects_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "menu_only",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            response = pilot.public_order(self.make_pilot_order_request(pilot))

            self.assertFalse(response.accepted)
            self.assertEqual(response.reason, "orders_disabled")
            self.assertEqual(pilot.store.list_orders(), [])
            pilot.store.close()

    def test_pilot_node_public_order_localizes_customer_rejection_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "menu_only",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            response = pilot.public_order(self.make_pilot_order_request(pilot), locale="sv")

            self.assertFalse(response.accepted)
            self.assertEqual(response.reason, "orders_disabled")
            self.assertEqual(response.message, "Restaurangen tar inte emot beställningar just nu.")
            self.assertEqual(pilot.store.list_orders(), [])
            pilot.store.close()

    def test_pilot_node_public_order_localizes_customer_runtime_message_without_changing_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot), locale="sv")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertTrue(accepted.accepted)
            self.assertEqual(
                accepted.message,
                "Ordern har accepterats. Betalning är satt till vid avhämtning.",
            )
            self.assertEqual(stored[0].status_message, "Order accepted. Payment set to pay at pickup.")
            pilot.store.close()

    def test_pilot_node_announces_only_public_modules_but_keeps_internal_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print,p4p.notify.email",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            node = pilot.node_state()
            operator_state = pilot.operator_state(authorization="Bearer operator-secret")

            self.assertEqual(node.modules, ["p4p.payment.cash"])
            self.assertEqual(
                operator_state["enabled_modules"],
                ["p4p.payment.cash", "p4p.order.print", "p4p.notify.email"],
            )
            self.assertEqual(operator_state["public_modules"], ["p4p.payment.cash"])
            self.assertEqual(operator_state["undeclared_modules"], [])
            self.assertEqual(
                [entry["module_id"] for entry in operator_state["module_declarations"]],
                ["p4p.payment.cash", "p4p.order.print", "p4p.notify.email"],
            )
            self.assertEqual(
                [entry["module_id"] for entry in operator_state["public_module_declarations"]],
                ["p4p.payment.cash"],
            )
            self.assertEqual(operator_state["module_declarations"][1]["visibility"], "operator_only")
            pilot.store.close()

    def test_pilot_public_info_only_exposes_public_module_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print,p4p.notify.email",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            info = pilot.public_info()

            self.assertEqual(info["modules"], ["p4p.payment.cash"])
            self.assertEqual(
                [entry["module_id"] for entry in info["module_declarations"]],
                ["p4p.payment.cash"],
            )
            self.assertEqual(info["undeclared_modules"], [])
            pilot.store.close()

    def test_pilot_node_keeps_homebuilt_modules_undeclared_and_non_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,local.pizzacoin.wallet",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            execution = sys.modules["pilot_node.execution"]
            operator_state = pilot.operator_state(authorization="Bearer operator-secret")
            operator_modules = pilot.operator_modules(authorization="Bearer operator-secret")
            info = pilot.public_info()
            node = pilot.node_state()

            self.assertEqual(operator_state["enabled_modules"], ["p4p.payment.cash", "local.pizzacoin.wallet"])
            self.assertEqual(operator_state["public_modules"], ["p4p.payment.cash"])
            self.assertEqual(operator_state["undeclared_modules"], ["local.pizzacoin.wallet"])
            self.assertEqual(
                [entry["module_id"] for entry in operator_state["module_declarations"]],
                ["p4p.payment.cash"],
            )
            self.assertEqual(node.modules, ["p4p.payment.cash"])
            self.assertEqual(info["modules"], ["p4p.payment.cash"])
            self.assertEqual(info["undeclared_modules"], [])
            self.assertEqual(
                [entry["module_id"] for entry in operator_modules["undeclared_modules"]],
                ["local.pizzacoin.wallet"],
            )
            self.assertEqual(operator_modules["undeclared_modules"][0]["health"], "undeclared")
            self.assertFalse(operator_modules["undeclared_modules"][0]["executable"])
            self.assertFalse(runtime.config.resolved_modules.contains("local.pizzacoin.wallet"))
            self.assertEqual(
                [executor.module_id for executor in execution.enabled_module_executors(runtime, lane="payment")],
                ["p4p.payment.cash"],
            )
            pilot.store.close()

    def test_pilot_node_imports_external_pizzacoin_manifest_and_executes_selected_payment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pizzacoin_manifest = REPO_ROOT.parent / "Pizzacoin" / "contracts" / "module.json"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,local.pizzacoin.wallet,p4p.order.print",
                    "P4P_EXTERNAL_MODULE_MANIFESTS": str(pizzacoin_manifest),
                    "P4P_PAYMENT_MODULE_ID": "local.pizzacoin.wallet",
                    "P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID": "usr_test_customer",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            execution = sys.modules["pilot_node.execution"]
            payment_client = ExternalPaymentClient(confirmed=True)
            with patch.object(execution.httpx, "Client", return_value=payment_client):
                accepted = pilot.public_order(self.make_pilot_order_request(pilot))

            operator_state = pilot.operator_state(authorization="Bearer operator-secret")
            info = pilot.public_info()
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(runtime.config.payment_module_id, "local.pizzacoin.wallet")
            self.assertEqual(runtime.config.flow_module_ids, ("local.pizzacoin.wallet", "p4p.order.print"))
            self.assertEqual(operator_state["undeclared_modules"], [])
            self.assertEqual(operator_state["public_modules"], ["p4p.payment.cash", "local.pizzacoin.wallet"])
            self.assertEqual(info["payment_methods"], ["external_test_payment"])
            self.assertEqual(
                [executor.module_id for executor in execution.enabled_module_executors(runtime, lane="payment")],
                ["local.pizzacoin.wallet"],
            )
            self.assertEqual(
                [event.event for event in events],
                [
                    "ORDER_ACCEPTED",
                    "PAYMENT_REQUIRED",
                    "PAYMENT_MODE_CHANGED",
                    "PRINT_REQUESTED",
                    "PRINT_SUCCESS_CONFIRMED",
                ],
            )
            self.assertEqual(events[1].source_module, "local.pizzacoin.wallet")
            self.assertEqual(events[1].metadata["amount"], 6500)
            self.assertEqual(events[1].metadata["currency"], "PIZZACOIN")
            self.assertEqual(events[2].source_module, "local.pizzacoin.wallet")
            self.assertEqual(events[2].metadata["external_payment_id"], "pay_test_001")
            self.assertEqual(payment_client.posts[0][0], "http://127.0.0.1:8301/p4p/payment")
            self.assertEqual(payment_client.posts[0][1]["customer_user_id"], "usr_test_customer")
            self.assertEqual(payment_client.posts[0][1]["amount"], 6500)
            self.assertEqual(payment_client.posts[1][0], "http://127.0.0.1:8301/p4p/payment/pay_test_001/confirm")
            self.assertEqual(stored[0].payment_method, "external_test_payment")
            self.assertEqual(stored[0].status_message, "Order accepted. Print confirmed.")
            pilot.store.close()

    def test_pilot_node_operator_modules_reports_active_external_payment_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pizzacoin_manifest = REPO_ROOT.parent / "Pizzacoin" / "contracts" / "module.json"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,local.pizzacoin.wallet,p4p.order.print",
                    "P4P_EXTERNAL_MODULE_MANIFESTS": str(pizzacoin_manifest),
                    "P4P_PAYMENT_MODULE_ID": "local.pizzacoin.wallet",
                    "P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID": "usr_test_customer",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            health_client = ModuleHealthClient(ok=True)
            with patch.object(pilot.httpx, "Client", return_value=health_client):
                modules = pilot.operator_modules(authorization="Bearer operator-secret")

            self.assertEqual(modules["active_by_lane"]["payment"], "local.pizzacoin.wallet")
            payment_modules = {
                entry["module_id"]: entry
                for entry in modules["lanes"]["payment"]["modules"]
            }
            self.assertFalse(payment_modules["p4p.payment.cash"]["active"])
            self.assertEqual(payment_modules["p4p.payment.cash"]["health"], "available")
            self.assertFalse(payment_modules["p4p.payment.cash"]["executable"])
            self.assertTrue(payment_modules["local.pizzacoin.wallet"]["active"])
            self.assertTrue(payment_modules["local.pizzacoin.wallet"]["configured"])
            self.assertTrue(payment_modules["local.pizzacoin.wallet"]["executable"])
            self.assertEqual(payment_modules["local.pizzacoin.wallet"]["health"], "up")
            self.assertEqual(payment_modules["local.pizzacoin.wallet"]["health_url"], "http://127.0.0.1:8301/health")
            self.assertEqual(health_client.gets, ["http://127.0.0.1:8301/health"])
            self.assertEqual(modules["lanes"]["operator"]["modules"][0]["module_id"], "p4p.order.print")
            self.assertTrue(modules["lanes"]["operator"]["modules"][0]["active"])
            pilot.store.close()

    def test_pilot_node_operator_modules_marks_selected_payment_missing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pizzacoin_manifest = REPO_ROOT.parent / "Pizzacoin" / "contracts" / "module.json"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "local.pizzacoin.wallet",
                    "P4P_EXTERNAL_MODULE_MANIFESTS": str(pizzacoin_manifest),
                    "P4P_PAYMENT_MODULE_ID": "local.pizzacoin.wallet",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            modules = pilot.operator_modules(authorization="Bearer operator-secret")
            payment_entry = modules["lanes"]["payment"]["modules"][0]

            self.assertEqual(payment_entry["module_id"], "local.pizzacoin.wallet")
            self.assertTrue(payment_entry["active"])
            self.assertFalse(payment_entry["configured"])
            self.assertFalse(payment_entry["executable"])
            self.assertEqual(payment_entry["health"], "not_configured")
            self.assertEqual(payment_entry["missing_configuration"], ["payment_external_customer_user_id"])
            pilot.store.close()

    def test_pilot_node_kitchen_screen_module_updates_operator_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.kitchen.screen,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            modules = pilot.operator_modules(authorization="Bearer operator-secret")
            orders = pilot.operator_orders(authorization="Bearer operator-secret")
            updated = pilot.operator_update_order(
                accepted.order_id,
                pilot.OrderStatusUpdate(status="ready", status_message="Ready for pickup."),
                authorization="Bearer operator-secret",
            )

            kitchen_entry = {
                entry["module_id"]: entry
                for entry in modules["lanes"]["operator"]["modules"]
            }["p4p.kitchen.screen"]
            self.assertTrue(kitchen_entry["active"])
            self.assertTrue(kitchen_entry["configured"])
            self.assertTrue(kitchen_entry["executable"])
            self.assertEqual(kitchen_entry["implementation"], "builtin_operator_surface")
            self.assertEqual(kitchen_entry["health"], "available")
            self.assertEqual(kitchen_entry["readiness"], "test")
            self.assertEqual(orders[0].order_id, accepted.order_id)
            self.assertEqual(updated.status, "ready")
            self.assertEqual(updated.status_message, "Ready for pickup.")
            self.assertEqual(
                pilot.operator_orders(authorization="Bearer operator-secret")[0].status,
                "ready",
            )
            events = pilot.operator_order_events(
                accepted.order_id,
                authorization="Bearer operator-secret",
            )
            status_event = events[-1]
            self.assertEqual(status_event.event, "ORDER_STATUS_UPDATED")
            self.assertEqual(status_event.source_module, "p4p.kitchen.screen")
            self.assertEqual(status_event.outcome, "SUCCESS")
            self.assertEqual(status_event.side_effect_state, "confirmed")
            self.assertEqual(status_event.metadata["previous_status"], "accepted")
            self.assertEqual(status_event.metadata["next_status"], "ready")
            pilot.store.close()

    def test_pilot_node_customer_status_module_exposes_safe_public_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            public_info = pilot.public_info()
            status = pilot.public_order_status(accepted.order_id)
            status_payload = status.model_dump(mode="json")
            viewed_event = pilot.operator_order_events(
                accepted.order_id,
                authorization="Bearer operator-secret",
            )[-1]

            self.assertIn("p4p.customer.status", public_info["modules"])
            self.assertEqual(status.order_id, accepted.order_id)
            self.assertEqual(status.status, "accepted")
            self.assertEqual(status.status_message, "Order accepted. Payment set to pay at pickup.")
            self.assertNotIn("customer_name", status_payload)
            self.assertNotIn("customer_contact", status_payload)
            self.assertNotIn("note", status_payload)
            self.assertNotIn("items", status_payload)
            self.assertEqual(viewed_event.event, "ORDER_STATUS_VIEWED")
            self.assertEqual(viewed_event.source_module, "p4p.customer.status")
            self.assertFalse(viewed_event.metadata["exposes_customer_contact"])
            self.assertFalse(viewed_event.metadata["exposes_order_note"])

            pilot.operator_update_order(
                accepted.order_id,
                pilot.OrderStatusUpdate(status="ready", status_message="Ready for pickup."),
                authorization="Bearer operator-secret",
            )
            ready_status = pilot.public_order_status(accepted.order_id)
            status_page = pilot.public_order_status_page(accepted.order_id)

            self.assertEqual(ready_status.status, "ready")
            self.assertEqual(ready_status.status_message, "Ready for pickup.")
            self.assertIn("Klar til afhentning.", status_page)
            self.assertIn(accepted.order_id, status_page)
            self.assertNotIn("+4512345678", status_page)
            self.assertNotIn("Anna Hansen", status_page)
            self.assertNotIn("No onions", status_page)
            pilot.store.close()

    def test_pilot_node_customer_status_page_localizes_runtime_message_from_requested_locale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.customer.status,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            status_page = pilot.public_order_status_page(accepted.order_id, locale="tr")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertIn("lang=\"tr\"", status_page)
            self.assertIn("Sipariş kabul edildi. Ödeme teslim almada ödenecek olarak ayarlandı.", status_page)
            self.assertNotIn("Order accepted. Payment set to pay at pickup.", status_page)
            self.assertEqual(stored[0].status_message, "Order accepted. Payment set to pay at pickup.")
            pilot.store.close()

    def test_pilot_node_customer_status_page_localizes_operator_ready_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.customer.status,p4p.payment.cash,p4p.kitchen.screen",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            pilot.operator_update_order(
                accepted.order_id,
                pilot.OrderStatusUpdate(status="ready", status_message="Ready for pickup."),
                authorization="Bearer operator-secret",
            )
            status_page = pilot.public_order_status_page(accepted.order_id, locale="sv")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertIn("Klar för avhämtning.", status_page)
            self.assertNotIn("Ready for pickup.", status_page)
            self.assertEqual(stored[0].status_message, "Ready for pickup.")
            pilot.store.close()

    def test_pilot_node_customer_status_page_keeps_free_operator_message_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.customer.status,p4p.payment.cash,p4p.kitchen.screen",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            pilot.operator_update_order(
                accepted.order_id,
                pilot.OrderStatusUpdate(status="accepted", status_message="Seen by kitchen"),
                authorization="Bearer operator-secret",
            )
            status_page = pilot.public_order_status_page(accepted.order_id, locale="sv")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertIn("Seen by kitchen", status_page)
            self.assertEqual(stored[0].status_message, "Seen by kitchen")
            pilot.store.close()

    def test_pilot_node_customer_status_endpoint_requires_enabled_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))

            with self.assertRaises(HTTPException) as missing_module:
                pilot.public_order_status(accepted.order_id)

            self.assertEqual(missing_module.exception.status_code, 404)
            self.assertEqual(missing_module.exception.detail, "Customer status module is not enabled")
            pilot.store.close()

    def test_pilot_node_hardware_feedback_modules_are_executable_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": (
                        "p4p.payment.cash,p4p.order.print.backup,"
                        "p4p.order.alert.basic,p4p.pickup.board.basic"
                    ),
                    "P4P_BACKUP_PRINT_TARGET": "backup_printer",
                    "P4P_BACKUP_PRINT_DRIVER": "file_spool",
                    "P4P_BACKUP_PRINT_SPOOL_DIR": str(Path(tmpdir) / "backup-spool"),
                    "P4P_ALERT_TARGET": "counter_bell",
                    "P4P_PICKUP_BOARD_TARGET": "counter_screen",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            modules = pilot.operator_modules(authorization="Bearer operator-secret")
            operator_modules = {entry["module_id"]: entry for entry in modules["lanes"]["operator"]["modules"]}

            backup_print = operator_modules["p4p.order.print.backup"]
            self.assertTrue(backup_print["active"])
            self.assertTrue(backup_print["configured"])
            self.assertTrue(backup_print["executable"])
            self.assertEqual(backup_print["implementation"], "builtin_hardware_probe")
            self.assertEqual(backup_print["health"], "available")

            alert = operator_modules["p4p.order.alert.basic"]
            self.assertTrue(alert["configured"])
            self.assertTrue(alert["executable"])
            self.assertEqual(alert["implementation"], "builtin_hardware_probe")

            pickup = operator_modules["p4p.pickup.board.basic"]
            self.assertTrue(pickup["configured"])
            self.assertTrue(pickup["executable"])
            self.assertEqual(pickup["implementation"], "builtin_operator_surface")
            self.assertEqual(pickup["configuration"]["view_url"], "/operator/pickup-board")
            pilot.store.close()

    def test_pilot_node_backup_print_module_self_test_can_write_spool_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spool_dir = Path(tmpdir) / "backup-spool"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print.backup",
                    "P4P_BACKUP_PRINT_TARGET": "backup_printer",
                    "P4P_BACKUP_PRINT_DRIVER": "file_spool",
                    "P4P_BACKUP_PRINT_SPOOL_DIR": str(spool_dir),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            result = pilot.operator_module_self_test(
                "p4p.order.print.backup",
                authorization="Bearer operator-secret",
            )

            self.assertEqual(result["events"], ["OUTBOUND_ACTION_REQUESTED", "ACTION_COMPLETED"])
            self.assertTrue(result["success"])
            self.assertEqual(result["driver"], "file_spool")
            artifact_path = Path(str(result["artifact_path"]))
            self.assertTrue(artifact_path.exists())
            self.assertIn("self-test-ticket", artifact_path.read_text(encoding="utf-8"))
            pilot.store.close()

    def test_pilot_node_order_alert_module_self_test_can_report_completed_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.alert.basic",
                    "P4P_ALERT_TARGET": "counter_bell",
                    "P4P_ALERT_MODE": "completed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            result = pilot.operator_module_self_test(
                "p4p.order.alert.basic",
                authorization="Bearer operator-secret",
            )

            self.assertEqual(result["events"], ["OUTBOUND_ACTION_REQUESTED", "ACTION_COMPLETED"])
            self.assertTrue(result["success"])
            self.assertEqual(result["target"], "counter_bell")
            pilot.store.close()

    def test_pilot_node_pickup_board_surface_filters_accepted_and_ready_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.kitchen.screen,p4p.pickup.board.basic",
                    "P4P_PICKUP_BOARD_TARGET": "counter_screen",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot, item_id="kebab-pita"))
            ready = pilot.public_order(self.make_pilot_order_request(pilot, item_id="durum-kebab"))
            pilot.operator_update_order(
                ready.order_id,
                pilot.OrderStatusUpdate(status="ready", status_message="Ready now."),
                authorization="Bearer operator-secret",
            )
            hidden = pilot.public_order(self.make_pilot_order_request(pilot, item_id="kebab-pita"))
            pilot.operator_update_order(
                hidden.order_id,
                pilot.OrderStatusUpdate(status="cancelled", status_message="Cancelled."),
                authorization="Bearer operator-secret",
            )

            page = pilot.operator_pickup_board_page()
            board = pilot.operator_pickup_board_data(authorization="Bearer operator-secret")

            self.assertIn("Pickup board", page)
            self.assertEqual(board["target"], "counter_screen")
            self.assertEqual([entry["order_id"] for entry in board["orders"]], [ready.order_id, accepted.order_id])
            self.assertEqual([entry["status"] for entry in board["orders"]], ["ready", "accepted"])
            pilot.store.close()

    def test_pilot_node_catalog_editor_module_updates_menu_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.customer.status,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            modules = pilot.operator_modules(authorization="Bearer operator-secret")
            catalog_entry = {
                entry["module_id"]: entry
                for entry in modules["lanes"]["operator"]["modules"]
            }["p4p.catalog.editor"]
            updated = pilot.operator_replace_menu(
                pilot.MenuUpdate(
                    items=[
                        pilot.MenuItem(
                            id="pizza-17",
                            name="Pizza 17",
                            description="Tomato, cheese, chili",
                            price=8900,
                            category="pizza",
                            active=True,
                            image_url="/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png",
                        ),
                        pilot.MenuItem(
                            id="durum-test",
                            name="Durum Test",
                            description="Hidden from public menu",
                            price=7500,
                            category="kebab",
                            active=False,
                        ),
                    ]
                ),
                authorization="Bearer operator-secret",
            )
            public_menu = pilot.public_menu()
            row = pilot.store._connection.execute(
                "SELECT event_json FROM order_events WHERE source_module = ?",
                ("p4p.catalog.editor",),
            ).fetchone()

            self.assertTrue(catalog_entry["active"])
            self.assertTrue(catalog_entry["configured"])
            self.assertTrue(catalog_entry["executable"])
            self.assertEqual(catalog_entry["implementation"], "builtin_operator_surface")
            self.assertEqual(catalog_entry["health"], "available")
            self.assertEqual([item.id for item in updated.items], ["pizza-17", "durum-test"])
            self.assertEqual([item.id for item in public_menu.items], ["pizza-17"])
            self.assertEqual(
                public_menu.items[0].image_url,
                "/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png",
            )
            self.assertIsNotNone(row)
            event = json.loads(str(row["event_json"]))
            self.assertEqual(event["event"], "CATALOG_UPDATED")
            self.assertEqual(event["source_module"], "p4p.catalog.editor")
            self.assertEqual(event["metadata"]["item_count"], 2)
            self.assertEqual(event["metadata"]["active_item_count"], 1)
            pilot.store.close()

    def test_pilot_node_menu_import_preview_extracts_draft_items_without_mutating_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "menu_only",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            before_menu = pilot.operator_menu(authorization="Bearer operator-secret")
            preview = pilot.operator_menu_import_preview(
                pilot.MenuImportPreviewRequest(
                    raw_text="\n".join(
                        [
                            "12. Margherita 75,-",
                            "13. Vesuvio 85,00",
                            "Durum kebab 65 kr",
                            "Levering 30 kr",
                            "Vælg mellem: 80,-",
                        ]
                    ),
                    source_name="phone-ocr-1",
                ),
                authorization="Bearer operator-secret",
            )
            after_menu = pilot.operator_menu(authorization="Bearer operator-secret")

            self.assertEqual(preview.source_kind, "ocr_text")
            self.assertEqual(preview.source_name, "phone-ocr-1")
            self.assertEqual([candidate.item.id for candidate in preview.candidates], ["margherita", "vesuvio", "durum-kebab"])
            self.assertEqual([candidate.item.price for candidate in preview.candidates], [7500, 8500, 6500])
            self.assertEqual([candidate.item.category for candidate in preview.candidates], ["pizza", "pizza", "durum"])
            self.assertIn("Levering 30 kr", preview.ignored_lines)
            self.assertIn("Vælg mellem: 80,-", preview.ignored_lines)
            self.assertTrue(any("not catalog truth" in warning.lower() for warning in preview.warnings))
            self.assertEqual(
                [item.model_dump(mode="json") for item in before_menu.items],
                [item.model_dump(mode="json") for item in after_menu.items],
            )
            self.assertEqual(
                pilot.root_index()["endpoints"]["operator_menu_import_preview"],
                "POST /operator/menu/import-preview",
            )
            pilot.store.close()

    def test_pilot_node_menu_import_preview_requires_ocr_module_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as missing_module:
                pilot.operator_menu_import_preview(
                    pilot.MenuImportPreviewRequest(raw_text="12. Margherita 75,-"),
                    authorization="Bearer operator-secret",
                )

            self.assertEqual(missing_module.exception.status_code, 404)
            self.assertEqual(missing_module.exception.detail, "Catalog OCR import module is not enabled")
            pilot.store.close()

    def test_pilot_node_menu_import_preview_requires_operator_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as auth_error:
                pilot.operator_menu_import_preview(
                    pilot.MenuImportPreviewRequest(raw_text="12. Margherita 75,-"),
                )

            self.assertEqual(auth_error.exception.status_code, 401)
            pilot.store.close()

    def test_pilot_node_menu_import_preview_humanizes_glued_pizza_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            preview = pilot.operator_menu_import_preview(
                pilot.MenuImportPreviewRequest(
                    raw_text="\n".join(
                        [
                            "FamiliepizzaMargherita 135 kr",
                            "Kebab Pizza 95 kr",
                        ]
                    )
                ),
                authorization="Bearer operator-secret",
            )

            candidates = {candidate.item.id: candidate.item for candidate in preview.candidates}
            self.assertIn("familiepizza-margherita", candidates)
            self.assertEqual(candidates["familiepizza-margherita"].name, "Familiepizza Margherita")
            self.assertEqual(candidates["familiepizza-margherita"].category, "pizza")
            self.assertEqual(candidates["kebab-pizza"].category, "pizza")
            pilot.store.close()

    def test_pilot_node_menu_import_preview_strips_glued_item_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            preview = pilot.operator_menu_import_preview(
                pilot.MenuImportPreviewRequest(
                    raw_text="\n".join(
                        [
                            "1M Margarita 45,-",
                            "51K Ayko 80,-",
                        ]
                    )
                ),
                authorization="Bearer operator-secret",
            )

            candidates = {candidate.item.id: candidate.item for candidate in preview.candidates}
            self.assertEqual(candidates["margarita"].name, "Margarita")
            self.assertEqual(candidates["ayko"].name, "Ayko")
            pilot.store.close()

    def test_menu_import_ignores_bare_integer_tokens_when_a_name_sits_to_the_right(self) -> None:
        menu_import = load_module("pilot-node/app/pilot_node/menu_import.py")

        tokens = [
            {
                "text": "24",
                "score": 0.99,
                "center_y": 100.0,
                "left": 800.0,
                "right": 830.0,
                "top": 88.0,
                "bottom": 112.0,
                "height": 24.0,
            },
            {
                "text": "Marsala",
                "score": 0.99,
                "center_y": 100.0,
                "left": 850.0,
                "right": 980.0,
                "top": 86.0,
                "bottom": 114.0,
                "height": 28.0,
            },
            {
                "text": "90,-",
                "score": 0.99,
                "center_y": 100.0,
                "left": 1280.0,
                "right": 1340.0,
                "top": 86.0,
                "bottom": 114.0,
                "height": 28.0,
            },
            {
                "text": "41",
                "score": 0.99,
                "center_y": 100.0,
                "left": 1460.0,
                "right": 1490.0,
                "top": 88.0,
                "bottom": 112.0,
                "height": 24.0,
            },
            {
                "text": "Calzone",
                "score": 0.99,
                "center_y": 100.0,
                "left": 1510.0,
                "right": 1650.0,
                "top": 86.0,
                "bottom": 114.0,
                "height": 28.0,
            },
        ]

        lines = menu_import._pair_item_names_with_prices(tokens)

        self.assertIn("Marsala 90,-", lines)
        self.assertNotIn("Marsala 41", lines)

    def test_menu_import_pairs_prices_with_their_own_visual_column(self) -> None:
        menu_import = load_module("pilot-node/app/pilot_node/menu_import.py")

        tokens = [
            {
                "text": "Torino",
                "score": 0.99,
                "center_y": 352.0,
                "left": 87.0,
                "right": 177.0,
                "top": 334.0,
                "bottom": 370.0,
                "height": 36.0,
            },
            {
                "text": "75,-",
                "score": 0.99,
                "center_y": 388.0,
                "left": 699.0,
                "right": 756.0,
                "top": 370.0,
                "bottom": 405.0,
                "height": 35.0,
            },
            {
                "text": "Bella Rosa",
                "score": 0.99,
                "center_y": 459.0,
                "left": 872.0,
                "right": 1015.0,
                "top": 445.0,
                "bottom": 473.0,
                "height": 28.0,
            },
            {
                "text": "90,-",
                "score": 0.99,
                "center_y": 496.0,
                "left": 1488.0,
                "right": 1541.0,
                "top": 480.0,
                "bottom": 511.0,
                "height": 31.0,
            },
            {
                "text": "Ciao Ciao",
                "score": 0.99,
                "center_y": 351.0,
                "left": 1673.0,
                "right": 1793.0,
                "top": 337.0,
                "bottom": 365.0,
                "height": 28.0,
            },
            {
                "text": "80,-",
                "score": 0.99,
                "center_y": 385.0,
                "left": 2255.0,
                "right": 2310.0,
                "top": 368.0,
                "bottom": 402.0,
                "height": 34.0,
            },
        ]

        lines = menu_import._pair_item_names_with_prices(tokens)

        self.assertIn("Torino 75,-", lines)
        self.assertIn("Bella Rosa 90,-", lines)
        self.assertIn("Ciao Ciao 80,-", lines)
        self.assertNotIn("Torino 90,-", lines)
        self.assertNotIn("Bella Rosa 80,-", lines)

    def test_menu_import_recovers_lower_right_items_with_offset_prices(self) -> None:
        menu_import = load_module("pilot-node/app/pilot_node/menu_import.py")

        tokens = [
            {
                "text": "Sandwich",
                "score": 0.99,
                "center_y": 853.0,
                "left": 1672.0,
                "right": 1794.0,
                "top": 839.0,
                "bottom": 867.0,
                "height": 28.0,
            },
            {
                "text": "80",
                "score": 0.99,
                "center_y": 953.0,
                "left": 2259.0,
                "right": 2304.0,
                "top": 940.0,
                "bottom": 966.0,
                "height": 26.0,
            },
            {
                "text": "Pitabrod",
                "score": 0.99,
                "center_y": 1068.0,
                "left": 1667.0,
                "right": 1780.0,
                "top": 1054.0,
                "bottom": 1082.0,
                "height": 28.0,
            },
            {
                "text": "60,-",
                "score": 0.99,
                "center_y": 1168.0,
                "left": 2259.0,
                "right": 2304.0,
                "top": 1155.0,
                "bottom": 1181.0,
                "height": 26.0,
            },
            {
                "text": "Durum",
                "score": 0.99,
                "center_y": 1283.0,
                "left": 1668.0,
                "right": 1758.0,
                "top": 1271.0,
                "bottom": 1296.0,
                "height": 25.0,
            },
            {
                "text": "85,-",
                "score": 0.99,
                "center_y": 1384.0,
                "left": 2256.0,
                "right": 2306.0,
                "top": 1369.0,
                "bottom": 1400.0,
                "height": 31.0,
            },
            {
                "text": "51K Ayko",
                "score": 0.99,
                "center_y": 1417.0,
                "left": 1612.0,
                "right": 1731.0,
                "top": 1401.0,
                "bottom": 1432.0,
                "height": 31.0,
            },
            {
                "text": "80,-",
                "score": 0.99,
                "center_y": 1485.0,
                "left": 2258.0,
                "right": 2307.0,
                "top": 1470.0,
                "bottom": 1501.0,
                "height": 31.0,
            },
            {
                "text": "85,-",
                "score": 0.99,
                "center_y": 1431.0,
                "left": 1488.0,
                "right": 1541.0,
                "top": 1416.0,
                "bottom": 1447.0,
                "height": 31.0,
            },
        ]

        lines = menu_import._pair_item_names_with_prices(tokens)

        self.assertIn("Sandwich 80", lines)
        self.assertIn("Pitabrod 60,-", lines)
        self.assertIn("Durum 85,-", lines)
        self.assertIn("51K Ayko 80,-", lines)
        self.assertNotIn("51K Ayko 85,-", lines)

    def test_pilot_node_menu_import_preview_ignores_size_and_modifier_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            preview = pilot.operator_menu_import_preview(
                pilot.MenuImportPreviewRequest(
                    raw_text="\n".join(
                        [
                            "33cm 9,00",
                            "(3pezzi) 4,00",
                            "(rosso) 2,00",
                            "verdurepastellate 10,00",
                            "CHINOTTO/LIMONATA33cl 2,50",
                        ]
                    )
                ),
                authorization="Bearer operator-secret",
            )

            candidate_ids = [candidate.item.id for candidate in preview.candidates]
            self.assertEqual(candidate_ids, ["verdure-pastellate", "chinotto-limonata-33-cl"])
            candidates = {candidate.item.id: candidate.item for candidate in preview.candidates}
            self.assertEqual(candidates["verdure-pastellate"].name, "verdure pastellate")
            self.assertEqual(candidates["chinotto-limonata-33-cl"].category, "drink")
            self.assertIn("33cm 9,00", preview.ignored_lines)
            self.assertIn("(3pezzi) 4,00", preview.ignored_lines)
            self.assertIn("(rosso) 2,00", preview.ignored_lines)
            pilot.store.close()

    def test_pilot_node_menu_import_image_preview_extracts_draft_items_from_fixture(self) -> None:
        fixture_path = REPO_ROOT / "docs/examples/menu-photo-map-fixtures/copenhagen-pizza-grill-paper-menu.png"
        if not fixture_path.exists():
            self.skipTest("Menu photo-map fixture is missing.")
        try:
            import onnxruntime  # noqa: F401
            import rapidocr  # noqa: F401
        except ImportError:
            self.skipTest("Local OCR dependencies are not installed.")

        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "menu_only",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            before_menu = pilot.operator_menu(authorization="Bearer operator-secret")
            preview = pilot.operator_menu_import_image_preview(
                fixture_path.read_bytes(),
                source_name="copenhagen-pizza-grill-paper-menu.png",
                authorization="Bearer operator-secret",
            )
            after_menu = pilot.operator_menu(authorization="Bearer operator-secret")

            self.assertEqual(preview.source_kind, "ocr_image")
            self.assertEqual(preview.source_name, "copenhagen-pizza-grill-paper-menu.png")
            self.assertIsNotNone(preview.extracted_text)
            self.assertGreater(preview.ocr_line_count or 0, 0)
            self.assertIn("Margherita", preview.extracted_text or "")
            candidate_ids = {candidate.item.id for candidate in preview.candidates}
            self.assertIn("margherita", candidate_ids)
            self.assertIn("vesuvio", candidate_ids)
            self.assertIn("durum-kebab", candidate_ids)
            self.assertTrue(any("image ocr is approximate" in warning.lower() for warning in preview.warnings))
            self.assertEqual(
                [item.model_dump(mode="json") for item in before_menu.items],
                [item.model_dump(mode="json") for item in after_menu.items],
            )
            self.assertEqual(
                pilot.root_index()["endpoints"]["operator_menu_import_image_preview"],
                "POST /operator/menu/import-image-preview",
            )
            pilot.store.close()

    def test_pilot_node_menu_import_image_preview_requires_operator_token(self) -> None:
        fixture_path = REPO_ROOT / "docs/examples/menu-photo-map-fixtures/copenhagen-pizza-grill-paper-menu.png"
        try:
            import onnxruntime  # noqa: F401
            import rapidocr  # noqa: F401
        except ImportError:
            self.skipTest("Local OCR dependencies are not installed.")
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as auth_error:
                pilot.operator_menu_import_image_preview(fixture_path.read_bytes())

            self.assertEqual(auth_error.exception.status_code, 401)
            pilot.store.close()

    def test_pilot_node_menu_list_module_exposes_active_catalog_as_customer_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            pilot.operator_replace_menu(
                pilot.MenuUpdate(
                    items=[
                        pilot.MenuItem(
                            id="pizza-17",
                            name="Pizza 17",
                            description="Tomato, cheese, chili",
                            price=8900,
                            category="pizza",
                            active=True,
                            image_url="/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png",
                        ),
                        pilot.MenuItem(
                            id="durum-test",
                            name="Durum Test",
                            description="Hidden from public menu",
                            price=7500,
                            category="kebab",
                            active=False,
                        ),
                    ]
                ),
                authorization="Bearer operator-secret",
            )

            modules = pilot.operator_modules(authorization="Bearer operator-secret")
            menu_entry = {
                entry["module_id"]: entry
                for entry in modules["lanes"]["public_capability"]["modules"]
            }["p4p.menu.list"]
            info = pilot.public_info()
            page = pilot.public_menu_list_page()
            page_sv = pilot.public_menu_list_page(locale="sv")
            active_order = pilot.public_order(
                pilot.OrderRequest(
                    customer_name="Anna Hansen",
                    customer_contact="+4512345678",
                    fulfillment="pickup",
                    items=[pilot.OrderItem(id="pizza-17", quantity=1)],
                    note="Menu list test",
                    client_version="p4p-menu-list-0.1",
                )
            )
            row = pilot.store._connection.execute(
                "SELECT event_json FROM order_events WHERE source_module = ?",
                ("p4p.menu.list",),
            ).fetchone()

            self.assertTrue(menu_entry["active"])
            self.assertTrue(menu_entry["configured"])
            self.assertTrue(menu_entry["executable"])
            self.assertEqual(menu_entry["implementation"], "builtin_customer_surface")
            self.assertEqual(menu_entry["health"], "available")
            self.assertIn("p4p.menu.list", info["modules"])
            self.assertIn("Pizza 17", page)
            self.assertIn("Tomato, cheese, chili", page)
            self.assertIn("89.00 DKK", page)
            self.assertIn('data-item-id="pizza-17"', page)
            self.assertIn('class="item has-image"', page)
            self.assertIn('src="/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png"', page)
            self.assertNotIn("Durum Test", page)
            self.assertIn('fetch("/p4p/order?lang=da"', page)
            self.assertIn("p4p-menu-list-0.1", page)
            self.assertIn("/p4p/orders/${encodeURIComponent(body.order_id)}", page)
            self.assertIn('<html lang="sv" dir="ltr">', page_sv)
            self.assertIn("Skicka order", page_sv)
            self.assertIn("Språk", page_sv)
            self.assertTrue(active_order.accepted)
            status_page_ar = pilot.public_order_status_page(active_order.order_id, locale="ar")
            self.assertIn('<html lang="ar" dir="rtl">', status_page_ar)
            self.assertIn("حالة الطلب", status_page_ar)
            self.assertIn("العودة إلى القائمة", status_page_ar)
            self.assertIsNotNone(row)
            event = json.loads(str(row["event_json"]))
            self.assertEqual(event["event"], "CUSTOMER_MENU_VIEWED")
            self.assertEqual(event["source_module"], "p4p.menu.list")
            self.assertEqual(event["metadata"]["active_item_count"], 1)
            self.assertFalse(event["metadata"]["exposes_inactive_items"])
            pilot.store.close()

    def test_pilot_node_menu_list_endpoint_requires_enabled_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as missing_module:
                pilot.public_menu_list_page()

            self.assertEqual(missing_module.exception.status_code, 404)
            self.assertEqual(missing_module.exception.detail, "Menu list module is not enabled")
            pilot.store.close()

    def test_pilot_node_photo_map_module_exposes_catalog_as_clickable_customer_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.menu.photo-map,p4p.customer.status,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            pilot.operator_replace_menu(
                pilot.MenuUpdate(
                    items=[
                        pilot.MenuItem(
                            id="pizza-17",
                            name="Pizza 17",
                            description="Tomato, cheese, chili",
                            price=8900,
                            category="pizza",
                            active=True,
                            image_url="/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png",
                        ),
                        pilot.MenuItem(
                            id="durum-test",
                            name="Durum Test",
                            description="Hidden from photo map",
                            price=7500,
                            category="kebab",
                            active=False,
                        ),
                    ]
                ),
                authorization="Bearer operator-secret",
            )

            modules = pilot.operator_modules(authorization="Bearer operator-secret")
            photo_entry = {
                entry["module_id"]: entry
                for entry in modules["lanes"]["public_capability"]["modules"]
            }["p4p.menu.photo-map"]
            info = pilot.public_info()
            page = pilot.public_menu_photo_map_page()
            page_ar = pilot.public_menu_photo_map_page(locale="ar")
            active_order = pilot.public_order(
                pilot.OrderRequest(
                    customer_name="Anna Hansen",
                    customer_contact="+4512345678",
                    fulfillment="pickup",
                    items=[pilot.OrderItem(id="pizza-17", quantity=1)],
                    note="Photo map test",
                    client_version="p4p-menu-photo-map-0.1",
                )
            )
            row = pilot.store._connection.execute(
                "SELECT event_json FROM order_events WHERE source_module = ?",
                ("p4p.menu.photo-map",),
            ).fetchone()

            self.assertTrue(photo_entry["active"])
            self.assertTrue(photo_entry["configured"])
            self.assertTrue(photo_entry["executable"])
            self.assertEqual(photo_entry["implementation"], "builtin_customer_surface")
            self.assertEqual(photo_entry["health"], "available")
            self.assertIn("p4p.menu.photo-map", info["modules"])
            self.assertIn("Fotomenu", page)
            self.assertIn("Pizza 17", page)
            self.assertIn("Tomato, cheese, chili", page)
            self.assertIn("89.00 DKK", page)
            self.assertIn('data-photo-map-item-id="pizza-17"', page)
            self.assertIn('data-photo-map-mode="catalog-derived-regions"', page)
            self.assertIn('class="hotspot has-image"', page)
            self.assertIn('src="/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png"', page)
            self.assertNotIn("Durum Test", page)
            self.assertIn('fetch("/p4p/order?lang=da"', page)
            self.assertIn("p4p-menu-photo-map-0.1", page)
            self.assertIn("/p4p/orders/${encodeURIComponent(body.order_id)}", page)
            self.assertIn('<html lang="ar" dir="rtl">', page_ar)
            self.assertIn("أرسل الطلب", page_ar)
            self.assertIn("اللغة", page_ar)
            self.assertTrue(active_order.accepted)
            self.assertIsNotNone(row)
            event = json.loads(str(row["event_json"]))
            self.assertEqual(event["event"], "CUSTOMER_MENU_VIEWED")
            self.assertEqual(event["source_module"], "p4p.menu.photo-map")
            self.assertEqual(event["metadata"]["active_item_count"], 1)
            self.assertEqual(event["metadata"]["region_count"], 1)
            self.assertEqual(event["metadata"]["map_mode"], "catalog-derived-regions")
            self.assertFalse(event["metadata"]["exposes_inactive_items"])
            pilot.store.close()

    def test_pilot_node_photo_map_endpoint_requires_enabled_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as missing_module:
                pilot.public_menu_photo_map_page()

            self.assertEqual(missing_module.exception.status_code, 404)
            self.assertEqual(missing_module.exception.detail, "Photo map menu module is not enabled")
            pilot.store.close()

    def test_pilot_node_external_payment_requires_explicit_customer_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pizzacoin_manifest = REPO_ROOT.parent / "Pizzacoin" / "contracts" / "module.json"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "local.pizzacoin.wallet,p4p.order.print",
                    "P4P_EXTERNAL_MODULE_MANIFESTS": str(pizzacoin_manifest),
                    "P4P_PAYMENT_MODULE_ID": "local.pizzacoin.wallet",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            execution = sys.modules["pilot_node.execution"]
            payment_client = ExternalPaymentClient(confirmed=True)
            with patch.object(execution.httpx, "Client", return_value=payment_client):
                accepted = pilot.public_order(self.make_pilot_order_request(pilot))

            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(runtime.config.flow_module_ids, ("local.pizzacoin.wallet", "p4p.order.print"))
            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PAYMENT_REQUIRED", "PAYMENT_FAILED", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].source_module, "local.pizzacoin.wallet")
            self.assertEqual(events[2].reason_code, "PAYMENT_CUSTOMER_USER_ID_MISSING")
            self.assertEqual(events[3].metadata["trigger_event"], "PAYMENT_FAILED")
            self.assertEqual(payment_client.posts, [])
            self.assertEqual(stored[0].status_message, "Order accepted. External payment needs human attention.")
            pilot.store.close()

    def test_pilot_node_persists_orders_and_operator_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_OPEN": "true",
                "P4P_NODE_ORDER_MODE": "live",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            self.assertTrue(accepted.accepted)

            stored_orders = pilot.operator_orders(authorization="Bearer operator-secret")
            self.assertEqual(len(stored_orders), 1)
            self.assertEqual(stored_orders[0].order_id, accepted.order_id)
            self.assertEqual(stored_orders[0].customer_contact, "+4512345678")

            updated = pilot.operator_update_order(
                accepted.order_id,
                pilot.OrderStatusUpdate(status="accepted", status_message="Seen by kitchen"),
                authorization="Bearer operator-secret",
            )
            self.assertEqual(updated.status, "accepted")
            self.assertEqual(updated.status_message, "Seen by kitchen")

            pilot.store.close()
            reloaded = load_module("pilot-node/pilot_node.py", env)
            persisted_orders = reloaded.operator_orders(authorization="Bearer operator-secret")
            self.assertEqual(len(persisted_orders), 1)
            self.assertEqual(persisted_orders[0].order_id, accepted.order_id)
            self.assertEqual(persisted_orders[0].status, "accepted")
            reloaded.store.close()

    def test_pilot_node_print_module_emits_confirmed_result_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PRINT_SUCCESS_CONFIRMED"],
            )
            self.assertEqual(events[1].metadata["contract_phase"], "request")
            self.assertEqual(events[2].metadata["contract_phase"], "result")
            self.assertEqual(events[-1].outcome, "SUCCESS")
            self.assertEqual(events[-1].metadata["adapter_target"], "printer")
            self.assertEqual(stored[0].status, "accepted")
            self.assertEqual(stored[0].status_message, "Order accepted. Print confirmed.")
            pilot.store.close()

    def test_pilot_node_payment_cash_lane_marks_pay_at_pickup_before_print(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")
            execution = sys.modules["pilot_node.execution"]
            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME

            self.assertEqual(
                [event.event for event in events],
                [
                    "ORDER_ACCEPTED",
                    "PAYMENT_REQUIRED",
                    "PAYMENT_MODE_CHANGED",
                    "PRINT_REQUESTED",
                    "PRINT_SUCCESS_CONFIRMED",
                ],
            )
            self.assertEqual(events[1].source_module, "p4p.payment.cash")
            self.assertEqual(events[1].metadata["contract_phase"], "request")
            self.assertEqual(events[2].metadata["payment_scope"], "outside_protocol")
            self.assertEqual(events[2].metadata["trigger_event"], "PAYMENT_REQUIRED")
            self.assertEqual(events[3].metadata["contract_phase"], "request")
            self.assertEqual(
                [executor.module_id for executor in execution.enabled_module_executors(runtime, lane="payment")],
                ["p4p.payment.cash"],
            )
            self.assertEqual(stored[0].status_message, "Order accepted. Print confirmed.")
            pilot.store.close()

    def test_pilot_node_payment_cash_failure_stops_before_print_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "should-not-print-payment.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print",
                    "P4P_PAYMENT_CASH_MODE": "failed",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PAYMENT_REQUIRED", "PAYMENT_FAILED", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].source_module, "p4p.payment.cash")
            self.assertEqual(events[2].reason_code, "PAYMENT_MODE_UNAVAILABLE")
            self.assertEqual(events[3].metadata["trigger_event"], "PAYMENT_FAILED")
            self.assertEqual(stored[0].status_message, "Order accepted. Payment mode needs human attention.")
            self.assertFalse(device_path.exists())
            pilot.store.close()

    def test_pilot_node_godpay_mock_success_records_roll_and_continues_to_print(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.godpay-mock,p4p.order.print",
                    "P4P_PAYMENT_MODULE_ID": "p4p.payment.godpay-mock",
                    "P4P_GODPAY_SUCCESS_THRESHOLD": "100",
                    "P4P_GODPAY_FORCE_ROLL": "88",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")
            operator_modules = pilot.operator_modules(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                [
                    "ORDER_ACCEPTED",
                    "PAYMENT_REQUIRED",
                    "PAYMENT_MODE_CHANGED",
                    "PRINT_REQUESTED",
                    "PRINT_SUCCESS_CONFIRMED",
                ],
            )
            self.assertEqual(events[1].source_module, "p4p.payment.godpay-mock")
            self.assertEqual(events[2].source_module, "p4p.payment.godpay-mock")
            self.assertEqual(events[2].metadata["payment_scope"], "internal_mock")
            self.assertEqual(events[2].metadata["real_payment"], False)
            self.assertEqual(events[2].metadata["roll"], 88)
            self.assertEqual(events[2].metadata["success_threshold"], 100)
            self.assertEqual(events[2].metadata["message"], "The pizza gods accepted the offering.")
            self.assertEqual(stored[0].payment_method, "godpay_mock")
            self.assertEqual(stored[0].status_message, "Order accepted. Print confirmed.")
            godpay = {
                entry["module_id"]: entry
                for entry in operator_modules["lanes"]["payment"]["modules"]
            }["p4p.payment.godpay-mock"]
            self.assertTrue(godpay["active"])
            self.assertTrue(godpay["configured"])
            self.assertTrue(godpay["executable"])
            self.assertEqual(godpay["implementation"], "internal_mock")
            self.assertEqual(godpay["configuration"]["success_threshold"], 100)
            self.assertEqual(godpay["configuration"]["forced_roll"], 88)
            pilot.store.close()

    def test_pilot_node_godpay_mock_failure_stops_before_print_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "should-not-print-godpay.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.godpay-mock,p4p.order.print",
                    "P4P_PAYMENT_MODULE_ID": "p4p.payment.godpay-mock",
                    "P4P_GODPAY_SUCCESS_THRESHOLD": "0",
                    "P4P_GODPAY_FORCE_ROLL": "1",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PAYMENT_REQUIRED", "PAYMENT_FAILED", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].source_module, "p4p.payment.godpay-mock")
            self.assertEqual(events[2].reason_code, "GODPAY_DECLINED")
            self.assertTrue(events[2].retryable)
            self.assertEqual(events[2].metadata["roll"], 1)
            self.assertEqual(events[2].metadata["success_threshold"], 0)
            self.assertEqual(events[2].metadata["message"], "The pizza gods declined this order.")
            self.assertEqual(events[3].metadata["trigger_event"], "PAYMENT_FAILED")
            self.assertEqual(stored[0].payment_method, "pay_at_pickup")
            self.assertEqual(stored[0].status_message, "The pizza gods declined this order.")
            self.assertFalse(device_path.exists())
            pilot.store.close()

    def test_pilot_node_chaospay_mock_is_declared_but_not_executable_yet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.payment.chaospay-mock",
                    "P4P_PAYMENT_MODULE_ID": "p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            info = pilot.public_info()
            operator_modules = pilot.operator_modules(authorization="Bearer operator-secret")
            payment_modules = {
                entry["module_id"]: entry
                for entry in operator_modules["lanes"]["payment"]["modules"]
            }

            self.assertEqual(info["modules"], ["p4p.payment.cash"])
            self.assertFalse(payment_modules["p4p.payment.chaospay-mock"]["active"])
            self.assertFalse(payment_modules["p4p.payment.chaospay-mock"]["configured"])
            self.assertFalse(payment_modules["p4p.payment.chaospay-mock"]["executable"])
            self.assertEqual(payment_modules["p4p.payment.chaospay-mock"]["implementation"], "internal_mock_planned")
            self.assertEqual(payment_modules["p4p.payment.chaospay-mock"]["health"], "not_configured")
            self.assertIn(
                "invalid_signature",
                payment_modules["p4p.payment.chaospay-mock"]["configuration"]["scenarios"],
            )
            pilot.store.close()

    def test_pilot_node_operator_can_persist_active_payment_module_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_OPEN": "true",
                "P4P_NODE_ORDER_MODE": "live",
                "P4P_NODE_MODULES": "p4p.payment.cash,p4p.payment.godpay-mock,p4p.order.print",
                "P4P_GODPAY_SUCCESS_THRESHOLD": "100",
                "P4P_GODPAY_FORCE_ROLL": "42",
                "P4P_PRINT_MODULE_MODE": "confirmed",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)
            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            execution = sys.modules["pilot_node.execution"]

            before = pilot.operator_modules(authorization="Bearer operator-secret")
            self.assertEqual(before["active_by_lane"]["payment"], "p4p.payment.cash")

            after = pilot.operator_update_payment_module(
                pilot.OperatorPaymentModuleUpdate(module_id="p4p.payment.godpay-mock"),
                authorization="Bearer operator-secret",
            )
            self.assertEqual(runtime.config.payment_module_id, "p4p.payment.cash")
            self.assertEqual(after["active_by_lane"]["payment"], "p4p.payment.godpay-mock")
            self.assertEqual(
                [executor.module_id for executor in execution.enabled_module_executors(runtime, lane="payment")],
                ["p4p.payment.godpay-mock"],
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                [
                    "ORDER_ACCEPTED",
                    "PAYMENT_REQUIRED",
                    "PAYMENT_MODE_CHANGED",
                    "PRINT_REQUESTED",
                    "PRINT_SUCCESS_CONFIRMED",
                ],
            )
            self.assertEqual(events[1].source_module, "p4p.payment.godpay-mock")
            self.assertEqual(events[2].metadata["roll"], 42)
            pilot.store.close()

            reloaded = load_module("pilot-node/pilot_node.py", env)
            reloaded_modules = reloaded.operator_modules(authorization="Bearer operator-secret")
            self.assertEqual(reloaded_modules["active_by_lane"]["payment"], "p4p.payment.godpay-mock")
            reloaded.store.close()

    def test_pilot_node_operator_modules_expose_current_desired_and_available_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            modules = pilot.operator_modules(authorization="Bearer operator-secret")

            self.assertEqual(modules["current_module_ids"], ["p4p.catalog.editor", "p4p.payment.cash"])
            self.assertEqual(modules["desired_module_ids"], ["p4p.catalog.editor", "p4p.payment.cash"])
            self.assertFalse(modules["restart_required"])
            available_module_ids = [entry["module_id"] for entry in modules["available_modules"]]
            self.assertIn("p4p.catalog.import.ocr", available_module_ids)
            self.assertIn("p4p.menu.list", available_module_ids)
            pilot.store.close()

    def test_pilot_node_operator_module_detail_supports_enabled_and_available_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            enabled_detail = pilot.operator_module_detail(
                "p4p.catalog.editor",
                authorization="Bearer operator-secret",
            )
            available_detail = pilot.operator_module_detail(
                "p4p.catalog.import.ocr",
                authorization="Bearer operator-secret",
            )
            module_page = pilot.operator_module_view_page("p4p.catalog.editor")
            ocr_module_page = pilot.operator_module_view_page("p4p.catalog.import.ocr")

            self.assertTrue(enabled_detail["module"]["enabled_now"])
            self.assertTrue(enabled_detail["module"]["desired_enabled"])
            self.assertIn("CATALOG_UPDATED", enabled_detail["module"]["output_events"])
            self.assertFalse(available_detail["module"]["enabled_now"])
            self.assertFalse(available_detail["module"]["active"])
            self.assertEqual(
                available_detail["documentation"]["links"]["module_doc_url"],
                "https://github.com/DennisHedegreen/p4p/blob/main/docs/modules/p4p.catalog.import.ocr.md",
            )
            self.assertIn("/operator/modules/", module_page)
            self.assertIn("Module detail", module_page)
            self.assertIn("OCR import surface", ocr_module_page)
            self.assertIn("Scan photo", ocr_module_page)
            self.assertIn("Save selected to catalog", ocr_module_page)
            self.assertIn("/operator/menu/import-image-preview", ocr_module_page)

            with self.assertRaises(HTTPException) as missing:
                pilot.operator_module_detail("local.missing.module", authorization="Bearer operator-secret")

            self.assertEqual(missing.exception.status_code, 404)
            pilot.store.close()

    def test_pilot_node_operator_module_set_persists_desired_modules_until_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.payment.cash",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)

            updated = pilot.operator_update_module_set(
                pilot.OperatorModuleSetUpdate(
                    module_ids=["p4p.catalog.editor", "p4p.catalog.import.ocr", "p4p.payment.cash"]
                ),
                authorization="Bearer operator-secret",
            )

            self.assertEqual(updated["current_module_ids"], ["p4p.catalog.editor", "p4p.payment.cash"])
            self.assertEqual(
                updated["desired_module_ids"],
                ["p4p.catalog.editor", "p4p.catalog.import.ocr", "p4p.payment.cash"],
            )
            self.assertTrue(updated["restart_required"])
            pilot.store.close()

            reloaded = load_module("pilot-node/pilot_node.py", env)
            reloaded_modules = reloaded.operator_modules(authorization="Bearer operator-secret")
            self.assertEqual(
                reloaded_modules["current_module_ids"],
                ["p4p.catalog.editor", "p4p.catalog.import.ocr", "p4p.payment.cash"],
            )
            self.assertEqual(
                reloaded_modules["desired_module_ids"],
                ["p4p.catalog.editor", "p4p.catalog.import.ocr", "p4p.payment.cash"],
            )
            self.assertFalse(reloaded_modules["restart_required"])
            reloaded.store.close()

    def test_pilot_node_operator_module_set_rejects_unknown_or_paymentless_or_dependency_breaking_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.catalog.editor,p4p.catalog.import.ocr,p4p.payment.cash",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as unknown:
                pilot.operator_update_module_set(
                    pilot.OperatorModuleSetUpdate(module_ids=["p4p.payment.cash", "local.unknown.module"]),
                    authorization="Bearer operator-secret",
                )
            with self.assertRaises(HTTPException) as paymentless:
                pilot.operator_update_module_set(
                    pilot.OperatorModuleSetUpdate(module_ids=["p4p.catalog.editor"]),
                    authorization="Bearer operator-secret",
                )
            with self.assertRaises(HTTPException) as missing_dependency:
                pilot.operator_update_module_set(
                    pilot.OperatorModuleSetUpdate(module_ids=["p4p.catalog.import.ocr", "p4p.payment.cash"]),
                    authorization="Bearer operator-secret",
                )

            self.assertEqual(unknown.exception.status_code, 400)
            self.assertEqual(paymentless.exception.status_code, 400)
            self.assertEqual(missing_dependency.exception.status_code, 400)
            self.assertIn("Unknown module_id", str(unknown.exception.detail))
            self.assertIn("payment", str(paymentless.exception.detail).lower())
            self.assertIn("still depend on it", str(missing_dependency.exception.detail))
            pilot.store.close()

    def test_pilot_node_operator_module_set_reassigns_payment_when_desired_set_removes_active_payment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.payment.godpay-mock",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            pilot.operator_update_payment_module(
                pilot.OperatorPaymentModuleUpdate(module_id="p4p.payment.godpay-mock"),
                authorization="Bearer operator-secret",
            )
            updated = pilot.operator_update_module_set(
                pilot.OperatorModuleSetUpdate(module_ids=["p4p.payment.cash"]),
                authorization="Bearer operator-secret",
            )

            self.assertEqual(updated["desired_module_ids"], ["p4p.payment.cash"])
            self.assertEqual(updated["desired_active_by_lane"]["payment"], "p4p.payment.cash")
            self.assertEqual(updated["active_by_lane"]["payment"], "p4p.payment.cash")
            pilot.store.close()

    def test_pilot_node_operator_setup_persists_onboarding_state_in_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_ORDER_MODE": "menu_only",
                "P4P_NODE_MODULES": (
                    "p4p.catalog.editor,p4p.menu.list,p4p.customer.status,"
                    "p4p.kitchen.screen,p4p.payment.cash"
                ),
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)

            before = pilot.operator_setup(authorization="Bearer operator-secret")
            self.assertIsNone(before["setup"]["started_at"])
            self.assertEqual(before["summary"]["status"], "incomplete")

            updated = pilot.operator_update_setup(
                pilot.OperatorSetupUpdate(
                    operator_locale="tr",
                    hardware_base_profile="counter_box",
                    hardware_enabled_addons=[
                        "ticket_printer",
                        "backup_spool",
                        "order_alert",
                        "pickup_board",
                    ],
                    catalog_ready=True,
                    local_tests_run=True,
                ),
                authorization="Bearer operator-secret",
            )

            self.assertEqual(updated["setup"]["operator_locale"], "tr")
            self.assertEqual(updated["setup"]["locale"]["current"], "tr")
            self.assertIn("en", [choice["id"] for choice in updated["setup"]["locale"]["choices"]])
            self.assertEqual(updated["setup"]["hardware_profile"], "box_v1_counter")
            self.assertEqual(updated["setup"]["hardware_base_profile"], "counter_box")
            self.assertEqual(
                updated["setup"]["hardware_enabled_addons"],
                ["ticket_printer", "backup_spool", "order_alert", "pickup_board"],
            )
            self.assertTrue(updated["setup"]["catalog_ready"])
            self.assertIn("catalog_reviewed", updated["setup"]["completed_steps"])
            self.assertIn("local_tests_run", updated["setup"]["completed_steps"])
            self.assertEqual(updated["setup"]["payment_module_id"], "p4p.payment.cash")
            self.assertEqual(updated["summary"]["status"], "menu_only-ready")
            self.assertTrue(updated["summary"]["ready_for_menu_only"])
            self.assertIsNotNone(updated["setup"]["completed_at"])
            pilot.store.close()

            reloaded = load_module("pilot-node/pilot_node.py", env)
            reloaded_setup = reloaded.operator_setup(authorization="Bearer operator-secret")
            self.assertEqual(reloaded_setup["setup"]["operator_locale"], "tr")
            self.assertEqual(reloaded_setup["setup"]["locale"]["current"], "tr")
            self.assertEqual(reloaded_setup["setup"]["hardware_profile"], "box_v1_counter")
            self.assertEqual(reloaded_setup["setup"]["hardware_base_profile"], "counter_box")
            self.assertEqual(
                reloaded_setup["setup"]["hardware_enabled_addons"],
                ["ticket_printer", "backup_spool", "order_alert", "pickup_board"],
            )
            self.assertTrue(reloaded_setup["setup"]["catalog_ready"])
            self.assertIn("local_tests_run", reloaded_setup["setup"]["completed_steps"])
            self.assertIsNotNone(reloaded_setup["setup"]["started_at"])
            self.assertIsNotNone(reloaded_setup["setup"]["last_reviewed_at"])
            reloaded.store.close()

    def test_pilot_node_operator_discover_and_node_rooms_share_public_catalog_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_ORDER_MODE": "menu_only",
                "P4P_NODE_MODULES": (
                    "p4p.catalog.editor,p4p.menu.list,p4p.customer.status,"
                    "p4p.kitchen.screen,p4p.payment.cash"
                ),
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)

            pilot.operator_update_setup(
                pilot.OperatorSetupUpdate(operator_locale="ar"),
                authorization="Bearer operator-secret",
            )
            discover = pilot.operator_discover(authorization="Bearer operator-secret")
            node_room = pilot.operator_node(authorization="Bearer operator-secret")

            self.assertEqual(discover["locale"]["current"], "ar")
            self.assertTrue(discover["locale"]["is_rtl"])
            self.assertEqual(discover["family"]["id"], "shop")
            self.assertIn("public_catalog_url", discover["links"])
            self.assertIn("shop_family_url", discover["links"])
            self.assertEqual(discover["links"]["modules_room_url"], "/operator/modules")
            self.assertFalse(any("install" in entry for entry in discover["recommended_modules"]))
            recommended_ids = [entry["module_id"] for entry in discover["recommended_modules"]]
            self.assertIn("p4p.catalog.editor", recommended_ids)
            self.assertIn("p4p.payment.cash", recommended_ids)

            self.assertEqual(node_room["locale"]["current"], "ar")
            self.assertIn("hardware", node_room)
            self.assertIn("setup", node_room)
            self.assertIn("modules", node_room)
            self.assertIn("links", node_room)
            self.assertEqual(node_room["links"]["discover_url"], "/operator/discover")
            self.assertEqual(node_room["links"]["modules_url"], "/operator/modules")
            self.assertEqual(node_room["links"]["setup_url"], "/operator/setup")
            pilot.store.close()

    def test_pilot_node_operator_locale_prefers_query_then_cookie_then_node_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_MODULES": "p4p.payment.cash",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)
            routes = load_module("pilot-node/app/pilot_node/routes.py", env)

            pilot.operator_update_setup(
                pilot.OperatorSetupUpdate(operator_locale="tr"),
                authorization="Bearer operator-secret",
            )

            async def receive() -> dict[str, object]:
                return {"type": "http.request", "body": b"", "more_body": False}

            cookie_request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/operator/setup",
                    "query_string": b"",
                    "headers": [(b"cookie", b"p4p_operator_locale=sv")],
                },
                receive,
            )
            query_request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/operator/setup",
                    "query_string": b"lang=ar",
                    "headers": [(b"cookie", b"p4p_operator_locale=sv")],
                },
                receive,
            )
            clear_request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/operator/setup",
                    "query_string": b"lang=default",
                    "headers": [(b"cookie", b"p4p_operator_locale=sv")],
                },
                receive,
            )

            cookie_locale, cookie_source = routes.operator_locale_source(pilot._app.RUNTIME, cookie_request)
            query_locale, query_source = routes.operator_locale_source(pilot._app.RUNTIME, query_request)
            clear_locale, clear_source = routes.operator_locale_source(pilot._app.RUNTIME, clear_request)

            self.assertEqual((cookie_locale, cookie_source), ("sv", "cookie"))
            self.assertEqual((query_locale, query_source), ("ar", "query"))
            self.assertEqual((clear_locale, clear_source), ("tr", "node_default"))

            response = Response()
            routes.apply_operator_locale_cookie(response, query_request, query_locale)
            self.assertIn("p4p_operator_locale=ar", response.headers.get("set-cookie", ""))

            clear_response = Response()
            routes.apply_operator_locale_cookie(clear_response, clear_request, clear_locale)
            self.assertIn("p4p_operator_locale=\"\"", clear_response.headers.get("set-cookie", ""))
            pilot.store.close()

    def test_pilot_node_reference_manifests_accept_localized_human_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_MODULES": "p4p.payment.cash",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            core = load_module("p4p_core/modules.py", env)
            manifest_payload = json.loads((REPO_ROOT / "modules/p4p.menu.list/module.json").read_text(encoding="utf-8"))
            provider_payload = json.loads((REPO_ROOT / "modules/p4p.menu.list/provider.json").read_text(encoding="utf-8"))

            manifest_payload["description"] = {"da": "Direkte menu", "en": "Direct menu"}
            manifest_payload["public_catalog"]["function"] = {"da": "Vis menu", "en": "Show menu"}
            manifest_payload["public_catalog"]["summary"] = {"da": "Kort tekst", "en": "Short text"}
            manifest_payload["public_catalog"]["operator_status"] = {"da": "Ikke aktiveret", "en": "Not enabled"}
            provider_payload["name"] = {"da": "P4P Reference", "en": "P4P Reference"}
            provider_payload["description"] = {"da": "Referenceprovider", "en": "Reference provider"}

            manifest = core.ModuleManifest.from_payload(manifest_payload, source_path=REPO_ROOT / "modules/p4p.menu.list/module.json")
            provider = core.ProviderManifest.from_payload(provider_payload, source_path=REPO_ROOT / "modules/p4p.menu.list/provider.json")

            self.assertEqual(manifest.description, "Direct menu")
            self.assertEqual(manifest.operator_status, "Not enabled")
            self.assertEqual(provider.name, "P4P Reference")
            self.assertEqual(provider.description, "Reference provider")

    def test_pilot_node_operator_import_manifest_persists_metadata_only_without_touching_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_MODULES": "p4p.payment.cash",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_node.py", env)
            payload = json.loads((REPO_ROOT / "modules/p4p.menu.list/module.json").read_text(encoding="utf-8"))
            payload["module_id"] = "local.demo.customer.menu"
            payload["provider_id"] = "local.demo"
            payload["version"] = "0.2"
            payload["public_catalog"]["title"] = {"da": "Lokal menuvisning", "en": "Local menu view"}
            payload["public_catalog"]["summary"] = {"da": "Kun metadata på noden.", "en": "Metadata only on the node."}

            imported = pilot.operator_import_module_manifest(
                source_name="module.json",
                content_bytes=json.dumps(payload).encode("utf-8"),
                authorization="Bearer operator-secret",
            )
            self.assertFalse(imported["replaced"])
            self.assertEqual(imported["manifest"]["module_id"], "local.demo.customer.menu")
            self.assertEqual(imported["manifest"]["validation_status"], "validated")
            self.assertFalse(imported["manifest"]["runnable_now"])
            self.assertFalse(imported["manifest"]["selectable_for_desired_set"])

            replaced_payload = dict(payload)
            replaced_payload["version"] = "0.3"
            replaced = pilot.operator_import_module_manifest(
                source_name="module-v2.json",
                content_bytes=json.dumps(replaced_payload).encode("utf-8"),
                authorization="Bearer operator-secret",
            )
            self.assertTrue(replaced["replaced"])
            self.assertEqual(replaced["manifest"]["version"], "0.3")

            imports_room = pilot.operator_import(authorization="Bearer operator-secret")
            modules_room = pilot.operator_modules(authorization="Bearer operator-secret")
            self.assertEqual(imports_room["imported_manifest_count"], 1)
            self.assertEqual(len(imports_room["imported_manifests"]), 1)
            self.assertEqual(modules_room["imported_manifest_count"], 1)
            self.assertEqual(len(modules_room["imported_manifests"]), 1)
            self.assertEqual(modules_room["current_module_ids"], ["p4p.payment.cash"])
            self.assertEqual(modules_room["desired_module_ids"], ["p4p.payment.cash"])
            self.assertFalse(modules_room["restart_required"])

            with self.assertRaises(HTTPException) as unknown_imported_module:
                pilot.operator_update_module_set(
                    pilot.OperatorModuleSetUpdate(
                        module_ids=["p4p.payment.cash", "local.demo.customer.menu"]
                    ),
                    authorization="Bearer operator-secret",
                )
            self.assertEqual(unknown_imported_module.exception.status_code, 400)
            self.assertIn("Unknown module_id", str(unknown_imported_module.exception.detail))

            deleted = pilot.operator_delete_imported_module_manifest(
                "local.demo.customer.menu",
                authorization="Bearer operator-secret",
            )
            self.assertTrue(deleted["removed"])
            self.assertEqual(deleted["imported_manifest_count"], 0)
            pilot.store.close()

    def test_pilot_node_operator_import_manifest_route_accepts_multipart_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "pilot.sqlite3")
            env = {
                "P4P_PILOT_NODE_DB_PATH": db_path,
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_NODE_MODULES": "p4p.payment.cash",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            }
            pilot = load_module("pilot-node/pilot_app.py", env)
            routes = load_module("pilot-node/app/pilot_node/routes.py", env)
            payload = json.loads((REPO_ROOT / "modules/p4p.menu.list/module.json").read_text(encoding="utf-8"))
            payload["module_id"] = "local.demo.multipart.menu"
            payload["provider_id"] = "local.demo"
            payload["version"] = "0.2"
            boundary = "----P4PMultipartBoundary"
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="manifest"; filename="module.json"\r\n'
                "Content-Type: application/json\r\n\r\n"
                f"{json.dumps(payload)}\r\n"
                f"--{boundary}--\r\n"
            ).encode("utf-8")

            async def receive() -> dict[str, object]:
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/operator/modules/import-manifest",
                    "query_string": b"",
                    "headers": [
                        (b"content-type", f"multipart/form-data; boundary={boundary}".encode("utf-8")),
                        (b"accept", b"application/json"),
                    ],
                },
                receive,
            )

            source_name, content_bytes = asyncio.run(routes.import_manifest_request_payload(request))
            imported = pilot.operator_import_module_manifest(
                source_name=source_name,
                content_bytes=content_bytes,
                authorization="Bearer operator-secret",
            )

            self.assertEqual(imported["manifest"]["module_id"], "local.demo.multipart.menu")
            self.assertEqual(imported["manifest"]["source_name"], "module.json")
            self.assertEqual(imported["manifest"]["validation_status"], "validated")
            imports_room = pilot.operator_import(authorization="Bearer operator-secret")
            self.assertEqual(imports_room["imported_manifest_count"], 1)
            self.assertEqual(imports_room["imported_manifests"][0]["module_id"], "local.demo.multipart.menu")
            pilot.store.close()

    def test_pilot_node_operator_import_manifest_rejects_invalid_and_colliding_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "pilot.sqlite3"
            external_manifest_path = Path(tmpdir) / "external-module.json"
            external_payload = json.loads((REPO_ROOT / "modules/p4p.menu.list/module.json").read_text(encoding="utf-8"))
            external_payload["module_id"] = "local.external.wallet"
            external_payload["provider_id"] = "local.external"
            external_payload["version"] = "1.0"
            external_manifest_path.write_text(json.dumps(external_payload), encoding="utf-8")

            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(db_path),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.payment.cash",
                    "P4P_EXTERNAL_MODULE_MANIFESTS": str(external_manifest_path),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as invalid_json:
                pilot.operator_import_module_manifest(
                    source_name="module.json",
                    content_bytes=b"{not-json",
                    authorization="Bearer operator-secret",
                )
            with self.assertRaises(HTTPException) as non_object_json:
                pilot.operator_import_module_manifest(
                    source_name="module.json",
                    content_bytes=b"[]",
                    authorization="Bearer operator-secret",
                )
            with self.assertRaises(HTTPException) as invalid_schema:
                pilot.operator_import_module_manifest(
                    source_name="module.json",
                    content_bytes=json.dumps({}).encode("utf-8"),
                    authorization="Bearer operator-secret",
                )

            reference_collision_payload = json.loads(
                (REPO_ROOT / "modules/p4p.menu.list/module.json").read_text(encoding="utf-8")
            )
            with self.assertRaises(HTTPException) as reference_collision:
                pilot.operator_import_module_manifest(
                    source_name="module.json",
                    content_bytes=json.dumps(reference_collision_payload).encode("utf-8"),
                    authorization="Bearer operator-secret",
                )

            external_collision_payload = dict(external_payload)
            with self.assertRaises(HTTPException) as external_collision:
                pilot.operator_import_module_manifest(
                    source_name="module.json",
                    content_bytes=json.dumps(external_collision_payload).encode("utf-8"),
                    authorization="Bearer operator-secret",
                )

            self.assertEqual(invalid_json.exception.status_code, 400)
            self.assertEqual(non_object_json.exception.status_code, 400)
            self.assertEqual(invalid_schema.exception.status_code, 400)
            self.assertEqual(reference_collision.exception.status_code, 400)
            self.assertEqual(external_collision.exception.status_code, 400)
            self.assertIn("valid UTF-8 JSON", str(invalid_json.exception.detail))
            self.assertIn("one JSON object", str(non_object_json.exception.detail))
            self.assertIn("Invalid module manifest", str(invalid_schema.exception.detail))
            self.assertIn("shadows", str(reference_collision.exception.detail))
            self.assertIn("shadows", str(external_collision.exception.detail))
            pilot.store.close()

    def test_pilot_node_operator_payment_module_selection_rejects_invalid_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as unknown:
                pilot.operator_update_payment_module(
                    pilot.OperatorPaymentModuleUpdate(module_id="local.unknown.payment"),
                    authorization="Bearer operator-secret",
                )
            with self.assertRaises(HTTPException) as non_payment:
                pilot.operator_update_payment_module(
                    pilot.OperatorPaymentModuleUpdate(module_id="p4p.order.print"),
                    authorization="Bearer operator-secret",
                )

            self.assertEqual(unknown.exception.status_code, 400)
            self.assertEqual(non_payment.exception.status_code, 400)
            pilot.store.close()

    def test_pilot_node_operator_selected_payment_manifest_without_executor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.payment.chaospay-mock",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            modules = pilot.operator_update_payment_module(
                pilot.OperatorPaymentModuleUpdate(module_id="p4p.payment.chaospay-mock"),
                authorization="Bearer operator-secret",
            )
            self.assertEqual(modules["active_by_lane"]["payment"], "p4p.payment.chaospay-mock")

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PAYMENT_REQUIRED", "PAYMENT_FAILED", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[1].source_module, "p4p.payment.chaospay-mock")
            self.assertEqual(events[2].source_module, "p4p.payment.chaospay-mock")
            self.assertEqual(events[2].reason_code, "PAYMENT_EXECUTOR_UNAVAILABLE")
            self.assertEqual(events[2].metadata["mock_module"], True)
            self.assertEqual(stored[0].status_message, "Order accepted. External payment needs human attention.")
            pilot.store.close()

    def test_pilot_node_selected_payment_manifest_without_executor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.chaospay-mock",
                    "P4P_PAYMENT_MODULE_ID": "p4p.payment.chaospay-mock",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PAYMENT_REQUIRED", "PAYMENT_FAILED", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].source_module, "p4p.payment.chaospay-mock")
            self.assertEqual(events[2].reason_code, "PAYMENT_EXECUTOR_UNAVAILABLE")
            self.assertEqual(events[2].metadata["real_payment"], False)
            self.assertEqual(stored[0].status_message, "Order accepted. External payment needs human attention.")
            pilot.store.close()

    def test_pilot_node_stock_module_validates_before_print_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.stock.basic,p4p.order.print",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                [
                    "ORDER_ACCEPTED",
                    "ORDER_VALIDATED",
                    "PAYMENT_REQUIRED",
                    "PAYMENT_MODE_CHANGED",
                    "PRINT_REQUESTED",
                    "PRINT_SUCCESS_CONFIRMED",
                ],
            )
            self.assertEqual(events[1].source_module, "p4p.stock.basic")
            self.assertEqual(events[1].metadata["contract_phase"], "result")
            self.assertEqual(events[1].metadata["trigger_event"], "ORDER_ACCEPTED")
            self.assertEqual(events[1].metadata["requested_item_ids"], ["kebab-pita"])
            self.assertEqual(events[2].source_module, "p4p.payment.cash")
            self.assertEqual(events[2].metadata["contract_phase"], "request")
            self.assertEqual(events[4].metadata["contract_phase"], "request")
            self.assertEqual(stored[0].status_message, "Order accepted. Print confirmed.")
            pilot.store.close()

    def test_pilot_node_stock_module_blocks_impossible_item_before_print_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "should-not-print.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.stock.basic,p4p.order.print",
                    "P4P_STOCK_UNAVAILABLE_ITEM_IDS": "kebab-pita",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "ITEM_NOT_POSSIBLE", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[1].source_module, "p4p.stock.basic")
            self.assertEqual(events[1].metadata["blocked_item_ids"], ["kebab-pita"])
            self.assertEqual(events[2].metadata["trigger_event"], "ITEM_NOT_POSSIBLE")
            self.assertEqual(stored[0].status_message, "Order accepted. Stock check needs human attention.")
            self.assertFalse(device_path.exists())
            pilot.store.close()

    def test_pilot_node_rejects_undeclared_print_output_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            execution = sys.modules["pilot_node.execution"]
            print_adapters = sys.modules["pilot_node.print_adapters"]

            class BrokenAdapter:
                target_id = "printer"
                confirmed_status_message = "Order accepted. Print confirmed."
                needs_human_status_message = "Order accepted. Printer issue detected. Human attention required."
                alerted_status_message = "Order accepted. Printer issue detected. Operator alerted by email. Human attention required."
                alert_failed_status_message = "Order accepted. Printer issue detected. Email alert failed. Human attention required."

                def decide(self, configured_mode: str):
                    return print_adapters.PrintAdapterDecision(
                        event="OUTBOUND_ACTION_REQUESTED",
                        outcome="SUCCESS",
                        severity="low",
                        retryable=False,
                        side_effect_state="none",
                    )

            with patch.object(execution, "build_print_adapter", return_value=BrokenAdapter()):
                with self.assertRaises(ValueError) as error:
                    pilot.public_order(self.make_pilot_order_request(pilot))

            self.assertIn("p4p.order.print", str(error.exception))
            self.assertIn("OUTBOUND_ACTION_REQUESTED", str(error.exception))
            pilot.store.close()

    def test_pilot_node_rejects_notification_trigger_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print,p4p.notify.email",
                    "P4P_PRINT_MODULE_MODE": "printer_offline",
                    "P4P_NOTIFY_EMAIL_MODE": "sent",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            execution = sys.modules["pilot_node.execution"]

            def broken_notification_result_event(*, runtime, order, trigger_event, adapter_target, hardware_profile_metadata):
                return execution.build_result_event(
                    runtime=runtime,
                    event="NOTIFICATION_SENT",
                    source_module=execution.NOTIFY_EMAIL_MODULE_ID,
                    order=order,
                    action_id=f"order:{order.order_id}:notify:email",
                    idempotency_key=f"notify:{order.order_id}:email",
                    outcome="SUCCESS",
                    severity="medium",
                    retryable=False,
                    side_effect_state="confirmed",
                    metadata={
                        **hardware_profile_metadata,
                        "configured_mode": "sent",
                        "trigger_event": "PRINT_TIMEOUT",
                        "adapter_target": adapter_target,
                        "broken_from": trigger_event,
                    },
                )

            with patch.object(execution, "build_notification_result_event", side_effect=broken_notification_result_event):
                with self.assertRaises(ValueError) as error:
                    pilot.public_order(self.make_pilot_order_request(pilot))

            self.assertIn("notification trigger_event=PRINTER_OFFLINE", str(error.exception))
            pilot.store.close()

    def test_pilot_node_print_module_can_target_screen_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "screen",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PRINT_SUCCESS_CONFIRMED"],
            )
            self.assertEqual(events[-1].metadata["adapter_target"], "screen")
            self.assertEqual(events[-1].metadata["delivery_surface"], "screen")
            self.assertEqual(stored[0].status_message, "Order accepted. Operator screen confirmed.")
            pilot.store.close()

    def test_pilot_node_hardware_profile_can_activate_box_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            serial_path = Path(tmpdir) / "box-v1-sensor.txt"
            serial_path.write_text("precheck:ok\npostcheck:confirmed\n", encoding="utf-8")
            device_path = Path(tmpdir) / "box-v1-printer.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_HARDWARE_PROFILE": "box_v1",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_SERIAL_PATH": str(serial_path),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(events[1].metadata["hardware_profile"], "box_v1")
            self.assertFalse(events[1].metadata["hardware_profile_customized"])
            self.assertEqual(events[1].metadata["adapter_target"], "printer")
            self.assertEqual(events[1].metadata["print_driver"], "escpos_raw")
            self.assertEqual(events[1].metadata["sensor_source"], "serial_status")
            self.assertEqual(events[-1].metadata["cut_mode"], "partial")
            self.assertEqual(events[-1].metadata["sensor_raw_line"], "postcheck:confirmed")
            self.assertTrue(device_path.exists())
            self.assertTrue(device_path.read_bytes().startswith(b"\x1b@"))
            pilot.store.close()

    def test_pilot_node_hardware_profile_still_allows_explicit_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_HARDWARE_PROFILE": "box_v1",
                    "P4P_PRINT_MODULE_TARGET": "screen",
                    "P4P_PRINT_MODULE_DRIVER": "simulated",
                    "P4P_PRINT_SENSOR_SOURCE": "simulated",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(events[1].metadata["hardware_profile"], "box_v1")
            self.assertTrue(events[1].metadata["hardware_profile_customized"])
            self.assertEqual(events[-1].metadata["adapter_target"], "screen")
            self.assertEqual(events[-1].metadata["print_driver"], "simulated")
            self.assertEqual(events[-1].metadata["sensor_source"], "simulated")
            self.assertEqual(events[-1].metadata["delivery_surface"], "screen")
            pilot.store.close()

    def test_pilot_node_operator_state_exposes_hardware_bundle_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "menu_only",
                    "P4P_NODE_MODULES": "p4p.payment.cash,p4p.order.print,p4p.order.print.backup,p4p.order.alert.basic,p4p.pickup.board.basic",
                    "P4P_HARDWARE_PROFILE": "box_v1_counter",
                    "P4P_PRINT_DEVICE_PATH": str(Path(tmpdir) / "printer.bin"),
                    "P4P_PRINT_SENSOR_SERIAL_PATH": str(Path(tmpdir) / "sensor.txt"),
                    "P4P_BACKUP_PRINT_SPOOL_DIR": str(Path(tmpdir) / "backup-spool"),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            state = pilot.operator_state(authorization="Bearer operator-secret")

            self.assertEqual(state["hardware"]["profile"], "box_v1_counter")
            self.assertFalse(state["hardware"]["customized"])
            self.assertEqual(state["hardware"]["print"]["driver"], "escpos_raw")
            self.assertEqual(state["hardware"]["print"]["target"], "printer")
            self.assertEqual(state["hardware"]["backup_print"]["target"], "backup_spool")
            self.assertEqual(state["hardware"]["backup_print"]["driver"], "file_spool")
            self.assertEqual(state["hardware"]["alert"]["target"], "counter_bell")
            self.assertEqual(state["hardware"]["pickup_board"]["target"], "counter_screen")
            pilot.store.close()

    def test_pilot_node_print_module_can_spool_ticket_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spool_dir = Path(tmpdir) / "spool"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "file_spool",
                    "P4P_PRINT_SPOOL_DIR": str(spool_dir),
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            ticket_path = Path(events[-1].metadata["spool_path"])

            self.assertEqual(events[-1].event, "PRINT_SUCCESS_CONFIRMED")
            self.assertEqual(events[-1].metadata["print_driver"], "file_spool")
            self.assertEqual(events[-1].metadata["side_effect_delivery"], "artifact_written")
            self.assertTrue(ticket_path.exists())
            ticket_text = ticket_path.read_text(encoding="utf-8")
            self.assertIn(accepted.order_id, ticket_text)
            self.assertIn("kebab-pita", ticket_text)
            pilot.store.close()

    def test_pilot_node_print_module_can_write_to_device_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "fake-printer-device.txt"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(events[-1].event, "PRINT_SUCCESS_CONFIRMED")
            self.assertEqual(events[-1].metadata["print_driver"], "device_path")
            self.assertEqual(events[-1].metadata["side_effect_delivery"], "device_written")
            self.assertEqual(events[-1].metadata["device_path"], str(device_path))
            self.assertTrue(device_path.exists())
            ticket_bytes = device_path.read_bytes()
            self.assertIn(accepted.order_id.encode("utf-8"), ticket_bytes)
            self.assertIn(b"kebab-pita", ticket_bytes)
            pilot.store.close()

    def test_pilot_node_print_module_can_write_escpos_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "fake-escpos-device.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "escpos_raw",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_ESCPOS_CUT_MODE": "partial",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(events[-1].event, "PRINT_SUCCESS_CONFIRMED")
            self.assertEqual(events[-1].metadata["print_driver"], "escpos_raw")
            self.assertEqual(events[-1].metadata["cut_mode"], "partial")
            ticket_bytes = device_path.read_bytes()
            self.assertTrue(ticket_bytes.startswith(b"\x1b@"))
            self.assertTrue(ticket_bytes.endswith(b"\x1dV\x01"))
            self.assertIn(accepted.order_id.encode("ascii"), ticket_bytes)
            self.assertIn(b"kebab-pita", ticket_bytes)
            pilot.store.close()

    def test_pilot_node_print_precheck_can_block_before_device_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "blocked-printer-device.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_PRECHECK": "paper_out",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PAPER_OUT", "ORDER_NEEDS_HUMAN"],
            )
            self.assertFalse(device_path.exists())
            self.assertEqual(events[2].metadata["sensor_phase"], "precheck")
            pilot.store.close()

    def test_pilot_node_print_postcheck_can_mark_device_write_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            device_path = Path(tmpdir) / "uncertain-printer-device.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_POSTCHECK": "uncertain",
                    "P4P_PRINT_MODULE_MODE": "confirmed",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PRINT_UNCERTAIN", "ORDER_NEEDS_HUMAN"],
            )
            self.assertTrue(device_path.exists())
            self.assertEqual(events[2].metadata["sensor_phase"], "postcheck")
            self.assertEqual(events[2].metadata["side_effect_delivery"], "device_written")
            self.assertEqual(events[2].side_effect_state, "unknown")
            pilot.store.close()

    def test_pilot_node_print_sensor_can_read_precheck_from_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "printer-sensor.json"
            status_path.write_text('{"precheck":"paper_out","postcheck":"confirmed"}', encoding="utf-8")
            device_path = Path(tmpdir) / "status-file-printer.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_SOURCE": "status_file",
                    "P4P_PRINT_SENSOR_STATUS_PATH": str(status_path),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PAPER_OUT", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].metadata["sensor_source"], "status_file")
            self.assertEqual(events[2].metadata["sensor_status_path"], str(status_path))
            self.assertFalse(device_path.exists())
            pilot.store.close()

    def test_pilot_node_print_sensor_can_read_postcheck_from_status_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "printer-sensor.json"
            status_path.write_text('{"precheck":"ok","postcheck":"uncertain"}', encoding="utf-8")
            device_path = Path(tmpdir) / "status-file-printer.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_SOURCE": "status_file",
                    "P4P_PRINT_SENSOR_STATUS_PATH": str(status_path),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PRINT_UNCERTAIN", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].metadata["sensor_source"], "status_file")
            self.assertEqual(events[2].metadata["sensor_status_path"], str(status_path))
            self.assertTrue(device_path.exists())
            pilot.store.close()

    def test_pilot_node_print_sensor_can_read_precheck_from_serial_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            serial_path = Path(tmpdir) / "printer-sensor-serial.txt"
            serial_path.write_text("precheck:paper_out\npostcheck:confirmed\n", encoding="utf-8")
            device_path = Path(tmpdir) / "serial-status-printer.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_SOURCE": "serial_status",
                    "P4P_PRINT_SENSOR_SERIAL_PATH": str(serial_path),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PAPER_OUT", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].metadata["sensor_source"], "serial_status")
            self.assertEqual(events[2].metadata["sensor_serial_path"], str(serial_path))
            self.assertEqual(events[2].metadata["sensor_raw_line"], "precheck:paper_out")
            self.assertFalse(device_path.exists())
            pilot.store.close()

    def test_pilot_node_print_sensor_can_read_postcheck_from_serial_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            serial_path = Path(tmpdir) / "printer-sensor-serial.txt"
            serial_path.write_text("precheck:ok\npostcheck=uncertain\n", encoding="utf-8")
            device_path = Path(tmpdir) / "serial-status-printer.bin"
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print",
                    "P4P_PRINT_MODULE_TARGET": "printer",
                    "P4P_PRINT_MODULE_DRIVER": "device_path",
                    "P4P_PRINT_DEVICE_PATH": str(device_path),
                    "P4P_PRINT_SENSOR_SOURCE": "serial_status",
                    "P4P_PRINT_SENSOR_SERIAL_PATH": str(serial_path),
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                ["ORDER_ACCEPTED", "PRINT_REQUESTED", "PRINT_UNCERTAIN", "ORDER_NEEDS_HUMAN"],
            )
            self.assertEqual(events[2].metadata["sensor_source"], "serial_status")
            self.assertEqual(events[2].metadata["sensor_serial_path"], str(serial_path))
            self.assertEqual(events[2].metadata["sensor_raw_line"], "postcheck=uncertain")
            self.assertTrue(device_path.exists())
            pilot.store.close()

    def test_pilot_node_print_failure_alerts_and_escalates_to_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_NODE_MODULES": "p4p.order.print,p4p.notify.email",
                    "P4P_PRINT_MODULE_MODE": "printer_offline",
                    "P4P_NOTIFY_EMAIL_MODE": "sent",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            accepted = pilot.public_order(self.make_pilot_order_request(pilot))
            events = pilot.operator_order_events(accepted.order_id, authorization="Bearer operator-secret")
            stored = pilot.operator_orders(authorization="Bearer operator-secret")

            self.assertEqual(
                [event.event for event in events],
                [
                    "ORDER_ACCEPTED",
                    "PRINT_REQUESTED",
                    "PRINTER_OFFLINE",
                    "NOTIFICATION_SENT",
                    "ORDER_NEEDS_HUMAN",
                ],
            )
            self.assertEqual(events[2].outcome, "UNAVAILABLE")
            self.assertEqual(events[3].source_module, "p4p.notify.email")
            self.assertEqual(stored[0].status, "accepted")
            self.assertIn("Human attention required.", stored[0].status_message or "")
            pilot.store.close()

    def test_pilot_node_operator_endpoints_require_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            with self.assertRaises(HTTPException) as missing_token:
                pilot.operator_orders()

            with self.assertRaises(HTTPException) as wrong_token:
                pilot.operator_orders(authorization="Bearer wrong-secret")

            with self.assertRaises(HTTPException) as missing_modules_token:
                pilot.operator_modules()

            with self.assertRaises(HTTPException) as missing_payment_module_token:
                pilot.operator_update_payment_module(
                    pilot.OperatorPaymentModuleUpdate(module_id="p4p.payment.cash"),
                )
            with self.assertRaises(HTTPException) as missing_module_detail_token:
                pilot.operator_module_detail("p4p.payment.cash")
            with self.assertRaises(HTTPException) as missing_module_set_token:
                pilot.operator_update_module_set(
                    pilot.OperatorModuleSetUpdate(module_ids=["p4p.payment.cash"]),
                )

            self.assertEqual(missing_token.exception.status_code, 401)
            self.assertEqual(wrong_token.exception.status_code, 401)
            self.assertEqual(missing_modules_token.exception.status_code, 401)
            self.assertEqual(missing_payment_module_token.exception.status_code, 401)
            self.assertEqual(missing_module_detail_token.exception.status_code, 401)
            self.assertEqual(missing_module_set_token.exception.status_code, 401)
            pilot.store.close()

    def test_pilot_node_root_index_points_browser_to_public_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            index = pilot.root_index()

            self.assertEqual(index["service"], "p4p-pilot-node")
            self.assertEqual(index["node_id"], "dk-brondby-kebab-001")
            self.assertTrue(index["accepts_orders"])
            self.assertEqual(index["endpoints"]["info"], "GET /p4p/info")
            self.assertEqual(
                index["endpoints"]["food_image_fixture"],
                "GET /p4p/assets/food-image-fixtures/{asset_path}",
            )
            self.assertEqual(index["endpoints"]["menu_list"], "GET /p4p/menu/list")
            self.assertEqual(index["endpoints"]["menu_photo_map"], "GET /p4p/menu/photo-map")
            self.assertEqual(index["endpoints"]["order"], "POST /p4p/order")
            self.assertEqual(index["endpoints"]["operator_gui"], "GET /operator")
            self.assertEqual(index["endpoints"]["operator_catalog"], "GET /operator/catalog")
            self.assertEqual(index["endpoints"]["operator_import"], "GET /operator/import")
            self.assertEqual(index["endpoints"]["operator_modules"], "GET /operator/modules")
            self.assertEqual(index["endpoints"]["operator_module_view"], "GET /operator/modules/view/{module_id}")
            self.assertEqual(index["endpoints"]["operator_module_detail"], "GET /operator/modules/{module_id}")
            self.assertEqual(index["endpoints"]["operator_module_imports"], "GET /operator/modules/imports")
            self.assertEqual(index["endpoints"]["operator_import_manifest"], "POST /operator/modules/import-manifest")
            self.assertEqual(
                index["endpoints"]["operator_delete_imported_manifest"],
                "DELETE /operator/modules/imports/{module_id}",
            )
            self.assertEqual(index["endpoints"]["operator_payment_module"], "PATCH /operator/modules/payment")
            self.assertEqual(index["endpoints"]["operator_module_set"], "PATCH /operator/modules/set")
            pilot.store.close()

    def test_pilot_node_operator_gui_loads_operations_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            html = pilot.operator_gui()

            self.assertIn("<title>P4P Drift</title>", html)
            self.assertIn('href="/operator/catalog"', html)
            self.assertIn('href="/operator/modules"', html)
            self.assertIn('href="/operator/import"', html)
            self.assertIn('request("/operator/modules")', html)
            self.assertIn('method: "PATCH"', html)
            self.assertIn('request("/operator/state")', html)
            self.assertIn('request("/operator/orders")', html)
            self.assertIn('request("/operator/menu")', html)
            self.assertIn("renderOrders", html)
            self.assertIn("Backoffice", html)
            self.assertNotIn("Running now on this node.", html)
            self.assertNotIn("Available modules", html)
            self.assertNotIn("saveCatalog", html)
            self.assertIn("updateOrder", html)
            self.assertIn("X-P4P-Operator-Token", html)
            self.assertIn("p4pOperatorToken", html)
            self.assertNotIn("Category before import", html)
            self.assertNotIn("import-preview-category", html)
            self.assertNotIn('importSourceNameInput.value = file.name', html)
            self.assertNotIn("slugifyImportName", html)
            pilot.store.close()

    def test_pilot_node_operator_catalog_page_loads_catalog_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            html = pilot.operator_catalog_page()

            self.assertIn("<title>P4P Katalog</title>", html)
            self.assertIn('href="/operator"', html)
            self.assertIn('href="/operator/modules"', html)
            self.assertIn('request("/operator/modules")', html)
            self.assertIn('request("/operator/menu")', html)
            self.assertIn("renderCatalog", html)
            self.assertIn("saveCatalog", html)
            self.assertIn("Open OCR module page", html)
            self.assertNotIn("Incoming and active pickup orders for the current shift.", html)
            pilot.store.close()

    def test_pilot_node_operator_modules_page_loads_module_control_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )

            html = pilot.operator_modules_page()

            self.assertIn("<title>P4P Moduler</title>", html)
            self.assertIn('href="/operator/catalog"', html)
            self.assertIn('request("/operator/modules")', html)
            self.assertIn("/operator/modules/view/", html)
            self.assertIn('request("/operator/state")', html)
            self.assertNotIn('request("/operator/menu")', html)
            self.assertIn("renderModuleStateSummary", html)
            self.assertIn("Current modules", html)
            self.assertIn("Available modules", html)
            self.assertIn("restart required", html)
            self.assertNotIn("saveCatalog", html)
            pilot.store.close()

    def test_pilot_node_dual_registers_to_primary_and_backup(self) -> None:
        primary = load_module("registry/main.py")
        backup = load_module("registry/main.py")
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_REGISTRY_URLS": "http://primary-registry.test,http://backup-registry.test",
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_OPEN": "true",
                    "P4P_NODE_ORDER_MODE": "live",
                    "P4P_OPERATOR_TOKEN": "operator-secret",
                },
            )
            routes = {
                "http://primary-registry.test": primary,
                "http://backup-registry.test": backup,
            }

            with patch.object(pilot.httpx, "AsyncClient", new=lambda *args, **kwargs: RegistryBridgeAsyncClient(routes)):
                asyncio.run(pilot.run_registry_cycle(force_announce=True))

            self.assertEqual(
                pilot.REGISTRATION.registered_registries,
                ["http://primary-registry.test", "http://backup-registry.test"],
            )
            primary_result = primary.discover(
                lat=55.6517,
                lng=12.4126,
                radius=10,
                category="kebab",
                country="DK",
            )
            backup_result = backup.discover(
                lat=55.6517,
                lng=12.4126,
                radius=10,
                category="kebab",
                country="DK",
            )

            self.assertEqual(len(primary_result.nodes), 1)
            self.assertEqual(len(backup_result.nodes), 1)
            self.assertEqual(primary_result.nodes[0].node_id, pilot.node_state().node_id)
            self.assertEqual(backup_result.nodes[0].node_id, pilot.node_state().node_id)
            pilot.store.close()

    def test_client_avoids_inner_html_for_untrusted_payloads(self) -> None:
        client_app = (REPO_ROOT / "client" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("innerHTML", client_app)
        self.assertNotIn("insertAdjacentHTML", client_app)
        self.assertNotIn("outerHTML", client_app)

    def test_node_checker_validates_interop_shapes(self) -> None:
        checker = load_module("scripts/check-node.py")

        info_results = checker.validate_info(
            {
                "node_id": "dk-test-node-001",
                "name": "Independent Test Node",
                "endpoint": "http://127.0.0.1:9001/p4p",
                "order_mode": "test",
                "protocol_version": "0.1",
                "modules": ["p4p.payment.cash", "p4p.delivery.pickup"],
                "module_declarations": [
                    {
                        "module_id": "p4p.payment.cash",
                        "provider_id": "p4p.reference",
                        "version": "0.1",
                        "status": "active",
                        "visibility": "public",
                        "readiness": "live",
                        "capabilities": ["accept_cash"],
                        "data_access": ["order_total"],
                        "customer_notice": "Pay at pickup.",
                    }
                ],
                "undeclared_modules": ["p4p.delivery.pickup"],
            }
        )
        self.assertFalse([result for result in info_results if result.level == "FAIL"])

        invalid_info = checker.validate_info({"order_mode": "maybe"})
        self.assertTrue(any(result.level == "FAIL" and result.name == "info.order_mode" for result in invalid_info))

        menu_results = checker.validate_menu(
            {
                "currency": "DKK",
                "updated_at": "2026-04-29T12:00:00Z",
                "items": [
                    {
                        "id": "kebab-box",
                        "name": "Kebab Box",
                        "description": "Test item",
                        "price": 6500,
                        "category": "kebab",
                        "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-durum-kebab.png",
                    }
                ],
            }
        )
        self.assertFalse([result for result in menu_results if result.level == "FAIL"])
        self.assertTrue(any(result.name == "menu.items[0].image_url" and result.level == "PASS" for result in menu_results))

        eur_menu = checker.validate_menu(
            {
                "currency": "EUR",
                "updated_at": "2026-04-29T12:00:00Z",
                "items": [
                    {
                        "id": "margherita",
                        "name": "Margherita",
                        "description": "Test item",
                        "price": 1299,
                        "category": "pizza",
                    }
                ],
            }
        )
        self.assertFalse([result for result in eur_menu if result.level == "FAIL"])

        bad_menu = checker.validate_menu({"currency": "EURO", "updated_at": "", "items": []})
        self.assertGreaterEqual(len([result for result in bad_menu if result.level == "FAIL"]), 3)

        accepted = checker.validate_order_response(
            {
                "accepted": True,
                "order_id": "test-001",
                "estimated_ready": "2026-04-29T12:20:00Z",
                "message": "Test order received.",
            },
            True,
        )
        self.assertFalse([result for result in accepted if result.level == "FAIL"])

        rejected = checker.validate_order_response(
            {
                "accepted": False,
                "reason": "orders_disabled",
                "message": "Orders are not enabled.",
            },
            False,
        )
        self.assertFalse([result for result in rejected if result.level == "FAIL"])

    def test_node_checker_refuses_live_order_without_explicit_flag(self) -> None:
        checker = load_module("scripts/check-node.py")
        calls: list[tuple[str, str]] = []

        def fake_fetch(url: str, *, method: str = "GET", payload=None, timeout: float = 5.0):
            calls.append((method, url))
            if url.endswith("/info"):
                return 200, {
                    "node_id": "dk-test-node-001",
                    "name": "Independent Test Node",
                    "endpoint": "http://127.0.0.1:9001/p4p",
                    "order_mode": "live",
                    "protocol_version": "0.1",
                }
            if url.endswith("/menu"):
                return 200, {
                    "currency": "DKK",
                    "updated_at": "2026-04-29T12:00:00Z",
                    "items": [
                        {
                            "id": "kebab-box",
                            "name": "Kebab Box",
                            "description": "Test item",
                            "price": 6500,
                            "category": "kebab",
                        }
                    ],
                }
            raise AssertionError(f"unexpected fetch {method} {url}")

        with patch.object(checker, "fetch_json", side_effect=fake_fetch):
            results = checker.run_checks(
                "http://127.0.0.1:9001/p4p",
                timeout=5.0,
                test_order=True,
                allow_live_order=False,
            )

        self.assertFalse(any(url.endswith("/order") for _, url in calls))
        self.assertTrue(any(result.level == "WARN" and result.name == "POST /order" for result in results))


if __name__ == "__main__":
    unittest.main()
