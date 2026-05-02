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
from pydantic import ValidationError


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

        imported = mirror.registry_source_import(snapshot)
        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirrors = mirror.registry_mirrors()
        promotions = mirror.curated_promotions()

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
        mirror = load_module("registry/main.py")

        snapshot = source.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        with self.assertRaises(HTTPException) as import_error:
            mirror.registry_source_import(snapshot)

        self.assertEqual(import_error.exception.status_code, 403)
        self.assertEqual(
            import_error.exception.detail,
            "Public registry source import requires registry signature",
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
            sync_result = asyncio.run(mirror.run_mirror_sync_once())

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        sync_status = mirror.registry_sync_status()

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
        mirror.registry_source_import(snapshot)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions()

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
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))

        override = mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="deny",
                reason="Temporary local hold",
                set_by="ops",
            )
        )
        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions()
        overrides = mirror.curated_overrides()

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
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))

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
            )
        )
        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions()

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
        relay.registry_source_import(snapshot)

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
        relay.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))
        relay_snapshot = relay.registry_source(SimpleNamespace(base_url="https://ignored.example/"))

        imported = downstream.registry_source_import(relay_snapshot)
        discover_result = downstream.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = downstream.registry_mirrors()
        promotions = downstream.curated_promotions()

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
        mirror.registry_source_import(snapshot)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors()
        sync_status = mirror.registry_sync_status()
        promotions = mirror.curated_promotions()

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
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))

        promoted_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        self.assertEqual(len(promoted_result.nodes), 1)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 1)
        self.assertEqual(mirror.curated_promotions().records[0].decision, "promote")

        source.node_manifest(
            source.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=(demo.utc_now() + demo.timedelta(seconds=1)).isoformat(),
                    key_status="revoked",
                )
            )
        )
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(mirror.curated_promotions().records[0].decision, "deny")
        self.assertEqual(mirror.curated_promotions().records[0].decision_basis, "no_visible_nodes")
        self.assertEqual(mirror.curated_promotions().records[0].promoted_node_ids, [])

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
        mirror.registry_source_import(snapshot)

        stored = next(iter(mirror.store._mirror_sources.values()))
        stored.imported_at = mirror.utc_now() - mirror.timedelta(seconds=2)

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        mirror_status = mirror.registry_mirrors()
        promotions = mirror.curated_promotions()

        self.assertEqual(discover_result.nodes, [])
        self.assertEqual(mirror.health()["mirrored_registries"], 0)
        self.assertEqual(mirror.health()["discoverable_mirrored_registries"], 0)
        self.assertEqual(mirror.health()["curated_active_index_entries"], 0)
        self.assertEqual(promotions.records[0].decision, "deny")
        self.assertEqual(promotions.records[0].decision_basis, "expired")
        self.assertFalse(mirror_status.sources[0].active)
        self.assertFalse(mirror_status.sources[0].discovery_eligible)
        self.assertEqual(mirror_status.sources[0].discovery_basis, "expired")

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
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))
        mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="allow",
                reason="Still valid only while source is fresh",
                set_by="ops",
            )
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
        promotions = mirror.curated_promotions()

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
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))

        source.node_manifest(
            source.NodeManifestRequest(
                **self.make_node_manifest_request(
                    demo,
                    manifest_version=2,
                    issued_at=(demo.utc_now() + demo.timedelta(seconds=1)).isoformat(),
                    key_status="revoked",
                )
            )
        )
        mirror.registry_source_import(source.registry_source(SimpleNamespace(base_url="https://ignored.example/")))
        mirror.curated_override(
            mirror.CuratedOverrideRequest(
                source_registry_url="https://registry-a.pizza4people.com",
                decision="allow",
                reason="Manual allow must not bypass revoked source",
                set_by="ops",
            )
        )

        discover_result = mirror.discover(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        promotions = mirror.curated_promotions()

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
        claims = registry.directory_claims()

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
            )
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
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    registry_type="country",
                    scope={"country_code": "DK"},
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
                claims=["local_only"],
                reason="Keep this node in local directories only",
                set_by="country-curator",
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

        self.assertEqual(len(discover_result.nodes), 1)
        self.assertEqual(directory_result.nodes, [])

    def test_expired_directory_claim_is_ignored(self) -> None:
        identity = load_module("p4p_identity.py")
        registry = load_module(
            "registry/main.py",
            {
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
            )
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
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_issue_trust_claims": True}
                ),
            },
        )
        directory = load_module(
            "registry/main.py",
            {
                "P4P_REGISTRY_URL": "https://directory.registry.test",
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
        )
        imported = directory.trust_claim_import(issued.claim)

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
        trust_claims = directory.trust_claims()

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

    def test_invalid_trust_claim_signature_is_rejected(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        directory = load_module(
            "registry/main.py",
            {
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
            directory.trust_claim_import(tampered)

        self.assertEqual(trust_claim_error.exception.status_code, 400)
        self.assertEqual(trust_claim_error.exception.detail, "Invalid trust claim signature")

    def test_expired_trust_claim_is_ignored_in_directory(self) -> None:
        identity = load_module("p4p_identity.py")
        issuer_private_key = identity.generate_private_key()
        directory = load_module(
            "registry/main.py",
            {
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

        directory.trust_claim_import(expired_claim)
        directory_result = directory.directory(
            lat=55.6517,
            lng=12.4126,
            radius=10,
            category="pizza",
            country="DK",
        )
        trust_claims = directory.trust_claims()

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
            )

        self.assertEqual(trust_claim_error.exception.status_code, 403)
        self.assertEqual(
            trust_claim_error.exception.detail,
            "This registry is not allowed to issue signed trust claims",
        )

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
                "P4P_REGISTRY_METADATA": self.make_registry_metadata(
                    capabilities={"can_curate_active_index": False},
                ),
            },
        )
        locked_moderation = load_module(
            "registry/main.py",
            {
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
            locked_relay.registry_source_import(snapshot)
        with self.assertRaises(HTTPException) as reexport_error:
            locked_reexport.registry_source(SimpleNamespace(base_url="https://ignored.example/"))
        locked_curate.registry_source_import(snapshot)
        with self.assertRaises(HTTPException) as override_error:
            locked_curate.curated_override(
                locked_curate.CuratedOverrideRequest(
                    source_registry_url="https://registry-a.pizza4people.com",
                    decision="allow",
                    reason="Not allowed here",
                )
            )
        with self.assertRaises(HTTPException) as directory_claim_error:
            locked_moderation.directory_claim(
                locked_moderation.DirectoryClaimRequest(
                    node_id=demo.NODE.node_id,
                    claims=["reviewed"],
                    reason="Not allowed here either",
                )
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
        self.assertEqual(locked_curate.curated_promotions().records[0].decision_basis, "curation_disabled")

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
            self.assertEqual(events[1].metadata["amount"], 65)
            self.assertEqual(events[1].metadata["currency"], "PIZZACOIN")
            self.assertEqual(events[2].source_module, "local.pizzacoin.wallet")
            self.assertEqual(events[2].metadata["external_payment_id"], "pay_test_001")
            self.assertEqual(payment_client.posts[0][0], "http://127.0.0.1:8301/p4p/payment")
            self.assertEqual(payment_client.posts[0][1]["customer_user_id"], "usr_test_customer")
            self.assertEqual(payment_client.posts[0][1]["amount"], 65)
            self.assertEqual(payment_client.posts[1][0], "http://127.0.0.1:8301/p4p/payment/pay_test_001/confirm")
            self.assertEqual(stored[0].status_message, "Order accepted. Print confirmed.")
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

            self.assertEqual(missing_token.exception.status_code, 401)
            self.assertEqual(wrong_token.exception.status_code, 401)
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
                    }
                ],
            }
        )
        self.assertFalse([result for result in menu_results if result.level == "FAIL"])

        bad_menu = checker.validate_menu({"currency": "EUR", "updated_at": "", "items": []})
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
