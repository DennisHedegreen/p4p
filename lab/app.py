from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parent.parent
P4P_ROOT = ROOT
LAB_ROOT = P4P_ROOT / "lab"
WORKSPACE_ROOT = P4P_ROOT.parent
CLIENT_ROOT = P4P_ROOT / "client"
REGISTRY_ROOT = P4P_ROOT / "registry"
NODE_ROOT = P4P_ROOT / "demo-node"
PILOT_NODE_ROOT = P4P_ROOT / "pilot-node"
REGISTRY_PYTHON = REGISTRY_ROOT / ".venv" / "bin" / "python"
NODE_PYTHON = NODE_ROOT / ".venv" / "bin" / "python"
PILOT_NODE_VENV = PILOT_NODE_ROOT / ".venv"
SCENARIOS_PATH = LAB_ROOT / "scenarios.json"


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1, le=25, default=10)


class LabServiceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    description: str = ""
    cwd: str
    command: list[str] = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)
    port: int | None = None
    health_url: str | None = None
    ready_text: str | None = None
    links: list[dict[str, str]] = Field(default_factory=list)


class LabScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    services: list[str] = Field(min_length=1)
    links: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    services: dict[str, LabServiceDefinition]
    scenarios: list[LabScenarioDefinition]


@dataclass
class ManagedProcess:
    name: str
    port: int | None
    kind: str
    cwd: Path
    command: list[str]
    env: dict[str, str]
    description: str = ""
    health_url: str | None = None
    ready_text: str | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    process: subprocess.Popen[str] | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    started_at: float | None = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class ProcessManager:
    def __init__(self) -> None:
        self._services: dict[str, ManagedProcess] = {}
        self._lock = threading.Lock()

    def _append_log(self, name: str, line: str) -> None:
        with self._lock:
            if name in self._services:
                self._services[name].logs.append(line.rstrip())

    def _reader(self, name: str, stream: Any) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                self._append_log(name, line)
        finally:
            stream.close()

    def _spawn(self, service: ManagedProcess) -> ManagedProcess:
        if not service.cwd.exists():
            raise HTTPException(status_code=400, detail=f"Missing working directory: {service.cwd}")
        executable = Path(service.command[0])
        if (executable.is_absolute() or "/" in service.command[0]) and not executable.exists():
            raise HTTPException(status_code=400, detail=f"Missing runtime: {service.command[0]}")

        process = subprocess.Popen(
            service.command,
            cwd=service.cwd,
            env=service.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        service.process = process
        service.started_at = time.time()
        self._services[service.name] = service
        assert process.stdout is not None
        threading.Thread(target=self._reader, args=(service.name, process.stdout), daemon=True).start()
        port_note = f" on port {service.port}" if service.port is not None else ""
        service.logs.append(f"[lab] started {service.name}{port_note}")
        return service

    def start_configured_service(self, definition: LabServiceDefinition) -> ManagedProcess:
        existing = self._services.get(definition.name)
        if existing and existing.is_running():
            return existing

        command = [_resolve_text(part) for part in definition.command]
        cwd = _resolve_path(definition.cwd)
        env = os.environ.copy()
        env.update({key: _resolve_text(value) for key, value in definition.env.items()})
        return self._spawn(
            ManagedProcess(
                name=definition.name,
                port=definition.port,
                kind=definition.kind,
                description=definition.description,
                cwd=cwd,
                command=command,
                env=env,
                health_url=_resolve_text(definition.health_url) if definition.health_url else None,
                ready_text=definition.ready_text,
                links=[_resolve_link(link) for link in definition.links],
            )
        )

    def start_registry(self, name: str, port: int, backups: list[dict[str, Any]]) -> ManagedProcess:
        existing = self._services.get(name)
        if existing and existing.is_running():
            return existing

        env = os.environ.copy()
        env["P4P_REGISTRY_URL"] = f"http://127.0.0.1:{port}"
        env["P4P_BACKUP_REGISTRIES"] = json.dumps(backups)
        command = [str(REGISTRY_PYTHON), "-m", "uvicorn", "main:app", "--port", str(port)]
        return self._spawn(
            ManagedProcess(
                name=name,
                port=port,
                kind="registry",
                description="Registry started by the legacy lab controls.",
                cwd=REGISTRY_ROOT,
                command=command,
                env=env,
            )
        )

    def start_node(
        self,
        *,
        name: str,
        port: int,
        node_index: int,
    ) -> ManagedProcess:
        existing = self._services.get(name)
        if existing and existing.is_running():
            return existing

        lat = 55.6517 + (node_index * 0.0025)
        lng = 12.4126 + (node_index * 0.0030)
        env = os.environ.copy()
        env.update(
            {
                "P4P_REGISTRY_URL": "http://127.0.0.1:8000",
                "P4P_REGISTRY_URLS": "http://127.0.0.1:8000,http://127.0.0.1:8002",
                "P4P_NODE_BASE_URL": f"http://127.0.0.1:{port}",
                "P4P_NODE_KEY_FILE": f"/tmp/p4p-lab-node-{node_index:03d}-identity.json",
                "P4P_NODE_ROOT_KEY_FILE": f"/tmp/p4p-lab-node-{node_index:03d}-root.json",
                "P4P_NODE_ID": f"dk-brondby-test-{node_index:03d}",
                "P4P_NODE_NAME": f"P4P Test Pizzeria {node_index}",
                "P4P_NODE_CITY": "Brondby",
                "P4P_NODE_COUNTRY": "DK",
                "P4P_NODE_CATEGORIES": "pizza,kebab",
                "P4P_NODE_ORDER_MODE": "test",
                "P4P_NODE_DELEGATION_ROLE": "primary",
                "P4P_NODE_MODULES": "p4p.payment.cash",
                "P4P_NODE_LAT": str(lat),
                "P4P_NODE_LNG": str(lng),
                "P4P_MENU_CURRENCY": "DKK",
                "P4P_MENU_ITEM_1_PRICE": str(7000 + node_index * 100),
                "P4P_MENU_ITEM_2_PRICE": str(8000 + node_index * 100),
            }
        )
        command = [str(NODE_PYTHON), "-m", "uvicorn", "demo_node:app", "--port", str(port)]
        return self._spawn(
            ManagedProcess(
                name=name,
                port=port,
                kind="node",
                description="Demo node started by the legacy lab batch controls.",
                cwd=NODE_ROOT,
                command=command,
                env=env,
            )
        )

    def _probe_node_health(self, service: ManagedProcess) -> tuple[bool, int | None, dict[str, Any] | None]:
        if not service.is_running():
            return False, None, None

        url = f"http://127.0.0.1:{service.port}/health"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                status_code = response.getcode()
                body = json.loads(response.read().decode("utf-8"))
                return status_code == 200, status_code, body
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"status": "error", "detail": raw}
            return False, exc.code, body
        except Exception as exc:
            return False, None, {"status": "unreachable", "detail": str(exc)}

    def _probe_client_health(self, service: ManagedProcess) -> tuple[bool, int | None, dict[str, Any] | None]:
        if not service.is_running():
            return False, None, None

        url = f"http://127.0.0.1:{service.port}/"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8", errors="replace")
                looks_like_client = "P4P Client" in body
                return (
                    status_code == 200 and looks_like_client,
                    status_code,
                    {
                        "status": "ready" if looks_like_client else "unexpected_content",
                        "detail": "P4P client root served" if looks_like_client else "unexpected content at /",
                    },
                )
        except urllib.error.HTTPError as exc:
            return False, exc.code, {"status": "error", "detail": f"HTTP {exc.code}"}
        except Exception as exc:
            return False, None, {"status": "unreachable", "detail": str(exc)}

    def start_client_server(self) -> ManagedProcess:
        name = "client-server"
        existing = self._services.get(name)
        if existing and existing.is_running():
            return existing

        command = [sys.executable, "-m", "http.server", "8765", "--directory", str(CLIENT_ROOT)]
        return self._spawn(
            ManagedProcess(
                name=name,
                port=8765,
                kind="client",
                description="Static reference client server.",
                cwd=CLIENT_ROOT,
                command=command,
                env=os.environ.copy(),
            )
        )

    def stop(self, name: str) -> None:
        service = self._services.get(name)
        if service is None or service.process is None:
            return
        if service.process.poll() is None:
            service.process.send_signal(signal.SIGTERM)
            try:
                service.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service.process.kill()
                service.process.wait(timeout=2)
        service.logs.append(f"[lab] stopped {name}")

    def stop_kind(self, kind: str) -> None:
        for name, service in list(self._services.items()):
            if service.kind == kind and service.is_running():
                self.stop(name)

    def status(self) -> dict[str, Any]:
        items = []
        for service in self._services.values():
            usable = service.is_running()
            health_status_code = None
            health = None
            if service.health_url:
                usable, health_status_code, health = self._probe_url_health(service)
            elif service.kind == "node":
                usable, health_status_code, health = self._probe_node_health(service)
            elif service.kind == "client":
                usable, health_status_code, health = self._probe_client_health(service)

            items.append(
                {
                    "name": service.name,
                    "kind": service.kind,
                    "description": service.description,
                    "port": service.port,
                    "url": f"http://127.0.0.1:{service.port}/" if service.port is not None else None,
                    "operator_url": (
                        f"http://127.0.0.1:{service.port}/operator"
                        if service.kind == "node" and service.port is not None
                        else None
                    ),
                    "links": service.links,
                    "command": _command_for_display(service.command),
                    "cwd": str(service.cwd),
                    "running": service.is_running(),
                    "usable": usable,
                    "pid": service.process.pid if service.process else None,
                    "started_at": service.started_at,
                    "health_status_code": health_status_code,
                    "health": health,
                    "logs": list(service.logs),
                }
            )
        items.sort(key=lambda item: (item["kind"], item["port"] if item["port"] is not None else 0))
        return {"services": items}

    def _probe_url_health(self, service: ManagedProcess) -> tuple[bool, int | None, dict[str, Any] | None]:
        if not service.is_running() or not service.health_url:
            return False, None, None

        try:
            with urllib.request.urlopen(service.health_url, timeout=1.5) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8", errors="replace")
                if service.ready_text:
                    ready = service.ready_text in body
                    return (
                        status_code == 200 and ready,
                        status_code,
                        {
                            "status": "ready" if ready else "unexpected_content",
                            "detail": f"Checked {service.health_url}",
                        },
                    )
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {"status": "ready", "detail": f"HTTP {status_code} from {service.health_url}"}
                return status_code == 200, status_code, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return False, exc.code, {"status": "error", "detail": raw or f"HTTP {exc.code}"}
        except Exception as exc:
            return False, None, {"status": "unreachable", "detail": str(exc)}


