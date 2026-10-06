// @vitest-environment node
import { randomBytes } from "node:crypto";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { ADMIN_USER_ID, RUN_VERSION_ID, dryRunOutDto } from "@/test/engine-admin-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { runDryRun } from "./actions";
import { DRY_RUN_FIELDS } from "./ui/dry-run-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const DRY_RUNS = "/v1/applicability-engine/dry-runs";

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: ADMIN_USER_ID,
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind: "internal",
    roles,
    displayName: "Example admin",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  data.set(DRY_RUN_FIELDS.subject, "version");
  data.set(DRY_RUN_FIELDS.sampleSize, "10");
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Error(`redirect ${String(href)}`);
  });
  vi.mocked(notFound).mockImplementation(() => {
    throw new Error("not found");
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
  vi.mocked(notFound).mockReset();
  vi.clearAllMocks();
});

describe("runDryRun", () => {
  it("runs the version and answers the report worded with the ontology, and the values sent", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      { method: "POST", path: DRY_RUNS, body: dryRunOutDto() },
      { path: "/v1/ontology", body: ONTOLOGY_DTO },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await runDryRun(IDLE, form({ [DRY_RUN_FIELDS.ruleVersionId]: RUN_VERSION_ID }));
    if (state.status !== "ok" || state.value === undefined) throw new Error("not ok");
    expect(state.message).toBe("The dry run finished; nothing was stored.");
    expect(state.value.values.ruleVersionId).toBe(RUN_VERSION_ID);
    expect(state.value.report.counts[0]?.value).toBe("1");
    expect(state.value.report.byAttribute[0]?.definition).not.toBeNull();
    expect(fake.requests[0]?.body).toEqual({
      rule_version_id: RUN_VERSION_ID,
      scope: { sample_size: 10 },
    });
  });

  it("refuses the form's shape before any request, and a scope too large with the way out", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: DRY_RUNS,
        status: 422,
        problem: {
          type: "urn:compliancewatch:problem:applicability-dry-run-too-large",
          title: "Example scope too large",
        },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    expect(await runDryRun(IDLE, form({ [DRY_RUN_FIELDS.ruleVersionId]: "nope" }))).toEqual({
      status: "error",
      fieldErrors: { rule_version_id: ["Enter the rule version's id."] },
    });
    expect(fake.requests).toHaveLength(0);
    const tooLarge = await runDryRun(
      IDLE,
      form({ [DRY_RUN_FIELDS.ruleVersionId]: RUN_VERSION_ID }),
    );
    expect(tooLarge).toMatchObject({
      status: "error",
      problem: { title: "Example scope too large" },
      formErrors: ["Name a tenant to narrow the scope to its businesses."],
    });
  });

  it("passes another refusal as it came, and words the keys alone without the ontology", async () => {
    await signedInAs(["admin"]);
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        {
          method: "POST",
          path: DRY_RUNS,
          status: 404,
          problem: { title: "Example version not found" },
        },
      ]).fetchImpl,
    );
    expect(
      await runDryRun(IDLE, form({ [DRY_RUN_FIELDS.ruleVersionId]: RUN_VERSION_ID })),
    ).toMatchObject({ status: "error", problem: { title: "Example version not found" } });
    vi.stubGlobal(
      "fetch",
      fakeFetch([
        { method: "POST", path: DRY_RUNS, body: dryRunOutDto() },
        { path: "/v1/ontology", status: 503, problem: {} },
      ]).fetchImpl,
    );
    const state = await runDryRun(IDLE, form({ [DRY_RUN_FIELDS.ruleVersionId]: RUN_VERSION_ID }));
    expect(state.status === "ok" && state.value?.report.byAttribute[0]?.definition).toBeNull();
  });

  it("is not found to anyone but an admin", async () => {
    await signedInAs(["reviewer"]);
    await expect(runDryRun(IDLE, form({}))).rejects.toThrow("not found");
  });
});
