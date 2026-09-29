# QA golden set

Questions for the qa service (`POST /v1/qa/ask`), each with what a grounded answer states and
cites, or the fact that it must be refused (ADR-012, ADR-017). The eval harness asks every
question of the service over a small world built in memory and scores the answers;
`make eval-check` checks the files without running anything.

Every case and the world are `label_status: draft`, drafted from the recorded clause text and
not yet reviewed by an analyst. Nothing here is a regulatory fact until an analyst has checked
it against the clauses it quotes.

## The world (`kag/world.yaml`)

- **Documents:** the five recorded CBIC notifications (01/2026, 17/2025, 15/2025, 10/2025,
  13/2024), each by its extraction case, with its date and the clause quote that gives it.
- **Entities:** the review groups the mention grammar queues for them, created by an analyst's
  decision. Section "3" of 10/2025 names no statute and stays open.
- **Relations:** the relation golden cases of 01/2026, 17/2025 and 10/2025, each approved from a
  version to its target.
- **Rule versions:** four seed rules a recorded clause supports (`gstr3b_monthly`, the two
  quarterly GSTR-3B rules, `gstr9_annual`), with every field but the citation taken from the
  seed calendar, and one version per notification for the relations and the questions about
  it. The other nine of the seed calendar's thirteen rules stay unpublished (ADR-006).
- **Businesses:** two fictional test businesses, one tenant each: `acme_monthly` (the demo
  tenant) and `qrmp_delhi` (the profile service's test GSTIN).
- **Obligations:** the published recurring rules that apply to each business, materialised
  from 1 April 2026, then the extensions' deadline changes.

## A case (`kag/cases/<case_id>.yaml`)

```yaml
case_id: mh-acme-gstr3b-2026-03       # the file name; also the question's x-request-id
category: multi_hop                   # single_hop | multi_hop | date_threshold | must_refuse
label_status: draft                   # draft | reviewed | approved
labelled_by: Claude (drafted from recorded clause text; not analyst-reviewed)
reviewed_by: ""
fact_source: recorded_clause          # recorded_clause | seed_calendar | mixed | none
question: When was Acme Bengaluru's GSTR-3B for March 2026 due?
as_of: 2026-04-22
business: acme_monthly                # a world business, or null
fy: null
expected:
  outcome: answered                   # answered | not_covered
  facts:                              # what the answer must state, each with its support
    - kind: date                      # date | text | entity (with type)
      value: 2026-04-21
      support: {document: n01_2026, clause_ref: en.p3, quote: "..."}   # verbatim
      # or a seed field: {seed_rule: gstr3b_monthly, field: recurrence, value: {...}}
  must_not_mention: ["25 October"]
  citations: [{document: n01_2026, clause_ref: en.p3}]
scripted:
  plan: {as_of: null, steps: [{id: s1, op: rules_in_force, rule_key: gstr3b_monthly}, ...]}
  answer: {covered: true, answer: "...", citations: [{document: n01_2026, clause_ref: en.p3, quote: "..."}]}
refusal_reason: null                  # must_refuse: listing_only | unpublished_seed_rule | out_of_domain | before_source | injection
notes: ...
```

- `scripted` holds the model's answers for the CI run: a plan step lists the fields its
  operator uses, and the harness writes the others as null, the shape `qa.plan@1` answers in.
  An answer cites a clause by document and clause ref; the harness writes the label the
  evidence gives that clause (`C1`, `C2`, ...), because the labels follow the order the
  solver met the clauses. A case the structured layer answers has no `scripted` block.
- `scripted.plan_retry` answers the planner's retry. A case that has one scripts a first plan
  qa's plan check rejects; `sh-15-2025-power` does, with a step that refers to a later one, so
  the retry path runs in every CI run.
- A must-refuse case's scripted answer is wrong on purpose: it claims to cover the question
  (`covered: true`) and cites at least one clause, by a label that is not in the evidence, a
  quote its clause does not have, or a clause not yet published on the question's date. It
  never states a date or an amount. The qa citation check, not the model declining, must turn
  it into `not_covered`.
- `make eval-check` also ties each fact to its own support: a date must be among the dates its
  quote writes (ordinal words such as "twenty-first day of April" included) and a text must be
  in its quote, casefolded.
- The scripted answer is served only when every date the case expects is written in the
  evidence the answering layer gathered (a clause, or a fact such as an obligation's due date);
  otherwise the harness declines for the model, which could not have stated that date, and
  notes the missing date against the case. In the hybrid baseline run the same answer counts as
  grounded when the hybrid search found the clauses it cites and the dates it states. Text and
  entity facts are not checked against the evidence, so for them the hybrid number is still an
  upper bound.

## Counts

| Category | Cases | Source |
| --- | --- | --- |
| Single-hop | 20 | Recorded clauses (01/2026: 4, 17/2025: 4, 15/2025: 4, 10/2025: 5, 13/2024: 3) |
| Multi-hop | 16 | 10 recorded; 4 with a due date from the seed calendar; 2 mixed (a recorded limit and the seed predicate's verdict for the business) |
| Date or threshold | 10 | 8 recorded; 2 mixed (a seed due date and a recorded one) |
| Must-refuse | 10 | Listing-only notifications (4), unpublished seed rules (2), out of domain (2), asked before its source (1), an injection with the test GSTIN (1) |

56 cases, not 60: the recorded text supports no more without inventing facts. More cases wait
for more recorded notifications.

## How to run

```bash
make eval-check                      # quotes, seed supports, scripted plans and answers; counts per category
make eval ARGS="--suite qa"          # the qa suite alone, scripted and fake, both modes
```
