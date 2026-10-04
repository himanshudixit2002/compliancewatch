import { describe, expect, it } from "vitest";
import { EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import { readGraph } from "./graph-form";

describe("readGraph", () => {
  it("asks for a version before anything is drawn", () => {
    expect(readGraph({})).toEqual({ kind: "empty" });
    expect(readGraph({ depth: "2" })).toEqual({ kind: "empty" });
  });

  it("reads the version, one relation out and every version by default", () => {
    expect(readGraph({ rule_version_id: ` ${EXAMPLE_VERSION_ID.toUpperCase()} ` })).toEqual({
      kind: "ok",
      ruleVersionId: EXAMPLE_VERSION_ID,
      depth: 1,
      publishedOnly: false,
    });
    expect(
      readGraph({ rule_version_id: EXAMPLE_VERSION_ID, depth: "2", scope: "published" }),
    ).toMatchObject({ depth: 2, publishedOnly: true });
    expect(readGraph({ rule_version_id: [EXAMPLE_VERSION_ID], depth: "9" })).toMatchObject({
      depth: 1,
    });
  });

  it("refuses a malformed id, keeping what was typed", () => {
    expect(readGraph({ rule_version_id: "example", depth: "2", scope: "all" })).toEqual({
      kind: "invalid",
      values: { version: "example", depth: "2", scope: "all" },
      errors: { version: "This is not a rule version id (a UUID)." },
    });
  });
});
