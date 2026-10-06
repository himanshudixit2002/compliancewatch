// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import {
  ADMIN_USER_ID,
  OLDER_VERSION_ID,
  RUN_VERSION_ID,
  fanOutRunDto,
  heldDto,
  holdDto,
} from "@/test/engine-admin-fixture";
import { fakeFetch, type FakeRoute } from "@/test/fake-fetch";
import { ruleVersionDetailDto } from "@/test/rule-version-fixture";
import { getFanOutList, getFanOutPage } from "./queries";

const INTERNAL = "00000000-0000-4000-8000-0000000000ee";
const admin: ClientPrincipal = {
  userId: ADMIN_USER_ID,
  tenantId: INTERNAL,
  tenantKind: "internal",
  roles: ["admin"],
};
const reviewer: ClientPrincipal = { ...admin, roles: ["reviewer"] };

const LIST = "/v1/applicability-engine/fan-outs";
const RUN = `${LIST}/${RUN_VERSION_ID}`;
const HOLD = "/v1/applicability-engine/fan-out-hold";
const VERSION = `/v1/rulebook/rule-versions/${RUN_VERSION_ID}`;

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getFanOutList", () => {
  it("lists the runs named by their versions, the hold, and what the session may do", async () => {
    const fake = fakeFetch([
      { path: HOLD, body: heldDto() },
      {
        path: LIST,
        body: {
          items: [
            fanOutRunDto(),
            fanOutRunDto({ rule_version_id: OLDER_VERSION_ID, status: "completed" }),
          ],
          next_cursor: "next-1",
        },
      },
      {
        path: VERSION,
        body: ruleVersionDetailDto({ rule_version_id: RUN_VERSION_ID, version: 3 }),
      },
      { path: `/v1/rulebook/rule-versions/${OLDER_VERSION_ID}`, status: 503, problem: {} },
    ]);
    const list = await getFanOutList(admin, "after-1", { fetchImpl: fake.fetchImpl });
    if (!list.ok) throw new Error(list.error.message);
    expect(list.value.hold).toMatchObject({ ok: true, hold: { held: true } });
    expect(list.value.rows.map((row) => [row.name, row.status, row.href])).toEqual([
      ["example_rule v3", "running", `/admin/fan-outs/${RUN_VERSION_ID}`],
      ["example_rule", "completed", `/admin/fan-outs/${OLDER_VERSION_ID}`],
    ]);
    expect(list.value.canControl).toBe(true);
    expect(list.value.nextHref).toBe("/admin/fan-outs?cursor=next-1");
    expect(list.value.firstHref).toBe("/admin/fan-outs");
    const reviewed = await getFanOutList(reviewer, null, { fetchImpl: fake.fetchImpl });
    expect(reviewed.ok && reviewed.value.canControl).toBe(false);
    expect(reviewed.ok && reviewed.value.firstHref).toBeNull();
  });

  it("shows the runs when the hold could not be read, and fails when the runs could not", async () => {
    const holdDown = fakeFetch([
      { path: HOLD, status: 503, problem: { title: "Example engine down" } },
      { path: LIST, body: { items: [], next_cursor: null } },
    ]);
    const list = await getFanOutList(admin, null, { fetchImpl: holdDown.fetchImpl });
    expect(list.ok && list.value.hold).toMatchObject({
      ok: false,
      failure: { message: "Example engine down" },
    });
    const listDown = fakeFetch([
      { path: HOLD, body: holdDto() },
      { path: LIST, status: 503, problem: {} },
    ]);
    const failed = await getFanOutList(admin, null, { fetchImpl: listDown.fetchImpl });
    expect(!failed.ok && failed.error.kind).toBe("unavailable");
  });
});

function pageRoutes(overrides: { run?: FakeRoute; version?: FakeRoute } = {}): FakeRoute[] {
  return [
    overrides.run ?? { path: RUN, body: fanOutRunDto() },
    overrides.version ?? {
      path: VERSION,
      body: ruleVersionDetailDto({ rule_version_id: RUN_VERSION_ID, status: "published" }),
    },
    { path: HOLD, body: holdDto() },
  ];
}

describe("getFanOutPage", () => {
  it("gives an admin the controls of the run's status and the rollback of a published version", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_PUBLISH_ACTIONS", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch(pageRoutes());
    const page = await getFanOutPage(admin, RUN_VERSION_ID, { fetchImpl: fake.fetchImpl });
    if (!page.ok) throw new Error(page.error.message);
    expect(page.value.run?.status).toBe("running");
    expect(page.value.version?.status).toBe("published");
    expect(page.value.controls).toEqual(["pause", "cancel"]);
    expect(page.value.canControl).toBe(true);
    expect(page.value.rollback).toEqual({ state: "offered", access: { allowed: true } });
  });

  it("says why the rollback is not offered: the flag off, not published, not an admin", async () => {
    const offFlag = await getFanOutPage(admin, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(pageRoutes()).fetchImpl,
    });
    expect(offFlag.ok && offFlag.value.rollback).toMatchObject({
      state: "offered",
      access: { allowed: false, title: expect.stringContaining("web.publish_actions") },
    });
    const draft = await getFanOutPage(admin, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(
        pageRoutes({
          version: {
            path: VERSION,
            body: ruleVersionDetailDto({ rule_version_id: RUN_VERSION_ID, status: "draft" }),
          },
        }),
      ).fetchImpl,
    });
    expect(draft.ok && draft.value.rollback).toEqual({
      state: "not_published",
      statusLabel: "Draft",
    });
    const read = await getFanOutPage(reviewer, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(pageRoutes()).fetchImpl,
    });
    expect(read.ok && read.value.rollback).toEqual({ state: "not_admin" });
    expect(read.ok && read.value.canControl).toBe(false);
  });

  it("shows a version the engine has no run of, and is not found when neither knows the id", async () => {
    const noRun = await getFanOutPage(admin, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(pageRoutes({ run: { path: RUN, status: 404, problem: {} } })).fetchImpl,
    });
    expect(noRun.ok && noRun.value.run).toBeNull();
    expect(noRun.ok && noRun.value.controls).toEqual([]);
    const unknown = await getFanOutPage(admin, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(
        pageRoutes({
          run: { path: RUN, status: 404, problem: {} },
          version: { path: VERSION, status: 404, problem: {} },
        }),
      ).fetchImpl,
    });
    expect(!unknown.ok && unknown.error.kind).toBe("not_found");
  });

  it("keeps the run when the rulebook fails, and fails when the engine does", async () => {
    const rulebookDown = await getFanOutPage(admin, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(
        pageRoutes({ version: { path: VERSION, status: 503, problem: { title: "Example down" } } }),
      ).fetchImpl,
    });
    if (!rulebookDown.ok) throw new Error(rulebookDown.error.message);
    expect(rulebookDown.value.version).toBeNull();
    expect(rulebookDown.value.versionFailure?.message).toBe("Example down");
    expect(rulebookDown.value.rollback).toEqual({ state: "unknown_version" });
    const engineDown = await getFanOutPage(admin, RUN_VERSION_ID, {
      fetchImpl: fakeFetch(pageRoutes({ run: { path: RUN, status: 500, problem: {} } })).fetchImpl,
    });
    expect(!engineDown.ok && engineDown.error.kind).toBe("server");
  });
});
