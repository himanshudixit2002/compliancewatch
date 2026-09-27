# ADR-012: Layered retrieval: structured, hybrid RAG, SQL entity joins, agentic fallback

- **Status:** Proposed (Accepted when the qa service ships layers 1 and 2 with the evaluation gate)
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
