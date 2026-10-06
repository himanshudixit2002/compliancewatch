import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { reviewItemFromDto } from "@/entities/applicability/mappers";
import { ruleVersionFromDto } from "@/entities/rule-version/mappers";
import {
  REVIEWED_TENANT_ID,
  REVIEWER_ID,
  REVIEW_ITEM_ID,
  resolvedItemDto,
  reviewItemDto,
} from "@/test/engine-admin-fixture";
import { RULE_VERSION_ID } from "@/test/obligation-fixture";
import { ruleVersionDto } from "@/test/rule-version-fixture";
import { reviewItemView } from "../model/items";
import type { DecisionLookup } from "../model/lookup";
import type { DecisionsView as DecisionsViewModel } from "../queries";
import { DecisionsView, type DecisionsViewProps } from "./decisions-view";

const PAGE = "/admin/decisions";
const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.decisions", href: PAGE, label: "Decision review" },
];
const RESOLVED_ID = "00000000-0000-4000-8000-00000000f0b2";
const version = ruleVersionFromDto(
  ruleVersionDto({ rule_version_id: RULE_VERSION_ID, version: 4 }),
);
const OK: DecisionLookup = {
  kind: "ok",
  tenantId: REVIEWED_TENANT_ID,
  status: "all",
  cursor: null,
};

function viewModel(overrides: Partial<DecisionsViewModel> = {}): DecisionsViewModel {
  const options = {
    version,
    versionHref: `/admin/rulebook/versions/${RULE_VERSION_ID}`,
    viewerId: REVIEWER_ID,
  };
  return {
    tenantId: REVIEWED_TENANT_ID,
    status: "all",
    items: [
      reviewItemView(reviewItemFromDto(reviewItemDto()), options),
      reviewItemView(reviewItemFromDto(resolvedItemDto({ item_id: RESOLVED_ID })), options),
    ],
    canResolve: true,
    nextHref: `${PAGE}?tenant=${REVIEWED_TENANT_ID}&status=all&cursor=next-1`,
    firstHref: null,
    ...overrides,
  };
}

function renderView(props: Partial<DecisionsViewProps> = {}) {
  return render(
    <DecisionsView
      title="Decision review"
      crumbs={CRUMBS}
      pageHref={PAGE}
      lookup={{ kind: "empty", status: "open" }}
      view={null}
      resolve={vi.fn()}
      {...props}
    />,
  );
}

describe("DecisionsView", () => {
  it("asks for a tenant before reading anything", async () => {
    const { container } = renderView();
    expect(screen.getByRole("heading", { level: 1, name: "Decision review" })).toBeDefined();
    const form = screen.getByRole("form", { name: "Look up a tenant's review items" });
    expect(form.getAttribute("method")).toBe("get");
    expect(form.getAttribute("action")).toBe(PAGE);
    expect(screen.getByText(/Give a tenant's id/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks a malformed tenant on its field and keeps it", () => {
    renderView({
      lookup: {
        kind: "invalid",
        value: "not-a-tenant",
        error: "Enter the tenant's id, a UUID.",
        status: "open",
      },
    });
    expect(screen.getByText("Enter the tenant's id, a UUID.")).toBeDefined();
    expect((screen.getByLabelText(/^Tenant id/) as HTMLInputElement).value).toBe("not-a-tenant");
  });

  it("shows each item with its conditions, settles an open one for a reviewer, and pages on", async () => {
    const resolve = vi.fn();
    const { container } = renderView({ lookup: OK, view: viewModel(), resolve });
    expect(screen.getByText(`Tenant ${REVIEWED_TENANT_ID}, Every item`)).toBeDefined();
    const open = container.querySelector(`[data-review-item='${REVIEW_ITEM_ID}']`) as HTMLElement;
    expect(within(open).getByRole("heading", { level: 3, name: "example_rule v4" })).toBeDefined();
    expect(open.textContent).toContain("A condition in words nobody has judged");
    expect(within(open).getAllByText("Not sure, needs review")).toHaveLength(2);
    expect(within(open).getByRole("table").textContent).toContain(
      "Example condition a person judges",
    );
    expect(within(open).getByRole("button", { name: "Settle the item" })).toBeDefined();
    expect(resolve).not.toHaveBeenCalled();
    const resolved = container.querySelector(`[data-review-item='${RESOLVED_ID}']`) as HTMLElement;
    expect(resolved.textContent).toContain("It applies. Settled by you on");
    expect(resolved.textContent).toContain("Note: Example note on why it applies");
    expect(within(resolved).queryByRole("button", { name: "Settle the item" })).toBeNull();
    expect(screen.getByRole("link", { name: "Next page" }).getAttribute("href")).toContain(
      "cursor=next-1",
    );
    expect(await runAxe(open)).toHaveNoViolations();
  });

  it("is read-only for an analyst, says why a list is empty, and shows a failed read", async () => {
    const { rerender, container } = renderView({
      lookup: OK,
      view: viewModel({ canResolve: false, nextHref: null }),
    });
    expect(screen.getByText("Only a reviewer or an admin settles a review item.")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Settle the item" })).toBeNull();
    rerender(
      <DecisionsView
        title="Decision review"
        crumbs={CRUMBS}
        pageHref={PAGE}
        lookup={{ ...OK, status: "open" }}
        view={viewModel({ status: "open", items: [], nextHref: null })}
        resolve={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Nothing waits for a reviewer" }),
    ).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    rerender(
      <DecisionsView
        title="Decision review"
        crumbs={CRUMBS}
        pageHref={PAGE}
        lookup={OK}
        view={null}
        error={{ message: "Example refused", status: 403, requestId: "req-example-2" }}
        resolve={vi.fn()}
      />,
    );
    expect(screen.getByText("Example refused")).toBeDefined();
    expect(screen.getByText("req-example-2")).toBeDefined();
  });
});
