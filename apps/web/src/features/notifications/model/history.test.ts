import { describe, expect, it } from "vitest";
import { historyHrefs } from "./history";

describe("historyHrefs", () => {
  it("links the next page after the cursor and back to the newest from a later page", () => {
    expect(historyHrefs("/list", {}, null)).toEqual({ nextHref: null, firstHref: null });
    expect(historyHrefs("/list", { state: "failed" }, "next")).toEqual({
      nextHref: "/list?state=failed&cursor=next",
      firstHref: null,
    });
    expect(historyHrefs("/list", { cursor: "now" }, null)).toEqual({
      nextHref: null,
      firstHref: "/list",
    });
    expect(
      historyHrefs("/list", { state: "sent", cursor: "now" }, "next", {
        tenant: "t",
        business: "b",
      }),
    ).toEqual({
      nextHref: "/list?tenant=t&business=b&state=sent&cursor=next",
      firstHref: "/list?tenant=t&business=b&state=sent",
    });
  });
});
