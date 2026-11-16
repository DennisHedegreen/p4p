# Pizza4People / P4P

*Brussels 2026 hackathon one-pager - non-technical version*

Use this when the group needs the shortest, clearest version first.

## One-sentence pitch

A lightweight direct-ordering system that lets a local takeaway shop be found,
show its menu, and receive pickup orders without a marketplace owning the first
customer contact.

## The problem

Food platforms look convenient, but they become permanent middlemen.

- the platform owns first contact
- the shop pays fees and loses visibility
- the customer remembers the app, not the shop
- even simple pickup orders are routed through someone else's market

## Who it is for

- small pizza, kebab, grill, burger, and takeaway shops
- owner-run places that need a simple direct channel
- customers who already live nearby and just need menu, order, and pickup

## What the group can show in the hackathon

- one shop page with menu and opening state
- QR code or direct link to that page
- simple pickup-order flow
- small operator view for incoming orders
- order status: `received` and `ready`
- payment at pickup first

## Demo flow

`QR/link -> menu -> order -> shop screen -> received -> ready -> pickup`

## Why this is a strong hackathon project

- concrete user and visible pain
- easy to explain in one minute
- visual live demo instead of abstract slides
- can be scoped small without killing the idea
- still has deeper protocol ambition behind it if the group wants more

## How a 5-person team can split it

1. customer flow and menu page
2. operator screen and order-state UI
3. backend and order transport
4. design, pitch, and demo narrative
5. integration, deployment, and live demo setup

## Hard scope boundary

In the hackathon we do **not** build:

- delivery logistics
- online payment processing
- customer account platform
- loyalty system
- full federation story
- production security story
- "Uber Eats but open source"

## Honest claim

This is a direct pickup-ordering proof for local shops.

The real point is simple:

**The customer should be able to reach the shop directly.**

## What the team already has to work with

- owner-facing concept surface: `pizza4people.com`
- repo and protocol layer: `github.com/DennisHedegreen/p4p`
- enough existing material to build a smaller honest demo without pretending the whole repo is finished

## Why it matters beyond the hackathon

If the demo works, it is not just another food app mockup.

It becomes a proof that a small shop can have a direct digital route back to
the customer without handing the relationship to a marketplace.
