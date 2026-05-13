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
import module_catalog as public_module_catalog

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
        providers_payload = json.loads((WORKSPACE_ROOT / "public/www/pizza4people/providers.json").read_text(encoding="utf-8"))
        protocols_modules_payload = json.loads(
            (WORKSPACE_ROOT / "public/www/protocols4people/modules.json").read_text(encoding="utf-8")
        )
        homepage = (WORKSPACE_ROOT / "public/www/pizza4people/index.html").read_text(encoding="utf-8")
        modules_page = (WORKSPACE_ROOT / "public/www/pizza4people/modules/index.html").read_text(encoding="utf-8")
        modules_page_da = (WORKSPACE_ROOT / "public/www/pizza4people/modules/da.html").read_text(encoding="utf-8")
        modules_page_ar = (WORKSPACE_ROOT / "public/www/pizza4people/modules/ar.html").read_text(encoding="utf-8")
        providers_page = (WORKSPACE_ROOT / "public/www/pizza4people/providers/index.html").read_text(encoding="utf-8")
        providers_page_da = (WORKSPACE_ROOT / "public/www/pizza4people/providers/da.html").read_text(encoding="utf-8")
        module_page = (WORKSPACE_ROOT / "public/www/pizza4people/modules/p4p.menu.list/index.html").read_text(encoding="utf-8")
        module_page_da = (
            WORKSPACE_ROOT / "public/www/pizza4people/modules/p4p.menu.list/da.html"
        ).read_text(encoding="utf-8")
        module_page_ar = (
            WORKSPACE_ROOT / "public/www/pizza4people/modules/p4p.menu.list/ar.html"
        ).read_text(encoding="utf-8")
        provider_detail_page = (WORKSPACE_ROOT / "public/www/pizza4people/providers/p4p.reference/index.html").read_text(encoding="utf-8")
        provider_detail_page_da = (
            WORKSPACE_ROOT / "public/www/pizza4people/providers/p4p.reference/da.html"
        ).read_text(encoding="utf-8")
        press_kit_en = (WORKSPACE_ROOT / "public/www/pizza4people/press-kit/en.html").read_text(encoding="utf-8")
        protocols_modules_page = (
            WORKSPACE_ROOT / "public/www/protocols4people/modules/index.html"
        ).read_text(encoding="utf-8")
        protocols_shop_page = (
            WORKSPACE_ROOT / "public/www/protocols4people/modules/shop/index.html"
        ).read_text(encoding="utf-8")
        screenshot_pack = builder.load_screenshot_pack()
        screenshot_source_root = builder.screenshot_asset_source_root(screenshot_pack)
        public_screenshot_root = WORKSPACE_ROOT / "public/www/pizza4people/assets/screenshots"
        protocols_screenshot_root = WORKSPACE_ROOT / "public/www/protocols4people/assets/screenshots"

        self.assertTrue(builder.SITE_DATA_PATH.exists())
        self.assertTrue(builder.SCREENSHOT_PACK_PATH.exists())

        module_ids = [entry["module_id"] for entry in modules_payload["modules"]]
        self.assertEqual(
            module_ids,
            [
                "p4p.catalog.editor",
                "p4p.catalog.import.ocr",
                "p4p.customer.status",
                "p4p.kitchen.screen",
                "p4p.menu.list",
                "p4p.menu.photo-map",
                "p4p.notify.email",
                "p4p.notify.sms",
                "p4p.order.alert.basic",
                "p4p.order.print",
                "p4p.order.print.backup",
                "p4p.payment.cash",
                "p4p.payment.chaospay-mock",
                "p4p.payment.godpay-mock",
                "p4p.payment.mobilepay",
                "p4p.pickup.board.basic",
                "p4p.stock.basic",
                "p4p.trust.cvr-basic",
            ],
        )
        first_module = modules_payload["modules"][0]
        self.assertIn("module_page_url", first_module)
        self.assertIn("provider_page_url", first_module)
        self.assertIn("module_doc_url", first_module)
        self.assertIn("module_manifest_url", first_module)
        self.assertIn("provider_doc_url", first_module)
        self.assertIn("pizza4people.com/modules/p4p.catalog.editor/", first_module["module_page_url"])
        self.assertIn("pizza4people.com/providers/p4p.reference/", first_module["provider_page_url"])
        self.assertIn("docs/modules/p4p.catalog.editor.md", first_module["module_doc_url"])
        self.assertIn("modules/p4p.catalog.editor/module.json", first_module["module_manifest_url"])
        self.assertIn("docs/providers/p4p.reference.md", first_module["provider_doc_url"])
        self.assertEqual(protocols_modules_payload["default_locale"], "da")
        self.assertEqual(protocols_modules_payload["supported_locales"], ["da", "sv", "tr", "ar", "ku", "en"])
        self.assertEqual(protocols_modules_payload["families"][0]["id"], "shop")
        self.assertIn("p4p.catalog.editor", protocols_modules_payload["families"][0]["recommended_module_ids"])
        self.assertTrue(protocols_modules_payload["modules"])
        self.assertIn("A pizza shop should be able to keep its menu and take orders direct.", homepage)
        self.assertIn("Public proof now", homepage)
        self.assertIn("Not a marketplace app", homepage)
        self.assertIn("Open full module page", homepage)
        self.assertIn("Open provider page", homepage)
        self.assertIn("Open manifest", homepage)
        self.assertIn("open provider catalog", homepage)
        self.assertIn('href="modules/"', homepage)
        self.assertIn('href="modules/#new-here"', homepage)
        self.assertIn("If you run a pizzeria", homepage)
        self.assertIn('details class="module-item', homepage)
        self.assertIn("Simple online menu", homepage)
        self.assertIn("Which module matters first?", modules_page)
        self.assertIn("Start with the simple idea, not the raw ids.", modules_page)
        self.assertIn("P4P core is the road. Modules are optional tools around the road.", modules_page)
        self.assertIn("If you run a shop", modules_page)
        self.assertIn("If you build software", modules_page)
        self.assertIn("If you are skeptical", modules_page)
        self.assertIn("Open simple module guide", modules_page)
        self.assertIn("Three practical ways into the module stack.", modules_page)
        self.assertIn("Open the current stack by role, not by raw id.", modules_page)
        self.assertIn("Start with the customer side", modules_page)
        self.assertIn('href="p4p.menu.list/"', modules_page)
        self.assertIn('<html lang="da" dir="ltr">', modules_page_da)
        self.assertIn("Hvilket modul betyder noget først?", modules_page_da)
        self.assertIn("Hvad kunden ser", modules_page_da)
        self.assertIn("Klik for detaljer", modules_page_da)
        self.assertIn('<html lang="ar" dir="rtl">', modules_page_ar)
        self.assertIn("اللغة", modules_page_ar)
        self.assertIn("Open module page", press_kit_en)
        self.assertIn("provider catalog", press_kit_en)
        self.assertIn("The shop keeps menu and prices", press_kit_en)
        self.assertIn("Full local reading path", press_kit_en)
        self.assertIn("HTML kits are the maintained source", homepage)
        self.assertIn("Open base first. Commercial services on top.", press_kit_en)
        self.assertIn("Protocols4People", protocols_modules_page)
        self.assertIn("module-catalog-payload", protocols_modules_page)
        self.assertIn("/modules/shop/", protocols_modules_page)
        self.assertIn("Protocols4People Shop Modules", protocols_shop_page)
        self.assertIn("module-catalog-payload", protocols_shop_page)
        self.assertIn("What the restaurant will control locally in the controlled pilot.", homepage)
        self.assertIn("They are not the narrow v0.1 proof loop itself.", homepage)
        self.assertIn("assets/screenshots/operator-operations-tablet.png", homepage)
        self.assertIn("What the local node looks like in the controlled pilot", press_kit_en)
        self.assertIn("assets/screenshots/operator-import-tablet.png", press_kit_en)
        self.assertIn(
            "A homebuilt or external module can become visible on the node as metadata before it becomes part of the runtime.",
            press_kit_en,
        )
        self.assertIn("payload.screenshot_sections", protocols_modules_page)
        self.assertIn("assets/screenshots/operator-modules-tablet.png", protocols_modules_page)
        self.assertIn("assets/screenshots/operator-discover-tablet.png", protocols_shop_page)
        self.assertIn("assets/screenshots/operator-import-tablet.png", protocols_shop_page)
        self.assertIn("screenshot_sections", protocols_modules_payload)
        self.assertIn("protocols_catalog", protocols_modules_payload["screenshot_sections"])
        self.assertIn("protocols_shop", protocols_modules_payload["screenshot_sections"])
        screenshot_ids = [entry["id"] for entry in screenshot_pack["screenshots"]]
        self.assertEqual(len(screenshot_ids), len(set(screenshot_ids)))
        for entry in screenshot_pack["screenshots"]:
            self.assertIn(entry["stage"], {"next_gate", "public_proof"})
            self.assertTrue(entry["alt"])
            self.assertTrue(entry["captions"])
            self.assertTrue((screenshot_source_root / entry["assets"]["public"]).exists())
            self.assertTrue((screenshot_source_root / entry["assets"]["github"]).exists())
            self.assertTrue((public_screenshot_root / entry["assets"]["public"]).exists())
            self.assertTrue((protocols_screenshot_root / entry["assets"]["public"]).exists())
        self.assertEqual([entry["provider_id"] for entry in providers_payload["providers"]], ["p4p.reference"])
        first_provider = providers_payload["providers"][0]
        self.assertEqual(first_provider["module_count"], len(module_ids))
        self.assertIn("provider_page_url", first_provider)
        self.assertIn("provider_doc_url", first_provider)
        self.assertIn("provider_manifest_url", first_provider)
        self.assertIn("pizza4people.com/providers/p4p.reference/", first_provider["provider_page_url"])
        self.assertIn("docs/providers/p4p.reference.md", first_provider["provider_doc_url"])
        self.assertIn("modules/p4p.catalog.editor/provider.json", first_provider["provider_manifest_url"])
        self.assertIn("Who stands behind the current Pizza4People tools?", providers_page)
        self.assertIn("Current tool source", providers_page)
        self.assertIn("Good first pages for a shop", providers_page)
        self.assertIn('details class="module-item provider-item', providers_page)
        self.assertIn("../modules/p4p.menu.list/", providers_page)
        self.assertIn('<html lang="da" dir="ltr">', providers_page_da)
        self.assertIn("Hvem står bag de nuværende Pizza4People-værktøjer?", providers_page_da)
        self.assertIn("Nuværende værktøjskilde", providers_page_da)
        self.assertIn("Simple online menu", module_page)
        self.assertIn("For a pizzeria", module_page)
        self.assertIn("Back to module catalog", module_page)
        self.assertIn("Do not stop at one module page.", module_page)
        self.assertIn("See what happens after the order", module_page)
        self.assertIn('href="../p4p.customer.status/"', module_page)
        self.assertIn("Open provider page", module_page)
        self.assertIn("Open GitHub module reference", module_page)
        self.assertIn('<html lang="da" dir="ltr">', module_page_da)
        self.assertIn("Tilbage til modul-katalog", module_page_da)
        self.assertIn('href="../da.html"', module_page_da)
        self.assertIn('<html lang="ar" dir="rtl">', module_page_ar)
        self.assertIn("اللغة", module_page_ar)
        self.assertIn("P4P Reference Modules", provider_detail_page)
        self.assertIn("What this covers right now", provider_detail_page)
        self.assertIn("Good first pages for a shop", provider_detail_page)
        self.assertIn(">Modules<", provider_detail_page)
        self.assertIn("Technical record", provider_detail_page)
        self.assertIn("Simple online menu", provider_detail_page)
        self.assertIn("Open raw provider manifest", provider_detail_page)
        self.assertIn('<html lang="da" dir="ltr">', provider_detail_page_da)
        self.assertIn("Tilbage til provider-katalog", provider_detail_page_da)
        self.assertIn("Teknisk registrering", provider_detail_page_da)

    def test_protocols4people_surface_stays_human_readable_but_narrow(self) -> None:
        protocols_site = (WORKSPACE_ROOT / "public/www/protocols4people/index.html").read_text(encoding="utf-8")

        self.assertIn(
            "A shop, venue, or local service should be able to keep direct contact with people.",
            protocols_site,
        )
        self.assertIn("Three clean ways into the project.", protocols_site)
        self.assertIn("What this site is, and what it is not.", protocols_site)
        self.assertIn("I want the exact protocol language", protocols_site)
        self.assertIn("The umbrella idea in ordinary examples.", protocols_site)
        self.assertIn("GitHub keeps the exact protocol language.", protocols_site)
        self.assertIn("If you want the concrete proof, start with Pizza4People.", protocols_site)
        self.assertIn("What is real now, what comes next, and what is not claimed.", protocols_site)
        self.assertIn("No broad restaurant rollout yet", protocols_site)

    def test_node_control_docs_and_dashboard_keep_registry_boundary_clear(self) -> None:
        node_control_readme = (REPO_ROOT / "node-control/README.md").read_text(encoding="utf-8")
        control = load_module("node-control/node_control.py")

        html = control.dashboard_html(
            {
                "checked_at": "2026-05-07T12:00:00Z",
                "summary": {
                    "configured_registries": 1,
                    "reachable_registries": 1,
                    "unique_nodes": 1,
                    "ready_nodes": 1,
                    "operator_visible_nodes": 1,
                },
                "registries": [
                    {
                        "registry_url": "http://registry-a.test",
                        "health": "up",
                        "health_reason": "ok",
                        "node_count": 1,
                        "snapshot": {"nodes": []},
                    }
                ],
                "nodes": [
                    {
                        "node_id": "dk-test-001",
                        "name": "Test Node",
                        "endpoint": "http://127.0.0.1:8201",
                        "country": "DK",
                        "city": "Brondby",
                        "categories": ["pizza"],
                        "last_seen": "2026-05-07T11:59:00Z",
                        "freshness": "fresh",
                        "open": True,
                        "order_mode": "live",
                        "registry_observations": [
                            {
                                "registry_url": "http://registry-a.test",
                                "last_seen": "2026-05-07T11:59:00Z",
                                "open": True,
                                "order_mode": "live",
                            }
                        ],
                        "observed_by": 1,
                        "announced_modules": ["p4p.payment.cash"],
                        "public_probe": {
                            "status": "ready",
                            "health": {"status": "ready", "accepts_orders": True},
                            "info": {"accepts_orders": True},
                        },
                        "operator_probe": {
                            "access": "ok",
                            "state": {},
                            "modules": {},
                        },
                        "enabled_modules": ["p4p.payment.cash"],
                        "public_modules": ["p4p.payment.cash"],
                        "undeclared_modules": [],
                        "active_by_lane": {"payment": "p4p.payment.cash"},
                        "module_health_counts": {"available": 1},
                        "module_entries": [
                            {
                                "module_id": "p4p.payment.cash",
                                "lane": "payment",
                                "health": "available",
                                "implementation": "builtin_reference",
                            }
                        ],
                        "registry_state": {
                            "ready": True,
                            "registered_registries": ["http://registry-a.test"],
                            "failed_registries": {},
                        },
                    }
                ],
            },
            selected_node_id="dk-test-001",
        )

        self.assertIn("This is not a registry feature.", node_control_readme)
        self.assertIn("GET /api/overview", node_control_readme)
        self.assertIn("P4P Node Control", html)
        self.assertIn("Registry truth stays narrow.", html)
        self.assertIn("Test Node", html)

    def test_five_place_pilot_pack_keeps_hardware_and_security_boundary_explicit(self) -> None:
        pilot_pack = (REPO_ROOT / "docs/FIVE-PLACE-PILOT-PACK.md").read_text(encoding="utf-8")
        preset_env = (REPO_ROOT / "deploy/pilot-node.five-place-presets.env.example").read_text(encoding="utf-8")
        pilot_env = (REPO_ROOT / "deploy/pilot-node.env.example").read_text(encoding="utf-8")

        self.assertIn("Version 5: Counter Full", pilot_pack)
        self.assertIn("Do not expose `/operator` on the public internet.", pilot_pack)
        self.assertIn("Use pickup and pay at pickup only for the first month.", pilot_pack)
        self.assertIn("box_v1_counter", pilot_pack)
        self.assertIn("Version 3: Screen + Bell", preset_env)
        self.assertIn("P4P_HARDWARE_PROFILE=box_v1_counter", preset_env)
        self.assertIn("deploy/pilot-node.five-place-presets.env.example", pilot_env)

    def test_catalog_editor_menu_import_preview_stays_draft_only(self) -> None:
        catalog_doc = (REPO_ROOT / "docs/modules/p4p.catalog.editor.md").read_text(encoding="utf-8")
        import_doc = (REPO_ROOT / "docs/modules/p4p.catalog.import.ocr.md").read_text(encoding="utf-8")
        pilot_readme = (REPO_ROOT / "pilot-node/README.md").read_text(encoding="utf-8")
        i18n_readme = (REPO_ROOT / "data/i18n/README.md").read_text(encoding="utf-8")
        i18n_packs = json.loads((REPO_ROOT / "data/i18n/packs.json").read_text(encoding="utf-8"))
        core_da = json.loads((REPO_ROOT / "data/i18n/core/da.json").read_text(encoding="utf-8"))
        core_sv = json.loads((REPO_ROOT / "data/i18n/core/sv.json").read_text(encoding="utf-8"))
        core_tr = json.loads((REPO_ROOT / "data/i18n/core/tr.json").read_text(encoding="utf-8"))
        core_ar = json.loads((REPO_ROOT / "data/i18n/core/ar.json").read_text(encoding="utf-8"))
        core_ku = json.loads((REPO_ROOT / "data/i18n/core/ku.json").read_text(encoding="utf-8"))
        core_en = json.loads((REPO_ROOT / "data/i18n/core/en.json").read_text(encoding="utf-8"))
        custom_da = json.loads((REPO_ROOT / "data/i18n/custom/example-node/da.json").read_text(encoding="utf-8"))
        custom_tr = json.loads((REPO_ROOT / "data/i18n/custom/example-node/tr.json").read_text(encoding="utf-8"))
        operator_html = (REPO_ROOT / "pilot-node/operator.html").read_text(encoding="utf-8")
        welcome_html = (REPO_ROOT / "pilot-node/operator-welcome.html").read_text(encoding="utf-8")
        setup_html = (REPO_ROOT / "pilot-node/operator-setup.html").read_text(encoding="utf-8")
        catalog_html = (REPO_ROOT / "pilot-node/operator-catalog.html").read_text(encoding="utf-8")
        modules_html = (REPO_ROOT / "pilot-node/operator-modules.html").read_text(encoding="utf-8")
        import_html = (REPO_ROOT / "pilot-node/operator-import.html").read_text(encoding="utf-8")
        node_html = (REPO_ROOT / "pilot-node/operator-node.html").read_text(encoding="utf-8")
        module_html = (REPO_ROOT / "pilot-node/module.html").read_text(encoding="utf-8")
        fixture_readme = (REPO_ROOT / "docs/examples/menu-photo-map-fixtures/README.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("p4p.catalog.import.ocr", catalog_doc)
        self.assertIn("draft-only", import_doc)
        self.assertIn("catalog truth", import_doc)
        self.assertIn("POST /operator/menu/import-preview", import_doc)
        self.assertIn("POST /operator/menu/import-image-preview", import_doc)
        self.assertIn("404", import_doc)
        self.assertIn("p4p.catalog.import.ocr", pilot_readme)
        self.assertIn("docs/HARDWARE-STATE-MODEL.md", pilot_readme)
        self.assertIn("data/i18n/", pilot_readme)
        self.assertIn("LANGUAGE-PACKS-v2", i18n_readme)
        self.assertEqual(i18n_packs["status"], "pilot-read-slice")
        self.assertEqual(i18n_packs["default_locale"], "da")
        self.assertEqual(i18n_packs["available_locales"], ["da", "sv", "tr", "ar", "ku", "en"])
        self.assertEqual(core_da["nav.operations"], "Drift")
        self.assertEqual(core_sv["nav.operations"], "Drift")
        self.assertEqual(core_tr["nav.operations"], "Operasyon")
        self.assertEqual(core_ar["nav.operations"], "التشغيل")
        self.assertEqual(core_ku["nav.operations"], "Çalakî")
        self.assertEqual(core_en["nav.operations"], "Operations")
        self.assertEqual(custom_da["nav.operations"], "Kasse")
        self.assertEqual(custom_tr["nav.operations"], "Tezgâh")
        self.assertEqual(public_module_catalog.shell_text("tr", "nav.operations"), "Operasyon")
        self.assertEqual(public_module_catalog.shell_text("ar", "common.open"), "افتح")
        self.assertEqual(public_module_catalog.shell_text("sv", "common.next_rooms"), core_sv["common.next_rooms"])
        self.assertEqual(public_module_catalog.shell_text("en", "catalog.editor_title"), core_en["catalog.editor_title"])
        self.assertEqual(public_module_catalog.shell_text("ku", "welcome.menu_work_title"), core_ku["welcome.menu_work_title"])
        self.assertEqual(
            public_module_catalog.shell_text("sv", "setup.checklist_title"),
            core_sv["setup.checklist_title"],
        )
        self.assertEqual(
            public_module_catalog.shell_text("tr", "import.local_manifest_title"),
            core_tr["import.local_manifest_title"],
        )
        self.assertEqual(
            public_module_catalog.shell_text("da", "node.runtime_body"),
            core_da["node.runtime_body"],
        )
        self.assertEqual(
            public_module_catalog.shell_text("ar", "setup.checklist_title"),
            core_ar["setup.checklist_title"],
        )
        self.assertEqual(
            public_module_catalog.shell_text("ku", "discover.recommended_title"),
            core_ku["discover.recommended_title"],
        )
        self.assertEqual(
            public_module_catalog.localized_shell_strings("da")["welcome.this_node_body"],
            core_da["welcome.this_node_body"],
        )
        self.assertEqual(
            public_module_catalog.localized_shell_strings("tr")["catalog.photo_import_body"],
            core_tr["catalog.photo_import_body"],
        )
        self.assertEqual(
            public_module_catalog.localized_shell_strings("sv")["discover.recommended_title"],
            core_sv["discover.recommended_title"],
        )
        self.assertEqual(
            public_module_catalog.localized_shell_strings("ku")["node.runtime_body"],
            core_ku["node.runtime_body"],
        )
        self.assertEqual(
            public_module_catalog.localized_shell_strings("ar")["modules.state_title"],
            core_ar["modules.state_title"],
        )
        self.assertIn("POST /operator/menu/import-preview", pilot_readme)
        self.assertIn("POST /operator/menu/import-image-preview", pilot_readme)
        self.assertIn("requirements-ocr.txt", pilot_readme)
        self.assertIn("GET /operator/welcome", pilot_readme)
        self.assertIn("GET /operator/setup", pilot_readme)
        self.assertIn("PATCH /operator/setup", pilot_readme)
        self.assertIn("GET /operator/discover", pilot_readme)
        self.assertIn("GET /operator/import", pilot_readme)
        self.assertIn("GET /operator/node", pilot_readme)
        self.assertIn("PATCH /operator/modules/set", pilot_readme)
        self.assertIn("GET /operator/modules/imports", pilot_readme)
        self.assertIn("POST /operator/modules/import-manifest", pilot_readme)
        self.assertIn("DELETE /operator/modules/imports/{module_id}", pilot_readme)
        self.assertIn("GET /operator/modules/{module_id}", pilot_readme)
        self.assertIn('/operator/assets/operator-shell.css', welcome_html)
        self.assertIn('/operator/assets/operator-shell.css', setup_html)
        self.assertIn('/operator/assets/operator-shell.css', operator_html)
        self.assertIn('/operator/assets/operator-shell.css', catalog_html)
        self.assertIn('/operator/assets/operator-shell.css', modules_html)
        self.assertIn('/operator/assets/operator-shell.css', import_html)
        self.assertIn('/operator/assets/operator-shell.css', module_html)
        self.assertIn('href="/operator/welcome"', operator_html)
        self.assertIn('href="/operator/setup"', operator_html)
        self.assertIn('href="/operator/discover"', operator_html)
        self.assertIn('href="/operator/import"', operator_html)
        self.assertIn('href="/operator/node"', operator_html)
        self.assertIn("{{page_title}}", welcome_html)
        self.assertIn("{{page_title}}", setup_html)
        self.assertIn("{{page_title}}", import_html)
        self.assertIn("Start here", welcome_html)
        self.assertIn("Next rooms", welcome_html)
        self.assertIn("Open discover", welcome_html)
        self.assertIn("Open import", welcome_html)
        self.assertIn("Setup checklist", setup_html)
        self.assertIn("Recorded setup state", setup_html)
        self.assertIn("Use these rooms", setup_html)
        self.assertIn("Base hardware shape", setup_html)
        self.assertIn("Extra hardware on this node", setup_html)
        self.assertIn("Operator language", setup_html)
        self.assertIn('id="save-setup"', setup_html)
        self.assertIn('request("/operator/setup"', setup_html)
        self.assertIn('"Accept": "application/json"', setup_html)
        self.assertIn('"Accept": "application/json"', welcome_html)
        self.assertNotIn("Scan photo", operator_html)
        self.assertNotIn("OCR_IMPORT_MODULE_ID", operator_html)
        self.assertNotIn("Photo OCR import is not enabled on this node.", operator_html)
        self.assertNotIn("Add selected to catalog", operator_html)
        self.assertNotIn("Catalog editor", operator_html)
        self.assertIn('href="/operator/catalog"', operator_html)
        self.assertIn("Backoffice", operator_html)
        self.assertIn("Open OCR module page", catalog_html)
        self.assertIn("renderCatalog", catalog_html)
        self.assertIn("Current modules", modules_html)
        self.assertIn("Available modules", modules_html)
        self.assertIn("Imported manifests", modules_html)
        self.assertIn('href="/operator/import"', modules_html)
        self.assertIn("Open Discover", modules_html)
        self.assertIn("Read public catalog", modules_html)
        self.assertIn("renderModuleStateSummary", modules_html)
        self.assertNotIn('request("/operator/menu"', modules_html)
        self.assertIn("/operator/modules/view/", modules_html)
        self.assertIn("Import local manifest", import_html)
        self.assertIn("/operator/modules/import-manifest", import_html)
        self.assertIn("/operator/modules/imports/", import_html)
        self.assertIn("/operator/modules/", module_html)
        self.assertIn("/operator/modules/set", module_html)
        self.assertIn("Runtime", node_html)
        self.assertIn("Setup truth", node_html)
        self.assertIn("Open import", node_html)
        self.assertIn("OCR import surface", module_html)
        self.assertIn("Scan photo", module_html)
        self.assertIn("Save selected to catalog", module_html)
        self.assertIn("Category before save", module_html)
        self.assertIn("/operator/menu/import-image-preview", module_html)
        self.assertIn("/operator/menu/import-image-preview", fixture_readme)

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
        self.assertIn("$defs", provider_schema)
        self.assertIn("$defs", module_schema)
        self.assertEqual(provider_schema["properties"]["name"]["$ref"], "#/$defs/humanText")
        self.assertEqual(provider_schema["properties"]["description"]["$ref"], "#/$defs/humanText")
        self.assertEqual(module_schema["properties"]["description"]["$ref"], "#/$defs/humanText")
        self.assertEqual(module_schema["properties"]["public_catalog"]["properties"]["title"]["$ref"], "#/$defs/humanText")
        self.assertEqual(module_schema["properties"]["public_catalog"]["properties"]["summary"]["$ref"], "#/$defs/humanText")
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

    def test_reference_module_docs_cover_every_manifest(self) -> None:
        module_root = REPO_ROOT / "modules"
        docs_root = REPO_ROOT / "docs/modules"
        index = (docs_root / "README.md").read_text(encoding="utf-8")
        payment_boundary = (
            "P4P does not hold funds, process payments, store payment credentials, "
            "settle money, or act as merchant of record."
        )
        self.assertIn("Every current module manifest under `modules/` should have exactly one human-readable page in this directory.", index)

        for module_dir in sorted(path for path in module_root.iterdir() if path.is_dir()):
            module_payload = json.loads((module_dir / "module.json").read_text(encoding="utf-8"))
            module_id = str(module_payload["module_id"])
            module_doc = docs_root / f"{module_id}.md"
            self.assertTrue(module_doc.exists(), module_id)

            text = module_doc.read_text(encoding="utf-8")
            self.assertIn(f"# {module_id}", text)
            self.assertIn(f"Status: `{module_payload['status']}`", text)
            self.assertIn(f"../../modules/{module_id}/module.json", text)
            self.assertIn(f"../../modules/{module_id}/provider.json", text)
            self.assertIn("## Purpose", text)
            self.assertIn("## What It Does Not Own", text)
            self.assertIn("## Data Access", text)
            self.assertIn("## Events", text)
            self.assertIn("## Current Readiness", text)
            self.assertIn(f"({module_id}.md)", index)

            if module_payload["module_class"] == "payment":
                self.assertIn(payment_boundary, text)
                self.assertIn("Payment modules are adapters chosen by the restaurant/operator.", text)
            if "mock" in module_id:
                self.assertIn("not real money", text)
                self.assertIn("not real settlement", text)

    def test_reference_provider_docs_cover_every_unique_provider(self) -> None:
        docs_root = REPO_ROOT / "docs/providers"
        index = (docs_root / "README.md").read_text(encoding="utf-8")
        providers = load_reference_provider_catalog()

        self.assertIn(
            "Every unique `provider_id` represented in the current reference manifest catalog should have exactly one human-readable page in this directory.",
            index,
        )

        for provider_id, provider in sorted(providers.items()):
            provider_doc = docs_root / f"{provider_id}.md"
            self.assertTrue(provider_doc.exists(), provider_id)

            text = provider_doc.read_text(encoding="utf-8")
            self.assertIn(f"# {provider_id}", text)
            self.assertIn(f"Status: `{provider.status}`", text)
            self.assertIn("../../modules/", text)
            self.assertIn("## Purpose", text)
            self.assertIn("## Declared Modules", text)
            self.assertIn("## Current Readiness", text)
            self.assertIn(f"({provider_id}.md)", index)

    def test_whitepaper_keeps_public_claim_boundaries(self) -> None:
        whitepaper = (REPO_ROOT / "docs/WHITEPAPER-v0.1.md").read_text(encoding="utf-8")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        docs_index = (REPO_ROOT / "docs/README.md").read_text(encoding="utf-8")
        reader_guide = (REPO_ROOT / "docs/GITHUB-READER-GUIDE.md").read_text(encoding="utf-8")

        self.assertIn("# P4P Working Whitepaper v0.1", whitepaper)
        self.assertIn("not production-ready", whitepaper)
        self.assertIn("advanced prototype", whitepaper)
        self.assertIn("controlled live pilot", whitepaper)
        self.assertIn("P4P is a phone book, not a marketplace.", whitepaper)
        self.assertIn("P4P is the socket, not the appliances.", whitepaper)
        self.assertIn(
            "P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.",
            whitepaper,
        )
        self.assertIn("Do not call this `P4P Pay`.", whitepaper)
        self.assertIn("None of these are real money, real settlement, real wallets, crypto", whitepaper)
        self.assertIn("P4P v0.1 is not:", whitepaper)
        self.assertIn("- a marketplace", whitepaper)
        self.assertIn("- a payment provider", whitepaper)
        self.assertIn("- a crypto project", whitepaper)
        self.assertIn("docs/WHITEPAPER-v0.1.md", readme)
        self.assertIn("WHITEPAPER-v0.1.md", docs_index)
        self.assertIn("docs/WHITEPAPER-v0.1.md", reader_guide)

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
