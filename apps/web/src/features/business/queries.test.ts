// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import {
  BUSINESS_DTO,
  ENTITY_ID,
  LOCATION_DTO,
  LOCATION_ID,
  ONBOARDING_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
  TENANT_ID,
  USER_ID,
} from "@/test/business-fixture";
import { fakeFetch, type FakeRoute } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import {
  getAttributesPage,
  getBusinessHome,
  getDirectoryPage,
  getDoneSummary,
  getProfilePage,
  getQuestionStep,
  getReviewTasksPage,
  getSnapshotPage,
  loadOnboardingState,
} from "./queries";

const owner: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};

const ROUTES: readonly FakeRoute[] = [
  { method: "GET", path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
  { method: "GET", path: `/v1/businesses/${ENTITY_ID}/onboarding`, body: ONBOARDING_DTO },
  { method: "GET", path: "/v1/ontology", body: ONTOLOGY_DTO },
  { method: "GET", path: `/v1/profile/nodes/${ENTITY_ID}/review-tasks`, body: [] },
  {
    method: "GET",
    path: `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`,
    body: [REVIEW_TASK_DTO],
  },
];

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("loadOnboardingState", () => {
  it("reads the business, its checklist, the ontology and the tasks on every node", async () => {
    const fake = fakeFetch(ROUTES);
    const result = await loadOnboardingState(owner, ENTITY_ID, { fetchImpl: fake.fetchImpl });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.business.id).toBe(ENTITY_ID);
    expect(result.value.onboarding.total).toBe(8);
    expect(result.value.ontology.attributes.length).toBeGreaterThan(0);
    expect(result.value.tasks.map((task) => task.id)).toEqual([REVIEW_TASK_DTO.id]);
    const tenantHeaders = fake.requests
      .filter((request) => request.pathname !== "/v1/ontology")
      .map((request) => request.headers["x-tenant-id"]);
    expect(new Set(tenantHeaders)).toEqual(new Set([TENANT_ID]));
  });

  it("returns the first failure: the business, the checklist, the ontology or a task list", async () => {
    const without = (path: string, status = 404) =>
      fakeFetch([
        { method: "GET", path, status, problem: { title: `Example ${status}` } },
        ...ROUTES.filter((route) => route.path !== path),
      ]);
    for (const path of [
      `/v1/businesses/${ENTITY_ID}`,
      `/v1/businesses/${ENTITY_ID}/onboarding`,
      "/v1/ontology",
      `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`,
    ]) {
      const result = await loadOnboardingState(owner, ENTITY_ID, {
        fetchImpl: without(path, 503).fetchImpl,
      });
      expect(result.ok, path).toBe(false);
      if (!result.ok) expect(result.error.kind, path).toBe("unavailable");
    }
    const missing = await loadOnboardingState(owner, ENTITY_ID, {
      fetchImpl: without(`/v1/businesses/${ENTITY_ID}`).fetchImpl,
    });
    expect(!missing.ok && missing.error.kind).toBe("not_found");
  });
});

describe("the step queries", () => {
  it("build the question step and the summary from the same reads", async () => {
    const step = await getQuestionStep(owner, ENTITY_ID, new Set(), "example_flag", {
      fetchImpl: fakeFetch(ROUTES).fetchImpl,
    });
    expect(step.ok && step.value.question?.key).toBe("example_flag");
    expect(step.ok && step.value.saved?.reviewTaskOpened).toBe(true);
    const summary = await getDoneSummary(owner, ENTITY_ID, {
      fetchImpl: fakeFetch(ROUTES).fetchImpl,
    });
    expect(summary.ok && summary.value.counts.unsure).toBe(1);
  });
});

const NOW = new Date("2026-09-29T06:00:00Z");
const PAGE_ROUTES: readonly FakeRoute[] = [
  ...ROUTES,
  { method: "GET", path: `/v1/profile/nodes/${LOCATION_ID}`, body: LOCATION_DTO },
  { method: "GET", path: /\/v1\/profile\/nodes\/[^/]+\/snapshot$/, body: SNAPSHOT_DTO },
];

