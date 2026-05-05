# Synthetic Food Image Fixtures

Status: synthetic image fixtures for P4P menu, catalog, ingredient, and
AI-ordering tests.

This directory is the safe place for generated food and ingredient fixtures.
The prompt pack is kept beside the generated outputs so the fixture set can be
recreated or extended later. These outputs must stay test-only unless an
operator later replaces them with their own real catalog images.

These fixtures are not restaurant data. They are not partner material. They are
not production catalog truth. They must not be used to claim what a real
restaurant serves.

## Directory Layout

Images are stored here:

```text
docs/examples/food-image-fixtures/
  dishes/*.png
  ingredients/*.png
  menu-cards/*.png
  README.md
  PROMPTS.md
  manifest.json
```

The generated set currently contains 22 unique PNG fixtures, scaled to a
maximum dimension of 900 px so they stay practical for GitHub and local tests.

## Use

Use these prompts and generated images to test:

- catalog item image fields
- customer menu list image rendering
- photo-map item previews
- ingredient selection UI
- allergen/ingredient explanation surfaces
- AI menu conversation grounding
- public demo screenshots without copying real restaurant assets

## Rules

- Do not include real restaurant names, real logos, phone numbers, QR codes, or
  third-party brand packaging.
- Do not present generated food images as real food from a restaurant.
- Do not use these images as production advertising claims.
- Catalog truth remains structured data: item ids, names, prices, currency,
  ingredients, allergens, availability, and operator approval.
- Images are visual fixtures only.

See [`manifest.json`](./manifest.json) for machine-readable metadata and
[`PROMPTS.md`](./PROMPTS.md) for the prompt pack.
