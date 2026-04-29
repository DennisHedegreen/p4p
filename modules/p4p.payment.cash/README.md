# p4p.payment.cash

Minimal example module for P4P.

This module means:

The restaurant accepts cash or direct in-person payment outside the P4P protocol.

It does not process payment.

It does not relay orders.

It does not change discovery.

## Why This Is The First Module

The first module should prove the module boundary, not payment complexity.

`p4p.payment.cash` is useful because it has almost no moving parts:
- no external API
- no checkout redirect
- no account system
- no card data
- no registry role

It lets the node announce an optional capability while core P4P still works without it.

## v0.1 Behavior

In `v0.1`, this module is only an opaque module id:

```json
"modules": ["p4p.payment.cash"]
```

Clients may display it.

Clients should not treat it as a certified payment guarantee.

## Future v0.2 Behavior

In `v0.2`, this module can become a signed module manifest with:
- provider identity
- version
- data access
- terms
- trust claims

It should still require no registry permission.

