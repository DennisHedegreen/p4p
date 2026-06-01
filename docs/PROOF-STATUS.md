# P4P Proof Status

Current checkpoint: 6 May 2026

This file is the dated proof checkpoint for the public P4P surface.

Use it to log what is actually true on the hosted internet surface, not only what the local repo intends.

This file is not the public proof claim.

If documents overlap:

- `PROOF.md` wins on what is publicly claimed right now
- `docs/PROOF-STATUS.md` wins on dated hosted-proof facts
- `SPEC.md` wins on contract details

## Canonical public source

- `P4P/scripts/build_public_site.py` is the canonical generator for `public/www/pizza4people/`
- `private/data/p4p/site-data.json` is the canonical public copy source for the Pizza4People homepage and press framing
- `P4P/modules/*/module.json` and `provider.json` feed the generated module catalog
- `public/www/pizza4people/press-kit/index.html` and `en.html` are the maintained press-kit source
- HTML kits are the maintained source; PDF kits are export artifacts
- `public/www/pizza4people/press-kit/*.pdf` are artifacts, not the maintained source
- `public/www/protocols4people/` is the separate umbrella surface and must keep the same narrow claim

## Rescue gate

Verified on 30 April 2026:

- `demo-node/.venv/bin/python -m unittest discover -s tests -v` passed with `109/109`
- `bash scripts/public-audit.sh` passed
- `node --check client/app.js` passed
- `demo-node/.venv/bin/python -m compileall demo-node/app/demo_node pilot-node/app/pilot_node registry p4p_core scripts` passed

This means the current repo state is internally coherent enough to keep the public claim narrow and honest.

It does not by itself mean the hosted surface is fully green.

Verified again on 3 May 2026 before the public GitHub/site update:

- `./.venv/bin/python -m unittest tests.test_v0_1_truthfulness` passed with `106/106`
- `./.venv/bin/python -m unittest tests.test_dev_cleanup` passed with `31/31`
- `bash scripts/public-audit.sh` passed with `137/137`
- `node --check client/app.js` passed
- `python3 -m json.tool docs/examples/menu-photo-map-fixtures/manifest.json` passed
- `python3 -m json.tool private/data/p4p/site-data.json` passed from the repository root
- `python3 -m json.tool public/www/pizza4people/modules.json` passed after rebuilding the public site
- `git diff --check` passed
- `./.venv/bin/python scripts/build_public_site.py` regenerated `public/www/pizza4people/`

This 3 May checkpoint adds the money/currency contract, synthetic paper-menu photo-map fixtures, the generated module catalog update, and an explicit public-site payment boundary.

## Public hosting check

Observed on 30 April 2026:

- plain `curl -I -L --max-redirs 2 https://pizza4people.com/` returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://www.pizza4people.com/` returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/press-kit/` returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://protocols4people.com/` returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://github.com/DennisHedegreen/p4p` returned `200`
- public `p4p/main` now points at commit `8682167` (`Public proof update and GitHub reading path`)
- `./_local/publish.sh --upload-special-domain pizza4people --yes` uploaded the current local `public/www/pizza4people/` tree to `/pizza4people.com`
- headless browser verification with `google-chrome --headless=new --dump-dom` loaded `pizza4people.com/`
- headless browser verification with `google-chrome --headless=new --dump-dom` loaded `pizza4people.com/press-kit/`
- headless browser verification confirmed the hosted homepage now shows the `Proof note` button, the `Where to start on GitHub` card, and the `public repo is the conservative story branch` wording

Read this honestly:

- browser reachability exists
- anonymous GitHub reachability exists
- edge behavior is still inconsistent
- the proof surface is therefore browser-verifiable, but not fully clean on plain HTTP tooling yet

This is not a reason to widen the claim.

It is a reason to keep the claim narrow and log the discrepancy.

## Hosted copy status

The hosted browser-visible copy is now back in sync with the current repo source of truth.

Confirmed after the 30 April 2026 upload:

- `pizza4people.com/` now shows the generated `Proof note` hero action
- `pizza4people.com/` now shows the `Where to start on GitHub` card with direct links to README, proof note, spec, and release notes
- `pizza4people.com/` now shows the `public repo is the conservative story branch` wording
- `pizza4people.com/press-kit/` loads the current Danish press-kit HTML

Confirmed after the 3 May 2026 upload:

