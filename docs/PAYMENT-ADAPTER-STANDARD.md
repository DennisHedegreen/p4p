# P4P Payment Adapter Standard

Status: public guardrail for payment-related modules.

P4P must not become a payment provider.

The payment layer is a routing and adapter boundary where a restaurant-owned node chooses an active module and hands an order-scoped payment request to that module.

## Boundary

P4P Core may:

- build an order
- select the node's active payment module
- send a payment request to that module
- receive module result events such as `PAYMENT_MODE_CHANGED` or `PAYMENT_FAILED`
- expose operator status for installed, active, configured, and reachable modules

P4P Core must not:

- hold customer funds
- process payments
- store card, wallet, or bank credentials
- issue a payment instrument
- act as merchant of record
- settle funds
- own refunds, chargebacks, or disputes
- describe a fake test ledger as real money or crypto

## Adapter Shape

A payment adapter is a module manifest plus an implementation chosen by the restaurant/operator.

The manifest should declare:

- `module_id`
- `provider_id`
- `module_class: payment`
- input and output events
- required configuration
- data access
- fallback behavior
- readiness and operator status

The implementation receives an order-scoped payment request and returns module result state. The pilot node currently treats `p4p.payment.cash` as the built-in reference adapter and can execute imported HTTP payment modules such as `local.pizzacoin.wallet`.

That does not make P4P the payment provider.

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

## Public Wording Rule

Do not call this `P4P Pay`.

Do not describe P4P as handling payment, settlement, refunds, chargebacks, customer balances, wallets, or provider compliance.

If a module talks to a real payment provider, the module must say who owns the merchant relationship and which external provider handles payment, confirmation, settlement, refunds, and disputes.

If a module is fake, mock, sandbox, or local-only, it must say so clearly.

## Test Ledger Rule

`Pizzacoin` is only a sandbox ledger for local experiments. It is useful for testing adapter boundaries, module health, fake balances, idempotency, and failure paths.

It must not be presented as a real coin, redeemable value, customer balance product, or production payment method.

## Internal Mock Rule

Internal mock payment modules may exist to test P4P flow behavior.

Current internal mocks:

- `p4p.payment.godpay-mock`: executable random success/failure debug module.
- `p4p.payment.chaospay-mock`: planned chaos-scenario module for later edge-case testing.

These modules must stay operator/test-facing. They must not be described as providers, funds movement, wallets, settlement, crypto, redeemable value, or production payment methods.