def _placeholders() -> dict[str, str]:
    return {
        "workspace_root": str(WORKSPACE_ROOT),
        "p4p_root": str(P4P_ROOT),
        "lab_root": str(LAB_ROOT),
        "client_root": str(CLIENT_ROOT),
        "registry_root": str(REGISTRY_ROOT),
        "demo_node_root": str(NODE_ROOT),
        "pilot_node_root": str(PILOT_NODE_ROOT),
        "registry_python": str(REGISTRY_PYTHON),
        "demo_node_python": str(NODE_PYTHON),
        "pilot_node_venv": str(PILOT_NODE_VENV),
        "python": sys.executable,
    }


def _resolve_text(value: str) -> str:
    resolved = value
    for key, replacement in _placeholders().items():
        resolved = resolved.replace("{" + key + "}", replacement)
    return resolved


def _resolve_path(value: str) -> Path:
    return Path(_resolve_text(value)).expanduser()


def _resolve_link(link: dict[str, str]) -> dict[str, str]:
    return {key: _resolve_text(value) for key, value in link.items()}


def _command_for_display(command: list[str]) -> str:
    return " ".join(command)


def load_lab_config() -> LabConfig:
    payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    return LabConfig.model_validate(payload)


def scenario_projection(config: LabConfig) -> dict[str, Any]:
    services = {
        name: {
            "name": service.name,
            "kind": service.kind,
            "description": service.description,
            "port": service.port,
            "cwd": _resolve_text(service.cwd),
            "command": _command_for_display([_resolve_text(part) for part in service.command]),
            "links": [_resolve_link(link) for link in service.links],
        }
        for name, service in config.services.items()
    }
    return {
        "version": config.version,
        "scenarios": [
            {
                "id": scenario.id,
                "title": scenario.title,
                "description": scenario.description,
                "services": scenario.services,
                "links": [_resolve_link(link) for link in scenario.links],
                "notes": scenario.notes,
            }
            for scenario in config.scenarios
        ],
        "services": services,
    }


