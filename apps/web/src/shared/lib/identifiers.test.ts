import { describe, expect, it } from "vitest";
import {
  gstinStateCode,
  isE164,
  isEmailAddress,
  isGstin,
  isHexId,
  isPan,
  isUuid,
  maskIdentifier,
  normaliseIdentifier,
  normalisePhone,
  panOfGstin,
} from "./identifiers.ts";

const GSTIN = "27ABCDE1234F1Z5";

describe("identifiers", () => {
  it("checks shapes", () => {
    expect(isUuid("00000000-0000-4000-8000-000000000001")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isPan("ABCDE1234F")).toBe(true);
    expect(isPan("abcde1234f")).toBe(false);
    expect(isGstin(GSTIN)).toBe(true);
    expect(isGstin("27ABCDE1234F1X5")).toBe(false);
    expect(isGstin("ABCDE1234F")).toBe(false);
    expect(isE164("+919876543210")).toBe(true);
    expect(isE164("9876543210")).toBe(false);
    expect(isHexId("0123456789abcdef0123456789abcdef")).toBe(true);
    expect(isHexId("0123")).toBe(false);
    expect(isEmailAddress("owner@example.com")).toBe(true);
    expect(isEmailAddress("owner@example")).toBe(false);
    expect(isEmailAddress("owner @example.com")).toBe(false);
    expect(isEmailAddress(`${"a".repeat(250)}@example.com`)).toBe(false);
  });

  it("normalises pasted values and extracts the parts of a GSTIN", () => {
    expect(normaliseIdentifier(" 27abcde 1234f1z5 ")).toBe(GSTIN);
    expect(gstinStateCode(GSTIN)).toBe("27");
    expect(panOfGstin(GSTIN)).toBe("ABCDE1234F");
    expect(() => gstinStateCode("nope")).toThrow(/not a GSTIN/);
    expect(() => panOfGstin("nope")).toThrow(/not a GSTIN/);
  });

  it("drops what people type between the digits of a phone number", () => {
    expect(normalisePhone(" +91 (98000) 000-01.")).toBe("+919800000001");
  });

  it("masks all but the tail", () => {
    expect(maskIdentifier(GSTIN)).toBe("************1Z5");
    expect(maskIdentifier("+919876543210", 4)).toBe("*********3210");
    expect(maskIdentifier("ab", 3)).toBe("ab");
  });
});
