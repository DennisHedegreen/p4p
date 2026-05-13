# P4P i18n Data

This folder is the first scaffold for the `LANGUAGE-PACKS-v2` direction.

It is not fully wired into the runtime yet.

Today:

- the locale engine still lives in code
- most operator/public shell copy still resolves from shared Python locale tables
- module/provider meaning still resolves from manifests
- a first shell-key slice now reads from `core/*.json` with code fallback

This folder exists so the next migration has a real target on disk instead of only a doc.

## Structure

- `core/`
  Base language packs for shared operator/public shell copy.
- `custom/`
  Optional per-node or per-customer override layers.
- `packs.json`
  Small install/availability manifest for which packs are present by default.

## Rule

These files are data packs.

They are not modules.

They are not executable.

They should stay simple enough that:

- a Danish-only node can ship with only Danish plus fallback English
- a Danish + Turkish pilot can expose only those two visible choices
- a customer-specific override can rename some room labels without forking the runtime

## Current Scaffold Status

The first scaffold includes:

- `core/da.json`
- `core/sv.json`
- `core/tr.json`
- `core/ar.json`
- `core/ku.json`
- `core/en.json`
- `custom/example-node/da.json`
- `custom/example-node/tr.json`
- `packs.json`

Those files are intentionally small.

They prove the shape and a real live runtime read path for:

- navigation labels
- some common operator buttons/headings
- part of `welcome.*`
- part of `catalog.*`

They do not represent the full migration yet.
