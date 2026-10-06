import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { answerFromDto } from "@/entities/answer/mappers";
import { answerDto, notCoveredDto } from "@/test/answer-fixture";
import { answerView } from "../model/ask";
import type { AskPageView } from "../queries";
import type { AskAction } from "./ask-form";
import { ASK_FIELDS } from "./answer-shared";
import { AskView } from "./ask-view";

const HEADER = { crumbs: [{ id: "owner.ask", href: "/b/x/ask", label: "Ask" }], tabs: [] };
const PAGE: AskPageView = {
  business: {
    id: "00000000-0000-4000-8000-0000000000e1",
    name: "Example business",
    pan: "ABCDE1234F",
  },
  enabled: true,
  nodes: [
    { id: "00000000-0000-4000-8000-0000000000a1", label: "29ABCDE1234F1Z5 (Example registration)" },
    { id: "00000000-0000-4000-8000-0000000000e1", label: "Example business (PAN ABCDE1234F)" },
  ],
};

describe("AskView", () => {
  it("asks about the chosen node and shows the cited answer with its layer", async () => {
    const sent: FormData[] = [];
    const action = vi.fn<AskAction>(async (_state, formData) => {
      sent.push(formData);
      return {
        status: "ok",
        value: answerView(answerFromDto(answerDto()), {
          question: String(formData.get(ASK_FIELDS.question)),
          about: "29ABCDE1234F1Z5 (Example registration)",
          documents: new Map(),
        }),
      };
    });
    const { container } = render(
      <AskView title="Ask" view={PAGE} header={HEADER} action={action} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Ask" })).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Your question/), "Example question?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    const answer = await screen.findByText("Example answer: due on 20 Jan 2000.");
    expect(answer).toBeDefined();
    expect(sent[0]?.get(ASK_FIELDS.node)).toBe("00000000-0000-4000-8000-0000000000a1");
    expect(sent[0]?.get(ASK_FIELDS.businessId)).toBe(PAGE.business.id);
    expect(screen.getByText("Answered from this business's obligations")).toBeDefined();
    expect(screen.getByText("Example quoted clause text.")).toBeDefined();
    // The question stays in its field after the answer.
    expect((screen.getByLabelText(/Your question/) as HTMLTextAreaElement).value).toBe(
      "Example question?",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows a question that is not covered honestly, and a refusal with its problem", async () => {
    let calls = 0;
    const action = vi.fn<AskAction>(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: "ok",
          value: answerView(answerFromDto(notCoveredDto()), {
            question: "Example question?",
            about: "x",
            documents: new Map(),
          }),
        };
      }
      return {
        status: "error",
        problem: { type: "urn:x", title: "Example budget used up", correlationId: "req-example-7" },
        formErrors: ["Example form error"],
        fieldErrors: { [ASK_FIELDS.question]: ["Example field error"] },
      };
    });
    render(<AskView title="Ask" view={PAGE} header={HEADER} action={action} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Your question/), "Example question?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Not covered")).toBeDefined();
    expect(screen.getByText("Why: no clause in force says enough to answer it")).toBeDefined();
    expect(screen.getByText("This answer cites no clause.")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByText("Example budget used up")).toBeDefined());
    expect(screen.getByText("req-example-7")).toBeDefined();
    expect(screen.getByText("Example form error")).toBeDefined();
    expect(screen.getByText("Example field error")).toBeDefined();
  });

  it("says asking is off and offers no form", () => {
    render(
      <AskView title="Ask" view={{ ...PAGE, enabled: false }} header={HEADER} action={vi.fn()} />,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: "Asking questions is not switched on" }),
    ).toBeDefined();
    expect(screen.queryByRole("form")).toBeNull();
  });
});
