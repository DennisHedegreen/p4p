# p4p.stock.basic

Minimal stock-check reference module for P4P.

This module means:

The node can do a final local stock check after an order is accepted and before the next operator lane continues.

It does not own the menu.

It does not define a universal order sequence.

It only proves that a node can insert an inventory decision between other modules without turning that decision into a new wire-level requirement.

## Why This Module Exists

`p4p.stock.basic` is the first reference example of an in-between module.

It shows that a flow can legally become:

`ORDER_ACCEPTED -> ORDER_VALIDATED -> ...`

or:

`ORDER_ACCEPTED -> ITEM_NOT_POSSIBLE -> ORDER_NEEDS_HUMAN`

without forcing every node to have the same ladder.

## v0.1 Behavior

In `v0.1`, this module is still just a declared module id plus a local execution contract.

Clients do not need to understand the full stock logic.

The important part is that the node can declare the module and validate the extra step honestly.

## Future v0.2 Behavior

In `v0.2`, this module can become a richer manifest with:
- provider identity
- stock freshness policy
- reservation semantics
- failure and fallback rules

The core protocol can still stay smaller than the module graph built on top of it.
