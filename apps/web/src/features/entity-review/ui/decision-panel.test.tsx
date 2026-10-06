import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { reviewItemFromDto } from "@/entities/rulebook/mappers";
import {
  EXAMPLE_ENTITY_ID,
  EXAMPLE_REVIEW_IDS,
  reviewItemDto,
  reviewItemDtos,
} from "@/test/rulebook-fixture";
import { itemRows } from "../model/group";
import { DecisionPanel, type DecideAction } from "./decision-panel";

const ITEMS = itemRows([
  reviewItemFromDto(reviewItemDto()),
  reviewItemFromDto(
    reviewItemDto({ review_id: EXAMPLE_REVIEW_IDS.second, mention_text: "Example second" }),
  ),
]);

function sentOf(formData: FormData): Record<string, string[]> {
  const sent: Record<string, string[]> = {};
  for (const [key, value] of formData.entries()) (sent[key] ??= []).push(String(value));
  return sent;
}

function renderPanel(action: DecideAction, overrides: { nameable?: boolean } = {}) {
  return render(
    <DecisionPanel
      action={action}
      items={ITEMS}
      typeLabel="Form"
      nameLabel="EXAMPLE-1"
      resolveHref="/admin/rulebook/entities/canonical?type=form&name=EXAMPLE-1"
      queueHref="/admin/rulebook/entities?type=form"
      nameable={overrides.nameable ?? true}
    />,
  );
}

describe("DecisionPanel", () => {
  it("makes the entity for the included mention after the dialog says what is recorded", async () => {
    const sent: Record<string, string[]>[] = [];
    const action = vi.fn<DecideAction>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return {
        status: "ok",
        message: "Example decided.",
        value: {
          message: "Example decided.",
          statusLabel: "Resolved",
          resolutionLabel: "A new entity was made",
          entityId: EXAMPLE_ENTITY_ID,
          entityHref: `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`,
          itemsClosed: 1,
          relationTargetsUpdated: 0,
        },
      };
    });
    const { container } = renderPanel(action);
    expect(await runAxe(container)).toHaveNoViolations();
    expect(screen.getByText(/covers every open mention of the group \(2\)/)).toBeDefined();
    const submit = screen.getByRole("button", { name: "Record the decision" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Include the mention Example clause" }));
    expect(screen.getByText("The decision covers the included mentions (1).")).toBeDefined();
    await user.click(screen.getByRole("radio", { name: "Make the entity" }));
    await user.type(screen.getByLabelText(/^Note/), "Example note");
    await user.click(submit);
    const dialog = screen.getByRole("dialog", { name: "Decide EXAMPLE-1?" });
    expect(dialog.textContent).toContain('makes the canonical Form "EXAMPLE-1"');
    expect(dialog.textContent).toContain("the included mentions (1)");
    await user.click(within(dialog).getByRole("button", { name: "Record the decision" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Example decided."),
    );
    expect(sent).toEqual([
      {
        decision: ["create_entity"],
        note: ["Example note"],
        review_ids: [EXAMPLE_REVIEW_IDS.first],
      },
    ]);
    expect(screen.getByRole("link", { name: EXAMPLE_ENTITY_ID }).getAttribute("href")).toBe(
      `/admin/rulebook/entities/canonical/${EXAMPLE_ENTITY_ID}`,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("asks for the entity to add the name to, and for a reason to reject", async () => {
    const sent: Record<string, string[]>[] = [];
    const action = vi.fn<DecideAction>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return { status: "error", fieldErrors: { entity_id: ["Example entity refused"] } };
    });
    renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Add the name to an entity" }));
    expect(
      screen.getByRole("link", { name: "See how this name resolves among the canonical entities" }),
    ).toBeDefined();
    const submit = screen.getByRole("button", { name: "Record the decision" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText(/^Entity id/), EXAMPLE_ENTITY_ID);
    await user.click(submit);
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Record the decision" }),
    );
    await waitFor(() => expect(screen.getByText("Example entity refused")).toBeDefined());
    expect(sent[0]).toEqual({
      decision: ["add_alias"],
      entity_id: [EXAMPLE_ENTITY_ID],
      note: [""],
    });

    await user.click(screen.getByRole("radio", { name: "Reject the mentions" }));
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.selectOptions(screen.getByLabelText(/^Why reject/), "wrong_type");
    await user.click(submit);
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("as rejected (Wrong entity type)");
    await user.click(within(dialog).getByRole("button", { name: "Record the decision" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toEqual({ decision: ["reject"], reject_reason: ["wrong_type"], note: [""] });
  });

  it("shows the rulebook's refusal with its correlation id", async () => {
    const action = vi.fn<DecideAction>().mockResolvedValue({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:rulebook-review-group-closed",
        title: "Example group closed",
        correlationId: "req-example-9",
      },
    });
    renderPanel(action);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Make the entity" }));
    await user.click(screen.getByRole("button", { name: "Record the decision" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Record the decision" }),
    );
    await waitFor(() => expect(screen.getByText("Example group closed")).toBeDefined());
    expect(screen.getByText("req-example-9")).toBeDefined();
  });

  it("keeps making an entity off for a name that cannot name one, and asks for mentions", async () => {
    renderPanel(vi.fn<DecideAction>(), { nameable: false });
    expect(
      (screen.getByRole("radio", { name: "Make the entity" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText(/include the mentions you decide/)).toBeDefined();
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Reject the mentions" }));
    await user.selectOptions(screen.getByLabelText(/^Why reject/), "text_artifact");
    const submit = screen.getByRole("button", { name: "Record the decision" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("checkbox", { name: "Include the mention Example second" }));
    expect((submit as HTMLButtonElement).disabled).toBe(false);
  });

  it("says a whole-group decision over the rulebook's 200 covers 200 or more", async () => {
    render(
      <DecisionPanel
        action={vi.fn<DecideAction>()}
        items={itemRows(reviewItemDtos(200).map(reviewItemFromDto))}
        typeLabel="Form"
        nameLabel="EXAMPLE-1"
        resolveHref={null}
        queueHref="/admin/rulebook/entities?type=form"
        nameable
      />,
    );
    expect(screen.getByText(/^No mention is included/).textContent).toBe(
      "No mention is included: the decision covers every open mention of the group, 200 or more (the first 200 listed).",
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Reject the mentions" }));
    await user.selectOptions(screen.getByLabelText(/^Why reject/), "out_of_scope");
    await user.click(screen.getByRole("button", { name: "Record the decision" }));
    expect(screen.getByRole("dialog").textContent).toContain(
      "closes every open mention of the group, 200 or more (the first 200 listed) as rejected",
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(
      screen.getByRole("checkbox", { name: "Include the mention Example clause 7" }),
    );
    expect(screen.getByText("The decision covers the included mentions (1).")).toBeDefined();
  });

  it("says every mention is decided once none is left", async () => {
    const { container } = render(
      <DecisionPanel
        action={vi.fn<DecideAction>()}
        items={[]}
        typeLabel="Form"
        nameLabel="EXAMPLE-1"
        resolveHref={null}
        queueHref="/admin/rulebook/entities?type=form"
        nameable
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Every mention of this group is decided" }),
    ).toBeDefined();
    expect(screen.getByRole("link", { name: "Back to the entity review queue" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
