# ADR-016: Business hierarchy: legal entity (PAN), registration (GSTIN), location

- **Status:** Proposed
- **Date:** 2026-09-28
- **Deciders:** Core Product, Regulatory Analysts, Identity and Partner

## Context

The domain model has one `BusinessProfile` per business under a tenant, and a CA-firm tenant
manages many businesses (guide section 6). Indian GST is not flat like that. A legal entity is
identified by its PAN; it holds one GST registration (GSTIN) per state it operates in, and the
GSTIN embeds the state code and the PAN; each registration has one or more places of business.
Some duties attach to each registration (returns are filed per GSTIN), some to the entity as a
whole (aggregate turnover is defined across all registrations under one PAN, and it decides
thresholds such as e-invoicing), and some to a place of business (what must be displayed or
kept there). A profile that cannot say which level it describes cannot be evaluated correctly,
and a CA firm that manages a client with registrations in five states needs to see them as one
client.

Alternatives: one profile per GSTIN with the entity-level attributes copied onto each (drift
between copies; aggregate turnover entered five times); one profile per PAN with a state list
(cannot hold per-registration facts such as the filing scheme); a free-form parent link with
no semantics (every consumer reinvents the rules).

## Decision

The profile service models three levels under a tenant: `legal_entity` (keyed by PAN),
`registration` (keyed by GSTIN, belongs to one entity, carries the state), and `location`
(belongs to one registration). Each level is a profile node with its own attributes, version
and history; the ontology declares for every attribute the level it lives at, and an attribute
declared at a higher level is inherited by the nodes below it when a profile snapshot is
assembled for evaluation. Aggregate turnover is entered once at the entity and read by every
registration; the filing scheme is entered per registration; a place-of-business attribute is
entered per location.

A rule version declares the level it applies at (entity, registration or location; the
ontology version 0.2.0 adds the vocabulary). The applicability engine evaluates a rule against
the nodes at that level, each with its inherited snapshot, and obligations attach to the node
evaluated. The kernel's `BusinessId` identifies the node evaluated, whatever its level, so the
engine, the obligation service and the notification service do not change shape; `ProfileSnapshot`
gains the level and the parent chain.

Every node carries `tenant_id` and is covered by row-level security. The GSTIN lookup adapter
pre-fills a registration and, from its PAN, finds or creates the entity; a business that does
not know an answer marks the attribute `unsure` and gets one question at a time, never a
form; an attribute the business says "does not apply" creates a review task rather than a
silent default.

## Consequences

- One truth per fact: entity-level facts are stored once and inherited, so the five-state
  client is one entity with five registrations, which is also what the CA multi-client view
  shows.
- The ontology needs a `level` on every attribute and the seed rules need a `level` on every
  rule version; both are additive to the existing formats and land with the ontology 0.2.0
  release and the seed calendar.
- Migrations are expand-only: the existing single-level profile becomes a `registration`
  under an entity created from its PAN when known, or under a placeholder entity flagged for
  completion.
- Inheritance is resolved at snapshot time, not stored, so a change at the entity is one
  `profile.updated` event that triggers re-evaluation of every registration under it.
- Revisit when a second regulator's hierarchy does not fit three levels (FSSAI licenses are
  per premises and may need a fourth) or when partner integrations need a different key than
  PAN for entities without one.
