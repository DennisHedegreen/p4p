const DEFAULT_REGISTRIES = [
  { tier: 0, url: "http://127.0.0.1:8000" },
  { tier: 1, url: "http://127.0.0.1:8002" }
];

let registries = [];
let pinnedRegistries = [];
let activeRegistry = null;
let selectedNode = null;
let selectedNodeMenuState = "idle";

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

function appendPill(parent, value, variant = "") {
  const element = document.createElement("span");
  element.className = `pill${variant ? ` ${variant}` : ""}`;
  element.textContent = safeText(value);
  parent.appendChild(element);
  return element;
}

function appendStatus(parent, value, options = {}) {
  const element = document.createElement(options.block ? "div" : "span");
  element.className = `status${options.variant ? ` ${options.variant}` : ""}`;
  element.textContent = safeText(value);
  if (options.marginTop) {
    element.style.marginTop = options.marginTop;
  }
  parent.appendChild(element);
  return element;
}

function appendEmptyStatus(parent, value, variant = "") {
  const element = document.createElement("p");
  element.className = `status${variant ? ` ${variant}` : ""}`;
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

function nodeLookupKey(node) {
  if (typeof node?.node_id === "string" && node.node_id) {
    return `node:${node.node_id}`;
  }
  if (typeof node?.endpoint === "string" && node.endpoint) {
    return `endpoint:${node.endpoint}`;
  }
  return null;
}

function mergeDirectoryNodes(nodes, directoryNodes) {
  const overlays = new Map();

  for (const node of asArray(directoryNodes)) {
    const key = nodeLookupKey(node);
    if (key) {
      overlays.set(key, node);
    }
  }

  return asArray(nodes).map((node) => {
    const key = nodeLookupKey(node);
    const overlay = key ? overlays.get(key) : null;
    if (!overlay) {
      return node;
    }
    return {
      ...node,
      ...overlay,
      modules: asArray(node.modules).length ? asArray(node.modules) : asArray(overlay.modules)
    };
  });
}

function moduleDeclarationSummary(entry) {
  const parts = [];
  if (typeof entry?.status === "string" && entry.status) {
    parts.push(entry.status);
  }
  if (typeof entry?.readiness === "string" && entry.readiness) {
    parts.push(entry.readiness);
  }
  if (typeof entry?.visibility === "string" && entry.visibility) {
    parts.push(entry.visibility);
  }
  if (typeof entry?.provider_id === "string" && entry.provider_id) {
    parts.push(entry.provider_id);
  }
  if (typeof entry?.customer_notice === "string" && entry.customer_notice) {
    parts.push(entry.customer_notice);
  }
  return parts.join(" • ");
}

function moduleEntriesForNode(node) {
  const declared = asArray(node?.module_declarations)
    .filter((entry) => typeof entry?.module_id === "string" && entry.module_id)
    .map((entry) => ({
      label: entry.module_id,
      title: moduleDeclarationSummary(entry)
    }));
  const undeclared = asArray(node?.undeclared_modules)
    .filter((moduleId) => typeof moduleId === "string" && moduleId)
    .map((moduleId) => ({
      label: `${moduleId} (opaque)`,
      title: "Compatibility module id without local manifest metadata."
    }));

  if (declared.length || undeclared.length) {
    return [...declared, ...undeclared];
  }

  return asArray(node?.modules)
    .filter((moduleId) => typeof moduleId === "string" && moduleId)
    .map((moduleId) => ({ label: moduleId, title: "" }));
}

function appendNodeModules(parent, node, { marginTop = "12px" } = {}) {
  const modules = moduleEntriesForNode(node);
  if (!modules.length) {
    return;
  }

  appendStatus(parent, "Modules:", {
    block: true,
    marginTop
  });
  const modulePills = document.createElement("div");
  modulePills.className = "pill-row";
  for (const moduleEntry of modules) {
    const pill = appendPill(modulePills, moduleEntry.label);
    if (moduleEntry.title) {
      pill.title = moduleEntry.title;
    }
  }
  parent.appendChild(modulePills);
}

function resetSelectedNodeView(message = "No node selected yet.") {
  selectedNodeEl.replaceChildren();
  const label = document.createElement("span");
  label.className = "status-label";
  label.textContent = "Selected node";
  selectedNodeEl.appendChild(label);
  appendEmptyStatus(selectedNodeEl, message);
}

function setMenuMessage(message, variant = "") {
  menuEl.replaceChildren();
  appendEmptyStatus(menuEl, message, variant);
}

function updateOrderControls() {
  if (!selectedNode) {
    placeOrderButton.disabled = true;
    orderStatusEl.textContent = "Select a node before placing an order.";
    orderStatusEl.className = "status";
    return;
  }

  if (selectedNodeMenuState === "loading") {
    placeOrderButton.disabled = true;
    orderStatusEl.textContent = "Loading direct menu from node...";
    orderStatusEl.className = "status";
    return;
  }

  if (selectedNodeMenuState === "error") {
    placeOrderButton.disabled = true;
    orderStatusEl.textContent = `${selectedNode.name} was discovered, but the node menu could not be reached yet.`;
    orderStatusEl.className = "status error";
    return;
  }

  if (!nodeAcceptsOrders(selectedNode)) {
    placeOrderButton.disabled = true;
    orderStatusEl.textContent = `${selectedNode.name} is discoverable, but does not accept orders in ${getOrderMode(selectedNode)} mode.`;
    orderStatusEl.className = "status";
    return;
  }

  placeOrderButton.disabled = false;
  orderStatusEl.textContent =
    getOrderMode(selectedNode) === "test"
      ? "This node accepts test orders only."
      : "This node accepts live orders.";
  orderStatusEl.className = "status good";
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
  let nodes = asArray(payload.nodes);

  if (activeRegistry) {
    try {
      const directoryPayload = await fetchJsonWithTimeout(
        buildRegistryUrl(activeRegistry, `/directory?${params.toString()}`)
      );
      nodes = mergeDirectoryNodes(nodes, directoryPayload.nodes);
    } catch (error) {
      // Keep discovery usable even when the richer directory overlay is missing.
    }
  }

  renderNodes(nodes);
  setLog({
    ...payload,
    nodes
  });
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

    const pills = document.createElement("div");
    pills.className = "pill-row";
    appendPill(pills, node.city);
    appendPill(pills, `${safeText(node.distance_km, "?")} km`);
    appendPill(pills, asArray(node.categories).join(", "));
    appendPill(pills, orderModeLabel(node));
    appendPill(pills, nodeIdentityLabel(node));
    appendPill(pills, discoverySourceLabel(node));
    wrapper.appendChild(pills);

    appendNodeModules(wrapper, node, { marginTop: "12px" });

    appendStatus(wrapper, node.endpoint, {
      block: true,
      marginTop: "12px"
    });

    const button = document.createElement("button");
    button.textContent = "Use This Node";
    button.addEventListener("click", () => {
      void selectNode(node);
    });
    wrapper.appendChild(button);
    nodesEl.appendChild(wrapper);
  }
}

