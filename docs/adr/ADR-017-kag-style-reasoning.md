# ADR-017: KAG-style reasoning over the rulebook in PostgreSQL

- **Status:** Proposed
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
the question's date are visible to the solver.

Knowledge alignment. A `canonical_entity` table holds one row per (type, canonical name) with an
alias array. The kernel owns the normalisation rule per type, so the pipeline and the qa service
derive the same canonical name from the same mention. The extraction stage resolves mentions
against the table; a mention that does not resolve goes to the review queue rather than creating
a new entity on its own.

Rollout. The planner and solver sit behind the `qa.kag_enabled` flag, default off, with
per-tenant targeting. The tables and the extraction stage ship first and are additive. The
kernel vocabulary (`domain_kernel.knowledge`) and the knowledge tables exist (rulebook migrations
0001 to 0004; documents, clauses and citations since 0004), and parsed documents reach the
rulebook through its API (ADR-018). The extraction stage, the planner and the solver follow.

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
similar to the question. It does not follow supersedes chains, does not compare a turnover to a
threshold, and does not know that two mentions are the same notification, so multi-hop and
date or threshold questions either go to the agentic fallback or get refused.

## Consequences

- Multi-hop and date or threshold questions get a deterministic path: the plan is inspectable,
  each step is a repository call that can be replayed, and the citations are the clauses the
  solver touched rather than whatever ranked highest.
- Three tables in the rulebook schema, one of which (`clause_entity`) the architecture already
  planned, and one more extraction stage per document. Extraction cost grows by one model call
  per document for relations; entity mentions are found by a grammar first and the model is
  asked only for what the grammar cannot see.
- The planner adds one model call, for multi-hop questions only. Single-hop questions still stop
  at the structured layer or hybrid RAG with no extra tokens.
- Alignment shifts work to analysts: unresolved mentions land in the review queue. The queue must
  be watched, and the alias table needs an owner.
- The kernel and the database both enforce the vocabulary, so adding an entity type or a relation
  kind is a kernel change plus a migration, not a config edit. That is intended.
- Revisit if the relation graph needs traversals deeper than three hops at interactive latency,
  if alias resolution needs fuzzy matching that SQL cannot do well, or if the eval phase shows no
  gain in grounded-answer rate over hybrid RAG. This ADR moves to Accepted only with the eval
  numbers: plan validity, solver success, citation correctness, grounded-answer rate and refusal
  accuracy against the golden set, and no drop in grounded-answer rate against the hybrid RAG
  baseline.
