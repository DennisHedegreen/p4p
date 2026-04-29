# P4P Order Consent

This document defines the current order-consent boundary.

Discovery is not consent.

A node can be listed in a registry before a restaurant accepts live orders.

## Order Modes

Nodes announce `order_mode` in public node metadata.

Allowed values:

| Mode | Client behavior | Node behavior |
|---|---|---|
| `disabled` | Do not show an active order action. | Reject order requests. |
| `menu_only` | Show menu/status only. | Reject order requests. |
| `test` | Show test-order flow only. | Accept test orders. |
| `live` | Show live-order flow. | Accept live orders. |

If `order_mode` is missing, clients and registries must treat it as `disabled`.

This keeps old or incomplete node payloads from being interpreted as consent to receive orders.

## Who Decides

The node operator decides order mode.

The registry lists what the node announces.

The registry must not decide whether a restaurant is allowed to receive orders.

For real restaurant use, `live` should only be enabled after the restaurant/node operator has explicitly activated it.

## What This Proves Now

In the reference demo, nodes use:

```json
{
  "order_mode": "test"
}
```

That means the public proof may submit test orders.

It does not mean a real restaurant has approved production orders.

## Later Trust Layer

Future versions should add claims such as:

- this node is controlled by this restaurant
- this restaurant has approved live order intake
- this CVR number matches the restaurant
- this trust provider reviewed the claim
- this node signed its current manifest

Those claims should be signed and client-verifiable.

They should not make the registry a certification authority.
