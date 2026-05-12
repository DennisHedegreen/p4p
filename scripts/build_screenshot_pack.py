from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


P4P_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = (
    P4P_ROOT.parent
    if (P4P_ROOT.parent / "private").exists() or (P4P_ROOT.parent / "public").exists()
    else P4P_ROOT
)
ROOT = WORKSPACE_ROOT
PRIVATE_SCREENSHOT_PACK_PATH = ROOT / "private/data/p4p/screenshot-pack.json"
REPO_SCREENSHOT_PACK_PATH = P4P_ROOT / "docs/screenshot-pack.json"

PUBLIC_SITE_PORT = 8765
REGISTRY_PORT = 8000
OPERATOR_PORT = 8211
RAW_BACKGROUND = "#edf4ee"
PUBLIC_CANVAS = (1600, 1200)
GITHUB_CANVAS = (1320, 980)
PLATE_BACKGROUND_TOP = "#eef5ef"
PLATE_BACKGROUND_BOTTOM = "#dbe9de"
TABLET_SHELL = "#1d2824"
TABLET_EDGE = "#33433d"
PILL_NEXT = "#136f63"
PILL_PROOF = "#7e4f13"
TITLE_COLOR = "#10201c"
MUTED_COLOR = "#4d6159"
ROUTE_COLOR = "#2a5148"
SHADOW_COLOR = (11, 19, 16, 70)


OPERATOR_CROP = {
    "operator-operations-tablet": (22, 158, 22, 28),
    "operator-catalog-tablet": (22, 154, 22, 28),
    "operator-modules-tablet": (22, 154, 22, 28),
    "operator-discover-tablet": (22, 154, 22, 28),
    "operator-import-tablet": (22, 154, 22, 28),
    "operator-module-detail-tablet": (22, 150, 22, 28),
}

