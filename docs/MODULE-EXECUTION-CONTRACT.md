# P4P Module Execution Contract

Status: planned `v0.2` design contract.

This file does not change the active `v0.1` wire payloads.

Its purpose is to lock the next layer before the code drifts into hidden module spaghetti.

The first concrete draft now lives in:

- `docs/schemas/provider-manifest.schema.json`
- `docs/schemas/module-manifest.schema.json`
- `docs/schemas/module-event-name.schema.json`
- `docs/schemas/node-module-declaration.schema.json`
- `docs/schemas/module-result-event.schema.json`
- `docs/EVENT-CATALOG.md`
- `docs/examples/provider-manifest.json`
- `docs/examples/module-manifest-print-primary.json`
- `docs/examples/node-module-declaration.json`
- `docs/examples/module-result-event-print-timeout.json`
- `modules/*/(provider|module).json` as reference manifests

## 1. Core Rule

P4P is not an app with features.

P4P is a protocol with a small core and optional modules around it.

The core stays:

- node identity
- node announce
- node heartbeat
- registry discover
- node menu endpoint
- node order endpoint
- node order-consent state
- direct client-to-node menu and order flow

If removing something breaks basic discovery and direct pickup ordering, that thing is too deep to be a module.

## 2. What A Module Is

A module is a replaceable execution unit that:

1. receives a command or event
2. performs one scoped action
3. returns a typed result
4. lets the node orchestrator decide the next step

Short form:

`event in -> action -> status out -> orchestrator decides next step`

Modules do not own the whole flow.

Modules do not call each other freely.

Modules report results.

The node decides fallback.

## 3. What Is Not A Module

These are not modules:

- the registry protocol itself
- the node identity model
- the node menu endpoint
- the node order endpoint
- the node operator layer as a whole

Registry, identity, menu, and order are core protocol boundaries.

The node operator layer may enable, disable, and configure modules.

That does not make node operation a module.

## 4. Node Orchestrator Rule

The orchestrator is node-local.

That means:

- fallback policy lives with the node
- module activation lives with the node operator layer
- private module credentials live with the node
- the registry does not decide which module runs next

The long-term protocol may define portable flow and event contracts.

It must not require one central orchestration service.

## 5. Module Lanes

Not every module is the same kind of thing.

The first execution contract distinguishes these lanes:

### 5.1 Public Capability Modules

Visible to clients or customers as part of the service offer.

Examples:

- payment
- delivery
- pickup mode
- customer-facing status

### 5.2 Operator Modules

Internal modules behind the node.

Examples:

- printer
- email notification
- dashboard alert
- POS forwarding
- accounting export

These should normally not be advertised as public customer capabilities.

### 5.3 Trust Modules

Modules that produce claims or verification evidence.

Examples:

- CVR lookup
- trust-list review
- signed provider claim

These belong to trust and directory logic, not to the direct customer order path by default.

### 5.4 Observability Modules

Modules that measure or log system state without owning discovery or order truth.

Examples:

- uptime checks
- delivery telemetry
- network evidence later

## 6. Standard Module Description

Each module should eventually describe itself in a standard manifest shape.

Illustrative direction:

```json
{
  "module_id": "p4p.order.print.primary",
  "module_class": "printer",
  "lane": "operator",
  "provider_id": "p4p.reference",
  "version": "0.1",
  "visibility": "operator_only",
  "capabilities": ["print_order", "report_status"],
  "input_events": ["ORDER_ACCEPTED", "PRINT_REQUESTED"],
  "output_events": [
    "PRINT_SUCCESS_CONFIRMED",
    "PRINT_FAILED_PRECHECK",
    "PRINT_TIMEOUT",
    "PRINT_UNCERTAIN",
    "PRINTER_OFFLINE",
    "PAPER_LOW",
    "PAPER_OUT",
    "PAPER_JAM"
  ],
  "permissions": [
    "read.order.summary",
    "read.order.items",
    "read.order.note"
  ],
  "blocking_policy": "fallback_required",
  "suggested_fallbacks": {
    "PRINTER_OFFLINE": ["p4p.order.print.backup", "p4p.notify.sms"],
    "PRINT_TIMEOUT": ["p4p.order.print.backup", "p4p.notify.sms"]
  },
  "idempotency_scope": "order_print",
  "failure_modes": ["PRINTER_OFFLINE", "PAPER_OUT", "PRINT_TIMEOUT", "PRINT_UNCERTAIN"]
}
```

This is the design target.

It is not yet an active `v0.1` runtime manifest schema.

## 7. Required Fields

Each real module contract should eventually define:

- `module_id`
- `module_class`
- `lane`
- `provider_id`
- `version`
- `visibility`
- `capabilities`
- `input_events`
- `output_events`
- `permissions`
- `blocking_policy`
- `idempotency_scope`

Optional but strongly recommended:

- `suggested_fallbacks`
- `failure_modes`
- `required_configuration`
- `data_access_summary`

## 8. Visibility

Visibility controls who should normally see the module.

Allowed values:

- `public`
- `operator_only`
- `trust_only`

Meaning:

- `public`: may be surfaced to clients as part of the node's visible capabilities
- `operator_only`: internal operational module, not a public capability announcement
- `trust_only`: trust, evidence, or claim layer, not ordinary order-path capability

## 9. Blocking Policy

Not every module should block the flow.

Allowed values:

- `blocking`
- `non_blocking`
- `fallback_required`

