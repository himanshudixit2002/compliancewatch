// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  SeedError,
  describeFailure,
  expectOk,
  failureFromBody,
  seedClients,
  unreachableReason,
  type CallOutcome,
} from "./http.mts";
import { serviceUrls } from "./lib.mts";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const TOKEN = "example-write-token";

function recordingFetch(): { fetchImpl: typeof fetch; requests: Request[] } {
  const requests: Request[] = [];
  const fetchImpl = (async (input: Request) => {
    requests.push(input);
    return new Response("[]", { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  return { fetchImpl, requests };
}

function outcome<T>(status: number, data?: T, error?: unknown): Promise<CallOutcome<T>> {
  const result: CallOutcome<T> = { response: new Response(null, { status }) };
  if (data !== undefined) result.data = data;
  if (error !== undefined) result.error = error;
  return Promise.resolve(result);
}

describe("seedClients", () => {
  it("sends the tenant to the tenant-scoped services and the write token only as the rulebook admin", async () => {
    const { fetchImpl, requests } = recordingFetch();
    const clients = seedClients(
      serviceUrls({ SERVICE_PORT_BASE: "9200" }),
      TENANT,
      TOKEN,
      fetchImpl,
    );
    await clients.identity.GET("/v1/identity/consents", {
      params: { query: { subject: TENANT } },
    });
    await clients.profile.GET("/v1/profile/nodes/{node_id}/review-tasks", {
      params: { path: { node_id: TENANT } },
    });
    await clients.notification.GET("/v1/notification/preferences/{channel}/{recipient}", {
      params: { path: { channel: "whatsapp", recipient: "910000000000" } },
    });
    await clients.rulebook.GET("/v1/rulebook/rules");
    await clients.rulebookAdmin.GET("/v1/rulebook/rules");

    expect(requests.map((request) => new URL(request.url).origin)).toEqual([
      "http://localhost:9201",
      "http://localhost:9202",
      "http://localhost:9206",
      "http://localhost:9203",
      "http://localhost:9203",
    ]);
    expect(requests.map((request) => request.headers.get("x-tenant-id"))).toEqual([
      TENANT,
      TENANT,
      TENANT,
      null,
      null,
    ]);
    expect(requests.map((request) => request.headers.get("x-cw-write-token"))).toEqual([
      null,
      null,
      null,
      null,
      TOKEN,
    ]);
    const ids = requests.map((request) => request.headers.get("x-request-id"));
    expect(ids.every((id) => id !== null && id.startsWith("seed-"))).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
    expect(requests.every((request) => request.headers.get("accept") === "application/json")).toBe(
      true,
    );
    expect(new URL(requests[0]?.url ?? "").searchParams.get("subject")).toBe(TENANT);
  });
});

describe("failureFromBody", () => {
  it("reads a problem's type, title, detail and correlation id, and folds in the validation issues", () => {
    const failure = failureFromBody(
      "profile",
      "PUT /x",
      422,
      {
        type: "urn:example:invalid",
        title: "Invalid",
        detail: "two fields",
        correlation_id: "seed-1-1",
        errors: [{ loc: ["body", "changes", 0, "value"], msg: "bad value" }, { msg: "" }, "odd"],
      },
      "check the answers",
    );
    expect(failure).toEqual({
      step: "profile",
      request: "PUT /x",
      status: 422,
      type: "urn:example:invalid",
      title: "Invalid",
      detail: "two fields; body.changes.0.value: bad value; ?: invalid; ?: invalid",
      correlationId: "seed-1-1",
      hint: "check the answers",
    });
  });

  it("uses the issues alone as the detail when the problem has none", () => {
    expect(
      failureFromBody("s", "r", 422, { errors: [{ loc: ["query", "fy"], msg: "x" }] }),
    ).toEqual({ step: "s", request: "r", status: 422, detail: "query.fy: x" });
  });

  it("keeps the start of a plain-text body and ignores what is not a problem", () => {
    expect(failureFromBody("s", "r", 502, "Bad gateway".repeat(40)).detail).toHaveLength(200);
    expect(failureFromBody("s", "r", 500, null)).toEqual({ step: "s", request: "r", status: 500 });
    expect(failureFromBody("s", "r", 500, { title: "", errors: [] })).toEqual({
      step: "s",
      request: "r",
      status: 500,
    });
  });
});

describe("describeFailure", () => {
  it("prints the request, status, problem and correlation id on one line and the hint under it", () => {
    expect(
      describeFailure({
        step: "rulebook",
        request: "PUT /doc",
        status: 401,
        type: "urn:example:token",
        title: "Token wrong",
        detail: "set it",
        correlationId: "seed-1-2",
        hint: "use the same token",
      }),
    ).toBe(
      'rulebook: PUT /doc -> 401 urn:example:token "Token wrong" (set it) [correlation seed-1-2]\n' +
        "  hint: use the same token",
    );
    expect(describeFailure({ step: "s", request: "r" })).toBe("s: r");
  });
});

describe("expectOk", () => {
  it("returns the data and the status of a 2xx answer", async () => {
    await expect(expectOk("s", "GET /x", outcome(201, { id: 1 }))).resolves.toEqual({
      data: { id: 1 },
      status: 201,
    });
  });

  it("throws a SeedError with the problem and the hint for the status", async () => {
    const call = expectOk("s", "PUT /x", outcome(409, undefined, { title: "Conflict" }), {
      409: "start the stack again",
    });
    await expect(call).rejects.toBeInstanceOf(SeedError);
    await expect(call).rejects.toMatchObject({
      failure: { status: 409, title: "Conflict", hint: "start the stack again" },
      message: expect.stringContaining('-> 409 "Conflict"') as unknown,
    });
  });

  it("reports a connection failure with its cause and the command that starts the stack", async () => {
    const refused = new TypeError("fetch failed", { cause: new Error("connect ECONNREFUSED") });
    const call = expectOk("s", "GET /x", Promise.reject(refused));
    await expect(call).rejects.toMatchObject({
      failure: {
        step: "s",
        title: "could not reach the service",
        detail: "connect ECONNREFUSED",
        hint: expect.stringContaining("make web-stack") as unknown,
      },
    });
    await expect(expectOk("s", "GET /x", Promise.reject("down"))).rejects.toMatchObject({
      failure: { detail: "down" },
    });
  });
});

describe("unreachableReason", () => {
  it("names the innermost cause, every address of a refused localhost and a bare error code", () => {
    const refusedBoth = Object.assign(
      new AggregateError(
        [
          new Error("connect ECONNREFUSED ::1:9201"),
          new Error("connect ECONNREFUSED 127.0.0.1:9201"),
          new Error("connect ECONNREFUSED 127.0.0.1:9201"),
        ],
        "",
      ),
      { code: "ECONNREFUSED" },
    );
    expect(unreachableReason(new TypeError("fetch failed", { cause: refusedBoth }))).toBe(
      "connect ECONNREFUSED ::1:9201; connect ECONNREFUSED 127.0.0.1:9201",
    );
    expect(unreachableReason(Object.assign(new Error(""), { code: "ETIMEDOUT" }))).toBe(
      "ETIMEDOUT",
    );
    expect(unreachableReason(new AggregateError([], ""))).toBe("AggregateError");
    expect(unreachableReason(new Error("socket hang up"))).toBe("socket hang up");
    expect(unreachableReason(42)).toBe("42");
  });

  it("leaves an empty detail out of the printed line", () => {
    expect(describeFailure({ step: "s", request: "r", title: "t", detail: "" })).toBe('s: r "t"');
  });
});
