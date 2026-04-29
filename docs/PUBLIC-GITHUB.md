# Public GitHub Plan

This document defines how P4P should be published without exposing the private development branch.

## Visibility Reality

GitHub repository visibility is repository-level.

It is not safe to rely on:

- `main` being public
- `dev` being private
- both living in the same GitHub repository

If a repository is public, its branches and reachable history are public.

Therefore the correct model is two repositories.

## Target Model

### Public repository

`github.com/DennisHedegreen/p4p`

Purpose:

- public protocol surface
- public `main`
- public docs
- public reference implementation
- public issues or discussions only when ready

Should contain:

- `README.md`
- `SPEC.md`
- `ARCHITECTURE.md`
- `ROADMAP.md`
- `PROOF.md`
- `registry/`
- `demo-node/`
- `pilot-node/`
- `client/`
- `docs/`
- `modules/`
- `deploy/`
- `tests/`

Should not contain:

- private strategy
- outreach lists
- journalist drafts
- real restaurant credentials
- real private keys
- real `.env` files
- real SQLite production data
- private LifeOS state

### Private development repository

`github.com/DennisHedegreen/p4p-dev`

Purpose:

- moving development branch
- rough work
- private release prep
- coordination before public pushes

This repository may keep `dev`.

It should still avoid real secrets.

## Clean Publication Sequence

Use this when the public repo should be `github.com/DennisHedegreen/p4p`.

1. Finish and commit the current private `dev` state.
2. Rename the current private GitHub repository from `p4p` to `p4p-dev`.
3. Update the local private remote to `git@github.com:DennisHedegreen/p4p-dev.git` or `https://github.com/DennisHedegreen/p4p-dev.git`.
4. Create a fresh public GitHub repository named `p4p`.
5. Push only the audited public `main` branch to the new public repository.
6. Add branch protection for public `main`.
7. Confirm the public site links to `https://github.com/DennisHedegreen/p4p`.

Do not make the current private repository public while `dev` exists on GitHub.

## Local Pre-Publication Audit

Run this from the repository root before pushing a public branch:

```sh
bash scripts/public-audit.sh
```

The script hard-fails on tracked sensitive-looking filenames and common secret literal patterns.

It also prints a review-only keyword scan for terms such as `secret`, `token`, `private`, `strategy`, and `outreach`.

Those keyword matches are not automatically wrong. They must be read before publication.

## Suggested Remote Command Shape

Do not run these commands blindly. Confirm the current GitHub state first.

```sh
gh repo rename p4p-dev --repo DennisHedegreen/p4p
git remote set-url origin https://github.com/DennisHedegreen/p4p-dev.git
gh repo create DennisHedegreen/p4p --public --description "Open protocol for direct restaurant-customer discovery and ordering without a platform middleman."
git remote add public https://github.com/DennisHedegreen/p4p.git
git push public public-main:main
```

The final branch name may differ. The rule is what matters: push only the audited public branch to the public repository.

## Public-Ready Checklist

Before making the public repo visible:

- `git status` is clean for the public export.
- `git diff --check` passes.
- full test suite passes.
- no real `.env` files are tracked.
- no real private keys are tracked.
- no real SQLite data is tracked.
- no private strategy or outreach material is tracked.
- public README explains that this is a protocol proof and controlled pilot path, not a delivery marketplace.
- public site does not overclaim production readiness.
- GitHub link on `pizza4people.com` works for anonymous visitors.

## Current Audit Notes

Initial local scan found:

- no tracked `.env`, key JSON, SQLite, PEM, token, or secret files
- no obvious real key/token literals in the current working tree
- placeholder examples such as `ed25519:example-*`
- test-only generated key strings created at runtime by unit tests

That is not a substitute for a final pre-public scan.

Run the audit again immediately before publishing.
