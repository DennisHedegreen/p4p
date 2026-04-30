import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const elements = new Map();
const fetchUrls = [];

function makeElement(tagName = "div") {
  return {
    tagName: tagName.toUpperCase(),
    textContent: "",
    className: "",
    title: "",
    style: {},
    value: "",
    disabled: false,
    children: [],
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    replaceChildren(...children) {
      this.children = [...children];
    },
    addEventListener(type, handler) {
      this[`on${type}`] = handler;
    }
  };
}

function collectText(node) {
  const own = typeof node?.textContent === "string" && node.textContent ? [node.textContent] : [];
  const childText = Array.isArray(node?.children)
    ? node.children.flatMap((child) => collectText(child))
    : [];
  return [...own, ...childText];
}

function findElementByText(node, text) {
  if (node?.textContent === text) {
    return node;
  }
  if (!Array.isArray(node?.children)) {
    return null;
  }
  for (const child of node.children) {
    const found = findElementByText(child, text);
    if (found) {
      return found;
    }
  }
  return null;
}

function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    async json() {
      return payload;
    },
    async text() {
      return JSON.stringify(payload);
    }
  };
}

global.window = {
  P4P_CLIENT_CONFIG: {
    registries: [
      { tier: 0, url: "http://127.0.0.1:8000" },
      { tier: 1, url: "http://127.0.0.1:8002" }
    ]
  },
  setTimeout,
  clearTimeout
};

global.document = {
  getElementById(id) {
    if (!elements.has(id)) {
      elements.set(id, makeElement("div"));
    }
    return elements.get(id);
  },
  createElement(tagName) {
    return makeElement(tagName);
  },
  createTextNode(text) {
    return { textContent: String(text) };
  }
};

Object.defineProperty(globalThis, "navigator", {
  value: {},
  configurable: true
});

global.fetch = async (url) => {
  const requestUrl = String(url);
  fetchUrls.push(requestUrl);

  if (requestUrl.includes("/discover?")) {
    return jsonResponse({
      nodes: [
        {
          node_id: "p4p-node-brondby-demo",
          name: "P4P Demo Pizza",
          city: "Brondby",
          endpoint: "http://127.0.0.1:8101/p4p",
          distance_km: 1.2,
          categories: ["pizza"],
          order_mode: "test",
          modules: ["p4p.payment.cash", "p4p.delivery.pickup"],
          source_kind: "local"
        }
      ],
      registry_version: "0.1",
      query_time: "2026-04-30T13:30:00+02:00"
    });
  }

  if (requestUrl.endsWith("/registry-info")) {
    return jsonResponse({
      registry_url: "http://127.0.0.1:8000",
      backups: [],
      registry_version: "0.1"
    });
  }

  if (requestUrl.includes("/directory?")) {
    return jsonResponse({
      nodes: [
        {
          node_id: "p4p-node-brondby-demo",
          name: "P4P Demo Pizza",
          city: "Brondby",
          endpoint: "http://127.0.0.1:8101/p4p",
          distance_km: 1.2,
          categories: ["pizza"],
          order_mode: "test",
          modules: ["p4p.payment.cash", "p4p.delivery.pickup"],
          source_kind: "local",
          module_declarations: [
            {
              module_id: "p4p.payment.cash",
              provider_id: "p4p.reference",
              version: "0.1",
              status: "active",
              visibility: "public",
              readiness: "live",
              capabilities: ["accept_cash"],
              data_access: ["order_total"],
              customer_notice: "Pay at pickup."
            }
          ],
          undeclared_modules: ["p4p.delivery.pickup"]
        }
      ],
      registry_version: "0.1",
      query_time: "2026-04-30T13:30:01+02:00",
      registry_metadata: {
        registry_type: "local",
        capabilities: {},
        scope: {}
      }
    });
  }

  throw new Error(`unexpected fetch: ${requestUrl}`);
};

elements.set("lat", makeElement("input"));
elements.get("lat").value = "55.6517";
elements.set("lng", makeElement("input"));
elements.get("lng").value = "12.4126";
elements.set("radius", makeElement("input"));
elements.get("radius").value = "10";
elements.set("category", makeElement("input"));
elements.get("category").value = "pizza";

const source = fs.readFileSync(new URL("../client/app.js", import.meta.url), "utf8");
vm.runInThisContext(source, { filename: "app.js" });

const hooks = global.window.__P4PClientTestHooks;
assert.ok(hooks, "test hooks were not exposed");

await hooks.discoverNodes();

assert.ok(fetchUrls.some((url) => url.includes("/discover?")), "discover was not requested");
assert.ok(fetchUrls.some((url) => url.includes("/directory?")), "directory overlay was not requested");

const renderedText = collectText(elements.get("nodes")).join(" | ");
assert.match(renderedText, /p4p\.payment\.cash/);
assert.match(renderedText, /p4p\.delivery\.pickup \(opaque\)/);

const declaredPill = findElementByText(elements.get("nodes"), "p4p.payment.cash");
assert.ok(declaredPill, "declared module pill was not rendered");
assert.match(declaredPill.title, /active • live • public • p4p\.reference/);
