import { describe, expect, it } from "vitest";
import { LEGAL_DOCS, LEGAL_DOC_NAMES, isLegalDoc, legalDocTitle } from "./legal-docs.ts";

describe("legal docs", () => {
  it("names the three documents rendered under /legal", () => {
    expect(LEGAL_DOC_NAMES).toEqual(["privacy-notice", "terms-of-service", "whatsapp-consent"]);
    expect(LEGAL_DOCS.every((doc) => /^[a-z-]+$/.test(doc.name))).toBe(true);
  });

  it("recognises a document name and gives its title", () => {
    expect(isLegalDoc("privacy-notice")).toBe(true);
    expect(isLegalDoc("data-map")).toBe(false);
    expect(legalDocTitle("whatsapp-consent")).toBe("WhatsApp consent");
    expect(() => legalDocTitle("nope" as never)).toThrow(/unknown legal document/);
  });
});
