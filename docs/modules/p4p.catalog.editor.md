# p4p.catalog.editor

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.catalog.editor/module.json`](../../modules/p4p.catalog.editor/module.json)

Provider: [`../../modules/p4p.catalog.editor/provider.json`](../../modules/p4p.catalog.editor/provider.json)

## Purpose

`p4p.catalog.editor` is the operator-owned catalog editor for the pilot node.

It lets a restaurant operator maintain the structured catalog that customer menu modules read from.

## What It Does

- views the current local catalog
- edits item names and descriptions
- edits integer minor-unit prices
- edits item categories
- toggles active/inactive availability
- edits optional item image URLs for customer menu surfaces
- records `CATALOG_UPDATED` when the enabled reference runtime saves a replacement catalog

## What It Does Not Own

- customer menu layout
- paper-menu image mapping
- stock validation
- payment
- kitchen status
- registry discovery
- node identity

The catalog is the local item truth. Menu presentation modules are separate surfaces on top of it.

## Data Access

Allowed data:

- `catalog_item_id`
- `catalog_item_name`
- `catalog_item_description`
- `catalog_item_price`
- `catalog_item_category`
- `catalog_item_active`

The reference runtime also carries optional item image metadata as a presentation aid. Images do not become truth for ingredients, allergens, availability, price, or payment.

## Events

Inputs:

- `ORDER_ITEM_CREATED`
- `ITEM_NOT_POSSIBLE`

Outputs:

- `CATALOG_UPDATED`

Failure mode:

- `CATALOG_UPDATE_FAILED`

## Local Test Path

Enable it in the pilot node with `P4P_NODE_MODULES`:

```text
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.payment.cash
```

Then open:

```text
GET /operator
GET /operator/menu
PUT /operator/menu
```

Operator routes require the operator token.

## Current Readiness

This is a test-ready reference module in the pilot-node runtime.

It is not a hosted production catalog service.
