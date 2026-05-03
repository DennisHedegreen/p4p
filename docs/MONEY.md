# Money And Currency

Status: active protocol rule for menu prices, order totals, and payment
adapter inputs.

P4P does not do currency conversion, hold funds, settle money, or act as
merchant of record. Money fields exist so nodes, customer surfaces, and payment
adapters agree on the same order amount.

## Rule

- A menu has one `currency`.
- `currency` is a three-letter uppercase currency code, such as `DKK`, `EUR`,
  `USD`, `JPY`, or `BRL`.
- Item `price` values are integer minor units in that menu currency.
- Order totals are calculated as integer minor units from the active catalog.
- P4P core does not convert between currencies.
- Payment adapters must not guess, rewrite, or silently convert currency.

Examples:

| Amount | Currency | Meaning |
| --- | --- | --- |
| `6500` | `DKK` | `65.00 DKK` |
| `1299` | `USD` | `12.99 USD` |
| `1200` | `JPY` | `1200 JPY` |
| `4590` | `BRL` | `45.90 BRL` |

## Mock And Sandbox Boundary

Internal mock modules may use explicit test currencies or labels in module
metadata, such as `TEST` or `PIZZACOIN`.

Those are not production currency codes for real menus. They must remain
labelled as internal mock, sandbox, or local-only behavior.

## Operator Rule

The restaurant/operator owns the menu currency. In the reference runtime this
can be set with:

```text
P4P_MENU_CURRENCY=DKK
```

Changing currency is a catalog/operator decision. It is not a customer-side
presentation setting.
