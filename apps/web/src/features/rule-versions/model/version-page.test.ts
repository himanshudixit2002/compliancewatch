import { describe, expect, it } from "vitest";
import { clauseDetailFromDto, relationFromDto } from "@/entities/rulebook/mappers";
import type { RelationDto } from "@/entities/rulebook/types";
import { citationFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import {
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  citationDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import {
  citationView,
  clauseHref,
  graphHref,
  markQuote,
  relationView,
  versionRef,
} from "./version-page";

const CLAUSE = clauseDetailFromDto({
  clause_id: EXAMPLE_CLAUSE_IDS.first,
  document_id: EXAMPLE_DOCUMENT_ID,
  clause_ref: "en.p1",
  ordinal: 1,
  page: 1,
  text: "Example clause text that opens the document.",
  regulator: "Example regulator",
  doc_type: "circular",
  external_ref: "Example 1/2000",
  title: "Example document title",
  url: "https://example.com/example-document.pdf",
  language: "en",
  published_at: "2000-01-15",
});

const RELATION: RelationDto = {
  relation_id: "00000000-0000-4000-8000-0000000000b1",
  from_rule_version_id: EXAMPLE_VERSION_ID,
  relation: "supersedes",
  to_kind: "rule_version",
  to_ref: EXAMPLE_OTHER_VERSION_ID,
  to_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
  to_entity_id: null,
  evidence_clause_id: EXAMPLE_CLAUSE_IDS.first,
  evidence_clause_ref: "en.p1",
  evidence_document_id: EXAMPLE_DOCUMENT_ID,
  candidate_id: null,
  period_label: null,
  new_due_on: null,
};

describe("the version page's links", () => {
  it("opens a clause in the document viewer, marked, and the graph around the version", () => {
    expect(clauseHref(EXAMPLE_DOCUMENT_ID, EXAMPLE_CLAUSE_IDS.first)).toBe(
      `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    );
    expect(graphHref(EXAMPLE_VERSION_ID)).toBe(
      `/admin/rulebook/relations/graph?rule_version_id=${EXAMPLE_VERSION_ID}`,
    );
  });
});

describe("citationView", () => {
  it("marks the quote in its clause when it is there word for word", () => {
    expect(markQuote("Example clause text", "clause")).toEqual({
      before: "Example ",
      mark: "clause",
      after: " text",
    });
    expect(markQuote("Example clause text", "absent")).toBeNull();
    expect(markQuote("Example clause text", "")).toBeNull();
    const view = citationView(citationFromDto(citationDto()), CLAUSE);
    expect(view.quoteMark?.mark).toBe("Example clause text that opens");
    expect(citationView(citationFromDto(citationDto()), null).quoteMark).toBeNull();
  });
});

describe("relationView", () => {
  const read = new Map([
    [
      EXAMPLE_OTHER_VERSION_ID,
      ruleVersionFromDto(
        ruleVersionDto({
          rule_version_id: EXAMPLE_OTHER_VERSION_ID,
          version: 3,
          status: "published",
        }),
      ),
    ],
  ]);

  it("names the version at the other end when it was read, and its id otherwise", () => {
    const from = relationView(relationFromDto(RELATION), "from", read);
    expect(from.version).toEqual({
      ruleVersionId: EXAMPLE_OTHER_VERSION_ID,
      href: `/admin/rulebook/versions/${EXAMPLE_OTHER_VERSION_ID}`,
      label: "example_rule v3",
      status: "published",
    });
    expect(from.entity).toBeNull();
    expect(from.evidenceHref).toContain(`clause_id=${EXAMPLE_CLAUSE_IDS.first}`);
    expect(relationView(relationFromDto(RELATION), "to", read).version?.ruleVersionId).toBe(
      EXAMPLE_VERSION_ID,
    );
    expect(versionRef(EXAMPLE_VERSION_ID, undefined)).toMatchObject({ label: null, status: null });
  });

  it("names an entity target by its type and canonical name", () => {
    const view = relationView(
      relationFromDto({
        ...RELATION,
        relation: "refers_to",
        to_kind: "form",
        to_ref: "example form",
        to_rule_version_id: null,
        to_entity_id: "00000000-0000-4000-8000-0000000000e1",
        period_label: "2000-03",
        new_due_on: "2000-04-21",
      }),
      "from",
      read,
    );
    expect(view).toMatchObject({
      version: null,
      entity: {
        entityType: "form",
        name: "example form",
        href: "/admin/rulebook/entities/canonical/00000000-0000-4000-8000-0000000000e1",
      },
      periodLabel: "2000-03",
      newDueOn: "2000-04-21",
    });
    expect(
      relationView(
        relationFromDto({
          ...RELATION,
          to_kind: "form",
          to_ref: "example form",
          to_rule_version_id: null,
        }),
        "from",
        read,
      ).entity?.href,
    ).toBeNull();
  });
});
