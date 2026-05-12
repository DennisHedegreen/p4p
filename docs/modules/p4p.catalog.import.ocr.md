# p4p.catalog.import.ocr

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.catalog.import.ocr/module.json`](../../modules/p4p.catalog.import.ocr/module.json)

Provider: [`../../modules/p4p.catalog.import.ocr/provider.json`](../../modules/p4p.catalog.import.ocr/provider.json)

## Purpose

`p4p.catalog.import.ocr` is the optional operator-owned OCR/import helper for the pilot node.

It lets a restaurant operator preview photographed or scanned menu text as draft catalog items before those items are reviewed and saved into the catalog.

## What It Does

- previews draft catalog lines from raw OCR/scanned menu text
- previews draft catalog lines from uploaded photographed/scanned paper-menu images
- gives the OCR helper its own operator module page instead of living inside the generic catalog-editor shell
- lets the operator review draft names, categories, and prices before saving selected rows through the catalog editor dependency
- keeps all OCR results draft-only until a human explicitly saves selected rows into the catalog

## What It Does Not Own

- catalog truth
- customer menu layout
- automatic OCR truth
- payment
- kitchen status
- registry discovery
- node identity

This module is a helper surface beside the catalog editor.
It does not become the source of truth for items, prices, or categories.

## Data Access

Allowed data:

- `draft_catalog_item_id`
- `draft_catalog_item_name`
- `draft_catalog_item_price`
- `draft_catalog_item_category`
- `draft_catalog_source_line`

The built-in image path runs local OCR first and then feeds the extracted text into the same draft parser as the plain text preview.

## Events

Inputs:

- `CATALOG_IMPORT_PREVIEW_REQUESTED`

Outputs:

- `CATALOG_IMPORT_PREVIEW_READY`

Failure modes:

- `CATALOG_IMPORT_PREVIEW_FAILED`

The important boundary is simpler than event flow: preview is draft-only until a human reviews the rows on the OCR module page and explicitly saves selected rows into the catalog.

## Local Test Path

Enable it in the pilot node with `P4P_NODE_MODULES`:

```text
P4P_NODE_MODULES=p4p.catalog.editor,p4p.catalog.import.ocr,p4p.menu.list,p4p.payment.cash
```

If you want the image path, also install:

```text
./.venv/bin/python -m pip install -r requirements-ocr.txt
```

Then use:

```text
GET /operator/modules/view/p4p.catalog.import.ocr
POST /operator/menu/import-preview
POST /operator/menu/import-image-preview?source_name=copenhagen-paper-menu.png
```

Operator routes require the operator token.

If `p4p.catalog.import.ocr` is not enabled, those preview routes return `404`.

The generic `GET /operator` operations room and `GET /operator/catalog` catalog room
should not expose OCR upload controls when this module is off.

## Current Readiness

This is a test-ready reference helper module in the pilot-node runtime.

It is not autonomous OCR truth.
It is not a production ingestion pipeline.
It is not a replacement for human review inside the catalog editor.
