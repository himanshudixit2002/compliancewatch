import { describe, expect, it } from "vitest";
import { ontologyFixture } from "@/test/ontology-fixture";
import {
  MAX_DEPTH,
  MAX_PARTS,
  addTo,
  combineRoot,
  conditionProblem,
  emptyGroup,
  emptyPredicate,
  errorKey,
  findNode,
  fromMapping,
  idSource,
  moveNode,
  operatorsFor,
  parseJson,
  removeNode,
  shapeProblem,
  sizeProblem,
  toJson,
  toMapping,
  toggleNot,
  validateTree,
  withAttribute,
  withOperator,
  type NodeDraft,
  type PredicateDraft,
} from "./predicate-tree";

/** The fixture with operators for the types it leaves without (decimal, date, string). */
const ONTOLOGY = {
  ...ontologyFixture(),
  operatorsByType: {
    ...ontologyFixture().operatorsByType,
    decimal: ["eq", "neq", "gt", "gte", "lt", "lte"],
    date: ["eq", "neq", "gt", "gte", "lt", "lte"],
    string: ["eq", "neq", "in", "not_in"],
  },
};

const STORED = {
  all_of: [
    { attribute: "example_kind", operator: "eq", value: "first" },
    { not: { attribute: "state_codes", operator: "contains_any", value: ["01", "02"] } },
    {
      any_of: [
        { attribute: "example_count", operator: "gte", value: 12 },
        { attribute: "example_flag", operator: "eq", value: true },
      ],
    },
    { attribute: "example_question", free_text: "Example condition an analyst judges." },
    { attribute: "example_ratio", operator: "gt", value: "1.5", free_text: "Example hint" },
  ],
};

function predicate(node: NodeDraft | undefined): PredicateDraft {
  if (node?.kind !== "predicate") throw new Error("expected a predicate");
  return node;
}

describe("fromMapping and toMapping", () => {
  it("round-trips a stored condition as the kernel writes it", () => {
    const tree = fromMapping(STORED, idSource());
    expect(toMapping(tree, ONTOLOGY)).toEqual(STORED);
    expect(JSON.parse(toJson(tree, ONTOLOGY))).toEqual(STORED);
  });

  it("opens an empty or missing condition as an empty all of", () => {
    expect(fromMapping({}, idSource())).toEqual({ kind: "all_of", id: "n0", items: [] });
    expect(fromMapping(null, idSource())).toEqual({ kind: "all_of", id: "n0", items: [] });
  });

  it("keeps a part of an unknown shape whole and writes it back as it was", () => {
    const stored = { all_of: [{ example: 1 }, { attribute: "example_kind", value: [{}] }] };
    const tree = fromMapping(stored, idSource());
    expect(tree.kind === "all_of" && tree.items.map((item) => item.kind)).toEqual(["raw", "raw"]);
    expect(toMapping(tree, ONTOLOGY)).toEqual(stored);
  });

  it("writes values in the kernel's canonical forms for the attribute's type", () => {
    const newId = idSource();
    const count: PredicateDraft = {
      ...emptyPredicate(newId(), "example_count"),
      operator: "in",
      values: ["1", " 2 "],
      types: [],
    };
    const flag: PredicateDraft = {
      ...emptyPredicate(newId(), "example_flag"),
      operator: "eq",
      values: ["false"],
      types: [],
    };
    const unknown: PredicateDraft = {
      ...emptyPredicate(newId(), "example_unknown"),
      operator: "eq",
      values: ["7"],
      types: ["number"],
      freeText: "  Example hint  ",
    };
    expect(toMapping(count, ONTOLOGY)).toEqual({
      attribute: "example_count",
      operator: "in",
      value: [1, 2],
    });
    expect(toMapping(flag, ONTOLOGY)).toEqual({
      attribute: "example_flag",
      operator: "eq",
      value: false,
    });
    expect(toMapping(unknown, ONTOLOGY)).toEqual({
      attribute: "example_unknown",
      operator: "eq",
      value: 7,
      free_text: "Example hint",
    });
  });
});

