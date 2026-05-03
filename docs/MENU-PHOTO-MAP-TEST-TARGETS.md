# Menu Photo Map Test Targets

Status: manual test targets, checked 2026-05-03.

These links are for manual testing of `p4p.menu.photo-map` and later OCR or
operator-assisted mapping experiments.

Do not copy third-party menu images, PDFs, or restaurant branding into this
repo unless there is explicit permission or a compatible license. Use these
targets to understand layout problems, then use synthetic fixtures or
restaurant-owned test material in automated tests.

## Why These Targets Exist

`p4p.menu.photo-map` is a customer surface that maps active structured catalog
items to visual regions. It is not the catalog source of truth.

The hard problem to test later is whether a photographed or scanned menu can be
turned into safe clickable regions without losing the operator-owned item ids,
prices, active/inactive status, and ordering boundaries.

## Synthetic Fixtures

The repo now includes synthetic paper-menu images for safe local testing:

```text
docs/examples/menu-photo-map-fixtures/
```

Use those fixtures before using any third-party public menu target. They cover
Portuguese/BRL, Japanese/JPY, English/USD, Italian/EUR, and Danish/DKK layouts
without relying on real restaurant material.

## Local Demo Prospects

These are nearby Brondby/Glostrup-area restaurants that could be useful future
conversation targets if P4P needs a local operator demo.

They are not partners, not approved test users, and not permission sources yet.
Do not copy their menu images, text, logos, or ordering data into the repo
without explicit permission. Use the links only to understand current operator
surfaces and prepare a realistic demo conversation.

| Prospect | Public Surface | Why It Is Useful Later | Demo Angle |
| --- | --- | --- | --- |
| U.P. Pizza, Brondby Strand | `https://uppizza.dk/` | Local pizza/kebab shop with its own ordering surface and a public menu. | Show paper-menu photo-map plus classic structured list menu side by side. |
| Del Rossa Pizza, Brondby | `https://delrossa.dk/` | Local restaurant site with direct branding, contact info, and menu entry point. | Show that P4P can be an operator-owned module layer, not another marketplace. |
| Torvets Cafe & Pizzaria, Brondby | `https://torvets-cafe.dk/takeaway` | Dense numbered menu with pizza, durum, burgers, and popular items. | Good future test for large menu mapping and category boundaries. |
| Vesterleds Pizzahus, Brondby | `https://vesterledspizzahus.dk/` | Local takeaway site with separate public ordering/menu surfaces. | Good operator demo for replacing platform dependency with direct node ownership. |
| Gourmet Pizzeria, Glostrup | `https://gourmetpizzaria.dk/menu/` | Rich public menu with numbered pizzas and mixed categories. | Good manual target for OCR and row-to-catalog mapping tests. |
| Toscana Pizza House, Glostrup | `https://toscanapizzahouse.dk/` | Local Meal4U-style ordering surface with delivery zones and broad menu scope. | Good future test for delivery/pricing boundaries as modules. |
| Big Ben Pizza & Cafe, Glostrup | `https://bigben-pizza.dk/menu/` | Large menu with variants, extras, and item pages. | Good stress target for variants, extras, and item-option modeling. |

## External Manual Targets

| Target | URL | Useful For | Do Not Assume |
| --- | --- | --- | --- |
| Divan Pizzeria menu PDF | `https://usercontent.one/wp/www.divan.dk/wp-content/uploads/2025/06/menukort.pdf` | Dense paper-menu PDF with many pizza rows and category blocks. Good for OCR, row detection, and manual region mapping. | Permission to embed, copy, or redistribute the PDF. |
| Divan menu page | `https://www.divan.dk/menu/` | Real website context around the PDF. Good for checking source attribution and public-page linking. | That the page structure is stable. |
| Leif's Pizzeria menu PDF | `https://www.leifspizzeria.dk/PDF-filer/leifspizzeria-menu.pdf` | Direct PDF menu target. Good for PDF rendering and operator-assisted item matching tests. | That all items should become P4P catalog items automatically. |
| Bellano 64 menu page | `https://bellano64.dk/menu/` | Rich restaurant menu surface. Good for testing mixed visual/embedded menu handling. | That the menu is a simple image or that embedding is allowed. |
| Zorro Pizza menu page | `https://www.zorropizza.dk/menu.html` | Plain HTML menu with many numbered pizzas. Good baseline for structured extraction compared with photo-map output. | That HTML menus need the same mapping path as photographed menus. |
| Pizzeria Ciao Ciao menu page | `https://www.pizzeriaciaociao.dk/` | Public menu page with categories and prices. Good baseline for list/menu parity checks. | That the page can be scraped without permission. |
| Restaurant Sangiovanni menu page | `https://www.sangiovanni.dk/menu` | Broader restaurant menu with sections beyond pizza. Good for testing categories and non-pizza layouts. | That this is a pizza-only test case. |

## Manual Test Questions

- Can an operator identify each menu row as one active catalog item?
- Can the visual label differ from the internal catalog id without breaking the order?
- Does the customer surface hide inactive catalog items even if they exist on the paper source?
- Can ambiguous items be routed to `ORDER_NEEDS_HUMAN` instead of creating a wrong order?
- Can a fallback to `p4p.menu.list` stay available if the photo-map is unclear?

## Automation Rule

Automated tests should use synthetic menu fixtures owned by this repo.

External targets are for human QA, visual comparison, and later permissioned
restaurant onboarding tests.
