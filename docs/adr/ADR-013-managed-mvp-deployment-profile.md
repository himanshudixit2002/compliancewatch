# ADR-013: Managed MVP deployment profile before the Kubernetes profile

- **Status:** Proposed (Accepted when the MVP profile deploys the demo tenant)
- **Date:** 2026-09-28 (full text; recorded in the Architecture Reference v1.0, section 8.2)
- **Deciders:** Platform and Infrastructure, with the maintainer as product owner

## Context

The target architecture runs ten services on EKS with Helm and Argo CD canaries, Aurora
PostgreSQL, Amazon MSK and self-hosted Temporal (guide sections 12 and 17). That profile is
right for the fan-out volumes of a scaled product and wrong for the first months: it needs a
cluster, a mesh, GPU pools and an on-call rotation before a single pilot customer exists, and
the team is one person plus pilots.

The code is already shaped so that the deployment profile is a choice, not a rewrite: every
external dependency sits behind an interface (source adapters, notification channels, the LLM
provider, the vector store, the workflow handle, the message producer), services share one
runtime library, and the domain layers import nothing from infrastructure. Three profiles use
the same containers and the same code.

| Layer | Local | MVP | Scale |
| --- | --- | --- | --- |
| Web | `next dev` | Vercel | Vercel or EKS |
| Services | `make run` per service | one modular deployable on Railway, Render or Fly.io | ten services on EKS, Helm, Argo CD |
| Workflows | Temporal in Docker | Temporal Cloud (or Inngest) | self-hosted Temporal |
| Events | Redpanda in Docker | Postgres outbox plus a managed queue | Amazon MSK |
| Database | Postgres and pgvector in Docker | Neon or Supabase Postgres | Aurora PostgreSQL, multi-AZ |
| Embeddings | bge-m3 on CPU or Voyage | Voyage API | bge-m3 on a GPU pool |
| Public URL | Cloudflare Tunnel | platform domains | ALB and WAF |

## Decision

The MVP (the roadmap's first two stages, guide section 20) runs the managed profile. One container image serves
every service's routers from a single FastAPI process (each service keeps its package, its
schema, its import boundaries and its own migrations; only the composition root differs), and
one worker process runs the Temporal workers and the outbox relay. The platform is Railway,
Render or Fly.io, chosen in the deployment work package by price and by the availability of a
Mumbai region; the database is managed Postgres with pgvector (Neon or Supabase) in an Indian
region; Temporal Cloud runs the workflows; events stay in the transactional outbox and are
relayed to a managed queue. The web app deploys to Vercel. Identity follows ADR-014.

The Kubernetes profile stays the target for the scale stage. Its Terraform and Helm directories exist
in the repository, are built out when the fan-out volumes require it, and are not a
prerequisite for launch. Nothing that the MVP profile needs is created by automation until the
maintainer creates the accounts; each such dependency is prepared behind a flag with a list of
manual steps.

## Consequences

- Launch cost is a few managed services rather than a cluster, and the first incident runbooks
  are about a platform dashboard, not kubectl.
- Data residency (DPDP, guide section 16) constrains the choice of every managed provider to
  one with an Indian region; a provider without one is out, whatever its price.
- One deployable means one deploy per change and no per-service scaling; when a component
  needs its own scale (the fan-out worker first), it is split out first, which the package
  boundaries allow without code moves.
- The event bus and the workflow engine differ between profiles; the outbox, the consumer base
  and the worker scaffold in py-common are the seams, and integration tests run against
  Redpanda and Temporal in Docker so the local profile keeps the scale profile honest.
- Managed Temporal and managed Postgres carry per-usage cost; the LLM gateway's budgets and the
  cost ledger are the model for watching them.
- Revisit when a pilot cohort's fan-out exceeds what one worker process handles within the
  freshness objective, or when an enterprise customer needs a deployment inside its own cloud.

## As built so far

As of 2026-10-04 (package M1-1), `composition/mvp` is the one deployable, run as two processes
of the same code:

- `cw-mvp serve`: every service's FastAPI app in one uvicorn process behind one dispatcher, each
  service on its own settings and schema. The public listener (8000) serves only the routes
  `cw_mvp.exposure` classes public, and the admin ones in token mode; the internal listener
  (8080) serves every route, and the services call each other there with tokens identity mints
  in the process, so the app holds no client secrets.
- `cw-mvp worker`: every service's consumers, periodic jobs and Temporal workers and the outbox
  relays in one event loop, with a health endpoint. Kafka and Temporal each run behind a switch
  that is off by default (`CW_WORKER_KAFKA_ENABLED`, `CW_WORKER_TEMPORAL_ENABLED`).
- Managed brokers and collectors are settings of py-common: Kafka over SASL and TLS, Temporal
  Cloud API keys or client certificates, OTLP over HTTP with headers.

The relay still publishes to Kafka, so the managed queue is a Kafka-compatible one. Not built
yet: both processes run together with Kafka and Temporal on (`make product`, package M1-2, on
the dev stack first), the container image and the platform, and migrations and the seed as
release steps.
