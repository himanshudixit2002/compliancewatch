# ADR-017: KAG-style reasoning over the rulebook in PostgreSQL

- **Status:** Proposed (Accepted when an analyst has reviewed the KAG golden set and a nightly
  real-model run meets the thresholds under Evaluation)
- **Date:** 2026-09-28
- **Deciders:** AI Platform, Regulatory Intelligence, Core Product

## Context

Knowledge Augmented Generation (Ant Group, 2024, arXiv:2409.13731) describes four ideas for
question answering in professional domains where a wrong answer has a cost. First,
schema-constrained knowledge: facts are extracted into a fixed vocabulary of types and
relations rather than free text. Second, mutual indexing: every fact points at the source text
it came from, and every piece of source text points at the facts extracted from it. Third,
logical-form-guided reasoning: the model turns a question into a small plan of typed steps, a
deterministic executor runs the plan against the knowledge store, and the model only phrases the
result. Fourth, knowledge alignment: mentions of the same thing in different documents resolve
to one canonical identity, so hops across documents land on the same node.

The architecture already does part of this. The ontology is the schema for business attributes
and rule predicates (ADR-003, ADR-007). Predicates are three-valued and evaluated without a
model call (ADR-007). A rule version cannot be published without verified citations to clauses
(ADR-006), which is the fact-to-text half of the mutual index. The Architecture Reference,
section 5.2 (ADR-012), names a `clause_entity` table so that multi-hop questions such as "what
changed for GSTR-1 since April" become SQL joins over clauses that share an entity. The same
section states the relation to KAG in those terms: the principles without the graph engine.

Two gaps remain. There is no canonical identity for the entities regulator text talks about.
"Notification 17/2026-Central Tax", "Notfn. No. 17/2026-CT" and "17/2026" are the same
notification, and today nothing says so, so joins over mention text miss or double count. There
is also no typed store for the relations between rules and those entities: supersedes, amends,
refers to, exempts, extends a deadline, corrects, withdraws. Supersession exists only as a
rule-version status and as fields of the `rule.published` and `rule.superseded` events, without
an evidence clause and without the other relation kinds. A question that needs two or three hops with a
date or a threshold in the middle has no place to execute deterministically. Hybrid RAG returns
clauses; it does not follow a chain.

## Decision

Adopt the four ideas as data model and code inside the existing services. No graph database and
no agent framework. Everything is rows in PostgreSQL (ADR-003) and code in the rulebook, pipeline
and qa services behind the existing service boundaries.

Schema-constrained facts. The vocabulary is fixed in the domain kernel: the ontology attributes,
the rule model (rule, rule version, predicate, obligation template) and ten entity types:
notification, circular, section, rule, form, hsn_code, sac_code, tax_rate, threshold, state.
Relations between rules and entities use seven kinds: supersedes, amends, refers_to, exempts,
extends_deadline, corrects and withdraws (corrects and withdraws since ADR-015). The kernel checks
the pairing: supersedes, extends_deadline, corrects and withdraws target a rule version; amends,
refers_to and exempts target a rule version or an entity. The database repeats the vocabulary
and the pairing, target-coupling and self-relation rules as check constraints; the kernel
validates the vocabulary, pairing and self-relation rules for every writer, while the entity-id
coupling is a database-only rule until alignment resolves the reference.

Mutual index. Text to fact: the `clause_entity` table records which canonical entity a clause
mentions and where in the clause text (span start and end). Fact to text: every row in
`rule_relation` carries the `clause_id` of the clause that is evidence for the relation, next to
the citations from rule versions to clauses in the `citation` table. Both directions are plain
foreign keys: rulebook migration 0004 created `document`, `clause` and `citation` and gave
`clause_entity` and `rule_relation` their foreign keys to `clause` and `rule_version`. A clause's
id is derived from its document's digest and its ref (`domain_kernel.documents.clause_id_for`), so
the pipeline, the rulebook and the vector index agree on it without asking each other.

