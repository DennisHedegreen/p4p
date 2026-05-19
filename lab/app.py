from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit

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
LAB_STATE_ROOT = LAB_ROOT / "state"
LAB_STATE_DB_PATH = LAB_STATE_ROOT / "lab-state.sqlite3"


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1, le=25, default=10)


class LabNodeInstanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(min_length=3, max_length=80)
    template_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=400)
    notes: str = Field(default="", max_length=4000)


class LabNodeInstanceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=400)
    notes: str = Field(default="", max_length=4000)
    registry_targets: list[str] = Field(default_factory=list)
    visibility_expectations: list[str] = Field(default_factory=list)
    module_ids: list[str] = Field(default_factory=list)
    menu_seed: dict[str, Any] = Field(default_factory=dict)
    node_id: str = Field(min_length=3, max_length=120)
    city: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=8)
    categories: list[str] = Field(default_factory=list)
    order_mode: str = Field(default="live", max_length=32)
    public_surface_key: str = Field(default="public_shop", max_length=120)


class LabCustomerFixtureInstanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    target_ref: str = Field(min_length=1, max_length=120)
    menu_surface: str = Field(default="list_menu", max_length=120)
    order_request: dict[str, Any] = Field(default_factory=dict)
    poll_status: LabFixturePollStatus | None = None
    expected: dict[str, Any] = Field(default_factory=dict)


class LabCustomerFixtureInstanceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    target_ref: str = Field(min_length=1, max_length=120)
    menu_surface: str = Field(default="list_menu", max_length=120)
    order_request: dict[str, Any] = Field(default_factory=dict)
    poll_status: LabFixturePollStatus | None = None
    expected: dict[str, Any] = Field(default_factory=dict)


class LabRegistryProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    upstreams: list[str] = Field(default_factory=list)
    announce_policy: str = Field(min_length=1, max_length=160)
    discover_policy: str = Field(min_length=1, max_length=160)
    notes: list[str] = Field(default_factory=list)


class LabRegistryLaneInstanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(min_length=3, max_length=80)
    template_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    notes: list[str] = Field(default_factory=list)


class LabRegistryLaneInstanceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    upstreams: list[str] = Field(default_factory=list)
    announce_policy: str = Field(min_length=1, max_length=160)
    discover_policy: str = Field(min_length=1, max_length=160)
    notes: list[str] = Field(default_factory=list)


class LabFlowScenarioInstanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    services: list[str] = Field(default_factory=list)
    node_refs: list[str] = Field(default_factory=list)
    fixture_runs: list[LabFlowFixtureRunDefinition] = Field(default_factory=list)
    checks: list[LabFlowCheckDefinition] | None = None
    notes: list[str] = Field(default_factory=list)


class LabFlowScenarioInstanceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    services: list[str] = Field(default_factory=list)
    node_refs: list[str] = Field(default_factory=list)
    fixture_runs: list[LabFlowFixtureRunDefinition] = Field(default_factory=list)
    checks: list[LabFlowCheckDefinition] | None = None
    notes: list[str] = Field(default_factory=list)


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


class LabRegistryScopeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network: str
    geography: str
    family: str


class LabRegistryProfileDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    service_name: str
    role: str
    curation_mode: str
    availability_role: str
    backup_for: str | None = None
    scope: LabRegistryScopeDefinition
    upstreams: list[str] = Field(default_factory=list)
    announce_policy: str
    discover_policy: str
    notes: list[str] = Field(default_factory=list)


class LabNodeProfileDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    service_name: str
    family: str
    tags: list[str] = Field(default_factory=list)
    operator_url: str | None = None
    registry_targets: list[str] = Field(default_factory=list)
    visibility_expectations: list[str] = Field(default_factory=list)
    customer_urls: dict[str, str] = Field(default_factory=dict)


class LabFixturePollStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    attempts: int = Field(default=4, ge=1, le=20)
    interval_ms: int = Field(default=250, ge=0, le=30_000)


class LabCustomerFixtureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    target_profile: str
    menu_surface: str = "list_menu"
    order_request: dict[str, Any]
    poll_status: LabFixturePollStatus | None = None
    expected: dict[str, Any] = Field(default_factory=dict)


class LabFlowFixtureRunDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    profile_id: str | None = None


class LabFlowCheckDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    service: str | None = None
    fixture_id: str | None = None
    profile_id: str | None = None


class LabFlowScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str = ""
    services: list[str] = Field(default_factory=list)
    node_profiles: list[str] = Field(default_factory=list)
    fixture_runs: list[LabFlowFixtureRunDefinition] = Field(default_factory=list)
    checks: list[LabFlowCheckDefinition] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LabLegacyScenarioDefinition(BaseModel):
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
    registry_profiles: dict[str, LabRegistryProfileDefinition]
    node_profiles: dict[str, LabNodeProfileDefinition]
    customer_fixtures: dict[str, LabCustomerFixtureDefinition]
    flow_scenarios: list[LabFlowScenarioDefinition]
    legacy_scenarios: list[LabLegacyScenarioDefinition]


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
    external: bool = False

    def is_running(self) -> bool:
        return self.external or (self.process is not None and self.process.poll() is None)


class ProcessManager:
    def __init__(self) -> None:
        self._services: dict[str, ManagedProcess] = {}
        self._lock = threading.Lock()

    def get_managed(self, name: str) -> ManagedProcess | None:
        with self._lock:
            return self._services.get(name)

    def find_by_port(self, port: int | None, *, exclude_name: str | None = None) -> ManagedProcess | None:
        if port is None:
            return None
        with self._lock:
            for name, service in self._services.items():
                if exclude_name and name == exclude_name:
                    continue
                if service.port == port:
                    return service
        return None

    def forget(self, name: str) -> ManagedProcess | None:
        with self._lock:
            return self._services.pop(name, None)

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
        candidate = ManagedProcess(
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
            external=True,
        )
        existing_status = self._project_service_status(candidate)
        if existing_status["usable"]:
            candidate.logs.append(f"[lab] adopted existing service on port {definition.port}")
            with self._lock:
                self._services[definition.name] = candidate
            return candidate
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

    def adopt_existing_service(self, definition: LabServiceDefinition) -> ManagedProcess:
        command = [_resolve_text(part) for part in definition.command]
        cwd = _resolve_path(definition.cwd)
        env = os.environ.copy()
        env.update({key: _resolve_text(value) for key, value in definition.env.items()})
        candidate = ManagedProcess(
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
            external=True,
        )
        existing_status = self._project_service_status(candidate)
        if not existing_status["usable"]:
            raise HTTPException(
                status_code=400,
                detail=f"No usable external service to adopt on port {definition.port}",
            )
        candidate.logs.append(f"[lab] adopted existing service on port {definition.port}")
        with self._lock:
            self._services[definition.name] = candidate
        return candidate

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
        if service is None:
            return
        if service.external and service.process is None:
            service.logs.append(f"[lab] external service still owns {name}; stop it from its original launcher.")
            return
        if service.process is None:
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

    def _project_service_status(self, service: ManagedProcess) -> dict[str, Any]:
        usable = service.is_running()
        health_status_code = None
        health = None
        if service.health_url:
            usable, health_status_code, health = self._probe_url_health(service)
        elif service.kind == "node":
            usable, health_status_code, health = self._probe_node_health(service)
        elif service.kind == "client":
            usable, health_status_code, health = self._probe_client_health(service)

        is_node_kind = service.kind in {"node", "pilot-node"}
        return {
            "name": service.name,
            "kind": service.kind,
            "description": service.description,
            "port": service.port,
            "url": f"http://127.0.0.1:{service.port}/" if service.port is not None else None,
            "operator_url": (
                f"http://127.0.0.1:{service.port}/operator" if is_node_kind and service.port is not None else None
            ),
            "links": service.links,
            "command": _command_for_display(service.command),
            "cwd": str(service.cwd),
            "running": service.is_running(),
            "usable": usable,
            "external": service.external,
            "pid": service.process.pid if service.process else None,
            "started_at": service.started_at,
            "health_status_code": health_status_code,
            "health": health,
            "logs": list(service.logs),
        }

    def get_service_status(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            service = self._services.get(name)
        if service is None:
            return None
        return self._project_service_status(service)

    def status(self) -> dict[str, Any]:
        with self._lock:
            services = list(self._services.values())
        items = [self._project_service_status(service) for service in services]
        items.sort(key=lambda item: (item["kind"], item["port"] if item["port"] is not None else 0))
        return {"services": items}


class RunStore:
    def __init__(self, *, max_runs: int = 100) -> None:
        self._runs: deque[dict[str, Any]] = deque(maxlen=max_runs)
        self._lock = threading.Lock()
        self._counter = 0

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._counter += 1
            entry = {"run_id": f"run-{self._counter:04d}", **payload}
            self._runs.appendleft(entry)
            return dict(entry)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._runs]


def _run_owner_stories(run: dict[str, Any]) -> list[str]:
    stories: list[str] = []
    owner_story = str(run.get("owner_story") or "").strip()
    if owner_story:
        stories.append(owner_story)
    for target in run.get("resolved_targets") or []:
        if isinstance(target, dict):
            target_story = str(target.get("owner_story") or "").strip()
            if target_story:
                stories.append(target_story)
    return _clean_string_list(stories)


