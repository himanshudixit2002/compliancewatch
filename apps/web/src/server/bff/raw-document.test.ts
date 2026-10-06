// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { ACTOR_ID, DOCUMENT_ID, documentDto } from "@/test/pipeline-fixture";
import { storedDocumentFromDto } from "@/entities/pipeline/mappers";
import { resetEnvCache } from "../env";
import {
  RAW_CONTENT_SECURITY_POLICY,
  cleanName,
  contentDisposition,
  forwardBytes,
  rawDocumentResponse,
  servedContentType,
} from "./raw-document";

const RECORD = `/v1/pipeline/documents/${DOCUMENT_ID}`;
const BYTES = `${RECORD}/raw`;
const PDF = "%PDF-1.4\nExample bytes\n%%EOF\n";

function claims(
  roles: SessionClaims["roles"],
  tenantKind: SessionClaims["tenantKind"] = "internal",
): SessionClaims {
  return {
    userId: ACTOR_ID,
    tenantId: "00000000-0000-4000-8000-0000000000ee",
    tenantKind,
    roles,
    displayName: "Example analyst",
    mfa: true,
    sv: 1,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
  };
}

const ANALYST = claims(["analyst"]);

function get(id = DOCUMENT_ID): Request {
  return new Request(`http://localhost:3000/api-bff/pipeline/documents/${id}/raw`);
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("rawDocumentResponse", () => {
  it("streams the stored bytes with the stored type, a safe name, nosniff and no caching", async () => {
    const fake = fakeFetch((request) =>
      request.pathname === RECORD
        ? jsonResponse(200, {
            ...documentDto({ size: PDF.length }),
            retries: [],
            read_as: null,
            classification: null,
            extraction: null,
          })
        : new Response(PDF, { status: 200, headers: { "content-type": "application/pdf" } }),
    );
    const response = await rawDocumentResponse(get(), DOCUMENT_ID, ANALYST, {
      fetchImpl: fake.fetchImpl,
    });
    expect(response.status).toBe(200);
    expect(await response.text()).toBe(PDF);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-length")).toBe(String(PDF.length));
    expect(response.headers.get("content-disposition")).toBe(
      `inline; filename="${DOCUMENT_ID}.pdf"; filename*=UTF-8''Example%20notice%201.pdf`,
    );
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("content-security-policy")).toBeNull();
    expect(fake.requests.map((request) => request.pathname)).toEqual([RECORD, BYTES]);
    for (const request of fake.requests) {
      expect(request.headers["x-tenant-id"]).toBeUndefined();
      expect(request.headers["x-cw-write-token"]).toBeUndefined();
      expect(request.cache).toBe("no-store");
    }
  });

  it("sandboxes an HTML page and serves any other type as a download", () => {
    const html = storedDocumentFromDto(
      documentDto({ content_type: "text/html; charset=utf-8", title: 'Example "page"/one' }),
    );
    expect(servedContentType(html.contentType)).toBe("text/html; charset=utf-8");
    expect(contentDisposition(html)).toBe(
      `inline; filename="${DOCUMENT_ID}.html"; filename*=UTF-8''Example%20page%20one.html`,
    );
    expect(RAW_CONTENT_SECURITY_POLICY).toBe("sandbox; default-src 'none'");
    const other = storedDocumentFromDto(
      documentDto({ content_type: "image/svg+xml", title: "", external_ref: "" }),
    );
    expect(servedContentType(other.contentType)).toBe("application/octet-stream");
    expect(contentDisposition(other)).toBe(`attachment; filename="${DOCUMENT_ID}.bin"`);
    expect(servedContentType('text/html; charset="bad value"')).toBe("text/html");
  });

  it("sets the sandbox on an HTML page it streams", async () => {
    const fake = fakeFetch((request) =>
      request.pathname === RECORD
        ? jsonResponse(200, {
            ...documentDto({ content_type: "text/html", size: 13 }),
            retries: [],
            read_as: null,
            classification: null,
            extraction: null,
          })
        : new Response("<p>Example</p>", { headers: { "content-type": "text/html" } }),
    );
    const response = await rawDocumentResponse(get(), DOCUMENT_ID, ANALYST, {
      fetchImpl: fake.fetchImpl,
    });
    expect(response.headers.get("content-security-policy")).toBe(RAW_CONTENT_SECURITY_POLICY);
  });

  it("sends a visitor without a session to sign in and back, and hides the route from a tenant", async () => {
    const fake = fakeFetch([]);
    const anonymous = await rawDocumentResponse(get(), DOCUMENT_ID, null, {
      fetchImpl: fake.fetchImpl,
    });
    expect(anonymous.status).toBe(303);
    expect(anonymous.headers.get("location")).toBe(
      `/sign-in?next=${encodeURIComponent(`/api-bff/pipeline/documents/${DOCUMENT_ID}/raw`)}`,
    );
    const owner = await rawDocumentResponse(get(), DOCUMENT_ID, claims(["owner"], "business"), {
      fetchImpl: fake.fetchImpl,
    });
    expect(owner.status).toBe(404);
    const malformed = await rawDocumentResponse(get("nope"), "nope", ANALYST, {
      fetchImpl: fake.fetchImpl,
    });
    expect(malformed.status).toBe(404);
    expect(fake.requests).toHaveLength(0);
  });

  it("names a file by a title whose cut falls inside a character outside the BMP", async () => {
    // 99 letters and U+1D400: 101 UTF-16 units, 100 characters. Cut at 100 units, the name kept
    // a lone surrogate and encodeURIComponent threw, after both pipeline calls.
    const title = `${"a".repeat(99)}\u{1D400}`;
    const named = `${"a".repeat(99)}%F0%9D%90%80.pdf`;
    expect(cleanName(title)).toBe(title);
    expect(cleanName(`${"a".repeat(100)}\u{1D400}`)).toBe("a".repeat(100));
    expect(cleanName(`Example\uD835 title\uDC00`)).toBe("Example� title�");
    expect(contentDisposition(storedDocumentFromDto(documentDto({ title })))).toBe(
      `inline; filename="${DOCUMENT_ID}.pdf"; filename*=UTF-8''${named}`,
    );
    const fake = fakeFetch((request) =>
      request.pathname === RECORD
        ? jsonResponse(200, {
            ...documentDto({ title, size: PDF.length }),
            retries: [],
            read_as: null,
            classification: null,
            extraction: null,
          })
        : new Response(PDF, { status: 200, headers: { "content-type": "application/pdf" } }),
    );
    const response = await rawDocumentResponse(get(), DOCUMENT_ID, ANALYST, {
      fetchImpl: fake.fetchImpl,
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toBe(
      `inline; filename="${DOCUMENT_ID}.pdf"; filename*=UTF-8''${named}`,
    );
    expect(await response.text()).toBe(PDF);
  });

  it("cancels the raw store's body when the answer cannot be built around it", async () => {
    const cancelled: unknown[] = [];
    const body = new ReadableStream<Uint8Array>({
      cancel(reason) {
        cancelled.push(reason);
      },
    });
    expect(() => forwardBytes(body, { "content-disposition": "inline\r\nx-example: 1" })).toThrow(
      TypeError,
    );
    await vi.waitFor(() => expect(cancelled).toHaveLength(1));
    expect(cancelled[0]).toBeInstanceOf(TypeError);
    const fine = forwardBytes(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode("Example bytes"));
          controller.close();
        },
      }),
      { "content-type": "application/pdf" },
    );
    expect(await fine.text()).toBe("Example bytes");
  });

  it("says plainly what the pipeline refused", async () => {
    const cases = [
      { on: RECORD, status: 404, title: "No stored document has this id" },
      { on: RECORD, status: 403, title: "The pipeline refused to serve the file" },
      { on: BYTES, status: 502, title: "The stored file cannot be served" },
      { on: BYTES, status: 503, title: "The raw store did not answer" },
      { on: BYTES, status: 500, title: "Test problem 500" },
    ];
    for (const item of cases) {
      const fake = fakeFetch((request) => {
        if (request.pathname === item.on) return problemResponse(item.status);
        return jsonResponse(200, {
          ...documentDto(),
          retries: [],
          read_as: null,
          classification: null,
          extraction: null,
        });
      });
      const response = await rawDocumentResponse(get(), DOCUMENT_ID, ANALYST, {
        fetchImpl: fake.fetchImpl,
      });
      expect(response.status, item.title).toBe(item.status);
      expect(response.headers.get("content-type")).toContain("application/problem+json");
      const problem = (await response.json()) as { title: string; correlation_id?: string };
      expect(problem.title).toBe(item.title);
      expect(problem.correlation_id).toMatch(/^[0-9a-f-]{36}$/);
    }
  });
});
