import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { attributeOf } from "@/entities/ontology/mappers";
import type { OntologyAttribute } from "@/entities/ontology/types";
import type { ActionState } from "@/shared/lib/action-state";
import { ontologyFixture } from "@/test/ontology-fixture";
import { AnswerForm } from "./answer-form";

const ONTOLOGY = ontologyFixture();
const KIND = attributeOf(ONTOLOGY, "example_kind") as OntologyAttribute;
const HIDDEN = { business_id: "b-1", node_id: "n-1", key: "example_kind", as_of_fy: "" };

describe("AnswerForm", () => {
  it("draws the attribute's control with the hidden fields and the three answers", async () => {
    const { container } = render(
      <main>
        <h1>Example question?</h1>
        <AnswerForm
          action={vi.fn(async (): Promise<ActionState> => ({ status: "idle" }))}
          attribute={KIND}
          id="q"
          label="Example question?"
          hideLabel
          description="Example help line."
          hidden={HIDDEN}
          valueField="value"
        />
      </main>,
    );
    expect(screen.getByRole("radiogroup", { name: "Example question?" })).toBeDefined();
    expect(screen.getByText("Example help line.")).toBeDefined();
    const hidden = [...container.querySelectorAll<HTMLInputElement>("input[type='hidden']")];
    expect(
      hidden.filter((input) => input.name in HIDDEN).map((input) => [input.name, input.value]),
    ).toEqual(Object.entries(HIDDEN));
    for (const name of ["Save", "Not sure", "Does not apply"]) {
      expect(screen.getByRole("button", { name })).toBeDefined();
    }
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("sends the chosen value with the pressed state and keeps it after a refusal", async () => {
    const user = userEvent.setup();
    let submitted: FormData | undefined;
    const action = vi.fn(async (_state: ActionState, formData: FormData): Promise<ActionState> => {
      submitted = formData;
      return { status: "error", fieldErrors: { value: ["Example value message."] } };
    });
    const { container } = render(
      <AnswerForm
        action={action}
        attribute={KIND}
        id="q"
        label="Example question?"
        hidden={HIDDEN}
        valueField="value"
      />,
    );
    await user.click(screen.getByRole("radio", { name: "Example second kind" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("Example value message.")).toBeDefined());
    expect(submitted?.get("state")).toBe("known");
    expect(submitted?.get("value")).toBe("second");
    expect(submitted?.get("node_id")).toBe("n-1");
    expect(
      screen.getByRole("radio", { name: "Example second kind" }).getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.getByText("Check the answer marked below.")).toBeDefined();
    expect(document.activeElement?.getAttribute("data-slot")).toBe("answer-errors");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("shows the service's problem and the form's errors", async () => {
    const user = userEvent.setup();
    render(
      <AnswerForm
        action={async (): Promise<ActionState> => ({
          status: "error",
          problem: { type: "urn:x", title: "Example problem", correlationId: "req-example-2" },
          formErrors: ["Example form message."],
        })}
        attribute={KIND}
        id="q"
        label="Example question?"
        hidden={HIDDEN}
        valueField="value"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Not sure" }));
    await waitFor(() => expect(screen.getByText("Example problem")).toBeDefined());
    expect(screen.getByText("req-example-2")).toBeDefined();
    expect(screen.getByText("Example form message.")).toBeDefined();
  });

  it("shows only the problem when there is nothing else to say", async () => {
    const user = userEvent.setup();
    render(
      <AnswerForm
        action={async (): Promise<ActionState> => ({
          status: "error",
          problem: { type: "urn:x", title: "Example lone problem" },
        })}
        attribute={KIND}
        id="q"
        label="Example question?"
        hidden={HIDDEN}
        valueField="value"
      />,
    );
    await user.click(screen.getByRole("button", { name: "Not sure" }));
    await waitFor(() => expect(screen.getByText("Example lone problem")).toBeDefined());
    expect(screen.queryByText("The answer was not saved")).toBeNull();
  });

  it("announces a saved answer and starts from the stored value", async () => {
    const user = userEvent.setup();
    render(
      <AnswerForm
        action={async (): Promise<ActionState> => ({ status: "ok", message: "Example saved." })}
        attribute={KIND}
        id="q"
        label="Example question?"
        hidden={HIDDEN}
        valueField="value"
        defaultValue="first"
        valueOnly
      />,
    );
    expect(
      screen.getByRole("radio", { name: "Example first kind" }).getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.queryByRole("button", { name: "Not sure" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save" }));
    // The status line is mounted empty from the start, so wait for its text, not for the node.
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example saved."));
  });

  it("has its status line in place before the action runs and puts the message in that node", async () => {
    const user = userEvent.setup();
    const action = vi.fn(async (): Promise<ActionState> => ({
      status: "ok",
      message: "Example saved.",
    }));
    render(
      <AnswerForm
        action={action}
        attribute={KIND}
        id="q"
        label="Example question?"
        hidden={HIDDEN}
        valueField="value"
        defaultValue="first"
        valueOnly
      />,
    );
    // A live region announces a change to its text, not a region inserted with its text.
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");
    expect(action).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(status.textContent).toBe("Example saved."));
    expect(screen.getByRole("status")).toBe(status);
  });
});
