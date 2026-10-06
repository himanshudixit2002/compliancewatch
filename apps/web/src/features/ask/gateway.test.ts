// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { answerDto } from "@/test/answer-fixture";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { DOCUMENT_ID, TENANT_ID, USER_ID } from "@/test/obligation-fixture";
import { documentDto } from "@/test/rulebook-fixture";
import { askGateway } from "./gateway";

const session: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(() => {
  resetEnvCache();
});

describe("AskGateway", () => {
  it("asks the public API for the tenant, with the question and the node in the body", async () => {
    const fake = fakeFetch([{ method: "POST", path: "/v1/qa", body: answerDto() }]);
    const answer = await askGateway({ session, fetchImpl: fake.fetchImpl }).ask({
      text: " Example question? ",
      nodeId: REGISTRATION_ID,
    });
    expect(answer.ok && answer.value.layer).toBe("structured");
    const [request] = fake.requests;
    expect(request?.url).toBe("http://localhost:8007/v1/qa");
    expect(request?.headers[TENANT_HEADER]).toBe(TENANT_ID);
    expect(request?.body).toEqual({
      question: "Example question?",
      business_node_id: REGISTRATION_ID,
    });
  });

  it("reads a cited document under its tag and the business", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/rulebook/documents/${DOCUMENT_ID}`,
        body: documentDto({ document_id: DOCUMENT_ID }),
      },
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
    ]);
    const gateway = askGateway({ session, fetchImpl: fake.fetchImpl });
    const document = await gateway.document(DOCUMENT_ID);
    expect(document.ok && document.value.title).toBe("Example document title");
    expect(fake.requests[0]?.next?.tags).toEqual([`rulebook:document:${DOCUMENT_ID}`]);
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
    expect((await gateway.business(ENTITY_ID)).ok).toBe(true);
  });
});
