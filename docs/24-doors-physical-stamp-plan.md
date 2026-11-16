# 24 Doors Physical Stamp Plan

*Brussels 2026 working note*

This is the physical-extension plan for `24 Doors`.

The digital tool already treats each EU language as a stamped door.

The physical version should make that idea touchable.

Not as merch.

As civic interface.

## 1. The Point

The physical stamps should help people understand three things fast:

- there are `24` official EU language doors
- language access is not cosmetic
- each door changes who can read, respond, and enter the institution

The physical object should feel:

- archival
- official-adjacent
- portable
- demo-friendly
- understandable in under 20 seconds

## 2. The Clean Build Ladder

There are really three versions.

### Version A: print-only stamp set

The simplest honest version.

- Print the 24 stamp artworks as real small cards, labels, or perforated sheets
- Let people sort them into a letter, board, or target frame
- Use them as physical tokens during explanation

This is enough for:

- table demo
- photos
- tactile explanation
- showing the “door system” without extra electronics

### Version B: scan-enabled stamp set

Each stamp gets:

- a short printed code
- or a QR/NFC destination

The stamp still works as a beautiful object, but now it can also open:

- the language review pack
- a locale-specific page
- the full door profile
- a scenario explainer

This is probably the best near-term public version.

### Version C: interactive chip-enabled stamp set

Each stamp contains a tiny tag so the stamp can be tapped or scanned.

That would let a phone or reader trigger:

- selected language
- selected scenario
- stamp metadata
- review status
- access-letter generation

This is the most interesting demo version, but only if the hardware stays simple.

## 3. Important Technical Rule

If the goal is:

- easy DIY
- phone interaction
- no weird reader setup

Then the right first direction is usually **NFC**, not generic “RFID”.

Why:

- people often say RFID when they mean any wireless tag
- but phones can usually read NFC much more naturally than other RFID formats
- NFC stickers/inlays are small enough to hide behind paper, card, or thin label stock

So the practical language should be:

- public wording: `chip-enabled stamp` or `tap-enabled stamp`
- technical wording: `NFC-backed stamp`

Not:

- “smart postal blockchain stamp”
- “IoT collectible”
- “AI postage layer”

## 4. What A Good Physical Stamp Could Do

One physical stamp should be able to carry:

- language id
- ISO code
- visual identity
- optional chip id
- optional route to a locale page or review candidate

Example:

- front: `EL`, `11/24`, Greek door artwork
- back: short explanation + code
- chip: opens Greek locale review or Greek access-letter route

## 5. What To Build First

### Recommended first prototype

Build:

- one A4 sheet with all 24 stamps
- one cut-out mini set
- one or two enlarged “hero” stamps
- one test stamp with a hidden NFC tag

That gives:

- a no-risk print version
- a tactile demo object
- one proof that the tap interaction works

Do **not** begin by trying to chip all 24 at once.

That is cost and failure before learning.

## 6. Cheap DIY Path

### Physical base

- heavier matte paper or sticker stock
- optional card backing
- optional perforation or hand-cut edges
- optional envelope / archive sleeve

### Interaction layer

- start with one hidden NFC sticker or inlay behind the stamp
- map it to one simple URL
- use the stamp as the launcher into the digital tool

### Best first behavior

Tap one stamp.

Open one URL.

That URL should do one thing clearly:

- open locale review
- or open the 24 Doors runtime with that language preselected

No complicated pairing.

No custom hardware required in v1.

## 7. What Not To Do First

- do not build a custom reader box first
- do not try to make the chip store the whole language object
- do not start with battery-powered stamps
- do not try to make them “track people”
- do not turn the concept into access control theater

The stamp should launch interpretation.

Not surveillance.

## 8. Recommended Architecture

### Layer 1: visual object

The stamp is already meaningful by itself.

### Layer 2: symbolic code

Printed identifiers:

- `EL`
- `11/24`
- `eu27__ell-swe__confident`
- review mark / native-review state

### Layer 3: digital trigger

Optional NFC or QR points to:

- runtime tool
- locale workbench
- review pack
- one special landing page for physical stamp demos

## 9. Good Demo Behaviors

### Demo behavior A

Pick a stamp.

Tap it.

The tool opens in that language.

### Demo behavior B

Tap a stamp and open its review candidate.

This is strong because it shows:

- the tool
- the translation layer
- the human review process

### Demo behavior C

Place two or three stamps together beside a printed letter.

Use them to explain:

- who gets in directly
- who needs mediation
- how multilingual access becomes visible

## 10. Why This Matters

If the physical stamp works, `24 Doors` stops being only a screen demo.

It becomes:

- a desk object
- a workshop object
- a meeting object
- a civic explanation device

That matters in Brussels because many people understand things faster when they can:

- hold it
- sort it
- point to it
- tap it

## 11. Risks

### Risk 1: too gimmicky

If the stamp becomes just “cute design”, the civic claim weakens.

### Risk 2: too technical

If the chip story dominates, the language-access story disappears.

### Risk 3: too expensive too early

If all 24 must be fully chipped before the concept can be shown, the build gets slower than necessary.

## 12. Best Rule

The object should still make sense if the chip fails.

That is the right design test.

If the chip works, good.

If not, the stamp should still explain the system.

## 13. Build Order

### Phase 1

- finalize the 24 stamp artworks as printable assets
- test one clean A4 physical sheet
- cut one hand-held set

### Phase 2

- choose one language stamp for chip test
- map it to a stable local or public URL
- test phone tap behavior

### Phase 3

- test 3 chipped stamps
- one entry-door language
- one bridge language
- one low-access language

### Phase 4

- decide whether all 24 need chips
- or whether the right answer is:
  - all 24 printable
  - only a few interactive hero stamps

## 14. Practical Recommendation

For now, the strongest realistic path is:

- all `24` as beautiful print objects
- `1-3` as NFC-backed prototype stamps
- one tiny explainer card:
  - `Tap the stamp. Open the door.`

That is enough to feel advanced without pretending the hardware is the point.

## 15. Next Repo Items

- one printable `24 Doors` stamp card/sheet spec
- one “physical stamp demo” landing page
- one mapping file from stamp id -> target URL
- one short build checklist for DIY assembly
- optional one-pager for Brussels: `24 Doors as a civic object`

## 16. Final Line

The physical stamp should not prove that Europe has good language access.

It should prove that language access can be made visible, portable, and discussable.

That is already a meaningful step.
