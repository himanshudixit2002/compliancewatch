# Event contracts changelog

Versions follow semver per topic. Adding an optional field is a minor bump, changing or removing
a field or making one required is a major bump and a new `v<major>` schema file, wording is a
patch. Every line names the topic and its version.

## 2026-10-06

- document.classified 1.0.0: first version; the pipeline's classify step and a triage's
  resolution produce it
- rule.candidate.created 1.1.0: optional source_id, source_key, doc_type, outcome, the candidate
  in the extraction schema's shape, issues, suggested_rule_key, clause_ids and ontology_version;
  the pipeline's rule extraction produces it
- document.parsed 1.1.0: doc_type admits statute; the pipeline's parse produces it, and the
  descriptions say clause text is read from the rulebook

## 2026-10-04

- applicability.decided 1.1.0: trigger review, a person's resolution of a review item

## 2026-10-01

- eval.run.completed 1.0.0: first version

## 2026-09-29

- notification.sent 1.0.1: the dedupe_key description names the key of each occasion
- notification.failed 1.0.1: the dedupe_key description names the key of each occasion
- rule.withdrawn 1.0.0: first version
- rule.deadline_changed 1.0.0: first version
- tenant.created 1.0.0: first version
- user.role.changed 1.0.0: first version

## 2026-09-28

- envelope 1.0.0: first version
- document.discovered 1.0.0: first version
- document.parsed 1.0.0: first version
- rule.candidate.created 1.0.0: first version
- rule.published 1.0.0: first version
- rule.superseded 1.0.0: first version
- profile.updated 1.0.0: first version
- applicability.decided 1.0.0: first version
- obligation.created 1.0.0: first version
- obligation.due_soon 1.0.0: first version
- obligation.closed 1.0.0: first version
- obligation.rescheduled 1.0.0: first version
- notification.sent 1.0.0: first version
- notification.failed 1.0.0: first version
- tenant.deletion.requested 1.0.0: first version
