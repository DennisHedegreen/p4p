# p4p.payment.godpay-mock

Internal debug payment mock for pilot-node.

It asks the pizza gods whether a test payment should pass:

- roll: `1..100`
- success when `roll <= P4P_GODPAY_SUCCESS_THRESHOLD`
- default threshold: `50`

This is not payment. It does not hold money, settle funds, issue value, or contact a provider.

Useful local knobs:

```bash
P4P_PAYMENT_MODULE_ID=p4p.payment.godpay-mock
P4P_GODPAY_SUCCESS_THRESHOLD=50
P4P_GODPAY_SEED=debug-seed
P4P_GODPAY_FORCE_ROLL=42
```

`P4P_GODPAY_FORCE_ROLL` is only for deterministic tests.
