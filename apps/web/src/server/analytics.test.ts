// @vitest-environment node
import { trace, type Span } from "@opentelemetry/api";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { OWNER_ID, VERSIONS, grantedState, summaryDto } from "@/test/consent-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import {
  analyticsNoticeVersion,
  eventLine,
  spanAttributes,
  track,
  type AnalyticsPrincipal,
  type ProductEvent,
} from "./analytics";
import { resetEnvCache } from "./env";
import { resetFlagReader } from "./flags";
import { readLegalVersions } from "./legal";

const TENANT = "00000000-0000-4000-8000-00000000000a";
const owner: AnalyticsPrincipal = {
  userId: OWNER_ID,
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};
const EVENT: ProductEvent = {
  name: "onboarding_step_completed",
  properties: { step: "question", attribute: "example_attribute", state: "unsure" },
};
const NOW = new Date("2000-01-01T00:00:00Z");
const CURRENT = "privacy-notice@9.9-draft";

function consentsAnswer(states = [grantedState("analytics", CURRENT)]) {
  return fakeFetch([{ method: "GET", path: "/v1/identity/consents", body: summaryDto(states) }]);
}

function sinks() {
  return { write: vi.fn<(line: string) => void>(), warn: vi.fn<(line: string) => void>() };
}

beforeEach(() => {
  vi.stubEnv("CW_WEB_ENV", "test");
});

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  resetEnvCache();
  await resetFlagReader();
});

describe("track with the flag off", () => {
  it("emits nothing and reads nothing", async () => {
    const fake = consentsAnswer();
    const { write, warn } = sinks();
    const outcome = await track(owner, EVENT, {
      fetchImpl: fake.fetchImpl,
      versions: VERSIONS,
      write,
      warn,
    });
    expect(outcome).toBe("flag_off");
    expect(fake.requests).toHaveLength(0);
    expect(write).not.toHaveBeenCalled();
  });
});

describe("track with the flag on", () => {
  beforeEach(() => {
    vi.stubEnv("CW_WEB_FLAG_ANALYTICS_ENABLED", "true");
  });

  it("emits one JSON line and a span event when the analytics consent is current", async () => {
    const fake = consentsAnswer();
    const { write, warn } = sinks();
    const addEvent = vi.fn();
    vi.spyOn(trace, "getActiveSpan").mockReturnValue({ addEvent } as unknown as Span);

    const outcome = await track(owner, EVENT, {
      fetchImpl: fake.fetchImpl,
      versions: VERSIONS,
      write,
      warn,
      now: () => NOW,
    });

    expect(outcome).toBe("sent");
    const [request] = fake.requests;
    expect(request?.pathname).toBe("/v1/identity/consents");
    expect(new URL(request?.url ?? "").searchParams.get("subject")).toBe(OWNER_ID);
    expect(request?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(request?.cache).toBe("no-store");
    expect(JSON.parse(String(write.mock.calls[0]?.[0]))).toEqual({
      level: "info",
      event: "product_event",
      name: "onboarding_step_completed",
      at: "2000-01-01T00:00:00.000Z",
      tenant_id: TENANT,
      user_id: OWNER_ID,
      properties: { step: "question", attribute: "example_attribute", state: "unsure" },
    });
    expect(addEvent).toHaveBeenCalledWith(
      "product.onboarding_step_completed",
      {
        "product.tenant_id": TENANT,
        "product.step": "question",
        "product.attribute": "example_attribute",
        "product.state": "unsure",
      },
      NOW,
    );
    expect(warn).not.toHaveBeenCalled();
  });

  it("emits nothing without a current grant: none, withdrawn, or for an older notice", async () => {
    for (const states of [
      [],
      [grantedState("analytics", CURRENT, false)],
      [grantedState("analytics", "privacy-notice@9.8")],
      [grantedState("terms", "terms-of-service@9.9")],
    ]) {
      const { write, warn } = sinks();
      const outcome = await track(owner, EVENT, {
        fetchImpl: consentsAnswer(states).fetchImpl,
        versions: VERSIONS,
        write,
        warn,
      });
      expect(outcome).toBe("no_consent");
      expect(write).not.toHaveBeenCalled();
    }
  });

  it("emits nothing when the consents cannot be read", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/identity/consents", status: 503, problem: {} },
    ]);
    const { write, warn } = sinks();
    expect(
      await track(owner, EVENT, { fetchImpl: fake.fetchImpl, versions: VERSIONS, write, warn }),
    ).toBe("no_consent");
    expect(write).not.toHaveBeenCalled();
  });

  it("drops the event and logs a warning when emitting fails", async () => {
    const { warn } = sinks();
    const write = vi.fn(() => {
      throw new Error("stdout closed");
    });
    const outcome = await track(owner, EVENT, {
      fetchImpl: consentsAnswer().fetchImpl,
      versions: VERSIONS,
      write,
      warn,
    });
    expect(outcome).toBe("failed");
    expect(JSON.parse(String(warn.mock.calls[0]?.[0]))).toEqual({
      level: "warn",
      event: "product_event_failed",
      name: "onboarding_step_completed",
      error: "stdout closed",
    });
  });

  it("writes to stdout by default and reads the documents' versions from docs/legal", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const current = analyticsNoticeVersion(readLegalVersions());
    const stale = consentsAnswer([grantedState("analytics", "privacy-notice@0.0-example")]);
    expect(await track(owner, EVENT, { fetchImpl: stale.fetchImpl })).toBe("no_consent");
    const granted = consentsAnswer([grantedState("analytics", current)]);
    expect(await track(owner, EVENT, { fetchImpl: granted.fetchImpl })).toBe("sent");
    expect(log).toHaveBeenCalledTimes(1);
  });
});

describe("the event's shapes", () => {
  it("names the privacy notice at its current version", () => {
    expect(analyticsNoticeVersion(VERSIONS)).toBe(CURRENT);
  });

  it("builds the line and the span attributes from the event alone", () => {
    const event: ProductEvent = {
      name: "notification_preference_saved",
      properties: { channel: "whatsapp", opted_in: false },
    };
    expect(spanAttributes(event, owner)).toEqual({
      "product.tenant_id": TENANT,
      "product.channel": "whatsapp",
      "product.opted_in": false,
    });
    expect(JSON.parse(eventLine(event, owner, NOW))).toMatchObject({
      name: "notification_preference_saved",
      properties: { channel: "whatsapp", opted_in: false },
    });
  });
});
