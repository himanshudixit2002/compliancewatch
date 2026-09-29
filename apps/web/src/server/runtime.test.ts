import { describe, expect, it } from "vitest";
import { WEB_ENVS, isLocalOrTest, isWebEnvName, webEnvName } from "./runtime";

describe("webEnvName", () => {
  it("defaults to local when CW_WEB_ENV is unset or empty", () => {
    expect(webEnvName({})).toBe("local");
    expect(webEnvName({ CW_WEB_ENV: "" })).toBe("local");
  });

  it("accepts the four known names and treats anything else as prod", () => {
    for (const name of WEB_ENVS) expect(webEnvName({ CW_WEB_ENV: name })).toBe(name);
    expect(webEnvName({ CW_WEB_ENV: "production" })).toBe("prod");
    expect(isWebEnvName("staging")).toBe(true);
    expect(isWebEnvName("dev")).toBe(false);
  });

  it("opens local-only pages in local and test only", () => {
    expect(isLocalOrTest({})).toBe(true);
    expect(isLocalOrTest({ CW_WEB_ENV: "test" })).toBe(true);
    expect(isLocalOrTest({ CW_WEB_ENV: "staging" })).toBe(false);
    expect(isLocalOrTest({ CW_WEB_ENV: "typo" })).toBe(false);
  });
});
