# Owner Collateral System

This document defines the canonical owner-facing print system for
`Pizza4People`.

It exists so the repo has one clear print-collateral truth instead of several
parallel draft lanes.

## Official Model

The owner pack is a two-booklet system:

1. `First Contact`
   - 12 A5 pages
   - first handoff
   - stronger tone
   - explains why Pizza4People exists and why the direct route matters
2. `Pilot Guide`
   - 8 A5 pages
   - follow-up practical booklet
   - calmer tone
   - explains what the first pilot actually needs and how it works

This is the canonical model.

Do not treat old flyer, fold, or trifold drafts as equally current.

## Canonical File Locations

Canonical files live under:

- `docs/owner-pack/first-contact/`
- `docs/owner-pack/pilot-guide/`

Each booklet folder must contain:

- one HTML/CSS master
- one exported PDF
- one `OUTLINE.md`

Legacy working material lives under:

- `docs/owner-pack/_legacy/`

## Brand Rules

For owner-facing print collateral:

- use `Pizza4People` as the first visible brand
- use `P4P` only as secondary shorthand where helpful
- avoid leading with protocol language on the cover

For GitHub and technical docs:

- `P4P` and `Pizza4People` may still appear together
- protocol/proof language may remain more visible there

## Page Count Rules

Lock the booklet sizes as:

- `First Contact`: 12 A5 pages / 6 A4 booklet pages
- `Pilot Guide`: 8 A5 pages / 4 A4 booklet pages

Do not silently grow or shrink these counts without updating this doc and the
corresponding `OUTLINE.md`.

## Output Rules

The HTML/CSS file is the master.

The PDF is an export artifact.

Do not treat a standalone PDF from Downloads as the source of truth, even if it
contains better current thinking.

If an external PDF becomes the strongest draft, rebuild it as HTML/CSS inside
the repo and make that rebuilt version canonical.

For the current `First Contact` lane, the Downloads draft
`P4P-first-contact-zine-A4-fold-booklet-da-v3.pdf` is the reference alpha that
informed the rebuild, but it is not the master.

## Language Rules

- Danish is the first canonical print language.
- English is a later derived variant.
- Future translations should follow the same booklet structure, not invent new
  shapes per language.

## Legacy Policy

The following older P4P print-collateral drafts are preserved as legacy:

- `PILOT-A5-FLYER-da.md`
- `PILOT-A5-GUIDE-da.md`
- `PILOT-FOLD-GUIDE-da.html/.pdf`
- `PILOT-TRIFOLD-GUIDE-da.html/.pdf`

They are kept for continuity and reuse, but they are no longer canonical.

Any new work should extend the owner-pack structure instead of reviving those
paths as first-class active files.
