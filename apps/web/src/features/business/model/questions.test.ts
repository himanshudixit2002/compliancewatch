import { describe, expect, it } from "vitest";
import { businessFromDto, onboardingFromDto } from "@/entities/business/mappers";
import type { Onboarding, Question } from "@/entities/business/types";
import { BUSINESS_DTO, ENTITY_ID, ONBOARDING_DTO, REGISTRATION_ID } from "@/test/business-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import {
  SKIP_LIST_LIMIT,
  attributeForQuestion,
  businessNodes,
  checklistItems,
  nodeLabel,
  parseSkipList,
  pickQuestion,
  serialiseSkipList,
  skipCookieName,
  skipKey,
  withSkip,
} from "./questions";

const ONTOLOGY = ontologyFixture();
const BUSINESS = businessFromDto(BUSINESS_DTO);
const FY = "2000-01";

/** The checklist's answer when the entity's unsure count question comes next. */
function onboardingWith(next: Partial<Question> | null): Onboarding {
  const base = onboardingFromDto(ONBOARDING_DTO);
  if (next === null) return { ...base, next: null, complete: true };
  return {
    ...base,
    next: {
      ...(base.next as Question),
      nodeId: ENTITY_ID,
      level: "entity",
      key: "example_count",
      state: "unsure",
      type: "integer",
      question: "Example service wording?",
      ...next,
    },
  };
}

describe("the skip list", () => {
  it("names one cookie per business and one item per node and attribute", () => {
    expect(skipCookieName(ENTITY_ID)).toBe(`cw_onboarding_skip_${ENTITY_ID}`);
    expect(skipKey(REGISTRATION_ID, "example_flag")).toBe(`${REGISTRATION_ID}:example_flag`);
  });

  it("round-trips sorted and drops anything malformed", () => {
    const items = new Set([skipKey(REGISTRATION_ID, "b_key"), skipKey(ENTITY_ID, "a_key")]);
    const text = serialiseSkipList(items);
    expect(JSON.parse(text)).toEqual([...items].sort());
    expect(parseSkipList(text)).toEqual(items);
    expect(parseSkipList(undefined).size).toBe(0);
    expect(parseSkipList("").size).toBe(0);
    expect(parseSkipList("not json").size).toBe(0);
    expect(parseSkipList('{"a":1}').size).toBe(0);
    expect(
      parseSkipList(JSON.stringify([skipKey(ENTITY_ID, "ok_key"), "x:y", 3, `${ENTITY_ID}:Bad`])),
    ).toEqual(new Set([skipKey(ENTITY_ID, "ok_key")]));
  });

  it("keeps at most the limit", () => {
    const many = Array.from({ length: SKIP_LIST_LIMIT + 5 }, (_, i) =>
      skipKey(ENTITY_ID, `key_${String(i).padStart(3, "0")}`),
    );
    expect(parseSkipList(JSON.stringify(many)).size).toBe(SKIP_LIST_LIMIT);
    expect(JSON.parse(serialiseSkipList(new Set(many)))).toHaveLength(SKIP_LIST_LIMIT);
  });

  it("adds an unsure item and removes it on any other answer", () => {
    const item = skipKey(ENTITY_ID, "example_count");
    const added = withSkip(new Set(), item, true);
    expect(added.has(item)).toBe(true);
    expect(withSkip(added, item, false).has(item)).toBe(false);
  });
});

describe("checklistItems", () => {
  it("walks the entity then each registration in ontology order, answerable attributes only", () => {
    expect(checklistItems(BUSINESS, ONTOLOGY, FY)).toEqual([
      {
        nodeId: ENTITY_ID,
        level: "entity",
        key: "state_codes",
        state: "known",
        perFinancialYear: false,
      },
      {
        nodeId: ENTITY_ID,
        level: "entity",
        key: "example_band",
        state: "known",
        perFinancialYear: true,
      },
      {
        nodeId: ENTITY_ID,
        level: "entity",
        key: "example_count",
        state: "unsure",
        perFinancialYear: false,
      },
      {
        nodeId: REGISTRATION_ID,
        level: "registration",
        key: "example_kind",
        state: "known",
        perFinancialYear: false,
      },
      {
        nodeId: REGISTRATION_ID,
        level: "registration",
        key: "example_since",
        state: "missing",
        perFinancialYear: false,
      },
      {
        nodeId: REGISTRATION_ID,
        level: "registration",
        key: "example_flag",
        state: "not_applicable",
        perFinancialYear: false,
      },
    ]);
  });

  it("reads a per-year value for the year asked only", () => {
    const band = checklistItems(BUSINESS, ONTOLOGY, "2001-02").find(
      (item) => item.key === "example_band",
    );
    expect(band?.state).toBe("missing");
  });
});

