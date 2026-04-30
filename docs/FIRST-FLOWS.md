# P4P First Flows

Status: planned `v0.2` flow pack.

This file turns the module-execution doctrine into a few concrete first flows.

It is intentionally small.

The goal is not to map every future module class.

The goal is to prove a disciplined event and fallback model without hiding logic inside one monolith.

## 1. Core Reminder

These flows sit on top of the core:

- registry discover
- node identity
- menu endpoint
- order endpoint
- order-consent state

Registry and identity are not modules here.

They are the base the flows run on.

## 2. First MVP Modules

The first practical bundle should stay small:

1. `registry.basic` as core registry runtime, not a module
2. `identity.restaurant_key` as core trust runtime, not a module
3. `p4p.menu.photo-hotspots`
4. `p4p.order.receiver`
5. `p4p.order.print.primary`
6. `p4p.notify.dashboard`
7. `p4p.notify.sms`
8. `p4p.payment.cash-at-pickup`

Optional next-after:

- `p4p.menu.ai-builder`
- `p4p.order.print.backup`

## 3. Flow A: Photo Menu To Printed Order

Purpose:

prove that a small restaurant can keep its existing menu reality and still move into a structured direct-order flow.

### Flow

```text
CUSTOMER_MENU_AREA_SELECTED
-> p4p.menu.photo-hotspots
-> ORDER_ITEM_CREATED
-> p4p.order.receiver
-> ORDER_DRAFT_CREATED
-> ORDER_VALIDATED
-> ORDER_ACCEPTED
-> p4p.order.print.primary
-> PRINT_SUCCESS_CONFIRMED
```

### Notes

- `p4p.menu.photo-hotspots` is a menu-entry module, not the public menu endpoint itself
- `p4p.order.receiver` is the order-path module that creates order state and enforces idempotency
- printer sits after order acceptance, not before

## 4. Flow B: Printer Failure To Human Escalation

Purpose:

prove the fallback principle on one concrete operational problem.

### Flow

```text
ORDER_ACCEPTED
-> p4p.order.print.primary
-> PRINTER_OFFLINE
-> node fallback policy
-> p4p.order.print.backup
-> PRINT_FAILED_PRECHECK
-> node fallback policy
-> p4p.notify.dashboard
-> NOTIFICATION_SENT
-> p4p.notify.sms
-> NOTIFICATION_SENT
-> ORDER_NEEDS_HUMAN
```

### Rules

- printer does not decide the whole chain
- printer reports result only
- orchestrator decides whether backup printer, dashboard, or SMS is next
- duplicate printing must be blocked by `idempotency_key`

### Important uncertainty rule

If the primary printer returns `PRINT_UNCERTAIN` or a result with outcome `TIMEOUT_UNKNOWN`, the node should not blindly auto-print again.

That should usually produce:

```text
PRINT_UNCERTAIN
-> dashboard alert
-> operator check
-> human decision
```

not:

```text
PRINT_UNCERTAIN
-> print again immediately
```

## 5. Flow C: AI Menu Builder To Manual Menu Fallback

Purpose:

allow AI assistance without letting AI invent unsupported items.

### Flow

```text
CUSTOMER_INTENT_SUBMITTED
-> p4p.menu.ai-builder
-> ITEM_NOT_POSSIBLE
-> node fallback policy
-> p4p.menu.photo-hotspots
-> CUSTOMER_MENU_AREA_SELECTED
-> ORDER_ITEM_CREATED
```

### Rules

- AI may choose only among real restaurant options
- AI must never invent toppings, sizes, or products
- failure of the AI module is not a failure of the whole order path
- manual selection is the honest fallback

## 6. Flow D: Payment Unavailable To Pay At Pickup

Purpose:

keep payment modular and stop the protocol from collapsing into one provider.

### Flow

```text
PAYMENT_REQUIRED
-> p4p.payment.stripe
-> UNAVAILABLE
-> node fallback policy
-> p4p.payment.cash-at-pickup
-> PAYMENT_MODE_CHANGED
```

### Rules

- payment is a module, not core protocol truth
- fallback from online payment to cash at pickup is promise-changing
- the node policy must explicitly allow it
- customer-visible state should make the changed payment mode clear

## 7. Flow E: Duplicate Order Protection

Purpose:

prove that retries and fallbacks do not create chaos.

### Flow

```text
ORDER_SUBMITTED
-> p4p.order.receiver
-> ORDER_ACCEPTED(order_id=ord_123, idempotency_key=order:abc)

ORDER_SUBMITTED again with same key
-> p4p.order.receiver
-> ORDER_ALREADY_ACCEPTED(order_id=ord_123, idempotency_key=order:abc)
```

### Rules

- same order key must not create a second accepted order
- same print key must not create a second confirmed print
- same payment key must not charge twice

## 8. Flow F: Node Offline To Local Queue And Retry

Purpose:

make temporary connectivity failure survivable without pretending nothing happened.

### Flow

```text
OUTBOUND_ACTION_REQUESTED
-> local node runtime
-> NODE_CONNECTIVITY_LOST
-> LOCAL_QUEUE_STORED
-> RETRY_SCHEDULED
-> ACTION_RETRIED
-> ACTION_COMPLETED
```

### Notes

- this is node-runtime behavior more than a public module
- queue state should still produce typed events
- if the action state becomes uncertain, escalate instead of silently replaying forever

## 9. First Frozen Event Set

The first canonical event-name freeze now lives in:

- `docs/EVENT-CATALOG.md`
- `docs/schemas/module-event-name.schema.json`

The first frozen set is:

- `CUSTOMER_MENU_AREA_SELECTED`
- `CUSTOMER_INTENT_SUBMITTED`
- `ORDER_ITEM_CREATED`
- `OPTIONS_REQUIRED`
- `ITEM_NOT_POSSIBLE`
- `ORDER_SUBMITTED`
- `ORDER_DRAFT_CREATED`
- `ORDER_VALIDATED`
- `ORDER_ACCEPTED`
- `ORDER_REJECTED`
- `ORDER_ALREADY_ACCEPTED`
- `PAYMENT_REQUIRED`
- `PAYMENT_MODE_CHANGED`
- `PAYMENT_FAILED`
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
- `OUTBOUND_ACTION_REQUESTED`
- `NODE_CONNECTIVITY_LOST`
- `LOCAL_QUEUE_STORED`
- `RETRY_SCHEDULED`
- `ACTION_RETRIED`
- `ACTION_COMPLETED`
- `ORDER_NEEDS_HUMAN`
- `NODE_IDENTITY_DECLARED`
- `TRUST_CLAIM_REQUESTED`
- `TRUST_CLAIM_EMITTED`
- `CVR_MATCH_CONFIRMED`
- `CVR_MATCH_MISSING`

## 10. First Practical Reading

The point of these flows is not completeness.

The point is to establish the first clean reading:

- core protocol stays small
- modules are replaceable
- modules report status
- node policy chooses fallback
- idempotency prevents duplicate damage

Short version:

`Registry finds.`

`Node governs.`

`Modules execute.`

`Events report.`

`Fallback rescues.`

`Keys prevent chaos.`
