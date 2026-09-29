import { describe, expect, it } from "vitest";
import { profileNodeFromDto, reviewTaskFromDto } from "@/entities/business/mappers";
import { REGISTRATION_DTO, REGISTRATION_ID, REVIEW_TASK_DTO } from "@/test/business-fixture";
import { reviewReasonLabel, reviewTaskRows } from "./review-tasks";

const open = reviewTaskFromDto(REVIEW_TASK_DTO);

describe("reviewTaskRows", () => {
  it("words the reason and names the node, open tasks first and newest first", () => {
    const closed = { ...open, id: "t-closed", open: false, createdAt: "2000-02-01T00:00:00Z" };
    const newer = {
      ...open,
      id: "t-newer",
      reason: "verify_registration",
      attributeKey: "registration",
      createdAt: "2000-01-05T00:00:00Z",
    };
    const rows = reviewTaskRows([closed, open, newer], [profileNodeFromDto(REGISTRATION_DTO)]);
    expect(rows.map((row) => row.id)).toEqual(["t-newer", open.id, "t-closed"]);
    expect(rows[1]).toMatchObject({
      attributeLabel: "Example flag",
      reasonLabel: "You said this does not apply; an analyst will confirm",
      openedAt: "3 Jan 2000, 5:30 am IST",
      statusLabel: "Open",
      nodeName: "Example registration",
    });
    expect(rows[0]?.reasonLabel).toBe("GSTIN details not verified by a lookup provider");
    expect(rows[2]?.statusLabel).toBe("Closed");
  });

  it("falls back to the node id and a humanised reason", () => {
    const [row] = reviewTaskRows([{ ...open, reason: "new_reason" }]);
    expect(row?.nodeName).toBe(REGISTRATION_ID);
    expect(row?.reasonLabel).toBe("New reason");
    expect(reviewReasonLabel("confirm_financial_year")).toBe(
      "Confirm this value for the new financial year",
    );
  });
});
