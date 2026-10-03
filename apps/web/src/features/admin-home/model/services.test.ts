import { describe, expect, it } from "vitest";
import { SYSTEM_ROUTE, servicesSummary } from "./services";

describe("servicesSummary", () => {
  it("counts the services that answer and lists the others with their address and reason", () => {
    const summary = servicesSummary(
      [
        { service: "identity", baseUrl: "http://localhost:8001", state: "up" },
        { service: "eval", baseUrl: "http://localhost:8009", state: "down", reason: "HTTP 503" },
        { service: "qa", baseUrl: "http://localhost:8007", state: "down" },
      ],
      (route) => (route === SYSTEM_ROUTE ? "/admin/system" : null),
    );
    expect(summary).toEqual({
      up: 1,
      total: 3,
      down: [
        { service: "eval", baseUrl: "http://localhost:8009", reason: "HTTP 503" },
        { service: "qa", baseUrl: "http://localhost:8007", reason: "unreachable" },
      ],
      systemHref: "/admin/system",
    });
  });
});
