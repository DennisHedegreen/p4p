# p4p.menu.list

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.menu.list/module.json`](../../modules/p4p.menu.list/module.json)

Provider: [`../../modules/p4p.menu.list/provider.json`](../../modules/p4p.menu.list/provider.json)

## Purpose

`p4p.menu.list` is a customer-facing list menu built from the node's active structured catalog items.

It is the plain reference menu surface: easy to inspect, easy to test, and deliberately boring.

## What It Does

- reads active catalog items
- groups items by category
- displays item names, descriptions, prices, and optional images
- builds a browser-side order draft
- submits an ordinary P4P order request to the node
- records `CUSTOMER_MENU_VIEWED`

## What It Does Not Own

- item ids
- prices
- availability
- stock
- allergens
- payment
- order acceptance
- operator state

The list menu is only a presentation layer. The catalog remains the source of item truth.

## Data Access

Allowed data:

- `catalog_item_id`
- `catalog_item_name`
- `catalog_item_description`
- `catalog_item_price`
- `catalog_item_category`
- `catalog_item_active`

The reference runtime may also show optional `image_url` metadata. Image metadata is presentation-only.

## Events

Inputs:

- `CATALOG_UPDATED`
- `ITEM_NOT_POSSIBLE`
- `ORDER_REJECTED`

Outputs:

- `CUSTOMER_MENU_VIEWED`

## Local Test Path

Enable it in the pilot node with `P4P_NODE_MODULES`:

```text
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.payment.cash
```

Then open:

```text
GET /p4p/menu/list
```

The lab scenario `pilot-photo-map-menu` also enables this module.

## Current Readiness

This is a test-ready reference module in the pilot-node runtime.

It is not a marketplace menu and not an ordering platform.
