# ADR-002: Python and FastAPI for services; Next.js and TypeScript for apps

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Platform and Infrastructure, Core Product, AI Platform

## Context

The backend parses PDFs and scanned notifications, calls model providers, computes embeddings
and runs evals. The libraries for that work (PyMuPDF, pdfplumber, PaddleOCR, LiteLLM, the Text
Embeddings Inference clients, Langfuse) are Python first, and so is the hiring pool for the AI
and data work. The frontend is an owner portal, a CA dashboard, the analyst review workbench and
an admin console, all used by people in a browser. Go was considered for the services: faster
and well typed, but its document and ML libraries are thin and it would split the backend into
two languages. Django was considered and set aside as heavier and sync-first, with an ORM that
pulls persistence into the domain. Remix and Vue were considered for the apps; Retool was
considered for the internal tools and set aside because the side-by-side review workbench is the
analysts' main tool and needs a real UI.

## Decision

Python 3.12 with FastAPI and Pydantic v2 for every service, SQLAlchemy 2 and Alembic for
persistence, and the same four-layer layout (api, application, domain, infrastructure) in each.
Next.js with React, TypeScript, Tailwind and shadcn/ui for the web app, with the internal tools
under `/admin` in the same app behind role gates, and the WhatsApp bot in TypeScript as well.
Typing is strict on both sides from the start: `mypy --strict` and `tsc --strict`.

## Consequences

- One backend language means the shared packages (py-common, the domain kernel, the ontology)
  work everywhere and there is one engineering profile to hire for.
- Python costs more per request than Go. The interactive targets (p95 300 ms profile save, 2 s
  single-business recompute, 4 s Q&A) are met with async I/O and by letting Postgres do the
  filtering; heavy work runs in Temporal workers, not request handlers.
- Strict typing keeps refactors across thirteen services safe and adds friction to quick scripts.
- One UI stack: the review workbench, the admin console and the product share components and
  authentication, and a Next.js major upgrade touches all of them at once (the repository is on
  Next.js 16 where the guide named 15).
- Revisit if a latency-critical path, most likely predicate evaluation during a fan-out at
  hundreds of thousands of businesses, cannot meet its target in Python after profiling. That
  piece could move to Go behind the same contract without changing anything else.
