# P4P Payment Adapter Standard

Status: public guardrail for payment-related modules.

P4P must not become a payment provider.

The payment layer is a routing and adapter boundary where a restaurant-owned node chooses a module and hands an order-scoped payment request to that module.

## Boundary

P4P Core may:

- build an order
- let a node/operator select a payment module
- hand a payment request to that module
- receive payment-status events from that module
- expose module status to the node operator

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

The implementation may connect to an external provider, mark a local payment mode, or simulate payment behavior for tests.

That does not make P4P the payment provider.

## Public Wording Rule

Do not call this `P4P Pay`.

Do not describe P4P as handling payment, settlement, refunds, chargebacks, customer balances, wallets, or provider compliance.

If a module talks to a real payment provider, the module must say who owns the merchant relationship and which external provider handles payment, confirmation, settlement, refunds, and disputes.

If a module is fake, mock, sandbox, or local-only, it must say so clearly.

## Test Module Rule

Internal or community mock payment modules may exist to test P4P flow behavior.

They must stay operator/test-facing.

They must not be described as providers, funds movement, wallets, settlement, crypto, redeemable value, or production payment methods.
