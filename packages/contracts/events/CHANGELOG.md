# Event contracts changelog

Versions follow semver per topic. Adding an optional field is a minor bump, changing or removing
a field or making one required is a major bump and a new `v<major>` schema file, wording is a
patch. Every line names the topic and its version.

## 2026-09-29

- notification.sent 1.0.1: the dedupe_key description names the key of each occasion
- notification.failed 1.0.1: the dedupe_key description names the key of each occasion
- rule.withdrawn 1.0.0: first version
- rule.deadline_changed 1.0.0: first version

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
