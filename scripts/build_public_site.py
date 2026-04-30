from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P4P_ROOT = ROOT / "P4P"
SITE_DATA_PATH = ROOT / "private/data/p4p/site-data.json"
PUBLIC_ROOT = ROOT / "public/www/pizza4people"
PRESS_ROOT = PUBLIC_ROOT / "press-kit"
MODULES_ROOT = P4P_ROOT / "modules"
TEMPLATE_ROOT = P4P_ROOT / "scripts/templates/public-site"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, str]) -> str:
    rendered = load_text(TEMPLATE_ROOT / name)
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", rendered)))
    if unresolved:
        raise ValueError(f"Unresolved template placeholders in {name}: {', '.join(unresolved)}")
    return rendered


def load_site_data() -> dict:
    return load_json(SITE_DATA_PATH)


def load_modules() -> list[dict]:
    modules: list[dict] = []
    for manifest_path in sorted(MODULES_ROOT.glob("*/module.json")):
        payload = load_json(manifest_path)
        public_catalog = payload.get("public_catalog", {})
        modules.append(
            {
                "module_id": payload["module_id"],
                "provider_id": payload["provider_id"],
                "description": payload["description"],
                "function": public_catalog.get("function", payload["description"]),
                "data_access": public_catalog.get(
                    "data_access_summary",
                    ", ".join(payload.get("data_access", [])) or "Not declared yet.",
                ),
                "trust_status": public_catalog.get("trust_status", payload["status"]),
                "readiness": public_catalog.get("readiness", payload["status"]),
                "operator_status": public_catalog.get("operator_status", "not enabled"),
            }
        )
    return modules


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def module_catalog_payload(site_data: dict, modules: list[dict]) -> dict:
    return {
        "catalog_name": "Pizza4People Module Catalog",
        "catalog_status": "generated from module manifests",
        "generated_at": site_data["generated_at"],
        "modules": [
            {
                "module_id": entry["module_id"],
                "provider_id": entry["provider_id"],
                "function": entry["function"],
                "data_access": entry["data_access"],
                "trust_status": entry["trust_status"],
                "readiness": entry["readiness"],
                "operator_status": entry["operator_status"],
            }
            for entry in modules
        ],
    }


def render_press_facts(facts: list[dict], urls: dict) -> str:
    items = []
    for fact in facts:
        body = escape(fact["body"])
        body = body.replace("Danish", '<a href="press-kit/">Danish</a>')
        body = body.replace("English", '<a href="press-kit/en.html">English</a>')
        body = body.replace("proof site", f'<a href="{escape(urls["site"])}">proof site</a>')
        body = body.replace("public repo", f'<a href="{escape(urls["repo"])}">public repo</a>')
        body = body.replace("public main repo", f'<a href="{escape(urls["repo"])}">public main repo</a>')
        body = body.replace("repo README", f'<a href="{escape(urls["repo_readme"])}">repo README</a>')
        body = body.replace("proof note", f'<a href="{escape(urls["repo_proof"])}">proof note</a>')
        body = body.replace("SPEC.md", f'<a href="{escape(urls["repo_spec"])}">SPEC.md</a>')
        body = body.replace(
            "release notes",
            f'<a href="{escape(urls["repo_release_notes"])}">release notes</a>',
        )
        items.append(
            f"""        <article>
          <h3>{escape(fact["title"])}</h3>
          <p>{body}</p>
        </article>"""
        )
    return "\n".join(items)


