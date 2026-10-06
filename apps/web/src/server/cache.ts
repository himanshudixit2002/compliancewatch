import "server-only";

import { revalidatePath, updateTag } from "next/cache";

/**
 * What the data layer caches, and how a mutation invalidates it.
 *
 * Only global reads are cached: records every tenant sees the same way (billing plans,
 * notification templates, the ontology, rulebook rules, documents and clauses, the gateway's
 * prompts and models). The review queues are global too but read fresh: the pipeline fills them
 * and analysts empty them outside this server (D-036). A gateway passes `cachedRead(tags)` as the call's fetch
 * options and Next keeps the response for `GLOBAL_REVALIDATE_SECONDS` (or the read's own
 * lifetime) under those tags. A tenant read passes
 * `uncachedRead()` (`cache: "no-store"`): profile nodes, consents, obligations and everything
 * else keyed by the session's tenant is fetched on every request. Authenticated pages are
 * `force-dynamic`; Next still honours an explicit `next.revalidate` on a fetch inside one, and
 * the fetch cache key includes the request headers, so `server/api/client.ts` gives a cached
 * read a request id derived from its tags instead of a fresh UUID.
 *
 * A server action that changes a cached record calls `afterMutation({ tags, paths })` before it
 * redirects: `updateTag` (Next 16, server actions only) expires each tag so the next read waits
 * for fresh data (read-your-writes), and `revalidatePath` refreshes the listed routes.
 * `revalidateTag(tag, "max")`, the stale-while-revalidate form for route handlers and
 * background refreshes, is not used by any screen on `main`.
 *
 * Tags are built here, never written inline, so a mutation and the reads it affects agree on
 * the string; a tag longer than Next's limit (256 characters) is a programming error and throws.
 */
export const GLOBAL_REVALIDATE_SECONDS = 300;

/** Next ignores a longer tag silently, so the builder refuses one instead. */
export const MAX_TAG_LENGTH = 256;

const SEPARATOR = ":";

export class CacheTagError extends Error {
  override readonly name = "CacheTagError";
}

/** `service:record[:part...]`; every part non-empty, no separator inside a part. */
export function cacheTag(service: string, record: string, ...parts: readonly string[]): string {
  const all = [service, record, ...parts];
  for (const part of all) {
    if (part === "") throw new CacheTagError("a cache tag part must not be empty");
    if (part.includes(SEPARATOR)) {
      throw new CacheTagError(`a cache tag part must not contain "${SEPARATOR}": ${part}`);
    }
  }
  const tag = all.join(SEPARATOR);
  if (tag.length > MAX_TAG_LENGTH) {
    throw new CacheTagError(`cache tag longer than ${MAX_TAG_LENGTH} characters: ${tag}`);
  }
  return tag;
}

/** The tags the screens read and the actions expire, one builder per cached record set. */
export const tags = {
  identity: {
    /** GET /v1/identity/billing/plans */
    plans: () => cacheTag("identity", "plans"),
    /** GET /v1/identity/consents?subject= for one tenant's subject (a tenant read; see uncachedRead) */
    consents: (tenantId: string, subject: string) =>
      cacheTag("identity", "consents", tenantId, subject),
  },
  profile: {
    /** One profile node of one tenant (a tenant read; see uncachedRead) */
    node: (tenantId: string, nodeId: string) => cacheTag("profile", "node", tenantId, nodeId),
    /** GET /v1/ontology: the attributes with their wording, the same for every tenant */
    ontology: () => cacheTag("profile", "ontology"),
  },
  rulebook: {
    /** GET /v1/rulebook/rules */
    rules: () => cacheTag("rulebook", "rules"),
    /** GET /v1/rulebook/documents/{document_id} */
    document: (documentId: string) => cacheTag("rulebook", "document", documentId),
    /** GET /v1/rulebook/clauses/{clause_id}: a clause never changes under its id */
    clause: (clauseId: string) => cacheTag("rulebook", "clause", clauseId),
  },
  notification: {
    /** GET /v1/notification/templates */
    templates: () => cacheTag("notification", "templates"),
  },
  llm: {
    /** GET /v1/llm-gateway/prompts */
    prompts: () => cacheTag("llm-gateway", "prompts"),
    /** GET /v1/llm-gateway/models */
    models: () => cacheTag("llm-gateway", "models"),
  },
} as const;

/** The fetch options a read passes to its openapi-fetch call (they reach Next's fetch). */
export interface ReadCacheOptions {
  cache?: RequestCache;
  next?: NextFetchRequestConfig;
}

/**
 * A global read: kept for `revalidateSeconds` under `tagList`, which a later `afterMutation`
 * can expire. At least one tag is required, or nothing could ever invalidate the entry.
 */
export function cachedRead(
  tagList: readonly string[],
  revalidateSeconds: number = GLOBAL_REVALIDATE_SECONDS,
): ReadCacheOptions {
  if (tagList.length === 0) throw new CacheTagError("a cached read needs at least one tag");
  if (!Number.isInteger(revalidateSeconds) || revalidateSeconds <= 0) {
    throw new CacheTagError(
      `revalidate must be a positive number of seconds: ${revalidateSeconds}`,
    );
  }
  return { next: { revalidate: revalidateSeconds, tags: [...tagList] } };
}

/** A tenant read, or any read that must reflect the service's current state: never cached. */
export function uncachedRead(): ReadCacheOptions {
  return { cache: "no-store" };
}

export interface Invalidation {
  /** Tags to expire; the next read of each waits for fresh data. */
  tags?: readonly string[];
  /** Routes to render again on their next request (`/settings/billing`, `/admin/rulebook/rules`). */
  paths?: readonly string[];
}

/**
 * Called by a server action after a successful write and before its redirect. Server actions
 * only: `updateTag` throws anywhere else (a route handler uses `revalidateTag(tag, "max")`).
 */
export function afterMutation({ tags: tagList = [], paths = [] }: Invalidation): void {
  for (const tag of tagList) updateTag(tag);
  for (const path of paths) revalidatePath(path);
}
