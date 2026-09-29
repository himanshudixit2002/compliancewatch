import type { Problem } from "@/entities/problem/types";

/**
 * A fetch stand-in for gateway and client tests: answers from a route table (or a handler),
 * records every request it received (method, URL, headers, parsed JSON body) and never touches
 * the network. Responses carry `application/problem+json` bodies for errors, like the services.
 *
 *   const { fetchImpl, requests } = fakeFetch([
 *     { method: "GET", path: "/v1/identity/billing/plans", body: [] },
 *     { method: "POST", path: "/v1/identity/consents", status: 422, problem: { errors: [...] } },
 *   ]);
 */
export interface RecordedRequest {
  method: string;
  url: string;
  pathname: string;
  headers: Record<string, string>;
  /** The JSON body, the raw text when it is not JSON, or undefined without a body. */
  body: unknown;
}

export interface FakeRoute {
  method?: string;
  /** A pathname, or a pattern matched against the pathname. */
  path: string | RegExp;
  status?: number;
  /** A JSON body for a 2xx; ignored when `problem` is set. */
  body?: unknown;
  /** An error body; `type`, `title` and `status` are filled in when absent. */
  problem?: Partial<Problem>;
  headers?: Record<string, string>;
}

export type FakeHandler = (request: RecordedRequest, raw: Request) => Response | Promise<Response>;

export interface FakeFetch {
  fetchImpl: (input: Request, init?: RequestInit) => Promise<Response>;
  requests: RecordedRequest[];
}

export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  if (status === 204 || body === undefined) return new Response(null, { status, headers });
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export function problemResponse(
  status: number,
  problem: Partial<Problem> = {},
  headers: Record<string, string> = {},
): Response {
  const body: Problem = {
    type: problem.type ?? `urn:compliancewatch:problem:test-${status}`,
    title: problem.title ?? `Test problem ${status}`,
    status,
    ...problem,
  };
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/problem+json", ...headers },
  });
}

export function textResponse(
  status: number,
  text: string,
  headers: Record<string, string> = {},
): Response {
  return new Response(text, { status, headers: { "content-type": "text/plain", ...headers } });
}

async function record(raw: Request): Promise<RecordedRequest> {
  const headers: Record<string, string> = {};
  raw.headers.forEach((value, key) => {
    headers[key] = value;
  });
  const text = await raw.text();
  let body: unknown;
  if (text !== "") {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  const url = new URL(raw.url);
  return { method: raw.method, url: raw.url, pathname: url.pathname, headers, body };
}

function matches(route: FakeRoute, request: RecordedRequest): boolean {
  if (route.method !== undefined && route.method.toUpperCase() !== request.method) return false;
  return typeof route.path === "string"
    ? route.path === request.pathname
    : route.path.test(request.pathname);
}

function respond(route: FakeRoute): Response {
  if (route.problem !== undefined) {
    return problemResponse(route.status ?? 400, route.problem, route.headers);
  }
  return jsonResponse(route.status ?? 200, route.body, route.headers);
}

/** Answers from the route table (first match wins; no match is a 404 problem) or the handler. */
export function fakeFetch(routes: readonly FakeRoute[] | FakeHandler): FakeFetch {
  const requests: RecordedRequest[] = [];
  const handler: FakeHandler =
    typeof routes === "function"
      ? routes
      : (request) => {
          const route = routes.find((candidate) => matches(candidate, request));
          return route === undefined
            ? problemResponse(404, {
                title: `No fake route for ${request.method} ${request.pathname}`,
              })
            : respond(route);
        };
  return {
    requests,
    fetchImpl: async (input) => {
      const recorded = await record(input);
      requests.push(recorded);
      return handler(recorded, input);
    },
  };
}

/** A fetch that never answers and rejects with the signal's reason when aborted. */
export function hangingFetch(): FakeFetch {
  const requests: RecordedRequest[] = [];
  return {
    requests,
    fetchImpl: async (input, init) => {
      requests.push(await record(input));
      return new Promise((_, reject) => {
        const signal = init?.signal;
        if (signal === undefined || signal === null) return;
        if (signal.aborted) {
          reject(signal.reason as Error);
          return;
        }
        signal.addEventListener("abort", () => reject(signal.reason as Error), { once: true });
      });
    },
  };
}

/** A fetch whose connection is refused, as undici reports it. */
export function refusingFetch(): FakeFetch {
  const requests: RecordedRequest[] = [];
  return {
    requests,
    fetchImpl: async (input) => {
      requests.push(await record(input));
      throw new TypeError("fetch failed", { cause: new Error("connect ECONNREFUSED") });
    },
  };
}
