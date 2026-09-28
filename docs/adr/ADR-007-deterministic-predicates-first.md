# ADR-007: Deterministic predicates first; LLM judgement only for free-text conditions, with confidence and review routing

- **Status:** Accepted
- **Date:** 2026-09-28 (full text; decision recorded in the Project Foundation guide, section 21)
- **Deciders:** Core Product, AI Platform, Regulatory Analysts

## Context

Applicability is the product: for each published rule version and each business, does the rule
apply, and why. A wrong "applies" sends a business a duty it does not have; a wrong "does not
apply" hides one it has. The decision must be explainable to the business and to an auditor,
cheap enough to run for a hundred thousand businesses when a rule is published, and testable
against a labelled set with precision and recall targets (guide section 3, F7).

Three ways to decide were on the table. A model could read the rule and the profile and
answer; that is expensive at fan-out scale, not reproducible, and its reasoning cannot be
shown as evidence. Engineers could write each rule as code; that is precise but slow, and the
people who understand the rules are analysts, not engineers. Or rules could be written in a
small structured language over a shared vocabulary that both the extractor and the profile
use, so that most decisions are a comparison and only the residue needs judgement.

The domain kernel already holds the third option: `Predicate` over an ontology attribute with
an operator and a value, combined with `AllOf`, `AnyOf` and `Not`, evaluated with Kleene's
three-valued logic (`applies`, `not_applicable`, `unsure`). A predicate with `free_text` and
no operator is always `unsure` until something judges it. `Confidence` carries a review
threshold of 0.8.

## Decision

A rule version's applicability is a specification of structured predicates over ontology
attributes. The engine evaluates them without a model call; a missing attribute or a free-text
predicate makes the result `unsure`, never a guess.

A free-text predicate is allowed only when the extractor and the reviewer agree that the
condition cannot be expressed with the ontology's attributes and operators. For those, and only
those, the engine asks the LLM gateway's judgement feature with a versioned, owned prompt, the
clause text and the relevant profile attributes, and gets back `applies`, `not_applicable` or
`unsure` with a confidence. The judgement never overrides a structured predicate.

Every decision is stored with the evaluated predicates, the profile version and the confidence
(`ApplicabilityDecision`). A decision that is `unsure`, or whose confidence is below the review
threshold, is routed to a reviewer and produces no obligation until a person confirms it. A
structured-only decision has confidence 1.

When a free-text predicate recurs across rules, the ontology gains an attribute for it and the
rules are re-extracted; the free-text path is a pressure valve, not a design.

## Consequences

- Fan-out is cheap: the deterministic path costs no tokens and runs in milliseconds per
  business; only the free-text residue pays for a model call, and that call is cached per
  (clause, profile attributes) through the gateway.
- Decisions are explainable: the stored predicate results are the explanation shown to the
  business and kept for the audit log.
- The labelled applicability set tests the deterministic path exactly and the judgement path
  statistically; precision and recall gates apply to both.
- The ontology is a bottleneck by design: an attribute must exist before a predicate can use
  it. The ontology package is versioned with a changelog and a monthly release train for that
  reason.
- Reviewers see every `unsure` decision. If that volume is too high the fix is a new attribute
  or a better extraction, not a lower threshold.
- Revisit if a regulator's rules turn out to be mostly narrative conditions that resist the
  vocabulary; FSSAI is the first test of that.
