import { describe, expect, it } from "vitest";
import { reviewItemFromDto } from "@/entities/applicability/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { REVIEWER_ID, resolvedItemDto, reviewItemDto } from "@/test/engine-admin-fixture";
import { DECISION_ID, RULE_VERSION_ID } from "@/test/obligation-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import { percent, resolutionLabel, reviewItemView } from "./items";

const version = ruleVersionFromDto(
  ruleVersionDto({ rule_version_id: RULE_VERSION_ID, version: 4, title: "Example rule 4" }),
);
const HREF = `/admin/rulebook/versions/${RULE_VERSION_ID}`;

describe("a review item in words", () => {
  it("names the version, why it needs a person and every condition of the decision", () => {
    const view = reviewItemView(reviewItemFromDto(reviewItemDto()), {
      version,
      versionHref: HREF,
      viewerId: REVIEWER_ID,
    });
    expect(view).toMatchObject({
      versionName: "example_rule v4",
      versionTitle: "Example rule 4",
      versionHref: HREF,
      reason: "A condition in words nobody has judged",
      status: "open",
      statusLabel: "Open",
      statusTone: "warning",
      resolution: null,
    });
    expect(view.decision).toMatchObject({
      result: "unsure",
      needsReview: true,
      confidence: "50%",
      trigger: "Rule published",
      profileVersion: 3,
      year: "1999-00",
    });
    expect(view.predicates.map((row) => [row.attribute, row.kind, row.outcome])).toEqual([
      ["example_kind", "a stated condition", "applies"],
      ["example_question", "a condition in words", "unsure"],
    ]);
  });

  it("says who settled a resolved item and how, or that a later decision did", () => {
    const mine = reviewItemView(reviewItemFromDto(resolvedItemDto()), {
      version: null,
      versionHref: HREF,
      viewerId: REVIEWER_ID,
    });
    expect(mine.versionName).toBe(RULE_VERSION_ID);
    expect(mine.resolution).toMatchObject({
      label: "It applies",
      by: "you",
      note: "Example note on why it applies",
      decisionId: DECISION_ID,
    });
    const theirs = reviewItemView(
      reviewItemFromDto(resolvedItemDto({ resolution: "dismiss", resolution_decision_id: null })),
      { version, versionHref: HREF, viewerId: "someone-else" },
    );
    expect(theirs.resolution).toMatchObject({
      label: "Dismissed, with no decision",
      by: "user 00000000…",
    });
    const later = reviewItemView(
      reviewItemFromDto(
        resolvedItemDto({ resolution: null, resolved_by: null, resolved_at: null, note: "" }),
      ),
      { version, versionHref: HREF, viewerId: REVIEWER_ID },
    );
    expect(later.resolution).toEqual({
      label: "A later decision needed no review",
      by: "the engine",
      at: null,
      note: "",
      decisionId: DECISION_ID,
    });
  });

  it("words the resolutions and a confidence", () => {
    expect(resolutionLabel("not_applicable")).toBe("It does not apply");
    expect(percent(0.456)).toBe("46%");
  });
});
