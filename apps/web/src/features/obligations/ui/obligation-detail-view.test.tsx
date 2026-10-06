import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { decisionFromDto } from "@/entities/applicability/mappers";
import { obligationDetailFromDto } from "@/entities/obligation/mappers";
import {
  APPROVER_IDS,
  DECISION_ID,
  NOW,
  USER_ID,
  changeDto,
  commentDto,
  decisionDto,
  obligationDetailDto,
} from "@/test/obligation-fixture";
import { obligationPageView, whyView, type WhyView } from "../model/detail";
import { ObligationDetailView } from "./obligation-detail-view";
import type { TrackingAction } from "./tracking-form";

const action: TrackingAction = vi.fn(async () => ({ status: "idle" as const }));
const HEADER = {
  crumbs: [{ id: "owner.obligation", href: "/b/x/obligations/y", label: "Example return 1" }],
  tabs: [],
};

function renderView(
  dto = obligationDetailDto(),
  why: WhyView = whyView(decisionFromDto(decisionDto()), DECISION_ID),
) {
  const view = obligationPageView(obligationDetailFromDto(dto), {
    node: "29ABCDE1234F1Z5 (Example registration)",
    clauses: new Map(),
    why,
    viewerId: USER_ID,
    now: NOW,
  });
  return render(
    <ObligationDetailView
      view={view}
      header={HEADER}
      listHref="/b/x/obligations"
      viewerId={USER_ID}
      actions={{ status: action, assign: action, comment: action }}
      keys={{
        status: "00000000-0000-4000-8000-00000000c0c1",
        assign: "00000000-0000-4000-8000-00000000c0c2",
        comment: "00000000-0000-4000-8000-00000000c0c3",
      }}
      assignee={{ mode: { kind: "id", note: "Example note on giving it by id." }, text: "Nobody" }}
    />,
  );
}

describe("ObligationDetailView", () => {
  it("shows what to do, the rule's review, its citations, why it applies and its tracking", async () => {
    const { container } = renderView(
      obligationDetailDto({
        history: [
          changeDto(),
          changeDto({
            change_id: "c2",
            kind: "started",
            status_after: "in_progress",
            actor: USER_ID,
          }),
        ],
        comments: [commentDto()],
      }),
    );
    expect(screen.getByRole("heading", { level: 1, name: "Example return 1" })).toBeDefined();
    const facts = screen.getByLabelText("The obligation");
    expect(facts.textContent).toContain("20 Jan 2000");
    expect(facts.textContent).toContain("Due in 10 days");
    expect(facts.textContent).toContain("29ABCDE1234F1Z5 (Example registration)");
    expect(screen.getByText("Example step one")).toBeDefined();
    // The seed rule is not reviewed, whatever approved its publication: both are said.
    const rule = container.querySelector("[data-slot='obligation-rule']") as HTMLElement;
    expect(within(rule).getByText("Not yet reviewed")).toBeDefined();
    expect(rule.textContent).toContain(
      "Published on 2 Jan 2000, approved for publication by 2 people:",
    );
    for (const approver of APPROVER_IDS) {
      expect(rule.querySelector(`[data-approver='${approver}']`)?.textContent).toBe(approver);
    }
    expect(screen.getByText("Example quoted clause text.")).toBeDefined();
    const why = container.querySelector("[data-slot='why-applies']") as HTMLElement;
    expect(why.textContent).toContain("with 100% confidence");
    expect(within(why).getByRole("table").textContent).toContain("Example kind is second");
    expect(screen.getByRole("button", { name: "Start work" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Mark as done" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Waive" })).toBeDefined();
    expect(screen.getByText("Example comment")).toBeDefined();
    const history = container.querySelector("[data-slot='history']") as HTMLElement;
    expect(history.textContent).toContain("Started");
    expect(history.textContent).toContain("By you");
    expect(screen.getByRole("link", { name: "All obligations of this business" })).toBeDefined();
    expect(screen.getByRole("complementary", { name: "Not legal advice" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers no status change on a closed obligation and says why nothing explains it", () => {
    renderView(
      obligationDetailDto({
        status: "done",
        closed_at: "2000-01-08T05:00:00Z",
        closed_reason: "completed",
        rule_version: null,
        citations: [],
        history: [],
      }),
      { state: "none" },
    );
    expect(screen.getByText(/This obligation is closed/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Mark as done" })).toBeNull();
    expect(screen.getByText("Completed on 8 Jan 2000")).toBeDefined();
    expect(screen.getByText(/has not kept the facts of this rule version/)).toBeDefined();
    expect(screen.getByText(/cites no verified clause/)).toBeDefined();
    expect(screen.getByText(/holds no decision of this rule/)).toBeDefined();
    expect(screen.getByText("Nothing has happened to this obligation yet.")).toBeDefined();
    expect(screen.getByText("A closed obligation keeps who it was given to.")).toBeDefined();
  });

  it("shows a decision that could not be read with its correlation id", () => {
    renderView(obligationDetailDto(), {
      state: "error",
      message: "Example engine down",
      correlationId: "req-example-1",
    });
    expect(
      screen.getByText("Why this applies could not be read from the applicability engine"),
    ).toBeDefined();
    expect(screen.getByText("req-example-1")).toBeDefined();
  });
});
