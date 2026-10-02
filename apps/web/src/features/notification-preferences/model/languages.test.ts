import { describe, expect, it } from "vitest";
import { templateFromDto } from "@/entities/notification/mappers";
import { TEMPLATE_DTOS, templateDto } from "@/test/notification-fixture";
import { languageName, languagesFor } from "./languages";

const TEMPLATES = TEMPLATE_DTOS.map(templateFromDto);

describe("languagesFor", () => {
  it("offers the languages a channel has templates in, English first, by the platform's names", () => {
    expect(languagesFor("whatsapp", TEMPLATES)).toEqual([
      { value: "en", label: "English" },
      { value: "hi", label: "Hindi" },
    ]);
    expect(languagesFor("email", TEMPLATES)).toEqual([{ value: "en", label: "English" }]);
  });

  it("keeps the current language and falls back to English without templates", () => {
    expect(languagesFor("email", TEMPLATES, "hi").map((option) => option.value)).toEqual([
      "en",
      "hi",
    ]);
    expect(languagesFor("email", [])).toEqual([{ value: "en", label: "English" }]);
    const others = [templateDto("whatsapp", "ta"), templateDto("whatsapp", "mr")].map(
      templateFromDto,
    );
    expect(languagesFor("whatsapp", others).map((option) => option.label)).toEqual([
      "Marathi",
      "Tamil",
    ]);
  });

  it("shows an unknown code as it is", () => {
    expect(languageName("zz")).toBe("zz");
    expect(languageName("not a code")).toBe("not a code");
  });
});
