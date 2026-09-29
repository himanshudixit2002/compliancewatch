import { describe, expect, it } from "vitest";
import { humanise, isKnownSpelling, titleCase } from "./humanise.ts";

describe("humanise", () => {
  it("turns snake and kebab case into a sentence", () => {
    expect(humanise("not_started")).toBe("Not started");
    expect(humanise("due-soon")).toBe("Due soon");
    expect(humanise("  waiting_for__review ")).toBe("Waiting for review");
    expect(humanise("")).toBe("");
  });

  it("keeps the regulatory spellings upper-case wherever they appear", () => {
    expect(humanise("ca_admin")).toBe("CA admin");
    expect(humanise("gstin_registered")).toBe("GSTIN registered");
    expect(humanise("opted_into_qrmp")).toBe("Opted into QRMP");
    expect(humanise("tds_deductor")).toBe("TDS deductor");
    expect(humanise("whatsapp_reminders")).toBe("WhatsApp reminders");
    expect(humanise("SEZ_UNIT")).toBe("SEZ unit");
    expect(isKnownSpelling("HSN")).toBe(true);
    expect(isKnownSpelling("monthly")).toBe(false);
  });

  it("title-cases labels without touching the spellings", () => {
    expect(titleCase("ca_admin")).toBe("CA Admin");
    expect(titleCase("review_task")).toBe("Review Task");
  });
});
