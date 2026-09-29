import { describe, expect, it } from "vitest";
import type { AttributeValue } from "@/entities/business/types";
import { attributeOf } from "@/entities/ontology/mappers";
import type { OntologyAttribute } from "@/entities/ontology/types";
import { REGISTRATION_ID } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { describeValue, formDefault, formatValue, parseAnswer, stateLabel } from "./values";

const ontology = ontologyFixture();

function attribute(key: string): OntologyAttribute {
  const found = attributeOf(ontology, key);
  if (found === undefined) throw new Error(`fixture has no ${key}`);
  return found;
}

function stored(partial: Partial<AttributeValue> & Pick<AttributeValue, "key">): AttributeValue {
  return {
    state: "known",
    value: null,
    asOfFy: null,
    source: "user_input",
    updatedAt: null,
    ...partial,
  };
}

describe("formatValue", () => {
  it("words every type with the ontology's labels", () => {
    expect(formatValue(attribute("example_kind"), "second")).toBe("Example second kind");
    expect(formatValue(attribute("example_band"), "large")).toBe("Example large band");
    expect(formatValue(attribute("example_kind"), "unlisted")).toBe("unlisted");
    expect(formatValue(attribute("state_codes"), ["03", "01", "99"])).toBe(
      "Example place one, Example place three, 99",
    );
    expect(formatValue(attribute("state_codes"), [])).toBe("None");
    expect(formatValue(attribute("example_flag"), true)).toBe("Yes");
    expect(formatValue(attribute("example_flag"), false)).toBe("No");
    expect(formatValue(attribute("example_flag"), "maybe")).toBe("maybe");
    expect(formatValue(attribute("example_count"), 123456)).toBe("1,23,456");
    expect(formatValue(attribute("example_count"), "12")).toBe("12");
    expect(formatValue(attribute("example_since"), "2000-01-02")).toBe("2 Jan 2000");
    expect(formatValue(attribute("example_since"), "soon")).toBe("soon");
    expect(formatValue(attribute("example_ratio"), "1.50")).toBe("1.50");
    expect(formatValue(attribute("example_note"), "Example note")).toBe("Example note");
  });

  it("shows nothing for no value, and the raw value for an attribute the ontology lacks", () => {
    expect(formatValue(attribute("example_kind"), null)).toBe("");
    expect(formatValue(undefined, undefined)).toBe("");
    expect(formatValue(undefined, { a: 1 })).toBe('{"a":1}');
    expect(formatValue(undefined, 7)).toBe("7");
  });

  it("describes an unsure or not-applicable value by its state", () => {
    const kind = attribute("example_kind");
    expect(describeValue(kind, stored({ key: "example_kind", value: "first" }))).toBe(
      "Example first kind",
    );
    expect(describeValue(kind, stored({ key: "example_kind", state: "unsure" }))).toBe("Not sure");
    expect(stateLabel("not_applicable")).toBe("Does not apply");
  });
});

describe("formDefault", () => {
  it("starts a control from a known value only", () => {
    expect(formDefault(attribute("example_kind"), stored({ key: "k", value: "first" }))).toBe(
      "first",
    );
    expect(formDefault(attribute("example_flag"), stored({ key: "k", value: false }))).toBe(
      "false",
    );
    expect(formDefault(attribute("state_codes"), stored({ key: "k", value: ["01"] }))).toEqual([
      "01",
    ]);
    expect(formDefault(attribute("state_codes"), stored({ key: "k", value: "01" }))).toEqual([]);
    expect(formDefault(attribute("example_count"), stored({ key: "k", value: 3 }))).toBe("3");
    expect(formDefault(attribute("example_kind"), stored({ key: "k", state: "unsure" }))).toBe(
      undefined,
    );
    expect(formDefault(attribute("example_kind"), undefined)).toBeUndefined();
  });
});

