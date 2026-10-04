// @vitest-environment node
import { randomBytes } from "node:crypto";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import { searchClauses } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;

class NotFound extends Error {}

async function signedInAs(overrides: Partial<SessionClaims> = {}): Promise<void> {
  const claims: SessionClaims = {
    userId: "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
    tenantId: "00000000-0000-4000-8000-00000000000a",
    tenantKind: "internal",
    roles: ["reviewer"],
    displayName: "Example reviewer",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(text: string): FormData {
  const data = new FormData();
  data.append("text", text);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.mocked(notFound).mockImplementation(() => {
    throw new NotFound();
  });
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(notFound).mockReset();
  vi.mocked(redirect).mockReset();
});

describe("searchClauses", () => {
  it("answers the hits with the words marked", async () => {
    await signedInAs();
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/rulebook/search",
        body: [
          {
            clause_id: EXAMPLE_CLAUSE_IDS.first,
            document_id: EXAMPLE_DOCUMENT_ID,
            clause_ref: "en.p1",
            text: "Example clause text",
            regulator: "Example regulator",
            doc_type: "circular",
            external_ref: "Example 1/2000",
            title: "Example document title",
            published_at: null,
            score: 0.0164,
            lexical_rank: 1,
            vector_rank: null,
            cited_by: [],
            out_of_force: false,
          },
        ],
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await searchClauses(IDLE, form("clause"));
    expect(state).toMatchObject({
      status: "ok",
      value: { terms: ["clause"], hits: [{ rank: 1, lexicalRank: 1, vectorRank: null }] },
    });
    expect(fake.requests[0]?.body).toEqual({ text: "clause", k: 8, doc_types: [] });
  });

  it("refuses blank words before any request and passes a failure on", async () => {
    await signedInAs();
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/rulebook/search",
        status: 422,
        problem: { title: "Example refusal" },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await searchClauses(IDLE, form(""))).toEqual({
      status: "error",
      fieldErrors: { text: ["Enter the words to search for."] },
    });
    expect(fake.requests).toHaveLength(0);
    expect(await searchClauses(IDLE, form("Example"))).toMatchObject({
      status: "error",
      problem: { title: "Example refusal" },
    });
  });

  it("is a 404 to a tenant role", async () => {
    await signedInAs({ tenantKind: "business", roles: ["owner"] });
    await expect(searchClauses(IDLE, form("Example"))).rejects.toBeInstanceOf(NotFound);
  });
});