def render_plain_cards(items: list[dict]) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            f"""        <article class="plain-card">
          <span class="plain-number">{index}</span>
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_proof_steps(items: list[dict]) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            f"""        <article class="proof-step">
          <span class="step-number">{index:02d}</span>
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_list_items(items: list[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    inner = "\n".join(f"          <li>{escape(item)}</li>" for item in items)
    return f"<{tag}>\n{inner}\n        </{tag}>"


def render_modules(modules: list[dict]) -> str:
    cards = []
    for entry in modules:
        live_class = " module-live" if entry["readiness"] in {"test", "live"} else ""
        cards.append(
            f"""        <article class="module-card{live_class}">
          <div class="module-head">
            <h3>{escape(entry["module_id"])}</h3>
            <span>{escape(entry["readiness"])}</span>
          </div>
          <p>{escape(entry["function"])}</p>
          <dl>
            <div><dt>Provider</dt><dd>{escape(entry["provider_id"])}</dd></div>
            <div><dt>Data</dt><dd>{escape(entry["data_access"])}</dd></div>
            <div><dt>Trust</dt><dd>{escape(entry["trust_status"])}</dd></div>
            <div><dt>Operator</dt><dd>{escape(entry["operator_status"])}</dd></div>
          </dl>
        </article>"""
        )
    return "\n".join(cards)


def render_trace(items: list[str]) -> str:
    return "\n".join(f'          <span role="listitem">{escape(item)}</span>' for item in items)


def render_gate(items: list[dict]) -> str:
    rendered = []
    for item in items:
        checked = " checked" if item["done"] else ""
        rendered.append(
            f'        <label><input type="checkbox"{checked} disabled> {escape(item["label"])}</label>'
        )
    return "\n".join(rendered)


def render_roadmap(items: list[str]) -> str:
    rows = []
    for item in items:
        number, body = item.split(". ", 1)
        rows.append(f"        <li><strong>{escape(number)}.</strong> {escape(body)}</li>")
    return "\n".join(rows)


def render_press_badges(labels: list[str]) -> str:
    output = []
    for label in labels:
        badge_class = " warn" if "Ikke" in label or "Not" in label else ""
        output.append(f'            <span class="badge{badge_class}">{escape(label)}</span>')
    return "\n".join(output)


def render_press_points(points: list[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    inner = "\n".join(f"            <li>{escape(point)}</li>" for point in points)
    return f"<{tag}>\n{inner}\n          </{tag}>"


def render_press_angles(items: list[dict]) -> str:
    cards = []
    for item in items:
        cards.append(
            f"""        <div class="card">
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </div>"""
        )
    return "\n".join(cards)


def homepage_html(site_data: dict, modules: list[dict]) -> str:
    home = site_data["homepage"]
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    return render_template(
        "homepage.html",
        {
            "generated_comment": f"Generated from private/data/p4p/site-data.json and P4P/modules on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "site_url": escape(urls["site"]),
            "hero_eyebrow": escape(home["eyebrow"]),
            "hero_title": escape(home["title"]),
            "hero_lede": escape(home["lede"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "notice": escape(home["notice"]),
            "just_eat_source_url": escape(urls["just_eat_source"]),
            "press_heading": escape(home["press_heading"]),
            "press_lede": escape(home["press_lede"]),
            "press_facts_html": render_press_facts(home["press_facts"], urls),
            "story_heading": escape(home["story_heading"]),
            "story_body": escape(home["story_body"]),
            "one_sentence": escape(home["one_sentence"]),
            "plain_cards_html": render_plain_cards(home["plain_demo"]),
            "problem_heading": escape(home["problem_heading"]),
            "problem_body_1": escape(home["problem_body"][0]),
            "problem_body_2": escape(home["problem_body"][1]),
            "proof_steps_html": render_proof_steps(home["proof_steps"]),
            "takeaway_heading": escape(home["takeaway_heading"]),
            "takeaway_body": escape(home["takeaway_body"]),
            "proves_list_html": render_list_items(home["proves"]),
            "does_not_prove_list_html": render_list_items(home["does_not_prove"]),
            "trust_heading": escape(home["trust_heading"]),
            "trust_body": escape(home["trust_body"]),
            "trace_html": render_trace(home["trace"]),
            "modules_html": render_modules(modules),
            "proof_gate_heading": escape(home["proof_gate_heading"]),
            "gate_html": render_gate(home["proof_gate"]),
            "roadmap_html": render_roadmap(home["roadmap"]),
            "contact_email": escape(contact["email"]),
            "footer_status": escape(home["footer_status"]),
        },
    )


def press_kit_html(site_data: dict, modules: list[dict], *, lang: str) -> str:
    data = site_data["press_kit"][lang]
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    is_dk = lang == "dk"
    return render_template(
        "press-kit.html",
        {
            "lang_attr": "da" if is_dk else "en",
            "author_name": escape(contact["name"]),
            "page_title": escape("Pizza4People Pressekit" if is_dk else "Pizza4People Press Kit"),
            "page_description": escape(
                "Kort pressekit for Pizza4People: et offentligt open-protocol proof for direkte restaurant-kunde discovery og ordering."
                if is_dk
                else "Press kit for Pizza4People: an open protocol proof for direct restaurant-customer discovery and ordering."
            ),
            "canonical_url": escape(urls["press_kit_dk"] if is_dk else urls["press_kit_en"]),
            "press_style": load_text(TEMPLATE_ROOT / "press-style.css").strip(),
            "topbar_label": escape(data["topbar_label"]),
            "date_label": escape(data["date_label"]),
            "kicker": escape(data["kicker"]),
            "headline": escape(data["headline"]),
            "lede": escape(data["lede"]),
            "badges_html": render_press_badges(data["badges"]),
            "quote": escape(data["quote"]),
            "other_lang_link": escape("en.html" if is_dk else "index.html"),
            "other_lang_label": escape("English version" if is_dk else "Dansk version"),
            "contact_name": escape(contact["name"]),
            "contact_org": escape(contact["org"]),
            "contact_email": escape(contact["email"]),
            "why_now_label": escape("Hvorfor nu" if is_dk else "Why now"),
            "why_now_heading": escape(data["why_now_heading"]),
            "why_now_body_html": "\n".join(
                f"          <p>{escape(paragraph)}</p>" for paragraph in data["why_now_body"]
            ),
            "journalist_box_label": escape(
                "Hvad en journalist kan skrive nu" if is_dk else "What can be written now"
            ),
            "journalist_bullets_html": render_press_points(data["journalist_bullets"]),
            "source_note": escape(data["source_note"]),
            "system_label": escape("Systemet på én side" if is_dk else "System in one page"),
            "system_heading": escape(data["system_heading"]),
            "client_flow_text": escape(
                "Finder restauranter, viser menu, sender ordre."
                if is_dk
                else "Finds restaurants, renders menus, sends orders."
            ),
            "registry_flow_text": escape(
                "Discovery, heartbeat, offentlig node-metadata."
                if is_dk
                else "Discovery, heartbeat and public node metadata."
            ),
            "node_flow_label": escape("Restaurant node" if is_dk else "Restaurant node"),
            "node_flow_text": escape(
                "Menu, ordreendpoint, status, identitet og operator-kontrol."
                if is_dk
                else "Menu, order endpoint, status, identity and operator control."
            ),
            "flow_caption": escape(
                "Registry bruges til discovery. Menu og ordre går direkte fra client til restaurant node."
                if is_dk
                else "Registry is used for discovery. Menu and order flow go directly from client to restaurant node."
            ),
            "layers_label": escape("Lagene" if is_dk else "Layers"),
            "layers_heading": escape(data["layers_heading"]),
            "module_cards_html": render_modules(modules),
            "status_label": escape("Nuværende status" if is_dk else "Current status"),
            "status_heading": escape(data["status_heading"]),
            "current_status_title": escape(data["current_status_title"]),
            "current_status_items_html": render_press_points(data["current_status_items"]),
            "next_test_title": escape(data["next_test_title"]),
            "next_test_items_html": render_press_points(data["next_test_items"], ordered=True),
            "primary_registry_text": escape(
                "Første discovery-endpoint." if is_dk else "First discovery endpoint."
            ),
            "backup_registry_text": escape(
                "Separat server, så discovery kan failover."
                if is_dk
                else "Separate server for discovery failover."
            ),
            "pilot_node_label": escape("Restaurant-owned node"),
            "pilot_node_text": escape(
                "Menu, order mode, order state og operator-kontrol."
                if is_dk
                else "Menu, order mode, order state and operator control."
            ),
            "pilot_client_text": escape(
                "Finder via registry. Taler direkte med node efter discovery."
                if is_dk
                else "Finds via registry. Talks directly to node after discovery."
            ),
            "verification_label": escape("Teknisk verifikation" if is_dk else "Technical verification"),
            "verification_heading": escape(data["verification_heading"]),
            "verification_body_html": "\n".join(
                f"          <p>{escape(paragraph)}</p>"
                for paragraph in data["verification_body"]
            ),
            "press_angles_label": escape("Pressevinkler" if is_dk else "Press angles"),
            "press_angles_heading": escape(data["press_angles_heading"]),
            "press_angles_html": render_press_angles(data["press_angles"]),
            "site_url": escape(urls["site"]),
            "umbrella_url": escape(urls["umbrella"]),
            "repo_url": escape(urls["repo"]),
            "just_eat_source_url": escape(urls["just_eat_source"]),
            "status_line": escape(data["status_line"]),
        },
    )


def build() -> None:
    site_data = load_site_data()
    modules = load_modules()
    write_text(
        PUBLIC_ROOT / "modules.json",
        json.dumps(module_catalog_payload(site_data, modules), indent=2) + "\n",
    )
    write_text(PUBLIC_ROOT / "index.html", homepage_html(site_data, modules))
    write_text(PRESS_ROOT / "index.html", press_kit_html(site_data, modules, lang="dk"))
    write_text(PRESS_ROOT / "en.html", press_kit_html(site_data, modules, lang="en"))


if __name__ == "__main__":
    build()
