import { describe, expect, it } from "vitest";
import { changeImpactFromDto } from "@/entities/applicability/mappers";
import { businessFromDto } from "@/entities/business/mappers";
import type { Business } from "@/entities/business/types";
import { bulkResultFromDto } from "@/entities/notification/mappers";
import { BUSINESS_DTO, DEMO_GSTIN, DEMO_PAN } from "@/test/business-fixture";
import { changeImpactDto } from "@/test/change-fixture";
import { bulkOutDto } from "@/test/engine-admin-fixture";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import {
  bulkSummary,
  clientRows,
  countsView,
  fanOutLine,
  filterLabel,
  impactHref,
  nodeLabel,
  outcomeLabel,
  readImpactQuery,
} from "./impact";

const business: Business = businessFromDto(BUSINESS_DTO);
const OTHER_CLIENT = "00000000-0000-4000-8000-0000000000e9";

describe("a CA firm's affected clients in words", () => {
  it("reads the filter (affected unless another result) and a cursor the engine could write", () => {
    expect(readImpactQuery({})).toEqual({ result: "applies", cursor: null });
    expect(readImpactQuery({ result: "unsure", cursor: "abc" })).toEqual({
      result: "unsure",
      cursor: "abc",
    });
    expect(readImpactQuery({ result: ["all"], cursor: "bad cursor" })).toEqual({
      result: "all",
      cursor: null,
    });
    expect(readImpactQuery({ result: "maybe" }).result).toBe("applies");
    expect(impactHref("/changes/x/impact", "applies")).toBe("/changes/x/impact");
    expect(impactHref("/changes/x/impact", "all", "next-1")).toBe(
      "/changes/x/impact?result=all&cursor=next-1",
    );
    expect(filterLabel("not_applicable")).toBe("Not affected");
  });

  it("names each client and its businesses from the profile service, or by id", () => {
    const impact = changeImpactFromDto(
      changeImpactDto([
        { result: "applies" },
        { businessId: ENTITY_ID, result: "unsure" },
        { entityId: OTHER_CLIENT, businessId: OTHER_CLIENT, result: "not_applicable" },
      ]),
    );
    const rows = clientRows(impact, new Map([[ENTITY_ID, business]]));
    expect(rows.map((row) => row.name)).toEqual([`Example business (${DEMO_PAN})`, OTHER_CLIENT]);
    expect(rows[0]?.businesses.map((row) => [row.label, row.result, row.needsReview])).toEqual([
      [`GSTIN ${DEMO_GSTIN}, Example registration`, "applies", false],
      [`The client itself (PAN ${DEMO_PAN})`, "unsure", true],
    ]);
    expect(rows[1]?.businesses[0]?.label).toBe(OTHER_CLIENT);
    expect(nodeLabel(business, "00000000-0000-4000-8000-0000000000ff")).toBe(
      "00000000-0000-4000-8000-0000000000ff",
    );
    expect(rows[0]?.businesses[0]?.confidence).toBe("100%");
  });

  it("counts every business with a decision and says how far the fan-out got", () => {
    expect(countsView({ applies: 1200, notApplicable: 3, unsure: 1 })).toEqual({
      applies: "1,200",
      unsure: "1",
      notApplicable: "3",
      total: "1,204",
    });
    expect(fanOutLine(null)).toMatch(/^The engine has no fan-out of this version/);
    expect(
      fanOutLine({
        status: "completed",
        businessesTotal: 6,
        evaluated: 6,
        applies: 3,
        startedAt: "2000-01-05T04:30:00Z",
        updatedAt: "2000-01-05T04:40:00Z",
        finishedAt: "2000-01-05T04:40:00Z",
      }),
    ).toBe("Its fan-out over every business of its level is complete: 6 of 6 decided.");
  });

  it("says what a bulk change card did, fresh or replayed", () => {
    const result = bulkResultFromDto(
      bulkOutDto({
        skipped_no_recipient: 1,
        businesses: [
          ...bulkOutDto().businesses,
          {
            business_id: ENTITY_ID,
            outcome: "no_recipient",
            obligation_id: null,
            queued: 0,
            duplicates: 0,
            unreachable: 2,
          },
          {
            business_id: OTHER_CLIENT,
            outcome: "duplicate",
            obligation_id: null,
            queued: 0,
            duplicates: 1,
            unreachable: 0,
          },
        ],
      }),
    );
    const fresh = bulkSummary(result, false);
    expect(fresh.message).toBe(
      "Sent. Businesses named: 3. Queued: 1, in 2 cards. Already told: 0. Nobody to tell: 1. Not affected: 0.",
    );
    expect(
      fresh.businesses.map((entry) => [entry.businessId, entry.outcomeLabel, entry.people]),
    ).toEqual([
      [REGISTRATION_ID, "Queued", "2 told now"],
      [ENTITY_ID, "Nobody to tell", "2 with no open address"],
      [OTHER_CLIENT, "Already told", "1 had it already"],
    ]);
    expect(bulkSummary(result, true).message).toMatch(/^This request had already been sent/);
    expect(outcomeLabel("not_affected")).toBe("Not affected");
    const nobody = bulkSummary(
      bulkResultFromDto(
        bulkOutDto({
          businesses: [
            {
              business_id: REGISTRATION_ID,
              outcome: "no_recipient",
              obligation_id: null,
              queued: 0,
              duplicates: 0,
              unreachable: 0,
            },
            {
              business_id: ENTITY_ID,
              outcome: "not_affected",
              obligation_id: null,
              queued: 0,
              duplicates: 0,
              unreachable: 0,
            },
          ],
        }),
      ),
      false,
    );
    expect(nobody.businesses.map((entry) => entry.people)).toEqual([
      "No client person follows it",
      "No open obligation of the change",
    ]);
  });
});
