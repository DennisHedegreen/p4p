import fs from "node:fs/promises";
import net from "node:net";
import { spawn } from "node:child_process";

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (!value.startsWith("--")) {
      continue;
    }
    const key = value.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      options[key] = "true";
      continue;
    }
    options[key] = next;
    index += 1;
  }
  return options;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function choosePort(preferred) {
  for (let candidate = preferred; candidate < preferred + 40; candidate += 1) {
    const server = net.createServer();
    try {
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(candidate, "127.0.0.1", resolve);
      });
      await new Promise((resolve) => server.close(resolve));
      return candidate;
    } catch {
      try {
        await new Promise((resolve) => server.close(resolve));
      } catch {
        // ignore
      }
    }
  }
  throw new Error(`Could not find a free port near ${preferred}`);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }
  return response.json();
}

function connectWebSocket(url) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.addEventListener("open", () => resolve(socket), { once: true });
    socket.addEventListener("error", (event) => reject(event.error || new Error("WebSocket error")), { once: true });
  });
}

class CdpSession {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.events = [];
    this.socket.addEventListener("message", (event) => {
      const payload = JSON.parse(event.data);
      if (typeof payload.id === "number") {
        const pending = this.pending.get(payload.id);
        if (!pending) {
          return;
        }
        this.pending.delete(payload.id);
        if (payload.error) {
          pending.reject(new Error(payload.error.message || "CDP error"));
          return;
        }
        pending.resolve(payload.result || {});
        return;
      }
      this.events.push(payload);
    });
  }

  send(method, params = {}) {
    const id = ++this.nextId;
    const message = { id, method, params };
    const promise = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
    this.socket.send(JSON.stringify(message));
    return promise;
  }

  async waitForEvent(method, timeoutMs = 10000) {
    const started = Date.now();
    for (;;) {
      const index = this.events.findIndex((entry) => entry.method === method);
      if (index >= 0) {
        return this.events.splice(index, 1)[0];
      }
      if (Date.now() - started > timeoutMs) {
        throw new Error(`Timed out waiting for CDP event: ${method}`);
      }
      await sleep(25);
    }
  }
}

function operatorCaptureCleanup() {
  return `
    (() => {
      const toolbar = document.querySelector('.toolbar');
      if (toolbar) toolbar.remove();
      const header = document.querySelector('header');
      if (header) {
        header.style.gridTemplateColumns = 'minmax(0, 1fr)';
        header.style.alignItems = 'start';
      }
      const statusLine = document.getElementById('status-line');
      if (statusLine) statusLine.remove();
      document.querySelectorAll('details.panel').forEach((node) => {
        node.open = false;
      });
      document.body.dataset.captureMode = 'true';
    })();
  `;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const url = args.url;
  const output = args.output;
  const width = Number.parseInt(args.width || "1280", 10);
  const height = Number.parseInt(args.height || "1400", 10);
  const waitMs = Number.parseInt(args.wait || "1500", 10);
  const token = args.token || "";
  const pageType = args["page-type"] || "public";

  if (!url || !output) {
    throw new Error("Usage: node capture_page.mjs --url <url> --output <png> [--width 1280] [--height 1400] [--wait 1500] [--token secret] [--page-type operator|public]");
  }

  const devtoolsPort = await choosePort(9222);
  const chrome = spawn(
    "google-chrome",
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      `--remote-debugging-port=${devtoolsPort}`,
      `--window-size=${width},${height}`,
      "about:blank",
    ],
    {
      stdio: ["ignore", "ignore", "pipe"],
    }
  );

  let stderr = "";
  chrome.stderr.setEncoding("utf-8");
  chrome.stderr.on("data", (chunk) => {
    stderr += chunk;
  });

  try {
    let metadata = null;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      try {
        const pages = await fetchJson(`http://127.0.0.1:${devtoolsPort}/json/list`);
        metadata = Array.isArray(pages) ? pages.find((entry) => entry.type === "page") || pages[0] : null;
        if (metadata?.webSocketDebuggerUrl) {
          break;
        }
      } catch {
        // keep waiting
      }
      await sleep(100);
    }
    if (!metadata?.webSocketDebuggerUrl) {
      throw new Error(`Chrome DevTools endpoint did not come up: ${stderr}`);
    }

    const socket = await connectWebSocket(metadata.webSocketDebuggerUrl);
    const session = new CdpSession(socket);
    await session.send("Page.enable");
    await session.send("Runtime.enable");
    await session.send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
      screenWidth: width,
      screenHeight: height,
    });
    if (token) {
      await session.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `
          (() => {
            try {
              localStorage.setItem("p4pOperatorToken", ${JSON.stringify(token)});
            } catch (error) {
              console.warn(error);
            }
          })();
        `,
      });
    }
    await session.send("Page.navigate", { url });
    await session.waitForEvent("Page.loadEventFired", 15000);
    await sleep(waitMs);
    if (pageType === "operator") {
      await session.send("Runtime.evaluate", { expression: operatorCaptureCleanup() });
      await sleep(200);
    }
    const screenshot = await session.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
      fromSurface: true,
    });
    await fs.writeFile(output, Buffer.from(screenshot.data, "base64"));
    socket.close();
  } finally {
    chrome.kill("SIGTERM");
    await new Promise((resolve) => chrome.once("exit", resolve));
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exit(1);
});
