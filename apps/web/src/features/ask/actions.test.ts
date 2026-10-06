// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { encryptSession } from "@/server/session";
import { answerDto, notCoveredDto } from "@/test/answer-fixture";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { DOCUMENT_ID, TENANT_ID } from "@/test/obligation-fixture";
import { documentDto } from "@/test/rulebook-fixture";
import { askQuestion } from "./actions";
import { ASK_FIELDS } from "./ui/answer-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;

async function signedIn(): Promise<void> {
  const claims: SessionClaims = {
    userId: "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
    tenantId: TENANT_ID,
    tenantKind: "business",
    roles: ["owner"],
    displayName: "Example owner",
    mfa: false,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(values: Record<string, string> = {}): FormData {
  const data = new FormData();
  data.set(ASK_FIELDS.businessId, ENTITY_ID);
  data.set(ASK_FIELDS.question, "Example question?");
  data.set(ASK_FIELDS.node, REGISTRATION_ID);
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_FLAG_QA_ENABLED", "true");
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
});

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  await resetFlagReader();
  vi.mocked(redirect).mockReset();
});

describe("askQuestion", () => {
  it("asks about the chosen node and joins each citation with its clause", async () => {
    await signedIn();
    const document = documentDto({ document_id: DOCUMENT_ID });
    const clauseRef = document.clauses[0]?.clause_ref ?? "en.p1";
    const fake = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      {
        method: "POST",
        path: "/v1/qa",
        body: answerDto({
          citations: [{ clause_ref: clauseRef, document_id: DOCUMENT_ID, quote: "Example quote" }],
        }),
      },
      { path: `/v1/rulebook/documents/${DOCUMENT_ID}`, body: document },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await askQuestion(IDLE, form());
    expect(state.status).toBe("ok");
    if (state.status !== "ok") return;
    expect(state.value).toMatchObject({
      question: "Example question?",
      about: "29ABCDE1234F1Z5 (Example registration)",
      outcome: "answered",
    });
    expect(state.value?.citations[0]?.documentTitle).toBe("Example document title");
    expect(fake.requests.find((request) => request.pathname === "/v1/qa")?.body).toEqual({
      question: "Example question?",
      business_node_id: REGISTRATION_ID,
    });
  });

  it("shows a question that is not covered as the answer it is", async () => {
    await signedIn();
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
        { method: "POST", path: "/v1/qa", body: notCoveredDto() },
      ]).fetchImpl,
    );
    const state = await askQuestion(IDLE, form());
    expect(state.status === "ok" && state.value?.outcome).toBe("not_covered");
  });

  it("refuses a bad form before asking, and passes on the service's refusal", async () => {
    await signedIn();
    const fake = fakeFetch([
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { method: "POST", path: "/v1/qa", status: 429, problem: { title: "Example budget used up" } },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const empty = await askQuestion(IDLE, form({ [ASK_FIELDS.question]: " " }));
    expect(empty).toEqual({
      status: "error",
      fieldErrors: { [ASK_FIELDS.question]: ["Write a question first."] },
    });
    expect(fake.requests.some((request) => request.pathname === "/v1/qa")).toBe(false);
    const limited = await askQuestion(IDLE, form());
    expect(limited).toMatchObject({
      status: "error",
      problem: { title: "Example budget used up" },
    });
    const noBusiness = await askQuestion(IDLE, form({ [ASK_FIELDS.businessId]: "x" }));
    expect(noBusiness).toEqual({
      status: "error",
      formErrors: ["This form names no business. Reload the page."],
    });
  });

  it("refuses while the flag is off, and passes on a missing business", async () => {
    await signedIn();
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: { title: "Example missing" } },
      ]).fetchImpl,
    );
    expect(await askQuestion(IDLE, form())).toMatchObject({
      status: "error",
      problem: { title: "Example missing" },
    });
    vi.stubEnv("CW_WEB_FLAG_QA_ENABLED", "false");
    resetEnvCache();
    await resetFlagReader();
    expect(await askQuestion(IDLE, form())).toEqual({
      status: "error",
      formErrors: ["Asking questions is not switched on for this tenant (web.qa_enabled)."],
    });
  });
});
