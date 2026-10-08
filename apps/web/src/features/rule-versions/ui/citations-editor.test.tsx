import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { EXAMPLE_CLAUSE_IDS } from "@/test/rulebook-fixture";
import { CitationsEditor, type SaveCitationsAction } from "./citations-editor";
import type { CitationsResult } from "./citations-shared";

describe("CitationsEditor", () => {
  it("adds and removes rows and sends them numbered in order", async () => {
    let sent: [string, string][] = [];
    const action = vi.fn<SaveCitationsAction>(async (_state, formData) => {
      sent = [...formData.entries()].map(([key, value]) => [key, String(value)]);
      return {
        status: "ok",
        value: {
          added: 2,
          unchanged: 0,
          verified: [{ clauseRef: "en.p1", quote: "Example", verified: true, matchScore: 0.96 }],
        },
        message: "Example stored",
      } satisfies ActionState<CitationsResult>;
    });
    const { container } = render(<CitationsEditor action={action} />);
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Add a citation" }));
    await user.click(screen.getByRole("button", { name: "Add a citation" }));
    await user.click(screen.getByRole("button", { name: "Remove citation 2" }));
    const clauses = screen.getAllByLabelText(/Clause id/);
    const quotes = screen.getAllByLabelText(/^Quote/);
    expect(clauses).toHaveLength(2);
    await user.type(clauses[0] as HTMLElement, EXAMPLE_CLAUSE_IDS.first);
    await user.type(quotes[0] as HTMLElement, "Example first quote");
    await user.type(clauses[1] as HTMLElement, EXAMPLE_CLAUSE_IDS.second);
    await user.type(quotes[1] as HTMLElement, "Example second quote");
    await user.click(screen.getByRole("button", { name: "Cite and verify" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Example stored"));
    expect(sent).toEqual([
      ["citations.0.clause_id", EXAMPLE_CLAUSE_IDS.first],
      ["citations.0.quote", "Example first quote"],
      ["citations.1.clause_id", EXAMPLE_CLAUSE_IDS.second],
      ["citations.1.quote", "Example second quote"],
    ]);
    expect(screen.getByText("Clause en.p1: verified, match score 0.96")).toBeDefined();
    // A save starts the rows over.
    expect(screen.getAllByLabelText(/Clause id/)).toHaveLength(1);
    expect((screen.getByLabelText(/Clause id/) as HTMLInputElement).value).toBe("");
  });

  it("keeps the rows after a refusal, with each problem on its row and every failure listed", async () => {
    const action = vi.fn<SaveCitationsAction>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:rulebook-citation-not-verified",
        title: "Example quote not found",
        detail: "Example detail",
        correlationId: "req-example-2",
      },
      fieldErrors: { "citations.0.quote": ["Not found in its clause: score 0.40"] },
      formErrors: ["en.p1 of example: score 0.40"],
    }));
    const { container } = render(<CitationsEditor action={action} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Clause id/), EXAMPLE_CLAUSE_IDS.first);
    await user.type(screen.getByLabelText(/^Quote/), "Example quote");
    await user.click(screen.getByRole("button", { name: "Cite and verify" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("req-example-2"));
    expect(screen.getByText("Not found in its clause: score 0.40")).toBeDefined();
    expect(screen.getByText("en.p1 of example: score 0.40")).toBeDefined();
    expect((screen.getByLabelText(/^Quote/) as HTMLTextAreaElement).value).toBe("Example quote");
    await waitFor(() => expect(container.contains(document.activeElement)).toBe(true));
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("lists a form-level refusal without a problem", async () => {
    render(
      <CitationsEditor
        action={vi.fn<SaveCitationsAction>(async () => ({
          status: "error",
          formErrors: ["Example form error"],
        }))}
      />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Cite and verify" }));
    await waitFor(() => expect(screen.getByText("Correct these first:")).toBeDefined());
    expect(screen.getByText("Example form error")).toBeDefined();
  });
});
