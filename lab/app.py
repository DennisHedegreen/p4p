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
CLIENT_ROOT = P4P_ROOT / "client"
REGISTRY_ROOT = P4P_ROOT / "registry"
NODE_ROOT = P4P_ROOT / "demo-node"
REGISTRY_PYTHON = REGISTRY_ROOT / ".venv" / "bin" / "python"
NODE_PYTHON = NODE_ROOT / ".venv" / "bin" / "python"


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1, le=25, default=10)


@dataclass
class ManagedProcess:
    name: str
    port: int
    kind: str
    cwd: Path
    command: list[str]
    env: dict[str, str]
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
        if not Path(service.command[0]).exists():
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
        service.logs.append(f"[lab] started {service.name} on port {service.port}")
        return service

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
                "P4P_MENU_ITEM_1_PRICE": str(70 + node_index),
                "P4P_MENU_ITEM_2_PRICE": str(80 + node_index),
            }
        )
        command = [str(NODE_PYTHON), "-m", "uvicorn", "demo_node:app", "--port", str(port)]
        return self._spawn(
            ManagedProcess(
                name=name,
                port=port,
                kind="node",
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
            if service.kind == "node":
                usable, health_status_code, health = self._probe_node_health(service)
            elif service.kind == "client":
                usable, health_status_code, health = self._probe_client_health(service)

            items.append(
                {
                    "name": service.name,
                    "kind": service.kind,
                    "port": service.port,
                    "url": f"http://127.0.0.1:{service.port}/",
                    "operator_url": (
                        f"http://127.0.0.1:{service.port}/operator"
                        if service.kind == "node"
                        else None
                    ),
                    "running": service.is_running(),
                    "usable": usable,
                    "pid": service.process.pid if service.process else None,
                    "started_at": service.started_at,
                    "health_status_code": health_status_code,
                    "health": health,
                    "logs": list(service.logs),
                }
            )
        items.sort(key=lambda item: (item["kind"], item["port"]))
        return {"services": items}


manager = ProcessManager()
app = FastAPI(title="P4P Lab", version="0.1")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
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
    if kind not in {"registry", "node", "client"}:
        raise HTTPException(status_code=400, detail="kind must be registry, node, or client")
    manager.stop_kind(kind)
    return manager.status()


@app.get("/api/links")
def links() -> dict[str, str]:
    return {
        "client": "http://127.0.0.1:8765/",
        "primary_registry": "http://127.0.0.1:8000",
        "backup_registry": "http://127.0.0.1:8002",
    }
