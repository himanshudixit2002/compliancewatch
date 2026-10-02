import { describe, expect, it } from "vitest";
import { businessFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, REGISTRATION_DTO } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { profileNodeFromDto } from "@/entities/business/mappers";
import {
  attributeLabel,
  attributeRows,
  sourceLabel,
  stateCounts,
  unansweredAttributes,
} from "./attributes";

const ontology = ontologyFixture();
const business = businessFromDto(BUSINESS_DTO);
const registration = profileNodeFromDto(REGISTRATION_DTO);

describe("attributeRows", () => {
  it("lists stored values in ontology order, worded, with state, year, source and time", () => {
    const rows = attributeRows(ontology, business.attributes);
    expect(rows.map((row) => row.id)).toEqual([
      "state_codes",
      "example_band@2000-01",
      "example_count",
    ]);
    expect(rows[0]).toMatchObject({
      label: "State codes",
      definition: "Example definition of state_codes.",
      state: "known",
      stateLabel: "Known",
      valueText: "Example place one, Example place two",
      asOfFy: null,
      sourceLabel: "GSTIN lookup",
      updatedAt: "2 Jan 2000, 8:34 am IST",
    });
    expect(rows[1]).toMatchObject({ valueText: "Example medium band", asOfFy: "2000-01" });
    expect(rows[2]).toMatchObject({
      state: "unsure",
      valueText: "Not sure",
      sourceLabel: "Your answer",
      updatedAt: null,
    });
  });

  it("shows the newest year first and keeps a value the ontology does not hold", () => {
    const rows = attributeRows(ontology, [
      { ...business.attributes[1]!, asOfFy: "1999-00", value: "small" },
      business.attributes[1]!,
      {
        key: "retired_key",
        state: "known",
        value: "x",
        asOfFy: null,
        source: "import",
        updatedAt: null,
      },
    ]);
    expect(rows.map((row) => row.id)).toEqual([
      "example_band@2000-01",
      "example_band@1999-00",
      "retired_key",
    ]);
    expect(rows[2]).toMatchObject({
      label: "Retired key",
      definition: "",
      valueText: "x",
      sourceLabel: "Import",
      attribute: undefined,
    });
  });

  it("words the known sources and humanises others", () => {
    expect(sourceLabel("derived")).toBe("Worked out by the service");
    expect(sourceLabel("partner_api")).toBe("Partner API");
    expect(attributeLabel("gstin_status")).toBe("GSTIN status");
  });
});

describe("unansweredAttributes", () => {
  it("lists answerable attributes of the levels without a value, per year where stated", () => {
    const entity = unansweredAttributes(ontology, ["entity"], business.attributes, "2000-01");
    expect(entity.map((item) => item.key)).toEqual([]);
    const nextYear = unansweredAttributes(ontology, ["entity"], business.attributes, "2001-02");
    expect(nextYear.map((item) => item.key)).toEqual(["example_band"]);
    const reg = unansweredAttributes(
      ontology,
      ["registration"],
      registration.attributes,
      "2000-01",
    );
    expect(reg.map((item) => item.key)).toEqual(["example_since"]);
  });
});

describe("stateCounts", () => {
  it("counts the values by state", () => {
    expect(stateCounts([...business.attributes, ...registration.attributes])).toEqual({
      known: 3,
      unsure: 1,
      not_applicable: 1,
    });
  });
});