PUBLIC_CROP = {
    "protocols-shop-family": (16, 90, 16, 26),
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_first_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Could not resolve required path from: {joined}")


SCREENSHOT_PACK_PATH = resolve_first_existing_path(PRIVATE_SCREENSHOT_PACK_PATH, REPO_SCREENSHOT_PACK_PATH)
SCREENSHOT_PACK_BASE_ROOT = ROOT if SCREENSHOT_PACK_PATH == PRIVATE_SCREENSHOT_PACK_PATH else P4P_ROOT


def resolve_pack_path(raw_path: str, *, default: str) -> Path:
    return SCREENSHOT_PACK_BASE_ROOT / str(raw_path or default)


def mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def choose_free_port(preferred: int) -> int:
    for candidate in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError(f"Could not find a free loopback port near {preferred}")


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        font_path = Path(candidate)
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


@dataclass
class ManagedProcess:
    name: str
    popen: subprocess.Popen[str]
    log_path: Path

    def stop(self) -> None:
        if self.popen.poll() is not None:
            return
        self.popen.terminate()
        try:
            self.popen.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.popen.kill()
            self.popen.wait(timeout=4)


class ScreenshotBuilder:
    def __init__(self) -> None:
        self.pack = load_json(SCREENSHOT_PACK_PATH)
        defaults = self.pack["defaults"]
        self.public_asset_dir = resolve_pack_path(
            str(defaults.get("public_asset_dir", "")),
            default="docs/assets/screenshots",
        )
        self.raw_capture_dir = resolve_pack_path(
            str(defaults.get("raw_capture_dir", "")),
            default=".local/screenshots/raw",
        )
        self.working_dir = resolve_pack_path(
            str(defaults.get("working_dir", "")),
            default=".local/screenshots/edited",
        )
        self.public_port = choose_free_port(PUBLIC_SITE_PORT)
        self.registry_port = choose_free_port(REGISTRY_PORT)
        self.operator_port = choose_free_port(OPERATOR_PORT)
        self.operator_token = "screenshot-secret"
        self.operator_base_url = f"http://127.0.0.1:{self.operator_port}"
        self.public_base_url = f"http://127.0.0.1:{self.public_port}"
        self.temp_dir = self.working_dir / "_runtime"
        self.logs_dir = self.temp_dir / "logs"
        self.manifest_path = self.temp_dir / "imported-demo-module.json"
        self.db_path = self.temp_dir / "screenshot-pack.sqlite3"
        self.processes: list[ManagedProcess] = []

    def build(self) -> None:
        mkdir(self.public_asset_dir)
        mkdir(self.raw_capture_dir)
        mkdir(self.working_dir)
        mkdir(self.temp_dir)
        mkdir(self.logs_dir)
        self._build_public_site()
        self._write_import_manifest()
        with ExitStack():
            self._start_services()
            self._seed_demo_state()
            self._capture_all()

    def _build_public_site(self) -> None:
        subprocess.run(
            [str(P4P_ROOT / ".venv/bin/python"), str(P4P_ROOT / "scripts/build_public_site.py")],
            cwd=ROOT,
            check=True,
        )

    def _start_services(self) -> None:
        self._start_public_server()
        self._start_registry()
        self._start_operator_node()
        self._wait_for_http(f"{self.public_base_url}/pizza4people/")
        self._wait_for_http(f"http://127.0.0.1:{self.registry_port}/health")
        self._wait_for_http(f"{self.operator_base_url}/health")

    def _start_process(
        self,
        *,
        name: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        log_path = self.logs_dir / f"{name}.log"
        handle = log_path.open("w", encoding="utf-8")
        popen = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.processes.append(ManagedProcess(name=name, popen=popen, log_path=log_path))

    def _start_public_server(self) -> None:
        self._start_process(
            name="public-www",
            command=[
                "python3",
                "-m",
                "http.server",
                str(self.public_port),
                "--directory",
                str(ROOT / "public/www"),
            ],
            cwd=ROOT,
        )

    def _start_registry(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(P4P_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        self._start_process(
            name="registry",
            command=[
                str(P4P_ROOT / "registry/.venv/bin/python"),
                "-m",
                "uvicorn",
                "main:app",
                "--app-dir",
                str(P4P_ROOT / "registry"),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.registry_port),
            ],
            cwd=P4P_ROOT,
            env=env,
        )

    def _start_operator_node(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "P4P_PILOT_NODE_DB_PATH": str(self.db_path),
                "P4P_OPERATOR_TOKEN": self.operator_token,
                "P4P_REGISTRY_URLS": f"http://127.0.0.1:{self.registry_port}",
                "P4P_NODE_BASE_URL": f"http://127.0.0.1:{self.operator_port}",
                "P4P_NODE_ORDER_MODE": "menu_only",
                "P4P_NODE_MODULES": ",".join(
                    [
                        "p4p.catalog.editor",
                        "p4p.catalog.import.ocr",
                        "p4p.menu.list",
                        "p4p.customer.status",
                        "p4p.kitchen.screen",
                        "p4p.payment.cash",
                        "p4p.notify.email",
                    ]
                ),
            }
        )
        self._start_process(
            name="pilot-node",
            command=[
                str(P4P_ROOT / ".venv/bin/python"),
                "-m",
                "uvicorn",
                "pilot_app:app",
                "--app-dir",
                str(P4P_ROOT / "pilot-node"),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.operator_port),
            ],
            cwd=P4P_ROOT,
            env=env,
        )

    def _wait_for_http(self, url: str, *, timeout_seconds: float = 25.0) -> None:
        deadline = time.time() + timeout_seconds
        last_error = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if 200 <= response.status < 500:
                        return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(0.35)
        raise RuntimeError(f"Timed out waiting for {url}: {last_error}")

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        *,
        content_type: str = "application/json",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
        }
        if self.operator_token and "/operator/" in url:
            request_headers["X-P4P-Operator-Token"] = self.operator_token
        if headers:
            request_headers.update(headers)
        data = body
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        if data is not None and content_type:
            request_headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc

    def _write_import_manifest(self) -> None:
        payload = {
            "module_id": "local.shop.counter-note",
            "module_class": "operator_surface",
            "lane": "operator",
            "type": "counter-note",
            "provider_id": "local.demo",
            "version": "0.1",
            "status": "prototype",
            "description": "Homebuilt module manifest imported locally during the metadata-only phase.",
            "visibility": "operator_only",
            "capabilities": ["show_counter_note"],
            "input_events": ["ORDER_READY"],
            "output_events": ["COUNTER_NOTE_VISIBLE"],
            "permissions": ["read.order.status"],
            "blocking_policy": "non_blocking",
            "suggested_fallbacks": {},
            "idempotency_scope": "counter_note",
            "failure_modes": ["COUNTER_NOTE_FAILED"],
            "data_access": ["order_status", "pickup_name"],
            "entrypoint": None,
            "signature": None,
            "public_catalog": {
                "title": {
                    "da": "Counter note",
                    "en": "Counter note",
                },
                "summary": {
                    "da": "Lokalt uploadet modulmanifest gemt som metadata på noden.",
                    "en": "Locally uploaded module manifest stored as metadata on the node.",
                },
                "function": "Lets the counter surface show one local note when an order is ready.",
                "data_access_summary": "Order status and a short pickup name.",
                "trust_status": "local uploaded manifest",
                "readiness": "test",
                "operator_status": "imported as metadata only",
            },
        }
        write_json(self.manifest_path, payload)

    def _seed_demo_state(self) -> None:
        self._request_json(
            "PATCH",
            f"{self.operator_base_url}/operator/setup",
            {
                "operator_locale": "da",
                "hardware_base_profile": "screen_only",
                "hardware_enabled_addons": ["ticket_printer", "order_alert"],
                "catalog_ready": True,
                "local_tests_run": True,
            },
        )
        self._request_json(
            "PUT",
            f"{self.operator_base_url}/operator/menu",
            {"items": self._demo_menu_items()},
        )
        self._request_json(
            "PATCH",
            f"{self.operator_base_url}/operator/modules/set",
            {
                "module_ids": [
                    "p4p.catalog.editor",
                    "p4p.catalog.import.ocr",
                    "p4p.menu.list",
                    "p4p.customer.status",
                    "p4p.kitchen.screen",
                    "p4p.payment.cash",
                    "p4p.notify.email",
                    "p4p.order.print",
                    "p4p.order.alert.basic",
                    "p4p.pickup.board.basic",
                ]
            },
        )
        self._request_json(
            "PATCH",
            f"{self.operator_base_url}/operator/state",
            {"open": True, "order_mode": "live"},
        )
        import_payload = load_json(self.manifest_path)
        self._request_json(
            "POST",
            f"{self.operator_base_url}/operator/modules/import-manifest",
            body=json.dumps(
                {
                    "source_name": self.manifest_path.name,
                    "manifest_json": json.dumps(import_payload, ensure_ascii=False),
                }
            ).encode("utf-8"),
        )
        orders = [
            self._request_json(
                "POST",
                f"{self.operator_base_url}/p4p/order",
                {
                    "customer_name": "Amira",
                    "customer_contact": "+4511111111",
                    "fulfillment": "pickup",
                    "items": [{"id": "pepperoni-pizza", "quantity": 1}, {"id": "fries-large", "quantity": 1}],
                    "note": "Chili on the side",
                    "client_version": "p4p-web-0.1",
                },
                headers={"Content-Type": "application/json"},
            ),
            self._request_json(
                "POST",
                f"{self.operator_base_url}/p4p/order",
                {
                    "customer_name": "Yusuf",
                    "customer_contact": "+4522222222",
                    "fulfillment": "pickup",
                    "items": [{"id": "durum-kebab", "quantity": 2}],
                    "note": "No onion",
                    "client_version": "p4p-web-0.1",
                },
                headers={"Content-Type": "application/json"},
            ),
            self._request_json(
                "POST",
                f"{self.operator_base_url}/p4p/order",
                {
                    "customer_name": "Sara",
                    "customer_contact": "+4533333333",
                    "fulfillment": "pickup",
                    "items": [{"id": "margherita-pizza", "quantity": 1}, {"id": "salad-side", "quantity": 1}],
                    "note": "Ready after 18:15",
                    "client_version": "p4p-web-0.1",
                },
                headers={"Content-Type": "application/json"},
            ),
        ]
        self._request_json(
            "PATCH",
            f"{self.operator_base_url}/operator/orders/{orders[0]['order_id']}",
            {"status": "accepted", "status_message": "In the oven", "estimated_ready_minutes": 14},
        )
        self._request_json(
            "PATCH",
            f"{self.operator_base_url}/operator/orders/{orders[1]['order_id']}",
            {"status": "ready", "status_message": "Ready at counter", "estimated_ready_minutes": 0},
        )
        self._request_json(
            "PATCH",
            f"{self.operator_base_url}/operator/orders/{orders[2]['order_id']}",
            {"status": "accepted", "status_message": "Queueing second batch", "estimated_ready_minutes": 18},
        )
        self._request_json("POST", f"{self.operator_base_url}/operator/reannounce")

    def _demo_menu_items(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "margherita-pizza",
                "name": "Margherita",
                "description": "Tomato, mozzarella, basil.",
                "price": 9500,
                "category": "pizza",
                "active": True,
                "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-margherita-pizza.png",
            },
            {
                "id": "pepperoni-pizza",
                "name": "Pepperoni",
                "description": "Pepperoni, mozzarella, chili oil.",
                "price": 10900,
                "category": "pizza",
                "active": True,
                "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-pepperoni-pizza.png",
            },
            {
                "id": "durum-kebab",
                "name": "Durum kebab",
                "description": "Kebab, salad, garlic dressing.",
                "price": 7900,
                "category": "rolls",
                "active": True,
                "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-durum-kebab.png",
            },
            {
                "id": "cheeseburger-meal",
                "name": "Cheeseburger meal",
                "description": "Cheeseburger with fries and dip.",
                "price": 8900,
                "category": "burger",
                "active": True,
                "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-cheeseburger.png",
            },
            {
                "id": "fries-large",
                "name": "Large fries",
                "description": "Salted fries with optional chili mayo.",
                "price": 3500,
                "category": "sides",
                "active": True,
                "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-fries.png",
            },
            {
                "id": "salad-side",
                "name": "Side salad",
                "description": "Tomato, olive, basil, and garlic dressing.",
                "price": 2900,
                "category": "sides",
                "active": True,
                "image_url": "/p4p/assets/food-image-fixtures/dishes/dish-side-salad.png",
            },
        ]

    def _capture_all(self) -> None:
        for entry in sorted(self.pack["screenshots"], key=lambda row: row["display_order"]):
            self._capture_one(entry)

    def _capture_one(self, entry: dict[str, Any]) -> None:
        raw_path = self.raw_capture_dir / f"{entry['id']}.png"
        public_path = self.public_asset_dir / str(entry["assets"]["public"])
        github_path = self.public_asset_dir / str(entry["assets"]["github"])
        url = self._source_url(entry["source"])
        viewport = entry["source"]["viewport"]
        virtual_time_budget_ms = int(entry["source"].get("virtual_time_budget_ms", 6000))
        subprocess.run(
            [
                "node",
                str(P4P_ROOT / "scripts/capture_page.mjs"),
                "--url",
                url,
                "--output",
                str(raw_path),
                "--width",
                str(viewport["width"]),
                "--height",
                str(viewport["height"]),
                "--wait",
                str(max(800, virtual_time_budget_ms // 4)),
                "--page-type",
                str(entry["source"]["site"]),
                "--token",
                self.operator_token if entry["source"]["site"] == "operator" else "",
            ],
            cwd=ROOT,
            check=True,
        )
        self._curate_plate(entry, raw_path, public_path, github_path)

    def _source_url(self, source: dict[str, Any]) -> str:
        base = self.operator_base_url if source["site"] == "operator" else self.public_base_url
        return f"{base}{source['path']}"

    def _curate_plate(
        self,
        entry: dict[str, Any],
        raw_path: Path,
        public_path: Path,
        github_path: Path,
    ) -> None:
        image = Image.open(raw_path).convert("RGBA")
        cropped = self._crop_image(entry["id"], image, source_site=entry["source"]["site"])
        self._render_plate(
            entry=entry,
            image=cropped,
            destination=public_path,
            canvas_size=PUBLIC_CANVAS,
            github_variant=False,
        )
        self._render_plate(
            entry=entry,
            image=cropped,
            destination=github_path,
            canvas_size=GITHUB_CANVAS,
            github_variant=True,
        )

    def _crop_image(self, screenshot_id: str, image: Image.Image, *, source_site: str) -> Image.Image:
        left = top = right = bottom = 0
        if source_site == "operator":
            left, top, right, bottom = OPERATOR_CROP.get(screenshot_id, (22, 154, 22, 28))
        else:
            left, top, right, bottom = PUBLIC_CROP.get(screenshot_id, (16, 90, 16, 26))
        width, height = image.size
        return image.crop((left, top, width - right, height - bottom))

    def _render_plate(
        self,
        *,
        entry: dict[str, Any],
        image: Image.Image,
        destination: Path,
        canvas_size: tuple[int, int],
        github_variant: bool,
    ) -> None:
        canvas = self._gradient_canvas(canvas_size)
        draw = ImageDraw.Draw(canvas)
        stage = str(entry["stage"])
        locale = "en"
        stage_label = "Controlled live pilot" if stage == "next_gate" else "Public proof"
        title = str(entry["title"].get(locale) or entry["title"].get("da") or entry["id"])
        route = str(entry["source"]["path"])

        pill_font = load_font(24 if not github_variant else 22, bold=True)
        title_font = load_font(52 if not github_variant else 44, bold=True)
        body_font = load_font(24 if not github_variant else 22)
        route_font = load_font(22 if not github_variant else 20)
        pill_color = PILL_NEXT if stage == "next_gate" else PILL_PROOF

        header_x = 108 if not github_variant else 80
        header_y = 84 if not github_variant else 64
        pill_text = stage_label.upper()
        pill_box = draw.rounded_rectangle(
            self._pill_bounds(draw, pill_font, pill_text, header_x, header_y, padding_x=22, padding_y=12),
            radius=24,
            fill=pill_color,
        )
        _ = pill_box
        draw.text((header_x + 22, header_y + 10), pill_text, font=pill_font, fill="#f6fff9")
        draw.text((header_x, header_y + 74), title, font=title_font, fill=TITLE_COLOR)
        subtitle = "Real local surface, captured from the working node." if stage == "next_gate" else "Public human reading layer for the module family."
        draw.text((header_x, header_y + 142), subtitle, font=body_font, fill=MUTED_COLOR)

        tablet_outer = (
            84 if not github_variant else 60,
            280 if not github_variant else 214,
            canvas_size[0] - (84 if not github_variant else 60),
            canvas_size[1] - (82 if not github_variant else 56),
        )
        screen_margin = 34 if not github_variant else 26
        shadow = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_box = (
            tablet_outer[0] + 10,
            tablet_outer[1] + 16,
            tablet_outer[2] + 10,
            tablet_outer[3] + 24,
        )
        shadow_draw.rounded_rectangle(shadow_box, radius=54, fill=SHADOW_COLOR)
        shadow = shadow.filter(ImageFilter.GaussianBlur(26))
        canvas.alpha_composite(shadow)

        tablet = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        tablet_draw = ImageDraw.Draw(tablet)
        tablet_draw.rounded_rectangle(tablet_outer, radius=58, fill=TABLET_SHELL, outline=TABLET_EDGE, width=3)
        screen_box = (
            tablet_outer[0] + screen_margin,
            tablet_outer[1] + screen_margin,
            tablet_outer[2] - screen_margin,
            tablet_outer[3] - screen_margin,
        )
        tablet_draw.rounded_rectangle(screen_box, radius=34, fill="#f4f6f3")
        canvas.alpha_composite(tablet)

        screen_width = screen_box[2] - screen_box[0]
        screen_height = screen_box[3] - screen_box[1]
        screen_image = ImageOps.contain(image, (screen_width, screen_height))
        screen_target = Image.new("RGBA", (screen_width, screen_height), RAW_BACKGROUND)
        offset_x = (screen_width - screen_image.width) // 2
        offset_y = (screen_height - screen_image.height) // 2
        screen_target.alpha_composite(screen_image, dest=(offset_x, offset_y))
        mask = Image.new("L", (screen_width, screen_height), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, screen_width, screen_height), radius=28, fill=255)
        canvas.alpha_composite(screen_target, dest=(screen_box[0], screen_box[1]), source=(0, 0, screen_width, screen_height))
        canvas.putalpha(ImageChops.lighter(canvas.getchannel("A"), Image.new("L", canvas.size, 255)))

        route_y = tablet_outer[3] + (18 if not github_variant else 12)
        route_text = route.replace("/protocols4people", "")
        draw.rounded_rectangle(
            self._pill_bounds(draw, route_font, route_text, header_x, route_y, padding_x=18, padding_y=10),
            radius=20,
            fill="#eff6f0",
            outline="#c7d9ce",
        )
        draw.text((header_x + 18, route_y + 8), route_text, font=route_font, fill=ROUTE_COLOR)

        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(destination, format="PNG", optimize=True)

    def _pill_bounds(
        self,
        draw: ImageDraw.ImageDraw,
        font: ImageFont.ImageFont,
        text: str,
        x: int,
        y: int,
        *,
        padding_x: int,
        padding_y: int,
    ) -> tuple[int, int, int, int]:
        left, top, right, bottom = draw.textbbox((x, y), text, font=font)
        width = right - left
        height = bottom - top
        return (x, y, x + width + padding_x * 2, y + height + padding_y * 2)

    def _gradient_canvas(self, size: tuple[int, int]) -> Image.Image:
        width, height = size
        top = Image.new("RGB", (width, height), PLATE_BACKGROUND_TOP)
        bottom = Image.new("RGB", (width, height), PLATE_BACKGROUND_BOTTOM)
        mask = Image.linear_gradient("L").resize((width, height))
        blended = Image.composite(bottom, top, mask)
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.ellipse(
            (-140, -80, width * 0.55, height * 0.48),
            fill=(212, 232, 219, 140),
        )
        overlay_draw.ellipse(
            (width * 0.55, height * 0.08, width + 90, height * 0.86),
            fill=(204, 228, 213, 70),
        )
        return Image.alpha_composite(blended.convert("RGBA"), overlay)

    def stop(self) -> None:
        for process in reversed(self.processes):
            process.stop()


def main() -> None:
    builder = ScreenshotBuilder()
    try:
        builder.build()
    finally:
        builder.stop()


if __name__ == "__main__":
    main()
