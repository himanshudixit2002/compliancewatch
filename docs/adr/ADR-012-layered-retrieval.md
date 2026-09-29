# ADR-012: Layered retrieval: structured, hybrid RAG, SQL entity joins, agentic fallback

- **Status:** Proposed (Accepted when layers 1 and 2 meet the gate on reviewed cases with a real
  model; the scripted CI gate exists since 2026-09-29)
- **Date:** 2026-09-28 (full text; recorded in the Architecture Reference v1.0, section 9.2)
- **Deciders:** AI Platform, Regulatory Intelligence

## Context

Question answering must be grounded: an answer cites published clauses in force on the
question's date or says "not covered" (guide section 3, F10; grounded-answer rate at least
97%). It must also be cheap and fast enough for a WhatsApp conversation, and most questions
are simple: "does e-invoicing apply to me", "when is my return due". Sending every question
through retrieval and a model call is the expensive way to answer questions the system already
knows the answer to.

Two harder classes remain. Multi-hop questions ("what changed for GSTR-1 since April")
need facts that live in several documents connected by a shared entity, which a similarity
search does not follow. Low-confidence questions need more searching before the system can
either answer or refuse honestly.

Alternatives: a single RAG pipeline for everything (simple, but pays a model call for every
question and misses multi-hop); a knowledge graph engine (answers multi-hop, but a second
store to build, keep in sync and operate); an agent that searches freely (flexible, but
unbounded cost and latency, and hard to evaluate).

## Decision

Questions pass through four layers, each more expensive than the last, and stop at the first
that answers with confidence.

1. **Structured.** The question is matched to the business's stored decisions and obligations
   and to rule predicates in PostgreSQL. No model call. A question that is answered here is
   answered in milliseconds with the obligation's own citation.
2. **Hybrid RAG.** Chunks are clauses, not token windows; each is embedded with a contextual
   header (document, topic, effective date). Metadata filters run first: regulator, status
   published, and effective period containing the question's date. BM25 and vector results are
   fused by reciprocal rank and reranked by a cross-encoder, top 40 to 8.
3. **Entity joins.** Every clause's entities (notification numbers, sections, forms, HSN and
   SAC codes, rates, thresholds) sit in the rulebook's `clause_entity` table against canonical
   entities (ADR-017). A multi-hop question becomes SQL joins over clauses that share an
   entity, followed through `rule_relation` for supersession and amendment, and the result is
   reranked like layer 2. Graph-style answers without a graph store.
4. **Agentic fallback.** Only when the top rerank score is low may the model issue two or three
   further searches before answering or refusing.

After retrieval every hit is followed through the supersedes links to the version in force on
the question's date, so an answer never quotes a replaced rule. The prompt receives the selected
clauses with their `clause_ref`s and must cite by ref; the response is post-checked (every
cited ref in the retrieved set, every quoted span in its clause with a fuzzy match of at least
0.85), and two failed checks produce "not covered". Every answer records which layer answered,
so the evaluation suite reports the share stopping at each layer.

## Consequences

- Most questions cost nothing beyond a database read; the model budget goes to the questions
  that need it.
- Layers are testable on their own: the structured layer against the labelled applicability
  set, retrieval against context recall and precision gates, entity joins against the KAG
  golden set (ADR-017), the whole against the grounded-answer rate.
- The rulebook must maintain embeddings, a full-text index and the entity tables; that is
  pipeline work at extraction time, not query time.
- An honest "not covered" is a product feature and is logged for the evaluation suite; the
  refusal rate is watched as closely as the answer rate.
- OpenSearch (ADR-010) replaces the in-database BM25 when the corpus outgrows it; the layer
  boundary does not move.

## Evaluation (2026-09-29)

The qa service (`POST /v1/qa/ask`) runs the layers in this order: structured, then the KAG layer
when the flag targets the tenant, then hybrid search. Against the four layers of the Decision:

1. **Structured: shipped.** Two phrasings only, "when is my `<form>` due" and "what is due this
   (or next) month", answered from the business's obligations with the rule version's verified
   citations, each checked again against its clause. No model call. Any other question passes
   on; this layer never refuses.
2. **Hybrid RAG: shipped.** The rulebook's `POST /search`: an English `tsvector` leg (the terms
   of `plainto_tsquery` joined by OR, ranked by `ts_rank_cd`, so not BM25) and a pgvector HNSW
   cosine leg over `clause_embedding`, each drawing a pool of 40 for `k=8`, fused by reciprocal
   rank with k=60, ties by clause id. There is no cross-encoder rerank: the fused order is what
   the answerer reads.
3. **Entity joins: shipped as the KAG layer, behind a flag.** Built as the planner and solver of
   ADR-017, it runs between layers 1 and 2 rather than after layer 2, and only for the tenants
   `CW_QA_KAG_ENABLED` and `CW_QA_KAG_TENANTS` target. A plan that does not validate, a failed
   or over-budget step, or no clause to cite falls back to layer 2 with the reason.
4. **Agentic fallback: not built.** Reciprocal rank fusion gives no score that means "low
   confidence", so nothing could trigger it yet.

The date filter is on documents first: with `as_of`, the search keeps documents published on or
before it and leaves undated documents out. Each hit also names the published or superseded
versions citing its clause and in force on that date (`cited_by`), and says whether the clause
is out of force (`out_of_force`: published, superseded or withdrawn versions cite it and none of
them is in force on that date). The hybrid layer drops a clause cited only by versions not in
force on the question's date and counts the drop on its span; a clause no version cites stays,
filtered by its document's date alone. It does not follow a dropped hit to the version that
replaced it, as the Decision describes. In the KAG layer a plan reaches rule versions only
through the set in force on the date, `retrieve_clauses` drops out-of-force clauses the same
way, and a `follow` step walks the supersedes links when the plan asks for it.

The query and the clauses are embedded through the llm-gateway (ADR-008). The default model is
`voyage/voyage-3.5-lite` (ADR-013), asked for 512 dimensions (the kernel's `EMBEDDING_DIMS`) and
checked against that length on every answer. Whether the Vercel AI Gateway passes the
`dimensions` parameter through to Voyage is not verified; the first nightly run with a real key
is the proof, and `CW_LLM_EMBEDDING_DIMENSIONS_PARAM` exists for a model without the parameter.
CI embeds with the gateway's fake `fake/hash-ngram-512`, which is lexical, not semantic, so CI
numbers say nothing about vector quality.

The scripted CI run of the KAG golden set (ADR-017, Evaluation; commit `614df20`) gives these
layer shares: with the KAG layer on, structured 0.05, KAG 0.77, hybrid 0.18; with it off,
structured 0.05 and hybrid 0.95. The hybrid baseline scores grounded-answer rate 0.870,
citation correctness 1.000 and refusal accuracy 1.000 on the 56 draft cases. The gate for that
run is refusal accuracy and answer safety at 1.0 for hybrid, which it meets. Context recall and
precision are not measured yet (the harness does not compute them), and no real model has
answered these cases.
