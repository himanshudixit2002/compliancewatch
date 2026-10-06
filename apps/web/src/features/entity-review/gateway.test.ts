// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { REVIEW_TOKEN_HEADER } from "@/server/api/rulebook-write";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { mentionGroupDto, reviewItemDto } from "@/test/rulebook-fixture";
import { entityReviewGateway } from "./gateway";

afterEach(() => {
  resetEnvCache();
});

describe("EntityReviewGateway", () => {
  it("reads a page of open groups with the type and the cursor, fresh and without a tenant", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/review/entities", body: [mentionGroupDto()] }]);
    const groups = await entityReviewGateway({ fetchImpl: fake.fetchImpl }).groups({
      entityType: "form",
      after: { entityType: "form", name: "" },
      limit: 26,
    });
    expect(groups.ok && groups.value[0]?.proposedName).toBe("EXAMPLE-1");
    const request = fake.requests[0];
    expect(request?.method).toBe("GET");
    expect(request?.url).toBe(
      "http://localhost:8003/v1/rulebook/review/entities?limit=26&entity_type=form&after_type=form&after_name=",
    );
    expect(request?.cache).toBe("no-store");
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.headers[REVIEW_TOKEN_HEADER]).toBeUndefined();
  });

  it("reads every type from the first page without a filter", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/review/entities", body: [] }]);
    await entityReviewGateway({ fetchImpl: fake.fetchImpl }).groups({
      entityType: null,
      after: null,
      limit: 26,
    });
    expect(fake.requests[0]?.url).toBe(
      "http://localhost:8003/v1/rulebook/review/entities?limit=26",
    );
  });

  it("reads one group's mentions with its name encoded, a slash and an empty name included", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/entities/items", body: [reviewItemDto()] },
    ]);
    const gateway = entityReviewGateway({ fetchImpl: fake.fetchImpl });
    const items = await gateway.items("notification", "01/2000-example tax");
    expect(items.ok && items.value[0]?.mentionText).toBe("Example clause");
    expect(fake.requests[0]?.url).toBe(
      "http://localhost:8003/v1/rulebook/review/entities/items?entity_type=notification&proposed_name=01%2F2000-example%20tax",
    );
    await gateway.items("form", "");
    expect(fake.requests[1]?.url).toBe(
      "http://localhost:8003/v1/rulebook/review/entities/items?entity_type=form&proposed_name=",
    );
  });

  it("passes the rulebook's problem on", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/entities", status: 422, problem: { title: "Example refusal" } },
    ]);
    const groups = await entityReviewGateway({ fetchImpl: fake.fetchImpl }).groups({
      entityType: null,
      after: null,
      limit: 26,
    });
    expect(groups.ok).toBe(false);
    expect(!groups.ok && groups.error.kind).toBe("validation");
  });
});
