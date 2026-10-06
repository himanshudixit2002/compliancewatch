// @vitest-environment node
import {
  BasicTracerProvider,
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { SpanKind, SpanStatusCode } from "@opentelemetry/api";
import { describe, expect, it } from "vitest";
import {
  RedactingSpanProcessor,
  personalPlaceholder,
  redactPath,
  redactText,
  redactUrl,
  redactValue,
} from "./telemetry-redaction";

/**
 * Synthetic values in the repo's test patterns (the example.com domain, the 98000 0000x numbers,
 * the ABCDE1234F PAN and its GSTIN), shaped like the real thing and never anyone's.
 */
const PHONE = "+919800000001";
const EMAIL = "owner@example.com";
const PAN = "ABCDE1234F";
const GSTIN = "29ABCDE1234F1Z5";

const NOTIFICATION = "http://localhost:9206";
const PREFERENCE_PHONE = `${NOTIFICATION}/v1/notification/preferences/whatsapp/${encodeURIComponent(PHONE)}`;
const PREFERENCE_EMAIL = `${NOTIFICATION}/v1/notification/preferences/email/${encodeURIComponent(EMAIL)}`;
const SEARCH = `http://localhost:9202/v1/businesses?q=${PAN}&limit=26`;

describe("redactUrl", () => {
  it("replaces the recipient of a notification preference, a number or an email", () => {
    expect(redactUrl(PREFERENCE_PHONE)).toBe(
      `${NOTIFICATION}/v1/notification/preferences/whatsapp/{recipient}`,
    );
    expect(redactUrl(PREFERENCE_EMAIL)).toBe(
      `${NOTIFICATION}/v1/notification/preferences/email/{recipient}`,
    );
    expect(redactUrl("/v1/notification/preferences/whatsapp/example-recipient")).toBe(
      "/v1/notification/preferences/whatsapp/{recipient}",
    );
    expect(redactUrl(`/proxy/v1/notification/preferences/email/${EMAIL}/history`)).toBe(
      "/proxy/v1/notification/preferences/email/{recipient}/history",
    );
  });

  it("drops the query, the fragment and a user and password before the host", () => {
    expect(redactUrl(SEARCH)).toBe("http://localhost:9202/v1/businesses");
    expect(redactUrl(`/businesses?q=${GSTIN}`)).toBe("/businesses");
    expect(redactUrl(`/v1/identity/consents?subject=${EMAIL}#top`)).toBe("/v1/identity/consents");
    expect(redactUrl("http://example-user:example-secret@localhost:9201/health")).toBe(
      "http://localhost:9201/health",
    );
  });

  it("replaces any other segment that is an email, a phone number, a PAN or a GSTIN", () => {
    expect(redactPath(`/v1/example/${encodeURIComponent(EMAIL)}/items`)).toBe(
      "/v1/example/{email}/items",
    );
    expect(redactPath(`/v1/example/${encodeURIComponent("+91 98000 00001")}`)).toBe(
      "/v1/example/{phone}",
    );
    expect(redactPath("/v1/example/9800000001")).toBe("/v1/example/{phone}");
    expect(redactPath(`/v1/example/${PAN}`)).toBe("/v1/example/{pan}");
    expect(redactPath(`/v1/example/${GSTIN.toLowerCase()}/returns`)).toBe(
      "/v1/example/{gstin}/returns",
    );
  });

  it("keeps ids, route templates, dates and versions readable", () => {
    for (const path of [
      "/v1/rulebook/rule-versions/00000000-0000-4000-8000-000000000001",
      "/v1/rulebook/review/relations/12345678-1234-1234-1234-123456789012/approve",
      "/admin/rulebook/relations/[candidateId]",
      "/v1/rulebook/rules/example.rule.1/versions",
      "/b/00000000-0000-4000-8000-000000000002/obligations/2000-01-31",
      "/v1/notification/preferences/whatsapp",
      "/",
    ]) {
      expect(redactUrl(path)).toBe(path);
    }
  });
});

describe("redactText", () => {
  it("redacts every URL and path in a span name and keeps the words", () => {
    expect(redactText(`fetch GET ${PREFERENCE_PHONE}`)).toBe(
      `fetch GET ${NOTIFICATION}/v1/notification/preferences/whatsapp/{recipient}`,
    );
    expect(redactText(`fetch GET ${SEARCH}`)).toBe("fetch GET http://localhost:9202/v1/businesses");
    expect(redactText(`GET /businesses?q=${PAN}`)).toBe("GET /businesses");
    expect(redactText("RSC GET /b/[businessId]/obligations")).toBe(
      "RSC GET /b/[businessId]/obligations",
    );
    expect(redactText(`Failed to parse URL from "${SEARCH}"`)).toBe(
      'Failed to parse URL from "http://localhost:9202/v1/businesses"',
    );
    expect(redactText("2000/01 and/or 1/2")).toBe("2000/01 and/or 1/2");
  });

  it("finds a person's value inside a text, but never inside an id", () => {
    expect(redactText(`No preference for ${EMAIL}: ${PHONE}`)).toBe(
      "No preference for {email}: {phone}",
    );
    expect(redactText(`q=${PAN}&gstin=${GSTIN}`)).toBe("q={pan}&gstin={gstin}");
    const ids = "request 12345678-1234-1234-1234-123456789012, chunk abcde1234f.js, at 2000-01-31";
    expect(redactText(ids)).toBe(ids);
  });

  it("replaces a whole value that names a person", () => {
    expect(redactText(EMAIL)).toBe("{email}");
    expect(redactText("+91 98000 00001")).toBe("{phone}");
    expect(redactText(GSTIN)).toBe("{gstin}");
    expect(redactText("GET")).toBe("GET");
    expect(personalPlaceholder("2000-01-31")).toBeNull();
    expect(personalPlaceholder("12345")).toBeNull();
  });

  it("redacts the strings of an array and leaves other values as they are", () => {
    expect(redactValue([`/businesses?q=${PAN}`, "/b"])).toEqual(["/businesses", "/b"]);
    const unchanged = ["/b", "/c"];
    expect(redactValue(unchanged)).toBe(unchanged);
    expect(redactValue(200)).toBe(200);
    expect(redactValue(true)).toBe(true);
    expect(redactValue(undefined)).toBeUndefined();
  });
});

function tracer() {
  const exporter = new InMemorySpanExporter();
  const provider = new BasicTracerProvider({
    spanProcessors: [new RedactingSpanProcessor(), new SimpleSpanProcessor(exporter)],
  });
  return { exporter, tracer: provider.getTracer("example") };
}

describe("RedactingSpanProcessor", () => {
  it("redacts a fetch span the way @vercel/otel starts one", () => {
    const { exporter, tracer: example } = tracer();
    const span = example.startSpan(`fetch GET ${PREFERENCE_PHONE}`, {
      kind: SpanKind.CLIENT,
      attributes: {
        "http.method": "GET",
        "http.url": PREFERENCE_PHONE,
        "http.host": "localhost:9206",
        "net.peer.name": "localhost",
        "operation.name": "fetch.GET",
        "resource.name": PREFERENCE_PHONE,
      },
    });
    expect(span.isRecording()).toBe(true);
    expect((span as unknown as { name: string }).name).not.toContain(encodeURIComponent(PHONE));
    span.setAttribute("http.status_code", 200);
    span.end();
    const [exported] = exporter.getFinishedSpans();
    const redactedUrl = `${NOTIFICATION}/v1/notification/preferences/whatsapp/{recipient}`;
    expect(exported?.name).toBe(`fetch GET ${redactedUrl}`);
    expect(exported?.attributes).toEqual({
      "http.method": "GET",
      "http.url": redactedUrl,
      "http.host": "localhost:9206",
      "net.peer.name": "localhost",
      "operation.name": "fetch.GET",
      "resource.name": redactedUrl,
      "http.status_code": 200,
    });
    expect(JSON.stringify(exported?.attributes)).not.toContain("9800000001");
  });

  it("redacts what is set after the start: the name, attributes, events and the status", () => {
    const { exporter, tracer: example } = tracer();
    const span = example.startSpan("GET", { kind: SpanKind.SERVER });
    span.setAttribute("http.target", `/businesses?q=${GSTIN}`);
    span.setAttribute("url.full", `${PREFERENCE_EMAIL}?channel=email`);
    span.setAttribute("url.query", `q=${PAN}`);
    span.setAttribute("enduser.id", EMAIL);
    span.updateName(`GET /businesses?q=${GSTIN}`);
    span.addEvent("example", { "exception.message": `fetch failed for ${SEARCH}` });
    span.setStatus({ code: SpanStatusCode.ERROR, message: `Example failure at ${SEARCH}` });
    span.end();
    const [exported] = exporter.getFinishedSpans();
    expect(exported?.name).toBe("GET /businesses");
    expect(exported?.attributes).toEqual({
      "http.target": "/businesses",
      "url.full": `${NOTIFICATION}/v1/notification/preferences/email/{recipient}`,
      "url.query": "",
      "enduser.id": "{email}",
    });
    expect(exported?.events[0]?.attributes).toEqual({
      "exception.message": "fetch failed for http://localhost:9202/v1/businesses",
    });
    expect(exported?.status.message).toBe("Example failure at http://localhost:9202/v1/businesses");
    const text = JSON.stringify({
      name: exported?.name,
      attributes: exported?.attributes,
      events: exported?.events,
      status: exported?.status,
    });
    for (const value of [PAN, GSTIN, EMAIL, "owner%40example.com", "9800000001"]) {
      expect(text).not.toContain(value);
    }
  });

  it("leaves a span without a URL or a person's value as it was", () => {
    const { exporter, tracer: example } = tracer();
    const span = example.startSpan("resolve page components", {
      attributes: { "next.route": "/admin/system", "next.span_type": "Example.span" },
    });
    span.end();
    const [exported] = exporter.getFinishedSpans();
    expect(exported?.name).toBe("resolve page components");
    expect(exported?.attributes).toEqual({
      "next.route": "/admin/system",
      "next.span_type": "Example.span",
    });
  });

  it("flushes and shuts down at once, holding nothing", async () => {
    const processor = new RedactingSpanProcessor();
    await expect(processor.forceFlush()).resolves.toBeUndefined();
    await expect(processor.shutdown()).resolves.toBeUndefined();
  });
});
