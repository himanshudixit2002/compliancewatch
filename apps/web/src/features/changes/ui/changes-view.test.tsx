import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { impactBusinessFromDto } from "@/entities/applicability/mappers";
import { ruleChangeFromDto } from "@/entities/change/mappers";
import { changeImpactDto, ruleChangeDto } from "@/test/change-fixture";
import { APPROVER_IDS } from "@/test/obligation-fixture";
import { applicabilityView, changeCard } from "../model/changes";
import type { ChangesView as ChangesViewModel } from "../queries";
import { ChangesView } from "./changes-view";

const HEADER = {
  crumbs: [{ id: "owner.changes", href: "/b/x/changes", label: "Changes" }],
  tabs: [],
};

function model(overrides: Partial<ChangesViewModel> = {}): ChangesViewModel {
  const applies = applicabilityView(
    {
      state: "read",
      businesses: changeImpactDto([{ result: "applies" }]).items[0]!.businesses.map(
        impactBusinessFromDto,
      ),
    },
    () => "29ABCDE1234F1Z5 (Example registration)",
  );
  return {
    business: { id: "x", name: "Example business", pan: "ABCDE1234F" },
    cards: [
      changeCard(ruleChangeFromDto(ruleChangeDto()), {
        clauses: new Map(),
        applicability: applies,
      }),
      changeCard(
        ruleChangeFromDto(
          ruleChangeDto({
            change_id: "00000000-0000-4000-8000-00000000c0c2",
            title: "Example rule 3",
            kind: "deadline_changed",
            seed_status: "reviewed",
            approved_by: [],
            deadline: {
              period_label: "2000-01",
              new_due_on: "2000-02-25",
              evidence_clause_id: null,
            },
          }),
        ),
        {
          clauses: new Map(),
          applicability: applicabilityView(
            { state: "failed", message: "Example engine down", correlationId: "req-example-6" },
            (id) => id,
          ),
        },
      ),
    ],
    nextHref: "/b/x/changes?cursor=next",
    firstHref: null,
    ...overrides,
  };
}

describe("ChangesView", () => {
  it("shows each change with what happened, whether it applies, its review and citations", async () => {
    const { container } = render(<ChangesView title="Changes" view={model()} header={HEADER} />);
    expect(screen.getByRole("heading", { level: 1, name: "Changes" })).toBeDefined();
    const published = screen.getByRole("article", { name: "Example rule 2" });
    expect(published.getAttribute("data-applicability")).toBe("applies");
    expect(within(published).getByText("Applies to this business")).toBeDefined();
    expect(published.textContent).toContain("29ABCDE1234F1Z5 (Example registration): applies");
    expect(within(published).getByText("Not yet reviewed")).toBeDefined();
    expect(published.textContent).toContain(
      "Published on 5 Jan 2000, approved for publication by 2 people:",
    );
    expect(published.querySelector(`[data-approver='${APPROVER_IDS[0]}']`)).not.toBeNull();
    expect(within(published).getByText("1 citation")).toBeDefined();
    expect(published.textContent).toContain("Example quoted clause text.");
    const moved = container.querySelector(
      "[data-change='00000000-0000-4000-8000-00000000c0c2']",
    ) as HTMLElement;
    expect(moved.textContent).toContain("Due date for the period 2000-01 moved to 25 Feb 2000.");
    expect(moved.textContent).toContain("Could not be read");
    expect(moved.textContent).toContain("req-example-6");
    expect(moved.textContent).toContain("names no approvers");
    expect(within(moved).queryByText("Not yet reviewed")).toBeNull();
    expect(screen.getByRole("link", { name: "Older changes" }).getAttribute("href")).toBe(
      "/b/x/changes?cursor=next",
    );
    expect(screen.getByRole("complementary", { name: "Not legal advice" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when nothing is published yet, and when a later page is past the end", () => {
    const first = render(
      <ChangesView title="Changes" view={model({ cards: [], nextHref: null })} header={HEADER} />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "No published changes yet" }),
    ).toBeDefined();
    expect(screen.queryByRole("navigation", { name: "Pages of the changes" })).toBeNull();
    first.unmount();
    render(
      <ChangesView
        title="Changes"
        view={model({ cards: [], nextHref: null, firstHref: "/b/x/changes" })}
        header={HEADER}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No older changes" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Back to the newest changes" })).toBeDefined();
  });
});