Logical-form planner and deterministic solver. In the qa service, after the structured layer and
before hybrid RAG, a planner prompt turns the question into a plan drawn from a closed operator
set (find entity, rules in force on a date, follow a relation to a bounded depth, evaluate
applicability, get obligations, compare or aggregate, retrieve clauses, answer). The plan is
validated against a JSON schema and the operator set; one retry with the validation error, then
fall back to layered retrieval. A solver executes the plan with repository calls and predicate
evaluation only, no model call, one trace span per step. The answerer phrases from the evidence
bundle the solver produced and cites only clause refs from that bundle, with the same post-check
and `not_covered` outcome as the rest of the qa service. Only published rule versions in force on
the question's date are visible to the solver, and a clause the rulebook marks out of force on
that date (versions that were published cite it and none of them is in force then) is dropped
from the search hits and from an entity's clauses before it can become evidence.

Knowledge alignment. A `canonical_entity` table holds one row per (type, canonical name) with an
alias array of names that are already normalised. The kernel owns the normalisation rule per type,
so the pipeline and the qa service derive the same canonical name from the same mention; a
section or rule carries its statute (`39(1)@cgst-act`), because a bare number is ambiguous. The
extraction stage resolves mentions against the table, by canonical name or by the one alias of
exactly one entity; a mention that does not resolve goes to the review queue
(`entity_review`) rather than creating a new entity on its own. There is no fuzzy matching. An
analyst decides a queue group (one entity type and proposed name) by creating the entity, adding
the name to an existing one, or rejecting it; the decision writes the mentions into
`clause_entity` in the same transaction. A name that does not name one entity across documents
(empty, or a section or rule without its statute) is decided mention by mention and never becomes
an alias. Approval records the aligned entity's canonical name, and aligns a candidate whose
target was decided after staging.

Relation staging. Relations are found before any rule version exists for the new document, so the
model's proposals are stored as `relation_candidate` rows at document level: the target as the
grammar named it (type and canonical name, aligned to an entity once review decides the name),
the evidence clause and quote, the confidence after the validators, and for `extends_deadline` the
period and the new due date as the text states them. The prompt (`extraction.rule_relations@1`)
may only choose targets from the grammar's list and clauses from the document, through a JSON
schema built per call; the validators check the quote against the clause (fuzzy match of at
least 0.85 plus the numbers, form codes and month names it carries), the date against the clause,
and agreement with the change detector. Nothing is dropped: a doubtful proposal is a candidate
that needs review, and output that cannot become one is kept in `extraction_run`.

Approval. An analyst approves a candidate by naming the rule version it starts from, which must
not be published yet, and for the relations that target a rule version, the version it targets.
Approval writes one `rule_relation` row pointing back at the candidate; a supersession that would
close a cycle is refused. The direction is always from the new, causing version X to the affected
version Y, which is what the later publish step needs: `rule.published`(X).supersedes lists the
targets of X's supersedes rows, `rule.superseded` is emitted for Y when X takes effect, an
`extends_deadline` row becomes the obligation service's deadline change for Y caused by X with the
candidate's period and due date, `corrects` likewise with reason corrected, and `withdraws`
withdraws Y.

Rollout. The planner and solver sit behind `CW_QA_KAG_ENABLED`, default off, with per-tenant
targeting through `CW_QA_KAG_TENANTS` (a comma list of tenant ids; empty means every tenant). The
flag is owned by AI Platform and is removed when this record is Accepted. The tables and the
extraction stage shipped first and are additive: the kernel vocabulary
(`domain_kernel.knowledge`) and the knowledge tables (rulebook migrations 0001 to 0005), parsed
documents reaching the rulebook through its API (ADR-018), and the extraction stage (mention
grammar, alignment, relation proposals, review and approval) in the pipeline worker behind
`CW_PIPELINE_KNOWLEDGE_ENABLED`, default off. Since 2026-09-29 the qa service has the planner
(`qa.plan@1`), the solver and the answerer (`qa.answer@1`) between the structured layer and
hybrid search (ADR-012). While the flag is on for a tenant, the planner runs for every question
the structured layer does not answer, single-hop or not; a cheap router that sends single-hop
questions straight to hybrid search is a follow-up.

