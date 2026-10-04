import { describe, expect, it } from "vitest";
import { languageName, languageOptions } from "./languages";

describe("languageName", () => {
  it("names a language, and keeps an unknown or invalid code as written", () => {
    expect(languageName("hi")).toBe("Hindi");
    expect(languageName("en")).toBe("English");
    expect(languageName("zz")).toBe("zz");
    expect(languageName("not a code")).toBe("not a code");
  });
});

describe("languageOptions", () => {
  it("lists each code once, English first, then by name", () => {
    expect(languageOptions(["ta", "hi", "en", "hi"])).toEqual([
      { value: "en", label: "English" },
      { value: "hi", label: "Hindi" },
      { value: "ta", label: "Tamil" },
    ]);
    expect(languageOptions(["hi", "en"])[0]?.value).toBe("en");
    expect(languageOptions([])).toEqual([]);
  });
});
