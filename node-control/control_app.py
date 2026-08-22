from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_core import (  # noqa: E402
    HEARTBEAT_TTL_SECONDS,
    PROTOCOL_VERSION,
    build_cors_middleware_options,
    env_float,
    env_list,
    load_registry_urls,
    normalized_registry_url,
    parse_datetime,
    utc_now,
)


@dataclass(frozen=True)
class NodeControlConfig:
    registry_urls: list[str]
    operator_tokens: dict[str, str]
    timeout_seconds: float


def load_node_control_registry_urls() -> list[str]:
    configured = env_list("P4P_NODE_CONTROL_REGISTRY_URLS", [])
    if not configured:
        configured = load_registry_urls()
    deduped: list[str] = []
    seen: set[str] = set()
    for value in configured:
        normalized = normalized_registry_url(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def load_operator_tokens() -> dict[str, str]:
    encoded = os.environ.get("P4P_NODE_CONTROL_OPERATOR_TOKENS", "").strip()
    if not encoded:
        return {}
    payload = json.loads(encoded)
    if not isinstance(payload, dict):
        raise ValueError("P4P_NODE_CONTROL_OPERATOR_TOKENS must be a JSON object")
    normalized: dict[str, str] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if not normalized_key or not normalized_value:
            continue
        normalized[normalized_key] = normalized_value
    return normalized


def build_node_control_config() -> NodeControlConfig:
    return NodeControlConfig(
        registry_urls=load_node_control_registry_urls(),
        operator_tokens=load_operator_tokens(),
        timeout_seconds=min(max(env_float("P4P_NODE_CONTROL_TIMEOUT_SECONDS", 2.0), 0.25), 10.0),
    )


def _error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.ConnectError):
        return str(exc) or "connect_error"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return str(exc) or exc.__class__.__name__


def _node_endpoint_base(endpoint: str) -> str:
    return endpoint.rstrip("/")


def _operator_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _operator_token_for(config: NodeControlConfig, *, node_id: str, endpoint: str) -> str | None:
    return config.operator_tokens.get(node_id) or config.operator_tokens.get(endpoint)


def _fetch_registry_probe(client: httpx.Client, registry_url: str) -> dict[str, Any]:
    probe: dict[str, Any] = {
        "registry_url": registry_url,
        "health": "down",
        "health_reason": "not_checked",
        "health_payload": None,
        "snapshot": None,
        "node_count": 0,
    }
    try:
        response = client.get(f"{registry_url}/health")
        response.raise_for_status()
        payload = response.json()
        probe["health"] = "up"
        probe["health_reason"] = str(payload.get("status") or "ok")
        probe["health_payload"] = payload
    except Exception as exc:
        probe["health_reason"] = _error_text(exc)

    try:
        response = client.get(f"{registry_url}/registry-source")
        response.raise_for_status()
        payload = response.json()
        probe["snapshot"] = payload
        probe["node_count"] = len(payload.get("nodes", []))
        if probe["health"] != "up":
            probe["health"] = "degraded"
            probe["health_reason"] = "registry_source_ok_health_probe_failed"
    except Exception as exc:
        if probe["snapshot"] is None:
            probe["snapshot_error"] = _error_text(exc)
    return probe


def _fetch_node_public_probe(client: httpx.Client, endpoint: str) -> dict[str, Any]:
    base = _node_endpoint_base(endpoint)
    probe: dict[str, Any] = {
        "base_url": base,
        "health": None,
        "info": None,
        "status": "down",
        "status_reason": "not_checked",
    }
    try:
        response = client.get(f"{base}/health")
        payload = response.json()
        probe["health"] = payload
        probe["status"] = str(payload.get("status") or "unknown")
        probe["status_reason"] = f"node_health_http_{response.status_code}"
    except Exception as exc:
        probe["status_reason"] = _error_text(exc)

    try:
        response = client.get(f"{base}/p4p/info")
        response.raise_for_status()
        probe["info"] = response.json()
    except Exception as exc:
        probe["info_error"] = _error_text(exc)
    return probe