describe("parseAnswer", () => {
  const known = (values: string[]) => ({ state: "known", values });

  it("reads each type's value from the form's strings", () => {
    expect(parseAnswer(attribute("example_kind"), known(["second"]))).toEqual({
      ok: true,
      answer: { key: "example_kind", state: "known", value: "second" },
    });
    expect(parseAnswer(attribute("example_flag"), known(["false"]))).toMatchObject({
      ok: true,
      answer: { value: false },
    });
    expect(parseAnswer(attribute("state_codes"), known(["03", "01", "01"]))).toMatchObject({
      ok: true,
      answer: { value: ["01", "03"] },
    });
    expect(parseAnswer(attribute("example_count"), known([" 1,000 "]))).toMatchObject({
      ok: true,
      answer: { value: 1000 },
    });
    expect(parseAnswer(attribute("example_ratio"), known(["2.25"]))).toMatchObject({
      ok: true,
      answer: { value: "2.25" },
    });
    expect(parseAnswer(attribute("example_since"), known(["2000-02-29"]))).toMatchObject({
      ok: true,
      answer: { value: "2000-02-29" },
    });
    expect(parseAnswer(attribute("example_note"), known([" Example "]))).toMatchObject({
      ok: true,
      answer: { value: "Example" },
    });
  });

  it("names what is wrong with a value", () => {
    const cases: [string, string[], string][] = [
      ["example_kind", ["third"], "Choose one of the options."],
      ["example_kind", [], "Choose one of the options."],
      ["example_flag", ["yes"], "Choose one of the options."],
      ["state_codes", [], "Tick at least one, or answer Not sure or Does not apply."],
      ["state_codes", ["01", "99"], "Tick at least one, or answer Not sure or Does not apply."],
      ["example_count", ["1.5"], "Enter a whole number, such as 12."],
      ["example_count", ["-1"], "Enter 0 or more."],
      ["example_count", ["1001"], "Enter 1,000 or less."],
      ["example_ratio", ["1.2.3"], "Enter a number, such as 1.5."],
      ["example_since", ["2000-02-30"], "Enter a date as day, month and year."],
      ["example_note", ["  "], "Enter an answer."],
    ];
    for (const [key, values, error] of cases) {
      expect(parseAnswer(attribute(key), known(values)), `${key} ${values.join(",")}`).toEqual({
        ok: false,
        error,
      });
    }
  });

  it("stores no value for not sure and does not apply, and refuses an unknown state", () => {
    expect(parseAnswer(attribute("example_kind"), { state: "unsure", values: ["first"] })).toEqual({
      ok: true,
      answer: { key: "example_kind", state: "unsure" },
    });
    expect(parseAnswer(attribute("example_flag"), { state: "not_applicable", values: [] })).toEqual(
      { ok: true, answer: { key: "example_flag", state: "not_applicable" } },
    );
    expect(parseAnswer(attribute("example_kind"), { state: "maybe", values: [] })).toEqual({
      ok: false,
      error: "Choose an answer.",
    });
  });

  it("sends the year only for a per-year attribute, and the node when given", () => {
    const band = attribute("example_band");
    expect(parseAnswer(band, known(["small"]), { asOfFy: "2000-01" })).toEqual({
      ok: true,
      answer: { key: "example_band", state: "known", value: "small", asOfFy: "2000-01" },
    });
    expect(parseAnswer(band, known(["small"]))).toEqual({
      ok: false,
      error: "This answer is stated for a financial year, and none was given.",
    });
    expect(parseAnswer(band, known(["small"]), { asOfFy: "2000-02" }).ok).toBe(false);
    expect(
      parseAnswer(attribute("example_flag"), known(["true"]), {
        asOfFy: "2000-01",
        nodeId: REGISTRATION_ID,
      }),
    ).toEqual({
      ok: true,
      answer: { key: "example_flag", state: "known", value: true, nodeId: REGISTRATION_ID },
    });
  });
});
