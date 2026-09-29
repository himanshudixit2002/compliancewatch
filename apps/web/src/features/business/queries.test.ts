// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import {
  BUSINESS_DTO,
  ENTITY_ID,
  ONBOARDING_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  TENANT_ID,
  USER_ID,
} from "@/test/business-fixture";
import { fakeFetch, type FakeRoute } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { getDoneSummary, getQuestionStep, loadOnboardingState } from "./queries";

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
