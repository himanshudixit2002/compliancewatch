import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { documentDetailFromDto } from "@/entities/pipeline/mappers";
import { documentFromDto } from "@/entities/rulebook/mappers";
import { reviewTaskDetailFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { ReviewTaskDetailDto } from "@/entities/rule-version/types";
import { ok } from "@/server/result";
import { breadcrumbsFor } from "@/shared/config/nav";
import type { WriteAction } from "@/shared/ui/write-outcome";
import { ontologyFixture } from "@/test/ontology-fixture";
import { documentDetailDto } from "@/test/pipeline-fixture";
import { EXAMPLE_DOCUMENT_ID, documentDto } from "@/test/rulebook-fixture";
import {
  EXAMPLE_ANALYST_ID,
  EXAMPLE_OTHER_VERSION_ID,
  citationDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import {
  EXAMPLE_TASK_ID,
  candidateTaskDetailDto,
  reviewTaskDetailDto,
  reviewTaskDto,
  ruleCandidateDto,
} from "@/test/review-task-fixture";
import { workbenchView, type Session, type WorkbenchReads } from "../model/workbench";
import type { WriteResult } from "./form-shared";
import type { RuleActions } from "./rule-pane";
import { WorkbenchView } from "./workbench-view";

const SESSION: Session = { userId: EXAMPLE_ANALYST_ID, roles: ["analyst"] };

function actions(): RuleActions {
  return {
    claim: vi.fn<WriteAction<WriteResult>>(),
    draft: vi.fn<WriteAction<WriteResult>>(),
    edit: vi.fn<WriteAction<WriteResult>>(),
    decide: vi.fn<WriteAction<WriteResult>>(),
  };
}

function view(dto: ReviewTaskDetailDto, overrides: Partial<WorkbenchReads> = {}) {
  return workbenchView(
    {
      detail: reviewTaskDetailFromDto(dto),
      ontology: ok(ontologyFixture()),
      documents: new Map([[EXAMPLE_DOCUMENT_ID, ok(documentFromDto(documentDto()))]]),
      stored: new Map([
        [
          EXAMPLE_DOCUMENT_ID,
          ok(documentDetailFromDto(documentDetailDto({ document_id: EXAMPLE_DOCUMENT_ID }))),
        ],
      ]),
      ruleVersions: ok([]),
      relations: null,
      targets: null,
      ruleKeys: [],
      access: { allowed: true },
      lifecycle: { allowed: true },
      ...overrides,
    },
    SESSION,
  );
}

describe("WorkbenchView", () => {
  it("lays out a claimed seed task: its facts, the marked source, the draft, the edit form and the history", async () => {
    const previous = ruleVersionFromDto(
      ruleVersionDto({
        rule_version_id: EXAMPLE_OTHER_VERSION_ID,
        version: 1,
        status: "published",
        summary: "Example earlier summary.",
      }),
    );
    const model = view(
      reviewTaskDetailDto({
        task: reviewTaskDto({ status: "claimed", claimed_by: EXAMPLE_ANALYST_ID }),
        rule_version: ruleVersionDto({ version: 2 }),
        citations: [
          citationDto(),
          citationDto({
            citation_id: "00000000-0000-4000-8000-0000000000ca",
            quote: "Example quote the clause does not hold",
            verified: false,
            match_score: null,
            verified_at: null,
          }),
        ],
      }),
      { ruleVersions: ok([previous]) },
    );
    const { container } = render(
      <WorkbenchView
        crumbs={breadcrumbsFor("admin.review.task", { taskId: EXAMPLE_TASK_ID })}
        view={model}
        actions={actions()}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example rule title" })).toBeDefined();
    expect(container.querySelector("[data-slot='task-facts']")?.textContent).toContain(
      "Seed draft",
    );
    const file = screen.getByRole("link", { name: /Open the original file \(PDF, 20.5 KB\)/ });
    expect(file.getAttribute("href")).toBe(
      `/api-bff/pipeline/documents/${EXAMPLE_DOCUMENT_ID}/raw`,
    );
    expect(file.getAttribute("target")).toBe("_blank");
    expect(file.getAttribute("rel")).toBe("noopener");
    const cited = container.querySelector("li[data-clause-ref='en.p1']");
    expect(cited?.getAttribute("data-marked")).toBe("clause");
    expect(cited?.querySelector("[data-slot='span-unmatched']")?.textContent).toContain(
      "Example quote the clause does not hold",
    );
    expect(container.querySelectorAll("[data-citation]")).toHaveLength(2);
    expect(screen.getByText("Not verified")).toBeDefined();
    expect(container.querySelector("[data-slot='draft-content']")?.textContent).toContain(
      "example_rule v2",
    );
    expect(screen.getByRole("button", { name: "Save the draft" })).toBeDefined();
    expect(container.querySelector("[data-slot='diff-previous']")?.textContent).toContain(
      "example_rule v1 and this draft",
    );
    expect(
      container.querySelector("[data-slot='diff-previous'] [data-change='removed']")?.textContent,
    ).toContain("Example earlier summary.");
    expect(container.querySelector("[data-slot='history-audit']")?.textContent).toContain("Edited");
    expect(container.querySelector("iframe, embed, object")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lays out a candidate task with its candidate pane, and offers nothing without access", async () => {
    const model = view(
      candidateTaskDetailDto({
        candidate: ruleCandidateDto({ outcome: "unparseable", candidate: null }),
      }),
      {
        access: { allowed: false, title: "The web.admin_rulebook_writes flag is off" },
        ruleVersions: null,
      },
    );
    const { container } = render(<WorkbenchView crumbs={[]} view={model} actions={null} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Example candidate title" }),
    ).toBeDefined();
    expect(screen.getByText("There is no candidate")).toBeDefined();
    expect(container.querySelector("[data-slot='candidate-issues']")?.textContent).toContain(
      "example_issue",
    );
    expect(container.querySelector("[data-slot='high-impact-reasons']")?.textContent).toContain(
      "Example reason it looks high impact",
    );
    expect(screen.getByText("The web.admin_rulebook_writes flag is off")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Claim this task" })).toBeNull();
    expect(container.querySelector("[data-slot='diff-none']")?.textContent).toBe(
      "Nothing to compare until a version is drafted.",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
