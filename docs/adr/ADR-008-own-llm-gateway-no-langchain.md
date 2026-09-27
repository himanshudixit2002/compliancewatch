# ADR-008: Own LLM gateway; no LangChain or LlamaIndex in production code

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** AI Platform, with Platform and Infrastructure

## Context

Five features call a language model: rule extraction, applicability judgement on free-text
conditions, grounded question answering, document classification, and a smoke check. Every one
of them needs the same things around the call: a versioned prompt so an eval run knows what it
measured, a cost figure in rupees per tenant and per feature with a monthly ceiling, a cache for
identical calls, masking of personal data before text leaves the system, a trace to look at when
an answer is wrong, and a way to swap the model without touching the caller. Two ways to get
these were on the table. LangChain and LlamaIndex bundle prompt templates, retrieval and model
clients behind their own abstractions; they move quickly, hide which calls are made and in what
order, and put the retrieval logic that the evals must judge inside a library. LiteLLM offers a
self-hosted proxy for provider routing, one more process to run, patch and secure. Vercel's AI
Gateway gives an OpenAI-compatible endpoint over many providers with one key, provider ordering
and a zero-data-retention flag, and takes no code of ours to run.

## Decision

One service, `services/llm-gateway`, is the only place that talks to a model provider. It owns
the routing table per feature, the prompt registry that refuses an unregistered prompt, the
in-memory cache, the cost ledger in USD and INR with tenant and feature budgets, PII masking, a
circuit breaker per provider, and tracing to Langfuse. Callers send a feature, a registered
prompt reference and text; they never see a provider SDK. The Vercel AI Gateway is the routing
layer behind the service, reached through the OpenAI client; a deterministic fake provider is
the default everywhere and the only one CI uses. Retrieval stays in the qa service as plain
code over pgvector. LangChain and LlamaIndex may be used in notebooks and experiments; they do
not appear in a service's dependencies.

## Consequences

- Cost, prompt versions, cache hits and masked fields are visible in one ledger and one trace,
  and an eval run can pin exactly which prompt and model produced a result.
- A model change is a routing-table edit or an environment variable, not a code change in the
  calling service.
- The gateway is on the path of every model call: it must stay small, stateless apart from the
  ledger, and its fake provider must keep the rest of the system testable without a key.
- The Vercel dependency is a contract, not code: the OpenAI-compatible surface makes a second
  real provider a new adapter behind the same protocol. Zero data retention needs a paid plan,
  and its flag must be set per environment.
- We write and maintain what a framework would have given for free: prompt loading, retries,
  structured output checks. That code is a few hundred lines and it is ours to read.
- Revisit if a framework offers a stable, inspectable abstraction that the evals can still
  judge, or if the gateway becomes the latency bottleneck for the question-answering path.
