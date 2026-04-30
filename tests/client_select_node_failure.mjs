import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const elements = new Map();

function makeElement(tagName = "div") {
  return {
    tagName: tagName.toUpperCase(),
    textContent: "",
    className: "",
    style: {},
    value: "",
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
global.fetch = async () => {
  throw new Error("node menu unavailable");
};

const source = fs.readFileSync(new URL("../client/app.js", import.meta.url), "utf8");
vm.runInThisContext(source, { filename: "app.js" });

const hooks = global.window.__P4PClientTestHooks;
assert.ok(hooks, "test hooks were not exposed");

const result = await hooks.selectNode({
  name: "Broken Node",
  endpoint: "http://127.0.0.1:8101/p4p",
  order_mode: "test",
  city: "Brondby",
  categories: ["pizza"]
});

assert.equal(result.ok, false);
assert.equal(elements.get("place-order").disabled, true);
assert.match(elements.get("order-status").textContent, /could not be reached/i);
assert.match(elements.get("log").textContent, /Node fetch failed/i);
