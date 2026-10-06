import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { changeImpactFromDto } from "@/entities/applicability/mappers";
import { businessFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO } from "@/test/business-fixture";
import { CHANGED_VERSION_ID, changeImpactDto } from "@/test/change-fixture";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import { clientRows } from "../model/impact";
import type { ChangeImpactView as ChangeImpactViewModel } from "../queries";
import type { BulkAction } from "./bulk-panel";
import { ChangeImpactView } from "./change-impact-view";

const PAGE = `/changes/${CHANGED_VERSION_ID}/impact`;
const CRUMBS = [
  { id: "owner.businesses", href: "/businesses", label: "Businesses" },
  { id: "ca.change-impact", href: PAGE, label: "Affected clients" },
];

function viewModel(overrides: Partial<ChangeImpactViewModel> = {}): ChangeImpactViewModel {
  const impact = changeImpactFromDto(
    changeImpactDto([{ result: "applies" }, { businessId: ENTITY_ID, result: "unsure" }]),
  );
  return {
    ruleVersionId: CHANGED_VERSION_ID,
    name: "example_rule v2",
    title: "Example rule 2",
    status: "Published",
    counts: { applies: "1", unsure: "1", notApplicable: "4", total: "6" },
    fanOut: "Its fan-out over every business of its level is complete: 6 of 6 decided.",
    filter: "applies",
    clients: clientRows(impact, new Map([[ENTITY_ID, businessFromDto(BUSINESS_DTO)]])),
    nextHref: `${PAGE}?cursor=page-2`,
    firstHref: null,
    targets: [{ businessId: REGISTRATION_ID, label: "Example business: GSTIN example" }],
    targetsCut: false,
    ...overrides,
  };
}

function renderView(view: ChangeImpactViewModel) {
  return render(
    <ChangeImpactView
      title="Affected clients"
      crumbs={CRUMBS}
      pageHref={PAGE}
      view={view}
      sendAction={vi.fn<BulkAction>()}
      idempotencyInput={<input type="hidden" name="idempotency_key" value="example" />}
    />,
  );
}

describe("ChangeImpactView", () => {
  it("shows the change, its counts, the fan-out, the clients by result and the bulk card", async () => {
    const { container } = renderView(viewModel());
    expect(screen.getByRole("heading", { level: 1, name: "Affected clients" })).toBeDefined();
    expect(
      screen.getByText("Which of your clients example_rule v2 affects: Example rule 2"),
    ).toBeDefined();
    expect(container.querySelector("[data-slot='change-facts']")?.textContent).toContain(
      "example_rule v2 is Published. Its fan-out over every business of its level is complete",
    );
    expect(container.querySelector("[data-count='not_applicable']")?.textContent).toContain("4");
    const filters = screen.getByRole("navigation", { name: "Show clients by result" });
    expect(
      within(filters).getByRole("link", { name: "Affected" }).getAttribute("aria-current"),
    ).toBe("true");
    expect(within(filters).getByRole("link", { name: "Every client" }).getAttribute("href")).toBe(
      `${PAGE}?result=all`,
    );
    const table = screen.getByRole("table");
    const client = table.querySelector(`tbody[data-client='${ENTITY_ID}']`) as HTMLElement;
    expect(within(client).getByRole("rowheader").textContent).toBe("Example business (ABCDE1234F)");
    expect(
      client.querySelector(`[data-business='${REGISTRATION_ID}']`)?.getAttribute("data-result"),
    ).toBe("applies");
    expect(within(client).getByText("Not sure, needs review")).toBeDefined();
    expect(screen.getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      `${PAGE}?cursor=page-2`,
    );
    expect(
      screen.getByRole("button", { name: "Send the change card to 1 affected business" }),
    ).toBeDefined();
    expect(screen.getByRole("complementary", { name: "Not legal advice" })).toBeDefined();
    expect(await runAxe(table)).toHaveNoViolations();
  });

  it("says why a list is empty, by its filter, and the end of a later page", async () => {
    const { rerender, container } = renderView(
      viewModel({ clients: [], nextHref: null, targets: [], filter: "applies" }),
    );
    expect(screen.getByRole("heading", { level: 2, name: "No client is affected" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    for (const [filter, heading] of [
      ["unsure", "No client is in doubt"],
      ["not_applicable", "No client is ruled out"],
      ["all", "No client has a decision of this change"],
    ] as const) {
      rerender(
        <ChangeImpactView
          title="Affected clients"
          crumbs={CRUMBS}
          pageHref={PAGE}
          view={viewModel({ clients: [], nextHref: null, targets: [], filter })}
          sendAction={vi.fn<BulkAction>()}
          idempotencyInput={null}
        />,
      );
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeDefined();
    }
    rerender(
      <ChangeImpactView
        title="Affected clients"
        crumbs={CRUMBS}
        pageHref={PAGE}
        view={viewModel({ clients: [], nextHref: null, firstHref: PAGE })}
        sendAction={vi.fn<BulkAction>()}
        idempotencyInput={null}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No more clients" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Back to the first page" }).getAttribute("href")).toBe(
      PAGE,
    );
  });
});