Meaning:

- `blocking`: flow may not continue automatically until the module returns a final result
- `non_blocking`: flow may continue and treat the module as side-work
- `fallback_required`: the flow may continue only if a valid fallback path resolves the failure

Examples:

- payment authorization may be `blocking`
- printer may be `fallback_required`
- email confirmation may be `non_blocking`

## 10. Event Model

Modules should not expose ad hoc strings with no structure.

The node should treat results as typed events.

Illustrative event envelope:

```json
{
  "event": "PRINT_TIMEOUT",
  "source_module": "p4p.order.print.primary",
  "order_id": "ord_123",
  "action_id": "act_456",
  "idempotency_key": "print:ord_123:primary:v1",
  "outcome": "FAILED_RETRYABLE",
  "reason_code": "USB_TIMEOUT",
  "severity": "high",
  "retryable": true,
  "side_effect_state": "unknown",
  "timestamp": "2026-04-30T12:10:00Z"
}
```

The exact wire shape may change.

The rule should not.

## 11. Canonical Outcome Model

Concrete events such as `PRINTER_OFFLINE` or `ITEM_NOT_POSSIBLE` are useful.

But every module result should also map to one canonical outcome family:

- `SUCCESS`
- `FAILED_RETRYABLE`
- `FAILED_PERMANENT`
- `TIMEOUT_UNKNOWN`
- `UNAVAILABLE`
- `NEEDS_INPUT`
- `NEEDS_HUMAN`

This gives the orchestrator a stable language across different module classes.

## 12. Permission Scopes

Modules should receive explicit scopes, not vague trust.

Illustrative scope families:

- `read.order.summary`
- `read.order.items`
- `read.order.customer_contact`
- `read.order.delivery_address`
- `read.menu.options`
- `read.node.identity_public`
- `read.node.operator_config`
- `write.order.draft`
- `write.order.status`
- `write.payment.state`
- `write.delivery.state`
- `emit.notification.sent`
- `emit.trust.claim`
- `store.provider_secret`

Rules:

- give the module only the scopes it actually needs
- do not leak payment or identity data to a printer module
- do not give a notification module the right to rewrite order truth
- do not give trust modules hidden power over core discoverability

## 13. Fallback Rule

Fallback is not module-to-module chaos.

Fallback is node policy.

That means:

1. module executes
2. module reports typed result
3. orchestrator reads fallback policy
4. orchestrator chooses next action

Modules may declare `suggested_fallbacks`.

They do not own the final fallback chain.

Why:

- the same module may be used in different restaurant policies
- one node may treat printer failure as critical
- another may accept dashboard-only fallback for test orders
- one fallback may change the customer promise and require confirmation

## 14. Transparent vs Promise-Changing Fallback

Not all fallbacks are equal.

### 14.1 Transparent Fallback

Does not materially change the customer promise.

Examples:

- primary printer -> backup printer
- email alert -> dashboard alert
- local retry after short timeout

### 14.2 Promise-Changing Fallback

Changes payment, pickup, delivery, or responsibility.

Examples:

- Stripe -> cash at pickup
- trusted-circle pickup -> self pickup
- AI item builder -> manual item selection
- restaurant driver -> third-party runner

Promise-changing fallback should normally require explicit policy approval and often customer or operator confirmation.

## 15. Idempotency Rule

Fallback must not create duplicate side effects.

That means:

- do not print the same order twice unless the state proves the first print did not complete
- do not charge payment twice
- do not issue two pickup delegations for the same role
- do not accept the same delivery twice

Every module execution that may cause a side effect should carry an `idempotency_key`.

Every module should define its `idempotency_scope`.

Examples:

- `order_accept`
- `order_print`
- `payment_attempt`
- `pickup_delegate_issue`

If the same idempotency key is seen again:

- return the known result if the action was already resolved
- refuse duplicate execution if the previous action is still authoritative
- escalate to `NEEDS_HUMAN` if the side-effect state is uncertain

## 16. Sensor And Evidence Rule

Modules may use sensors or local evidence sources internally.

Example:

- printer precheck
- printer postcheck
- paper sensor
- drawer sensor

That evidence belongs inside the module's result logic.

The sensor does not orchestrate fallback by itself.

It improves the honesty of the reported status.

Short rule:

`not just action attempted, but action evidenced`

## 17. First Event Families To Lock

The first practical families should be:

- order draft events
- order validation events
- order acceptance/rejection events
- payment result events
- printer result events
- notification result events
- delivery/pickup result events
- human-escalation events

The canonical name list now lives in `EVENT-CATALOG.md` and `docs/schemas/module-event-name.schema.json`.

Illustrative examples:

- `ORDER_DRAFT_CREATED`
- `ORDER_VALIDATED`
- `ORDER_ACCEPTED`
- `ORDER_REJECTED`
- `PAYMENT_REQUIRED`
- `PAYMENT_FAILED`
- `PRINT_REQUESTED`
- `PRINT_SUCCESS_CONFIRMED`
- `PRINT_UNCERTAIN`
- `ORDER_NEEDS_HUMAN`

## 18. First Practical Rule Set

For the near-term P4P box, the execution contract should support these first flows:

- menu photo selection into order draft
- manual order validation
- accepted order to printer
- printer failure to alert fallback
- unavailable payment module to pay-at-pickup fallback
- AI menu builder to manual menu fallback

See `FIRST-FLOWS.md` for the first concrete flow sketches.
