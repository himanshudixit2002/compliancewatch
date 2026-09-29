import type { identity, notification, profile, rulebook } from "@compliancewatch/contracts/openapi";
import createClient, { type Client } from "openapi-fetch";
import type { SeedService } from "./lib.mts";

/**
 * The seed's HTTP layer: one openapi-fetch client per service it fills, typed from the committed
 * specs, and `expectOk()`, which turns a call into its data or a `SeedError` carrying the
 * problem the service answered (type, title, detail, correlation id) or the connection failure.
 * The tenant-scoped clients send x-tenant-id; the rulebook admin client sends the write token
 * and nothing else does. Every request carries an x-request-id the services echo as the
 * problem's correlation_id, so a failure names the log line to look for.
 */
export interface SeedFailure {
  step: string;
  request: string;
  status?: number;
  type?: string;
  title?: string;
  detail?: string;
  correlationId?: string;
  hint?: string;
}

export class SeedError extends Error {
  override readonly name = "SeedError";
  readonly failure: SeedFailure;

  constructor(failure: SeedFailure) {
    super(describeFailure(failure));
    this.failure = failure;
  }
}

export function describeFailure(failure: SeedFailure): string {
  const parts = [`${failure.step}: ${failure.request}`];
  if (failure.status !== undefined) parts.push(`-> ${failure.status}`);
  if (failure.type !== undefined) parts.push(failure.type);
  if (failure.title !== undefined) parts.push(`"${failure.title}"`);
  if (failure.detail !== undefined && failure.detail !== "") parts.push(`(${failure.detail})`);
  if (failure.correlationId !== undefined) parts.push(`[correlation ${failure.correlationId}]`);
  const line = parts.join(" ");
  return failure.hint === undefined ? line : `${line}\n  hint: ${failure.hint}`;
}

export interface SeedClients {
  identity: Client<identity.paths>;
  profile: Client<profile.paths>;
  notification: Client<notification.paths>;
  rulebook: Client<rulebook.paths>;
  /** The rulebook with the write token; only the rulebook step uses it. */
  rulebookAdmin: Client<rulebook.paths>;
}

let requestCounter = 0;

function requestId(): string {
  requestCounter += 1;
  return `seed-${process.pid}-${requestCounter}`;
}

function clientFor<Paths extends object>(
  baseUrl: string,
  headers: Record<string, string>,
  fetchImpl: typeof fetch,
): Client<Paths> {
  const client = createClient<Paths>({
    baseUrl,
    headers: { accept: "application/json", ...headers },
    fetch: fetchImpl,
  });
  client.use({
    onRequest({ request }) {
      request.headers.set("x-request-id", requestId());
    },
  });
  return client;
}

/** `fetchImpl` is the network; the tests pass a stand-in that records the requests. */
export function seedClients(
  urls: Readonly<Record<SeedService, string>>,
  tenantId: string,
  writeToken: string,
  fetchImpl: typeof fetch = globalThis.fetch,
): SeedClients {
  const tenant = { "x-tenant-id": tenantId };
  return {
    identity: clientFor<identity.paths>(urls.identity, tenant, fetchImpl),
    profile: clientFor<profile.paths>(urls.profile, tenant, fetchImpl),
    notification: clientFor<notification.paths>(urls.notification, tenant, fetchImpl),
    rulebook: clientFor<rulebook.paths>(urls.rulebook, {}, fetchImpl),
    rulebookAdmin: clientFor<rulebook.paths>(
      urls.rulebook,
      { "x-cw-write-token": writeToken },
      fetchImpl,
    ),
  };
}

/** The `{ data, error, response }` an openapi-fetch method resolves to, as `expectOk` needs it. */
export interface CallOutcome<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

interface ProblemLike {
  type?: unknown;
  title?: unknown;
  detail?: unknown;
  correlation_id?: unknown;
  errors?: unknown;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/** A problem+json body (or any JSON the service sent) as the failure's fields. */
export function failureFromBody(
  step: string,
  request: string,
  status: number,
  body: unknown,
  hint?: string,
): SeedFailure {
  const problem: ProblemLike = typeof body === "object" && body !== null ? body : {};
  const failure: SeedFailure = { step, request, status };
  const type = text(problem.type);
  const title = text(problem.title);
  const correlationId = text(problem.correlation_id);
  let detail = text(problem.detail);
  if (Array.isArray(problem.errors) && problem.errors.length > 0) {
    const issues = problem.errors
      .map((issue: unknown) => {
        const record = typeof issue === "object" && issue !== null ? issue : {};
        const loc = Array.isArray((record as { loc?: unknown }).loc)
          ? ((record as { loc: unknown[] }).loc as unknown[]).map(String).join(".")
          : "?";
        return `${loc}: ${text((record as { msg?: unknown }).msg) ?? "invalid"}`;
      })
      .join("; ");
    detail = detail === undefined ? issues : `${detail}; ${issues}`;
  }
  if (type !== undefined) failure.type = type;
  if (title !== undefined) failure.title = title;
  if (detail !== undefined) failure.detail = detail;
  if (correlationId !== undefined) failure.correlationId = correlationId;
  if (typeof body === "string" && body !== "" && detail === undefined) {
    failure.detail = body.slice(0, 200);
  }
  if (hint !== undefined) failure.hint = hint;
  return failure;
}

/**
 * Why a request never got an answer, from the innermost cause: fetch wraps the socket error, and
 * a refused connection to "localhost" is an AggregateError over both addresses, often with an
 * empty message and only a code.
 */
export function unreachableReason(error: unknown): string {
  if (error instanceof AggregateError && error.errors.length > 0) {
    return [...new Set(error.errors.map(unreachableReason))].join("; ");
  }
  if (error instanceof Error) {
    if (error.cause !== undefined) return unreachableReason(error.cause);
    if (error.message !== "") return error.message;
    const code = (error as Error & { code?: unknown }).code;
    return typeof code === "string" && code !== "" ? code : error.name;
  }
  return String(error);
}

/**
 * The data of a successful call. A non-2xx answer or a connection failure throws a SeedError;
 * `hints` maps a status to the sentence printed under it (what to set, what to check).
 */
export async function expectOk<T>(
  step: string,
  request: string,
  promise: Promise<CallOutcome<T>>,
  hints: Readonly<Record<number, string>> = {},
): Promise<{ data: T; status: number }> {
  let outcome: CallOutcome<T>;
  try {
    outcome = await promise;
  } catch (error) {
    throw new SeedError({
      step,
      request,
      title: "could not reach the service",
      detail: unreachableReason(error),
      hint: "is the stack running? make web-stack && make web-stack-wait",
    });
  }
  const { response } = outcome;
  if (!response.ok) {
    throw new SeedError(
      failureFromBody(step, request, response.status, outcome.error, hints[response.status]),
    );
  }
  return { data: outcome.data as T, status: response.status };
}
