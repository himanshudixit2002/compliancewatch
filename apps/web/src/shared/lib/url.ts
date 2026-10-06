/**
 * URL helpers for redirects and links. A `next` parameter from a request is only honoured
 * when it is a relative path inside this app, so a sign-in link can never send a user to
 * another origin.
 */
const CONTROL_OR_SPACE = /[\s\u0000-\u001f\u007f]/;

/** A same-origin path such as "/settings/team?tab=1"; anything else yields the fallback. */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (typeof next !== "string" || next === "") return fallback;
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (next.includes("\\") || CONTROL_OR_SPACE.test(next)) return fallback;
  if (/^\/[^/?#]*:/.test(next)) return fallback;
  return next;
}

/** Appends a query string, skipping undefined and empty values. */
export function withQuery(
  pathname: string,
  params: Readonly<Record<string, string | number | undefined>>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text === "" ? pathname : `${pathname}?${text}`;
}

/** The pathname of a URL or path string, without query or hash. */
export function pathnameOf(value: string): string {
  const stop = value.search(/[?#]/);
  return stop === -1 ? value : value.slice(0, stop);
}

/** A link is active on its own path and on paths below it, except the root and section homes. */
export function isActivePath(
  href: string,
  currentPath: string,
  roots: readonly string[] = ["/", "/admin"],
): boolean {
  if (roots.includes(href)) return currentPath === href;
  return currentPath === href || currentPath.startsWith(`${href}/`);
}

/** The one href to mark current: the longest of those active on the path, or null. */
export function activeHref(hrefs: readonly string[], currentPath: string): string | null {
  let best: string | null = null;
  for (const href of hrefs) {
    if (isActivePath(href, currentPath) && (best === null || href.length > best.length))
      best = href;
  }
  return best;
}

/** An http or https address as a link target; anything else (javascript:, data:, junk) is null. */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}
