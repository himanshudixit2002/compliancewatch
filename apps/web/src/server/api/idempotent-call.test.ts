// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { IDEMPOTENCY_KEY_FIELD as SHARED_FIELD } from "@/shared/lib/idempotency";
import { fakeFetch, refusingFetch } from "@/test/fake-fetch";
import { resetEnvCache } from "../env";
import {
  IDEMPOTENCY_KEY_FIELD,
  IDEMPOTENCY_KEY_HEADER,
  REPLAYED_HEADER,
  callIdempotent,
} from "./idempotency";
import { obligationClient, type ClientPrincipal } from "./services";

const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";
const OBLIGATION = "00000000-0000-4000-8000-000000000001";
const PATH = `/v1/obligation/obligations/${OBLIGATION}/comments`;
const session: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-0000000000a1",
  tenantId: "00000000-0000-4000-8000-0000000000b1",
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(() => {
  resetEnvCache();
});

function post(fetchImpl: ReturnType<typeof fakeFetch>["fetchImpl"]) {
  return obligationClient({ session, fetchImpl }).POST(
    "/v1/obligation/obligations/{obligation_id}/comments",
    {
      params: {
        path: { obligation_id: OBLIGATION },
        header: { "Idempotency-Key": FORM_UUID },
      },
      body: { body: "Example comment" },
    },
  );
}

describe("callIdempotent", () => {
  it("says whether the service replayed its first answer", async () => {
    const first = fakeFetch([{ path: PATH, status: 201, body: { comment_id: "c1" } }]);
    const fresh = await callIdempotent(post(first.fetchImpl));
    expect(fresh.ok && fresh.value).toEqual({ value: { comment_id: "c1" }, replayed: false });
    expect(first.requests[0]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBe(FORM_UUID);

    const again = fakeFetch([
      {
        path: PATH,
        status: 201,
        body: { comment_id: "c1" },
        headers: { [REPLAYED_HEADER]: "true" },
      },
    ]);
    const replayed = await callIdempotent(post(again.fetchImpl));
    expect(replayed.ok && replayed.value).toEqual({ value: { comment_id: "c1" }, replayed: true });
  });

  it("passes a problem or a refused connection on as call() maps it", async () => {
    const conflict = fakeFetch([{ path: PATH, status: 409, problem: { title: "Example closed" } }]);
    const refused = await callIdempotent(post(conflict.fetchImpl));
    expect(refused.ok ? null : refused.error.kind).toBe("conflict");
    const down = await callIdempotent(post(refusingFetch().fetchImpl));
    expect(down.ok ? null : down.error.kind).toBe("network");
  });

  it("names the hidden field where a client form can reach it", () => {
    expect(IDEMPOTENCY_KEY_FIELD).toBe(SHARED_FIELD);
  });
});
