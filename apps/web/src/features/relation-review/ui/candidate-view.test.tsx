import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { clauseDetailFromDto, relationCandidateFromDto } from "@/entities/rulebook/mappers";
import type { RelationCandidateDto } from "@/entities/rulebook/types";
import { webError } from "@/server/result";
import {
  EXAMPLE_CLAUSE_IDS,
  EXAMPLE_DOCUMENT_ID,
  EXAMPLE_ENTITY_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import { candidateFacts, evidenceOf } from "../model/candidate";
import type { CandidatePage } from "../queries";
import type { CandidateAction } from "./candidate-decisions";
import { CandidateView } from "./candidate-view";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  {
    id: "admin.rulebook.relations",
    href: "/admin/rulebook/relations",
    label: "Relation candidates",
  },
  {
    id: "admin.rulebook.relation",
    href: "/admin/rulebook/relations/x",
    label: "Relation candidate",
  },
];

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
  url: "https://example.com/example.pdf",
  language: "en",
  published_at: null,
});

function pageOf(
  overrides: Partial<RelationCandidateDto> = {},
  extra: Partial<CandidatePage> = {},
): CandidatePage {
  const candidate = relationCandidateFromDto(relationCandidateDto(overrides));
  return {
    facts: candidateFacts(candidate),
    evidence: evidenceOf(candidate, CLAUSE),
    evidenceError: null,
    access: { allowed: true },
    needsTarget: true,
    options: { from: [], target: [] },
    optionsError: null,
    ...extra,
  };
}

describe("CandidateView", () => {
  it("shows the candidate, its flags and the quote marked in its clause, with the decisions", async () => {
    const { container } = render(
      <CandidateView
        title="Relation candidate"
        crumbs={crumbs}
        page={pageOf()}
        approve={vi.fn<CandidateAction>()}
        reject={vi.fn<CandidateAction>()}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Relation candidate" })).toBeDefined();
    expect(screen.getByText("Extends deadline: Form EXAMPLE-1")).toBeDefined();
    expect(screen.getByText("The pipeline flagged this candidate")).toBeDefined();
    expect(screen.getByText("Target unaligned: Example detail")).toBeDefined();
    expect(container.querySelector("mark")?.textContent).toBe("clause text that opens");
    expect(
      screen.getByRole("link", { name: "Align it in the entity review" }).getAttribute("href"),
    ).toBe("/admin/rulebook/entities/group?type=form&name=EXAMPLE-1");
    expect(screen.getByRole("heading", { level: 2, name: "Approve" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Reject" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("names what holds the decision back for an open candidate", () => {
    render(
      <CandidateView
        title="Relation candidate"
        crumbs={crumbs}
        page={pageOf(
          {},
          { access: { allowed: false, title: "Example token missing" }, options: null },
        )}
        approve={null}
        reject={null}
      />,
    );
    expect(screen.getByText("Example token missing")).toBeDefined();
    expect(screen.queryByRole("heading", { name: "Approve" })).toBeNull();
  });

  it("shows who decided a closed candidate, and the quote alone when the clause failed", async () => {
    const { container } = render(
      <CandidateView
        title="Relation candidate"
        crumbs={crumbs}
        page={pageOf(
          {
            status: "rejected",
            reject_reason: "wrong_target",
            decided_by: "example-user",
            target_entity_id: EXAMPLE_ENTITY_ID,
            needs_review: false,
            issues: [],
          },
          {
            access: { allowed: false, title: "Example flag off" },
            evidence: evidenceOf(relationCandidateFromDto(relationCandidateDto()), null),
            evidenceError: webError("unavailable", "web-example", "Example clause outage"),
            options: null,
          },
        )}
        approve={null}
        reject={null}
      />,
    );
    expect(screen.getByText("Wrong target")).toBeDefined();
    expect(screen.getByText("example-user")).toBeDefined();
    expect(
      screen.getByRole("link", { name: `Aligned to entity ${EXAMPLE_ENTITY_ID}` }),
    ).toBeDefined();
    expect(
      screen.getByText("This candidate is Rejected: it takes no further decision."),
    ).toBeDefined();
    expect(screen.getByText("Example clause outage")).toBeDefined();
    expect(container.querySelector("blockquote")?.textContent).toBe("clause text that opens");
    expect(screen.queryByText("The pipeline flagged this candidate")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