def _fetch_node_operator_probe(client: httpx.Client, endpoint: str, token: str | None) -> dict[str, Any]:
    if not token:
        return {
            "access": "not_configured",
            "state": None,
            "modules": None,
        }

    base = _node_endpoint_base(endpoint)
    headers = _operator_headers(token)
    probe: dict[str, Any] = {
        "access": "down",
        "state": None,
        "modules": None,
        "token_source": "configured",
    }
    try:
        state_response = client.get(f"{base}/operator/state", headers=headers)
        state_response.raise_for_status()
        probe["state"] = state_response.json()
    except Exception as exc:
        probe["access"] = "denied_or_unreachable"
        probe["reason"] = _error_text(exc)
        return probe

    try:
        modules_response = client.get(f"{base}/operator/modules", headers=headers)
        modules_response.raise_for_status()
        probe["modules"] = modules_response.json()
        probe["access"] = "ok"
    except Exception as exc:
        probe["access"] = "partial"
        probe["reason"] = _error_text(exc)
    return probe


def _freshness_label(last_seen: str | None) -> str:
    parsed = parse_datetime(last_seen)
    if parsed is None:
        return "unknown"
    age_seconds = (utc_now() - parsed).total_seconds()
    return "fresh" if age_seconds <= HEARTBEAT_TTL_SECONDS else "stale"


def collect_control_snapshot(config: NodeControlConfig | None = None) -> dict[str, Any]:
    effective = config or CONFIG
    checked_at = utc_now().isoformat()
    registries: list[dict[str, Any]] = []
    nodes_by_id: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=effective.timeout_seconds, follow_redirects=True) as client:
        for registry_url in effective.registry_urls:
            probe = _fetch_registry_probe(client, registry_url)
            registries.append(probe)
            snapshot = probe.get("snapshot") or {}
            for entry in snapshot.get("nodes", []):
                node_payload = entry.get("node") or {}
                node_id = str(node_payload.get("node_id") or "").strip()
                endpoint = str(node_payload.get("endpoint") or "").strip()
                if not node_id or not endpoint:
                    continue
                record = nodes_by_id.setdefault(
                    node_id,
                    {
                        "node_id": node_id,
                        "name": str(node_payload.get("name") or node_id),
                        "endpoint": endpoint,
                        "country": str(node_payload.get("country") or ""),
                        "city": str(node_payload.get("city") or ""),
                        "categories": list(node_payload.get("categories") or []),
                        "last_seen": entry.get("last_seen"),
                        "open": node_payload.get("open"),
                        "order_mode": node_payload.get("order_mode"),
                        "modules": list(node_payload.get("modules") or []),
                        "node_public_key": node_payload.get("node_public_key"),
                        "registries": [],
                        "_last_seen_parsed": parse_datetime(entry.get("last_seen")),
                    },
                )
                record["registries"].append(
                    {
                        "registry_url": registry_url,
                        "last_seen": entry.get("last_seen"),
                        "open": node_payload.get("open"),
                        "order_mode": node_payload.get("order_mode"),
                    }
                )
                observed_last_seen = parse_datetime(entry.get("last_seen"))
                current_last_seen = record.get("_last_seen_parsed")
                if observed_last_seen and (current_last_seen is None or observed_last_seen > current_last_seen):
                    record.update(
                        {
                            "name": str(node_payload.get("name") or record["name"]),
                            "endpoint": endpoint,
                            "country": str(node_payload.get("country") or record["country"]),
                            "city": str(node_payload.get("city") or record["city"]),
                            "categories": list(node_payload.get("categories") or record["categories"]),
                            "last_seen": entry.get("last_seen"),
                            "open": node_payload.get("open"),
                            "order_mode": node_payload.get("order_mode"),
                            "modules": list(node_payload.get("modules") or record["modules"]),
                            "node_public_key": node_payload.get("node_public_key") or record["node_public_key"],
                            "_last_seen_parsed": observed_last_seen,
                        }
                    )

        nodes: list[dict[str, Any]] = []
        for node_id, record in nodes_by_id.items():
            token = _operator_token_for(effective, node_id=node_id, endpoint=record["endpoint"])
            public_probe = _fetch_node_public_probe(client, record["endpoint"])
            operator_probe = _fetch_node_operator_probe(client, record["endpoint"], token)
            operator_state = operator_probe.get("state") or {}
            operator_modules = operator_probe.get("modules") or {}
            module_entries = list(operator_modules.get("modules") or [])
            health_counts: dict[str, int] = {}
            for module in module_entries:
                health_key = str(module.get("health") or "unknown")
                health_counts[health_key] = health_counts.get(health_key, 0) + 1

            registry_state = operator_state.get("registry") or {}
            active_by_lane = operator_modules.get("active_by_lane") or operator_state.get("active_by_lane") or {}
            nodes.append(
                {
                    "node_id": node_id,
                    "name": record["name"],
                    "endpoint": record["endpoint"],
                    "country": record["country"],
                    "city": record["city"],
                    "categories": record["categories"],
                    "last_seen": record["last_seen"],
                    "freshness": _freshness_label(record["last_seen"]),
                    "open": record["open"],
                    "order_mode": record["order_mode"],
                    "registry_observations": record["registries"],
                    "observed_by": len(record["registries"]),
                    "announced_modules": record["modules"],
                    "public_probe": public_probe,
                    "operator_probe": operator_probe,
                    "hardware": operator_state.get("hardware") or {},
                    "enabled_modules": operator_state.get("enabled_modules") or [],
                    "public_modules": operator_state.get("public_modules") or [],
                    "undeclared_modules": operator_state.get("undeclared_modules") or operator_modules.get("undeclared_modules") or [],
                    "active_by_lane": active_by_lane,
                    "module_health_counts": health_counts,
                    "module_entries": module_entries,
                    "registry_state": registry_state,
                }
            )

    nodes.sort(
        key=lambda entry: (
            0 if entry["public_probe"]["status"] == "ready" else 1,
            0 if entry["freshness"] == "fresh" else 1,
            entry["name"].lower(),
        )
    )
    reachable_registries = sum(1 for probe in registries if probe.get("snapshot") is not None)
    ready_nodes = sum(1 for entry in nodes if entry["public_probe"]["status"] == "ready")
    operator_nodes = sum(1 for entry in nodes if entry["operator_probe"]["access"] in {"ok", "partial"})
    return {
        "checked_at": checked_at,
        "config": {
            "registry_urls": effective.registry_urls,
            "timeout_seconds": effective.timeout_seconds,
        },
        "summary": {
            "configured_registries": len(effective.registry_urls),
            "reachable_registries": reachable_registries,
            "unique_nodes": len(nodes),
            "ready_nodes": ready_nodes,
            "operator_visible_nodes": operator_nodes,
        },
        "registries": registries,
        "nodes": nodes,
    }


