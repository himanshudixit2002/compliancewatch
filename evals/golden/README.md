# golden sets

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 8, 14 and 19.

- **Owns:** Golden sets as versioned data files, reviewed like code: extraction (starts at 200 documents), qa (starts at 500 questions), applicability (target 2,000 labelled decisions)
- **Owning team:** Regulatory Analysts (an analyst approves every addition); AI Platform owns the tooling (guide section 14)
- **Consumes:** Review edits, "not covered" answers and user thumbs-down after analyst triage
- **Emits / publishes:** Versioned golden data consumed by evals/harness

## Layout

```
extraction/     # document -> expected RuleCandidate; see extraction/README.md for the format
  cbic_notifications/index.yaml   # the 50 Central Tax notifications listed for labelling
  cbic_notifications/cases/*.yaml # one file per document: clauses, detector prefill, expected
qa/             # question -> expected grounded answer and citations (or not_covered); empty
applicability/  # (profile, rule version) -> expected decision; empty
```

## How to run

`make label ARGS="check"` validates every case; `make eval` scores them (see evals/harness).
