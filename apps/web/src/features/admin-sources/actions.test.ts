// @vitest-environment node
import { randomBytes } from "node:crypto";
import { refresh, revalidatePath } from "next/cache";
import { notFound, redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { ACTOR_ID, SOURCE_KEY, sourceDto } from "@/test/pipeline-fixture";
import { editSource, fetchSource } from "./actions";
import { FETCH_FIELDS, SETTINGS_FIELDS, SETTINGS_RENDERED_FIELDS } from "./ui/source-shared";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn(), refresh: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const IDLE = { status: "idle" } as const;
const REASON = "Example reason of enough length";
const SOURCE = `/v1/pipeline/sources/${SOURCE_KEY}`;

async function signedInAs(roles: SessionClaims["roles"]): Promise<void> {
  const claims: SessionClaims = {
    userId: ACTOR_ID,
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

/**
 * The settings form as the page renders it for `sourceDto()` (its hidden fields say so), changed by
 * `overrides`.
 */
function settingsForm(overrides: Record<string, string | null> = {}): FormData {
  const values: Record<string, string | null> = {
    [SETTINGS_FIELDS.name]: "Example notices",
    [SETTINGS_FIELDS.cadence]: "7200",
    [SETTINGS_FIELDS.enabled]: "on",
    [SETTINGS_FIELDS.paused]: null,
    [SETTINGS_FIELDS.parameters]: '{"listing": "notices"}',
    [SETTINGS_FIELDS.reason]: REASON,
    [SETTINGS_RENDERED_FIELDS.name]: "Example notices",
    [SETTINGS_RENDERED_FIELDS.cadence]: "7200",
    [SETTINGS_RENDERED_FIELDS.enabled]: "on",
    [SETTINGS_RENDERED_FIELDS.paused]: "off",
    [SETTINGS_RENDERED_FIELDS.parameters]: '{\n  "listing": "notices"\n}',
    ...overrides,
  };
  const data = new FormData();
  for (const [name, value] of Object.entries(values)) if (value !== null) data.set(name, value);
  return data;
}

beforeEach(() => {
  fakeCookies.reset();
  vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(KEY).toString("base64"));
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
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

describe("editSource", () => {
  it("sends only what changed with the reason and the admin, and renders the pages again", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch((request) =>
      request.method === "GET"
        ? jsonResponse(200, { items: [sourceDto()] })
        : jsonResponse(200, sourceDto({ paused: true })),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await editSource(
      SOURCE_KEY,
      IDLE,
      settingsForm({ [SETTINGS_FIELDS.paused]: "on" }),
    );
    expect(state).toMatchObject({
      status: "ok",
      value: { message: "Saved: paused.", changed: ["paused"] },
    });
    const patch = fake.requests.find((request) => request.method === "PATCH");
    expect(patch?.pathname).toBe(SOURCE);
    expect(patch?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON, paused: true });
    expect(patch?.headers["x-cw-write-token"]).toBe("example-write-token");
    expect(vi.mocked(revalidatePath).mock.calls.map(([path]) => path)).toEqual([
      "/admin/sources",
      SOURCE.replace("/v1/pipeline", "/admin"),
    ]);
  });

  it("refuses an analyst, an unknown key and an unchanged form before any write", async () => {
    await signedInAs(["analyst"]);
    const fake = fakeFetch(() => jsonResponse(200, { items: [sourceDto()] }));
    vi.stubGlobal("fetch", fake.fetchImpl);
    const changed = settingsForm({ [SETTINGS_FIELDS.cadence]: "3600" });
    expect(await editSource(SOURCE_KEY, IDLE, changed)).toMatchObject({
      status: "error",
      formErrors: ["Only an admin changes a source"],
    });
    await signedInAs(["admin"]);
    expect((await editSource("Bad-Key", IDLE, changed)).status).toBe("error");
    expect(await editSource("example_unknown", IDLE, changed)).toMatchObject({
      status: "error",
      formErrors: ["The pipeline holds no source under this key"],
    });
    expect(await editSource(SOURCE_KEY, IDLE, settingsForm())).toMatchObject({
      status: "error",
      formErrors: [expect.stringMatching(/^Nothing to save/)],
    });
    expect(
      await editSource(SOURCE_KEY, IDLE, settingsForm({ [SETTINGS_FIELDS.reason]: "short" })),
    ).toMatchObject({ status: "error", fieldErrors: { reason: [expect.any(String)] } });
    expect(
      await editSource(
        SOURCE_KEY,
        IDLE,
        settingsForm({
          [SETTINGS_FIELDS.cadence]: "3600",
          [SETTINGS_RENDERED_FIELDS.paused]: null,
        }),
      ),
    ).toMatchObject({
      status: "error",
      formErrors: [expect.stringMatching(/^The form did not say which settings it showed/)],
    });
    expect(fake.requests.some((request) => request.method === "PATCH")).toBe(false);
  });

  it("keeps another admin's pause when a form rendered before it changes only the cadence", async () => {
    // Admin A opened the source unpaused; admin B paused it; A changed only the cadence and saved.
    await signedInAs(["admin"]);
    const fake = fakeFetch((request) =>
      request.method === "GET"
        ? jsonResponse(200, { items: [sourceDto({ paused: true })] })
        : jsonResponse(200, sourceDto({ paused: true, cadence_seconds: 3600 })),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await editSource(
      SOURCE_KEY,
      IDLE,
      settingsForm({ [SETTINGS_FIELDS.cadence]: "3600" }),
    );
    expect(state).toMatchObject({
      status: "ok",
      value: { message: "Saved: cadence.", changed: ["cadenceSeconds"] },
    });
    const patch = fake.requests.find((request) => request.method === "PATCH");
    expect(patch?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON, cadence_seconds: 3600 });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("refuses a change to a setting someone else changed meanwhile, sends nothing and renders again", async () => {
    // B set the cadence to four hours after A's form rendered two; A asked for one.
    await signedInAs(["admin"]);
    const fake = fakeFetch(() =>
      jsonResponse(200, { items: [sourceDto({ cadence_seconds: 14_400, paused: true })] }),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await editSource(
      SOURCE_KEY,
      IDLE,
      settingsForm({
        [SETTINGS_FIELDS.cadence]: "3600",
        [SETTINGS_FIELDS.name]: "Example renamed",
      }),
    );
    expect(state).toEqual({
      status: "error",
      formErrors: [
        "The cadence changed meanwhile: it is now 14400 seconds (4 h).",
        "Nothing was saved. The form now shows the source as the pipeline holds it: make your change again if it still applies.",
      ],
    });
    expect(fake.requests.map((request) => request.method)).toEqual(["GET"]);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("says the parameters were refused under their field, and passes a failed read on", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch((request) =>
      request.method === "GET"
        ? jsonResponse(200, { items: [sourceDto()] })
        : problemResponse(422, {
            type: "urn:compliancewatch:problem:pipeline-source-invalid",
            detail: "listing: Example refusal",
          }),
    );
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await editSource(
      SOURCE_KEY,
      IDLE,
      settingsForm({ [SETTINGS_FIELDS.parameters]: '{"listing": "example"}' }),
    );
    expect(state).toMatchObject({
      status: "error",
      problem: { title: "The pipeline refused the parameters", detail: "listing: Example refusal" },
      fieldErrors: { parameters: [expect.any(String)] },
    });
    const away = fakeFetch(() => problemResponse(503));
    vi.stubGlobal("fetch", away.fetchImpl);
    expect(
      await editSource(SOURCE_KEY, IDLE, settingsForm({ [SETTINGS_FIELDS.cadence]: "3600" })),
    ).toMatchObject({ status: "error", problem: { title: "Test problem 503" } });
    expect(away.requests.map((request) => request.method)).toEqual(["GET"]);
  });
});

describe("fetchSource", () => {
  function form(reason: string): FormData {
    const data = new FormData();
    data.set(FETCH_FIELDS.reason, reason);
    return data;
  }

  it("starts a crawl with the reason and says which run it recorded", async () => {
    await signedInAs(["admin"]);
    const fake = fakeFetch([
      {
        method: "POST",
        path: `${SOURCE}/fetch`,
        status: 202,
        body: { run_id: "r-1", source_key: SOURCE_KEY, trigger: "manual", workflow_id: "w-1" },
      },
    ]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const state = await fetchSource(SOURCE_KEY, IDLE, form(REASON));
    expect(state).toMatchObject({
      status: "ok",
      value: { message: expect.stringContaining("run r-1, workflow w-1") },
    });
    expect(fake.requests[0]?.body).toEqual({ actor_id: ACTOR_ID, reason: REASON });
  });

  it("explains a fetch refused while crawling is off, and the pipeline's other refusals", async () => {
    await signedInAs(["admin"]);
    const answers: [string, number, string][] = [
      ["pipeline-crawl-disabled", 503, "Crawling is off, so nothing was fetched"],
      ["pipeline-crawl-running", 409, "A crawl of this source is running"],
      ["pipeline-source-upload-only", 409, "This source is upload-only"],
      ["pipeline-crawl-unavailable", 503, "Temporal did not answer, so the crawl did not start"],
      ["pipeline-source-not-found", 404, "The pipeline holds no source under this key"],
      ["example-other", 409, "Test problem 409"],
    ];
    for (const [slug, status, title] of answers) {
      vi.stubGlobal(
        "fetch",
        fakeFetch(() => problemResponse(status, { type: `urn:compliancewatch:problem:${slug}` }))
          .fetchImpl,
      );
      const state = await fetchSource(SOURCE_KEY, IDLE, form(REASON));
      expect(state.status === "error" && state.problem?.title, slug).toBe(title);
      if (slug === "pipeline-crawl-disabled" && state.status === "error") {
        expect(state.problem?.detail).toContain("CW_PIPELINE_CRAWL_ENABLED");
        expect(state.problem?.correlationId).toMatch(/^[0-9a-f-]{36}$/);
      }
    }
  });

  it("refuses an analyst, a bad key and a short reason before any request", async () => {
    const fake = fakeFetch([]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    await signedInAs(["reviewer"]);
    expect((await fetchSource(SOURCE_KEY, IDLE, form(REASON))).status).toBe("error");
    await signedInAs(["admin"]);
    expect((await fetchSource("Bad", IDLE, form(REASON))).status).toBe("error");
    expect(await fetchSource(SOURCE_KEY, IDLE, form("short"))).toMatchObject({
      status: "error",
      fieldErrors: { reason: [expect.any(String)] },
    });
    expect(fake.requests).toHaveLength(0);
  });
});