def node_detail(snapshot: dict[str, Any], node_id: str) -> dict[str, Any]:
    for entry in snapshot.get("nodes", []):
        if entry["node_id"] == node_id:
            return entry
    raise HTTPException(status_code=404, detail=f"Unknown node_id: {node_id}")


def _health_badge(label: str, *, tone: str) -> str:
    return f'<span class="badge badge-{escape(tone)}">{escape(label)}</span>'


def _node_status_badges(node: dict[str, Any]) -> str:
    badges = [
        _health_badge(str(node["public_probe"]["status"]), tone="good" if node["public_probe"]["status"] == "ready" else "warn"),
        _health_badge(str(node["freshness"]), tone="good" if node["freshness"] == "fresh" else "warn"),
        _health_badge(f'operator {node["operator_probe"]["access"]}', tone="muted" if node["operator_probe"]["access"] == "not_configured" else "good"),
    ]
    return " ".join(badges)


def _render_registry_cards(snapshot: dict[str, Any]) -> str:
    cards: list[str] = []
    for registry in snapshot.get("registries", []):
        tone = "good" if registry.get("snapshot") is not None else "warn"
        cards.append(
            f"""<article class="registry-card">
  <div class="row-line">
    <h3>{escape(registry["registry_url"])}</h3>
    {_health_badge(registry.get("health", "unknown"), tone=tone)}
  </div>
  <p>{escape(str(registry.get("health_reason") or ""))}</p>
  <p><strong>Nodes seen:</strong> {registry.get("node_count", 0)}</p>
</article>"""
        )
    return "\n".join(cards) or "<p>No registries configured.</p>"