describe("validateTree", () => {
  it("finds nothing wrong with a well-shaped condition", () => {
    expect(validateTree(fromMapping(STORED, idSource()), ONTOLOGY)).toEqual({});
  });

  it("ties each shape problem to its node's field", () => {
    const newId = idSource();
    const root = emptyGroup(newId());
    const noAttribute = emptyPredicate(newId());
    const badKey: PredicateDraft = { ...emptyPredicate(newId(), "Example Key"), freeText: "x" };
    const wrongOperator: PredicateDraft = {
      ...emptyPredicate(newId(), "example_flag"),
      operator: "gt",
      values: ["true"],
    };
    const notWhole: PredicateDraft = {
      ...emptyPredicate(newId(), "example_count"),
      operator: "eq",
      values: ["1.5"],
    };
    const noValues: PredicateDraft = {
      ...emptyPredicate(newId(), "example_kind"),
      operator: "in",
      values: [],
    };
    const notAnOption: PredicateDraft = {
      ...emptyPredicate(newId(), "example_kind"),
      operator: "eq",
      values: ["third"],
    };
    const badDate: PredicateDraft = {
      ...emptyPredicate(newId(), "example_since"),
      operator: "eq",
      values: ["01/01/2000"],
    };
    const tree = [
      noAttribute,
      badKey,
      wrongOperator,
      notWhole,
      noValues,
      notAnOption,
      badDate,
    ].reduce<NodeDraft>((current, node) => addTo(current, root.id, node), root);
    expect(validateTree(tree, ONTOLOGY)).toEqual({
      [errorKey(noAttribute.id, "attribute")]: "Choose an attribute.",
      [errorKey(noAttribute.id, "freeText")]:
        "Choose an operator and a value, or write what has to be judged.",
      [errorKey(badKey.id, "attribute")]:
        "An attribute key is lower-case letters, digits and underscores, starting with a letter.",
      [errorKey(wrongOperator.id, "operator")]:
        "This operator does not apply to the attribute's type.",
      [errorKey(notWhole.id, "value")]: "Enter a whole number.",
      [errorKey(noValues.id, "value")]: "Choose or enter at least one value.",
      [errorKey(notAnOption.id, "value")]: "Choose one of the attribute's values.",
      [errorKey(badDate.id, "value")]: "Enter a date as YYYY-MM-DD.",
    });
  });

  it("checks a decimal's and a boolean's text, and an unknown attribute's value only for presence", () => {
    const newId = idSource();
    const decimal: PredicateDraft = {
      ...emptyPredicate(newId(), "example_ratio"),
      operator: "gt",
      values: ["one"],
    };
    const flag: PredicateDraft = {
      ...emptyPredicate(newId(), "example_flag"),
      operator: "eq",
      values: ["yes"],
    };
    const unknown: PredicateDraft = {
      ...emptyPredicate(newId(), "example_unknown"),
      operator: "eq",
      values: [" "],
    };
    expect(validateTree(decimal, ONTOLOGY)).toEqual({
      [errorKey(decimal.id, "value")]: "Enter a number, such as 1.5.",
    });
    expect(validateTree(flag, ONTOLOGY)).toEqual({
      [errorKey(flag.id, "value")]: "Choose Yes or No.",
    });
    expect(validateTree(unknown, null)).toEqual({
      [errorKey(unknown.id, "value")]: "Enter a value.",
    });
  });
});