function renderSelectedNode(node) {
  selectedNodeEl.replaceChildren();
  const label = document.createElement("span");
  label.className = "status-label";
  label.textContent = "Selected node";
  selectedNodeEl.appendChild(label);
  appendStrong(selectedNodeEl, node.name);
  appendBreak(selectedNodeEl);

  const pills = document.createElement("div");
  pills.className = "pill-row";
  appendPill(pills, orderModeLabel(node));
  appendPill(pills, nodeIdentityLabel(node));
  appendPill(pills, discoverySourceLabel(node));
  selectedNodeEl.appendChild(pills);
  appendNodeModules(selectedNodeEl, node, { marginTop: "12px" });

  appendStatus(selectedNodeEl, node.endpoint, {
    block: true,
    marginTop: "12px"
  });
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
    const meta = document.createElement("div");
    meta.className = "pill-row";
    appendPill(meta, item.id);
    appendPill(meta, item.category);
    wrapper.appendChild(meta);
    menuEl.appendChild(wrapper);
  }
}

async function selectNode(node) {
  selectedNode = node;
  selectedNodeMenuState = "loading";
  renderSelectedNode(node);
  setMenuMessage("Loading menu directly from node...");
  updateOrderControls();

  try {
    const menu = await fetchJsonWithTimeout(`${node.endpoint}/menu`);
    selectedNodeMenuState = "ready";
    renderMenu(menu.items || []);
    updateOrderControls();
    setLog(menu);
    return { ok: true, menu };
  } catch (error) {
    selectedNodeMenuState = "error";
    setMenuMessage(`Menu unavailable: ${error.message}`, "error");
    appendStatus(selectedNodeEl, "Node discovered, but direct menu fetch failed.", {
      block: true,
      marginTop: "12px",
      variant: "error"
    });
    updateOrderControls();
    setLog(`Node fetch failed: ${error.message}`);
    return { ok: false, error };
  }
}

async function placeOrder() {
  if (!selectedNode) {
    setLog("Select a node first.");
    return;
  }
  if (selectedNodeMenuState !== "ready") {
    setLog("Selected node menu is not available yet.");
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

  orderStatusEl.textContent = "Submitting direct order to node...";
  orderStatusEl.className = "status";
  const data = await fetchJsonWithTimeout(`${selectedNode.endpoint}/order`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  orderStatusEl.textContent = data.accepted ? "Direct order accepted." : "Direct order rejected.";
  orderStatusEl.className = `status ${data.accepted ? "good" : "error"}`;
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
  placeOrder().catch((error) => {
    orderStatusEl.textContent = `Order failed: ${error.message}`;
    orderStatusEl.className = "status error";
    setLog(`Order failed: ${error.message}`);
  });
});

document.getElementById("use-location").addEventListener("click", useBrowserLocation);

pinnedRegistries = loadInitialRegistries();
registries = [...pinnedRegistries];
setRegistryStatus(
  registries.length
    ? `idle, seed tier ${registries[0].tier} at ${registries[0].url}`
    : "idle, no registries configured"
);
resetSelectedNodeView();
setMenuMessage("Select a node to fetch its menu.");
updateOrderControls();

window.__P4PClientTestHooks = {
  buildRegistryUrl,
  discoverNodes,
  fetchJsonWithTimeout,
  mergeDirectoryNodes,
  moduleEntriesForNode,
  normalizeRegistries,
  selectNode
};