def _render_node_rows(snapshot: dict[str, Any], *, selected_node_id: str | None) -> str:
    rows: list[str] = []
    for node in snapshot.get("nodes", []):
        active = ' class="selected"' if node["node_id"] == selected_node_id else ""
        payment_module = str(node.get("active_by_lane", {}).get("payment") or "-")
        rows.append(
            f"""<tr{active}>
  <td><a href="/?node_id={quote(node["node_id"])}">{escape(node["name"])}</a><div class="muted"><code>{escape(node["node_id"])}</code></div></td>
  <td>{escape(node["city"] or "-")}</td>
  <td>{_node_status_badges(node)}</td>
  <td>{escape(str(node["order_mode"] or "-"))}</td>
  <td>{node["observed_by"]}</td>
  <td>{escape(payment_module)}</td>
</tr>"""
        )
    return "\n".join(rows) or '<tr><td colspan="6">No nodes visible yet.</td></tr>'


def _render_selected_node(node: dict[str, Any] | None) -> str:
    if node is None:
        return "<p>Select a node to inspect health, registry truth, and module state.</p>"

    module_entries = node.get("module_entries") or []
    module_items = "\n".join(
        f"""<tr>
  <td><code>{escape(str(entry.get("module_id") or "-"))}</code></td>
  <td>{escape(str(entry.get("lane") or "-"))}</td>
  <td>{_health_badge(str(entry.get("health") or "unknown"), tone="good" if entry.get("health") in {"up", "available"} else "warn")}</td>
  <td>{escape(str(entry.get("implementation") or "-"))}</td>
</tr>"""
        for entry in module_entries
    ) or '<tr><td colspan="4">No operator module detail available.</td></tr>'

    registry_rows = "\n".join(
        f"""<li><code>{escape(str(item.get("registry_url") or "-"))}</code> seen at {escape(str(item.get("last_seen") or "-"))}</li>"""
        for item in node.get("registry_observations", [])
    ) or "<li>No registry observations.</li>"

    registry_state = node.get("registry_state") or {}
    module_counts = node.get("module_health_counts") or {}
    counts_text = ", ".join(f"{key}: {value}" for key, value in sorted(module_counts.items())) or "No module health counts yet."
    operator_probe = node.get("operator_probe") or {}
    public_probe = node.get("public_probe") or {}
    hardware = node.get("hardware") if isinstance(node.get("hardware"), dict) else {}
    hardware_profile = str(hardware.get("profile") or "-")
    hardware_customized = hardware.get("customized")
    hardware_print = hardware.get("print") if isinstance(hardware.get("print"), dict) else {}
    hardware_backup = hardware.get("backup_print") if isinstance(hardware.get("backup_print"), dict) else {}
    hardware_alert = hardware.get("alert") if isinstance(hardware.get("alert"), dict) else {}
    hardware_pickup = hardware.get("pickup_board") if isinstance(hardware.get("pickup_board"), dict) else {}
    active_payment = str(node.get("active_by_lane", {}).get("payment") or "-")
    public_health_payload = public_probe.get("health") if isinstance(public_probe.get("health"), dict) else {}
    public_info_payload = public_probe.get("info") if isinstance(public_probe.get("info"), dict) else {}
    accepts_orders = public_health_payload.get("accepts_orders")
    if accepts_orders is None:
        accepts_orders = public_info_payload.get("accepts_orders")

    return f"""
<section class="detail-card">
  <div class="row-line">
    <div>
      <p class="eyebrow">Selected node</p>
      <h2>{escape(node["name"])}</h2>
      <p><code>{escape(node["node_id"])}</code></p>
    </div>
    <div class="badges">{_node_status_badges(node)}</div>
  </div>
  <p><strong>Endpoint:</strong> <code>{escape(node["endpoint"])}</code></p>
  <p><strong>Mode:</strong> {escape(str(node["order_mode"] or "-"))} / <strong>Open:</strong> {escape(str(node["open"]))} / <strong>Accepts orders:</strong> {escape("-" if accepts_orders is None else str(accepts_orders))}</p>
  <p><strong>Observed by:</strong> {node["observed_by"]} registries / <strong>Last seen:</strong> {escape(str(node.get("last_seen") or "-"))}</p>
  <p><strong>Active payment lane:</strong> {escape(active_payment)}</p>
  <p><strong>Module health counts:</strong> {escape(counts_text)}</p>
  <p><strong>Node registry view:</strong> ready={escape(str(registry_state.get("ready")))} / registered={escape(str(len(registry_state.get("registered_registries") or [])))} / failed={escape(str(len((registry_state.get("failed_registries") or {}).keys())))} </p>
  <p><strong>Hardware profile:</strong> {escape(hardware_profile)} / <strong>Customized:</strong> {escape("-" if hardware_customized is None else str(hardware_customized))}</p>
  <p><strong>Primary print:</strong> {escape(str(hardware_print.get("driver") or "-"))} -> {escape(str(hardware_print.get("target") or "-"))} / <strong>Sensor:</strong> {escape(str(hardware_print.get("sensor_source") or "-"))}</p>
  <p><strong>Backup print:</strong> {escape(str(hardware_backup.get("driver") or "-"))} -> {escape(str(hardware_backup.get("target") or "-"))} / <strong>Alert:</strong> {escape(str(hardware_alert.get("target") or "-"))} ({escape(str(hardware_alert.get("mode") or "-"))}) / <strong>Pickup board:</strong> {escape(str(hardware_pickup.get("target") or "-"))}</p>
  <p><strong>Operator access:</strong> {escape(str(operator_probe.get("access") or "not_configured"))}</p>
</section>

<section class="detail-grid">
  <article class="detail-card">
    <h3>Registry observations</h3>
    <ul>{registry_rows}</ul>
  </article>
  <article class="detail-card">
    <h3>Public node health</h3>
    <pre>{escape(json.dumps(public_probe, indent=2, sort_keys=True))}</pre>
  </article>
</section>

<section class="detail-card">
  <h3>Module view</h3>
  <table>
    <thead><tr><th>Module</th><th>Lane</th><th>Health</th><th>Implementation</th></tr></thead>
    <tbody>{module_items}</tbody>
  </table>
</section>"""


