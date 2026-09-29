import { describe, expect, it } from "vitest";
import { COUNT_TILES, countLabel, toCountTile, toServiceErrorLike } from "./counts";

const at = (route: string) => (route === "/admin/rulebook/rules" ? "/admin/rulebook/rules" : null);

describe("count tiles", () => {
  it("count the two review queues and the two registries, each with the tool that lists them", () => {
    expect(COUNT_TILES.map((tile) => [tile.key, tile.toolRoute])).toEqual([
      ["entityGroups", "/admin/rulebook/entities"],
      ["relationCandidates", "/admin/rulebook/relations"],
      ["rules", "/admin/rulebook/rules"],
      ["prompts", "/admin/llm/prompts"],
    ]);
  });

  it("show a full page as at least that many", () => {
    expect(countLabel({ count: 3, capped: false })).toBe("3");
    expect(countLabel({ count: 200, capped: true })).toBe("200+");
  });

  it("link a tile to its tool once the tool is built, and add the open mentions to the groups", () => {
    const [groups, , rules] = COUNT_TILES;
    expect(
      toCountTile(groups!, { ok: true, value: { count: 5, capped: false, within: 7 } }, at),
    ).toEqual({
      key: "entityGroups",
      title: "Entity groups to review",
      value: "5",
      detail: "7 open mentions in these groups",
      href: null,
      error: null,
    });
    expect(
      toCountTile(rules!, { ok: true, value: { count: 12, capped: false } }, at),
    ).toMatchObject({ value: "12", detail: null, href: "/admin/rulebook/rules" });
  });

  it("put a failed read in the tile with what the error view shows and nothing else", () => {
    const [, candidates] = COUNT_TILES;
    const error = {
      kind: "network",
      message: "The service could not be reached.",
      requestId: "req-example-2",
    };
    expect(toCountTile(candidates!, { ok: false, error }, at)).toEqual({
      key: "relationCandidates",
      title: "Open relation candidates",
      value: null,
      detail: null,
      href: null,
      error: { message: "The service could not be reached.", requestId: "req-example-2" },
    });
    expect(
      toServiceErrorLike({
        message: "Not found",
        status: 404,
        requestId: "r",
        problem: { detail: "No such list" },
      }),
    ).toEqual({
      message: "Not found",
      status: 404,
      requestId: "r",
      problem: { detail: "No such list" },
    });
    expect(
      toServiceErrorLike({ message: "Oops", requestId: "r", problem: { detail: null } }),
    ).toEqual({ message: "Oops", requestId: "r" });
  });
});
