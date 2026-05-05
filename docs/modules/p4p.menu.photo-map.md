# p4p.menu.photo-map

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.menu.photo-map/module.json`](../../modules/p4p.menu.photo-map/module.json)

Provider: [`../../modules/p4p.menu.photo-map/provider.json`](../../modules/p4p.menu.photo-map/provider.json)

## Purpose

`p4p.menu.photo-map` is a customer-facing paper-menu style surface.

It maps active structured catalog items to clickable visual regions.

## What It Does

- reads active catalog items
- presents them as clickable paper-menu style regions
- displays optional item images when the catalog has an `image_url`
- builds a browser-side order draft
- submits an ordinary P4P order request to the node
- records `CUSTOMER_MENU_VIEWED`

## What It Does Not Own

- OCR
- catalog truth
- item ids
- prices
- inventory
- allergens
- payment
- order acceptance

The important boundary: this module does not convert a real menu photo into authoritative catalog data. It is a presentation surface over structured catalog items.

## Data Access

Allowed data:

- `catalog_item_id`
- `catalog_item_name`
- `catalog_item_description`
- `catalog_item_price`
- `catalog_item_category`
- `catalog_item_active`

Optional images and paper-menu fixtures are demo material. They are not proof of restaurant data, menu truth, partner material, or production readiness.

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
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.photo-map,p4p.menu.list,p4p.customer.status,p4p.payment.cash
```

Then open:

```text
GET /p4p/menu/photo-map
```

The lab scenario `pilot-photo-map-menu` seeds this surface with synthetic Margherita and Durum fixture images.

## Current Readiness

This is a test-ready reference module in the pilot-node runtime.

It is not OCR, not a menu importer, and not a restaurant-partner menu.
