# client

Canonical `v0.1` customer-side reference client.

Responsibilities:
- query registry `/discover`
- start from a small seed list and refresh runtime registry ordering from `/registry-info`
- fetch menu directly from the selected node
- submit order directly to the node
- fail over to backup registries when primary is down, with a 5-second timeout per registry

Target:
Static HTML and JavaScript with browser geolocation.

## Files

- `index.html` — minimal browser client
- `config.js` — deploy-time registry seed list
- `app.js` — discovery, failover, menu fetch, and direct ordering logic

## Local run

Serve this folder with any static server after the registry and demo-node are running.

Example:

```bash
cd /path/to/p4p/client
python3 -m http.server 8765
```

Then open `http://127.0.0.1:8765/`.

If you instead serve from the repo root, then the client lives at `/client/`.

## Deploy config

For a public proof, edit `config.js` so the seed registries use public HTTPS URLs.

Example:

```js
window.P4P_CLIENT_CONFIG = {
  registries: [
    { tier: 0, url: "https://registry-a.pizza4people.com" },
    { tier: 1, url: "https://registry-b.pizza4people.com" }
  ]
};
```

The client uses this seed list first, then refreshes registry ordering from `/registry-info`.
