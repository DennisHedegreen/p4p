const DEFAULT_REGISTRIES = [
  { tier: 0, url: "http://127.0.0.1:8000" },
  { tier: 1, url: "http://127.0.0.1:8002" }
];

let registries = [];
let pinnedRegistries = [];

let activeRegistry = null;
let selectedNode = null;

const registryStatusEl = document.getElementById("registry-status");
const nodesEl = document.getElementById("nodes");
const menuEl = document.getElementById("menu");
const selectedNodeEl = document.getElementById("selected-node");
const logEl = document.getElementById("log");
const orderStatusEl = document.getElementById("order-status");
const placeOrderButton = document.getElementById("place-order");

function setLog(value) {
  logEl.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function setRegistryStatus(message) {
  registryStatusEl.textContent = `Registry status: ${message}`;
}

function safeText(value, fallback = "") {
  if (value === null || value === undefined) {
    return fallback;
  }
  return String(value);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function appendBreak(parent) {
  parent.appendChild(document.createElement("br"));
}

function appendStrong(parent, value) {
  const element = document.createElement("strong");
  element.textContent = safeText(value);
  parent.appendChild(element);
  return element;
}

function appendPill(parent, value) {
  const element = document.createElement("span");
  element.className = "pill";
  element.textContent = safeText(value);
  parent.appendChild(element);
  return element;
}

function appendStatus(parent, value, options = {}) {
  const element = document.createElement(options.block ? "div" : "span");
  element.className = "status";
  element.textContent = safeText(value);
  if (options.marginTop) {
    element.style.marginTop = options.marginTop;
  }
  parent.appendChild(element);
  return element;
}

function appendEmptyStatus(parent, value) {
  const element = document.createElement("p");
  element.className = "status";
  element.textContent = value;
  parent.appendChild(element);
}

function getOrderMode(node) {
  return node?.order_mode || "disabled";
}

function nodeAcceptsOrders(node) {
  return ["test", "live"].includes(getOrderMode(node));
}

function orderModeLabel(node) {
  const mode = getOrderMode(node);
  if (mode === "live") {
    return "Order: live";
  }
  if (mode === "test") {
    return "Order: test only";
  }
  if (mode === "menu_only") {
    return "Menu only";
  }
  return "Orders disabled";
}

function nodeIdentityLabel(node) {
  if (node?.delegation?.role === "backup") {
    return "Delegated backup node";
  }
  if (node?.delegation?.role === "primary") {
    return "Delegated primary node";
  }
  return node?.node_public_key ? "Signed node" : "Unsigned node";
}

function discoverySourceLabel(node) {
  if (node?.source_kind === "mirrored") {
    const upstream = typeof node.source_registry_url === "string" ? node.source_registry_url : "upstream registry";
    const relay = typeof node.source_relay_registry_url === "string" ? node.source_relay_registry_url : null;
    const basis = node.source_discovery_basis === "trusted_upstream"
      ? "trusted"
      : node.source_discovery_basis === "trusted_relayed_upstream"
        ? "trusted-relay"
        : node.source_discovery_basis === "manual_override_allow"
          ? "manual-allow"
        : node.source_discovery_basis === "all_active_policy"
          ? "active-policy"
          : "mirrored";
    const freshness = node.source_freshness_state === "stale" ? "stale" : "fresh";
    if (node.source_signature_verified === false) {
      return relay
        ? `Mirrored: ${basis}, ${freshness}, unsigned ${upstream} via ${relay}`
        : `Mirrored: ${basis}, ${freshness}, unsigned ${upstream}`;
    }
    return relay
      ? `Mirrored: ${basis}, ${freshness}, ${upstream} via ${relay}`
      : `Mirrored: ${basis}, ${freshness}, ${upstream}`;
  }
  return "Local registry node";
}

function updateOrderControls() {
  if (!selectedNode) {
    placeOrderButton.disabled = true;
    orderStatusEl.textContent = "Select a node before placing an order.";
    return;
  }

  if (!nodeAcceptsOrders(selectedNode)) {
    placeOrderButton.disabled = true;
    orderStatusEl.textContent = `${selectedNode.name} is discoverable, but does not accept orders in ${getOrderMode(selectedNode)} mode.`;
    return;
  }

  placeOrderButton.disabled = false;
  orderStatusEl.textContent =
    getOrderMode(selectedNode) === "test"
      ? "This node accepts test orders only."
      : "This node accepts live orders.";
}

function normalizeRegistryUrl(url) {
  if (typeof url !== "string") {
    return null;
  }

  const trimmed = url.trim();
  if (!trimmed) {
    return null;
  }

  return trimmed.replace(/\/+$/, "");
}

function buildRegistryUrl(registry, path) {
  const baseUrl = normalizeRegistryUrl(registry?.url);
  const nextPath = path.startsWith("/") ? path : `/${path}`;

  if (!baseUrl) {
    throw new Error("Registry entry is missing a usable base URL");
  }

  return `${baseUrl}${nextPath}`;
}

function normalizeRegistries(entries) {
  const seen = new Set();
  const normalized = [];

  for (const entry of entries || []) {
    const normalizedUrl = normalizeRegistryUrl(entry?.url);
    const numericTier = Number(entry?.tier);
    if (!normalizedUrl || seen.has(normalizedUrl)) {
      continue;
    }
    normalized.push({
      tier: Number.isInteger(numericTier) && numericTier >= 0 ? numericTier : normalized.length,
      url: normalizedUrl
    });
    seen.add(normalizedUrl);
  }

  return normalized.sort((left, right) => left.tier - right.tier);
}

function mergeAdvisoryRegistries(pinnedEntries, advisoryEntries, registryUrl) {
  const merged = [];
  const seen = new Set();

  const append = (entry) => {
    const normalizedUrl = normalizeRegistryUrl(entry?.url);
    const numericTier = Number(entry?.tier);
    if (!normalizedUrl || seen.has(normalizedUrl)) {
      return;
    }
    merged.push({
      tier: Number.isInteger(numericTier) && numericTier >= 0 ? numericTier : merged.length,
      url: normalizedUrl
    });
    seen.add(normalizedUrl);
  };

  for (const entry of normalizeRegistries(pinnedEntries)) {
    append(entry);
  }

  if (registryUrl) {
    append({ tier: merged.length, url: registryUrl });
  }

  for (const entry of normalizeRegistries(advisoryEntries)) {
    append(entry);
  }

  return merged;
}

function loadInitialRegistries() {
  const configured = window.P4P_CLIENT_CONFIG?.registries;
  const normalized = normalizeRegistries(configured);
  return normalized.length ? normalized : normalizeRegistries(DEFAULT_REGISTRIES);
}

async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => "");
      throw new Error(`HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
    }

    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`timeout after ${timeoutMs / 1000}s`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function refreshRegistryList(registry) {
  try {
    const info = await fetchJsonWithTimeout(buildRegistryUrl(registry, "/registry-info"));
    const nextRegistries = mergeAdvisoryRegistries(
      pinnedRegistries,
      info.backups,
      info.registry_url
    );
    if (nextRegistries.length) {
      registries = nextRegistries;
    }
  } catch (error) {
    setRegistryStatus(`using ${registry.url}, but registry-info refresh failed`);
  }
}

async function fetchWithFailover(path, options = {}) {
  let lastError = null;
  const failures = [];

  for (let index = 0; index < registries.length; index += 1) {
    const registry = registries[index];
    const registryUrl = normalizeRegistryUrl(registry.url) || String(registry.url || "");
    try {
      const payload = await fetchJsonWithTimeout(buildRegistryUrl(registry, path), options);
      activeRegistry = registry;
      await refreshRegistryList(registry);
      if (index > 0) {
        setRegistryStatus(`failover succeeded on tier ${registry.tier} at ${registryUrl}`);
      } else {
        setRegistryStatus(`using tier ${registry.tier} at ${registryUrl}`);
      }
      return payload;
    } catch (error) {
      lastError = error;
      failures.push(`tier ${registry.tier} at ${registryUrl} -> ${error.message}`);
      setRegistryStatus(`tier ${registry.tier} at ${registryUrl} failed, trying next`);
    }
  }

  if (failures.length) {
    throw new Error(failures.join(" | "));
  }

  throw lastError || new Error("No registry available");
}

async function discoverNodes() {
  const lat = document.getElementById("lat").value;
  const lng = document.getElementById("lng").value;
  const radius = document.getElementById("radius").value;
  const category = document.getElementById("category").value.trim().toLowerCase();

  const params = new URLSearchParams({
    lat,
    lng,
    radius,
    category
  });

  const payload = await fetchWithFailover(`/discover?${params.toString()}`);
  renderNodes(payload.nodes || []);
  setLog(payload);
}

function renderNodes(nodes) {
  nodesEl.replaceChildren();

  if (!nodes.length) {
    appendEmptyStatus(nodesEl, "No nodes found.");
    return;
  }

  for (const node of nodes) {
    const wrapper = document.createElement("div");
    wrapper.className = "node";

    appendStrong(wrapper, node.name);
    appendBreak(wrapper);
    appendPill(wrapper, node.city);
    appendPill(wrapper, `${safeText(node.distance_km, "?")} km`);
    appendPill(wrapper, asArray(node.categories).join(", "));
    appendPill(wrapper, orderModeLabel(node));
    appendPill(wrapper, nodeIdentityLabel(node));
    appendPill(wrapper, discoverySourceLabel(node));

    const modules = asArray(node.modules);
    if (modules.length) {
      const moduleRow = appendStatus(wrapper, "Modules: ", {
        block: true,
        marginTop: "8px"
      });
      for (const moduleId of modules) {
        appendPill(moduleRow, moduleId);
      }
    }

    appendStatus(wrapper, node.endpoint, {
      block: true,
      marginTop: "8px"
    });

    const button = document.createElement("button");
    button.textContent = "Use This Node";
    button.addEventListener("click", () => selectNode(node));
    wrapper.appendChild(button);
    nodesEl.appendChild(wrapper);
  }
}

async function selectNode(node) {
  selectedNode = node;
  selectedNodeEl.replaceChildren();
  appendStrong(selectedNodeEl, node.name);
  appendBreak(selectedNodeEl);
  appendPill(selectedNodeEl, orderModeLabel(node));
  appendPill(selectedNodeEl, nodeIdentityLabel(node));
  appendPill(selectedNodeEl, discoverySourceLabel(node));
  appendStatus(selectedNodeEl, node.endpoint);
  updateOrderControls();

  const menu = await fetchJsonWithTimeout(`${node.endpoint}/menu`);
  renderMenu(menu.items || []);
  setLog(menu);
}

function renderMenu(items) {
  menuEl.replaceChildren();

  if (!items.length) {
    appendEmptyStatus(menuEl, "No menu items.");
    return;
  }

  for (const item of items) {
    const wrapper = document.createElement("div");
    wrapper.className = "menu-item";
    appendStrong(wrapper, item.name);
    wrapper.appendChild(document.createTextNode(` - ${safeText(item.price, "?")} DKK`));
    appendBreak(wrapper);
    appendStatus(wrapper, item.description);
    appendBreak(wrapper);
    appendPill(wrapper, item.id);
    appendPill(wrapper, item.category);
    menuEl.appendChild(wrapper);
  }
}

async function placeOrder() {
  if (!selectedNode) {
    setLog("Select a node first.");
    return;
  }
  if (!nodeAcceptsOrders(selectedNode)) {
    setLog(`Selected node does not accept orders in ${getOrderMode(selectedNode)} mode.`);
    return;
  }

  const payload = {
    customer_name: document.getElementById("customer-name").value,
    customer_contact: document.getElementById("customer-contact").value,
    fulfillment: "pickup",
    items: [
      {
        id: document.getElementById("item-id").value,
        quantity: Number(document.getElementById("quantity").value)
      }
    ],
    note: document.getElementById("note").value,
    client_version: "p4p-web-0.1"
  };

  const data = await fetchJsonWithTimeout(`${selectedNode.endpoint}/order`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  setLog(data);
}

function useBrowserLocation() {
  if (!navigator.geolocation) {
    setLog("Geolocation is not available in this browser.");
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      document.getElementById("lat").value = position.coords.latitude.toFixed(6);
      document.getElementById("lng").value = position.coords.longitude.toFixed(6);
      setLog("Browser location loaded.");
    },
    (error) => {
      setLog(`Geolocation failed: ${error.message}`);
    }
  );
}

document.getElementById("discover").addEventListener("click", () => {
  discoverNodes().catch((error) => setLog(`Discover failed: ${error.message}`));
});

placeOrderButton.addEventListener("click", () => {
  placeOrder().catch((error) => setLog(`Order failed: ${error.message}`));
});

document.getElementById("use-location").addEventListener("click", useBrowserLocation);

pinnedRegistries = loadInitialRegistries();
registries = [...pinnedRegistries];
setRegistryStatus(
  registries.length
    ? `idle, seed tier ${registries[0].tier} at ${registries[0].url}`
    : "idle, no registries configured"
);
updateOrderControls();