describe("the JSON view", () => {
  it("reads a well-shaped condition back into a tree", () => {
    const parsed = parseJson(JSON.stringify(STORED), idSource());
    expect(parsed.ok).toBe(true);
    if (parsed.ok) expect(toMapping(parsed.node, ONTOLOGY)).toEqual(STORED);
  });

  it("names the first problem of a malformed one", () => {
    expect(parseJson("{", idSource())).toEqual({ ok: false, problem: "This is not valid JSON." });
    expect(parseJson("[]", idSource())).toEqual({
      ok: false,
      problem: "specification must be an object.",
    });
    expect(shapeProblem({ all_of: {} })).toBe("specification.all_of must be a list.");
    expect(shapeProblem({ any_of: [{ attribute: "Bad" }] })).toBe(
      "specification.any_of[0].attribute must be a lower-case key such as example_key.",
    );
    expect(shapeProblem({ not: { attribute: "example_kind", operator: "eq" } })).toBe(
      "specification.not needs an operator and a value together.",
    );
    expect(shapeProblem({ attribute: "example_kind", operator: 1, value: 1 })).toBe(
      "specification.operator must be text.",
    );
    expect(shapeProblem({ attribute: "example_kind", operator: "in", value: [{}] })).toBe(
      "specification.value must be a string, a number or a boolean, or a list of them.",
    );
    expect(shapeProblem({ attribute: "example_kind", free_text: 1 })).toBe(
      "specification.free_text must be text.",
    );
    expect(shapeProblem({ attribute: "example_kind", free_text: " " })).toBe(
      "specification needs an operator and a value, or free text.",
    );
    expect(shapeProblem({ attribute: "example_kind", extra: 1 })).toBe(
      "specification must be all_of, any_of, not, or a predicate with attribute, operator, value and free_text.",
    );
  });
});

describe("the condition's bounds", () => {
  /** A predicate inside `levels` nested negations: the predicate sits at depth levels + 1. */
  function negated(levels: number): unknown {
    let node: unknown = { attribute: "example_kind", operator: "eq", value: "first" };
    for (let level = 0; level < levels; level += 1) node = { not: node };
    return node;
  }

  /** The same as JSON text, built without JSON.stringify (which would overflow first). */
  function negatedText(levels: number): string {
    return `${'{"not":'.repeat(levels)}{"attribute":"example_kind","free_text":"x"}${"}".repeat(levels)}`;
  }

  it("takes a condition up to the depth and the parts it allows", () => {
    expect(sizeProblem(negated(MAX_DEPTH - 1))).toBeNull();
    expect(conditionProblem(negated(MAX_DEPTH - 1))).toBeNull();
    const parts = {
      all_of: Array.from({ length: MAX_PARTS - 1 }, () => ({
        attribute: "example_kind",
        free_text: "Example",
      })),
    };
    expect(sizeProblem(parts)).toBeNull();
  });

  it("refuses a condition nested too deep or with too many parts, in words", () => {
    expect(sizeProblem(negated(MAX_DEPTH))).toBe(
      "The condition nests deeper than 32 levels of groups and negations: make it flatter.",
    );
    expect(
      sizeProblem({
        any_of: Array.from({ length: MAX_PARTS }, () => ({ attribute: "a", free_text: "x" })),
      }),
    ).toBe("The condition holds more than 500 parts: split the rule or simplify the condition.");
  });

  it("refuses 20,000 nested negations without overflowing, in the form and the JSON view", () => {
    const deep = JSON.parse(negatedText(20_000)) as unknown;
    expect(conditionProblem(deep)).toMatch(/deeper than 32 levels/);
    expect(parseJson(negatedText(20_000), idSource())).toEqual({
      ok: false,
      problem:
        "The condition nests deeper than 32 levels of groups and negations: make it flatter.",
    });
  });
});

