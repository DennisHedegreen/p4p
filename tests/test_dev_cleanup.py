from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import p4p_core.modules as module_catalog

from p4p_core import HeartbeatRequest as SharedHeartbeatRequest
from p4p_core import Location as SharedLocation
from p4p_core import ModuleResultEvent
from p4p_core import NodeDescriptor as SharedNodeDescriptor
from p4p_core import build_cors_middleware_options
from p4p_core import load_reference_module_catalog, load_reference_provider_catalog
from p4p_core import utc_now, validate_pilot_order_event_flow


_MODULE_COUNTER = 0


def make_flow_event(
    *,
    event: str,
    source_module: str,
    action_id: str,
    outcome: str = "SUCCESS",
    severity: str = "low",
    retryable: bool = False,
    side_effect_state: str = "confirmed",
    metadata: dict[str, object] | None = None,
) -> ModuleResultEvent:
    return ModuleResultEvent(
        event=event,
        source_module=source_module,
        order_id="ord-flow-1",
        action_id=action_id,
        idempotency_key=action_id,
        outcome=outcome,
        severity=severity,
        retryable=retryable,
        side_effect_state=side_effect_state,
        timestamp=utc_now(),
        metadata=metadata,
    )


def load_module(relative_path: str, env: dict[str, str] | None = None):
    global _MODULE_COUNTER

    _MODULE_COUNTER += 1
    module_path = REPO_ROOT / relative_path
    module_name = f"p4p_cleanup_test_module_{_MODULE_COUNTER}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module

    with patch.dict(os.environ, env or {}, clear=False):
        spec.loader.exec_module(module)

    return module


