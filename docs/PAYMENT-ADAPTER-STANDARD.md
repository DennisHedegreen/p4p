# P4P Payment Adapter Standard

Status: draft guardrail for the pilot-node module work.

P4P must not become a payment provider. The payment layer is a routing and adapter boundary where a restaurant-owned node selects a module and hands a payment request to that module.

## Boundary

P4P Core may:

- build an order
- select the node's active payment module
- send a payment request to that module
- receive module result events such as `PAYMENT_MODE_CHANGED` or `PAYMENT_FAILED`
- expose operator status for installed, active, configured, and reachable modules

P4P Core must not:

- hold customer funds
- store card, wallet, or bank credentials
- issue a payment instrument
- act as merchant of record
- settle funds
- own refunds, chargebacks, or disputes
- describe a fake test ledger as real money or crypto

## Adapter Shape

A payment adapter is a module manifest plus an implementation endpoint.

The manifest declares:

- `module_id`
- `provider_id`
- `module_class: payment`
- input and output events
- required configuration
- data access
- fallback modules
- readiness and operator status

The implementation receives an order-scoped payment request and returns module result state. The pilot node currently treats `p4p.payment.cash` as the built-in reference adapter and can execute imported HTTP payment modules such as `local.pizzacoin.wallet`.

## Operator Status

Operator tooling should show the difference between:

- a module the node has listed
- a module with a loaded manifest
- the active payment module
- a module with required configuration present
- a module that can currently be reached

The pilot node exposes this through:

```text
GET /operator/modules
```

The endpoint is operator-token protected. It is for local operation and GUI surfaces, not for public discovery.

## Test Ledger Rule

`Pizzacoin` is only a sandbox ledger for local experiments. It is useful for testing adapter boundaries, module health, fake balances, idempotency, and failure paths.

It must not be presented as a real coin, redeemable value, customer balance product, or production payment method.
