# extraction golden set

One case per document. The pipeline's labelling tool writes the file; an analyst fills in
`expected` and moves `label_status` forward. Nothing in `expected` is a regulatory fact until an
analyst has reviewed it against the clauses in the same file.

## Workflow

1. `make label ARGS="index --source cbic_notifications --since 2024-01-01 --limit 50 --out evals/golden/extraction/cbic_notifications/index.yaml"` lists the documents (every entry `label_status: draft`). The maintainer approves the list before anyone labels.
2. `make label ARGS="prepare --index evals/golden/extraction/cbic_notifications/index.yaml"` fetches and parses each document (one request per second, honouring robots.txt) into `cases/<number>.yaml`: the clauses as `[ref] text`, a `detector` block with what the deterministic detector saw, and `expected: null`.
3. The analyst writes `expected` (the shape below), sets `labelled_by`, and `label_status: reviewed`. A second analyst sets `reviewed_by` and `label_status: approved`.
4. `make label ARGS="check"` confirms every `expected` is a well-formed candidate that cites clauses in its own document and passes the validators (quotes present, numbers and dates written in the cited clauses, predicates over ontology attributes). CI runs the same check.

## `expected`

The same JSON shape the extractor asks the model for (`pipeline.domain.candidate.CANDIDATE_SCHEMA`):

| Field | Meaning |
| --- | --- |
| `title`, `summary` | plain language |
| `doc_kind` | notification, circular, press_release, act_amendment |
| `change_kind` | none, corrigendum, withdrawal, amendment, extension |
| `effective_from`, `effective_to` | ISO dates or null; must be written in a cited clause |
| `references` | earlier notifications and circulars named, as written |
| `applies_to` | predicates over ontology attributes, each with the `clause_ref` it comes from |
| `obligation` | title, steps, evidence_type, due_in_days, clause_ref; or null |
| `recurrence` | frequency, due_day, due_month_offset, clause_ref; or null |
| `amounts` | rupee amounts as whole rupees with the clause they appear in |
| `citations` | clause_ref and a quote copied from that clause; at least one |
| `confidence` | 0 to 1 |

## Status

`cbic_notifications/index.yaml` lists 50 Central Tax notifications (02/2026 back to 04/2024),
all `draft`, awaiting the maintainer's approval of the list. One case is prepared and carries a
draft label written from the document text (`cases/01-2026-central-tax.yaml`); an analyst
reviews it before it counts as reviewed.
