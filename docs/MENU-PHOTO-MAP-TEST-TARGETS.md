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
