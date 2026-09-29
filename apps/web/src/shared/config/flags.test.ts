import { describe, expect, it } from "vitest";
import { FLAGS, FLAG_NAMES, envVarFor, isFlagName } from "./flags.ts";

describe("flags", () => {
  it("declares every flag off by default with an owner and a removal condition", () => {
    for (const flag of FLAGS) {
      expect(flag.default, flag.name).toBe(false);
      expect(flag.owner.length, flag.name).toBeGreaterThan(0);
      expect(flag.removal.trim().length, flag.name).toBeGreaterThan(10);
      expect(flag.description.trim().length, flag.name).toBeGreaterThan(10);
      expect(flag.name, flag.name).toMatch(/^web\.[a-z_]+$/);
    }
    expect(new Set(FLAG_NAMES).size).toBe(FLAGS.length);
  });

  it("maps a flag name to its local override variable", () => {
    expect(envVarFor("web.qa_enabled")).toBe("CW_WEB_FLAG_QA_ENABLED");
    expect(envVarFor("web.tenant_header_off")).toBe("CW_WEB_FLAG_TENANT_HEADER_OFF");
    expect(isFlagName("web.qa_enabled")).toBe(true);
    expect(isFlagName("qa_enabled")).toBe(false);
  });
});
