# P4P Hackathon Packet

*Brussels 2026 team packet*

This is not the whitepaper.

This is not the full repo story either.

This is the shorter packet for the group:

- what the team can actually build
- what the team should not claim
- which repo lanes and modules already exist
- what kind of follow-up help would matter if the demo lands

## 1. The Claim We Align Around

The shortest honest claim is:

`direct pickup ordering for local takeaway shops without marketplace capture`

That means:

- the customer reaches the shop directly
- the shop keeps the order path
- discovery can be public without making the registry an order relay

## 2. What We Can Finish Together In The Hackathon

### Minimum demo

- [ ] one shop page and readable menu
- [ ] QR code or direct link
- [ ] simple pickup-order flow
- [ ] small operator screen
- [ ] order status: `received`
- [ ] order status: `ready`
- [ ] payment at pickup first

### Stronger if time allows

- [ ] one small registry for discovery
- [ ] one small node endpoint for menu + order
- [ ] explicit `order_mode`
- [ ] request trace that proves `menu` and `order` hit the node directly
- [ ] backup registry failover for discovery

## 3. What We Say Honestly In The Room

- This is a proof of direct ordering, not a finished business rollout.
- This is a prototype, not a production restaurant system.
- The value is the boundary:
  discovery can be public without giving the order path to a marketplace.
- The team is testing whether a shop can stay directly reachable.

## 4. Keep Out Of Scope

- online payment integration
- delivery logistics
- customer accounts or loyalty systems
- large admin dashboards
- full federation story
- production security claims
- legal overpromises
- pretending the whole repo is the demo

## 5. Repo Lanes The Group Can Pick From

- `registry/`
  discovery lane: announce, heartbeat, discover, backup-registry story
- `demo-node/`
  smallest protocol proof node with direct menu and order path
- `pilot-node/`
  more real restaurant-shaped node with operator rooms, SQLite state, and optional module lanes
- `client/`
  simple public customer flow and menu/order surface
- `docs/` + `tests/`
  one-pagers, packet, demo script, proof language, and smoke path

## 6. Modules The Group Can Actually Use

### Public customer side

- `p4p.menu.list`
  plain customer menu surface
- `p4p.payment.cash`
  pay-at-pickup boundary without pretending P4P is a payment company
- `p4p.customer.status`
  read-only order status after submission

### Operator side

- `p4p.kitchen.screen`
  operator queue for incoming and ready orders
- `p4p.catalog.editor`
  restaurant-owned menu/catalog truth
- `p4p.pickup.board.basic`
  simple local pickup counter board

### Good optional add-ons if time allows

- `p4p.menu.photo-map`
  more visual paper-menu style customer surface
- `p4p.stock.basic`
  simple stock check before the order proceeds
- `p4p.catalog.import.ocr`
  draft OCR/scanned-menu helper beside the catalog editor
- `p4p.order.alert.basic`
  local alert/bell self-test lane
- `p4p.order.print.backup`
  backup print/spool self-test lane

## 7. Keep On GitHub, Not In The Room Claim

- `p4p.payment.godpay-mock` and `p4p.payment.chaospay-mock`
  internal mock/debug lanes only
- `p4p.payment.mobilepay`
  planned external adapter invitation, not a live payment claim
- `p4p.order.print`
  printer/POS direction, not first honest demo requirement
- `p4p.notify.email` and `p4p.notify.sms`
  planned fallback notification directions
- `p4p.trust.cvr-basic`
  later trust/CVR direction, not first hackathon scope

## 8. Choose One Build Shape

- Use `pilot-node/` if the group wants a more believable operator surface with modules.
- Use `demo-node/` if the group wants the smallest technical proof first.
- Use `client/` or a very thin custom surface for the customer flow.
- Bring in `registry/` only if someone on the team wants the deeper protocol boundary and can keep it explained simply.

## 9. One Clean GitHub Split For Five People

- one person on `registry/`
- one person on `demo-node/` or `pilot-node/`
- one person on `client/`
- one person on operator/module polish
- one person on docs, one-pagers, and live demo order

Practical rule:

- one owner per lane
- one shared merge point
- do not let everybody edit everything at once

## 10. What Success Looks Like For The Group

- [ ] A customer opens a QR code or direct link.
- [ ] The customer sees the shop page and menu.
- [ ] The customer places a pickup order.
- [ ] The shop sees the order on its operator screen.
- [ ] The order can move from `received` to `ready`.
- [ ] The team can explain in one sentence why this is different from a platform marketplace.
- [ ] If using the technical variant, the team can show that discovery used a registry but the order did not go through the registry.

## 11. Longer-Term Path

### Phase 1: tighten the packet

- clean the repo story and public reading path
- keep the non-technical and technical one-pagers aligned
- show one short demo path outsiders can follow fast
- write the fuller whitepaper later as a separate job

### Phase 2: controlled real pilot

- one real takeaway or food-service partner
- real QR, menu, pickup, operator flow, and local hardware truth
- honest log of what breaks in practice

### Phase 3: module maturation

- printer / kitchen ticket lane
- local node / local box lane
- better stock, alert, and pickup-board reliability
- later payment adapters, trust, and certification lanes if the pilot is real

## 12. What Help Would Actually Matter

- one real pilot partner
- small follow-up funding or incubation
- legal and regulatory guidance around ordering, receipts, and consumer rules
- multilingual or cross-country testing support
- one public-interest or civic-tech partner that cares about local digital resilience

## 13. Group Debrief

After the presentation, the team should ask:

- [ ] Did people understand the problem quickly?
- [ ] Did they understand why this is not just another food app?
- [ ] Did the direct-order boundary feel meaningful?
- [ ] Did anyone ask for the technical version?
- [ ] Did anyone offer a real pilot path?
- [ ] Did the room push us toward too much scope?
- [ ] Which modules sounded real and useful to outsiders?
- [ ] What should be cut or clarified before the next presentation?

## 14. Final Boundary

The team does not need to prove the whole future of food ordering.

It only needs to prove:

- that a shop can stay directly reachable
- that the order path can stay out of platform capture
- that the surrounding software can stay modular instead of collapsing back into one platform owner
