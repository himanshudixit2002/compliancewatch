// @vitest-environment node
import { describe, expect, it } from "vitest";
import { isSameOriginRequest, requestHost } from "./origin";

const DIRECT = { trustForwardedHost: false };
const PROXIED = { trustForwardedHost: true };

function headers(entries: Record<string, string>): Headers {
  return new Headers(entries);
}

describe("requestHost", () => {
  it("reads Host, lower-cased, and X-Forwarded-Host's first hop only when trusted", () => {
    const sent = headers({ host: "App.Example.com", "x-forwarded-host": "edge.example, inner" });
    expect(requestHost(sent, DIRECT)).toBe("app.example.com");
    expect(requestHost(sent, PROXIED)).toBe("edge.example");
    expect(requestHost(headers({ host: "127.0.0.1:3291" }), PROXIED)).toBe("127.0.0.1:3291");
    expect(requestHost(headers({}), DIRECT)).toBeNull();
  });
});

describe("isSameOriginRequest", () => {
  it("lets Sec-Fetch-Site decide when the browser sends it", () => {
    expect(isSameOriginRequest(headers({ "sec-fetch-site": "same-origin" }), DIRECT)).toBe(true);
    for (const site of ["cross-site", "same-site", "none"]) {
      const sent = headers({
        "sec-fetch-site": site,
        origin: "http://app.example.com",
        host: "app.example.com",
      });
      expect(isSameOriginRequest(sent, DIRECT), site).toBe(false);
    }
  });

  it("compares Origin's host with the host the browser asked for, whatever the scheme", () => {
    const own = { origin: "http://app.example.com", host: "app.example.com" };
    expect(isSameOriginRequest(headers(own), DIRECT)).toBe(true);
    const loopback = { origin: "http://127.0.0.1:3291", host: "127.0.0.1:3291" };
    expect(isSameOriginRequest(headers(loopback), DIRECT)).toBe(true);
    const tls = { origin: "https://app.example.com", host: "app.example.com" };
    expect(isSameOriginRequest(headers(tls), DIRECT)).toBe(true);
    const foreign = { origin: "https://evil.example", host: "app.example.com" };
    expect(isSameOriginRequest(headers(foreign), DIRECT)).toBe(false);
    const otherPort = { origin: "http://app.example.com:8080", host: "app.example.com" };
    expect(isSameOriginRequest(headers(otherPort), DIRECT)).toBe(false);
  });

  it("uses X-Forwarded-Host only behind a trusted proxy", () => {
    const proxied = {
      origin: "https://app.example.com",
      host: "10.0.0.5:3000",
      "x-forwarded-host": "app.example.com",
    };
    expect(isSameOriginRequest(headers(proxied), PROXIED)).toBe(true);
    expect(isSameOriginRequest(headers(proxied), DIRECT)).toBe(false);
    const spoofed = { origin: "https://evil.example", host: "app.example.com" };
    expect(
      isSameOriginRequest(headers({ ...spoofed, "x-forwarded-host": "evil.example" }), DIRECT),
    ).toBe(false);
  });

  it("refuses an opaque or missing host and passes a request with neither header", () => {
    expect(isSameOriginRequest(headers({ origin: "null", host: "app.example.com" }), DIRECT)).toBe(
      false,
    );
    expect(isSameOriginRequest(headers({ origin: "http://app.example.com" }), DIRECT)).toBe(false);
    expect(isSameOriginRequest(headers({ host: "app.example.com" }), DIRECT)).toBe(true);
  });
});
