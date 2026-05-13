# Custom Overrides

This folder is for per-node or per-customer language overrides.

Suggested shape:

- `custom/<node-or-customer-id>/da.json`
- `custom/<node-or-customer-id>/tr.json`

These files should contain only the keys that differ from the core pack.

They are for deployment language, not protocol truth.

Good use:

- rename `Operations` to `Counter`
- rename `Catalog` to `Menu`
- use customer-preferred terms in one local rollout

Bad use:

- rewriting module identity
- changing protocol meaning
- hiding whether a module is actually public/operator-only

The example folder below is only a scaffold.
