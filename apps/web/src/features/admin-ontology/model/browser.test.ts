import { describe, expect, it } from "vitest";
import { attributeOf } from "@/entities/ontology/mappers";
import type { OntologyAttribute } from "@/entities/ontology/types";
import { ontologyFixture } from "@/test/ontology-fixture";
import { exampleText, ontologyBrowserView, rangeText, usageNote } from "./browser";

const ONTOLOGY = ontologyFixture();

function attribute(key: string): OntologyAttribute {
  const found = attributeOf(ONTOLOGY, key);
  if (found === undefined) throw new Error(`no ${key} in the fixture`);
  return found;
}

describe("ontologyBrowserView", () => {
  it("groups the attributes by level, entity first, in the ontology's order", () => {
    const view = ontologyBrowserView(ONTOLOGY);
    expect(view.sections.map((section) => section.level)).toEqual([
      "entity",
      "registration",
      "location",
    ]);
    expect(view.sections.map((section) => section.label)).toEqual([
      "Legal entity (PAN)",
      "Registration (GSTIN)",
      "Location",
    ]);
    expect(view.sections[0]?.attributes.map((row) => row.key)).toEqual([
      "state_codes",
      "example_band",
      "example_count",
      "example_derived",
    ]);
    expect(view.total).toBe(ONTOLOGY.attributes.length);
    expect(view).toMatchObject({
      version: "0.0.1",
      wordingVersion: "0.0.1",
      language: "en",
      reviewStatus: "needs_review",
      wordingReviewed: false,
      unsupported: [],
    });
  });

  it("words each attribute with the service's text and the kernel's kinds", () => {
    const view = ontologyBrowserView(ONTOLOGY);
    const kind = view.sections[1]?.attributes.find((row) => row.key === "example_kind");
    expect(kind).toEqual({
      key: "example_kind",
      typeLabel: "One of a list",
      sourceLabel: "Pre-filled from the GSTIN lookup",
      perFinancialYear: false,
      definition: "Example definition of example_kind.",
      question: "Example question about example_kind?",
      help: "Example help line.",
      options: [
        { value: "first", label: "Example first kind" },
        { value: "second", label: "Example second kind" },
      ],
      range: null,
      example: "Example first kind",
      operators: ["eq", "neq", "in", "not_in"],
    });
    const derived = view.sections[0]?.attributes.find((row) => row.key === "example_derived");
    expect(derived).toMatchObject({ question: "", sourceLabel: "Worked out by the service" });
    const band = view.sections[0]?.attributes.find((row) => row.key === "example_band");
    expect(band).toMatchObject({ perFinancialYear: true, typeLabel: "One of an ordered list" });
    const note = view.sections[2]?.attributes.find((row) => row.key === "example_note");
    expect(note?.operators).toEqual([]);
  });

  it("leaves out empty levels and keeps the keys the app cannot show", () => {
    const view = ontologyBrowserView({
      ...ONTOLOGY,
      attributes: ONTOLOGY.attributes.filter((item) => item.level === "entity"),
      unsupported: ["example_unknown"],
      wordingReviewed: true,
      reviewStatus: "reviewed",
    });
    expect(view.sections.map((section) => section.level)).toEqual(["entity"]);
    expect(view.unsupported).toEqual(["example_unknown"]);
    expect(view.wordingReviewed).toBe(true);
    expect(ontologyBrowserView({ ...ONTOLOGY, attributes: [] }).sections).toEqual([]);
  });
});

describe("rangeText", () => {
  it("words the bounds of a number", () => {
    expect(rangeText(0, 1000)).toBe("0 to 1000");
    expect(rangeText(0, null)).toBe("0 or more");
    expect(rangeText(null, 10)).toBe("Up to 10");
    expect(rangeText(null, null)).toBeNull();
  });
});

describe("exampleText", () => {
  it("words the example with the value labels, Yes or No, and an IST date", () => {
    expect(exampleText(attribute("example_kind"))).toBe("Example first kind");
    expect(exampleText(attribute("state_codes"))).toBe("Example place one");
    expect(exampleText(attribute("example_flag"))).toBe("No");
    expect(exampleText({ ...attribute("example_flag"), example: true })).toBe("Yes");
    expect(exampleText(attribute("example_since"))).toBe("1 Jan 2000");
    expect(exampleText(attribute("example_count"))).toBe("12");
    expect(exampleText(attribute("example_ratio"))).toBe("1.5");
    expect(exampleText(attribute("example_note"))).toBeNull();
    expect(exampleText({ ...attribute("example_since"), example: "not a date" })).toBe(
      "not a date",
    );
    expect(exampleText({ ...attribute("example_note"), example: { a: 1 } })).toBe('{"a":1}');
  });
});

describe("usageNote", () => {
  it("names the registry entry that waits for the counts and the route it waits for", () => {
    expect(usageNote()).toEqual({
      title: "Attribute usage",
      waitingFor: [
        {
          method: "GET",
          path: "/v1/profile/admin/attribute-usage",
          owner: "services track (WP30)",
        },
      ],
    });
  });
});
