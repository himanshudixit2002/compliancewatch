# API SLO burn (ApiErrorBurnRate, ApiLatencyBurnRate)

Objective (architecture reference 8.3): public API availability 99.9%, read latency p95
under 300 ms. The alerts fire when the 1-hour error share is above 0.2% (twice the monthly
budget's burn) or p95 is above 600 ms for 15 minutes.

## First five minutes

1. Which service: the alert's `service_name`. Grafana dashboard `cw-services` shows the request
   rate, p95 and error rate per service; Tempo (Explore) has the traces of the failing route
   (`http_response_status_code = 5xx`).
2. Is it one route or everything? The dashboard's routes panel breaks the errors down by
   `http_route`. One route: a bug or a downstream (a database timeout shows as 503 from
   `/ready` first). Everything: the service is down, out of memory or its database is.
3. A deploy in the last hour? Roll it back (Fly: `fly releases` then `fly deploy --image` of the
   previous image; the Argo CD canary rolls back on its own once it exists).

## Common causes

- Database connection limit: `make dev-psql` (dev) or the managed console shows
  `pg_stat_activity`; the services use `NullPool` and open a connection per request, so a
  slow query multiplies connections.
- The llm-gateway's provider is slow: the gateway's latency shows in `latency_ms` of its
  log lines; the breaker opens after three failures and the fallback model takes over.
- A tenant hammering one endpoint: the `tenant_id` field in the logs; there is no per-tenant
  rate limit yet, so the fix is a WAF rule or an API key revocation.

## After

Write the timeline in the incident channel, open the postmortem within five working days
(S2 when the product API was down). Rule publication pauses while an S1 is open.