def dashboard_html(snapshot: dict[str, Any], *, selected_node_id: str | None = None) -> str:
    selected = None
    if selected_node_id:
        for node in snapshot.get("nodes", []):
            if node["node_id"] == selected_node_id:
                selected = node
                break
    if selected is None and snapshot.get("nodes"):
        selected = snapshot["nodes"][0]
        selected_node_id = selected["node_id"]

    summary = snapshot.get("summary", {})
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>P4P Node Control</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #0d1117;
        --panel: #151b23;
        --panel-2: #1c2430;
        --line: #2d3644;
        --text: #f6efe2;
        --muted: #9ca7b8;
        --good: #6edb8f;
        --warn: #f0c36b;
        --bad: #ef6a6a;
        --link: #8dc7ff;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: var(--bg);
        color: var(--text);
      }}
      main {{
        max-width: 1200px;
        margin: 0 auto;
        padding: 32px 20px 80px;
      }}
      a {{ color: var(--link); text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
      h1, h2, h3, p {{ margin-top: 0; }}
      .eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--warn);
        font-size: 0.8rem;
      }}
      .hero, .detail-card, .summary-card, .registry-card {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 18px;
      }}
      .hero {{ padding: 24px; margin-bottom: 20px; }}
      .summary-grid, .registry-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin: 18px 0 20px;
      }}
      .summary-card, .registry-card, .detail-card {{ padding: 16px; }}
      .layout {{
        display: grid;
        grid-template-columns: minmax(320px, 460px) minmax(0, 1fr);
        gap: 18px;
        align-items: start;
      }}
      .row-line {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: start;
      }}
      .badges {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
      .badge {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid var(--line);
        font-size: 0.78rem;
      }}
      .badge-good {{ color: var(--good); }}
      .badge-warn {{ color: var(--warn); }}
      .badge-muted {{ color: var(--muted); }}
      .muted {{ color: var(--muted); font-size: 0.9rem; margin-top: 4px; }}
      table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.95rem;
      }}
      th, td {{
        text-align: left;
        border-top: 1px solid var(--line);
        padding: 10px 8px;
        vertical-align: top;
      }}
      th:first-child, td:first-child {{ padding-left: 0; }}
      tr.selected {{ background: color-mix(in srgb, var(--panel-2) 76%, transparent); }}
      pre {{
        white-space: pre-wrap;
        word-break: break-word;
        background: var(--panel-2);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 12px;
        overflow-x: auto;
      }}
      .detail-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 16px;
        margin: 16px 0;
      }}
      @media (max-width: 960px) {{
        .layout {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <p class="eyebrow">Node control / local control plane</p>
        <h1>P4P Node Control</h1>
        <p>This is a local control surface above registries and nodes. It reads registry truth, public node health, and optional operator state. It does not move restaurant control into the registry.</p>
        <p class="muted">Checked at {escape(str(snapshot.get("checked_at") or "-"))}. Protocol {escape(PROTOCOL_VERSION)}.</p>
      </section>

      <section class="summary-grid">
        <article class="summary-card"><p class="eyebrow">Registries</p><h2>{summary.get("configured_registries", 0)}</h2><p>{summary.get("reachable_registries", 0)} reachable now.</p></article>
        <article class="summary-card"><p class="eyebrow">Nodes</p><h2>{summary.get("unique_nodes", 0)}</h2><p>{summary.get("ready_nodes", 0)} report ready.</p></article>
        <article class="summary-card"><p class="eyebrow">Operator view</p><h2>{summary.get("operator_visible_nodes", 0)}</h2><p>Nodes with token-backed operator detail.</p></article>
      </section>

      <section class="registry-grid">
        {_render_registry_cards(snapshot)}
      </section>

      <section class="layout">
        <article class="detail-card">
          <div class="row-line">
            <div>
              <p class="eyebrow">Fleet view</p>
              <h2>Choose a node</h2>
            </div>
            <div class="muted">Registry truth stays narrow.</div>
          </div>
          <table>
            <thead>
              <tr><th>Node</th><th>City</th><th>Status</th><th>Mode</th><th>Seen by</th><th>Payment</th></tr>
            </thead>
            <tbody>
              {_render_node_rows(snapshot, selected_node_id=selected_node_id)}
            </tbody>
          </table>
        </article>
        <div>
          {_render_selected_node(selected)}
        </div>
      </section>
    </main>
  </body>
</html>"""


CONFIG = build_node_control_config()


def build_app(config: NodeControlConfig) -> FastAPI:
    app = FastAPI(
        title="P4P Node Control",
        version=PROTOCOL_VERSION,
        summary="Local multi-node control plane for reading registry and node truth without moving authority into the registry.",
    )
    app.add_middleware(CORSMiddleware, **build_cors_middleware_options())

    @app.get("/health")
    def health(response: Response) -> dict[str, Any]:
        snapshot = collect_control_snapshot(config)
        ready = snapshot["summary"]["reachable_registries"] > 0
        response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if ready else "not_ready",
            "service": "p4p-node-control",
            "protocol_version": PROTOCOL_VERSION,
            **snapshot["summary"],
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        return collect_control_snapshot(config)

    @app.get("/api/nodes/{node_id}")
    def node_api(node_id: str) -> dict[str, Any]:
        snapshot = collect_control_snapshot(config)
        return node_detail(snapshot, node_id)

    @app.get("/", response_class=HTMLResponse)
    def root(node_id: str | None = Query(default=None)) -> str:
        snapshot = collect_control_snapshot(config)
        return dashboard_html(snapshot, selected_node_id=node_id)

    return app


app = build_app(CONFIG)


__all__ = [
    "CONFIG",
    "NodeControlConfig",
    "app",
    "build_app",
    "build_node_control_config",
    "collect_control_snapshot",
    "dashboard_html",
    "node_detail",
]