def _run_surface_keys(run: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    surface_key = str(run.get("public_surface_key") or "").strip()
    if surface_key:
        keys.append(surface_key)
    for target in run.get("resolved_targets") or []:
        if isinstance(target, dict):
            target_key = str(target.get("public_surface_key") or "").strip()
            if target_key:
                keys.append(target_key)
    return _clean_string_list(keys)


def _run_registry_lanes(run: dict[str, Any]) -> list[str]:
    lanes: list[str] = []
    for lane in run.get("registry_targets") or []:
        lane_value = str(lane).strip()
        if lane_value:
            lanes.append(lane_value)
    for target in run.get("resolved_targets") or []:
        if not isinstance(target, dict):
            continue
        for lane in target.get("registry_targets") or []:
            lane_value = str(lane).strip()
            if lane_value:
                lanes.append(lane_value)
        for lane in target.get("visibility_expectations") or []:
            lane_value = str(lane).strip()
            if lane_value:
                lanes.append(lane_value)
    return _clean_string_list(lanes)


def _runs_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    owner_stories: list[str] = []
    surface_keys: list[str] = []
    registry_lanes: list[str] = []
    success_count = 0
    failed_count = 0
    for run in runs:
        kind = str(run.get("kind") or "run")
        kinds[kind] = kinds.get(kind, 0) + 1
        if run.get("success"):
            success_count += 1
        else:
            failed_count += 1
        owner_stories.extend(_run_owner_stories(run))
        surface_keys.extend(_run_surface_keys(run))
        registry_lanes.extend(_run_registry_lanes(run))
    return {
        "total_runs": len(runs),
        "success_count": success_count,
        "failed_count": failed_count,
        "kinds": kinds,
        "owner_stories": _clean_string_list(owner_stories),
        "surface_keys": _clean_string_list(surface_keys),
        "registry_lanes": _clean_string_list(registry_lanes),
    }


def _human_label(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    return cleaned.replace("_", " ").replace("-", " ").title()


def _run_story_text(run: dict[str, Any]) -> str:
    resolved_targets = list(run.get("resolved_targets") or [])
    run_kind = str(run.get("kind") or "")
    if run_kind == "customer_fixture":
        owner_stories = _run_owner_stories(run)
        owner_part = owner_stories[0] if owner_stories else "an unresolved local target"
        return f"This fixture tested one synthetic customer lane against {owner_part}."
    if run_kind in {"flow_scenario", "flow_scenario_instance"}:
        check_count = len(list(run.get("checks") or []))
        return (
            f"This flow tested {len(resolved_targets)} local owner"
            f"{'' if len(resolved_targets) == 1 else 's'} with {check_count} explicit check"
            f"{'' if check_count == 1 else 's'}."
        )
    return "This run recorded local test truth for the current lab session."


def _facet_projection(values: list[str], *, label_fn: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        counts[cleaned] = counts.get(cleaned, 0) + 1
    rows: list[dict[str, Any]] = []
    for key in sorted(counts):
        rows.append(
            {
                "id": key,
                "label": label_fn(key) if label_fn else key,
                "count": counts[key],
            }
        )
    return rows


def _runs_proof_lanes(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lanes: dict[str, dict[str, Any]] = {}
    for run in runs:
        owner_stories = list(run.get("owner_stories") or [])
        if not owner_stories:
            owner_stories = ["No owner story recorded"]
        for owner_story in owner_stories:
            lane = lanes.setdefault(
                owner_story,
                {
                    "owner_story": owner_story,
                    "run_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "kinds": {},
                    "surface_labels": [],
                    "registry_lanes": [],
                    "latest_run_title": "",
                },
            )
            lane["run_count"] += 1
            if run.get("success"):
                lane["success_count"] += 1
            else:
                lane["failed_count"] += 1
            kind = str(run.get("kind") or "run")
            lane["kinds"][kind] = lane["kinds"].get(kind, 0) + 1
            lane["surface_labels"].extend(list(run.get("surface_labels") or []))
            lane["registry_lanes"].extend(list(run.get("registry_lanes") or []))
            if not lane["latest_run_title"]:
                lane["latest_run_title"] = str(
                    run.get("title") or run.get("scenario_id") or run.get("fixture_id") or run.get("run_id") or ""
                ).strip()
    rows: list[dict[str, Any]] = []
    for owner_story, lane in lanes.items():
        rows.append(
            {
                "owner_story": owner_story,
                "run_count": lane["run_count"],
                "success_count": lane["success_count"],
                "failed_count": lane["failed_count"],
                "kinds": lane["kinds"],
                "surface_labels": _clean_string_list(lane["surface_labels"]),
                "registry_lanes": _clean_string_list(lane["registry_lanes"]),
                "latest_run_title": lane["latest_run_title"],
            }
        )
    rows.sort(key=lambda item: (-int(item["run_count"]), str(item["owner_story"])))
    return rows


def runs_room_projection() -> dict[str, Any]:
    base_runs = run_store.list()
    runs: list[dict[str, Any]] = []
    for run in base_runs:
        owner_stories = _run_owner_stories(run)
        surface_keys = _run_surface_keys(run)
        registry_lanes = _run_registry_lanes(run)
        runs.append(
            {
                **run,
                "owner_stories": owner_stories,
                "surface_keys": surface_keys,
                "surface_labels": [_human_label(key or "public_shop") for key in surface_keys],
                "registry_lanes": registry_lanes,
                "run_story": _run_story_text(run),
            }
        )
    summary = _runs_summary(base_runs)
    summary["surface_labels"] = [_human_label(key or "public_shop") for key in summary.get("surface_keys", [])]
    if runs:
        latest_run = runs[0]
        summary["latest_run_title"] = str(
            latest_run.get("title") or latest_run.get("scenario_id") or latest_run.get("fixture_id") or latest_run.get("run_id") or ""
        ).strip()
        summary["latest_run_story"] = latest_run.get("run_story") or ""
    else:
        summary["latest_run_title"] = ""
        summary["latest_run_story"] = ""
    filters = {
        "kinds": _facet_projection([str(run.get("kind") or "run") for run in runs], label_fn=_human_label),
        "owners": _facet_projection(
            [owner for run in runs for owner in list(run.get("owner_stories") or [])]
        ),
        "surfaces": _facet_projection(
            [surface for run in runs for surface in list(run.get("surface_keys") or [])],
            label_fn=_human_label,
        ),
        "registries": _facet_projection(
            [lane for run in runs for lane in list(run.get("registry_lanes") or [])]
        ),
        "outcomes": [
            {"id": "success", "label": "Success", "count": summary["success_count"]},
            {"id": "failed", "label": "Failed", "count": summary["failed_count"]},
        ],
    }
    return {"summary": summary, "filters": filters, "proof_lanes": _runs_proof_lanes(runs), "runs": runs}


def _iso_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    payload = json.loads(value)
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


def _json_dict(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(item) for key, item in payload.items()}


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        return {}
    return dict(payload)


def _json_array_of_objects(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    payload = json.loads(value)
    if not isinstance(payload, list):
        return []
    items: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            items.append(dict(item))
    return items


def _clean_string_list(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _count_phrase(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _flow_target_exists(config: LabConfig, target_ref: str) -> bool:
    return target_ref in config.node_profiles or state_store.get_node_instance(target_ref) is not None


def _customer_fixture_exists(config: LabConfig, fixture_id: str) -> bool:
    return fixture_id in config.customer_fixtures or state_store.get_customer_fixture_instance(fixture_id) is not None


def _normalize_customer_fixture_instance_payload(
    *,
    config: LabConfig,
    target_ref: str,
    menu_surface: str,
    order_request: dict[str, Any],
    poll_status: dict[str, Any] | None,
    expected: dict[str, Any],
) -> dict[str, Any]:
    cleaned_target_ref = str(target_ref).strip()
    if not cleaned_target_ref:
        raise HTTPException(status_code=400, detail="target_ref is required")
    if not _flow_target_exists(config, cleaned_target_ref):
        raise HTTPException(status_code=400, detail=f"Unknown fixture target ref: {cleaned_target_ref}")
    if not isinstance(order_request, dict):
        raise HTTPException(status_code=400, detail="order_request must be an object")
    raw_items = order_request.get("items", [])
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=400, detail="order_request.items must be a non-empty list")
    normalized_items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise HTTPException(status_code=400, detail="order_request.items must contain objects")
        item_id = str(raw_item.get("id", "")).strip()
        if not item_id:
            raise HTTPException(status_code=400, detail="order_request item id is required")
        try:
            quantity = int(raw_item.get("quantity", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid quantity for item {item_id}") from None
        if quantity < 1:
            raise HTTPException(status_code=400, detail=f"Quantity must be at least 1 for item {item_id}")
        normalized_items.append({"id": item_id, "quantity": quantity})
    normalized_request = {
        "customer_name": str(order_request.get("customer_name", "")).strip(),
        "customer_contact": str(order_request.get("customer_contact", "")).strip(),
        "fulfillment": str(order_request.get("fulfillment", "pickup")).strip() or "pickup",
        "items": normalized_items,
        "note": str(order_request.get("note", "")).strip(),
        "client_version": str(order_request.get("client_version", "p4p-lab-local-fixture")).strip()
        or "p4p-lab-local-fixture",
    }
    normalized_expected: dict[str, Any] = {}
    if isinstance(expected, dict):
        normalized_expected["accepted"] = bool(expected.get("accepted", True))
        final_status = str(expected.get("final_status", "")).strip()
        if final_status:
            normalized_expected["final_status"] = final_status
    normalized_poll = None
    if isinstance(poll_status, dict):
        normalized_poll = LabFixturePollStatus(**poll_status).model_dump(mode="json")
        if not normalized_poll.get("enabled", True):
            normalized_poll = None
    cleaned_menu_surface = str(menu_surface or "list_menu").strip() or "list_menu"
    return {
        "target_ref": cleaned_target_ref,
        "menu_surface": cleaned_menu_surface,
        "order_request": normalized_request,
        "poll_status": normalized_poll,
        "expected": normalized_expected,
    }


def _normalize_flow_scenario_instance_payload(
    *,
    config: LabConfig,
    services: list[str],
    node_refs: list[str],
    fixture_runs: list[dict[str, Any]],
    checks: list[dict[str, Any]] | None,
    notes: list[str],
) -> dict[str, Any]:
    cleaned_services = _clean_string_list(services)
    cleaned_node_refs = _clean_string_list(node_refs)
    for service_name in cleaned_services:
        if service_name not in config.services:
            raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    for node_ref in cleaned_node_refs:
        if not _flow_target_exists(config, node_ref):
            raise HTTPException(status_code=400, detail=f"Unknown node ref: {node_ref}")

    normalized_fixture_runs: list[dict[str, Any]] = []
    for raw_run in fixture_runs:
        if not isinstance(raw_run, dict):
            raise HTTPException(status_code=400, detail="fixture_runs must contain objects")
        fixture_id = str(raw_run.get("fixture_id", "")).strip()
        target_ref = str(raw_run.get("profile_id", "")).strip()
        if not fixture_id:
            raise HTTPException(status_code=400, detail="fixture_runs fixture_id is required")
        if not _customer_fixture_exists(config, fixture_id):
            raise HTTPException(status_code=400, detail=f"Unknown customer fixture: {fixture_id}")
        if target_ref and not _flow_target_exists(config, target_ref):
            raise HTTPException(status_code=400, detail=f"Unknown fixture target ref: {target_ref}")
        normalized_fixture_runs.append(
            {
                "fixture_id": fixture_id,
                "profile_id": target_ref or None,
            }
        )

    if checks is None:
        normalized_checks: list[dict[str, Any]] = []
        for service_name in cleaned_services:
            normalized_checks.append({"kind": "service_usable", "service": service_name})
        for node_ref in cleaned_node_refs:
            resolved = _resolve_flow_target(config, node_ref)
            normalized_checks.append({"kind": "service_usable", "service": resolved["service_name"], "profile_id": node_ref})
        for fixture_run in normalized_fixture_runs:
            normalized_checks.append(
                {
                    "kind": "fixture_succeeded",
                    "fixture_id": fixture_run["fixture_id"],
                    "profile_id": fixture_run.get("profile_id") or _get_customer_fixture(config, fixture_run["fixture_id"])["target_profile"],
                }
            )
    else:
        normalized_checks = []
        allowed_kinds = {"service_usable", "service_running", "stop_service", "service_stopped", "fixture_succeeded"}
        for raw_check in checks:
            if not isinstance(raw_check, dict):
                raise HTTPException(status_code=400, detail="checks must contain objects")
            kind = str(raw_check.get("kind", "")).strip()
            if kind not in allowed_kinds:
                raise HTTPException(status_code=400, detail=f"Unknown flow check kind: {kind or '<empty>'}")
            service_name = str(raw_check.get("service", "")).strip()
            fixture_id = str(raw_check.get("fixture_id", "")).strip()
            profile_id = str(raw_check.get("profile_id", "")).strip()
            if kind in {"service_usable", "service_running", "stop_service", "service_stopped"}:
                if not service_name:
                    raise HTTPException(status_code=400, detail=f"Flow check kind {kind} requires service")
                if service_name not in config.services and not manager.get_service_status(service_name):
                    raise HTTPException(status_code=400, detail=f"Unknown service in flow check: {service_name}")
            if kind == "fixture_succeeded":
                if not fixture_id:
                    raise HTTPException(status_code=400, detail="Flow check kind fixture_succeeded requires fixture_id")
                if not _customer_fixture_exists(config, fixture_id):
                    raise HTTPException(status_code=400, detail=f"Unknown customer fixture in flow check: {fixture_id}")
                if profile_id and not _flow_target_exists(config, profile_id):
                    raise HTTPException(status_code=400, detail=f"Unknown profile_id in flow check: {profile_id}")
            elif profile_id and not _flow_target_exists(config, profile_id):
                raise HTTPException(status_code=400, detail=f"Unknown profile_id in flow check: {profile_id}")
            normalized_checks.append(
                {
                    "kind": kind,
                    "service": service_name or None,
                    "fixture_id": fixture_id or None,
                    "profile_id": profile_id or None,
                }
            )
    return {
        "services": cleaned_services,
        "node_refs": cleaned_node_refs,
        "fixture_runs": normalized_fixture_runs,
        "checks": normalized_checks,
        "notes": _clean_string_list(notes),
    }


def _extract_module_ids_from_env(env: dict[str, str]) -> list[str]:
    raw = env.get("P4P_NODE_MODULES", "")
    return _clean_string_list(raw.split(","))


def _extract_menu_seed_from_env(env: dict[str, str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    indexes: set[str] = set()
    prefix = "P4P_MENU_ITEM_"
    for key in env:
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].split("_", 1)
        if len(parts) != 2:
            continue
        indexes.add(parts[0])
    for index in sorted(indexes, key=lambda value: int(value) if value.isdigit() else value):
        item_prefix = f"{prefix}{index}_"
        item_id = env.get(f"{item_prefix}ID", "").strip()
        if not item_id:
            continue
        price_raw = env.get(f"{item_prefix}PRICE", "").strip()
        price_minor: int | None = None
        if price_raw:
            try:
                price_minor = int(price_raw)
            except ValueError:
                price_minor = None
        items.append(
            {
                "id": item_id,
                "name": env.get(f"{item_prefix}NAME", "").strip(),
                "description": env.get(f"{item_prefix}DESCRIPTION", "").strip(),
                "category": env.get(f"{item_prefix}CATEGORY", "").strip(),
                "price_minor": price_minor,
                "image_url": env.get(f"{item_prefix}IMAGE_URL", "").strip(),
            }
        )
    menu_seed: dict[str, Any] = {"items": items}
    currency = env.get("P4P_MENU_CURRENCY", "").strip()
    if currency:
        menu_seed["currency"] = currency
    return menu_seed


def _extract_categories_from_env(env: dict[str, str]) -> list[str]:
    raw = env.get("P4P_NODE_CATEGORIES", "")
    return _clean_string_list(raw.split(","))


def _extract_node_runtime_metadata_from_env(env: dict[str, str], *, fallback_node_id: str) -> dict[str, Any]:
    return {
        "node_id": str(env.get("P4P_NODE_ID", "")).strip() or fallback_node_id,
        "city": str(env.get("P4P_NODE_CITY", "")).strip(),
        "country": str(env.get("P4P_NODE_COUNTRY", "")).strip(),
        "categories": _extract_categories_from_env(env),
        "order_mode": str(env.get("P4P_NODE_ORDER_MODE", "")).strip() or "live",
    }


def _validate_node_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="node_id is required")
    if any(char.isspace() for char in cleaned):
        raise HTTPException(status_code=400, detail="node_id must not contain spaces")
    if not all(char.isalnum() or char in {"-", "_"} for char in cleaned):
        raise HTTPException(status_code=400, detail="node_id may only contain letters, numbers, '-' or '_'")
    return cleaned


def _normalize_order_mode(value: str) -> str:
    cleaned = value.strip()
    allowed = {"disabled", "menu_only", "test", "live"}
    if cleaned not in allowed:
        raise HTTPException(status_code=400, detail=f"order_mode must be one of: {', '.join(sorted(allowed))}")
    return cleaned


def _normalize_menu_seed(payload: dict[str, Any]) -> dict[str, Any]:
    items_payload = payload.get("items", [])
    if not isinstance(items_payload, list):
        raise HTTPException(status_code=400, detail="menu_seed.items must be a list")
    items: list[dict[str, Any]] = []
    for raw_item in items_payload:
        if not isinstance(raw_item, dict):
            raise HTTPException(status_code=400, detail="menu_seed.items must contain objects")
        item_id = str(raw_item.get("id", "")).strip()
        if not item_id:
            raise HTTPException(status_code=400, detail="menu_seed item id is required")
        name = str(raw_item.get("name", "")).strip()
        description = str(raw_item.get("description", "")).strip()
        category = str(raw_item.get("category", "")).strip()
        image_url = str(raw_item.get("image_url", "")).strip()
        price_value = raw_item.get("price_minor")
        if price_value in ("", None):
            price_minor = None
        else:
            try:
                price_minor = int(price_value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"menu_seed item price_minor must be integer for {item_id}")
        items.append(
            {
                "id": item_id,
                "name": name,
                "description": description,
                "category": category,
                "price_minor": price_minor,
                "image_url": image_url,
            }
        )
    normalized: dict[str, Any] = {"items": items}
    currency = str(payload.get("currency", "")).strip()
    if currency:
        normalized["currency"] = currency
    return normalized


def _apply_menu_seed_to_env(env: dict[str, str], menu_seed: dict[str, Any]) -> dict[str, str]:
    updated = {key: value for key, value in env.items() if not key.startswith("P4P_MENU_ITEM_") and key != "P4P_MENU_CURRENCY"}
    currency = str(menu_seed.get("currency", "")).strip()
    if currency:
        updated["P4P_MENU_CURRENCY"] = currency
    for index, raw_item in enumerate(menu_seed.get("items", []), start=1):
        if not isinstance(raw_item, dict):
            continue
        prefix = f"P4P_MENU_ITEM_{index}_"
        item_id = str(raw_item.get("id", "")).strip()
        if not item_id:
            continue
        updated[f"{prefix}ID"] = item_id
        if raw_item.get("name") not in (None, ""):
            updated[f"{prefix}NAME"] = str(raw_item.get("name", "")).strip()
        if raw_item.get("description") not in (None, ""):
            updated[f"{prefix}DESCRIPTION"] = str(raw_item.get("description", "")).strip()
        if raw_item.get("category") not in (None, ""):
            updated[f"{prefix}CATEGORY"] = str(raw_item.get("category", "")).strip()
        if raw_item.get("price_minor") not in (None, ""):
            updated[f"{prefix}PRICE"] = str(int(raw_item["price_minor"]))
        if raw_item.get("image_url") not in (None, ""):
            updated[f"{prefix}IMAGE_URL"] = str(raw_item.get("image_url", "")).strip()
    return updated


def _registry_urls_for_targets(
    config: LabConfig,
    registry_targets: list[str],
    registry_lane_instances: list[dict[str, Any]] | None = None,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    lane_by_id = {
        str(item.get("id")): item
        for item in (registry_lane_instances or [])
        if item.get("id")
    }
    for registry_target in registry_targets:
        profile = config.registry_profiles.get(registry_target)
        url = ""
        if profile is not None:
            service = config.services.get(profile.service_name)
            if service is not None:
                url = _resolve_text(service.env.get("P4P_REGISTRY_URL", "")) or ""
        elif registry_target in lane_by_id:
            port = lane_by_id[registry_target].get("port")
            if port:
                url = f"http://127.0.0.1:{int(port)}"
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _remap_url_to_port(url: str | None, port: int) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    new_netloc = f"127.0.0.1:{port}"
    return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))


def _remap_customer_urls(urls: dict[str, str], port: int) -> dict[str, str]:
    return {key: _remap_url_to_port(value, port) or "" for key, value in urls.items()}


def _pick_public_shop_url(customer_urls: dict[str, str], preferred_key: str | None) -> tuple[str | None, str]:
    cleaned_preferred_key = (preferred_key or "").strip()
    if cleaned_preferred_key and customer_urls.get(cleaned_preferred_key):
        return customer_urls[cleaned_preferred_key], cleaned_preferred_key

    for candidate in ("public_shop", "list_menu", "photo_map", "menu_json"):
        if customer_urls.get(candidate):
            return customer_urls[candidate], candidate

    for key, url in customer_urls.items():
        if url:
            return url, key

    return None, cleaned_preferred_key or "public_shop"


class LabStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS node_instances (
                    instance_id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    family TEXT NOT NULL,
                    service_name TEXT,
                    port INTEGER,
                    node_id TEXT,
                    city TEXT,
                    country TEXT,
                    categories_json TEXT NOT NULL DEFAULT '[]',
                    order_mode TEXT NOT NULL DEFAULT 'live',
                    operator_token TEXT,
                    operator_url TEXT,
                    public_shop_url TEXT,
                    customer_urls_json TEXT NOT NULL,
                    registry_targets_json TEXT NOT NULL,
                    visibility_expectations_json TEXT NOT NULL,
                    module_ids_json TEXT NOT NULL DEFAULT '[]',
                    menu_seed_json TEXT NOT NULL DEFAULT '{"items":[]}',
                    public_surface_key TEXT NOT NULL DEFAULT 'public_shop',
                    tags_json TEXT NOT NULL,
                    launch_mode TEXT NOT NULL,
                    launchable_now INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS registry_profile_overrides (
                    profile_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    upstreams_json TEXT NOT NULL DEFAULT '[]',
                    announce_policy TEXT NOT NULL,
                    discover_policy TEXT NOT NULL,
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS registry_lane_instances (
                    instance_id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    service_name TEXT NOT NULL,
                    port INTEGER,
                    role TEXT NOT NULL,
                    curation_mode TEXT NOT NULL,
                    availability_role TEXT NOT NULL,
                    backup_for TEXT,
                    scope_network TEXT NOT NULL,
                    scope_geography TEXT NOT NULL,
                    scope_family TEXT NOT NULL,
                    upstreams_json TEXT NOT NULL DEFAULT '[]',
                    announce_policy TEXT NOT NULL,
                    discover_policy TEXT NOT NULL,
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    launch_mode TEXT NOT NULL,
                    launchable_now INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS flow_scenario_instances (
                    instance_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    services_json TEXT NOT NULL DEFAULT '[]',
                    node_refs_json TEXT NOT NULL DEFAULT '[]',
                    fixture_runs_json TEXT NOT NULL DEFAULT '[]',
                    checks_json TEXT NOT NULL DEFAULT '[]',
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_fixture_instances (
                    instance_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    target_ref TEXT NOT NULL,
                    menu_surface TEXT NOT NULL DEFAULT 'list_menu',
                    order_request_json TEXT NOT NULL DEFAULT '{}',
                    poll_status_json TEXT,
                    expected_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(node_instances)").fetchall()
            }
            if "port" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN port INTEGER")
            if "node_id" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN node_id TEXT")
            if "city" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN city TEXT")
            if "country" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN country TEXT")
            if "categories_json" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN categories_json TEXT NOT NULL DEFAULT '[]'")
            if "order_mode" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN order_mode TEXT NOT NULL DEFAULT 'live'")
            if "operator_token" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN operator_token TEXT")
            if "module_ids_json" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN module_ids_json TEXT NOT NULL DEFAULT '[]'")
            if "menu_seed_json" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN menu_seed_json TEXT NOT NULL DEFAULT '{\"items\":[]}'")
            if "public_surface_key" not in columns:
                connection.execute("ALTER TABLE node_instances ADD COLUMN public_surface_key TEXT NOT NULL DEFAULT 'public_shop'")
            connection.commit()

    def list_registry_profile_overrides(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        profile_id,
                        title,
                        description,
                        upstreams_json,
                        announce_policy,
                        discover_policy,
                        notes_json,
                        updated_at
                    FROM registry_profile_overrides
                    ORDER BY profile_id
                    """
                ).fetchall()
        return {
            row["profile_id"]: {
                "profile_id": row["profile_id"],
                "title": row["title"],
                "description": row["description"],
                "upstreams": _json_list(row["upstreams_json"]),
                "announce_policy": row["announce_policy"],
                "discover_policy": row["discover_policy"],
                "notes": _json_list(row["notes_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def update_registry_profile_override(
        self,
        *,
        config: LabConfig,
        profile_id: str,
        title: str,
        description: str,
        upstreams: list[str],
        announce_policy: str,
        discover_policy: str,
        notes: list[str],
    ) -> dict[str, Any]:
        if profile_id not in config.registry_profiles:
            raise HTTPException(status_code=404, detail=f"Unknown registry profile: {profile_id}")
        cleaned_title = title.strip()
        if not cleaned_title:
            raise HTTPException(status_code=400, detail="Registry profile title is required")
        cleaned_description = description.strip()
        cleaned_upstreams = _clean_string_list(upstreams)
        cleaned_notes = _clean_string_list(notes)
        cleaned_announce_policy = announce_policy.strip()
        cleaned_discover_policy = discover_policy.strip()
        if not cleaned_announce_policy:
            raise HTTPException(status_code=400, detail="announce_policy is required")
        if not cleaned_discover_policy:
            raise HTTPException(status_code=400, detail="discover_policy is required")
        for upstream_id in cleaned_upstreams:
            if upstream_id == profile_id:
                raise HTTPException(status_code=400, detail="Registry profile cannot list itself as an upstream")
            if upstream_id not in config.registry_profiles:
                raise HTTPException(status_code=400, detail=f"Unknown upstream registry lane: {upstream_id}")
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO registry_profile_overrides (
                        profile_id,
                        title,
                        description,
                        upstreams_json,
                        announce_policy,
                        discover_policy,
                        notes_json,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id) DO UPDATE SET
                        title=excluded.title,
                        description=excluded.description,
                        upstreams_json=excluded.upstreams_json,
                        announce_policy=excluded.announce_policy,
                        discover_policy=excluded.discover_policy,
                        notes_json=excluded.notes_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        profile_id,
                        cleaned_title,
                        cleaned_description,
                        json.dumps(cleaned_upstreams, ensure_ascii=True),
                        cleaned_announce_policy,
                        cleaned_discover_policy,
                        json.dumps(cleaned_notes, ensure_ascii=True),
                        timestamp,
                    ),
                )
                connection.commit()
        override = self.list_registry_profile_overrides().get(profile_id)
        if override is None:
            raise HTTPException(status_code=500, detail=f"Failed to persist registry profile override: {profile_id}")
        return override

    def list_registry_lane_instances(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        instance_id,
                        template_id,
                        title,
                        description,
                        service_name,
                        port,
                        role,
                        curation_mode,
                        availability_role,
                        backup_for,
                        scope_network,
                        scope_geography,
                        scope_family,
                        upstreams_json,
                        announce_policy,
                        discover_policy,
                        notes_json,
                        launch_mode,
                        launchable_now,
                        created_at,
                        updated_at
                    FROM registry_lane_instances
                    ORDER BY created_at, rowid
                    """
                ).fetchall()
        return [
            {
                "id": row["instance_id"],
                "template_id": row["template_id"],
                "title": row["title"],
                "description": row["description"],
                "service_name": row["service_name"],
                "port": row["port"],
                "role": row["role"],
                "curation_mode": row["curation_mode"],
                "availability_role": row["availability_role"],
                "backup_for": row["backup_for"],
                "scope": {
                    "network": row["scope_network"],
                    "geography": row["scope_geography"],
                    "family": row["scope_family"],
                },
                "upstreams": _json_list(row["upstreams_json"]),
                "announce_policy": row["announce_policy"],
                "discover_policy": row["discover_policy"],
                "notes": _json_list(row["notes_json"]),
                "launch_mode": row["launch_mode"],
                "launchable_now": bool(row["launchable_now"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "override_active": True,
                "override_updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_registry_lane_instance(self, instance_id: str) -> dict[str, Any] | None:
        for item in self.list_registry_lane_instances():
            if item["id"] == instance_id:
                return item
        return None

    def next_available_registry_port(self, *, config: LabConfig, start: int = 8010, stop: int = 8099) -> int:
        used_ports: set[int] = {
            int(service.port)
            for service in config.services.values()
            if service.port is not None
        }
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT port FROM registry_lane_instances WHERE port IS NOT NULL"
                ).fetchall()
        for row in rows:
            used_ports.add(int(row["port"]))
        for port in range(start, stop + 1):
            if port not in used_ports:
                return port
        raise HTTPException(status_code=500, detail="No available lab ports left for generated registry lanes")

    def create_registry_lane_instance(
        self,
        *,
        config: LabConfig,
        template: LabRegistryProfileDefinition,
        instance_id: str,
        title: str,
        description: str,
        notes: list[str],
    ) -> dict[str, Any]:
        cleaned_instance_id = instance_id.strip()
        if not cleaned_instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")
        if any(char.isspace() for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id must not contain spaces")
        if not all(char.isalnum() or char in {"-", "_"} for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id may only contain letters, numbers, '-' or '_'")
        if cleaned_instance_id in config.registry_profiles:
            raise HTTPException(status_code=409, detail=f"Registry lane id already exists in seed config: {cleaned_instance_id}")
        port = self.next_available_registry_port(config=config)
        service_name = f"registry-lane-{cleaned_instance_id}"
        timestamp = _iso_timestamp()
        cleaned_notes = _clean_string_list(notes)
        with self._lock:
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT 1 FROM registry_lane_instances WHERE instance_id = ?",
                    (cleaned_instance_id,),
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail=f"Registry lane instance already exists: {cleaned_instance_id}")
                connection.execute(
                    """
                    INSERT INTO registry_lane_instances (
                        instance_id,
                        template_id,
                        title,
                        description,
                        service_name,
                        port,
                        role,
                        curation_mode,
                        availability_role,
                        backup_for,
                        scope_network,
                        scope_geography,
                        scope_family,
                        upstreams_json,
                        announce_policy,
                        discover_policy,
                        notes_json,
                        launch_mode,
                        launchable_now,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cleaned_instance_id,
                        template.id,
                        title.strip(),
                        description.strip(),
                        service_name,
                        port,
                        template.role,
                        template.curation_mode,
                        template.availability_role,
                        template.backup_for,
                        template.scope.network,
                        template.scope.geography,
                        template.scope.family,
                        json.dumps(list(template.upstreams), ensure_ascii=True),
                        template.announce_policy,
                        template.discover_policy,
                        json.dumps(cleaned_notes or list(template.notes), ensure_ascii=True),
                        "generated_lane",
                        1,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.commit()
        lane = self.get_registry_lane_instance(cleaned_instance_id)
        if lane is None:
            raise HTTPException(status_code=500, detail=f"Failed to create registry lane instance: {cleaned_instance_id}")
        return lane

    def update_registry_lane_instance(
        self,
        *,
        config: LabConfig,
        instance_id: str,
        title: str,
        description: str,
        upstreams: list[str],
        announce_policy: str,
        discover_policy: str,
        notes: list[str],
    ) -> dict[str, Any]:
        lane = self.get_registry_lane_instance(instance_id)
        if lane is None:
            raise HTTPException(status_code=404, detail=f"Unknown registry lane instance: {instance_id}")
        cleaned_title = title.strip()
        if not cleaned_title:
            raise HTTPException(status_code=400, detail="Registry lane title is required")
        cleaned_upstreams = _clean_string_list(upstreams)
        valid_registry_ids = set(config.registry_profiles) | {
            item["id"] for item in self.list_registry_lane_instances()
        }
        for upstream_id in cleaned_upstreams:
            if upstream_id == instance_id:
                raise HTTPException(status_code=400, detail="Registry lane cannot list itself as an upstream")
            if upstream_id not in valid_registry_ids:
                raise HTTPException(status_code=400, detail=f"Unknown upstream registry lane: {upstream_id}")
        cleaned_announce_policy = announce_policy.strip()
        cleaned_discover_policy = discover_policy.strip()
        if not cleaned_announce_policy:
            raise HTTPException(status_code=400, detail="announce_policy is required")
        if not cleaned_discover_policy:
            raise HTTPException(status_code=400, detail="discover_policy is required")
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE registry_lane_instances
                    SET
                        title = ?,
                        description = ?,
                        upstreams_json = ?,
                        announce_policy = ?,
                        discover_policy = ?,
                        notes_json = ?,
                        updated_at = ?
                    WHERE instance_id = ?
                    """,
                    (
                        cleaned_title,
                        description.strip(),
                        json.dumps(cleaned_upstreams, ensure_ascii=True),
                        cleaned_announce_policy,
                        cleaned_discover_policy,
                        json.dumps(_clean_string_list(notes), ensure_ascii=True),
                        timestamp,
                        instance_id,
                    ),
                )
                connection.commit()
        updated = self.get_registry_lane_instance(instance_id)
        if updated is None:
            raise HTTPException(status_code=500, detail=f"Failed to update registry lane instance: {instance_id}")
        return updated

    def list_flow_scenario_instances(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        instance_id,
                        title,
                        description,
                        services_json,
                        node_refs_json,
                        fixture_runs_json,
                        checks_json,
                        notes_json,
                        created_at,
                        updated_at
                    FROM flow_scenario_instances
                    ORDER BY created_at, rowid
                    """
                ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            fixture_runs = _json_array_of_objects(row["fixture_runs_json"])
            checks = _json_array_of_objects(row["checks_json"])
            items.append(
                {
                    "id": row["instance_id"],
                    "title": row["title"],
                    "description": row["description"],
                    "services": _json_list(row["services_json"]),
                    "node_profiles": _json_list(row["node_refs_json"]),
                    "fixture_runs": fixture_runs,
                    "checks": checks,
                    "notes": _json_list(row["notes_json"]),
                    "generated": True,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return items

    def get_flow_scenario_instance(self, instance_id: str) -> dict[str, Any] | None:
        for item in self.list_flow_scenario_instances():
            if item["id"] == instance_id:
                return item
        return None

    def create_flow_scenario_instance(
        self,
        *,
        config: LabConfig,
        instance_id: str,
        title: str,
        description: str,
        services: list[str],
        node_refs: list[str],
        fixture_runs: list[dict[str, Any]],
        notes: list[str],
        checks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        cleaned_instance_id = instance_id.strip()
        if not cleaned_instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")
        if any(char.isspace() for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id must not contain spaces")
        if not all(char.isalnum() or char in {"-", "_"} for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id may only contain letters, numbers, '-' or '_'")
        if any(item.id == cleaned_instance_id for item in config.flow_scenarios):
            raise HTTPException(status_code=409, detail=f"Flow scenario id already exists in seed config: {cleaned_instance_id}")
        payload = _normalize_flow_scenario_instance_payload(
            config=config,
            services=services,
            node_refs=node_refs,
            fixture_runs=fixture_runs,
            checks=checks,
            notes=notes,
        )
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT 1 FROM flow_scenario_instances WHERE instance_id = ?",
                    (cleaned_instance_id,),
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail=f"Flow scenario instance already exists: {cleaned_instance_id}")
                connection.execute(
                    """
                    INSERT INTO flow_scenario_instances (
                        instance_id,
                        title,
                        description,
                        services_json,
                        node_refs_json,
                        fixture_runs_json,
                        checks_json,
                        notes_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cleaned_instance_id,
                        title.strip(),
                        description.strip(),
                        json.dumps(payload["services"], ensure_ascii=True),
                        json.dumps(payload["node_refs"], ensure_ascii=True),
                        json.dumps(payload["fixture_runs"], ensure_ascii=True),
                        json.dumps(payload["checks"], ensure_ascii=True),
                        json.dumps(payload["notes"], ensure_ascii=True),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.commit()
        item = self.get_flow_scenario_instance(cleaned_instance_id)
        if item is None:
            raise HTTPException(status_code=500, detail=f"Failed to create flow scenario instance: {cleaned_instance_id}")
        return item

    def update_flow_scenario_instance(
        self,
        *,
        config: LabConfig,
        instance_id: str,
        title: str,
        description: str,
        services: list[str],
        node_refs: list[str],
        fixture_runs: list[dict[str, Any]],
        notes: list[str],
        checks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_flow_scenario_instance(instance_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Unknown flow scenario instance: {instance_id}")
        payload = _normalize_flow_scenario_instance_payload(
            config=config,
            services=services,
            node_refs=node_refs,
            fixture_runs=fixture_runs,
            checks=checks,
            notes=notes,
        )
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE flow_scenario_instances
                    SET
                        title = ?,
                        description = ?,
                        services_json = ?,
                        node_refs_json = ?,
                        fixture_runs_json = ?,
                        checks_json = ?,
                        notes_json = ?,
                        updated_at = ?
                    WHERE instance_id = ?
                    """,
                    (
                        title.strip(),
                        description.strip(),
                        json.dumps(payload["services"], ensure_ascii=True),
                        json.dumps(payload["node_refs"], ensure_ascii=True),
                        json.dumps(payload["fixture_runs"], ensure_ascii=True),
                        json.dumps(payload["checks"], ensure_ascii=True),
                        json.dumps(payload["notes"], ensure_ascii=True),
                        timestamp,
                        instance_id,
                    ),
                )
                connection.commit()
        item = self.get_flow_scenario_instance(instance_id)
        if item is None:
            raise HTTPException(status_code=500, detail=f"Failed to update flow scenario instance: {instance_id}")
        return item

    def list_customer_fixture_instances(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        instance_id,
                        title,
                        description,
                        target_ref,
                        menu_surface,
                        order_request_json,
                        poll_status_json,
                        expected_json,
                        created_at,
                        updated_at
                    FROM customer_fixture_instances
                    ORDER BY created_at, rowid
                    """
                ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            poll_status = _json_object(row["poll_status_json"]) if row["poll_status_json"] else None
            items.append(
                {
                    "id": row["instance_id"],
                    "title": row["title"],
                    "description": row["description"],
                    "target_profile": row["target_ref"],
                    "target_ref": row["target_ref"],
                    "menu_surface": row["menu_surface"],
                    "order_request": _json_object(row["order_request_json"]),
                    "poll_status": poll_status,
                    "expected": _json_object(row["expected_json"]),
                    "generated": True,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return items

    def get_customer_fixture_instance(self, instance_id: str) -> dict[str, Any] | None:
        for item in self.list_customer_fixture_instances():
            if item["id"] == instance_id:
                return item
        return None

    def create_customer_fixture_instance(
        self,
        *,
        config: LabConfig,
        instance_id: str,
        title: str,
        description: str,
        target_ref: str,
        menu_surface: str,
        order_request: dict[str, Any],
        poll_status: dict[str, Any] | None,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        cleaned_instance_id = instance_id.strip()
        if not cleaned_instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")
        if any(char.isspace() for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id must not contain spaces")
        if not all(char.isalnum() or char in {"-", "_"} for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id may only contain letters, numbers, '-' or '_'")
        if cleaned_instance_id in config.customer_fixtures:
            raise HTTPException(status_code=409, detail=f"Customer fixture id already exists in seed config: {cleaned_instance_id}")
        payload = _normalize_customer_fixture_instance_payload(
            config=config,
            target_ref=target_ref,
            menu_surface=menu_surface,
            order_request=order_request,
            poll_status=poll_status,
            expected=expected,
        )
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT 1 FROM customer_fixture_instances WHERE instance_id = ?",
                    (cleaned_instance_id,),
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail=f"Customer fixture instance already exists: {cleaned_instance_id}")
                connection.execute(
                    """
                    INSERT INTO customer_fixture_instances (
                        instance_id,
                        title,
                        description,
                        target_ref,
                        menu_surface,
                        order_request_json,
                        poll_status_json,
                        expected_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cleaned_instance_id,
                        title.strip(),
                        description.strip(),
                        payload["target_ref"],
                        payload["menu_surface"],
                        json.dumps(payload["order_request"], ensure_ascii=True),
                        json.dumps(payload["poll_status"], ensure_ascii=True) if payload["poll_status"] else None,
                        json.dumps(payload["expected"], ensure_ascii=True),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.commit()
        item = self.get_customer_fixture_instance(cleaned_instance_id)
        if item is None:
            raise HTTPException(status_code=500, detail=f"Failed to create customer fixture instance: {cleaned_instance_id}")
        return item

    def update_customer_fixture_instance(
        self,
        *,
        config: LabConfig,
        instance_id: str,
        title: str,
        description: str,
        target_ref: str,
        menu_surface: str,
        order_request: dict[str, Any],
        poll_status: dict[str, Any] | None,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.get_customer_fixture_instance(instance_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Unknown customer fixture instance: {instance_id}")
        payload = _normalize_customer_fixture_instance_payload(
            config=config,
            target_ref=target_ref,
            menu_surface=menu_surface,
            order_request=order_request,
            poll_status=poll_status,
            expected=expected,
        )
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE customer_fixture_instances
                    SET
                        title = ?,
                        description = ?,
                        target_ref = ?,
                        menu_surface = ?,
                        order_request_json = ?,
                        poll_status_json = ?,
                        expected_json = ?,
                        updated_at = ?
                    WHERE instance_id = ?
                    """,
                    (
                        title.strip(),
                        description.strip(),
                        payload["target_ref"],
                        payload["menu_surface"],
                        json.dumps(payload["order_request"], ensure_ascii=True),
                        json.dumps(payload["poll_status"], ensure_ascii=True) if payload["poll_status"] else None,
                        json.dumps(payload["expected"], ensure_ascii=True),
                        timestamp,
                        instance_id,
                    ),
                )
                connection.commit()
        item = self.get_customer_fixture_instance(instance_id)
        if item is None:
            raise HTTPException(status_code=500, detail=f"Failed to update customer fixture instance: {instance_id}")
        return item

    def sync_seed_templates(self, config: LabConfig) -> None:
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                for template in config.node_profiles.values():
                    customer_urls = _resolve_profile_customer_urls(template)
                    template_service = config.services[template.service_name]
                    module_ids = _extract_module_ids_from_env(template_service.env)
                    menu_seed = _extract_menu_seed_from_env(template_service.env)
                    runtime_metadata = _extract_node_runtime_metadata_from_env(template_service.env, fallback_node_id=template.id)
                    public_shop_url, public_surface_key = _pick_public_shop_url(customer_urls, "public_shop")
                    connection.execute(
                        """
                        INSERT INTO node_instances (
                            instance_id,
                            template_id,
                            title,
                            description,
                            notes,
                            family,
                            service_name,
                            port,
                            node_id,
                            city,
                            country,
                            categories_json,
                            order_mode,
                            operator_token,
                            operator_url,
                            public_shop_url,
                            customer_urls_json,
                            registry_targets_json,
                            visibility_expectations_json,
                            module_ids_json,
                            menu_seed_json,
                            public_surface_key,
                            tags_json,
                            launch_mode,
                            launchable_now,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(instance_id) DO UPDATE SET
                            template_id=excluded.template_id,
                            title=excluded.title,
                            description=excluded.description,
                            family=excluded.family,
                            service_name=excluded.service_name,
                            port=excluded.port,
                            node_id=excluded.node_id,
                            city=excluded.city,
                            country=excluded.country,
                            categories_json=excluded.categories_json,
                            order_mode=excluded.order_mode,
                            operator_token=excluded.operator_token,
                            operator_url=excluded.operator_url,
                            public_shop_url=excluded.public_shop_url,
                            customer_urls_json=excluded.customer_urls_json,
                            registry_targets_json=excluded.registry_targets_json,
                            visibility_expectations_json=excluded.visibility_expectations_json,
                            module_ids_json=excluded.module_ids_json,
                            menu_seed_json=excluded.menu_seed_json,
                            public_surface_key=excluded.public_surface_key,
                            tags_json=excluded.tags_json,
                            launch_mode=excluded.launch_mode,
                            launchable_now=excluded.launchable_now,
                            updated_at=excluded.updated_at
                        WHERE node_instances.launch_mode = 'seeded_service'
                        """,
                        (
                            template.id,
                            template.id,
                            template.title,
                            template.description,
                            "Seeded from lab/scenarios.json.",
                            template.family,
                            template.service_name,
                            config.services[template.service_name].port,
                            runtime_metadata["node_id"],
                            runtime_metadata["city"],
                            runtime_metadata["country"],
                            json.dumps(runtime_metadata["categories"], ensure_ascii=True),
                            runtime_metadata["order_mode"],
                            "change-this",
                            _resolve_text(template.operator_url),
                            public_shop_url,
                            json.dumps(customer_urls, ensure_ascii=True, sort_keys=True),
                            json.dumps(list(template.registry_targets), ensure_ascii=True),
                            json.dumps(list(template.visibility_expectations), ensure_ascii=True),
                            json.dumps(module_ids, ensure_ascii=True),
                            json.dumps(menu_seed, ensure_ascii=True, sort_keys=True),
                            public_surface_key,
                            json.dumps(list(template.tags), ensure_ascii=True),
                            "seeded_service",
                            1,
                            timestamp,
                            timestamp,
                        ),
                    )
                connection.commit()

    def list_node_instances(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT
                        instance_id,
                        template_id,
                        title,
                        description,
                        notes,
                        family,
                        service_name,
                        port,
                        node_id,
                        city,
                        country,
                        categories_json,
                        order_mode,
                        operator_token,
                        operator_url,
                        public_shop_url,
                        customer_urls_json,
                        registry_targets_json,
                        visibility_expectations_json,
                        module_ids_json,
                        menu_seed_json,
                        public_surface_key,
                        tags_json,
                        launch_mode,
                        launchable_now,
                        created_at,
                        updated_at
                    FROM node_instances
                    ORDER BY created_at, rowid
                    """
                ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": row["instance_id"],
                    "template_id": row["template_id"],
                    "title": row["title"],
                    "description": row["description"],
                    "notes": row["notes"],
                    "family": row["family"],
                    "service_name": row["service_name"],
                    "port": row["port"],
                    "node_id": row["node_id"] or row["instance_id"],
                    "city": row["city"] or "",
                    "country": row["country"] or "",
                    "categories": _json_list(row["categories_json"]),
                    "order_mode": row["order_mode"] or "live",
                    "operator_token": row["operator_token"],
                    "operator_url": row["operator_url"],
                    "public_shop_url": row["public_shop_url"],
                    "customer_urls": _json_dict(row["customer_urls_json"]),
                    "registry_targets": _json_list(row["registry_targets_json"]),
                    "visibility_expectations": _json_list(row["visibility_expectations_json"]),
                    "module_ids": _json_list(row["module_ids_json"]),
                    "menu_seed": _json_object(row["menu_seed_json"]),
                    "public_surface_key": row["public_surface_key"] or "public_shop",
                    "tags": _json_list(row["tags_json"]),
                    "launch_mode": row["launch_mode"],
                    "launchable_now": bool(row["launchable_now"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return items

    def create_node_instance(
        self,
        *,
        config: LabConfig,
        template: LabNodeProfileDefinition,
        instance_id: str,
        title: str,
        description: str,
        notes: str,
    ) -> dict[str, Any]:
        cleaned_instance_id = instance_id.strip()
        if not cleaned_instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")
        if any(char.isspace() for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id must not contain spaces")
        if not all(char.isalnum() or char in {"-", "_"} for char in cleaned_instance_id):
            raise HTTPException(status_code=400, detail="instance_id may only contain letters, numbers, '-' or '_'")

        timestamp = _iso_timestamp()
        port = self.next_available_port()
        service_name = f"instance-{cleaned_instance_id}"
        operator_token = f"lab-{cleaned_instance_id}"
        customer_urls = _remap_customer_urls(_resolve_profile_customer_urls(template), port)
        template_service = config.services[template.service_name]
        module_ids = _extract_module_ids_from_env(template_service.env)
        menu_seed = _extract_menu_seed_from_env(template_service.env)
        runtime_metadata = _extract_node_runtime_metadata_from_env(template_service.env, fallback_node_id=cleaned_instance_id)
        runtime_metadata["node_id"] = cleaned_instance_id
        public_shop_url, public_surface_key = _pick_public_shop_url(customer_urls, "public_shop")
        operator_url = _remap_url_to_port(_resolve_text(template.operator_url), port)
        with self._lock:
            with self._connect() as connection:
                existing = connection.execute(
                    "SELECT 1 FROM node_instances WHERE instance_id = ?",
                    (cleaned_instance_id,),
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail=f"Node instance already exists: {cleaned_instance_id}")
                connection.execute(
                    """
                    INSERT INTO node_instances (
                        instance_id,
                        template_id,
                        title,
                        description,
                        notes,
                        family,
                        service_name,
                        port,
                        node_id,
                        city,
                        country,
                        categories_json,
                        order_mode,
                        operator_token,
                        operator_url,
                        public_shop_url,
                        customer_urls_json,
                        registry_targets_json,
                        visibility_expectations_json,
                        module_ids_json,
                        menu_seed_json,
                        public_surface_key,
                        tags_json,
                        launch_mode,
                        launchable_now,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cleaned_instance_id,
                        template.id,
                        title.strip(),
                        description.strip(),
                        notes.strip(),
                        template.family,
                        service_name,
                        port,
                        runtime_metadata["node_id"],
                        runtime_metadata["city"],
                        runtime_metadata["country"],
                        json.dumps(runtime_metadata["categories"], ensure_ascii=True),
                        runtime_metadata["order_mode"],
                        operator_token,
                        operator_url,
                        public_shop_url,
                        json.dumps(customer_urls, ensure_ascii=True, sort_keys=True),
                        json.dumps(list(template.registry_targets), ensure_ascii=True),
                        json.dumps(list(template.visibility_expectations), ensure_ascii=True),
                        json.dumps(module_ids, ensure_ascii=True),
                        json.dumps(menu_seed, ensure_ascii=True, sort_keys=True),
                        public_surface_key,
                        json.dumps(list(template.tags), ensure_ascii=True),
                        "generated_instance",
                        1,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.commit()
        return next(item for item in self.list_node_instances() if item["id"] == cleaned_instance_id)

    def update_node_instance(
        self,
        *,
        config: LabConfig,
        instance_id: str,
        title: str,
        description: str,
        notes: str,
        registry_targets: list[str],
        visibility_expectations: list[str],
        module_ids: list[str],
        menu_seed: dict[str, Any],
        node_id: str,
        city: str,
        country: str,
        categories: list[str],
        order_mode: str,
        public_surface_key: str,
    ) -> dict[str, Any]:
        instance = self.get_node_instance(instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail=f"Unknown node instance: {instance_id}")
        if instance.get("launch_mode") != "generated_instance":
            raise HTTPException(status_code=400, detail=f"Only generated node instances can be edited here: {instance_id}")
        cleaned_registry_targets = _clean_string_list(registry_targets)
        cleaned_visibility_expectations = _clean_string_list(visibility_expectations or registry_targets)
        valid_registry_ids = set(config.registry_profiles) | {
            item["id"] for item in self.list_registry_lane_instances()
        }
        cleaned_module_ids = _clean_string_list(module_ids)
        normalized_menu_seed = _normalize_menu_seed(menu_seed)
        cleaned_node_id = _validate_node_id(node_id)
        cleaned_city = city.strip()
        cleaned_country = country.strip().upper()
        cleaned_categories = _clean_string_list(categories)
        cleaned_order_mode = _normalize_order_mode(order_mode)
        public_shop_url, cleaned_public_surface_key = _pick_public_shop_url(
            instance.get("customer_urls") or {},
            public_surface_key,
        )
        for registry_target in cleaned_registry_targets:
            if registry_target not in valid_registry_ids:
                raise HTTPException(status_code=400, detail=f"Unknown registry target: {registry_target}")
        for visibility_expectation in cleaned_visibility_expectations:
            if visibility_expectation not in valid_registry_ids:
                raise HTTPException(status_code=400, detail=f"Unknown visibility expectation: {visibility_expectation}")
        timestamp = _iso_timestamp()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE node_instances
                    SET
                        title = ?,
                        description = ?,
                        notes = ?,
                        node_id = ?,
                        city = ?,
                        country = ?,
                        categories_json = ?,
                        order_mode = ?,
                        registry_targets_json = ?,
                        visibility_expectations_json = ?,
                        module_ids_json = ?,
                        menu_seed_json = ?,
                        public_shop_url = ?,
                        public_surface_key = ?,
                        updated_at = ?
                    WHERE instance_id = ?
                    """,
                    (
                        title.strip(),
                        description.strip(),
                        notes.strip(),
                        cleaned_node_id,
                        cleaned_city,
                        cleaned_country,
                        json.dumps(cleaned_categories, ensure_ascii=True),
                        cleaned_order_mode,
                        json.dumps(cleaned_registry_targets, ensure_ascii=True),
                        json.dumps(cleaned_visibility_expectations, ensure_ascii=True),
                        json.dumps(cleaned_module_ids, ensure_ascii=True),
                        json.dumps(normalized_menu_seed, ensure_ascii=True, sort_keys=True),
                        public_shop_url,
                        cleaned_public_surface_key,
                        timestamp,
                        instance_id,
                    ),
                )
                connection.commit()
        return next(item for item in self.list_node_instances() if item["id"] == instance_id)

    def get_node_instance(self, instance_id: str) -> dict[str, Any] | None:
        for item in self.list_node_instances():
            if item["id"] == instance_id:
                return item
        return None

    def next_available_port(self, *, start: int = 8700, stop: int = 8999) -> int:
        used_ports: set[int] = set()
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute("SELECT port FROM node_instances WHERE port IS NOT NULL").fetchall()
        for row in rows:
            used_ports.add(int(row["port"]))
        for port in range(start, stop + 1):
            if port not in used_ports:
                return port
        raise HTTPException(status_code=500, detail="No available lab ports left for generated node instances")


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
        "lab_state_root": str(LAB_STATE_ROOT),
        "lab_state_db_path": str(Path(os.environ.get("P4P_LAB_STATE_DB_PATH", str(LAB_STATE_DB_PATH)))),
        "python": sys.executable,
    }


def _resolve_text(value: str | None) -> str | None:
    if value is None:
        return None
    resolved = value
    for key, replacement in _placeholders().items():
        resolved = resolved.replace("{" + key + "}", replacement)
    return resolved


def _resolve_path(value: str) -> Path:
    return Path(_resolve_text(value) or value).expanduser()


def _resolve_link(link: dict[str, str]) -> dict[str, str]:
    return {key: (_resolve_text(value) or "") for key, value in link.items()}


def _command_for_display(command: list[str]) -> str:
    return " ".join(command)


def _resolve_service_projection(service: LabServiceDefinition) -> dict[str, Any]:
    return {
        "name": service.name,
        "kind": service.kind,
        "description": service.description,
        "port": service.port,
        "cwd": _resolve_text(service.cwd),
        "command": _command_for_display([_resolve_text(part) or part for part in service.command]),
        "links": [_resolve_link(link) for link in service.links],
    }


def _resolve_registry_profile_projection(
    profile: LabRegistryProfileDefinition,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    projection = {
        "id": profile.id,
        "title": profile.title,
        "description": profile.description,
        "service_name": profile.service_name,
        "role": profile.role,
        "curation_mode": profile.curation_mode,
        "availability_role": profile.availability_role,
        "backup_for": profile.backup_for,
        "scope": profile.scope.model_dump(mode="json"),
        "upstreams": list(profile.upstreams),
        "announce_policy": profile.announce_policy,
        "discover_policy": profile.discover_policy,
        "notes": list(profile.notes),
        "override_active": False,
        "override_updated_at": None,
    }
    if override:
        projection["title"] = override.get("title") or projection["title"]
        projection["description"] = override.get("description") if override.get("description") is not None else projection["description"]
        projection["upstreams"] = list(override.get("upstreams") or projection["upstreams"])
        projection["announce_policy"] = override.get("announce_policy") or projection["announce_policy"]
        projection["discover_policy"] = override.get("discover_policy") or projection["discover_policy"]
        projection["notes"] = list(override.get("notes") or [])
        projection["override_active"] = True
        projection["override_updated_at"] = override.get("updated_at")
    return projection


def _resolve_registry_lane_instance_projection(lane: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": lane["id"],
        "template_id": lane["template_id"],
        "title": lane["title"],
        "description": lane["description"],
        "service_name": lane["service_name"],
        "role": lane["role"],
        "curation_mode": lane["curation_mode"],
        "availability_role": lane["availability_role"],
        "backup_for": lane.get("backup_for"),
        "scope": dict(lane.get("scope") or {}),
        "upstreams": list(lane.get("upstreams") or []),
        "announce_policy": lane["announce_policy"],
        "discover_policy": lane["discover_policy"],
        "notes": list(lane.get("notes") or []),
        "port": lane.get("port"),
        "launch_mode": lane.get("launch_mode") or "generated_lane",
        "launchable_now": bool(lane.get("launchable_now")),
        "override_active": True,
        "override_updated_at": lane.get("updated_at"),
        "generated": True,
    }


def _resolve_profile_customer_urls(profile: LabNodeProfileDefinition) -> dict[str, str]:
    return {key: _resolve_text(value) or "" for key, value in profile.customer_urls.items()}


def _resolve_node_profile_projection(profile: LabNodeProfileDefinition) -> dict[str, Any]:
    customer_urls = _resolve_profile_customer_urls(profile)
    public_shop_url, public_surface_key = _pick_public_shop_url(customer_urls, "public_shop")
    return {
        "id": profile.id,
        "title": profile.title,
        "description": profile.description,
        "service_name": profile.service_name,
        "family": profile.family,
        "tags": list(profile.tags),
        "operator_url": _resolve_text(profile.operator_url),
        "registry_targets": list(profile.registry_targets),
        "visibility_expectations": list(profile.visibility_expectations),
        "public_shop_url": public_shop_url,
        "public_surface_key": public_surface_key,
        "customer_urls": customer_urls,
    }


def _resolve_customer_fixture_projection(fixture: LabCustomerFixtureDefinition) -> dict[str, Any]:
    return {
        "id": fixture.id,
        "title": fixture.title,
        "description": fixture.description,
        "target_profile": fixture.target_profile,
        "target_ref": fixture.target_profile,
        "menu_surface": fixture.menu_surface,
        "order_request": fixture.order_request,
        "poll_status": fixture.poll_status.model_dump(mode="json") if fixture.poll_status else None,
        "expected": fixture.expected,
        "generated": False,
    }


def _resolve_flow_scenario_projection(scenario: LabFlowScenarioDefinition) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "title": scenario.title,
        "description": scenario.description,
        "services": list(scenario.services),
        "node_profiles": list(scenario.node_profiles),
        "fixture_runs": [item.model_dump(mode="json") for item in scenario.fixture_runs],
        "checks": [item.model_dump(mode="json") for item in scenario.checks],
        "links": [_resolve_link(link) for link in scenario.links],
        "notes": list(scenario.notes),
    }


def _resolve_legacy_scenario_projection(scenario: LabLegacyScenarioDefinition) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "title": scenario.title,
        "description": scenario.description,
        "services": list(scenario.services),
        "links": [_resolve_link(link) for link in scenario.links],
        "notes": list(scenario.notes),
    }


def _lab_state_db_path() -> Path:
    return Path(os.environ.get("P4P_LAB_STATE_DB_PATH", str(LAB_STATE_DB_PATH)))


def validate_lab_config_references(config: LabConfig) -> None:
    for registry_profile_id, registry_profile in config.registry_profiles.items():
        if registry_profile.service_name not in config.services:
            raise ValueError(
                f"registry profile references unknown service: {registry_profile_id} -> {registry_profile.service_name}"
            )
        service = config.services[registry_profile.service_name]
        if service.kind != "registry":
            raise ValueError(
                f"registry profile must point at registry service: {registry_profile_id} -> {registry_profile.service_name}"
            )
        if registry_profile.backup_for and registry_profile.backup_for not in config.registry_profiles:
            raise ValueError(
                f"registry profile references unknown backup target: {registry_profile_id} -> {registry_profile.backup_for}"
            )
        for upstream_id in registry_profile.upstreams:
            if upstream_id not in config.registry_profiles:
                raise ValueError(
                    f"registry profile references unknown upstream: {registry_profile_id} -> {upstream_id}"
                )

    for profile_id, profile in config.node_profiles.items():
        if profile.service_name not in config.services:
            raise ValueError(f"node profile references unknown service: {profile_id} -> {profile.service_name}")
        for registry_target in profile.registry_targets:
            if registry_target not in config.registry_profiles:
                raise ValueError(f"node profile references unknown registry target: {profile_id} -> {registry_target}")
        for visibility_expectation in profile.visibility_expectations:
            if visibility_expectation not in config.registry_profiles:
                raise ValueError(
                    f"node profile references unknown visibility expectation: {profile_id} -> {visibility_expectation}"
                )

    for fixture_id, fixture in config.customer_fixtures.items():
        if fixture.target_profile not in config.node_profiles:
            raise ValueError(f"customer fixture references unknown node profile: {fixture_id} -> {fixture.target_profile}")

    for scenario in config.flow_scenarios:
        for service_name in scenario.services:
            if service_name not in config.services:
                raise ValueError(f"flow scenario references unknown service: {scenario.id} -> {service_name}")
        for profile_id in scenario.node_profiles:
            if profile_id not in config.node_profiles:
                raise ValueError(f"flow scenario references unknown node profile: {scenario.id} -> {profile_id}")
        for fixture_run in scenario.fixture_runs:
            if fixture_run.fixture_id not in config.customer_fixtures:
                raise ValueError(f"flow scenario references unknown customer fixture: {scenario.id} -> {fixture_run.fixture_id}")
            if fixture_run.profile_id and fixture_run.profile_id not in config.node_profiles:
                raise ValueError(f"flow scenario references unknown fixture profile: {scenario.id} -> {fixture_run.profile_id}")
        for check in scenario.checks:
            if check.service and check.service not in config.services:
                raise ValueError(f"flow scenario check references unknown service: {scenario.id} -> {check.service}")
            if check.profile_id and check.profile_id not in config.node_profiles:
                raise ValueError(f"flow scenario check references unknown node profile: {scenario.id} -> {check.profile_id}")
            if check.fixture_id and check.fixture_id not in config.customer_fixtures:
                raise ValueError(f"flow scenario check references unknown customer fixture: {scenario.id} -> {check.fixture_id}")

    for scenario in config.legacy_scenarios:
        for service_name in scenario.services:
            if service_name not in config.services:
                raise ValueError(f"legacy scenario references unknown service: {scenario.id} -> {service_name}")


def load_lab_config() -> LabConfig:
    payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    config = LabConfig.model_validate(payload)
    validate_lab_config_references(config)
    if "state_store" in globals():
        state_store.sync_seed_templates(config)
    return config


def scenario_projection(config: LabConfig) -> dict[str, Any]:
    registry_overrides = state_store.list_registry_profile_overrides()
    registry_lane_instances = [
        _resolve_registry_lane_instance_projection(item)
        for item in state_store.list_registry_lane_instances()
    ]
    flow_scenario_instances = state_store.list_flow_scenario_instances()
    customer_fixture_instances = state_store.list_customer_fixture_instances()
    node_templates = [_resolve_node_profile_projection(profile) for profile in config.node_profiles.values()]
    node_instances = state_store.list_node_instances()
    return {
        "version": config.version,
        "services": {name: _resolve_service_projection(service) for name, service in config.services.items()},
        "registry_profiles": [
            _resolve_registry_profile_projection(profile, registry_overrides.get(profile.id))
            for profile in config.registry_profiles.values()
        ],
        "registry_lane_instances": registry_lane_instances,
        "node_profiles": node_templates,
        "node_templates": node_templates,
        "node_instances": node_instances,
        "customer_fixtures": [
            _resolve_customer_fixture_projection(fixture) for fixture in config.customer_fixtures.values()
        ],
        "customer_fixture_instances": customer_fixture_instances,
        "flow_scenarios": [_resolve_flow_scenario_projection(scenario) for scenario in config.flow_scenarios],
        "flow_scenario_instances": flow_scenario_instances,
        "legacy_scenarios": [_resolve_legacy_scenario_projection(scenario) for scenario in config.legacy_scenarios],
    }


def server_inventory_projection(config: LabConfig) -> dict[str, Any]:
    runtime_status = {item["name"]: item for item in manager.status()["services"]}
    registry_overrides = state_store.list_registry_profile_overrides()
    registry_lane_instances = state_store.list_registry_lane_instances()
    node_templates = [_resolve_node_profile_projection(profile) for profile in config.node_profiles.values()]
    node_instances = state_store.list_node_instances()
    items: list[dict[str, Any]] = []
    configured_service_names = set(config.services)
    registry_profile_service_names = {
        profile.id: profile.service_name for profile in config.registry_profiles.values()
    }
    registry_lane_service_names = {
        lane["id"]: str(lane["service_name"])
        for lane in registry_lane_instances
        if lane.get("service_name")
    }

    def _registry_target_service_names(registry_targets: list[str]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for registry_target in registry_targets:
            service_name = registry_profile_service_names.get(registry_target) or registry_lane_service_names.get(registry_target)
            if not service_name or service_name in seen:
                continue
            seen.add(service_name)
            names.append(service_name)
        return names

    for service_name, service_definition in config.services.items():
        service_projection = _resolve_service_projection(service_definition)
        status = runtime_status.get(service_name)
        attached_registry_profiles = [
            _resolve_registry_profile_projection(profile, registry_overrides.get(profile.id))
            for profile in config.registry_profiles.values()
            if profile.service_name == service_name
        ]
        attached_node_templates = [
            template for template in node_templates if template["service_name"] == service_name
        ]
        attached_node_instances = [
            instance for instance in node_instances if instance.get("service_name") == service_name
        ]
        layer_links: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for link in service_projection["links"]:
            pair = (link["label"], link["url"])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                layer_links.append(link)
        for template in attached_node_templates:
            if template.get("operator_url"):
                pair = (f"{template['id']} operator", template["operator_url"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    layer_links.append(
                        {
                            "label": f"{template['id']} operator",
                            "url": template["operator_url"],
                            "description": "Operator surface attached to this service.",
                        }
                    )
            if template.get("public_shop_url"):
                pair = (f"{template['id']} public shop", template["public_shop_url"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    layer_links.append(
                        {
                            "label": f"{template['id']} public shop",
                            "url": template["public_shop_url"],
                            "description": "Public customer surface attached to this service.",
                        }
                    )
        dependency_service_names: list[str] = []
        seen_dependency_services: set[str] = set()
        for template in attached_node_templates:
            for dependency in _registry_target_service_names(template.get("registry_targets", [])):
                if dependency == service_name or dependency in seen_dependency_services:
                    continue
                seen_dependency_services.add(dependency)
                dependency_service_names.append(dependency)
        for instance in attached_node_instances:
            for dependency in _registry_target_service_names(instance.get("registry_targets", [])):
                if dependency == service_name or dependency in seen_dependency_services:
                    continue
                seen_dependency_services.add(dependency)
                dependency_service_names.append(dependency)
        items.append(
            {
                **service_projection,
                "status": status,
                "running": bool(status and status.get("running")),
                "usable": bool(status and status.get("usable")),
                "action_target": {"type": "service", "id": service_name},
                "dependency_service_names": dependency_service_names,
                "attached_registry_profiles": attached_registry_profiles,
                "attached_node_templates": attached_node_templates,
                "attached_node_instances": attached_node_instances,
                "layer_links": layer_links,
                "binding": _server_binding_projection(
                    service_name=service_name,
                    service_kind=service_projection["kind"],
                    action_target={"type": "service", "id": service_name},
                    attached_registry_profiles=attached_registry_profiles,
                    attached_node_templates=attached_node_templates,
                    attached_node_instances=attached_node_instances,
                ),
            }
        )

    for instance in node_instances:
        service_name = instance.get("service_name")
        if not service_name or service_name in configured_service_names:
            continue
        status = runtime_status.get(service_name)
        links: list[dict[str, str]] = []
        if instance.get("operator_url"):
            links.append(
                {
                    "label": f"{instance['id']} operator",
                    "url": instance["operator_url"],
                    "description": "Generated operator surface for this node instance.",
                }
            )
        if instance.get("public_shop_url"):
            links.append(
                {
                    "label": f"{instance['id']} public shop",
                    "url": instance["public_shop_url"],
                    "description": "Generated public customer surface for this node instance.",
                }
            )
        items.append(
            {
                "name": service_name,
                "kind": "pilot-node",
                "description": f"Generated runtime service for node instance {instance['id']}.",
                "port": instance.get("port"),
                "cwd": str(PILOT_NODE_ROOT),
                "command": "[generated from template service]",
                "links": links,
                "status": status,
                "running": bool(status and status.get("running")),
                "usable": bool(status and status.get("usable")),
                "action_target": {"type": "node-instance", "id": instance["id"]},
                "dependency_service_names": _registry_target_service_names(instance.get("registry_targets", [])),
                "attached_registry_profiles": [],
                "attached_node_templates": [],
                "attached_node_instances": [instance],
                "layer_links": links,
                "binding": _server_binding_projection(
                    service_name=service_name,
                    service_kind="pilot-node",
                    action_target={"type": "node-instance", "id": instance["id"]},
                    attached_registry_profiles=[],
                    attached_node_templates=[],
                    attached_node_instances=[instance],
                ),
            }
        )

    for lane in registry_lane_instances:
        service_name = lane.get("service_name")
        if not service_name or service_name in configured_service_names:
            continue
        status = runtime_status.get(service_name)
        definition = _build_registry_lane_instance_service_definition(config, lane)
        service_projection = _resolve_service_projection(definition)
        lane_projection = _resolve_registry_lane_instance_projection(lane)
        dependency_service_names = _registry_target_service_names(lane.get("upstreams", []))
        items.append(
            {
                **service_projection,
                "status": status,
                "running": bool(status and status.get("running")),
                "usable": bool(status and status.get("usable")),
                "action_target": {"type": "registry-lane-instance", "id": lane["id"]},
                "dependency_service_names": dependency_service_names,
                "attached_registry_profiles": [lane_projection],
                "attached_node_templates": [],
                "attached_node_instances": [],
                "layer_links": service_projection["links"],
                "binding": _server_binding_projection(
                    service_name=service_name,
                    service_kind=service_projection["kind"],
                    action_target={"type": "registry-lane-instance", "id": lane["id"]},
                    attached_registry_profiles=[lane_projection],
                    attached_node_templates=[],
                    attached_node_instances=[],
                ),
            }
        )

    items.sort(key=lambda item: (item["kind"], item["port"] if item["port"] is not None else 0, item["name"]))
    return {"servers": items, "groups": _server_group_projection(items)}


def nodes_room_projection(config: LabConfig) -> dict[str, Any]:
    runtime_status = {item["name"]: item for item in manager.status()["services"]}
    node_templates = [_resolve_node_profile_projection(profile) for profile in config.node_profiles.values()]
    node_instances = state_store.list_node_instances()

    def _status_projection(service_name: str | None) -> dict[str, Any] | None:
        if not service_name:
            return None
        status = runtime_status.get(service_name)
        if not status:
            return None
        return {
            "name": status["name"],
            "running": bool(status.get("running")),
            "usable": bool(status.get("usable")),
            "external": bool(status.get("external")),
            "port": status.get("port"),
        }

    def _open_first_story(operator_url: str | None, public_shop_url: str | None) -> str:
        if operator_url and public_shop_url:
            return "Open operator first, then the primary public lane."
        if operator_url:
            return "Open the operator lane first."
        if public_shop_url:
            return "Open the primary public lane first."
        return "No live lane is attached yet."

    def _registry_story(registry_targets: list[str], visibility_expectations: list[str]) -> str:
        announce = _clean_string_list(registry_targets)
        visible = _clean_string_list(visibility_expectations)
        announce_story = ", ".join(announce) if announce else "no announce lanes yet"
        visible_story = ", ".join(visible) if visible else "no visibility lanes yet"
        return f"Announces {announce_story}; visible through {visible_story}."

    def _surface_story(customer_urls: dict[str, str], public_surface_key: str) -> str:
        keys = [key for key, url in customer_urls.items() if url]
        if not keys:
            return "No customer/public surfaces projected yet."
        primary_label = public_surface_key if public_surface_key in customer_urls else keys[0]
        return (
            f"Primary public lane is `{primary_label}` across "
            f"{_count_phrase(len(keys), 'surface')}."
        )

    def _surface_cards(
        *,
        owner_kind: str,
        owner_id: str,
        owner_title: str,
        owner_story: str,
        customer_urls: dict[str, str],
        public_surface_key: str,
        order_mode: str | None,
        registry_targets: list[str],
        visibility_expectations: list[str],
        running: bool,
        usable: bool,
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for key, url in customer_urls.items():
            if not url:
                continue
            cards.append(
                {
                    "id": f"{owner_kind}:{owner_id}:{key}",
                    "owner_kind": owner_kind,
                    "owner_id": owner_id,
                    "owner_title": owner_title,
                    "owner_story": owner_story,
                    "surface_key": key,
                    "surface_url": url,
                    "primary": key == public_surface_key,
                    "order_mode": order_mode or "",
                    "registry_targets": list(registry_targets),
                    "visibility_expectations": list(visibility_expectations),
                    "running": running,
                    "usable": usable,
                }
            )
        return cards

    template_cards: list[dict[str, Any]] = []
    surface_cards: list[dict[str, Any]] = []
    for template in node_templates:
        service = config.services[template["service_name"]]
        status = _status_projection(template["service_name"])
        running = bool(status and status.get("running"))
        usable = bool(status and status.get("usable"))
        owner_story = f"Seeded node template {template['title']}"
        customer_urls = dict(template.get("customer_urls") or {})
        template_cards.append(
            {
                **template,
                "seed_kind": "template",
                "port": service.port,
                "status": status,
                "running": running,
                "usable": usable,
                "owner_story": owner_story,
                "open_first_story": _open_first_story(template.get("operator_url"), template.get("public_shop_url")),
                "runtime_story": (
                    f"Seeded runtime `{template['service_name']}`"
                    f"{f' on port {service.port}' if service.port is not None else ''}."
                ),
                "registry_story": _registry_story(
                    list(template.get("registry_targets") or []),
                    list(template.get("visibility_expectations") or []),
                ),
                "surface_story": _surface_story(customer_urls, str(template.get("public_surface_key") or "public_shop")),
                "customer_surface_count": len([url for url in customer_urls.values() if url]),
            }
        )
        surface_cards.extend(
            _surface_cards(
                owner_kind="template",
                owner_id=template["id"],
                owner_title=template["title"],
                owner_story=owner_story,
                customer_urls=customer_urls,
                public_surface_key=str(template.get("public_surface_key") or "public_shop"),
                order_mode=None,
                registry_targets=list(template.get("registry_targets") or []),
                visibility_expectations=list(template.get("visibility_expectations") or []),
                running=running,
                usable=usable,
            )
        )

    instance_cards: list[dict[str, Any]] = []
    for instance in node_instances:
        status = _status_projection(str(instance.get("service_name") or ""))
        running = bool(status and status.get("running"))
        usable = bool(status and status.get("usable"))
        instance_port = instance.get("port")
        port_suffix = f" on port {instance_port}" if instance_port is not None else ""
        owner_story = (
            f"Generated node instance {instance['title']}"
            if instance.get("launch_mode") == "generated_instance"
            else f"Seeded node instance {instance['title']}"
        )
        customer_urls = dict(instance.get("customer_urls") or {})
        menu_items = instance.get("menu_seed", {}).get("items", [])
        instance_cards.append(
            {
                **instance,
                "status": status,
                "running": running,
                "usable": usable,
                "owner_story": owner_story,
                "open_first_story": _open_first_story(instance.get("operator_url"), instance.get("public_shop_url")),
                "runtime_story": (
                    f"{'Generated' if instance.get('launch_mode') == 'generated_instance' else 'Seeded'} runtime "
                    f"`{instance.get('service_name') or instance['id']}`"
                    f"{port_suffix}."
                ),
                "registry_story": _registry_story(
                    list(instance.get("registry_targets") or []),
                    list(instance.get("visibility_expectations") or []),
                ),
                "surface_story": _surface_story(customer_urls, str(instance.get("public_surface_key") or "public_shop")),
                "customer_surface_count": len([url for url in customer_urls.values() if url]),
                "module_count": len(list(instance.get("module_ids") or [])),
                "menu_item_count": len(menu_items) if isinstance(menu_items, list) else 0,
            }
        )
        surface_cards.extend(
            _surface_cards(
                owner_kind="instance",
                owner_id=instance["id"],
                owner_title=instance["title"],
                owner_story=owner_story,
                customer_urls=customer_urls,
                public_surface_key=str(instance.get("public_surface_key") or "public_shop"),
                order_mode=str(instance.get("order_mode") or ""),
                registry_targets=list(instance.get("registry_targets") or []),
                visibility_expectations=list(instance.get("visibility_expectations") or []),
                running=running,
                usable=usable,
            )
        )

    surface_cards.sort(key=lambda item: (item["owner_kind"], item["owner_title"], item["surface_key"]))
    filters = {
        "families": _clean_string_list(
            [str(item.get("family") or "").strip() for item in [*template_cards, *instance_cards]]
        ),
        "order_modes": _clean_string_list(
            [str(item.get("order_mode") or "").strip() for item in instance_cards]
        ),
        "registry_lanes": _clean_string_list(
            [
                lane
                for item in [*template_cards, *instance_cards]
                for lane in [
                    *list(item.get("registry_targets") or []),
                    *list(item.get("visibility_expectations") or []),
                ]
            ]
        ),
        "owner_kinds": _clean_string_list([str(item.get("owner_kind") or "").strip() for item in surface_cards]),
        "surface_keys": _clean_string_list([str(item.get("surface_key") or "").strip() for item in surface_cards]),
    }
    summary = {
        "template_count": len(template_cards),
        "instance_count": len(instance_cards),
        "seeded_instance_count": sum(1 for item in instance_cards if item.get("launch_mode") == "seeded_service"),
        "generated_instance_count": sum(1 for item in instance_cards if item.get("launch_mode") == "generated_instance"),
        "running_instance_count": sum(1 for item in instance_cards if item.get("running")),
        "ready_instance_count": sum(1 for item in instance_cards if item.get("usable")),
        "surface_count": len(surface_cards),
        "primary_surface_count": sum(1 for item in surface_cards if item.get("primary")),
        "owner_count": len({item["owner_id"] for item in surface_cards}),
    }
    return {
        "summary": summary,
        "filters": filters,
        "node_templates": template_cards,
        "node_instances": instance_cards,
        "customer_surfaces": surface_cards,
    }


def control_rooms_projection(config: LabConfig) -> dict[str, Any]:
    inventory = server_inventory_projection(config)
    groups = inventory["groups"]

    def _room_kind(group_id: str) -> str:
        if group_id == "registry-stack":
            return "registry-room"
        if group_id == "node-runtimes":
            return "runtime-room"
        if group_id == "live-layers":
            return "reading-room"
        return "control-room"

    def _room_story(group: dict[str, Any]) -> str:
        group_id = str(group.get("id") or "")
        if group_id == "registry-stack":
            return "Bring this room up first when you need the local discovery backbone alive before anything else."
        if group_id == "node-runtimes":
            return "Use this room when you want the real operator and public shop lanes alive together instead of starting one runtime at a time."
        if group_id == "live-layers":
            return "Use this room after something is already alive and you mostly need the doors into the right local surfaces."
        return "Local grouped control room for the current P4P test stack."

    def _start_story(group: dict[str, Any]) -> str:
        if not group.get("actions"):
            return "This room does not start anything directly. It helps you open the live layers once something is already running."
        start_order = _clean_string_list(group.get("plan", {}).get("start_order", []))
        if group.get("plan", {}).get("dependencies_first") and start_order:
            return f"Dependencies first, then bring up this room in order: {', '.join(start_order)}."
        if start_order:
            return f"Bring this room up in order: {', '.join(start_order)}."
        return "This room can start its attached local lanes directly."

    def _recover_story(group: dict[str, Any]) -> str:
        rebind_owner_stories = _clean_string_list(group.get("plan", {}).get("rebind_owner_stories", []))
        if rebind_owner_stories:
            return (
                "Recover rebinds these local owners if the live port drifted before restarting what still belongs in this room: "
                f"{', '.join(rebind_owner_stories)}."
            )
        if group.get("actions"):
            return "Recover uses the same room plan but without assuming the current bindings are still clean."
        return "This room is read-only. Recovery belongs to the runtime rooms that own the processes."

    def _open_first_story(group: dict[str, Any]) -> str:
        first_link = next(iter(group.get("links") or []), None)
        if not first_link:
            return "No first-open lane is projected for this room yet."
        label = str(first_link.get("label") or first_link.get("url") or "").strip()
        description = str(first_link.get("description") or "").strip()
        if description:
            return f"Open {label} first. {description}"
        return f"Open {label} first from this room."

    rooms: list[dict[str, Any]] = []
    for group in groups:
        room = {
            **group,
            "kind": _room_kind(str(group.get("id") or "")),
            "actionable": bool(group.get("actions")),
            "room_story": _room_story(group),
            "start_story": _start_story(group),
            "recover_story": _recover_story(group),
            "open_first_story": _open_first_story(group),
            "first_link": next(iter(group.get("links") or []), None),
        }
        rooms.append(room)

    summary = {
        "room_count": len(rooms),
        "actionable_room_count": sum(1 for room in rooms if room["actionable"]),
        "running_room_count": sum(1 for room in rooms if int(room.get("running_count") or 0) > 0),
        "ready_room_count": sum(1 for room in rooms if int(room.get("ready_count") or 0) > 0),
        "dependency_room_count": sum(
            1 for room in rooms if bool((room.get("plan") or {}).get("dependencies_first"))
        ),
        "first_open_labels": _clean_string_list(
            [
                str(room.get("first_link", {}).get("label") or "").strip()
                for room in rooms
                if room.get("first_link")
            ]
        ),
    }
    return {"summary": summary, "rooms": rooms}


def _server_group_projection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _primary_link(item: dict[str, Any]) -> dict[str, str] | None:
        links = item.get("layer_links") or []
        return links[0] if links else None

    def _member_projection(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": item["name"],
            "kind": item["kind"],
            "port": item.get("port"),
            "running": bool(item.get("running")),
            "usable": bool(item.get("usable")),
            "action_target": item.get("action_target"),
            "dependency_service_names": list(item.get("dependency_service_names", [])),
            "binding": dict(item.get("binding") or {}),
            "primary_link": _primary_link(item),
        }

    def _group(
        *,
        group_id: str,
        title: str,
        description: str,
        members: list[dict[str, Any]],
        action_label_prefix: str | None = None,
        links: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        projected_members = [_member_projection(item) for item in members]
        dependency_service_names = _clean_string_list(
            [
                dependency
                for member in projected_members
                for dependency in member.get("dependency_service_names", [])
            ]
        )
        truth_owner_stories = _clean_string_list(
            [
                str(member.get("binding", {}).get("owner_story") or "").strip()
                for member in projected_members
                if str(member.get("binding", {}).get("owner_story") or "").strip()
            ]
        )
        rebind_owner_ids = _clean_string_list(
            [
                str(member.get("binding", {}).get("owner_id") or "").strip()
                for member in projected_members
                if bool(member.get("binding", {}).get("can_rebind"))
                and str(member.get("binding", {}).get("owner_id") or "").strip()
            ]
        )
        rebind_owner_stories = _clean_string_list(
            [
                str(member.get("binding", {}).get("owner_story") or "").strip()
                for member in projected_members
                if bool(member.get("binding", {}).get("can_rebind"))
                and str(member.get("binding", {}).get("owner_story") or "").strip()
            ]
        )
        payload: dict[str, Any] = {
            "id": group_id,
            "title": title,
            "description": description,
            "running_count": sum(1 for member in projected_members if member["running"]),
            "ready_count": sum(1 for member in projected_members if member["usable"]),
            "service_names": [member["name"] for member in projected_members],
            "dependency_service_names": dependency_service_names,
            "truth_owner_stories": truth_owner_stories,
            "rebind_owner_ids": rebind_owner_ids,
            "rebind_owner_stories": rebind_owner_stories,
            "members": projected_members,
            "links": links or [],
            "actions": [],
        }
        if action_label_prefix and projected_members:
            payload["actions"] = [
                {
                    "id": "start",
                    "label": f"Start {action_label_prefix}",
                    "tone": "primary",
                },
                {
                    "id": "stop",
                    "label": f"Stop {action_label_prefix}",
                    "tone": "danger",
                },
                {
                    "id": "restart",
                    "label": f"Restart {action_label_prefix}",
                    "tone": "secondary",
                },
                {
                    "id": "recover",
                    "label": f"Recover {action_label_prefix}",
                    "tone": "secondary",
                },
            ]
        ordered_start = _clean_string_list(dependency_service_names + [member["name"] for member in projected_members])
        ordered_stop = list(reversed([member["name"] for member in projected_members]))
        payload["plan"] = {
            "start_order": ordered_start,
            "stop_order": ordered_stop,
            "dependencies_first": bool(dependency_service_names),
            "rebind_owner_ids": rebind_owner_ids,
            "rebind_owner_stories": rebind_owner_stories,
        }
        return payload

    registry_members = [item for item in items if item.get("kind") == "registry"]
    node_members = [item for item in items if item.get("kind") in {"pilot-node", "demo-node"}]
    live_links: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in items:
        primary = _primary_link(item)
        if primary is None:
            continue
        pair = (primary["label"], primary["url"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        live_links.append(primary)

    groups: list[dict[str, Any]] = []
    if registry_members:
        groups.append(
            _group(
                group_id="registry-stack",
                title="Registry stack",
                description="Bring the open, backup, and curated registry lanes up or down together.",
                members=registry_members,
                action_label_prefix="registry stack",
                links=[item for item in live_links if "/directory" in item["url"] or ":80" in item["url"]],
            )
        )
    if node_members:
        groups.append(
            _group(
                group_id="node-runtimes",
                title="Node runtimes",
                description="Bring the operator and customer-facing node stack up or down together.",
                members=node_members,
                action_label_prefix="node runtimes",
                links=[item for item in live_links if "/operator" in item["url"] or "/p4p/" in item["url"]],
            )
        )
    groups.append(
        _group(
            group_id="live-layers",
            title="Open the live layers",
            description="Jump directly into the surfaces that matter first without reading the raw process rows.",
            members=[item for item in items if _primary_link(item) is not None],
            links=live_links[:6],
        )
    )
    return groups


def _start_server_action_target(config: LabConfig, target: dict[str, Any] | None) -> None:
    if not target:
        raise HTTPException(status_code=400, detail="Missing server action target")
    target_type = str(target.get("type") or "")
    target_id = str(target.get("id") or "")
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing server action target id")
    if target_type == "service":
        definition = _get_service_definition(config, target_id)
        manager.start_configured_service(definition)
        return
    if target_type == "node-instance":
        instance = _get_node_instance(target_id)
        if not instance.get("launchable_now"):
            raise HTTPException(status_code=400, detail=f"Node instance is not launchable yet: {target_id}")
        if instance.get("launch_mode") == "seeded_service" and instance.get("service_name") in config.services:
            definition = _get_service_definition(config, str(instance["service_name"]))
        else:
            definition = _build_node_instance_service_definition(config, instance)
        manager.start_configured_service(definition)
        return
    if target_type == "registry-lane-instance":
        lane = _get_registry_lane_instance(target_id)
        if not lane.get("launchable_now"):
            raise HTTPException(status_code=400, detail=f"Registry lane is not launchable yet: {target_id}")
        definition = _build_registry_lane_instance_service_definition(config, lane)
        manager.start_configured_service(definition)
        return
    raise HTTPException(status_code=400, detail=f"Unknown server action target type: {target_type}")


def _stop_server_action_target(target: dict[str, Any] | None) -> None:
    if not target:
        raise HTTPException(status_code=400, detail="Missing server action target")
    target_type = str(target.get("type") or "")
    target_id = str(target.get("id") or "")
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing server action target id")
    if target_type == "service":
        manager.stop(target_id)
        return
    if target_type == "node-instance":
        instance = _get_node_instance(target_id)
        service_name = instance.get("service_name")
        if not service_name:
            raise HTTPException(status_code=400, detail=f"Node instance has no service binding: {target_id}")
        manager.stop(str(service_name))
        return
    if target_type == "registry-lane-instance":
        lane = _get_registry_lane_instance(target_id)
        service_name = lane.get("service_name")
        if not service_name:
            raise HTTPException(status_code=400, detail=f"Registry lane has no service binding: {target_id}")
        manager.stop(str(service_name))
        return
    raise HTTPException(status_code=400, detail=f"Unknown server action target type: {target_type}")


def _service_name_for_action_target(config: LabConfig, target: dict[str, Any] | None) -> str:
    if not target:
        raise HTTPException(status_code=400, detail="Missing server action target")
    target_type = str(target.get("type") or "")
    target_id = str(target.get("id") or "")
    if target_type == "service":
        return target_id
    if target_type == "node-instance":
        instance = _get_node_instance(target_id)
        service_name = str(instance.get("service_name") or "")
        if not service_name:
            raise HTTPException(status_code=400, detail=f"Node instance has no service binding: {target_id}")
        return service_name
    if target_type == "registry-lane-instance":
        lane = _get_registry_lane_instance(target_id)
        service_name = str(lane.get("service_name") or "")
        if not service_name:
            raise HTTPException(status_code=400, detail=f"Registry lane has no service binding: {target_id}")
        return service_name
    raise HTTPException(status_code=400, detail=f"Unknown server action target type: {target_type}")


def _definition_for_action_target(config: LabConfig, target: dict[str, Any] | None) -> LabServiceDefinition:
    if not target:
        raise HTTPException(status_code=400, detail="Missing server action target")
    target_type = str(target.get("type") or "")
    target_id = str(target.get("id") or "")
    if target_type == "service":
        return _get_service_definition(config, target_id)
    if target_type == "node-instance":
        instance = _get_node_instance(target_id)
        if instance.get("launch_mode") == "seeded_service" and instance.get("service_name") in config.services:
            return _get_service_definition(config, str(instance["service_name"]))
        return _build_node_instance_service_definition(config, instance)
    if target_type == "registry-lane-instance":
        lane = _get_registry_lane_instance(target_id)
        return _build_registry_lane_instance_service_definition(config, lane)
    raise HTTPException(status_code=400, detail=f"Unknown server action target type: {target_type}")


def _restart_server_action_target(config: LabConfig, target: dict[str, Any] | None) -> None:
    service_name = _service_name_for_action_target(config, target)
    managed = manager.get_managed(service_name)
    if managed and managed.external and managed.process is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot restart adopted external service from lab: {service_name}",
        )
    _stop_server_action_target(target)
    _start_server_action_target(config, target)


def _adopt_server_action_target(config: LabConfig, target: dict[str, Any] | None) -> None:
    definition = _definition_for_action_target(config, target)
    manager.adopt_existing_service(definition)


def _rebind_server_action_target(config: LabConfig, target: dict[str, Any] | None) -> None:
    definition = _definition_for_action_target(config, target)
    if definition.port is None:
        raise HTTPException(status_code=400, detail=f"Cannot rebind service without fixed port: {definition.name}")
    conflicting = manager.find_by_port(definition.port, exclude_name=definition.name)
    if conflicting and not conflicting.external and conflicting.process is not None and conflicting.process.poll() is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Port {definition.port} is still owned by lab-managed runtime {conflicting.name}. "
                "Stop that runtime before rebinding this lane."
            ),
        )
    if conflicting:
        manager.forget(conflicting.name)
    manager.forget(definition.name)
    manager.adopt_existing_service(definition)


def _recover_server_action_target(config: LabConfig, target: dict[str, Any] | None) -> None:
    service_name = _service_name_for_action_target(config, target)
    status = manager.get_service_status(service_name)
    if status and status.get("running") and status.get("usable"):
        return
    managed = manager.get_managed(service_name)
    if managed and managed.external and managed.process is None:
        manager.forget(service_name)
        _start_server_action_target(config, target)
        return
    if status and status.get("running") and not status.get("usable"):
        _restart_server_action_target(config, target)
        return
    _start_server_action_target(config, target)


def _server_binding_projection(
    *,
    service_name: str,
    service_kind: str,
    action_target: dict[str, Any] | None,
    attached_registry_profiles: list[dict[str, Any]],
    attached_node_templates: list[dict[str, Any]],
    attached_node_instances: list[dict[str, Any]],
) -> dict[str, Any]:
    target_type = str((action_target or {}).get("type") or "")
    target_id = str((action_target or {}).get("id") or "")

    if target_type == "node-instance":
        attached = next((item for item in attached_node_instances if item.get("id") == target_id), None)
        title = str((attached or {}).get("title") or target_id or service_name)
        node_id = str((attached or {}).get("node_id") or target_id or service_name)
        return {
            "kind": "node-instance",
            "title": title,
            "owner_id": target_id or service_name,
            "owner_story": f"Generated node instance {title}",
            "description": (
                f"This room treats the live runtime on this port as node `{node_id}` "
                f"inside generated instance `{target_id or service_name}`."
            ),
            "can_rebind": True,
        }

    if target_type == "registry-lane-instance":
        attached = next((item for item in attached_registry_profiles if item.get("id") == target_id), None)
        title = str((attached or {}).get("title") or target_id or service_name)
        return {
            "kind": "registry-lane-instance",
            "title": title,
            "owner_id": target_id or service_name,
            "owner_story": f"Generated registry lane {title}",
            "description": (
                f"This room treats the live registry process on this port as lane `{target_id or service_name}` "
                f"with the meaning layer `{title}`."
            ),
            "can_rebind": True,
        }

    if attached_registry_profiles:
        if len(attached_registry_profiles) == 1:
            lane = attached_registry_profiles[0]
            title = str(lane.get("title") or lane.get("id") or service_name)
            lane_id = str(lane.get("id") or service_name)
            return {
                "kind": "registry-profile",
                "title": title,
                "owner_id": lane_id,
                "owner_story": f"Registry lane {title}",
                "description": f"This room treats this runtime as the canonical service binding for registry lane `{lane_id}`.",
                "can_rebind": False,
            }
        titles = [str(item.get("title") or item.get("id") or service_name) for item in attached_registry_profiles]
        return {
            "kind": "registry-service-shared",
            "title": "Shared registry service",
            "owner_id": service_name,
            "owner_story": f"Shared registry runtime for {_count_phrase(len(titles), 'lane')}",
            "description": f"This room maps this runtime to multiple registry lanes: {', '.join(titles[:3])}.",
            "can_rebind": False,
        }

    if attached_node_templates:
        if len(attached_node_templates) == 1:
            template = attached_node_templates[0]
            title = str(template.get("title") or template.get("id") or service_name)
            return {
                "kind": "node-template",
                "title": title,
                "owner_id": str(template.get("id") or service_name),
                "owner_story": f"Seeded node template {title}",
                "description": f"This room treats this runtime as the seeded service binding for node template `{template.get('id') or service_name}`.",
                "can_rebind": False,
            }
        titles = [str(item.get("title") or item.get("id") or service_name) for item in attached_node_templates]
        return {
            "kind": "node-template-shared",
            "title": "Shared seeded runtime",
            "owner_id": service_name,
            "owner_story": f"Seeded runtime for {_count_phrase(len(titles), 'template')}",
            "description": f"This room maps this runtime to multiple seeded templates: {', '.join(titles[:3])}.",
            "can_rebind": False,
        }

    if attached_node_instances:
        if len(attached_node_instances) == 1:
            instance = attached_node_instances[0]
            title = str(instance.get("title") or instance.get("id") or service_name)
            node_id = str(instance.get("node_id") or instance.get("id") or service_name)
            return {
                "kind": "node-instance-attached",
                "title": title,
                "owner_id": str(instance.get("id") or service_name),
                "owner_story": f"Generated node instance {title}",
                "description": f"This room treats this runtime as the service layer behind node `{node_id}`.",
                "can_rebind": False,
            }
        titles = [str(item.get("title") or item.get("id") or service_name) for item in attached_node_instances]
        return {
            "kind": "node-service-shared",
            "title": "Shared node runtime",
            "owner_id": service_name,
            "owner_story": f"Shared runtime for {_count_phrase(len(titles), 'generated lane')}",
            "description": f"This room maps this runtime to multiple generated node lanes: {', '.join(titles[:3])}.",
            "can_rebind": False,
        }

    return {
        "kind": service_kind,
        "title": service_name,
        "owner_id": service_name,
        "owner_story": f"Local {service_kind} runtime",
        "description": "This room has no richer binding truth projected for this runtime yet.",
        "can_rebind": False,
    }


def topology_projection(config: LabConfig) -> dict[str, Any]:
    runtime_status = {item["name"]: item for item in manager.status()["services"]}
    registry_overrides = state_store.list_registry_profile_overrides()
    registry_lane_instances = state_store.list_registry_lane_instances()
    node_templates = [_resolve_node_profile_projection(profile) for profile in config.node_profiles.values()]
    node_instances = state_store.list_node_instances()
    registry_template_projections = {
        profile.id: _resolve_registry_profile_projection(profile, registry_overrides.get(profile.id))
        for profile in config.registry_profiles.values()
    }
    registry_lane_projections = {
        lane["id"]: _resolve_registry_lane_instance_projection(lane)
        for lane in registry_lane_instances
    }
    items: list[dict[str, Any]] = []

    def _build_topology_item(
        profile_projection: dict[str, Any],
        *,
        service_definition: LabServiceDefinition,
    ) -> dict[str, Any]:
        service_projection = _resolve_service_projection(service_definition)
        status = runtime_status.get(profile_projection["service_name"])
        upstream_profiles = [
            (
                registry_template_projections.get(upstream_id)
                or registry_lane_projections.get(upstream_id)
            )
            for upstream_id in profile_projection["upstreams"]
            if registry_template_projections.get(upstream_id) or registry_lane_projections.get(upstream_id)
        ]
        attached_node_templates = []
        attached_node_instances = []
        layer_links: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for link in service_projection["links"]:
            pair = (link["label"], link["url"])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                layer_links.append(link)

        for template in node_templates:
            targeted = profile_projection["id"] in template.get("registry_targets", [])
            expected = profile_projection["id"] in template.get("visibility_expectations", [])
            if not targeted and not expected:
                continue
            attached = {
                **template,
                "registry_targeted": targeted,
                "visibility_expected": expected,
            }
            attached_node_templates.append(attached)
            if template.get("operator_url"):
                pair = (f"{template['id']} operator", template["operator_url"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    layer_links.append(
                        {
                            "label": f"{template['id']} operator",
                            "url": template["operator_url"],
                            "description": "Operator surface for a node template linked to this registry lane.",
                        }
                    )
            if template.get("public_shop_url"):
                pair = (f"{template['id']} public shop", template["public_shop_url"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    layer_links.append(
                        {
                            "label": f"{template['id']} public shop",
                            "url": template["public_shop_url"],
                            "description": "Public customer surface for a node template linked to this registry lane.",
                        }
                    )

        for instance in node_instances:
            targeted = profile_projection["id"] in instance.get("registry_targets", [])
            expected = profile_projection["id"] in instance.get("visibility_expectations", [])
            if not targeted and not expected:
                continue
            attached = {
                **instance,
                "registry_targeted": targeted,
                "visibility_expected": expected,
            }
            attached_node_instances.append(attached)
            if instance.get("operator_url"):
                pair = (f"{instance['id']} operator", instance["operator_url"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    layer_links.append(
                        {
                            "label": f"{instance['id']} operator",
                            "url": instance["operator_url"],
                            "description": "Operator surface for a persisted node instance linked to this registry lane.",
                        }
                    )
            if instance.get("public_shop_url"):
                pair = (f"{instance['id']} public shop", instance["public_shop_url"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    layer_links.append(
                        {
                            "label": f"{instance['id']} public shop",
                            "url": instance["public_shop_url"],
                            "description": "Public customer surface for a persisted node instance linked to this registry lane.",
                        }
                    )

        return {
            **profile_projection,
            "service": service_projection,
            "status": status,
            "running": bool(status and status.get("running")),
            "usable": bool(status and status.get("usable")),
            "upstream_profiles": upstream_profiles,
            "attached_node_templates": attached_node_templates,
            "attached_node_instances": attached_node_instances,
            "layer_links": layer_links,
        }

    for profile in config.registry_profiles.values():
        profile_projection = registry_template_projections[profile.id]
        service_definition = _get_service_definition(config, profile.service_name)
        items.append(_build_topology_item(profile_projection, service_definition=service_definition))

    for lane in registry_lane_instances:
        lane_projection = registry_lane_projections[lane["id"]]
        service_definition = _build_registry_lane_instance_service_definition(config, lane)
        items.append(_build_topology_item(lane_projection, service_definition=service_definition))

    return {
        "registry_profiles": items,
        "registry_templates": list(registry_template_projections.values()),
        "registry_lane_instances": list(registry_lane_projections.values()),
    }


def _get_service_definition(config: LabConfig, service_name: str) -> LabServiceDefinition:
    definition = config.services.get(service_name)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown configured service: {service_name}")
    return definition


def _get_node_profile(config: LabConfig, profile_id: str) -> LabNodeProfileDefinition:
    profile = config.node_profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown node profile: {profile_id}")
    return profile


def _get_customer_fixture(config: LabConfig, fixture_id: str) -> dict[str, Any]:
    fixture = config.customer_fixtures.get(fixture_id)
    if fixture is not None:
        return _resolve_customer_fixture_projection(fixture)
    instance = state_store.get_customer_fixture_instance(fixture_id)
    if instance is not None:
        return instance
    raise HTTPException(status_code=404, detail=f"Unknown customer fixture: {fixture_id}")


def _get_flow_scenario(config: LabConfig, scenario_id: str) -> LabFlowScenarioDefinition:
    scenario = next((item for item in config.flow_scenarios if item.id == scenario_id), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown flow scenario: {scenario_id}")
    return scenario


def _get_flow_scenario_instance(scenario_id: str) -> dict[str, Any]:
    scenario = state_store.get_flow_scenario_instance(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown flow scenario instance: {scenario_id}")
    return scenario


def _get_legacy_scenario(config: LabConfig, scenario_id: str) -> LabLegacyScenarioDefinition:
    scenario = next((item for item in config.legacy_scenarios if item.id == scenario_id), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown legacy scenario: {scenario_id}")
    return scenario


def _get_node_instance(instance_id: str) -> dict[str, Any]:
    instance = state_store.get_node_instance(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Unknown node instance: {instance_id}")
    return instance


def _get_registry_lane_instance(instance_id: str) -> dict[str, Any]:
    lane = state_store.get_registry_lane_instance(instance_id)
    if lane is None:
        raise HTTPException(status_code=404, detail=f"Unknown registry lane instance: {instance_id}")
    return lane


def _resolve_flow_target(config: LabConfig, target_ref: str) -> dict[str, Any]:
    if target_ref in config.node_profiles:
        profile = _get_node_profile(config, target_ref)
        service = _get_service_definition(config, profile.service_name)
        customer_urls = _resolve_profile_customer_urls(profile)
        public_shop_url, public_surface_key = _pick_public_shop_url(customer_urls, "public_shop")
        return {
            "id": profile.id,
            "title": profile.title,
            "kind": "seed_profile",
            "owner_kind": "seed_profile",
            "owner_story": f"Seeded node template {profile.title}",
            "service_name": profile.service_name,
            "service_definition": service,
            "customer_urls": customer_urls,
            "operator_url": _resolve_text(profile.operator_url),
            "public_shop_url": public_shop_url,
            "public_surface_key": public_surface_key,
            "node_id": profile.id,
            "city": None,
            "country": None,
            "categories": [],
            "order_mode": None,
            "registry_targets": list(profile.registry_targets),
            "visibility_expectations": list(profile.visibility_expectations),
        }
    instance = state_store.get_node_instance(target_ref)
    if instance is not None:
        service_name = str(instance.get("service_name") or "")
        if instance.get("launch_mode") == "seeded_service" and service_name in config.services:
            service = _get_service_definition(config, service_name)
        else:
            service = _build_node_instance_service_definition(config, instance)
        title = str(instance.get("title") or instance["id"])
        return {
            "id": instance["id"],
            "title": title,
            "kind": "node_instance",
            "owner_kind": "node_instance",
            "owner_story": f"Generated node instance {title}",
            "service_name": service_name,
            "service_definition": service,
            "customer_urls": dict(instance.get("customer_urls") or {}),
            "operator_url": instance.get("operator_url"),
            "public_shop_url": instance.get("public_shop_url"),
            "public_surface_key": instance.get("public_surface_key") or "public_shop",
            "node_id": str(instance.get("node_id") or instance["id"]),
            "city": instance.get("city"),
            "country": instance.get("country"),
            "categories": list(instance.get("categories") or []),
            "order_mode": instance.get("order_mode"),
            "registry_targets": list(instance.get("registry_targets") or []),
            "visibility_expectations": list(instance.get("visibility_expectations") or []),
        }
    raise HTTPException(status_code=404, detail=f"Unknown flow target: {target_ref}")


def _flow_target_summary(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": target["id"],
        "title": target["title"],
        "kind": target["kind"],
        "owner_kind": target.get("owner_kind"),
        "owner_story": target.get("owner_story"),
        "node_id": target.get("node_id"),
        "city": target.get("city"),
        "country": target.get("country"),
        "categories": list(target.get("categories") or []),
        "order_mode": target.get("order_mode"),
        "service_name": target["service_name"],
        "public_surface_key": target.get("public_surface_key") or "public_shop",
        "public_shop_url": target.get("public_shop_url"),
        "registry_targets": list(target.get("registry_targets") or []),
        "visibility_expectations": list(target.get("visibility_expectations") or []),
    }


def _replace_port_in_command(command: list[str], port: int) -> list[str]:
    updated = list(command)
    if "--port" in updated:
        index = updated.index("--port")
        if index + 1 < len(updated):
            updated[index + 1] = str(port)
            return updated
    updated.extend(["--port", str(port)])
    return updated


def _build_node_instance_service_definition(config: LabConfig, instance: dict[str, Any]) -> LabServiceDefinition:
    template = _get_node_profile(config, instance["template_id"])
    template_service = _get_service_definition(config, template.service_name)
    if template_service.kind != "pilot-node":
        raise HTTPException(
            status_code=400,
            detail=f"Only pilot-node templates can generate launchable node instances in this slice: {template.id}",
        )
    port = instance.get("port")
    if not port:
        raise HTTPException(status_code=400, detail=f"Node instance has no assigned port: {instance['id']}")

    command = [_resolve_text(part) or part for part in template_service.command]
    command = _replace_port_in_command(command, int(port))
    env = {key: _resolve_text(value) or "" for key, value in template_service.env.items()}
    env["P4P_NODE_MODULES"] = ",".join(_clean_string_list(instance.get("module_ids", [])))
    registry_urls = _registry_urls_for_targets(
        config,
        _clean_string_list(instance.get("registry_targets", [])),
        state_store.list_registry_lane_instances(),
    )
    if registry_urls:
        env["P4P_REGISTRY_URLS"] = ",".join(registry_urls)
        env["P4P_REGISTRY_URL"] = registry_urls[0]
    env = _apply_menu_seed_to_env(env, _normalize_menu_seed(instance.get("menu_seed") or {}))
    db_path = LAB_STATE_ROOT / f"{instance['id']}.sqlite3"
    env.update(
        {
            "P4P_PILOT_NODE_DB_PATH": str(db_path),
            "P4P_NODE_BASE_URL": f"http://127.0.0.1:{port}",
            "P4P_NODE_ID": str(instance.get("node_id") or instance["id"]),
            "P4P_NODE_NAME": str(instance.get("title") or instance["id"]),
            "P4P_NODE_CITY": str(instance.get("city") or ""),
            "P4P_NODE_COUNTRY": str(instance.get("country") or ""),
            "P4P_NODE_CATEGORIES": ",".join(_clean_string_list(instance.get("categories", []))),
            "P4P_NODE_ORDER_MODE": str(instance.get("order_mode") or "live"),
            "P4P_OPERATOR_TOKEN": str(instance.get("operator_token") or "change-this"),
        }
    )
    health_url = f"http://127.0.0.1:{port}/"
    links: list[dict[str, str]] = [
        {
            "label": "Pilot index",
            "url": health_url,
            "description": "Generated node instance root.",
        }
    ]
    operator_url = instance.get("operator_url")
    if operator_url:
        links.append(
            {
                "label": "Generated operator",
                "url": operator_url,
                "description": "Operator surface for the generated node instance.",
            }
        )
    public_shop_url = instance.get("public_shop_url")
    if public_shop_url:
        links.append(
            {
                "label": "Generated public shop",
                "url": public_shop_url,
                "description": "Public customer surface for the generated node instance.",
            }
        )
    for key, url in (instance.get("customer_urls") or {}).items():
        if not url:
            continue
        label = key.replace("_", " ").replace("-", " ").title()
        links.append(
            {
                "label": label,
                "url": url,
                "description": "Derived customer-facing route from the instance template.",
            }
        )

    return LabServiceDefinition(
        name=str(instance["service_name"]),
        kind=template_service.kind,
        description=f"Generated node instance from template {template.id}.",
        cwd=template_service.cwd,
        command=command,
        env=env,
        port=int(port),
        health_url=health_url,
        ready_text=template_service.ready_text,
        links=links,
    )


def _build_registry_lane_instance_service_definition(config: LabConfig, lane: dict[str, Any]) -> LabServiceDefinition:
    template = config.registry_profiles.get(str(lane["template_id"]))
    if template is None:
        raise HTTPException(status_code=400, detail=f"Unknown registry lane template: {lane['template_id']}")
    template_service = _get_service_definition(config, template.service_name)
    if template_service.kind != "registry":
        raise HTTPException(
            status_code=400,
            detail=f"Only registry templates can generate launchable registry lanes in this slice: {template.id}",
        )
    port = lane.get("port")
    if not port:
        raise HTTPException(status_code=400, detail=f"Registry lane has no assigned port: {lane['id']}")
    command = [_resolve_text(part) or part for part in template_service.command]
    command = _replace_port_in_command(command, int(port))
    self_url = f"http://127.0.0.1:{int(port)}"
    upstream_urls = _registry_urls_for_targets(
        config,
        _clean_string_list(lane.get("upstreams", [])),
        state_store.list_registry_lane_instances(),
    )
    backups = [{"tier": 0, "url": self_url}]
    for index, upstream_url in enumerate(upstream_urls, start=1):
        backups.append({"tier": index, "url": upstream_url})
    env = {key: _resolve_text(value) or "" for key, value in template_service.env.items()}
    env["P4P_REGISTRY_URL"] = self_url
    env["P4P_BACKUP_REGISTRIES"] = json.dumps(backups, ensure_ascii=True)
    links = [
        {
            "label": "Registry info",
            "url": f"{self_url}/registry-info",
            "description": f"Shows identity and backup configuration for generated lane {lane['id']}.",
        },
        {
            "label": "Lane discover",
            "url": f"{self_url}/discover?lat=55.6517&lng=12.4126&radius=50&category=pizza&country=DK",
            "description": f"Checks discoverability through generated lane {lane['id']}.",
        },
    ]
    return LabServiceDefinition(
        name=str(lane["service_name"]),
        kind="registry",
        description=f"Generated registry lane from template {template.id}.",
        cwd=template_service.cwd,
        command=command,
        env=env,
        port=int(port),
        health_url=f"{self_url}/registry-info",
        ready_text=template_service.ready_text,
        links=links,
    )


def _http_json_request(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=4.0) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.getcode(), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"detail": raw or f"HTTP {exc.code}"}
        return exc.code, payload
    except Exception as exc:
        return 0, {"detail": str(exc)}


def _wait_for_service_ready(service_name: str, *, timeout_seconds: float = 8.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        status = manager.get_service_status(service_name)
        last_status = status
        if status and status.get("running") and status.get("usable"):
            return status
        time.sleep(0.2)
    return last_status


def _record_run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_store.record(payload)


def run_customer_fixture(
    config: LabConfig,
    fixture_id: str,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    fixture = _get_customer_fixture(config, fixture_id)
    effective_profile_id = profile_id or str(fixture.get("target_profile") or fixture.get("target_ref") or "").strip()
    target = _resolve_flow_target(config, effective_profile_id)
    service = target["service_definition"]
    started_at = time.time()

    manager.start_configured_service(service)
    service_status = _wait_for_service_ready(service.name)
    profile_urls = target["customer_urls"]
    menu_json_url = profile_urls.get("menu_json")
    order_api_url = profile_urls.get("order_api")
    status_template = profile_urls.get("status_api_template")
    selected_surface_key = str(fixture.get("menu_surface") or target.get("public_surface_key") or "public_shop")
    selected_surface_url = str(profile_urls.get(selected_surface_key) or target.get("public_shop_url") or "")

    run_payload: dict[str, Any] = {
        "kind": "customer_fixture",
        "fixture_id": fixture["id"],
        "title": fixture["title"],
        "profile_id": target["id"],
        "owner_kind": target.get("owner_kind"),
        "owner_story": target.get("owner_story"),
        "node_id": target.get("node_id"),
        "service_name": service.name,
        "menu_surface": fixture["menu_surface"],
        "public_surface_key": selected_surface_key,
        "surface_url": selected_surface_url or None,
        "registry_targets": list(target.get("registry_targets") or []),
        "visibility_expectations": list(target.get("visibility_expectations") or []),
        "request_payload": fixture["order_request"],
        "started_at": started_at,
        "finished_at": None,
        "order_id": None,
        "status_payload": None,
        "success": False,
        "error": None,
    }

    if not service_status or not service_status.get("usable"):
        run_payload["finished_at"] = time.time()
        run_payload["error"] = f"Service not ready: {service.name}"
        return _record_run(run_payload)

    try:
        if menu_json_url:
            menu_status_code, menu_payload = _http_json_request("GET", menu_json_url)
            if menu_status_code != 200:
                raise RuntimeError(f"Menu fetch failed with status {menu_status_code}")
            if isinstance(menu_payload, dict):
                menu_items = {
                    str(item.get("id"))
                    for item in menu_payload.get("items", [])
                    if isinstance(item, dict) and item.get("id") is not None
                }
                if menu_items:
                    requested_ids = {
                        str(item.get("id"))
                        for item in fixture["order_request"].get("items", [])
                        if isinstance(item, dict) and item.get("id") is not None
                    }
                    missing = sorted(requested_ids - menu_items)
                    if missing:
                        raise RuntimeError(f"Fixture items missing from menu: {', '.join(missing)}")

        if not order_api_url:
            raise RuntimeError(f"Missing order_api for node profile: {target['id']}")

        order_status_code, order_payload = _http_json_request("POST", order_api_url, fixture["order_request"])
        if order_status_code != 200 or not isinstance(order_payload, dict):
            detail = order_payload.get("detail") if isinstance(order_payload, dict) else order_payload
            raise RuntimeError(f"Order request failed: {detail or order_status_code}")
        if order_payload.get("accepted") is False:
            raise RuntimeError(order_payload.get("message") or order_payload.get("reason") or "Order rejected.")

        order_id = str(order_payload.get("order_id") or "").strip()
        run_payload["order_id"] = order_id or None

        expected = fixture.get("expected") or {}
        expected_accepted = bool(expected.get("accepted", True))
        if expected_accepted and not order_id:
            raise RuntimeError("Order accepted response did not include order_id.")

        last_status_payload: dict[str, Any] | None = None
        poll = fixture.get("poll_status") or None
        if poll and poll.get("enabled", True) and order_id:
            if not status_template:
                raise RuntimeError(f"Missing status_api_template for node profile: {target['id']}")
            status_url = status_template.replace("{order_id}", quote(order_id, safe=""))
            for attempt in range(int(poll.get("attempts", 4))):
                status_code, status_payload = _http_json_request("GET", status_url)
                if status_code == 200 and isinstance(status_payload, dict):
                    last_status_payload = status_payload
                    expected_final_status = str(expected.get("final_status") or "").strip()
                    if not expected_final_status or status_payload.get("status") == expected_final_status:
                        break
                if attempt < int(poll.get("attempts", 4)) - 1:
                    time.sleep(int(poll.get("interval_ms", 250)) / 1000)

        run_payload["status_payload"] = last_status_payload

        expected_final_status = str(expected.get("final_status") or "").strip()
        final_status_matches = True
        if expected_final_status:
            final_status_matches = (
                isinstance(last_status_payload, dict) and last_status_payload.get("status") == expected_final_status
            )

        run_payload["success"] = bool(order_id) and final_status_matches and expected_accepted
    except Exception as exc:
        run_payload["error"] = str(exc)

    run_payload["finished_at"] = time.time()
    return _record_run(run_payload)


def run_flow_scenario(config: LabConfig, scenario_id: str) -> dict[str, Any]:
    scenario = _get_flow_scenario(config, scenario_id)
    return _run_flow_plan(
        config,
        kind="flow_scenario",
        scenario_id=scenario.id,
        title=scenario.title,
        services=list(scenario.services),
        node_refs=list(scenario.node_profiles),
        fixture_runs=[item.model_dump(mode="json") for item in scenario.fixture_runs],
        checks=[item.model_dump(mode="json") for item in scenario.checks],
    )


def run_flow_scenario_instance(config: LabConfig, scenario_id: str) -> dict[str, Any]:
    scenario = _get_flow_scenario_instance(scenario_id)
    return _run_flow_plan(
        config,
        kind="flow_scenario_instance",
        scenario_id=scenario["id"],
        title=scenario["title"],
        services=list(scenario.get("services") or []),
        node_refs=list(scenario.get("node_profiles") or []),
        fixture_runs=list(scenario.get("fixture_runs") or []),
        checks=list(scenario.get("checks") or []),
    )


def _run_flow_plan(
    config: LabConfig,
    *,
    kind: str,
    scenario_id: str,
    title: str,
    services: list[str],
    node_refs: list[str],
    fixture_runs: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    started_at = time.time()
    fixture_results: dict[str, dict[str, Any]] = {}
    check_results: list[dict[str, Any]] = []
    resolved_targets_by_id: dict[str, dict[str, Any]] = {}

    for service_name in services:
        service = _get_service_definition(config, service_name)
        manager.start_configured_service(service)
        _wait_for_service_ready(service.name)

    for target_ref in node_refs:
        target = _resolve_flow_target(config, target_ref)
        resolved_targets_by_id[target["id"]] = _flow_target_summary(target)
        service = target["service_definition"]
        manager.start_configured_service(service)
        _wait_for_service_ready(service.name)

    for fixture_run in fixture_runs:
        fixture_id = str(fixture_run.get("fixture_id", "")).strip()
        fixture = _get_customer_fixture(config, fixture_id)
        effective_profile_id = str(fixture_run.get("profile_id", "")).strip() or str(
            fixture.get("target_profile") or fixture.get("target_ref") or ""
        ).strip()
        target = _resolve_flow_target(config, effective_profile_id)
        resolved_targets_by_id[target["id"]] = _flow_target_summary(target)
        result = run_customer_fixture(config, fixture_id, profile_id=effective_profile_id)
        fixture_results[f"{fixture_id}:{effective_profile_id}"] = result

    overall_success = all(result.get("success") for result in fixture_results.values()) if fixture_results else True

    for check in checks:
        result = {
            "kind": check.get("kind"),
            "service": check.get("service"),
            "fixture_id": check.get("fixture_id"),
            "profile_id": check.get("profile_id"),
            "success": False,
            "detail": "",
        }
        if check.get("kind") == "service_usable":
            status = manager.get_service_status(check.get("service") or "")
            result["success"] = bool(status and status.get("usable"))
            result["detail"] = f"usable={bool(status and status.get('usable'))}"
        elif check.get("kind") == "service_running":
            status = manager.get_service_status(check.get("service") or "")
            result["success"] = bool(status and status.get("running"))
            result["detail"] = f"running={bool(status and status.get('running'))}"
        elif check.get("kind") == "stop_service":
            manager.stop(check.get("service") or "")
            result["success"] = True
            result["detail"] = "service stopped"
        elif check.get("kind") == "service_stopped":
            status = manager.get_service_status(check.get("service") or "")
            result["success"] = not bool(status and status.get("running"))
            result["detail"] = f"running={bool(status and status.get('running')) if status else False}"
        elif check.get("kind") == "fixture_succeeded":
            fixture_id = check.get("fixture_id") or ""
            fixture = _get_customer_fixture(config, fixture_id)
            key = f"{fixture_id}:{check.get('profile_id') or fixture.get('target_profile') or fixture.get('target_ref')}"
            fixture_result = fixture_results.get(key)
            result["success"] = bool(fixture_result and fixture_result.get("success"))
            result["detail"] = f"fixture_run={key}"
        else:
            result["detail"] = "unknown check kind"

        check_results.append(result)
        if not result["success"]:
            overall_success = False

    run_payload = {
        "kind": kind,
        "scenario_id": scenario_id,
        "title": title,
        "started_at": started_at,
        "finished_at": time.time(),
        "services": list(services),
        "node_profiles": list(node_refs),
        "resolved_targets": list(resolved_targets_by_id.values()),
        "fixture_run_ids": [result["run_id"] for result in fixture_results.values()],
        "checks": check_results,
        "success": overall_success,
        "error": None,
    }
    return _record_run(run_payload)


manager = ProcessManager()
run_store = RunStore()
state_store = LabStateStore(_lab_state_db_path())
app = FastAPI(title="P4P Lab", version="0.2")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/nodes", response_class=HTMLResponse)
def nodes_page() -> str:
    return (Path(__file__).parent / "nodes.html").read_text(encoding="utf-8")


@app.get("/servers", response_class=HTMLResponse)
def servers_page() -> str:
    return (Path(__file__).parent / "servers.html").read_text(encoding="utf-8")


@app.get("/control", response_class=HTMLResponse)
def control_page() -> str:
    return (Path(__file__).parent / "control.html").read_text(encoding="utf-8")


@app.get("/runs", response_class=HTMLResponse)
def runs_page() -> str:
    return (Path(__file__).parent / "runs.html").read_text(encoding="utf-8")


@app.get("/topology", response_class=HTMLResponse)
def topology_page() -> str:
    return (Path(__file__).parent / "topology.html").read_text(encoding="utf-8")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return manager.status()


@app.get("/api/scenarios")
def api_scenarios() -> dict[str, Any]:
    return scenario_projection(load_lab_config())


@app.get("/api/nodes-room")
def api_nodes_room() -> dict[str, Any]:
    return nodes_room_projection(load_lab_config())


@app.get("/api/servers")
def api_servers() -> dict[str, Any]:
    return server_inventory_projection(load_lab_config())


@app.get("/api/control-rooms")
def api_control_rooms() -> dict[str, Any]:
    return control_rooms_projection(load_lab_config())


@app.get("/api/runs-room")
def api_runs_room() -> dict[str, Any]:
    return runs_room_projection()


@app.get("/api/topology")
def api_topology() -> dict[str, Any]:
    return topology_projection(load_lab_config())


@app.patch("/api/registry-profiles/{profile_id}")
def api_update_registry_profile(profile_id: str, payload: LabRegistryProfileUpdateRequest) -> dict[str, Any]:
    config = load_lab_config()
    override = state_store.update_registry_profile_override(
        config=config,
        profile_id=profile_id,
        title=payload.title,
        description=payload.description,
        upstreams=payload.upstreams,
        announce_policy=payload.announce_policy,
        discover_policy=payload.discover_policy,
        notes=payload.notes,
    )
    return {
        "registry_profile_override": override,
        "registry_profiles": scenario_projection(config)["registry_profiles"],
        "topology": topology_projection(config),
    }


@app.get("/api/registry-lane-instances")
def api_registry_lane_instances() -> dict[str, Any]:
    load_lab_config()
    return {"registry_lane_instances": state_store.list_registry_lane_instances()}


@app.post("/api/registry-lane-instances")
def api_create_registry_lane_instance(payload: LabRegistryLaneInstanceCreateRequest) -> dict[str, Any]:
    config = load_lab_config()
    template = config.registry_profiles.get(payload.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Unknown registry template: {payload.template_id}")
    lane = state_store.create_registry_lane_instance(
        config=config,
        template=template,
        instance_id=payload.instance_id,
        title=payload.title,
        description=payload.description,
        notes=payload.notes,
    )
    return {
        "registry_lane_instance": lane,
        "registry_lane_instances": state_store.list_registry_lane_instances(),
        "topology": topology_projection(config),
    }


@app.patch("/api/registry-lane-instances/{instance_id}")
def api_update_registry_lane_instance(
    instance_id: str,
    payload: LabRegistryLaneInstanceUpdateRequest,
) -> dict[str, Any]:
    config = load_lab_config()
    lane = state_store.update_registry_lane_instance(
        config=config,
        instance_id=instance_id,
        title=payload.title,
        description=payload.description,
        upstreams=payload.upstreams,
        announce_policy=payload.announce_policy,
        discover_policy=payload.discover_policy,
        notes=payload.notes,
    )
    return {
        "registry_lane_instance": lane,
        "registry_lane_instances": state_store.list_registry_lane_instances(),
        "topology": topology_projection(config),
    }


@app.post("/api/registry-lane-instances/{instance_id}/start")
def api_start_registry_lane_instance(instance_id: str) -> dict[str, Any]:
    config = load_lab_config()
    _start_server_action_target(config, {"type": "registry-lane-instance", "id": instance_id})
    return {
        "status": manager.status(),
        "registry_lane_instances": state_store.list_registry_lane_instances(),
        "topology": topology_projection(config),
    }


@app.post("/api/registry-lane-instances/{instance_id}/stop")
def api_stop_registry_lane_instance(instance_id: str) -> dict[str, Any]:
    _stop_server_action_target({"type": "registry-lane-instance", "id": instance_id})
    return {
        "status": manager.status(),
        "registry_lane_instances": state_store.list_registry_lane_instances(),
    }


@app.get("/api/node-instances")
def api_node_instances() -> dict[str, Any]:
    load_lab_config()
    return {"node_instances": state_store.list_node_instances()}


@app.post("/api/node-instances")
def api_create_node_instance(payload: LabNodeInstanceCreateRequest) -> dict[str, Any]:
    config = load_lab_config()
    template = _get_node_profile(config, payload.template_id)
    instance = state_store.create_node_instance(
        config=config,
        template=template,
        instance_id=payload.instance_id,
        title=payload.title,
        description=payload.description,
        notes=payload.notes,
    )
    return {"node_instance": instance, "node_instances": state_store.list_node_instances()}


@app.patch("/api/node-instances/{instance_id}")
def api_update_node_instance(instance_id: str, payload: LabNodeInstanceUpdateRequest) -> dict[str, Any]:
    config = load_lab_config()
    instance = state_store.update_node_instance(
        config=config,
        instance_id=instance_id,
        title=payload.title,
        description=payload.description,
        notes=payload.notes,
        registry_targets=payload.registry_targets,
        visibility_expectations=payload.visibility_expectations,
        module_ids=payload.module_ids,
        menu_seed=payload.menu_seed,
        node_id=payload.node_id,
        city=payload.city,
        country=payload.country,
        categories=payload.categories,
        order_mode=payload.order_mode,
        public_surface_key=payload.public_surface_key,
    )
    return {"node_instance": instance, "node_instances": state_store.list_node_instances()}


@app.post("/api/node-instances/{instance_id}/start")
def api_start_node_instance(instance_id: str) -> dict[str, Any]:
    config = load_lab_config()
    _start_server_action_target(config, {"type": "node-instance", "id": instance_id})
    return {"status": manager.status(), "node_instances": state_store.list_node_instances()}


@app.post("/api/node-instances/{instance_id}/stop")
def api_stop_node_instance(instance_id: str) -> dict[str, Any]:
    _stop_server_action_target({"type": "node-instance", "id": instance_id})
    return {"status": manager.status(), "node_instances": state_store.list_node_instances()}


@app.get("/api/flow-scenario-instances")
def api_flow_scenario_instances() -> dict[str, Any]:
    load_lab_config()
    return {"flow_scenario_instances": state_store.list_flow_scenario_instances()}


@app.get("/api/customer-fixture-instances")
def api_customer_fixture_instances() -> dict[str, Any]:
    load_lab_config()
    return {"customer_fixture_instances": state_store.list_customer_fixture_instances()}


@app.post("/api/customer-fixture-instances")
def api_create_customer_fixture_instance(payload: LabCustomerFixtureInstanceCreateRequest) -> dict[str, Any]:
    config = load_lab_config()
    fixture = state_store.create_customer_fixture_instance(
        config=config,
        instance_id=payload.instance_id,
        title=payload.title,
        description=payload.description,
        target_ref=payload.target_ref,
        menu_surface=payload.menu_surface,
        order_request=payload.order_request,
        poll_status=payload.poll_status.model_dump(mode="json") if payload.poll_status else None,
        expected=payload.expected,
    )
    return {
        "customer_fixture_instance": fixture,
        "customer_fixture_instances": state_store.list_customer_fixture_instances(),
    }


@app.patch("/api/customer-fixture-instances/{instance_id}")
def api_update_customer_fixture_instance(
    instance_id: str,
    payload: LabCustomerFixtureInstanceUpdateRequest,
) -> dict[str, Any]:
    config = load_lab_config()
    fixture = state_store.update_customer_fixture_instance(
        config=config,
        instance_id=instance_id,
        title=payload.title,
        description=payload.description,
        target_ref=payload.target_ref,
        menu_surface=payload.menu_surface,
        order_request=payload.order_request,
        poll_status=payload.poll_status.model_dump(mode="json") if payload.poll_status else None,
        expected=payload.expected,
    )
    return {
        "customer_fixture_instance": fixture,
        "customer_fixture_instances": state_store.list_customer_fixture_instances(),
    }


@app.post("/api/flow-scenario-instances")
def api_create_flow_scenario_instance(payload: LabFlowScenarioInstanceCreateRequest) -> dict[str, Any]:
    config = load_lab_config()
    scenario = state_store.create_flow_scenario_instance(
        config=config,
        instance_id=payload.instance_id,
        title=payload.title,
        description=payload.description,
        services=payload.services,
        node_refs=payload.node_refs,
        fixture_runs=[item.model_dump(mode="json") for item in payload.fixture_runs],
        checks=[item.model_dump(mode="json") for item in payload.checks] if payload.checks is not None else None,
        notes=payload.notes,
    )
    return {
        "flow_scenario_instance": scenario,
        "flow_scenario_instances": state_store.list_flow_scenario_instances(),
    }


@app.patch("/api/flow-scenario-instances/{instance_id}")
def api_update_flow_scenario_instance(
    instance_id: str,
    payload: LabFlowScenarioInstanceUpdateRequest,
) -> dict[str, Any]:
    config = load_lab_config()
    scenario = state_store.update_flow_scenario_instance(
        config=config,
        instance_id=instance_id,
        title=payload.title,
        description=payload.description,
        services=payload.services,
        node_refs=payload.node_refs,
        fixture_runs=[item.model_dump(mode="json") for item in payload.fixture_runs],
        checks=[item.model_dump(mode="json") for item in payload.checks] if payload.checks is not None else None,
        notes=payload.notes,
    )
    return {
        "flow_scenario_instance": scenario,
        "flow_scenario_instances": state_store.list_flow_scenario_instances(),
    }


@app.get("/api/runs")
def api_runs() -> dict[str, Any]:
    runs = run_store.list()
    return {"runs": runs, "summary": _runs_summary(runs)}


@app.post("/api/node-profiles/{profile_id}/start")
def api_start_node_profile(profile_id: str) -> dict[str, Any]:
    config = load_lab_config()
    profile = _get_node_profile(config, profile_id)
    service = _get_service_definition(config, profile.service_name)
    manager.start_configured_service(service)
    return manager.status()


@app.post("/api/node-profiles/{profile_id}/stop")
def api_stop_node_profile(profile_id: str) -> dict[str, Any]:
    config = load_lab_config()
    profile = _get_node_profile(config, profile_id)
    manager.stop(profile.service_name)
    return manager.status()


@app.post("/api/customer-fixtures/{fixture_id}/run")
def api_run_customer_fixture(fixture_id: str) -> dict[str, Any]:
    config = load_lab_config()
    run = run_customer_fixture(config, fixture_id)
    return {"run": run, "status": manager.status(), "runs": run_store.list()}


@app.post("/api/flow-scenarios/{scenario_id}/run")
def api_run_flow_scenario(scenario_id: str) -> dict[str, Any]:
    config = load_lab_config()
    run = run_flow_scenario(config, scenario_id)
    return {"run": run, "status": manager.status(), "runs": run_store.list()}


@app.post("/api/flow-scenario-instances/{scenario_id}/run")
def api_run_flow_scenario_instance(scenario_id: str) -> dict[str, Any]:
    config = load_lab_config()
    run = run_flow_scenario_instance(config, scenario_id)
    return {"run": run, "status": manager.status(), "runs": run_store.list()}


@app.post("/api/scenarios/{scenario_id}/start")
def start_scenario(scenario_id: str) -> dict[str, Any]:
    config = load_lab_config()
    scenario = _get_legacy_scenario(config, scenario_id)
    for service_name in scenario.services:
        definition = _get_service_definition(config, service_name)
        manager.start_configured_service(definition)
    return manager.status()


@app.post("/api/scenarios/{scenario_id}/stop")
def stop_scenario(scenario_id: str) -> dict[str, Any]:
    config = load_lab_config()
    scenario = _get_legacy_scenario(config, scenario_id)
    for service_name in scenario.services:
        manager.stop(service_name)
    return manager.status()


@app.post("/api/services/{service_name}/start")
def start_configured_service(service_name: str) -> dict[str, Any]:
    config = load_lab_config()
    _start_server_action_target(config, {"type": "service", "id": service_name})
    return manager.status()


@app.post("/api/server-groups/{group_id}/{action}")
def api_server_group_action(group_id: str, action: str) -> dict[str, Any]:
    if action not in {"start", "stop", "restart", "recover"}:
        raise HTTPException(status_code=400, detail="Unsupported server-group action")
    config = load_lab_config()
    inventory = server_inventory_projection(config)
    group = next((item for item in inventory["groups"] if item["id"] == group_id), None)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Unknown server group: {group_id}")
    if not group.get("actions"):
        raise HTTPException(status_code=400, detail=f"Server group has no runtime action lane: {group_id}")
    member_targets: dict[str, dict[str, Any]] = {}
    for member in group.get("members", []):
        target = member.get("action_target")
        if not target:
            continue
        key = str(member.get("name") or target.get("id") or "").strip()
        if not key:
            continue
        member_targets[key] = target
    dependency_targets = {
        service_name: {"type": "service", "id": service_name}
        for service_name in group.get("dependency_service_names", [])
    }
    fallback_start_order = list(group.get("dependency_service_names", [])) + list(member_targets.keys())
    fallback_stop_order = list(reversed(list(member_targets.keys())))
    if action in {"start", "recover"}:
        ordered_names = group.get("plan", {}).get("start_order", []) or fallback_start_order
    elif action == "stop":
        ordered_names = group.get("plan", {}).get("stop_order", []) or fallback_stop_order
    else:
        ordered_names = group.get("plan", {}).get("start_order", []) or fallback_start_order
    for service_name in ordered_names:
        target = member_targets.get(service_name) or dependency_targets.get(service_name)
        if not target:
            continue
        if action == "start":
            _start_server_action_target(config, target)
        elif action == "stop":
            _stop_server_action_target(target)
        elif action == "restart":
            if service_name in dependency_targets:
                _start_server_action_target(config, target)
            else:
                _restart_server_action_target(config, target)
        else:
            _recover_server_action_target(config, target)
    refreshed_inventory = server_inventory_projection(config)
    return {
        "status": manager.status(),
        "servers": refreshed_inventory["servers"],
        "groups": refreshed_inventory["groups"],
    }


@app.post("/api/server-actions/{target_type}/{target_id}/{action}")
def api_server_action(target_type: str, target_id: str, action: str) -> dict[str, Any]:
    if action not in {"start", "stop", "restart", "recover", "adopt", "rebind"}:
        raise HTTPException(status_code=400, detail="Unsupported server action")
    config = load_lab_config()
    target = {"type": target_type, "id": target_id}
    if action == "start":
        _start_server_action_target(config, target)
    elif action == "stop":
        _stop_server_action_target(target)
    elif action == "restart":
        _restart_server_action_target(config, target)
    elif action == "recover":
        _recover_server_action_target(config, target)
    elif action == "adopt":
        _adopt_server_action_target(config, target)
    else:
        _rebind_server_action_target(config, target)
    refreshed_inventory = server_inventory_projection(config)
    return {
        "status": manager.status(),
        "servers": refreshed_inventory["servers"],
        "groups": refreshed_inventory["groups"],
    }


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
    _stop_server_action_target({"type": "service", "id": name})
    return manager.status()


@app.post("/api/stop-kind/{kind}")
def stop_kind(kind: str) -> dict[str, Any]:
    configured_kinds = {service.kind for service in load_lab_config().services.values()}
    if kind not in {"registry", "node", "client", "pilot-node"} | configured_kinds:
        raise HTTPException(status_code=400, detail="Unknown service kind")
    manager.stop_kind(kind)
    return manager.status()


@app.get("/api/links")
def links() -> dict[str, str]:
    return {
        "client": "http://127.0.0.1:8765/",
        "primary_registry": "http://127.0.0.1:8000",
        "secondary_registry": "http://127.0.0.1:8001",
        "backup_registry": "http://127.0.0.1:8002",
        "primary_directory": "http://127.0.0.1:8000/directory?lat=55.6517&lng=12.4126&radius=50",
        "backup_directory": "http://127.0.0.1:8002/directory?lat=55.6517&lng=12.4126&radius=50",
    }
