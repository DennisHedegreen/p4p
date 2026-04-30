# P4P Proof Status

Current checkpoint: 30 April 2026

This file is the dated proof checkpoint for the public P4P surface.

Use it to log what is actually true on the hosted internet surface, not only what the local repo intends.

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
- `demo-node/.venv/bin/python -m compileall demo_node pilot_node registry p4p_core scripts` passed

This means the current repo state is internally coherent enough to keep the public claim narrow and honest.

It does not by itself mean the hosted surface is fully green.

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

Local repo truth remains:

- `public/www/pizza4people/index.html`
- `public/www/pizza4people/press-kit/index.html`
- `public/www/pizza4people/press-kit/en.html`
- `public/www/protocols4people/index.html`

If hosted copy drifts again, the next upload must bring the hosted surface back to that source of truth before broader outreach.

## Current honest public line

Use this line consistently:

Pizza4People is a public protocol proof.

The next step is a controlled live pilot.

It is not a finished restaurant platform, not a production security claim, and not a broad rollout.

## Remaining public gate

Before calling the public proof surface fully green:

- keep `docs/PROOF-STATUS.md` updated if the edge-layer behavior changes again
- record the narrower failover proof video or another equivalent direct-order/failover artifact
- keep `editorial/work/p4p-is-live/` in work-state until distribution follow-up is logged cleanly