describe("getDirectoryPage", () => {
  it("reads a page of the tenant's businesses with the term and the cursor", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/v1/businesses",
        body: {
          items: [
            {
              id: ENTITY_ID,
              name: "Example business",
              pan: "ABCDE1234F",
              gstins: [],
              updated_at: "2000-01-04T00:00:00Z",
            },
          ],
          next_cursor: null,
        },
      },
    ]);
    const page = await getDirectoryPage(
      owner,
      { q: "example", cursor: "c1", page: 2 },
      { fetchImpl: fake.fetchImpl },
    );
    const url = new URL(fake.requests[0]?.url ?? "");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      q: "example",
      limit: "20",
      cursor: "c1",
    });
    expect(page.ok && page.value.rows[0]?.href).toBe(`/b/${ENTITY_ID}`);
    expect(page.ok && page.value.page).toBe(2);
    await getDirectoryPage(owner, { q: "", page: 1 }, { fetchImpl: fake.fetchImpl });
    expect(new URL(fake.requests[1]?.url ?? "").searchParams.has("cursor")).toBe(false);
  });
});

describe("the business page queries", () => {
  it("read the home: business, checklist and open tasks", async () => {
    const home = await getBusinessHome(owner, ENTITY_ID, {
      fetchImpl: fakeFetch(ROUTES).fetchImpl,
    });
    expect(home.ok && home.value.openTasks).toBe(1);
    const missing = await getBusinessHome(owner, ENTITY_ID, {
      fetchImpl: fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404 }]).fetchImpl,
    });
    expect(!missing.ok && missing.error.kind).toBe("not_found");
    const noChecklist = await getBusinessHome(owner, ENTITY_ID, {
      fetchImpl: fakeFetch([
        { method: "GET", path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
        { path: `/v1/businesses/${ENTITY_ID}/onboarding`, status: 503 },
      ]).fetchImpl,
    });
    expect(!noChecklist.ok && noChecklist.error.kind).toBe("unavailable");
  });

  it("read the profile and the review tasks", async () => {
    const profile = await getProfilePage(owner, ENTITY_ID, {
      fetchImpl: fakeFetch(ROUTES).fetchImpl,
    });
    expect(profile.ok && profile.value.registrations).toHaveLength(1);
    const tasks = await getReviewTasksPage(owner, ENTITY_ID, {
      fetchImpl: fakeFetch(ROUTES).fetchImpl,
    });
    expect(tasks.ok && tasks.value.openCount).toBe(1);
    const failed = await getReviewTasksPage(owner, ENTITY_ID, {
      fetchImpl: fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 503 }]).fetchImpl,
    });
    expect(failed.ok).toBe(false);
  });

  it("read a node's attributes, with the edit link for its node and year", async () => {
    const page = await getAttributesPage(
      owner,
      ENTITY_ID,
      { node: REGISTRATION_ID, fy: "2000-01", edit: "example_kind", canEdit: true },
      { fetchImpl: fakeFetch(PAGE_ROUTES).fetchImpl, now: NOW },
    );
    expect(page.ok).toBe(true);
    if (!page.ok) return;
    expect(page.value.editing?.key).toBe("example_kind");
    expect(page.value.own[0]?.editHref).toBe(
      `/b/${ENTITY_ID}/attributes?node=${REGISTRATION_ID}&fy=2000-01&edit=example_kind`,
    );
    const entity = await getAttributesPage(
      owner,
      ENTITY_ID,
      { canEdit: false },
      { fetchImpl: fakeFetch(PAGE_ROUTES).fetchImpl, now: NOW },
    );
    expect(entity.ok && entity.value.fy).toBe("2026-27");
  });

  it("read a location's attributes through its node, and refuse a node of another business", async () => {
    const location = await getAttributesPage(
      owner,
      ENTITY_ID,
      { node: LOCATION_ID, canEdit: true },
      { fetchImpl: fakeFetch(PAGE_ROUTES).fetchImpl },
    );
    expect(location.ok && location.value.node.id).toBe(LOCATION_ID);
    const foreign = await getAttributesPage(
      owner,
      ENTITY_ID,
      { node: LOCATION_ID, canEdit: true },
      {
        fetchImpl: fakeFetch([
          {
            method: "GET",
            path: `/v1/profile/nodes/${LOCATION_ID}`,
            body: { ...LOCATION_DTO, parent_id: USER_ID },
          },
          ...PAGE_ROUTES,
        ]).fetchImpl,
      },
    );
    expect(!foreign.ok && foreign.error.problem?.type).toBe(
      "urn:compliancewatch:problem:web-node-not-in-business",
    );
    const gone = await getAttributesPage(
      owner,
      ENTITY_ID,
      { node: LOCATION_ID, canEdit: true },
      {
        fetchImpl: fakeFetch([
          { path: `/v1/profile/nodes/${LOCATION_ID}`, status: 404 },
          ...PAGE_ROUTES,
        ]).fetchImpl,
      },
    );
    expect(!gone.ok && gone.error.kind).toBe("not_found");
    const down = await getAttributesPage(
      owner,
      ENTITY_ID,
      { node: LOCATION_ID, canEdit: true },
      {
        fetchImpl: fakeFetch([
          { path: `/v1/profile/nodes/${LOCATION_ID}`, status: 503 },
          ...PAGE_ROUTES,
        ]).fetchImpl,
      },
    );
    expect(!down.ok && down.error.kind).toBe("unavailable");
  });

  it("pass on a failed read of the business or the ontology", async () => {
    const noBusiness = await getAttributesPage(
      owner,
      ENTITY_ID,
      { canEdit: true },
      { fetchImpl: fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404 }]).fetchImpl },
    );
    expect(!noBusiness.ok && noBusiness.error.kind).toBe("not_found");
    const noOntology = await getSnapshotPage(
      owner,
      ENTITY_ID,
      {},
      {
        fetchImpl: fakeFetch([{ path: "/v1/ontology", status: 503 }, ...PAGE_ROUTES]).fetchImpl,
      },
    );
    expect(!noOntology.ok && noOntology.error.kind).toBe("unavailable");
    const noAttrOntology = await getAttributesPage(
      owner,
      ENTITY_ID,
      { canEdit: true },
      {
        fetchImpl: fakeFetch([{ path: "/v1/ontology", status: 503 }, ...PAGE_ROUTES]).fetchImpl,
      },
    );
    expect(noAttrOntology.ok).toBe(false);
  });

  it("read the snapshot for the node and year", async () => {
    const fake = fakeFetch(PAGE_ROUTES);
    const page = await getSnapshotPage(
      owner,
      ENTITY_ID,
      { node: REGISTRATION_ID, fy: "2000-01" },
      { fetchImpl: fake.fetchImpl, now: NOW },
    );
    expect(page.ok && page.value.rows.length).toBe(3);
    const snapshot = fake.requests.find((request) => request.pathname.endsWith("/snapshot"));
    expect(snapshot?.url).toContain(`/v1/profile/nodes/${REGISTRATION_ID}/snapshot?fy=2000-01`);
    const failed = await getSnapshotPage(
      owner,
      ENTITY_ID,
      {},
      {
        fetchImpl: fakeFetch([
          { path: /\/snapshot$/, status: 422, problem: { title: "Example invalid" } },
          ...ROUTES,
        ]).fetchImpl,
      },
    );
    expect(!failed.ok && failed.error.kind).toBe("validation");
    const noBusiness = await getSnapshotPage(
      owner,
      ENTITY_ID,
      {},
      { fetchImpl: fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404 }]).fetchImpl },
    );
    expect(noBusiness.ok).toBe(false);
  });
});
