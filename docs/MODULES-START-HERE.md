# Modules Start Here

This file is for people who land on the P4P module layer without already knowing what a module is.

It is the short human explanation.

It is not the full module contract.

## In One Line

A module is an optional add-on around the small P4P core.

The core stays:

- discovery
- direct menu fetch
- direct order submission

Everything around that may later be modular.

## Plain Example

Think like this:

- P4P core = the road
- modules = the things you may attach around the road

Good module examples:

- a kitchen screen
- a printer handoff
- a pickup board
- a payment adapter
- a stock check
- an operator alert

Bad module examples:

- registry discovery itself
- the node menu endpoint itself
- the node order endpoint itself

If removing something breaks basic restaurant discovery or direct ordering, it is too deep to be "just a module".

## Why This Exists

P4P is trying to avoid one big platform owning everything.

That means:

- the restaurant should be able to keep its own menu and order flow
- the protocol core should stay small
- extra tools should compete around the core instead of becoming the core

## What A Module Does Not Mean

A module existing in the repo does not automatically mean:

- it is live
- it is trusted
- it is production-ready
- it is part of the current public proof claim
- P4P core owns it forever

Some modules are reference modules.

Some are internal mocks.

Some are planned only.

Some may later belong to outside developers or providers.

## The Most Important Boundaries

Payment:

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

So payment modules are adapters, not "P4P becomes a payment company".

Discovery:

The registry may help the customer find a restaurant.

It must not quietly become the place where the order actually lives.

Operator tools:

A kitchen screen, pickup board, or alert is support around the node.

It must not be confused with the core protocol claim.

## If You Want To Read Just Three Module Examples

Start here:

1. [`modules/p4p.menu.list.md`](modules/p4p.menu.list.md)
2. [`modules/p4p.kitchen.screen.md`](modules/p4p.kitchen.screen.md)
3. [`modules/p4p.payment.cash.md`](modules/p4p.payment.cash.md)

Then read:

4. [`modules/p4p.order.print.backup.md`](modules/p4p.order.print.backup.md)
5. [`modules/p4p.pickup.board.basic.md`](modules/p4p.pickup.board.basic.md)

That gives you one customer surface, one operator surface, one payment boundary, and two pilot hardware lanes.

## If You Want To Build One

Read in this order:

1. [`COMMUNITY-MODULES.md`](COMMUNITY-MODULES.md)
2. [`modules/README.md`](modules/README.md)
3. [`MODULE-RULES.md`](MODULE-RULES.md)
4. [`MODULE-PROVIDERS.md`](MODULE-PROVIDERS.md)
5. [`MODULE-EXECUTION-CONTRACT.md`](MODULE-EXECUTION-CONTRACT.md)

## If You Want To Judge Whether The Whole Idea Is Sensible

Read:

1. [`../REVIEW-ME.md`](../REVIEW-ME.md)
2. [`../ARCHITECTURE.md`](../ARCHITECTURE.md)
3. [`../PROOF.md`](../PROOF.md)

The real question is not "does this repo have many modules?"

The real question is:

does the core stay small while the extras stay optional?