class P4PDevCleanupTests(unittest.TestCase):
    def make_pilot_order_request(self, pilot_module, item_id: str = "kebab-pita"):
        return pilot_module.OrderRequest(
            customer_name="Anna Hansen",
            customer_contact="+4512345678",
            fulfillment="pickup",
            items=[pilot_module.OrderItem(id=item_id, quantity=1)],
            note="Proof test",
            client_version="p4p-web-0.1",
        )

    def test_demo_operator_disabled_by_default(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
            },
        )

        self.assertFalse(demo.OPERATOR_ENABLED)

    def test_demo_operator_http_requires_token_when_enabled(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_OPERATOR_ENABLED": "true",
                "P4P_OPERATOR_TOKEN": "operator-secret",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
                "P4P_REGISTRY_URL": "http://127.0.0.1:1",
            },
        )

        with self.assertRaises(HTTPException) as missing_token:
            demo.require_operator_token()

        demo.require_operator_token(authorization="Bearer operator-secret")
        self.assertEqual(missing_token.exception.status_code, 401)

    def test_demo_operator_http_returns_404_when_disabled(self) -> None:
        demo = load_module(
            "demo-node/demo_node.py",
            {
                "P4P_OPERATOR_ENABLED": "false",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8001",
                "P4P_REGISTRY_URL": "http://127.0.0.1:1",
            },
        )

        with self.assertRaises(HTTPException) as disabled_error:
            demo.require_operator_token()

        self.assertEqual(disabled_error.exception.status_code, 404)

    def test_cors_defaults_to_loopback_and_accepts_explicit_allowlist(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            defaults = build_cors_middleware_options()
        with patch.dict(os.environ, {"P4P_CORS_ALLOW_ORIGINS": "https://pizza4people.com,https://protocols4people.com"}, clear=False):
            allowlist = build_cors_middleware_options()

        self.assertEqual(defaults["allow_origins"], [])
        self.assertIn("allow_origin_regex", defaults)
        self.assertEqual(
            allowlist["allow_origins"],
            ["https://pizza4people.com", "https://protocols4people.com"],
        )
        self.assertNotIn("allow_origin_regex", allowlist)

    def test_registry_uses_shared_protocol_models(self) -> None:
        registry = load_module("registry/main.py")
        pilot = load_module(
            "pilot-node/pilot_node.py",
            {
                "P4P_PILOT_NODE_DB_PATH": ":memory:",
                "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                "P4P_OPERATOR_TOKEN": "operator-secret",
            },
        )

        self.assertIs(registry.Location, SharedLocation)
        self.assertIs(registry.HeartbeatRequest, SharedHeartbeatRequest)
        self.assertTrue(issubclass(registry.Node, SharedNodeDescriptor))
        self.assertIsInstance(pilot.node_state(), SharedNodeDescriptor)
        pilot.store.close()

    def test_public_site_build_generates_catalog_and_facts(self) -> None:
        builder = load_module("scripts/build_public_site.py")

        builder.build()

        modules_payload = json.loads((WORKSPACE_ROOT / "public/www/pizza4people/modules.json").read_text(encoding="utf-8"))
        homepage = (WORKSPACE_ROOT / "public/www/pizza4people/index.html").read_text(encoding="utf-8")
        press_kit_en = (WORKSPACE_ROOT / "public/www/pizza4people/press-kit/en.html").read_text(encoding="utf-8")

        module_ids = [entry["module_id"] for entry in modules_payload["modules"]]
        self.assertEqual(
            module_ids,
            [
                "p4p.catalog.editor",
                "p4p.customer.status",
                "p4p.kitchen.screen",
                "p4p.menu.list",
                "p4p.menu.photo-map",
                "p4p.notify.email",
                "p4p.order.print",
                "p4p.payment.cash",
                "p4p.payment.chaospay-mock",
                "p4p.payment.godpay-mock",
                "p4p.stock.basic",
                "p4p.trust.cvr-basic",
            ],
        )
        self.assertIn("HTML kits are the maintained source", homepage)
        self.assertIn("Open base first. Commercial services on top.", press_kit_en)

    def test_lab_gui_is_scenario_config_driven(self) -> None:
        lab = load_module("lab/app.py")
        config = lab.load_lab_config()
        projection = lab.scenario_projection(config)
        page = (REPO_ROOT / "lab/index.html").read_text(encoding="utf-8")

        scenario_ids = {scenario["id"] for scenario in projection["scenarios"]}
        service_ids = set(projection["services"])

        self.assertIn("pilot-photo-map-menu", scenario_ids)
        self.assertIn("registry-client-demo-node", scenario_ids)
        self.assertIn("pilot-photo-map", service_ids)
        self.assertIn("primary-registry", service_ids)
        self.assertIn("p4p.menu.photo-map", config.services["pilot-photo-map"].env["P4P_NODE_MODULES"])
        self.assertIn("food-image-fixtures", config.services["pilot-photo-map"].env["P4P_MENU_ITEM_1_IMAGE_URL"])
        self.assertEqual(config.services["pilot-photo-map"].env["P4P_MENU_ITEM_1_ID"], "margherita")
        self.assertIn("/api/scenarios", page)
        self.assertIn("lab/scenarios.json", page)
        self.assertNotIn("Start Primary Registry", page)
        for scenario in config.scenarios:
            for service_name in scenario.services:
                self.assertIn(service_name, config.services)

    def test_synthetic_menu_photo_map_fixtures_have_manifest_and_files(self) -> None:
        fixture_root = REPO_ROOT / "docs/examples/menu-photo-map-fixtures"
        manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
        readme = (fixture_root / "README.md").read_text(encoding="utf-8")

        self.assertEqual(manifest["status"], "synthetic-test-fixtures")
        self.assertTrue(manifest["policy"]["not_real_restaurants"])
        self.assertTrue(manifest["policy"]["not_partner_material"])
        self.assertIn("not catalog truth", readme.lower())
        currencies = {fixture["currency"] for fixture in manifest["fixtures"]}
        self.assertEqual(currencies, {"BRL", "JPY", "USD", "EUR", "DKK"})
        for fixture in manifest["fixtures"]:
            image_path = fixture_root / fixture["file"]
            self.assertTrue(image_path.exists(), fixture["file"])
            self.assertGreater(image_path.stat().st_size, 100_000, fixture["file"])

    def test_synthetic_food_image_fixtures_have_manifest_and_files(self) -> None:
        fixture_root = REPO_ROOT / "docs/examples/food-image-fixtures"
        manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
        readme = (fixture_root / "README.md").read_text(encoding="utf-8")
        prompts = (fixture_root / "PROMPTS.md").read_text(encoding="utf-8")

        self.assertEqual(manifest["status"], "synthetic-image-fixtures")
        self.assertEqual(manifest["fixture_count"], 22)
        self.assertEqual(manifest["max_fixture_dimension_px"], 900)
        self.assertTrue(manifest["policy"]["not_real_restaurants"])
        self.assertTrue(manifest["policy"]["not_partner_material"])
        self.assertTrue(manifest["policy"]["not_production_catalog_truth"])
        self.assertTrue(manifest["policy"]["not_advertising_claims"])
        self.assertIn("not restaurant data", readme.lower())
        self.assertIn("Global rules", prompts)
        self.assertIn("no logos", prompts)

        categories = {spec["category"] for spec in manifest["prompt_specs"]}
        self.assertEqual(categories, {"dish", "ingredient", "menu-card"})
        self.assertGreaterEqual(len(manifest["prompt_specs"]), 20)
        target_files = [spec["target_file"] for spec in manifest["prompt_specs"]]
        self.assertEqual(len(target_files), len(set(target_files)))
        for target_file in target_files:
            self.assertRegex(target_file, r"^(dishes|ingredients|menu-cards)/[-a-z0-9]+\.png$")
            image_path = fixture_root / target_file
            self.assertIn(image_path.parent.name, {"dishes", "ingredients", "menu-cards"})
            self.assertTrue(image_path.exists(), target_file)
            self.assertGreater(image_path.stat().st_size, 100_000, target_file)

    def test_proof_status_and_release_notes_anchor_public_gate(self) -> None:
        proof_status = (REPO_ROOT / "docs/PROOF-STATUS.md").read_text(encoding="utf-8")
        release_notes = (REPO_ROOT / "docs/RELEASE-NOTES.md").read_text(encoding="utf-8")
        test_guide = (REPO_ROOT / "TEST-GUIDE.md").read_text(encoding="utf-8")

        self.assertIn("HTML kits are the maintained source", proof_status)
        self.assertIn("Simply `455`", proof_status)
        self.assertIn("google-chrome --headless=new", test_guide)
        self.assertIn("docs/PROOF-STATUS.md", test_guide)
        self.assertIn("v0.1.0-proof.1", release_notes)
        self.assertIn("public-main", release_notes)

    def test_reference_module_and_provider_manifests_keep_frozen_fields(self) -> None:
        module_root = REPO_ROOT / "modules"
        module_ids: list[str] = []
        module_payloads: list[dict[str, object]] = []
        provider_payloads: list[dict[str, object]] = []

        for module_dir in sorted(path for path in module_root.iterdir() if path.is_dir()):
            module_payload = json.loads((module_dir / "module.json").read_text(encoding="utf-8"))
            provider_payload = json.loads((module_dir / "provider.json").read_text(encoding="utf-8"))
            module_ids.append(str(module_payload["module_id"]))
            module_payloads.append(module_payload)
            provider_payloads.append(provider_payload)

        required_module_keys = {
            "module_id",
            "module_class",
            "lane",
            "type",
            "provider_id",
            "version",
            "status",
            "description",
            "visibility",
            "capabilities",
            "input_events",
            "output_events",
            "permissions",
            "blocking_policy",
            "idempotency_scope",
            "requires",
            "data_access",
            "entrypoint",
            "signature",
            "public_catalog",
        }
        required_provider_keys = {
            "provider_id",
            "name",
            "description",
            "website",
            "public_key",
            "contact",
            "modules",
            "supported_lanes",
            "status",
            "signature",
        }
        allowed_lanes = {"public_capability", "operator", "trust", "observability"}
        allowed_visibility = {"public", "operator_only", "trust_only"}
        allowed_blocking = {"blocking", "non_blocking", "fallback_required"}

        for payload in module_payloads:
            self.assertTrue(required_module_keys.issubset(payload))
            self.assertIn(payload["lane"], allowed_lanes)
            self.assertIn(payload["visibility"], allowed_visibility)
            self.assertIn(payload["blocking_policy"], allowed_blocking)
            self.assertTrue(payload["capabilities"])
            self.assertTrue(payload["input_events"])
            self.assertTrue(payload["output_events"])
            self.assertTrue(payload["permissions"])
            self.assertIn("function", payload["public_catalog"])
            self.assertIn("data_access_summary", payload["public_catalog"])

        expected_module_ids = sorted(module_ids)
        for payload in provider_payloads:
            self.assertTrue(required_provider_keys.issubset(payload))
            self.assertEqual(sorted(payload["modules"]), expected_module_ids)
            self.assertTrue(payload["supported_lanes"])

        provider_schema = json.loads(
            (REPO_ROOT / "docs/schemas/provider-manifest.schema.json").read_text(encoding="utf-8")
        )
        module_schema = json.loads(
            (REPO_ROOT / "docs/schemas/module-manifest.schema.json").read_text(encoding="utf-8")
        )
        node_module_declaration_schema = json.loads(
            (REPO_ROOT / "docs/schemas/node-module-declaration.schema.json").read_text(encoding="utf-8")
        )
        event_schema = json.loads(
            (REPO_ROOT / "docs/schemas/module-result-event.schema.json").read_text(encoding="utf-8")
        )
        event_name_schema = json.loads(
            (REPO_ROOT / "docs/schemas/module-event-name.schema.json").read_text(encoding="utf-8")
        )
        provider_example = json.loads(
            (REPO_ROOT / "docs/examples/provider-manifest.json").read_text(encoding="utf-8")
        )
        module_example = json.loads(
            (REPO_ROOT / "docs/examples/module-manifest-print-primary.json").read_text(encoding="utf-8")
        )
        node_module_declaration_example = json.loads(
            (REPO_ROOT / "docs/examples/node-module-declaration.json").read_text(encoding="utf-8")
        )
        event_example = json.loads(
            (REPO_ROOT / "docs/examples/module-result-event-print-timeout.json").read_text(encoding="utf-8")
        )
        allowed_events = set(event_name_schema["enum"])

        self.assertEqual(provider_schema["title"], "P4P Module Provider Manifest")
        self.assertEqual(module_schema["title"], "P4P Module Manifest")
        self.assertEqual(event_name_schema["title"], "P4P Module Event Name")
        self.assertEqual(node_module_declaration_schema["title"], "P4P Node Module Declaration")
        self.assertEqual(event_schema["title"], "P4P Module Result Event")
        self.assertEqual(event_schema["properties"]["event"]["$ref"], "module-event-name.schema.json")
        self.assertEqual(provider_example["provider_id"], "p4p.reference")
        self.assertEqual(module_example["module_id"], "p4p.order.print")
        self.assertEqual(node_module_declaration_example["module_id"], "p4p.payment.cash")
        self.assertEqual(event_example["event"], "PRINT_TIMEOUT")
        self.assertIn("TRUST_CLAIM_REQUESTED", allowed_events)
        self.assertIn("OUTBOUND_ACTION_REQUESTED", allowed_events)

        for payload in module_payloads:
            for field in ("input_events", "output_events", "failure_modes"):
                for event_name in payload.get(field, []):
                    self.assertIn(event_name, allowed_events)
            for event_name in payload.get("suggested_fallbacks", {}):
                self.assertIn(event_name, allowed_events)

    def test_reference_provider_catalog_deduplicates_shared_provider_identity(self) -> None:
        providers = load_reference_provider_catalog()
        modules = load_reference_module_catalog()

        self.assertEqual(sorted(providers), ["p4p.reference"])
        provider = providers["p4p.reference"]
        self.assertEqual(sorted(provider.module_ids), sorted(modules))
        self.assertTrue(provider.supports_lane("operator"))
        self.assertTrue(provider.contains_module("p4p.order.print"))

    def test_reference_provider_catalog_rejects_duplicate_manifest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            modules_root = Path(temp_dir)
            provider_a = modules_root / "module-a"
            provider_b = modules_root / "module-b"
            provider_a.mkdir()
            provider_b.mkdir()

            provider_payload = {
                "provider_id": "p4p.reference",
                "name": "P4P Reference Modules",
                "description": "Reference provider manifest.",
                "website": "https://github.com/DennisHedegreen/p4p",
                "public_key": None,
                "contact": None,
                "modules": ["p4p.order.print"],
                "supported_lanes": ["operator"],
                "status": "unsigned-reference",
                "signature": None,
            }
            (provider_a / "provider.json").write_text(json.dumps(provider_payload), encoding="utf-8")
            drifted_payload = dict(provider_payload)
            drifted_payload["status"] = "drifted-reference"
            (provider_b / "provider.json").write_text(json.dumps(drifted_payload), encoding="utf-8")

            with patch.object(module_catalog, "MODULES_ROOT", modules_root):
                module_catalog.load_reference_provider_catalog.cache_clear()
                module_catalog.load_reference_module_catalog.cache_clear()
                try:
                    with self.assertRaises(ValueError) as error:
                        module_catalog.load_reference_provider_catalog()
                finally:
                    module_catalog.load_reference_provider_catalog.cache_clear()
                    module_catalog.load_reference_module_catalog.cache_clear()

        self.assertIn("Provider manifest drift", str(error.exception))

    def test_reference_module_catalog_rejects_provider_lane_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            modules_root = Path(temp_dir)
            module_dir = modules_root / "p4p.test.module"
            module_dir.mkdir()

            provider_payload = {
                "provider_id": "p4p.test",
                "name": "P4P Test Provider",
                "description": "Reference provider manifest for test-only lane validation.",
                "website": "https://example.com/provider",
                "public_key": None,
                "contact": None,
                "modules": ["p4p.test.module"],
                "supported_lanes": ["public_capability"],
                "status": "unsigned-reference",
                "signature": None,
            }
            module_payload = {
                "module_id": "p4p.test.module",
                "provider_id": "p4p.test",
                "version": "0.1",
                "lane": "operator",
                "visibility": "operator_only",
                "blocking_policy": "non_blocking",
                "capabilities": ["test_capability"],
                "data_access": ["order_summary"],
                "input_events": ["ORDER_ACCEPTED"],
                "output_events": ["ORDER_NEEDS_HUMAN"],
                "failure_modes": ["ORDER_NEEDS_HUMAN"],
                "suggested_fallbacks": {},
                "status": "planned",
                "description": "Synthetic module used to verify provider lane checks.",
                "public_catalog": {},
            }
            (module_dir / "provider.json").write_text(json.dumps(provider_payload), encoding="utf-8")
            (module_dir / "module.json").write_text(json.dumps(module_payload), encoding="utf-8")

            with patch.object(module_catalog, "MODULES_ROOT", modules_root):
                module_catalog.load_reference_provider_catalog.cache_clear()
                module_catalog.load_reference_module_catalog.cache_clear()
                try:
                    with self.assertRaises(ValueError) as error:
                        module_catalog.load_reference_module_catalog()
                finally:
                    module_catalog.load_reference_provider_catalog.cache_clear()
                    module_catalog.load_reference_module_catalog.cache_clear()

        self.assertIn("does not declare support for module lane operator", str(error.exception))

    def test_pilot_order_flow_contract_rejects_human_escalation_after_confirmed_print(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            ),
            make_flow_event(
                event="PRINT_REQUESTED",
                source_module="p4p.order.print",
                action_id="order:ord-flow-1:print:primary",
                side_effect_state="none",
                metadata={"contract_phase": "request"},
            ),
            make_flow_event(
                event="PRINT_SUCCESS_CONFIRMED",
                source_module="p4p.order.print",
                action_id="order:ord-flow-1:print:primary",
                metadata={"contract_phase": "result", "adapter_target": "printer"},
            ),
        ]

        next_event = make_flow_event(
            event="ORDER_NEEDS_HUMAN",
            source_module="p4p.order.receiver",
            action_id="order:ord-flow-1:needs-human",
            outcome="NEEDS_HUMAN",
            severity="critical",
            side_effect_state="none",
            metadata={"contract_phase": "result", "trigger_event": "PRINT_SUCCESS_CONFIRMED"},
        )

        with self.assertRaises(ValueError) as error:
            validate_pilot_order_event_flow(existing_events, next_event)

        self.assertIn("forbids ORDER_NEEDS_HUMAN after PRINT_SUCCESS_CONFIRMED", str(error.exception))

    def test_pilot_order_flow_contract_rejects_notification_trigger_drift(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            ),
            make_flow_event(
                event="PRINT_REQUESTED",
                source_module="p4p.order.print",
                action_id="order:ord-flow-1:print:primary",
                side_effect_state="none",
                metadata={"contract_phase": "request"},
            ),
            make_flow_event(
                event="PRINTER_OFFLINE",
                source_module="p4p.order.print",
                action_id="order:ord-flow-1:print:primary",
                outcome="UNAVAILABLE",
                severity="high",
                retryable=True,
                side_effect_state="none",
                metadata={"contract_phase": "result", "adapter_target": "printer"},
            ),
        ]

        next_event = make_flow_event(
            event="NOTIFICATION_SENT",
            source_module="p4p.notify.email",
            action_id="order:ord-flow-1:notify:email",
            severity="medium",
            metadata={"contract_phase": "result", "trigger_event": "PRINT_TIMEOUT"},
        )

        with self.assertRaises(ValueError) as error:
            validate_pilot_order_event_flow(existing_events, next_event)

        self.assertIn("notification trigger_event=PRINTER_OFFLINE", str(error.exception))

    def test_pilot_order_flow_contract_allows_payment_module_between_accept_and_print(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            )
        ]

        payment_requested = make_flow_event(
            event="PAYMENT_REQUIRED",
            source_module="p4p.payment.cash",
            action_id="order:ord-flow-1:payment:cash",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            payment_requested,
            enabled_module_ids=("p4p.payment.cash", "p4p.order.print"),
        )
        existing_events.append(payment_requested)

        payment_changed = make_flow_event(
            event="PAYMENT_MODE_CHANGED",
            source_module="p4p.payment.cash",
            action_id="order:ord-flow-1:payment:cash",
            metadata={"contract_phase": "result"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            payment_changed,
            enabled_module_ids=("p4p.payment.cash", "p4p.order.print"),
        )
        existing_events.append(payment_changed)

        print_requested = make_flow_event(
            event="PRINT_REQUESTED",
            source_module="p4p.order.print",
            action_id="order:ord-flow-1:print:primary",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            print_requested,
            enabled_module_ids=("p4p.payment.cash", "p4p.order.print"),
        )

    def test_pilot_order_flow_contract_allows_payment_failure_to_trigger_human(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            ),
            make_flow_event(
                event="PAYMENT_REQUIRED",
                source_module="p4p.payment.cash",
                action_id="order:ord-flow-1:payment:cash",
                side_effect_state="none",
                metadata={"contract_phase": "request"},
            ),
            make_flow_event(
                event="PAYMENT_FAILED",
                source_module="p4p.payment.cash",
                action_id="order:ord-flow-1:payment:cash",
                outcome="FAILED_RETRYABLE",
                severity="high",
                retryable=True,
                side_effect_state="none",
                metadata={"contract_phase": "result"},
            ),
        ]

        next_event = make_flow_event(
            event="ORDER_NEEDS_HUMAN",
            source_module="p4p.order.receiver",
            action_id="order:ord-flow-1:needs-human",
            outcome="NEEDS_HUMAN",
            severity="critical",
            side_effect_state="none",
            metadata={"contract_phase": "result", "trigger_event": "PAYMENT_FAILED"},
        )

        validate_pilot_order_event_flow(
            existing_events,
            next_event,
            enabled_module_ids=("p4p.payment.cash",),
        )

    def test_pilot_order_flow_contract_does_not_allow_payment_path_without_payment_module(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            )
        ]

        payment_requested = make_flow_event(
            event="PAYMENT_REQUIRED",
            source_module="p4p.payment.cash",
            action_id="order:ord-flow-1:payment:cash",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )

        with self.assertRaises(ValueError) as error:
            validate_pilot_order_event_flow(existing_events, payment_requested, enabled_module_ids=("p4p.order.print",))

        self.assertIn("forbids PAYMENT_REQUIRED after ORDER_ACCEPTED", str(error.exception))

    def test_pilot_order_flow_contract_allows_stock_module_between_accept_and_print(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            )
        ]

        stock_validated = make_flow_event(
            event="ORDER_VALIDATED",
            source_module="p4p.stock.basic",
            action_id="order:ord-flow-1:stock:basic",
            metadata={"contract_phase": "result"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            stock_validated,
            enabled_module_ids=("p4p.stock.basic", "p4p.order.print"),
        )
        existing_events.append(stock_validated)

        print_requested = make_flow_event(
            event="PRINT_REQUESTED",
            source_module="p4p.order.print",
            action_id="order:ord-flow-1:print:primary",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            print_requested,
            enabled_module_ids=("p4p.stock.basic", "p4p.order.print"),
        )

    def test_pilot_order_flow_contract_allows_stock_failure_to_trigger_human(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            ),
            make_flow_event(
                event="ITEM_NOT_POSSIBLE",
                source_module="p4p.stock.basic",
                action_id="order:ord-flow-1:stock:basic",
                outcome="FAILED_PERMANENT",
                severity="medium",
                side_effect_state="none",
                metadata={"contract_phase": "result"},
            ),
        ]

        next_event = make_flow_event(
            event="ORDER_NEEDS_HUMAN",
            source_module="p4p.order.receiver",
            action_id="order:ord-flow-1:needs-human",
            outcome="NEEDS_HUMAN",
            severity="high",
            side_effect_state="none",
            metadata={"contract_phase": "result", "trigger_event": "ITEM_NOT_POSSIBLE"},
        )

        validate_pilot_order_event_flow(
            existing_events,
            next_event,
            enabled_module_ids=("p4p.stock.basic",),
        )

    def test_pilot_order_flow_contract_composes_stock_and_payment_extensions(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            )
        ]

        stock_validated = make_flow_event(
            event="ORDER_VALIDATED",
            source_module="p4p.stock.basic",
            action_id="order:ord-flow-1:stock:basic",
            metadata={"contract_phase": "result"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            stock_validated,
            enabled_module_ids=("p4p.stock.basic", "p4p.payment.cash", "p4p.order.print"),
        )
        existing_events.append(stock_validated)

        payment_requested = make_flow_event(
            event="PAYMENT_REQUIRED",
            source_module="p4p.payment.cash",
            action_id="order:ord-flow-1:payment:cash",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            payment_requested,
            enabled_module_ids=("p4p.stock.basic", "p4p.payment.cash", "p4p.order.print"),
        )
        existing_events.append(payment_requested)

        payment_changed = make_flow_event(
            event="PAYMENT_MODE_CHANGED",
            source_module="p4p.payment.cash",
            action_id="order:ord-flow-1:payment:cash",
            metadata={"contract_phase": "result"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            payment_changed,
            enabled_module_ids=("p4p.stock.basic", "p4p.payment.cash", "p4p.order.print"),
        )
        existing_events.append(payment_changed)

        print_requested = make_flow_event(
            event="PRINT_REQUESTED",
            source_module="p4p.order.print",
            action_id="order:ord-flow-1:print:primary",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            print_requested,
            enabled_module_ids=("p4p.stock.basic", "p4p.payment.cash", "p4p.order.print"),
        )

    def test_pilot_order_flow_contract_keeps_direct_print_path_when_optional_modules_are_enabled(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            )
        ]

        print_requested = make_flow_event(
            event="PRINT_REQUESTED",
            source_module="p4p.order.print",
            action_id="order:ord-flow-1:print:primary",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            print_requested,
            enabled_module_ids=("p4p.stock.basic", "p4p.payment.cash", "p4p.order.print"),
        )

    def test_pilot_order_flow_contract_keeps_direct_print_path_after_stock_even_when_payment_is_enabled(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            ),
            make_flow_event(
                event="ORDER_VALIDATED",
                source_module="p4p.stock.basic",
                action_id="order:ord-flow-1:stock:basic",
                metadata={"contract_phase": "result"},
            ),
        ]

        print_requested = make_flow_event(
            event="PRINT_REQUESTED",
            source_module="p4p.order.print",
            action_id="order:ord-flow-1:print:primary",
            side_effect_state="none",
            metadata={"contract_phase": "request"},
        )
        validate_pilot_order_event_flow(
            existing_events,
            print_requested,
            enabled_module_ids=("p4p.stock.basic", "p4p.payment.cash", "p4p.order.print"),
        )

    def test_pilot_order_flow_contract_rejects_stock_path_without_stock_module(self) -> None:
        existing_events = [
            make_flow_event(
                event="ORDER_ACCEPTED",
                source_module="p4p.order.receiver",
                action_id="order:ord-flow-1:accept",
                metadata={"contract_phase": "result"},
            )
        ]

        stock_validated = make_flow_event(
            event="ORDER_VALIDATED",
            source_module="p4p.stock.basic",
            action_id="order:ord-flow-1:stock:basic",
            metadata={"contract_phase": "result"},
        )

        with self.assertRaises(ValueError) as error:
            validate_pilot_order_event_flow(existing_events, stock_validated, enabled_module_ids=("p4p.order.print",))

        self.assertIn("forbids ORDER_VALIDATED after ORDER_ACCEPTED", str(error.exception))

    def test_pilot_build_result_event_rejects_unknown_runtime_module_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.order.print",
                },
            )
            execution = sys.modules["pilot_node.execution"]
            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            order = pilot.store.create_order(self.make_pilot_order_request(pilot))

            with self.assertRaises(ValueError) as error:
                execution.build_result_event(
                    runtime=runtime,
                    event="ORDER_ACCEPTED",
                    source_module="p4p.unknown.module",
                    order=order,
                    action_id="order:ord-flow-1:unknown",
                    idempotency_key="order:ord-flow-1:unknown",
                    outcome="SUCCESS",
                    severity="low",
                    retryable=False,
                    side_effect_state="confirmed",
                )

            self.assertIn("Unknown runtime module id", str(error.exception))
            pilot.store.close()

    def test_pilot_build_result_event_rejects_reserved_contract_phase_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.order.print",
                },
            )
            execution = sys.modules["pilot_node.execution"]
            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            order = pilot.store.create_order(self.make_pilot_order_request(pilot))

            with self.assertRaises(ValueError) as error:
                execution.build_result_event(
                    runtime=runtime,
                    event="PRINT_REQUESTED",
                    source_module="p4p.order.print",
                    order=order,
                    action_id="order:ord-flow-1:print:primary",
                    idempotency_key="print:ord-flow-1:primary",
                    outcome="SUCCESS",
                    severity="low",
                    retryable=False,
                    side_effect_state="none",
                    contract_phase=execution.REQUEST_PHASE,
                    metadata={"contract_phase": "result"},
                )

            self.assertIn("contract_phase is reserved event metadata", str(error.exception))
            pilot.store.close()

    def test_pilot_build_result_event_rejects_conflicting_trigger_event_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.order.print,p4p.notify.email",
                },
            )
            execution = sys.modules["pilot_node.execution"]
            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME
            order = pilot.store.create_order(self.make_pilot_order_request(pilot))

            with self.assertRaises(ValueError) as error:
                execution.build_result_event(
                    runtime=runtime,
                    event="NOTIFICATION_SENT",
                    source_module="p4p.notify.email",
                    order=order,
                    action_id="order:ord-flow-1:notify:email",
                    idempotency_key="notify:ord-flow-1:email",
                    outcome="SUCCESS",
                    severity="medium",
                    retryable=False,
                    side_effect_state="confirmed",
                    trigger_event="PRINTER_OFFLINE",
                    metadata={execution.TRIGGER_EVENT_METADATA_KEY: "PRINT_TIMEOUT"},
                )

            self.assertIn("trigger_event metadata must match explicit trigger_event", str(error.exception))
            pilot.store.close()

    def test_pilot_module_supports_fallback_rejects_unknown_runtime_module_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pilot = load_module(
                "pilot-node/pilot_node.py",
                {
                    "P4P_PILOT_NODE_DB_PATH": str(Path(tmpdir) / "pilot.sqlite3"),
                    "P4P_NODE_BASE_URL": "http://127.0.0.1:8201",
                    "P4P_NODE_MODULES": "p4p.order.print,p4p.notify.email",
                },
            )
            execution = sys.modules["pilot_node.execution"]
            runtime = sys.modules[f"{pilot.__name__}_app"].RUNTIME

            with self.assertRaises(ValueError) as error:
                execution.module_supports_fallback(
                    runtime,
                    "p4p.order.print",
                    "PRINTER_OFFLINE",
                    "p4p.unknown.module",
                )

            self.assertIn("Unknown runtime module id", str(error.exception))
            pilot.store.close()

    def test_client_select_node_handles_unreachable_menu(self) -> None:
        result = subprocess.run(
            ["node", str(REPO_ROOT / "tests/client_select_node_failure.mjs")],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_client_prefers_directory_module_overlay_when_available(self) -> None:
        result = subprocess.run(
            ["node", str(REPO_ROOT / "tests/client_directory_overlay.mjs")],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_registry_lifespan_closes_persistent_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = load_module(
                "registry/main.py",
                {
                    "P4P_REGISTRY_DB_PATH": str(Path(temp_dir) / "registry.sqlite3"),
                },
            )

            self.assertTrue(registry.store.persistence_enabled)

            async def exercise_lifespan() -> None:
                async with registry.app.router.lifespan_context(registry.app):
                    self.assertTrue(registry.store.persistence_enabled)

            asyncio.run(exercise_lifespan())

            self.assertFalse(registry.store.persistence_enabled)


if __name__ == "__main__":
    unittest.main()
