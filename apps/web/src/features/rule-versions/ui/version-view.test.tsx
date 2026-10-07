import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { clauseDetailFromDto, relationFromDto } from "@/entities/rulebook/mappers";
import { citationFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import { ontologyFixture } from "@/test/ontology-fixture";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  citationDto,
  ruleVersionDetailDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import { describeSpecification } from "@/shared/ui/specification";
import { citationView, graphHref, relationView, type VersionPageView } from "../model/version-page";
import type { SaveCitationsAction } from "./citations-editor";
import { VersionView } from "./version-view";
import type { TakeStepAction } from "./workflow-panel";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.versions", href: "/admin/rulebook/versions", label: "Rule versions" },
  {
    id: "admin.rulebook.version",
    href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
    label: "example_rule v1",
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

const OTHER = ruleVersionFromDto(
  ruleVersionDto({ rule_version_id: EXAMPLE_OTHER_VERSION_ID, version: 2, status: "published" }),
);

function pageView(overrides: Partial<VersionPageView> = {}): VersionPageView {
  const version = ruleVersionFromDto(ruleVersionDto());
  const relation = relationFromDto({
    relation_id: "00000000-0000-4000-8000-0000000000b1",
    from_rule_version_id: EXAMPLE_VERSION_ID,
    relation: "extends_deadline",
    to_kind: "rule_version",
    to_ref: EXAMPLE_OTHER_VERSION_ID,
    to_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
    to_entity_id: null,
    evidence_clause_id: EXAMPLE_CLAUSE_IDS.first,
    evidence_clause_ref: "en.p1",
    evidence_document_id: EXAMPLE_DOCUMENT_ID,
    candidate_id: null,
    period_label: "2000-03",
    new_due_on: "2000-04-21",
  });
  return {
    version,
    specification:
      version.specification === null
        ? null
        : describeSpecification(version.specification, ontologyFixture()),
    ontologyError: null,
    citations: { ok: true, value: [citationView(citationFromDto(citationDto()), CLAUSE)] },
    relations: {
      ok: true,
      value: {
        from: [relationView(relation, "from", new Map([[EXAMPLE_OTHER_VERSION_ID, OTHER]]))],
        to: [],
      },
    },
    steps: ["submit"],
    access: { allowed: true },
    canCite: true,
    graphHref: graphHref(EXAMPLE_VERSION_ID),
    ...overrides,
  };
}

function renderView(view: VersionPageView) {
  return render(
    <VersionView
      view={view}
      crumbs={CRUMBS}
      citeAction={vi.fn<SaveCitationsAction>()}
      stepAction={vi.fn<TakeStepAction>()}
      sessionUserId={EXAMPLE_ANALYST_ID}
      sessionName="Example analyst"
    />,
  );
}

describe("VersionView", () => {
  it("shows a draft with the not-reviewed warning, its facts, condition, obligation and source", async () => {
    const { container } = renderView(pageView());
    expect(screen.getByRole("heading", { level: 1, name: "Example rule title" })).toBeDefined();
    expect(screen.getAllByText("Not yet reviewed").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/No analyst has completed a review round/)).toBeDefined();
    const facts = container.querySelector('[data-slot="version-facts"]') as HTMLElement;
    expect(within(facts).getByText("example_rule")).toBeDefined();
    expect(within(facts).getByText("1 Apr 2000")).toBeDefined();
    expect(within(facts).getByText("open-ended")).toBeDefined();
    expect(within(facts).getByText("No: publishing needs one approver")).toBeDefined();
    expect(screen.getByText("is Example first kind")).toBeDefined();
    expect(screen.getByText("Not in the ontology")).toBeDefined();
    expect(screen.getByText("Needs judgement: Example condition an analyst judges.")).toBeDefined();
    expect(screen.getByText("Example obligation")).toBeDefined();
    expect(screen.getByText("Monthly, due on day 20, month offset 0")).toBeDefined();
    expect(screen.getByText("Example evidence")).toBeDefined();
    expect(screen.getByText("Example instrument, 2000")).toBeDefined();
    expect(screen.getByText("Example question for the analyst?")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("names the approvers of the round a published version came from, on a fresh visit", () => {
    const published = ruleVersionFromDto(
      ruleVersionDetailDto({
        status: "published",
        published_at: "2000-05-02T06:00:00Z",
        approved_by: [EXAMPLE_ANALYST_ID],
      }),
    );
    const { container } = renderView(pageView({ version: published }));
    const approvers = container.querySelector('[data-slot="published-approvers"]') as HTMLElement;
    expect(within(approvers).getByText(EXAMPLE_ANALYST_ID)).toBeDefined();
    const draft = renderView(pageView()).container;
    const facts = draft.querySelector('[data-slot="version-facts"]') as HTMLElement;
    expect(within(facts).getByText("No approvers until it is published")).toBeDefined();
  });

  it("lists the citations with their verification and the clause, and offers the form for a draft", () => {
    const { container } = renderView(pageView());
    const table = container.querySelector('[data-slot="citations-table"]') as HTMLElement;
    expect(within(table).getByRole("link", { name: "Clause en.p1" }).getAttribute("href")).toBe(
      `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    );
    expect(within(table).getByText("Verified")).toBeDefined();
    expect(within(table).getByText("Match score 0.97")).toBeDefined();
    expect(table.querySelector("mark")?.textContent).toBe("Example clause text that opens");
    expect(screen.getByRole("form", { name: "Cite clauses" })).toBeDefined();
  });

  it("lists the relations with the version at the other end and the way to the graph", () => {
    const { container } = renderView(pageView());
    const relations = container.querySelector('[data-slot="relations-table"]') as HTMLElement;
    expect(within(relations).getByText("Extends deadline")).toBeDefined();
    expect(within(relations).getByText("Period 2000-03, due 21 Apr 2000")).toBeDefined();
    expect(within(relations).getByRole("link", { name: "example_rule v2" })).toBeDefined();
    expect(screen.getByText("No version states a relation to this one.")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Open the relations graph" }).getAttribute("href"),
    ).toBe(`/admin/rulebook/relations/graph?rule_version_id=${EXAMPLE_VERSION_ID}`);
    expect(screen.getByRole("button", { name: "Submit for review" })).toBeDefined();
  });

  it("shows a reviewed, published version without the warning or the citation form", async () => {
    const version = ruleVersionFromDto(
      ruleVersionDto({
        status: "published",
        seed_status: "reviewed",
        published_at: "2000-05-02T06:00:00Z",
        effective_to: "2001-04-01",
        high_impact: true,
        todo: [],
        recurrence: null,
        obligation_template: { title: "Example one-off", steps: [], due_in_days: 30 },
        source: { instrument: "Example", reference: "", url: "https://example.com/source" },
        specification: {},
      }),
    );
    const { container } = renderView(
      pageView({
        version,
        specification: null,
        citations: { ok: true, value: [] },
        relations: {
          ok: false,
          error: { message: "Example relations failure", requestId: "req-r" },
        },
        steps: ["withdraw"],
        canCite: false,
        ontologyError: { message: "Example ontology failure", requestId: "req-o" },
      }),
    );
    expect(screen.queryByText(/No analyst has completed a review round/)).toBeNull();
    expect(screen.getByText("Reviewed")).toBeDefined();
    expect(screen.getByText("Yes: publishing needs two different approvers")).toBeDefined();
    expect(screen.getByText("The version states no condition yet.")).toBeDefined();
    expect(screen.getByText("30 days after the event that triggers it")).toBeDefined();
    expect(screen.getByText("The version carries no open question.")).toBeDefined();
    expect(screen.getByRole("heading", { name: "No clause cited yet" })).toBeDefined();
    expect(screen.getByText(/Citations are added only while the version is a draft/)).toBeDefined();
    expect(screen.queryByRole("form", { name: "Cite clauses" })).toBeNull();
    expect(screen.getByText(/The ontology could not be read/)).toBeDefined();
    expect(screen.getByText("Example relations failure")).toBeDefined();
    expect(screen.getByRole("link", { name: /example.com\/source/ }).getAttribute("target")).toBe(
      "_blank",
    );
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("holds citing back with the refusal, and says when a clause could not be read", () => {
    renderView(
      pageView({
        access: { allowed: false, title: "Example flag is off", flag: "web.publish_actions" },
        citations: { ok: true, value: [citationView(citationFromDto(citationDto()), null)] },
      }),
    );
    expect(screen.getByText("Citing is held back")).toBeDefined();
    expect(screen.getAllByText("Example flag is off")).toHaveLength(2);
    expect(screen.getByText("The clause could not be read.")).toBeDefined();
  });

  it("shows a failed citation read with its correlation id", () => {
    renderView(
      pageView({
        citations: {
          ok: false,
          error: { message: "Example citations failure", requestId: "req-c" },
        },
      }),
    );
    expect(screen.getByText("Example citations failure")).toBeDefined();
  });
});
