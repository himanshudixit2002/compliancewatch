import { describe, expect, it } from "vitest";
import { listedObligationFromDto } from "@/entities/obligation/mappers";
import { NOW, REGISTRATION_ID, dueAt, listedObligationDto } from "@/test/obligation-fixture";
import {
  MAX_WINDOW_DAYS,
  compareByDue,
  decodeListKey,
  encodeListKey,
  hasFilterErrors,
  isAfterKey,
  listHref,
  mergeByDue,
  obligationRow,
  readListFilter,
  windowAfter,
  windowText,
  type ListKey,
} from "./list";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const C = "00000000-0000-4000-8000-00000000000c";

/** Base64url without padding, as the list writes its keys. */
function b64url(text: string): string {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function key(id: string, day: string | null): ListKey {
  return { id, dueAt: day === null ? null : dueAt(day) };
}

describe("list keys", () => {
  it("round-trip through the address and refuse anything this list did not write", () => {
    const dated = key(A, "2000-01-20");
    expect(decodeListKey(encodeListKey(dated))).toEqual(dated);
    expect(decodeListKey(encodeListKey(key(B, null)))).toEqual(key(B, null));
    expect(decodeListKey(undefined)).toBeNull();
    expect(decodeListKey("")).toBeNull();
    expect(decodeListKey("not base64!")).toBeNull();
    expect(decodeListKey(b64url(JSON.stringify({ d: null, i: "not-an-id" })))).toBeNull();
    expect(decodeListKey(b64url(JSON.stringify({ d: "yesterday", i: A })))).toBeNull();
    expect(decodeListKey(b64url(JSON.stringify({ d: 5, i: A })))).toBeNull();
    expect(decodeListKey(b64url("null"))).toBeNull();
    expect(decodeListKey(b64url("{"))).toBeNull();
    expect(decodeListKey("a".repeat(600))).toBeNull();
  });

  it("order by due instant, the undated last, then by id", () => {
    const rows = [key(C, null), key(B, "2000-01-20"), key(A, "2000-01-20"), key(A, "2000-01-05")];
    expect([...rows].sort(compareByDue)).toEqual([
      key(A, "2000-01-05"),
      key(A, "2000-01-20"),
      key(B, "2000-01-20"),
      key(C, null),
    ]);
    expect(compareByDue(key(A, null), key(B, null))).toBeLessThan(0);
    expect(compareByDue(key(A, "2000-01-05"), key(A, null))).toBeLessThan(0);
    expect(isAfterKey(key(B, "2000-01-20"), key(A, "2000-01-20"))).toBe(true);
    expect(isAfterKey(key(A, "2000-01-20"), key(A, "2000-01-20"))).toBe(false);
    expect(isAfterKey(key(A, "2000-01-01"), null)).toBe(true);
  });
});

describe("readListFilter", () => {
  it("reads the defaults from an empty address", () => {
    const read = readListFilter({});
    expect(read.filter).toEqual({ status: "all", from: null, to: null, after: null });
    expect(hasFilterErrors(read)).toBe(false);
  });

  it("keeps a known status and a valid window, and ignores an unknown status", () => {
    const after = encodeListKey(key(A, "2000-01-20"));
    const read = readListFilter({
      status: ["todo", "done"],
      from: "2000-01-01",
      to: "2000-12-31",
      after,
    });
    expect(read.filter).toEqual({
      status: "todo",
      from: "2000-01-01",
      to: "2000-12-31",
      after: key(A, "2000-01-20"),
    });
    expect(readListFilter({ status: "overdue" }).filter.status).toBe("all");
  });

  it("refuses a date that is not one, an end before the start and a window over the limit", () => {
    const junk = readListFilter({ from: "2000-02-30", to: "soon" });
    expect(junk.errors).toEqual({
      from: "Enter a date as YYYY-MM-DD.",
      to: "Enter a date as YYYY-MM-DD.",
    });
    expect(junk.typed).toEqual({ from: "2000-02-30", to: "soon" });
    expect(junk.filter.from).toBeNull();
    expect(readListFilter({ from: "2000-02-01", to: "2000-01-31" }).errors.to).toBe(
      "The end of the window is before its start.",
    );
    // 2000 is a leap year: 1 Jan to 31 Dec is 366 days, the limit; one more is refused.
    expect(hasFilterErrors(readListFilter({ from: "2000-01-01", to: "2000-12-31" }))).toBe(false);
    const long = readListFilter({ from: "2000-01-01", to: "2001-01-01" });
    expect(long.errors.to).toBe(
      `This window spans 367 days; the obligation service lists at most ${MAX_WINDOW_DAYS} at a time. Shorten it, or leave one end empty.`,
    );
    expect(long.filter.to).toBeNull();
  });
});

describe("listHref and windows", () => {
  it("leaves the defaults out of the address and carries the key of the page's last row", () => {
    expect(listHref("/b/x/obligations", { status: "all", from: null, to: null })).toBe(
      "/b/x/obligations",
    );
    const href = listHref(
      "/b/x/obligations",
      { status: "done", from: "2000-01-01", to: null },
      key(A, "2000-01-20"),
    );
    const url = new URL(href, "http://localhost");
    expect(url.searchParams.get("status")).toBe("done");
    expect(url.searchParams.get("from")).toBe("2000-01-01");
    expect(url.searchParams.has("to")).toBe(false);
    expect(decodeListKey(url.searchParams.get("after") ?? undefined)).toEqual(key(A, "2000-01-20"));
  });

  it("asks each node from the key's due day, or the filter's start when it is later", () => {
    expect(windowAfter({ from: null, to: null }, null)).toEqual({ from: null, to: null });
    expect(windowAfter({ from: null, to: "2000-12-31" }, key(A, "2000-01-20"))).toEqual({
      from: "2000-01-20",
      to: "2000-12-31",
    });
    expect(windowAfter({ from: "2000-02-01", to: null }, key(A, "2000-01-20"))).toEqual({
      from: "2000-02-01",
      to: null,
    });
    expect(windowAfter({ from: null, to: null }, key(A, null))).toEqual({ from: null, to: null });
  });

  it("words the window", () => {
    expect(windowText({ from: "2000-01-01", to: "2000-03-31" })).toBe(
      "Due from 1 Jan 2000 to 31 Mar 2000.",
    );
    expect(windowText({ from: "2000-01-01", to: null })).toBe("Due on or after 1 Jan 2000.");
    expect(windowText({ from: null, to: "2000-03-31" })).toBe("Due on or before 31 Mar 2000.");
    expect(windowText({ from: null, to: null })).toBeNull();
  });
});

describe("mergeByDue", () => {
  it("merges the nodes' rows in due order and says whether more follow", () => {
    const merged = mergeByDue(
      [
        { items: [key(B, "2000-01-20"), key(C, "2000-02-20")], more: false },
        { items: [key(A, "2000-01-05"), key(A, null)], more: false },
      ],
      3,
    );
    expect(merged.items).toEqual([
      key(A, "2000-01-05"),
      key(B, "2000-01-20"),
      key(C, "2000-02-20"),
    ]);
    expect(merged.more).toBe(true);
    expect(mergeByDue([{ items: [key(A, "2000-01-05")], more: false }], 3).more).toBe(false);
    expect(mergeByDue([{ items: [], more: true }], 3).more).toBe(true);
  });
});

describe("obligationRow", () => {
  it("words a row for the table and names its node only for a business with several", () => {
    const item = listedObligationFromDto(listedObligationDto({ due_at: dueAt("2000-01-09") }));
    const nodes = [
      { id: "00000000-0000-4000-8000-0000000000e1", name: "Example business (PAN ABCDE1234F)" },
      { id: REGISTRATION_ID, name: "29ABCDE1234F1Z5 (Example registration)" },
    ];
    const row = obligationRow(item, { href: "/b/x/obligations/y", nodes, now: NOW });
    expect(row).toMatchObject({
      title: "Example return 1",
      node: "29ABCDE1234F1Z5 (Example registration)",
      statusLabel: "Open",
      due: "9 Jan 2000",
      dueNote: "Overdue by 1 day",
      overdue: true,
      citations: 1,
      review: { label: "Not yet reviewed", reviewed: false },
    });
    expect(obligationRow(item, { href: "/x", nodes: nodes.slice(1), now: NOW }).node).toBeNull();
    expect(obligationRow(item, { href: "/x", nodes: [nodes[0]!, nodes[0]!], now: NOW }).node).toBe(
      "A node of this business",
    );
  });
});
