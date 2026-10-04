import { describe, expect, it } from "vitest";
import {
  ownerLabel,
  roleLabel,
  roleLabels,
  statusLabel,
  statusTone,
  toAwaitedItem,
  toNotAvailableView,
  toScreenRow,
} from "./mappers";
import type { ScreenLike } from "./types";

const waiting: ScreenLike = {
  id: "owner.ask",
  route: "/b/[businessId]/ask",
  title: "Ask",
  section: "owner",
  roles: ["owner", "ca_admin"],
  status: "waiting",
  awaits: [{ method: "POST", path: "/v1/qa/ask", owner: "plan-k" }],
  guideRef: "2 uc3",
};

describe("screen mappers", () => {
  it("labels roles, statuses and owners in words", () => {
    expect(roleLabel("ca_admin")).toBe("CA admin");
    expect(roleLabel("unknown_role")).toBe("unknown_role");
    expect(roleLabels("public")).toEqual(["Public"]);
    expect(roleLabels(["owner", "analyst"])).toEqual(["Owner", "Analyst"]);
    expect(statusLabel("live")).toBe("Available");
    expect(statusLabel("ready")).toBe("Ready to build");
    expect(statusTone("live")).toBe("success");
    expect(statusTone("ready")).toBe("info");
    expect(statusTone("waiting")).toBe("warning");
    expect(statusTone("planned")).toBe("neutral");
    expect(ownerLabel("plan-a", "WP22")).toBe("services track (WP22)");
    expect(ownerLabel("plan-k")).toBe("KAG track");
    expect(ownerLabel("unplanned", "indicative path")).toBe("not scheduled (indicative path)");
  });

  it("turns a waiting entry into the notice props with its awaited routes", () => {
    expect(toNotAvailableView(waiting)).toEqual({
      title: "Ask",
      guideRef: "2 uc3",
      roles: ["Owner", "CA admin"],
      backendReady: false,
      waitingFor: [{ method: "POST", path: "/v1/qa/ask", owner: "KAG track" }],
    });
  });

  it("marks a ready entry and lists its awaited items, then the routes it only uses", () => {
    const view = toNotAvailableView({
      ...waiting,
      status: "ready",
      uses: [
        { service: "qa", method: "POST", path: "/v1/qa/ask" },
        { service: "rulebook", method: "GET", path: "/v1/rulebook/rule-versions" },
      ],
    });
    expect(view.backendReady).toBe(true);
    expect(view.waitingFor).toEqual([
      { method: "POST", path: "/v1/qa/ask", owner: "KAG track" },
      { method: "GET", path: "/v1/rulebook/rule-versions", owner: "rulebook service" },
    ]);
  });

  it("lists only the awaited items of a waiting entry, not its used routes", () => {
    const view = toNotAvailableView({
      ...waiting,
      uses: [{ service: "rulebook", method: "GET", path: "/v1/rulebook/rule-versions" }],
    });
    expect(view.backendReady).toBe(false);
    expect(view.waitingFor).toHaveLength(1);
  });

  it("lists awaited files next to routes and keeps preview and notes", () => {
    const view = toNotAvailableView({
      ...waiting,
      id: "admin.flags",
      awaits: [],
      awaitsFiles: [{ path: "packages/flags/registry.json", owner: "plan-a", ref: "WP12" }],
      preview: "FlagTable",
      notes: "Read-only.",
    });
    expect(view.waitingFor).toEqual([
      { method: "file", path: "packages/flags/registry.json", owner: "services track (WP12)" },
    ]);
    expect(view.preview).toBe("FlagTable");
    expect(view.notes).toBe("Read-only.");
  });

  it("returns null waitingFor when nothing is awaited", () => {
    expect(toNotAvailableView({ ...waiting, awaits: [] }).waitingFor).toBeNull();
  });

  it("builds a sitemap row", () => {
    expect(toScreenRow(waiting)).toEqual({
      id: "owner.ask",
      route: "/b/[businessId]/ask",
      title: "Ask",
      section: "owner",
      roles: ["Owner", "CA admin"],
      status: "waiting",
      statusLabel: "Waiting for a backend",
      guideRef: "2 uc3",
    });
  });
});

describe("toAwaitedItem", () => {
  it("names who delivers a route, and the header a hardened route must require", () => {
    expect(
      toAwaitedItem({ method: "GET", path: "/v1/example", owner: "plan-a", ref: "WP1" }),
    ).toEqual({ method: "GET", path: "/v1/example", owner: "services track (WP1)" });
    expect(
      toAwaitedItem({
        method: "POST",
        path: "/v1/example/{id}/again",
        owner: "plan-a",
        ref: "WP2",
        header: "Idempotency-Key",
      }),
    ).toEqual({
      method: "POST",
      path: "/v1/example/{id}/again",
      owner: "services track (WP2), requiring Idempotency-Key",
    });
  });
});
