# Start Here

P4P is an open protocol for direct restaurant discovery and ordering.

The plain-language idea is simple:

> A restaurant can be found in public while its menu, orders, and customer relationship remain direct between the customer and the restaurant.

P4P is a phone book, not a marketplace. It is the socket, not the appliances.

Public explainer: <https://pizza4people.com/start/>

## A Concrete Pizzeria Example

1. A customer searches an open registry for nearby restaurants.
2. The registry returns the address of a restaurant node.
3. The customer client fetches the menu directly from that node.
4. The customer sends the order directly to that node.
5. After discovery, the registry is out of the order flow.

```text
customer -> registry -> restaurant address
customer ------------> restaurant node -> menu and order
```

The registry helps the two sides find each other. It does not receive the order, own the customer, or become the restaurant's operating system.

## Three Terms

### Node

The restaurant-owned endpoint or computer where its menu, orders, and local state live.

### Registry

The phone book. It lets a node announce where it can be reached and lets a customer discover that address.

### Module

An optional, replaceable tool around the core. Examples include printing, a kitchen display, notifications, stock handling, and a payment adapter.

The core should still work when optional modules are changed or removed.

## What P4P Does

- defines an open discovery and ordering flow
- keeps the restaurant node primary after discovery
- lets the restaurant own its local state and operations
- keeps extra capabilities replaceable as modules
- makes the proof and its limits inspectable in public

## What P4P Does Not Do

- hold or settle funds
- process or store payment credentials
- act as merchant of record
- own customer accounts or the customer relationship
- rank restaurants or hide them behind a marketplace
- claim broad production readiness today

Payment can be added through adapters selected by the restaurant. P4P itself does not become the payment provider.

## What Works Today

The current public `v0.1` proof demonstrates:

- registry discovery
- direct menu fetch from the restaurant node
- direct order submission to the restaurant node
- failover between registries for discovery

This is an advanced prototype with real code and tests. The next gate is a controlled live pilot on a restaurant-owned node.

It is not yet a broad production service.

## Choose Your Route

If you run a restaurant:

1. Read [`PILOT-LIVE.md`](PILOT-LIVE.md).
2. Look at the operator surfaces in [`pilot-node/README.md`](pilot-node/README.md).
3. Check the current deployment boundary in [`deploy/README.md`](deploy/README.md).

If you are a developer:

1. Read [`SPEC.md`](SPEC.md).
2. Read [`ARCHITECTURE.md`](ARCHITECTURE.md).
3. Reproduce the checks with [`TEST-GUIDE.md`](TEST-GUIDE.md).

If you want to review the claims:

1. Follow [`REVIEW-ME.md`](REVIEW-ME.md).
2. Read the canonical claim in [`PROOF.md`](PROOF.md).
3. Check the dated record in [`docs/PROOF-STATUS.md`](docs/PROOF-STATUS.md).

If you want the longer explanation:

1. Read [`docs/WHITEPAPER-v0.1.md`](docs/WHITEPAPER-v0.1.md).
2. Use [`docs/GITHUB-READER-GUIDE.md`](docs/GITHUB-READER-GUIDE.md) to navigate the rest of the repository.

## Four Short Answers

**Is P4P an app?**

No. It is a protocol and a small base that different apps and tools can use.

**Can a restaurant use it now?**

Not as a broad production service yet. The next honest milestone is a controlled live pilot.

**Why pizza?**

A narrow, concrete restaurant flow is easier to build, test, and challenge than an abstract platform.

**Why not just use a marketplace?**

A marketplace can still be useful. P4P tests whether basic discovery and ordering can also exist without one company owning first contact, order routing, and the customer relationship.