Publication as built (2026-09-29). The rulebook publishes a version behind
`CW_RULEBOOK_PUBLISH_ENABLED` (default off, owned by Regulatory Intelligence) once its citations
are verified and it has one approver, two when it is high impact (ADR-006). The relation effects
follow the direction described above. A `supersedes`, `corrects` or `withdraws` relation cuts
Y's `effective_to` to X's `effective_from` at publication, so a read for a later date sees X at
once; Y's status moves (to superseded, or withdrawn) and `rule.superseded` or `rule.withdrawn`
goes out when X takes effect: at publication when that day has come, otherwise on X's first day
through the daily sweep (`rulebook-transitions`). An `extends_deadline` relation emits
`rule.deadline_changed` (reason `deadline_extended`) at publication, with the candidate's period
and new due date. `corrects` is treated as a replacement until a candidate can carry the
corrected date, so it does not emit a deadline change with reason corrected yet. Every event is
written to the rulebook's outbox in the transaction of the change it records. The obligation
service does not consume them yet: its consumer needs a cross-tenant design under row-level
security.

## Alternatives considered

Full OpenSPG KAG. The reference implementation brings its own graph engine and its own model
orchestration stack. That is a new stateful system to run and back up beside Postgres, against
ADR-003, and a second place where prompts and retrieval live, against ADR-008. The parts of KAG
that matter here are the data model and the plan-then-solve split, and both fit in Postgres.

GraphRAG. Community detection over an entity graph plus model-written community summaries
answers broad "what is this corpus about" questions well. Building and refreshing the summaries
is expensive at the year-three target of 200 sources (Architecture Reference, section 1.5), and
a summary is not a clause: a citation into a summary cannot be post-checked against regulator
text, which the answer policy requires.

Plain hybrid RAG. This is already layer two of ADR-012 and stays. It returns the clauses most
similar to the question. It does not follow supersedes chains (as built, it drops a clause cited
only by versions not in force on the question's date, but it cannot reach the version that
replaced it), does not compare a turnover to a threshold, and does not know that two mentions
are the same notification, so multi-hop and date or threshold questions either go to the
agentic fallback or get refused.

## Consequences

- Multi-hop and date or threshold questions get a deterministic path: the plan is inspectable,
  each step is a repository call that can be replayed, and the citations are the clauses the
  solver touched rather than whatever ranked highest.
- Three tables in the rulebook schema, one of which (`clause_entity`) the architecture already
  planned, and one more extraction stage per document. Extraction cost grows by one model call
  per document for relations; entity mentions are found by a grammar first and the model is
  asked only for what the grammar cannot see.
- The planner adds one model call (two when the first plan fails validation) for every question
  the structured layer does not answer, while the flag is on for the tenant: nothing tells a
  single-hop question from a multi-hop one before the plan exists. Questions the structured
  layer answers, and every question of a tenant the flag does not target, cost no planner call.
  A cheap router in front of the planner is a follow-up.
- Alignment shifts work to analysts: unresolved mentions land in the review queue. The queue is
  watched: the rulebook reports its open items and the age of the oldest, and two ticket alerts
  (`EntityReviewQueueStale` past 48 hours, `EntityReviewQueueBacklog` past 500 open items for 6
  hours) lead to `docs/runbooks/entity-review-queue.md`. The alias table still needs an owner.
- A published deadline extension, withdrawal or supersession reaches the rule events, not yet
  the obligations: until the obligation service consumes `rule.deadline_changed`,
  `rule.withdrawn` and `rule.superseded`, a business's open obligations keep their dates. The
  structured layer does not repeat them blindly: it counts only obligations of versions in force
  on the question's date, and it passes the question on (to the KAG layer or hybrid search) when
  a version in force extends the obligation's deadline, since the obligation's own due date may
  not have moved yet.
- The kernel and the database both enforce the vocabulary, so adding an entity type or a relation
  kind is a kernel change plus a migration, not a config edit. That is intended.
- Revisit if the relation graph needs traversals deeper than three hops at interactive latency,
  if alias resolution needs fuzzy matching that SQL cannot do well, or if the eval phase shows no
  gain in grounded-answer rate over hybrid RAG. This ADR moves to Accepted only with the eval
  numbers: plan validity, solver success, citation correctness, grounded-answer rate and refusal
  accuracy against the golden set, and no drop in grounded-answer rate against the hybrid RAG
  baseline. The Evaluation section below has the first numbers and the proposed thresholds.

## Evaluation (2026-09-29)