- `./_local/publish.sh --upload-special-domain pizza4people --yes` uploaded the current local `public/www/pizza4people/` tree to `/pizza4people.com`
- `gh api repos/DennisHedegreen/p4p/commits/main --jq .sha` confirmed the public `main` branch had accepted the 3 May public-surface update before this checkpoint-log edit was committed
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/` still returned Simply `455`
- plain `curl -sS --max-time 15 https://pizza4people.com/modules.json` still returned the Simply `455` error page
- headless browser verification loaded `pizza4people.com/` and found the updated 30 April 2026 date wording, module-layer note, integer minor-unit currency note, and payment-adapter boundary
- headless browser verification loaded `pizza4people.com/modules.json` and found `generated_at: 2026-05-03`, `p4p.menu.photo-map`, and `p4p.payment.godpay-mock`
- the generated homepage now mentions replaceable customer menu modules, internal mock payment modules, operator workflow modules, and integer minor-unit pricing with an explicit node currency
- the generated module section now repeats the payment boundary: payment modules are adapters chosen by the restaurant/operator; P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record
- the generated homepage now treats 30 April 2026 as an announced closure date, not a future event
- `public/www/pizza4people/modules.json` now lists the current module manifests, including `p4p.menu.list`, `p4p.menu.photo-map`, `p4p.customer.status`, `p4p.kitchen.screen`, `p4p.stock.basic`, `p4p.payment.cash`, `p4p.payment.godpay-mock`, and `p4p.payment.chaospay-mock`

Confirmed after the 6 May 2026 upload:

- `./_local/publish.sh --upload-special-domain pizza4people --yes` uploaded the current local `public/www/pizza4people/` tree to `/pizza4people.com`
- `./_local/publish.sh --upload-special-domain protocols4people --yes` uploaded the current local `public/www/protocols4people/` tree to `/protocols4people.com`
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/` still returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/press-kit/` still returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://protocols4people.com/` still returned Simply `455`
- headless browser verification loaded `pizza4people.com/` and found the new shorter hero line `A pizza shop should be able to keep its menu and take orders direct.`
- headless browser verification loaded `pizza4people.com/` and found the new hero state tags `Public proof now`, `Pickup-first pilot next`, and `Not a marketplace app`
- headless browser verification loaded `pizza4people.com/press-kit/` and found the simplified Danish press-kit HTML with the four-card shop-language module section
- headless browser verification loaded `protocols4people.com/` and found the new `Start here` and `Boundary` routing sections plus the line that GitHub keeps the exact protocol language
- browser-visible hosted copy is therefore in sync again with the current local `pizza4people` and `protocols4people` truth surfaces, while plain curl still fails at the edge layer

Confirmed after the late 6 May 2026 Pizza4People module-layer upload:

- `./_local/publish.sh --upload-special-domain pizza4people --yes` uploaded the latest local `public/www/pizza4people/` tree again after the dedicated module-catalog and per-module `read next` pass
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/` still returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/modules/` still returned Simply `455`
- headless browser verification loaded `pizza4people.com/` and found the dedicated `module pages` route in the homepage module section
- headless browser verification loaded `pizza4people.com/modules/` and found the new `Which module matters first?` module catalog plus the `Three practical ways into the module stack` route cards
- headless browser verification loaded `pizza4people.com/modules/p4p.menu.list/` and found the per-module `Read next` section beginning with `See what happens after the order`
- the hosted module layer now reads as a guided path: homepage overview -> module catalog -> module page -> next relevant module/provider/catalog route
- browser-visible hosted copy is therefore back in sync with the current local Pizza4People module-reading layer, while plain curl still fails at the edge layer

Confirmed after the 7 May 2026 beginner-module-entrypoint pass:

- plain `curl -I -L --max-redirs 2 https://pizza4people.com/` still returned Simply `455`
- plain `curl -I -L --max-redirs 2 https://pizza4people.com/modules/` still returned Simply `455`
- headless browser verification loaded `pizza4people.com/` and found the new homepage route `If modules make no sense yet, start with the simple guide inside the module pages`
- headless browser verification loaded `pizza4people.com/modules/` and found the new `New here?` section plus the line `Start with the simple idea, not the raw ids`
- headless browser verification loaded `pizza4people.com/modules/` and found the three beginner routing cards `If you run a shop`, `If you build software`, and `If you are skeptical`
- browser-visible hosted copy is therefore in sync with the current local beginner-friendly module entrypoint, while plain curl still fails at the edge layer

Local repo truth remains:

- `public/www/pizza4people/index.html`
- `public/www/pizza4people/modules/index.html`
- `public/www/pizza4people/modules/p4p.menu.list/index.html`
- `public/www/pizza4people/providers/index.html`
- `public/www/pizza4people/providers/p4p.reference/index.html`
- `public/www/pizza4people/press-kit/index.html`
- `public/www/pizza4people/press-kit/en.html`
- `public/www/protocols4people/index.html`

If hosted copy drifts again, the next upload must bring the hosted surface back to that source of truth before broader outreach.

## Current honest public line

Use this line consistently:

Pizza4People is a public protocol proof.

The next step is a controlled live pilot.

It is not a finished restaurant platform, not a production security claim, and not a broad rollout.

Payment modules are adapters. P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Menu prices use explicit currency codes and integer minor units. P4P does not do currency conversion.

## Remaining public gate

Before calling the public proof surface fully green:

- keep `docs/PROOF-STATUS.md` updated if the edge-layer behavior changes again
- record the narrower failover proof video or another equivalent direct-order/failover artifact
- keep `editorial/work/p4p-is-live/` in work-state until distribution follow-up is logged cleanly
