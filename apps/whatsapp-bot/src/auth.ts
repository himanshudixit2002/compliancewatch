/**
 * The bot's own access token from the identity service, for its calls to notification and
 * identity.
 *
 * With BOT_SERVICE_CLIENT_SECRET set, IdentityTokenSource exchanges the client id
 * (BOT_SERVICE_CLIENT_ID, by default whatsapp-bot) and the secret at
 * POST /v1/identity/service-tokens and keeps the token until a minute before it expires (at most
 * half its lifetime), so the bot asks identity about every nine minutes rather than once per
 * message. Callers that need a token while one is being fetched wait for that fetch. When that
 * refresh fails, the cached token keeps being used until it really expires, and identity is not
 * asked again for FAILED_FETCH_RETRY_MS: calls in between do not wait on identity, and without a
 * valid token they fail at once.
 *
 * authorizedFetch puts the token on a request as `authorization: Bearer`. When the called service
 * refuses the token itself (a 401 whose WWW-Authenticate says invalid_token, or whose problem type
 * is auth-token-invalid: it no longer trusts the key that signed the token, say) the token is
 * dropped and the request sent once more with a fresh one. Any other 401, such as a wrong shared
 * token, comes back as it came. Without the secret there is no token source, and every client
 * sends exactly what it sent before service tokens existed.
 */

type Fetch = typeof fetch;

export const SERVICE_TOKENS_PATH = "/v1/identity/service-tokens";
export const DEFAULT_IDENTITY_API_URL = "http://localhost:8001";
export const DEFAULT_BOT_CLIENT_ID = "whatsapp-bot";
/** A cached token is replaced this long before it expires (at most half its lifetime). */
export const REFRESH_MARGIN_MS = 60_000;
/** After a failed fetch, the next attempt waits this long. */
export const FAILED_FETCH_RETRY_MS = 5_000;

/** Where a client gets the bearer token it sends; `invalidate` drops one the callee refused. */
export interface BearerSource {
  token(): Promise<string>;
  invalidate(token: string): void;
}

interface CachedToken {
  readonly token: string;
  readonly refreshAt: number;
  readonly expiresAt: number;
}

/** The last failed fetch and when identity may be asked again. */
interface FailedFetch {
  readonly error: Error;
  readonly retryAt: number;
}

/** The body of identity's answer, checked before the token is used. */
function parseToken(body: unknown, clientId: string): { token: string; expiresInMs: number } {
  const answer = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  const token = answer.access_token;
  const expiresIn = answer.expires_in;
  const tokenType = answer.token_type ?? "Bearer";
  if (
    typeof token !== "string" ||
    token === "" ||
    typeof expiresIn !== "number" ||
    !Number.isFinite(expiresIn) ||
    expiresIn <= 0 ||
    typeof tokenType !== "string" ||
    tokenType.toLowerCase() !== "bearer"
  ) {
    throw new Error(
      `identity token: the answer for client ${clientId} lacks a bearer access_token and expires_in`,
    );
  }
  return { token, expiresInMs: expiresIn * 1000 };
}

/**
 * The bot's service token, exchanged with its client credentials and cached until near expiry. A
 * failed refresh leaves the cached token in use while it is valid (with a warning), and no fetch is
 * tried again for `retryMs`.
 */
export class IdentityTokenSource implements BearerSource {
  readonly clientId: string;
  private readonly url: string;
  private readonly clientSecret: string;
  private readonly fetchImpl: Fetch;
  private readonly now: () => number;
  private readonly warn: (line: string) => void;
  private readonly retryMs: number;
  private cached: CachedToken | null = null;
  private pending: Promise<CachedToken> | null = null;
  private failed: FailedFetch | null = null;

  constructor(
    identityUrl: string,
    clientId: string,
    clientSecret: string,
    fetchImpl: Fetch = fetch,
    now: () => number = Date.now,
    warn: (line: string) => void = console.warn,
    retryMs: number = FAILED_FETCH_RETRY_MS,
  ) {
    if (clientId.trim() === "") throw new Error("a service token source needs a client id");
    if (clientSecret === "") throw new Error("a service token source needs a client secret");
    this.url = `${identityUrl.replace(/\/$/, "")}${SERVICE_TOKENS_PATH}`;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.fetchImpl = fetchImpl;
    this.now = now;
    this.warn = warn;
    this.retryMs = retryMs;
  }

  /**
   * A token valid for at least the refresh margin, or, while identity cannot give a new one, the
   * cached token until it expires. Rejects when there is no valid token and identity refuses the
   * client or is down, at once and without asking identity again for `retryMs` after a failure.
   */
  async token(): Promise<string> {
    const cached = this.cached;
    const now = this.now();
    if (cached !== null && now < cached.refreshAt) return cached.token;
    if (this.pending === null) {
      const failed = this.failed;
      if (failed !== null && now < failed.retryAt) return backingOff(cached, failed, now);
      this.pending = this.refresh().finally(() => {
        this.pending = null;
      });
    }
    return (await this.pending).token;
  }

