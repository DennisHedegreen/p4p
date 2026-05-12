# Synthetic Menu Photo-Map Fixtures

Status: synthetic fixtures for `p4p.menu.photo-map` testing.

These images are fictional, AI-generated paper menu examples supplied by the
project owner on 2026-05-03.

They exist so P4P can test photographed/paper-menu mapping without copying real
restaurant menus, logos, or brand material into the repo.

## Fixture Set

| Fixture | Locale | Language | Currency | Image |
| --- | --- | --- | --- | --- |
| `synthetic-sao-paulo-pizzeria` | Sao Paulo, Brazil | Portuguese | `BRL` | [`sao-paulo-pizzeria-paper-menu.png`](./sao-paulo-pizzeria-paper-menu.png) |
| `synthetic-tokyo-pizzeria` | Tokyo, Japan | Japanese and English | `JPY` | [`tokyo-pizzeria-paper-menu.png`](./tokyo-pizzeria-paper-menu.png) |
| `synthetic-nyc-pizza` | New York, United States | English | `USD` | [`nyc-pizza-paper-menu.png`](./nyc-pizza-paper-menu.png) |
| `synthetic-naples-pizzeria` | Naples, Italy | Italian | `EUR` | [`naples-pizzeria-paper-menu.png`](./naples-pizzeria-paper-menu.png) |
| `synthetic-copenhagen-pizza-grill` | Copenhagen, Denmark | Danish | `DKK` | [`copenhagen-pizza-grill-paper-menu.png`](./copenhagen-pizza-grill-paper-menu.png) |

See [`manifest.json`](./manifest.json) for machine-readable fixture metadata.

## Use

Use these fixtures to test:

- clickable hotspot placement over a real-looking menu image
- OCR and operator-assisted item matching
- category boundaries
- multiple price columns
- multi-language menu text
- currency display across `BRL`, `JPY`, `USD`, `EUR`, and `DKK`

The generated text is test material only. It is not catalog truth and should not
be treated as production restaurant data.

When local OCR is enabled in the pilot node, a fixture can be posted directly to
the operator-only image preview route:

```bash
curl -sS \
  -H "Authorization: Bearer $P4P_OPERATOR_TOKEN" \
  -H "Content-Type: image/png" \
  --data-binary @copenhagen-pizza-grill-paper-menu.png \
  "http://127.0.0.1:8201/operator/menu/import-image-preview?source_name=copenhagen-pizza-grill-paper-menu.png"
```
