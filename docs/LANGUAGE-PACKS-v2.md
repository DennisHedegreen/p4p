# P4P Language Packs v2

This is the next-step spec for making P4P language handling more data-driven.

It does not replace the active locale system today.

Today:

- locale resolution lives in code
- much operator shell copy still lives in a shared Python locale table
- module/provider text is partly manifest-driven and partly bridged through code

The point of this spec is to make future node variants simpler:

- Danish-only
- Danish + Turkish
- Danish + Swedish + Arabic
- customer-specific word choices
- custom local overrides without forking the runtime

## Core Rule

Keep the locale engine in code.

Move most human copy into data.

Keep module/provider language in manifests.

Do not introduce a separate executable plugin-like language system.

Language packs are data, not logic.

## v2 Target

P4P should resolve language from four layers:

1. node-local custom override
2. installed language pack
3. `en`
4. `da`

If no matching text exists, return the first non-empty value.

`da` remains the canonical maintenance default.

## What Stays In Code

These stay in code because they are app behavior, not content:

- supported locale ids
- locale normalization
- fallback order
- RTL/LTR handling
- browser override vs node-default resolution
- interpolation and formatting helpers
- template lookup helpers

Examples:

- `SUPPORTED_LOCALES`
- `DEFAULT_LOCALE`
- `RTL_LOCALES`
- `normalize_locale(...)`
- `localized_text(...)`

## What Moves To Data Packs

These should move out of shared Python tables and into JSON:

- operator room intros
- operator room helper text
- section headings
- empty-state copy
- restart-warning body copy
- checklist phrasing
- public-site section intros
- screenshot captions
- proof/press/module-reading helper copy

This is the content that should become customer-tunable without touching code.

## What Stays In Manifests

Module/provider identity and public-reading text should stay with the module/provider itself:

- module title
- module summary
- module description
- public catalog function text
- data-access summary
- trust status
- operator status
- customer notice
- provider name
- provider description

That means:

- operator/public chrome uses language packs
- module/provider meaning uses manifests

## File Shape

### Core packs

Suggested path:

- `P4P/data/i18n/core/da.json`
- `P4P/data/i18n/core/sv.json`
- `P4P/data/i18n/core/tr.json`
- `P4P/data/i18n/core/ar.json`
- `P4P/data/i18n/core/ku.json`
- `P4P/data/i18n/core/en.json`

Each file should be one plain JSON object:

```json
{
  "common.open": "Åbn",
  "common.save": "Gem",
  "welcome.this_node_body": "Lokal menu, lokalt ordreflow og lokale operatorflader.",
  "discover.groups_body": "Læs det offentlige modulkatalog her, og brug derefter Moduler..."
}
```

The first scaffold now exists on disk with:

- `data/i18n/core/da.json`
- `data/i18n/core/sv.json`
- `data/i18n/core/tr.json`
- `data/i18n/core/ar.json`
- `data/i18n/core/ku.json`
- `data/i18n/core/en.json`
- `data/i18n/packs.json`

The runtime also now reads a first shell-key slice from those core packs
with code fallback, so the folder is no longer docs-only.

### Optional node-local overrides

Suggested path:

- `P4P/data/i18n/custom/<node-or-customer-id>/da.json`
- `P4P/data/i18n/custom/<node-or-customer-id>/tr.json`

These files override the core pack for one deployment.

Example:

```json
{
  "nav.operations": "Kasse",
  "common.open_catalog": "Åbn menukort"
}
```

This is for real shop language, not protocol truth.

The first scaffold now also includes:

- `data/i18n/custom/example-node/da.json`
- `data/i18n/custom/example-node/tr.json`

### Optional installed-pack manifest

Suggested path:

- `P4P/data/i18n/packs.json`

Example:

```json
{
  "default_locale": "da",
  "available_locales": ["da", "tr", "en"],
  "custom_scope": "dk-brondby-kebab-001"
}
```

This is not the text itself.
It is only the install/availability manifest.

## Node Policy

Every node should be able to declare:

- one node default locale
- a locale whitelist
- optional custom override scope

Suggested persisted setup fields:

- `operator_locale`
- `operator_enabled_locales`
- `operator_locale_override_scope`

Example:

```json
{
  "operator_locale": "da",
  "operator_enabled_locales": ["da", "tr"],
  "operator_locale_override_scope": "dk-brondby-kebab-001"
}
```

This lets one node expose only the languages it actually wants.

## Resolution Order

For operator/public shell copy:

1. query param locale
2. browser override cookie
3. node default locale
4. `da`

For text lookup inside a chosen locale:

1. custom override pack
2. core pack for chosen locale
3. core `en`
4. core `da`
5. first non-empty value

For module/provider manifest fields:

1. chosen locale in the manifest locale-map
2. manifest `en`
3. manifest `da`
4. first non-empty manifest locale

Do not mix shell pack keys and manifest keys into one file.

## Why This Split Exists

Operator shell copy is deployment language.

Module/provider text is protocol/package language.

Those are related, but not the same thing.

If they live in the same blob:

- custom shop wording becomes messy
- module portability gets worse
- public catalog and operator can drift for the wrong reasons

## What Not To Do

Do not:

- turn language packs into executable modules
- add one separate language-pack file per module in v2
- make every locale mandatory for every node
- force menu item content into this pass
- duplicate module/provider text both in packs and manifests as a long-term model

## Migration Plan

### Phase 1

Add core pack files and loader helpers.

Keep existing `SHELL_STRINGS` as fallback while migrating.

### Phase 2

Move operator room copy from shared Python tables into:

- `data/i18n/core/*.json`

Keep small status words in code if helpful.

### Phase 3

Add node locale whitelist and override scope to setup state.

### Phase 4

Move public-site helper copy and screenshot captions into the same pack model.

### Phase 5

Thin down `module_catalog.py` so it becomes lookup/assembly logic rather than the source of most prose.

### Phase 6

Gradually remove the `MODULE_META` language bridge as manifests themselves become properly localized.

## Minimum Acceptance For v2

The model is good enough when:

- a node can run Danish-only without code edits
- a node can run Danish + Turkish without code edits
- a customer-specific override can rename room labels without forking the repo
- operator and public shell copy use the same pack system
- module/provider text still resolves from manifests

## Short Rule

In v2:

- engine in code
- shell copy in language-pack JSON
- module/provider meaning in manifests
- per-node or per-customer overrides as thin JSON layers

That is the clean path to a Danish-only build or a custom local build without changing runtime logic.
