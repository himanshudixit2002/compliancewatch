import { describe, expect, it } from "vitest";
import { mentionGroupFromDto } from "@/entities/rulebook/mappers";
import { mentionGroupDto } from "@/test/rulebook-fixture";
import {
  QUEUE_PAGE_SIZE,
  groupHref,
  groupNameLabel,
  queueHref,
  queueRow,
  queueView,
  readQueue,
  typeOptions,
} from "./queue";

const PATH = "/admin/rulebook/entities";

function groups(count: number) {
  return Array.from({ length: count }, (_, index) =>
    mentionGroupFromDto(mentionGroupDto({ proposed_name: `EXAMPLE-${index + 1}` })),
  );
}

describe("readQueue", () => {
  it("lists every type from the first page by default", () => {
    expect(readQueue({})).toEqual({ kind: "ok", filter: { entityType: null, after: null } });
  });

  it("reads a type and a cursor, an empty name included", () => {
    expect(readQueue({ type: "form", after_type: "form", after_name: "" })).toEqual({
      kind: "ok",
      filter: { entityType: "form", after: { entityType: "form", name: "" } },
    });
    expect(readQueue({ type: ["section"], after_type: "rule", after_name: "1@example" })).toEqual({
      kind: "ok",
      filter: { entityType: "section", after: { entityType: "rule", name: "1@example" } },
    });
  });

  it("refuses a type the rulebook does not know and drops a cursor that is not a group's key", () => {
    expect(readQueue({ type: "example" })).toEqual({
      kind: "invalid",
      value: "example",
      filter: { entityType: null, after: null },
    });
    expect(readQueue({ after_type: "example", after_name: "x" })).toEqual({
      kind: "ok",
      filter: { entityType: null, after: null },
    });
  });
});

describe("the queue's links", () => {
  it("keep an empty name in the cursor and in a group's address", () => {
    expect(queueHref(PATH, { entityType: null, after: null })).toBe(PATH);
    expect(queueHref(PATH, { entityType: "form", after: { entityType: "form", name: "" } })).toBe(
      `${PATH}?type=form&after_type=form&after_name=`,
    );
    expect(groupHref("form", "")).toBe("/admin/rulebook/entities/group?type=form&name=");
    expect(groupHref("notification", "01/2000-example tax")).toBe(
      "/admin/rulebook/entities/group?type=notification&name=01%2F2000-example+tax",
    );
  });

  it("names an empty group and offers every type first", () => {
    expect(groupNameLabel("")).toBe("(no name)");
    expect(groupNameLabel("EXAMPLE-1")).toBe("EXAMPLE-1");
    expect(typeOptions()[0]).toEqual({ value: "", label: "Every type" });
    expect(typeOptions().map((option) => option.value)).toContain("hsn_code");
    expect(typeOptions().find((option) => option.value === "hsn_code")?.label).toBe("HSN code");
  });
});

describe("queueView", () => {
  it("shows a page and links the next one after the last group shown", () => {
    const view = queueView(PATH, { entityType: "form", after: null }, groups(QUEUE_PAGE_SIZE + 1));
    expect(view.rows).toHaveLength(QUEUE_PAGE_SIZE);
    expect(view.mentionsOnPage).toBe(QUEUE_PAGE_SIZE * 2);
    expect(view.nextHref).toBe(
      `${PATH}?type=form&after_type=form&after_name=EXAMPLE-${QUEUE_PAGE_SIZE}`,
    );
    expect(view.firstHref).toBeNull();
  });

  it("has no next page on the last one and links back to the first", () => {
    const view = queueView(
      PATH,
      { entityType: null, after: { entityType: "form", name: "EXAMPLE-0" } },
      groups(2),
    );
    expect(view.nextHref).toBeNull();
    expect(view.firstHref).toBe(PATH);
  });

  it("words a row with its first mention marked in its document", () => {
    const row = queueRow(mentionGroupFromDto(mentionGroupDto()));
    expect(row).toMatchObject({
      typeLabel: "Form",
      nameLabel: "EXAMPLE-1",
      openCount: 2,
      href: "/admin/rulebook/entities/group?type=form&name=EXAMPLE-1",
      example: {
        text: "Example clause",
        reasonLabel: "No entity has this name",
        documentHref:
          "/admin/rulebook/documents/00000000-0000-0000-0000-00000000d0c1?clause_id=00000000-0000-5000-8000-0000000000c2&start=0&end=14",
      },
    });
    expect(queueRow(mentionGroupFromDto(mentionGroupDto({ examples: [] }))).example).toBeNull();
  });
});
