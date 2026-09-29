import "server-only";

/**
 * Whether a state-changing request (a form POST to a route handler) comes from a page of this
 * site, so a foreign page cannot make a visitor's browser submit it. Server actions get the
 * same check from Next; a route handler does it itself.
 *
 * The answer never depends on the URL Next builds for the request: under `next start` that URL
 * carries the server's bind address (http://localhost:PORT) whatever host the browser used, so
 * comparing with it refuses every visitor who opened the app by another name (127.0.0.1, a LAN
 * address, a domain behind a reverse proxy). Instead, in order:
 *
 * 1. `Sec-Fetch-Site`, when the browser sends it: only `same-origin` passes. Browsers set it and
 *    a page cannot, so it is the strongest signal and needs no host at all.
 * 2. `Origin`, when there is no `Sec-Fetch-Site`: its host must equal the host the browser asked
 *    for, the `Host` header, or the first `X-Forwarded-Host` value when the deployment trusts its
 *    proxy's forwarded headers. The scheme is not compared: behind a TLS-terminating proxy the
 *    request arrives over http while the page's origin is https.
 * 3. Neither header: a request that is not a browser's cross-site submission (curl, a test,
 *    an old client). It passes; a browser posting from another site always sends one of the two.
 *
 * An `Origin` that is not a URL (the opaque `null` of a sandboxed frame) fails.
 */
export interface SameOriginOptions {
  /** Read the host from X-Forwarded-Host (CW_WEB_TRUST_FORWARDED_IP): only behind a proxy that sets it. */
  trustForwardedHost: boolean;
}

/** The host the browser asked for, lower-cased; null when the request names none. */
export function requestHost(headers: Headers, options: SameOriginOptions): string | null {
  const forwarded = options.trustForwardedHost
    ? headers.get("x-forwarded-host")?.split(",")[0]?.trim()
    : undefined;
  const host = forwarded || headers.get("host")?.trim();
  return host ? host.toLowerCase() : null;
}

export function isSameOriginRequest(headers: Headers, options: SameOriginOptions): boolean {
  const fetchSite = headers.get("sec-fetch-site");
  if (fetchSite !== null) return fetchSite.trim().toLowerCase() === "same-origin";
  const origin = headers.get("origin");
  if (origin === null) return true;
  const host = requestHost(headers, options);
  if (host === null) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
