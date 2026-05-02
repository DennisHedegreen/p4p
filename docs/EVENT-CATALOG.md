# P4P Event Catalog

Status: planned `v0.2` canonical event-name freeze.

This file is the small public list of event names that later module manifests,
node declarations, flows, and runtime results should share.

The matching machine-readable shape lives in
`docs/schemas/module-event-name.schema.json`.

## Rule

If a new module event name is introduced, it should land in both:

- `docs/EVENT-CATALOG.md`
- `docs/schemas/module-event-name.schema.json`

This is how P4P avoids hidden event drift between:

- module manifests
- flow sketches
- trust modules
- fallback policy
- runtime result envelopes

## Customer And Menu Events

- `CUSTOMER_MENU_AREA_SELECTED`
- `CUSTOMER_INTENT_SUBMITTED`
- `ORDER_ITEM_CREATED`
- `OPTIONS_REQUIRED`
- `ITEM_NOT_POSSIBLE`
- `CATALOG_UPDATED`
- `CATALOG_UPDATE_FAILED`

## Order Lifecycle Events

- `ORDER_SUBMITTED`
- `ORDER_DRAFT_CREATED`
- `ORDER_VALIDATED`
- `ORDER_ACCEPTED`
- `ORDER_REJECTED`
- `ORDER_ALREADY_ACCEPTED`
- `ORDER_STATUS_VIEWED`
- `ORDER_STATUS_LOOKUP_FAILED`
- `ORDER_STATUS_UPDATED`
- `ORDER_STATUS_UPDATE_FAILED`
- `ORDER_NEEDS_HUMAN`

## Payment Events

- `PAYMENT_REQUIRED`
- `PAYMENT_MODE_CHANGED`
- `PAYMENT_FAILED`

## Printer And Operator Events

- `PRINT_REQUESTED`
- `PRINT_SUCCESS_CONFIRMED`
- `PRINT_FAILED_PRECHECK`
- `PRINT_UNCERTAIN`
- `PRINT_TIMEOUT`
- `PRINTER_OFFLINE`
- `PAPER_LOW`
- `PAPER_OUT`
- `PAPER_JAM`
- `NOTIFICATION_SENT`
- `NOTIFICATION_FAILED`

## Connectivity And Retry Events

- `OUTBOUND_ACTION_REQUESTED`
- `NODE_CONNECTIVITY_LOST`
- `LOCAL_QUEUE_STORED`
- `RETRY_SCHEDULED`
- `ACTION_RETRIED`
- `ACTION_COMPLETED`

## Trust Events

- `NODE_IDENTITY_DECLARED`
- `TRUST_CLAIM_REQUESTED`
- `TRUST_CLAIM_EMITTED`
- `CVR_MATCH_CONFIRMED`
- `CVR_MATCH_MISSING`

## Outcome Reminder

These event names are not the same thing as result outcomes.

Outcome values still live separately in the execution contract:

- `SUCCESS`
- `FAILED_RETRYABLE`
- `FAILED_PERMANENT`
- `TIMEOUT_UNKNOWN`
- `UNAVAILABLE`
- `NEEDS_INPUT`
- `NEEDS_HUMAN`
