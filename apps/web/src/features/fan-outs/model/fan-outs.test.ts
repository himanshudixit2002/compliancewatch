import { describe, expect, it } from "vitest";
import { fanOutHoldFromDto, fanOutRunFromDto } from "@/entities/applicability/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { RUN_VERSION_ID, fanOutRunDto, heldDto, holdDto } from "@/test/engine-admin-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import {
  actorText,
  controlsFor,
  fanOutRow,
  fanOutStatusLabel,
  fanOutStatusMeaning,
  fanOutStatusTone,
  flipsText,
  holdView,
  isFinished,
  lastChangeText,
  listHrefs,
  progressText,
  readCursor,
  versionName,
} from "./fan-outs";

const run = (overrides = {}) => fanOutRunFromDto(fanOutRunDto(overrides));
const version = ruleVersionFromDto(
  ruleVersionDto({ rule_version_id: RUN_VERSION_ID, version: 2, title: "Example rule 2" }),
);

describe("fan-out words", () => {
  it("names each status with its tone and what it means", () => {
    expect(fanOutStatusLabel("held")).toBe("Held");
    expect(fanOutStatusTone("held")).toBe("warning");
    expect(fanOutStatusTone("failed")).toBe("danger");
    expect(fanOutStatusTone("completed")).toBe("success");
    expect(fanOutStatusMeaning("paused")).toContain("only when an admin resumes it");
  });

  it("offers the controls each status allows, and none once finished", () => {
    expect(controlsFor("running")).toEqual(["pause", "cancel"]);
    expect(controlsFor("held")).toEqual(["pause", "cancel"]);
    expect(controlsFor("paused")).toEqual(["resume", "cancel"]);
    for (const status of ["completed", "cancelled", "disabled", "failed"] as const) {
      expect(controlsFor(status)).toEqual([]);
      expect(isFinished(status)).toBe(true);
    }
    expect(isFinished("running")).toBe(false);
  });

  it("says how far a run got and how many results flipped", () => {
    expect(progressText(run())).toBe("1,000 of 2,000 decided");
    expect(flipsText(run())).toBe("No business compared with a version it supersedes");
    expect(flipsText(run({ flips: 6, flips_compared: 200, flip_rate: 0.03 }))).toBe(
      "6 of 200 compared flipped (3%)",
    );
  });

  it("names who changed a run: a user by the start of their id, the system or a service", () => {
    expect(actorText("system:applicability-engine")).toBe("the system (applicability-engine)");
    expect(actorText("service:example-client")).toBe("the service example-client");
    expect(actorText("00000000-0000-4000-8000-00000000f0c2")).toBe("user 00000000…");
    expect(actorText("someone else")).toBe("someone else");
    expect(actorText("")).toBeNull();
    expect(actorText(null)).toBeNull();
  });

  it("names the version from the rulebook, or by its rule key", () => {
    expect(versionName(run(), version)).toBe("example_rule v2");
    expect(versionName(run(), null)).toBe("example_rule");
  });

  it("says the last change of status with its reason", () => {
    expect(lastChangeText(run())).toBe("By the system (applicability-engine)");
    expect(
      lastChangeText(
        run({ status_by: "00000000-0000-4000-8000-00000000f0c2", status_reason: "Example reason" }),
      ),
    ).toBe("By user 00000000…: Example reason");
    expect(lastChangeText(run({ status_by: "", status_reason: "Example reason" }))).toBe(
      "Example reason",
    );
    expect(lastChangeText(run({ status_by: "", status_reason: " " }))).toBeNull();
  });

  it("builds a row with the version's name and title, and when it last moved", () => {
    const row = fanOutRow(run(), version, `/admin/fan-outs/${RUN_VERSION_ID}`);
    expect(row).toMatchObject({
      name: "example_rule v2",
      title: "Example rule 2",
      statusLabel: "Running",
      level: "Registrations (GSTIN)",
      progress: "1,000 of 2,000 decided",
      applies: "400",
    });
    expect(row.lastMoved).toMatch(/^Last moved /);
    const finished = fanOutRow(
      run({ status: "completed", finished_at: "2000-01-05T05:00:00Z" }),
      null,
      "/x",
    );
    expect(finished.lastMoved).toMatch(/^Finished /);
    expect(finished.title).toBeNull();
  });

  it("words the hold, set or not", () => {
    expect(holdView(fanOutHoldFromDto(holdDto()))).toEqual({
      held: false,
      reason: null,
      by: null,
      since: null,
    });
    const held = holdView(fanOutHoldFromDto(heldDto("Example reason given")));
    expect(held).toMatchObject({
      held: true,
      reason: "Example reason given",
      by: "the system (applicability-engine)",
    });
    expect(held.since).toContain("2000");
    expect(holdView(fanOutHoldFromDto(heldDto(" "))).reason).toBeNull();
  });

  it("pages by the engine's cursor and reads only a cursor it could have written", () => {
    expect(listHrefs("/admin/fan-outs", null, "abc")).toEqual({
      nextHref: "/admin/fan-outs?cursor=abc",
      firstHref: null,
    });
    expect(listHrefs("/admin/fan-outs", "abc", null)).toEqual({
      nextHref: null,
      firstHref: "/admin/fan-outs",
    });
    expect(readCursor("eyJhIjoxfQ")).toBe("eyJhIjoxfQ");
    expect(readCursor(["eyJhIjoxfQ", "x"])).toBe("eyJhIjoxfQ");
    expect(readCursor("not a cursor!")).toBeNull();
    expect(readCursor("x".repeat(513))).toBeNull();
    expect(readCursor(undefined)).toBeNull();
    expect(readCursor("")).toBeNull();
  });
});