  /** Drop `token` if it is the cached one, so the next call fetches a new token. */
  invalidate(token: string): void {
    if (this.cached?.token === token) this.cached = null;
  }

  /** A fresh token, or after a failure the cached one while it is valid (not one invalidated). */
  private async refresh(): Promise<CachedToken> {
    try {
      const fresh = await this.fetchToken();
      this.failed = null;
      return fresh;
    } catch (thrown) {
      const failedAt = this.now();
      const error = thrown instanceof Error ? thrown : new Error(String(thrown));
      this.failed = { error, retryAt: failedAt + this.retryMs };
      const cached = this.cached;
      if (cached === null || failedAt >= cached.expiresAt) throw error;
      const left = Math.round((cached.expiresAt - failedAt) / 1000);
      this.warn(`whatsapp-bot: ${error.message}; keeping the cached token, valid ${left} s more`);
      return cached;
    }
  }

  private async fetchToken(): Promise<CachedToken> {
    const requestedAt = this.now();
    let res: Response;
    try {
      res = await this.fetchImpl(this.url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ client_id: this.clientId, client_secret: this.clientSecret }),
      });
    } catch (error) {
      throw new Error(`identity token: identity unreachable for client ${this.clientId}`, {
        cause: error,
      });
    }
    if (res.status !== 200) {
      throw new Error(`identity token: ${res.status} for client ${this.clientId}`);
    }
    const body: unknown = await res.json().catch(() => null);
    const { token, expiresInMs } = parseToken(body, this.clientId);
    const margin = Math.min(REFRESH_MARGIN_MS, expiresInMs / 2);
    const expiresAt = requestedAt + expiresInMs;
    this.cached = { token, refreshAt: expiresAt - margin, expiresAt };
    return this.cached;
  }
}

/** Between a failed fetch and the next attempt: the cached token while valid, else the failure. */
function backingOff(cached: CachedToken | null, failed: FailedFetch, now: number): string {
  if (cached !== null && now < cached.expiresAt) return cached.token;
  const seconds = Math.ceil((failed.retryAt - now) / 1000);
  throw new Error(`${failed.error.message}; the next attempt is in ${seconds} s`, {
    cause: failed.error,
  });
}

/**
 * The token source the environment configures: none without BOT_SERVICE_CLIENT_SECRET, else one
 * for BOT_SERVICE_CLIENT_ID (default whatsapp-bot) at IDENTITY_API_URL.
 */
export function identityTokenSource(
  env: Readonly<Record<string, string | undefined>>,
  fetchImpl: Fetch = fetch,
): IdentityTokenSource | null {
  const secret = env.BOT_SERVICE_CLIENT_SECRET ?? "";
  if (secret === "") return null;
  return new IdentityTokenSource(
    env.IDENTITY_API_URL || DEFAULT_IDENTITY_API_URL,
    env.BOT_SERVICE_CLIENT_ID || DEFAULT_BOT_CLIENT_ID,
    secret,
    fetchImpl,
  );
}

/** RFC 6750's error code for a bearer token that is expired, revoked or otherwise invalid. */
const INVALID_TOKEN_CHALLENGE = /\berror\s*=\s*"?invalid_token\b/i;
const INVALID_TOKEN_PROBLEM = /(^|[:/])auth-token-invalid$/;

/**
 * Whether `res` refuses the bearer token itself, which a fresh token may cure: a 401 with an
 * invalid_token challenge or the auth-token-invalid problem type. The body is read from a clone.
 */
export async function tokenRefused(res: Response): Promise<boolean> {
  if (res.status !== 401) return false;
  if (INVALID_TOKEN_CHALLENGE.test(res.headers.get("www-authenticate") ?? "")) return true;
  const body: unknown = await res
    .clone()
    .json()
    .catch(() => null);
  const kind =
    typeof body === "object" && body !== null ? (body as Record<string, unknown>).type : undefined;
  return typeof kind === "string" && INVALID_TOKEN_PROBLEM.test(kind);
}

/** The parts of a request the bot's clients send. */
export interface RequestParts {
  readonly method?: string;
  readonly headers?: Readonly<Record<string, string>>;
  readonly body?: string;
}

function withBearer(init: RequestParts | undefined, token: string): RequestInit {
  return { ...init, headers: { ...init?.headers, authorization: `Bearer ${token}` } };
}

/**
 * `fetchImpl(url, init)` with the source's bearer token, retried once with a fresh token when the
 * answer refuses the token (`tokenRefused`). Without a source the request goes out exactly as given.
 */
export async function authorizedFetch(
  fetchImpl: Fetch,
  tokens: BearerSource | null,
  url: string,
  init?: RequestParts,
): Promise<Response> {
  if (tokens === null) return init === undefined ? fetchImpl(url) : fetchImpl(url, init);
  const first = await tokens.token();
  const res = await fetchImpl(url, withBearer(init, first));
  if (!(await tokenRefused(res))) return res;
  tokens.invalidate(first);
  return fetchImpl(url, withBearer(init, await tokens.token()));
}
