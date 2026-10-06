import { describe, expect, it } from "vitest";
import { membersOf } from "./union";

type Example = "first" | "second" | "third";

describe("membersOf", () => {
  it("lists the members in the order the record holds them", () => {
    expect(membersOf<Example>({ second: true, first: true, third: true })).toEqual([
      "second",
      "first",
      "third",
    ]);
  });

  it("fails the build when the record lacks a member or holds one the union does not", () => {
    // @ts-expect-error "third" is missing from the record
    const missing = membersOf<Example>({ first: true, second: true });
    const extra = membersOf<Example>({
      first: true,
      second: true,
      third: true,
      // @ts-expect-error "fourth" is not a member of the union
      fourth: true,
    });
    expect(missing).toHaveLength(2);
    expect(extra).toHaveLength(4);
  });
});
