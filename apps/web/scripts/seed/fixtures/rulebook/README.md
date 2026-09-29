# Recorded rulebook fixtures

The three JSON files are the request bodies the pipeline sends to the rulebook for one recorded
CBIC notification, replayed by `make web-seed` (`scripts/seed/steps/rulebook.mts`) so the admin
review queues have real regulator records without running the pipeline. Nothing in them is
written by hand: they were recorded once from the pipeline's own parser and grammar over the
PDF the pipeline's tests already keep.

| File                            | Sent to                                                        | Recorded from                                                                                                                                                 |
| ------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gst-ct-01-2026.document.json`  | `PUT /v1/rulebook/documents/{document_id}`                     | `PdfParser` (`pipeline.infrastructure.parsers`, `pdf@1`) over the recorded PDF; the body `HttpRulebook.register_document` builds                              |
| `gst-ct-01-2026.mentions.json`  | `PUT /v1/rulebook/documents/{document_id}/mentions`            | the mention grammar (`pipeline.domain.grammar`, `grammar@1`) through `MentionStage`, the body `HttpRulebook.submit_mentions` builds                           |
| `gst-ct-01-2026.relations.json` | `PUT /v1/rulebook/documents/{document_id}/relation-candidates` | `RelationStage` (`extraction.rule_relations@1`) over the scripted answer the demo's knowledge-flow test uses, the body `HttpRulebook.submit_relations` builds |

## Provenance

- The document is notification `01/2026-Central Tax` (CBIC), the PDF recorded at
  `services/pipeline/tests/fixtures/cbic/gst-ct-01-2026.pdf.json` (base64 in the `data`
  field). Its SHA-256 is `51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed` and
  the document id is the first half of that digest read as a UUID
  (`51f5dbee-1615-f0ec-4725-6abddb11061a`), the kernel's rule
  (`domain_kernel.documents.document_id_for`). The seed hashes the PDF again before every run
  and refuses to continue when the digest and the fixture disagree.
- The title and the publication date (`2026-04-21`) are the source listing's, recorded at
  `services/pipeline/tests/fixtures/cbic/notifications-2026-p0.json`; they are what the
  pipeline's `RegisterDocument` stores over the parser's own values when the CBIC source is
  fetched. The URL is the listing's file path under the CBIC repository host.
- `source_id` (`00000000-0000-4000-8000-00000000000b`) is a fixed id for the seed's source row;
  the pipeline's source registry does not exist yet. `fetched_at` is the fixed
  `2026-09-28T00:00:00+00:00` the demo uses as its as-of date.
- The relation candidate is the scripted model answer staged by
  `tools/demo/tests/unit/test_knowledge_flow.py` (the notification extends the GSTR-3B deadline
  for the period `2026-03` to `2026-04-21`), run through the real relation stage, which verified
  the evidence quote against the clause text (`quote_score` 1.0). No model was called; the
  `model` field says `scripted/golden`. Its `rule_key` (`gstr3b_monthly`) was known to the
  in-process rulebook while recording; the seed blanks it when the target rulebook does not list
  that rule (a memory-store rulebook lists none), as the relation stage would have: its answer
  schema only offers the rule keys the rulebook lists. The rulebook would otherwise stage the
  candidate with a `rule_key_unknown` issue.

## Recording again

From the repository root, after a change to the parser, the grammar, the relation stage or the
recorded PDF:

```bash
uv run --package compliancewatch-demo python apps/web/scripts/seed/fixtures/rulebook/record.py
pnpm exec prettier --write apps/web/scripts/seed/fixtures/rulebook
```

`record.py` runs the stages the way `pipeline.application.knowledge_activities` does and captures
the bodies `HttpRulebook` sends to an in-process rulebook on the memory store, so what is
committed is exactly what a running pipeline would send. `scripts/seed/seed.test.mts` checks
the committed files: they parse, the digest matches the PDF, every mention is the exact slice
of its clause, every candidate's target is one of the recorded mentions (same clause, span, type
and proposed name) and every evidence quote is in its clause. The seed runs the same checks
before it sends anything.
