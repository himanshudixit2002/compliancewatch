import { describe, expect, it } from "vitest";
import { changeImpactDto } from "@/test/change-fixture";
import {
  OLDER_VERSION_ID,
  REVIEWER_ID,
  REVIEW_ITEM_ID,
  RUN_VERSION_ID,
  dryRunOutDto,
  fanOutRunDto,
  heldDto,
  holdDto,
  resolvedItemDto,
  reviewItemDto,
} from "@/test/engine-admin-fixture";
import { ENTITY_ID, REGISTRATION_ID, decisionDto } from "@/test/obligation-fixture";
import {
  changeImpactFromDto,
  decisionFromDto,
  dryRunReportFromDto,
  dryRunToDto,
  fanOutHoldFromDto,
  fanOutPageFromDto,
  fanOutRunFromDto,
  holdToDto,
  resolveToDto,
  reviewItemFromDto,
  reviewItemPageFromDto,
} from "./mappers";

describe("applicability mappers", () => {
  it("map a decision with each predicate in words", () => {
    const decision = decisionFromDto(decisionDto());
    expect(decision).toMatchObject({
      businessId: REGISTRATION_ID,
      result: "applies",
      confidence: 1,
      needsReview: false,
      trigger: "rule_published",
      asOfFy: "1999-00",
    });
    expect(decision.evaluated).toEqual([
      {
        attribute: "example_kind",
        kind: "structured",
        description: "Example kind is second",
        outcome: "applies",
        confidence: 1,
        reason: "Example kind is second on this node",
        needsReview: false,
      },
    ]);
  });

  it("group an impact's businesses under their client", () => {
    const impact = changeImpactFromDto(
      changeImpactDto([
        { result: "applies" },
        { businessId: "00000000-0000-4000-8000-0000000000a2", result: "unsure" },
      ]),
    );
    expect(impact.clients).toHaveLength(1);
    expect(impact.clients[0]?.entityId).toBe(ENTITY_ID);
    expect(impact.clients[0]?.businesses.map((business) => business.result)).toEqual([
      "applies",
      "unsure",
    ]);
    expect(impact.nextCursor).toBeNull();
    expect(impact.counts).toEqual({ applies: 0, notApplicable: 0, unsure: 0 });
    expect(impact.fanOut).toBeNull();
  });

  it("map the counts and the fan-out of an impact", () => {
    const impact = changeImpactFromDto(
      changeImpactDto([{ result: "applies" }], {
        counts: { applies: 3, not_applicable: 2, unsure: 1 },
        fan_out: {
          status: "completed",
          businesses_total: 6,
          evaluated: 6,
          applies: 3,
          started_at: "2000-01-05T04:30:00Z",
          updated_at: "2000-01-05T04:40:00Z",
          finished_at: "2000-01-05T04:40:00Z",
        },
      }),
    );
    expect(impact.counts).toEqual({ applies: 3, notApplicable: 2, unsure: 1 });
    expect(impact.fanOut).toEqual({
      status: "completed",
      businessesTotal: 6,
      evaluated: 6,
      applies: 3,
      startedAt: "2000-01-05T04:30:00Z",
      updatedAt: "2000-01-05T04:40:00Z",
      finishedAt: "2000-01-05T04:40:00Z",
    });
  });

  it("map a review item with the decision under review, open and resolved", () => {
    const open = reviewItemFromDto(reviewItemDto());
    expect(open).toMatchObject({
      id: REVIEW_ITEM_ID,
      businessId: REGISTRATION_ID,
      reason: "free_text",
      status: "open",
      resolution: null,
      resolvedBy: null,
      resolvedAt: null,
      note: "",
      resolutionDecisionId: null,
    });
    expect(open.decision.result).toBe("unsure");
    expect(open.decision.evaluated.map((predicate) => predicate.kind)).toEqual([
      "structured",
      "free_text",
    ]);
    const page = reviewItemPageFromDto({ items: [resolvedItemDto()], next_cursor: "next-1" });
    expect(page.nextCursor).toBe("next-1");
    expect(page.items[0]).toMatchObject({
      status: "resolved",
      resolution: "applies",
      resolvedBy: REVIEWER_ID,
      note: "Example note on why it applies",
    });
  });

  it("send a resolution with the reviewer the caller names", () => {
    expect(resolveToDto({ resolution: "dismiss", note: "Example note" }, REVIEWER_ID)).toEqual({
      resolution: "dismiss",
      note: "Example note",
      resolved_by: REVIEWER_ID,
    });
  });

  it("map a fan-out run, a page of them and the hold", () => {
    const run = fanOutRunFromDto(
      fanOutRunDto({
        supersedes: [OLDER_VERSION_ID],
        flips_compared: 200,
        flips: 6,
        flip_rate: 0.03,
      }),
    );
    expect(run).toMatchObject({
      ruleVersionId: RUN_VERSION_ID,
      ruleKey: "example_rule",
      status: "running",
      supersedes: [OLDER_VERSION_ID],
      businessesTotal: 2000,
      evaluated: 1000,
      flipsCompared: 200,
      flips: 6,
      flipRate: 0.03,
      finishedAt: null,
      statusBy: "system:applicability-engine",
    });
    const page = fanOutPageFromDto({ items: [fanOutRunDto()], next_cursor: null });
    expect(page.items).toHaveLength(1);
    expect(page.nextCursor).toBeNull();
    expect(fanOutHoldFromDto(holdDto())).toEqual({
      held: false,
      reason: null,
      setBy: null,
      setAt: null,
    });
    expect(fanOutHoldFromDto(heldDto("Example reason given"))).toMatchObject({
      held: true,
      reason: "Example reason given",
    });
    expect(holdToDto(true, "Example reason given")).toEqual({
      held: true,
      reason: "Example reason given",
    });
  });

  it("send a dry run of a version or of a specification, with its scope", () => {
    expect(
      dryRunToDto({
        ruleVersionId: RUN_VERSION_ID,
        specification: null,
        level: null,
        tenantId: null,
        sampleSize: 10,
      }),
    ).toEqual({ rule_version_id: RUN_VERSION_ID, scope: { sample_size: 10 } });
    expect(
      dryRunToDto({
        ruleVersionId: null,
        specification: { attribute: "example_kind", operator: "eq", value: "first" },
        level: "entity",
        tenantId: ENTITY_ID,
        sampleSize: 0,
      }),
    ).toEqual({
      specification: { attribute: "example_kind", operator: "eq", value: "first" },
      scope: { sample_size: 0, level: "entity", tenant_id: ENTITY_ID },
    });
  });

  it("map a dry run's counts, attributes and samples", () => {
    const report = dryRunReportFromDto(dryRunOutDto());
    expect(report).toMatchObject({
      ruleVersionId: RUN_VERSION_ID,
      status: "draft",
      asOfFy: "1999-00",
      evaluated: 3,
      counts: { applies: 1, notApplicable: 1, unsure: 1 },
      needsReview: 1,
      maxBusinesses: 2000,
    });
    expect(report.byAttribute[0]).toEqual({
      attribute: "example_kind",
      applies: 1,
      notApplicable: 1,
      unsure: 0,
    });
    expect(report.samples[0]).toMatchObject({
      businessId: REGISTRATION_ID,
      result: "applies",
      deciding: ["example_kind"],
    });
    expect(report.samples[0]?.evaluated[0]?.attribute).toBe("example_kind");
  });
});