The golden set is `evals/golden/qa/kag`: 56 cases, all `label_status: draft`, none reviewed by an
analyst. By category: 20 single-hop, 16 multi-hop, 10 date or threshold, 10 must-refuse. They are
asked against a world built in memory from the five recorded CBIC notifications, the relation
golden cases and the four seed rules a recorded clause supports (`evals/golden/qa/README.md`).
The target was 60; the recorded text supports no more without inventing facts, and the four
missing multi-hop cases wait for more recorded notifications.

The scoring is stricter than in the first run. With the KAG layer on, a case whose scripted
plan has steps counts as grounded only when the KAG layer decided it, so a hybrid answer after
a KAG fallback no longer counts for the KAG run; a valid plan with steps that finds no clause for
an answerable case counts as a solver failure. The scripted answer is withheld (the harness
declines for the model) when a date the case expects is not written in the evidence the
answering layer gathered, which takes three cases away from the hybrid baseline (a due date
only the obligations give). `make eval-check` ties every fact to its own support quote and
holds each must-refuse case to an answer that claims to cover the question with a citation, so
the citation check, not the model declining, refuses it. The two annual-return cases now rest
on the seed predicate as well as the recorded limit (fact source mixed). One case
(`sh-15-2025-power`) scripts a first plan that refers to a later step and a valid retry, so
the planner's retry runs in every CI run.

`make eval EVAL_PROFILE=ci` on commit `9ee75e9`, scripted provider, KAG layer on against the
hybrid baseline (layer off), pasted from the report:

| Metric | KAG | Hybrid | Delta |
| --- | --- | --- | --- |
| plan_validity | 1.000 | n/a | n/a |
| plan_first_try_validity | 0.981 | n/a | n/a |
| solver_success | 1.000 | n/a | n/a |
| citation_correctness | 1.000 | 1.000 | +0.000 |
| grounded_answer_rate | 1.000 | 0.804 | +0.196 |
| refusal_accuracy | 1.000 | 1.000 | +0.000 |
| false_refusal_rate | 0.000 | 0.196 | -0.196 |
| answer_safety | 1.000 | 1.000 | +0.000 |
| response_rate | 1.000 | 1.000 | +0.000 |
| grounded, category date_threshold | 1.000 | 0.600 | |
| grounded, category multi_hop | 1.000 | 0.812 | |
| grounded, category single_hop | 1.000 | 0.900 | |
| grounded, fact source mixed | 1.000 | 0.500 | |
| grounded, fact source recorded_clause | 1.000 | 0.842 | |
| grounded, fact source seed_calendar | 1.000 | 0.750 | |

Layer shares with the KAG layer on: structured 0.05, KAG 0.77, hybrid 0.18; with it off,
structured 0.05 and hybrid 0.95. The first-try share is 52 of 53 planned questions, the retry
case; it is reported, not gated. All 22 CI gates pass, among them those for `qa_kag` (plan
validity, solver success, citation correctness, grounded-answer rate, refusal accuracy and
answer safety at 1.0, and grounded-answer rate at least `qa_hybrid`'s) and for `qa_hybrid`
(refusal accuracy and answer safety at 1.0). The baseline gate cannot fail on its own in CI,
where the KAG minimum is already 1.0; it matters for a gate with a lower minimum, such as the
nightly one proposed below. With the gateway's fake provider, response rate and answer safety
are 1.000 in both modes.

What these numbers do not say:

- The scripted answers are the labels. A score of 1.0 proves that the harness, the qa service
  and the labels agree, not that a model plans or answers well.
- The hybrid number is still generous. The baseline is served the same scripted answer, which
  counts as grounded when the search found the clauses it cites and every date the case expects
  is in the hybrid evidence; text and entity facts are not checked against the evidence, so its
  answer can still state a name or a phrase only the KAG layer's facts gave.
- There are no real-model numbers yet. The nightly run reports the qa suites without gating
  them, and needs the `CW_AI_GATEWAY_API_KEY` secret to run at all.

Proposed to the deciders as the nightly gate that moves this record to Accepted, once an analyst
has reviewed the cases: plan validity at least 0.95, solver success at least 0.98, citation
correctness at least 0.95, grounded-answer rate at least 0.97, refusal accuracy at least 0.95,
and no drop in grounded-answer rate against the hybrid baseline of the same run.
