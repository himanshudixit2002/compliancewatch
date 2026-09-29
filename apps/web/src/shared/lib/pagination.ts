/**
 * Keyset pagination state for lists: services take `limit` and an opaque `after` cursor and
 * answer with the next cursor. The app keeps the cursor in the query string and never
 * computes offsets.
 */
export interface PageQuery {
  limit: number;
  after?: string;
}

export interface PageLimits {
  defaultLimit: number;
  maxLimit: number;
}

export const DEFAULT_LIMITS: PageLimits = { defaultLimit: 20, maxLimit: 100 };

/** Reads limit and after from a query, clamping the limit; a bad limit falls back to the default. */
export function parsePageQuery(
  query: Readonly<Record<string, string | string[] | undefined>> | URLSearchParams,
  limits: PageLimits = DEFAULT_LIMITS,
): PageQuery {
  const read = (key: string): string | undefined => {
    if (query instanceof URLSearchParams) return query.get(key) ?? undefined;
    const value = query[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const rawLimit = Number(read("limit"));
  const limit =
    Number.isInteger(rawLimit) && rawLimit > 0
      ? Math.min(rawLimit, limits.maxLimit)
      : limits.defaultLimit;
  const after = read("after");
  return after === undefined || after === "" ? { limit } : { limit, after };
}

/** The query string for a page, keeping the other filters; "" when nothing is set. */
export function pageQueryString(
  page: PageQuery,
  filters: Readonly<Record<string, string | undefined>> = {},
  limits: PageLimits = DEFAULT_LIMITS,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, value);
  }
  if (page.limit !== limits.defaultLimit) params.set("limit", String(page.limit));
  if (page.after !== undefined) params.set("after", page.after);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

/** The href of the next page, or null when the service returned no cursor. */
export function nextPageHref(
  pathname: string,
  page: PageQuery,
  nextCursor: string | null | undefined,
  filters: Readonly<Record<string, string | undefined>> = {},
): string | null {
  if (nextCursor === null || nextCursor === undefined || nextCursor === "") return null;
  return `${pathname}${pageQueryString({ limit: page.limit, after: nextCursor }, filters)}`;
}

/** The href of the first page (keyset lists cannot go back one page; they restart). */
export function firstPageHref(
  pathname: string,
  page: PageQuery,
  filters: Readonly<Record<string, string | undefined>> = {},
): string {
  return `${pathname}${pageQueryString({ limit: page.limit }, filters)}`;
}