describe("pickQuestion", () => {
  it("asks the checklist's next question while it is not skipped", () => {
    const onboarding = onboardingWith({});
    expect(pickQuestion(onboarding, BUSINESS, ONTOLOGY, new Set())).toBe(onboarding.next);
  });

  it("walks past a skipped question to the next open one, worded by the ontology", () => {
    const question = pickQuestion(
      onboardingWith({}),
      BUSINESS,
      ONTOLOGY,
      new Set([skipKey(ENTITY_ID, "example_count")]),
    );
    expect(question).toEqual({
      nodeId: REGISTRATION_ID,
      level: "registration",
      key: "example_since",
      state: "missing",
      perFinancialYear: false,
      asOfFy: null,
      type: "date",
      question: "Example question about example_since?",
      help: "",
      options: [],
      min: null,
      max: null,
    });
  });

  it("gives the year to a per-year question found by the walk", () => {
    const onboarding = { ...onboardingWith({}), asOfFy: "2001-02" };
    const question = pickQuestion(
      onboarding,
      BUSINESS,
      ONTOLOGY,
      new Set([skipKey(ENTITY_ID, "example_count")]),
    );
    expect(question?.key).toBe("example_band");
    expect(question?.asOfFy).toBe("2001-02");
  });

  it("is done when every open question is skipped, or the checklist is complete", () => {
    const skipped = new Set([
      skipKey(ENTITY_ID, "example_count"),
      skipKey(REGISTRATION_ID, "example_since"),
    ]);
    expect(pickQuestion(onboardingWith({}), BUSINESS, ONTOLOGY, skipped)).toBeNull();
    expect(pickQuestion(onboardingWith(null), BUSINESS, ONTOLOGY, new Set())).toBeNull();
  });
});

describe("attributeForQuestion", () => {
  const next = onboardingWith({}).next as Question;

  it("uses the ontology's attribute when it has the key", () => {
    expect(attributeForQuestion(next, ONTOLOGY)?.min).toBe(0);
  });

  it("builds one from the question for a key the cached ontology lacks", () => {
    const attribute = attributeForQuestion(
      {
        ...next,
        key: "example_new",
        level: "registration",
        type: "enum",
        options: [{ value: "a", label: "Example a" }],
      },
      ONTOLOGY,
    );
    expect(attribute).toMatchObject({
      key: "example_new",
      type: "enum",
      level: "registration",
      question: "Example service wording?",
      options: [{ value: "a", label: "Example a" }],
    });
    expect(attributeForQuestion({ ...next, key: "example_other" }, ONTOLOGY)?.level).toBe("entity");
  });

  it("gives up on a type no control draws", () => {
    expect(
      attributeForQuestion({ ...next, key: "example_new", type: "polygon" }, ONTOLOGY),
    ).toBeUndefined();
  });
});

describe("nodeLabel and businessNodes", () => {
  it("names the business by its PAN and a registration by its GSTIN", () => {
    expect(nodeLabel(BUSINESS, ENTITY_ID)).toBe("About Example business (PAN ABCDE1234F).");
    expect(nodeLabel(BUSINESS, REGISTRATION_ID)).toBe(
      "About the registration 29ABCDE1234F1Z5 (Example registration).",
    );
    expect(nodeLabel(BUSINESS, "other")).toBe("About node other.");
  });

  it("lists the entity as a node, then the registrations", () => {
    const nodes = businessNodes(BUSINESS);
    expect(nodes.map((node) => [node.id, node.level, node.key])).toEqual([
      [ENTITY_ID, "entity", "ABCDE1234F"],
      [REGISTRATION_ID, "registration", "29ABCDE1234F1Z5"],
    ]);
  });
});
