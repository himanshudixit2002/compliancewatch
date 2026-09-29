import { describe, expect, it } from "vitest";
import {
  ownerLabel,
  roleLabel,
  roleLabels,
  statusLabel,
  statusTone,
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
    expect(statusTone("live")).toBe("success");
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
      waitingFor: [{ method: "POST", path: "/v1/qa/ask", owner: "KAG track" }],
    });
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
