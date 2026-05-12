# MobilePay Developer Call

Status: protocol-facing invitation for external adapter builders.

This note exists so `p4p.payment.mobilepay` is read correctly.

It is not a promise that P4P core will become a MobilePay integration owner.

## Short Version

P4P should stay the motorway.

If a MobilePay-style adapter exists, it should be an external module provider or operator-side integration, not a P4P-core payment business.

## Why The Boundary Matters

The current P4P design keeps discovery, menu fetch, direct ordering, and module declaration in the core.

Payment stays outside the core.

That is not aesthetic minimalism. It is structural:

- P4P should not hold funds
- P4P should not process payments
- P4P should not store payment credentials
- P4P should not become merchant of record
- P4P should not quietly absorb payment-specific legal or operational burden

## What An External Builder Would Own

If an external developer or integrator wants to build toward MobilePay, the adapter side should own:

- MobilePay/Vipps MobilePay API integration
- merchant setup and merchant-specific credentials
- payment request creation
- capture/cancel/refund behavior
- payment-status error handling
- payment-specific operational and compliance burden

P4P core should only expose the replaceable module slot and keep the payment adapter optional.

## Desired First Shape

If anyone builds this, the desired first shape is still narrow:

- pickup-first
- operator-chosen
- replaceable
- easy to disable
- easy to fall back from to `p4p.payment.cash`
- no expansion of P4P core into a payment product

## Official Context

Vipps MobilePay's developer docs describe payment integrations where the merchant creates payment requests and then manages payment operations such as capture, cancel, and refund.

Official docs:

- <https://developer.vippsmobilepay.com/docs/APIs/payment-integration/>
- <https://developer.vippsmobilepay.com/docs/APIs/epayment-api/api-guide/operations/>
- <https://developer.vippsmobilepay.com/docs/knowledge-base/payments/>

That is exactly why this should sit outside P4P core.

## Current Reading

`p4p.payment.mobilepay` should therefore be read as:

- external-developer invitation
- module contract placeholder
- not reference runtime
- not current public proof claim
- not a P4P-owned payment roadmap promise