describe("the changes", () => {
  it("adds, nests, moves and removes parts without touching the old tree", () => {
    const newId = idSource("t");
    const root = fromMapping(STORED, newId);
    const added = addTo(root, root.id, emptyPredicate("extra", "example_flag"));
    expect(root.kind === "all_of" && root.items).toHaveLength(5);
    expect(added.kind === "all_of" && added.items.map((item) => item.id).at(-1)).toBe("extra");

    const negated = toggleNot(added, "extra", newId);
    const wrapper = negated.kind === "all_of" ? negated.items.at(-1) : undefined;
    expect(wrapper?.kind).toBe("not");
    expect(toggleNot(negated, wrapper?.id ?? "", newId)).toEqual(added);

    const moved = moveNode(added, "extra", -1);
    expect(moved.kind === "all_of" && moved.items.map((item) => item.id).slice(-2)).toEqual([
      "extra",
      (added.kind === "all_of" ? added.items[4]?.id : undefined) as string,
    ]);
    expect(moveNode(added, "extra", 1)).toBe(added);

    const firstId = root.kind === "all_of" ? (root.items[0]?.id as string) : "";
    const removed = removeNode(added, firstId);
    expect(removed.kind === "all_of" && removed.items).toHaveLength(5);
    expect(findNode(removed, firstId)).toBeUndefined();
    expect(removeNode(added, added.id)).toBe(added);
  });

  it("removes a negation along with its one part", () => {
    const root = fromMapping(STORED, idSource());
    const negation = root.kind === "all_of" ? root.items[1] : undefined;
    const inner = negation?.kind === "not" ? negation.item.id : "";
    const removed = removeNode(root, inner);
    expect(findNode(removed, negation?.id ?? "")).toBeUndefined();
    expect(removed.kind === "all_of" && removed.items).toHaveLength(4);
  });

  it("keeps an operator and values while a new attribute allows them", () => {
    const kind: PredicateDraft = {
      ...emptyPredicate("p", "example_kind"),
      operator: "eq",
      values: ["first"],
      types: ["string"],
    };
    expect(withAttribute(kind, "example_kind", ONTOLOGY)).toEqual(kind);
    expect(withAttribute(kind, "example_band", ONTOLOGY)).toMatchObject({
      attribute: "example_band",
      operator: "eq",
      values: [],
    });
    expect(withAttribute(kind, "state_codes", ONTOLOGY)).toMatchObject({
      operator: "",
      values: [],
    });
    const count: PredicateDraft = {
      ...emptyPredicate("c", "example_count"),
      operator: "gt",
      values: ["3"],
      types: ["number"],
    };
    expect(withAttribute(count, "example_unknown", ONTOLOGY)).toMatchObject({
      operator: "gt",
      values: [],
    });
    expect(predicate(withOperator(count, "in"))).toMatchObject({ operator: "in", values: ["3"] });
    const many = {
      ...count,
      operator: "in",
      values: ["1", "2"],
      types: ["number", "number"] as const,
    };
    expect(withOperator({ ...many, types: [...many.types] }, "eq")).toMatchObject({
      values: ["1"],
      types: ["number"],
    });
    expect(withOperator(count, "")).toMatchObject({ operator: "", values: [], types: [] });
  });

  it("offers the ontology's operators for the attribute's type, every kernel one for an unknown", () => {
    expect(operatorsFor(ONTOLOGY, "example_flag")).toEqual(["eq", "neq"]);
    expect(operatorsFor(ontologyFixture(), "example_ratio")).toEqual([]);
    expect(operatorsFor(ONTOLOGY, "example_unknown")).toContain("contains_any");
    expect(operatorsFor(null, "example_flag")).toHaveLength(10);
  });
});

describe("the lists and the root", () => {
  it("leaves the empty lines of a list out, and asks for one value at least", () => {
    const list: PredicateDraft = {
      ...emptyPredicate("l", "example_count"),
      operator: "in",
      values: ["1", "", " ", "2"],
      types: [],
    };
    expect(toMapping(list, ONTOLOGY)).toEqual({
      attribute: "example_count",
      operator: "in",
      value: [1, 2],
    });
    expect(validateTree(list, ONTOLOGY)).toEqual({});
    expect(validateTree({ ...list, values: ["", " "] }, ONTOLOGY)).toEqual({
      [errorKey("l", "value")]: "Choose or enter at least one value.",
    });
  });

  it("combines a single condition with a new one in an all of, and adds to a group as it is", () => {
    const newId = idSource("r");
    const single = fromMapping({ attribute: "example_flag", operator: "eq", value: true }, newId);
    const combined = combineRoot(single, emptyPredicate("added"), newId);
    expect(combined.kind).toBe("all_of");
    expect(toMapping(combined, ONTOLOGY)).toEqual({
      all_of: [
        { attribute: "example_flag", operator: "eq", value: true },
        { attribute: "", free_text: "" },
      ],
    });
    const group = emptyGroup("g");
    expect(combineRoot(group, emptyPredicate("x"), newId)).toEqual({
      ...group,
      items: [emptyPredicate("x")],
    });
  });
});
