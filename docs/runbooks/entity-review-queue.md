# Entity review queue (EntityReviewQueueStale, EntityReviewQueueBacklog)

Mentions that alignment cannot resolve to exactly one canonical entity wait in the rulebook's
`entity_review` table for an analyst (ADR-017). Until one is decided, its clause is missing from
the entity index, and a relation candidate that points at the name cannot be approved against an
entity (409 `rulebook-relation-target-unresolved`). Both alerts are tickets for Regulatory
Intelligence:

- `EntityReviewQueueStale`: the oldest open item has waited more than 48 hours, for an hour.
- `EntityReviewQueueBacklog`: more than 500 items have been open for 6 hours.

The rulebook reports the gauges `rulebook_entity_review_oldest_open_age_seconds` and
`rulebook_entity_review_open_items{entity_type}` when `CW_OTEL_ENDPOINT` is set, from a count
of open items it reads at most once a minute. A failed count logs
`review_metrics.read_failed` and reports nothing, so a rulebook that cannot reach its database
shows as missing data rather than as an empty queue.

## Triage

1. Which types: Prometheus or Grafana Explore, `max by (entity_type)
   (rulebook_entity_review_open_items)`. One type growing points at one extractor or one kind of
   document; every type growing points at a batch of new documents.
2. Which groups: `GET /v1/rulebook/review/entities?entity_type=<type>` lists the open groups,
   one per (entity type, proposed name), with the open count and five examples each. A few
   groups holding most of the items usually means one name recurs across many clauses; one
   decision closes all of them.
3. Why they were queued, in the database (`make dev-psql` locally, schema `rulebook`):
   `select entity_type, reason, count(*), min(created_at) from entity_review where status =
   'open' group by 1, 2 order by 3 desc`. `no_match` is a name no entity has yet,
   `ambiguous_alias` a name that is an alias of several, `unqualified` a section or rule without
   its statute, `empty_name` a mention the grammar could not name.
4. Did something change upstream? A jump in open items right after a pipeline deploy or a
   large ingest run is new documents arriving, not analysts falling behind.

## Fix

- Decide the largest groups first: `POST /v1/rulebook/review/entities/decisions` creates the
  entity, adds the name as an alias of an existing one, or rejects the group, and resolves every
  open mention of it in one transaction. It needs `x-cw-review-token` (`CW_RULEBOOK_REVIEW_TOKEN`);
  the pipeline's write token is refused.
- `unqualified` and `empty_name` groups are decided mention by mention:
  `GET /v1/rulebook/review/entities/items?entity_type=<type>&proposed_name=<name>` returns the
  review ids, and the decision lists the ones it covers in `review_ids`.
- An `ambiguous_alias` group means two entities share an alias. Decide which entity the
  mentions belong to with `add_alias` and the chosen `entity_id`; fixing the aliases themselves
  is a change to `canonical_entity` that the alias owner reviews.
- A flood of `no_match` for names that are clearly wrong (text artifacts, headings) is an
  extractor problem: reject the groups with `text_artifact` or `not_an_entity` and raise the
  grammar or prompt issue with the pipeline owners, with the group names as examples.
- Nothing is resolved automatically and no entity is created without an analyst: do not
  clear the queue with SQL.

## Escalation

The alerts are tickets, not pages: nothing is lost while items wait, but answers and relation
approvals miss the unresolved names. If the queue is still over the threshold after a working
day of review, raise it with the Regulatory Intelligence lead, who can add reviewers or turn
off `CW_PIPELINE_KNOWLEDGE_ENABLED` on the pipeline until the queue is back under the threshold
(that also stops documents reaching the rulebook). A queue that grows because of an extractor
change goes to the pipeline owners as a bug, with the reasons and group names from the triage
above.
