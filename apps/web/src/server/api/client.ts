import "server-only";

import { randomUUID } from "node:crypto";
import createClient, { type Client } from "openapi-fetch";
import type { ServiceName } from "@/shared/config/services";
import { err, ok, type Result } from "../result";
import { networkError, problemFromBody, toApiError } from "./problem";

/**
 * One openapi-fetch client per service, bound to the paths generated from its committed spec.
 * Every request carries a fresh x-request-id (a UUID the services echo as the problem's
 * correlation_id and in their logs), `accept: application/json`, the time limit from
 * CW_WEB_REQUEST_TIMEOUT_MS, and the headers the service factory adds (the tenant header, the
 * rulebook write token). `call()` turns the client's `{ data, error, response }` into a
 * `Result`: a value with its request id, or an `ApiError` from the problem body; a refused
 * connection or a timeout becomes `kind: "network"`, still with the request id. Nothing here
 * throws for an expected failure, and nothing here runs in a browser.
 */
export const REQUEST_ID_HEADER = "x-request-id";
export const TENANT_HEADER = "x-tenant-id";
export const WRITE_TOKEN_HEADER = "x-cw-write-token";

/** What a test injects in place of fetch: the Request openapi-fetch built plus the signal. */
export type FetchImpl = (input: Request, init?: RequestInit) => Promise<Response>;

export interface ServiceClientOptions {
  service: ServiceName;
  baseUrl: string;
  timeoutMs: number;
  fetchImpl?: FetchImpl;
  /** Headers every request of this client sends, on top of accept and x-request-id. */
  headers?: Readonly<Record<string, string>>;
}

/** The exception openapi-fetch rethrows, wrapped with the request id; `call` converts it. */
export class NetworkFailure extends Error {
  override readonly name = "NetworkFailure";
  readonly service: ServiceName;
  readonly requestId: string;
  readonly timeoutMs: number;

  constructor(service: ServiceName, requestId: string, timeoutMs: number, cause: unknown) {
    super(`${service}: request ${requestId} failed before a response arrived`, { cause });
    this.service = service;
    this.requestId = requestId;
    this.timeoutMs = timeoutMs;
  }
}

const REQUEST_IDS = new WeakMap<Response, string>();

/** The x-request-id sent with the request that produced the response ("" when unknown). */
export function requestIdOf(response: Response): string {
  return REQUEST_IDS.get(response) ?? response.headers.get(REQUEST_ID_HEADER) ?? "";
}

function withTimeout(request: Request, timeoutMs: number): AbortSignal {
  return AbortSignal.any([request.signal, AbortSignal.timeout(timeoutMs)]);
}

export function createServiceClient<Paths extends object>(
  options: ServiceClientOptions,
): Client<Paths> {
  const fetchImpl: FetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const client = createClient<Paths>({
    baseUrl: options.baseUrl,
    headers: { accept: "application/json", ...options.headers },
    fetch: (request) => fetchImpl(request, { signal: withTimeout(request, options.timeoutMs) }),
  });
  client.use({
    onRequest({ request }) {
      request.headers.set(REQUEST_ID_HEADER, randomUUID());
    },
    onResponse({ request, response }) {
      REQUEST_IDS.set(response, request.headers.get(REQUEST_ID_HEADER) ?? "");
    },
    onError({ request, error }) {
      const requestId = request.headers.get(REQUEST_ID_HEADER) ?? "";
      return new NetworkFailure(options.service, requestId, options.timeoutMs, error);
    },
  });
  return client;
}

/** What an openapi-fetch method resolves to, in the shape `call` needs. */
export type CallOutcome<T> =
  | { data: T; error?: never; response: Response }
  | { data?: never; error: unknown; response: Response };

/**
 * `const plans = await call(identityClient(ctx).GET("/v1/identity/billing/plans"))`.
 * A 2xx gives `ok(data, requestId)` (data is undefined for a 204); anything else gives the
 * ApiError for the status and body; a NetworkFailure gives `kind: "network"`. Any other
 * exception is a bug and propagates.
 */
export async function call<T>(promise: Promise<CallOutcome<T>>): Promise<Result<T>> {
  let outcome: CallOutcome<T>;
  try {
    outcome = await promise;
  } catch (error) {
    if (error instanceof NetworkFailure) {
      return err(networkError(error.requestId, error.cause, error.timeoutMs));
    }
    throw error;
  }
  const { response } = outcome;
  const requestId = requestIdOf(response);
  if (response.ok) return ok(outcome.data as T, requestId);
  return err(
    toApiError({
      status: response.status,
      headers: response.headers,
      problem: problemFromBody(outcome.error),
      requestId,
    }),
  );
}
