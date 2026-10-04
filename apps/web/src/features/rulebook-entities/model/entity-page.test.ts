import { describe, expect, it } from "vitest";
import { mentionedClauseFromDto, relationFromDto } from "@/entities/rulebook/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import {
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  mentionedClauseDto,
  relationDto,
} from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID, ruleVersionDto } from "@/test/rule-version-fixture";
import { mentionedClauseView, relationToEntity } from "./entity-page";

describe("mentionedClauseView", () => {
  it("marks every mention and links to the document with the first one marked", () => {
    const view = mentionedClauseView(mentionedClauseFromDto(mentionedClauseDto()));
    expect(view.segments).toEqual([
      { text: "Example clause names ", mark: false },
      { text: "example form", mark: true },
      { text: ", then ", mark: false },
      { text: "example form 1", mark: true },
      { text: " again.", mark: false },
    ]);
    expect(view).toMatchObject({
      clauseRef: "en.p1",
      externalRef: "Example 1/2000",
      mentions: 2,
      outOfForce: false,
      href: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}&start=21&end=33`,
    });
  });

  it("marks the whole clause from a link when the clause carries no span", () => {
    const view = mentionedClauseView(mentionedClauseFromDto(mentionedClauseDto({ mentions: [] })));
    expect(view.href).toBe(
      `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    );
    expect(view.segments).toHaveLength(1);
  });
});

describe("relationToEntity", () => {
  it("names the version it comes from when it was read, its id otherwise", () => {
    const relation = relationFromDto(relationDto());
    const read = new Map([
      [EXAMPLE_VERSION_ID, ruleVersionFromDto(ruleVersionDto({ version: 4 }))],
    ]);
    expect(relationToEntity(relation, read)).toEqual({
      relationId: "00000000-0000-4000-8000-0000000000b1",
      relation: "refers_to",
      from: {
        ruleVersionId: EXAMPLE_VERSION_ID,
        href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
        label: "example_rule v4",
        status: "draft",
      },
      evidenceClauseRef: "en.p1",
      evidenceHref: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    });
    expect(relationToEntity(relation, new Map()).from).toMatchObject({ label: null, status: null });
  });
});