manager = ProcessManager()
app = FastAPI(title="P4P Lab", version="0.1")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return manager.status()


@app.get("/api/scenarios")
def api_scenarios() -> dict[str, Any]:
    return scenario_projection(load_lab_config())


@app.post("/api/scenarios/{scenario_id}/start")
def start_scenario(scenario_id: str) -> dict[str, Any]:
    config = load_lab_config()
    scenario = next((item for item in config.scenarios if item.id == scenario_id), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}")
    for service_name in scenario.services:
        definition = config.services.get(service_name)
        if definition is None:
            raise HTTPException(status_code=400, detail=f"Scenario references unknown service: {service_name}")
        manager.start_configured_service(definition)
    return manager.status()


@app.post("/api/scenarios/{scenario_id}/stop")
def stop_scenario(scenario_id: str) -> dict[str, Any]:
    config = load_lab_config()
    scenario = next((item for item in config.scenarios if item.id == scenario_id), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}")
    for service_name in scenario.services:
        manager.stop(service_name)
    return manager.status()


@app.post("/api/services/{service_name}/start")
def start_configured_service(service_name: str) -> dict[str, Any]:
    config = load_lab_config()
    definition = config.services.get(service_name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown configured service: {service_name}")
    manager.start_configured_service(definition)
    return manager.status()


@app.post("/api/start/primary")
def start_primary() -> dict[str, Any]:
    manager.start_registry(
        "primary-registry",
        8000,
        [
            {"tier": 0, "url": "http://127.0.0.1:8000"},
            {"tier": 1, "url": "http://127.0.0.1:8002"},
        ],
    )
    return manager.status()


@app.post("/api/start/backup")
def start_backup() -> dict[str, Any]:
    manager.start_registry(
        "backup-registry",
        8002,
        [
            {"tier": 0, "url": "http://127.0.0.1:8002"},
            {"tier": 1, "url": "http://127.0.0.1:8000"},
        ],
    )
    return manager.status()


@app.post("/api/start/node/{node_index}")
def start_single_node(node_index: int) -> dict[str, Any]:
    if node_index < 1 or node_index > 25:
        raise HTTPException(status_code=400, detail="node_index must be between 1 and 25")
    manager.start_node(
        name=f"node-{node_index}",
        port=8100 + node_index,
        node_index=node_index,
    )
    return manager.status()


@app.post("/api/start/client")
def start_client() -> dict[str, Any]:
    manager.start_client_server()
    return manager.status()


@app.post("/api/start/nodes")
def start_nodes_batch(payload: BatchRequest) -> dict[str, Any]:
    for node_index in range(1, payload.count + 1):
        manager.start_node(
            name=f"node-{node_index}",
            port=8100 + node_index,
            node_index=node_index,
        )
    return manager.status()


@app.post("/api/stop/{name}")
def stop_service(name: str) -> dict[str, Any]:
    manager.stop(name)
    return manager.status()


@app.post("/api/stop-kind/{kind}")
def stop_kind(kind: str) -> dict[str, Any]:
    configured_kinds = {service.kind for service in load_lab_config().services.values()}
    if kind not in {"registry", "node", "client"} | configured_kinds:
        raise HTTPException(status_code=400, detail="Unknown service kind")
    manager.stop_kind(kind)
    return manager.status()


@app.get("/api/links")
def links() -> dict[str, str]:
    return {
        "client": "http://127.0.0.1:8765/",
        "primary_registry": "http://127.0.0.1:8000",
        "backup_registry": "http://127.0.0.1:8002",
        "primary_directory": "http://127.0.0.1:8000/directory?lat=55.6517&lng=12.4126&radius=50",
        "backup_directory": "http://127.0.0.1:8002/directory?lat=55.6517&lng=12.4126&radius=50",
    }
