import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import {
  WriteOutcome,
  idempotencyKeyFor,
  useWriteAction,
  type WriteAction,
  type WriteAttempt,
} from "./write-outcome";

interface Result {
  message: string;
}

/** A panel with one button that sends a request through the hook and shows the outcome. */
function Panel({
  action,
  resendable,
  renderValue,
}: {
  action: WriteAction<Result>;
  resendable?: (type: string) => boolean;
  renderValue?: (value: Result, message: string) => string;
}) {
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          const formData = new FormData();
          formData.set("reason", "Example reason");
          send(formData);
        }}
      >
        Send
      </button>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="example-outcome"
        fieldNames={["reason"]}
        resendable={resendable}
        renderValue={renderValue}
      />
    </div>
  );
}

describe("useWriteAction and WriteOutcome", () => {
  it("announces a success where focus lands", async () => {
    const action = vi.fn<WriteAction<Result>>(async () => ({
      status: "ok",
      value: { message: "Example done." },
      message: "Example done.",
    }));
    const { container } = render(<Panel action={action} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example done."));
    expect(document.activeElement?.getAttribute("data-slot")).toBe("example-outcome");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders a success its own way when asked", async () => {
    const action = vi.fn<WriteAction<Result>>(async () => ({
      status: "ok",
      value: { message: "Example done." },
      message: "Example announced.",
    }));
    render(
      <Panel action={action} renderValue={(value, message) => `${value.message} / ${message}`} />,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Example done. / Example announced."),
    );
  });

  it("shows a refusal with its id, the form's messages but not the fields', and sends it again when it may", async () => {
    const answers: ActionState<Result>[] = [
      {
        status: "error",
        problem: {
          type: "urn:compliancewatch:problem:example-unavailable",
          title: "Example service did not answer",
          correlationId: "req-example-1",
        },
        formErrors: ["Example form message"],
        fieldErrors: { reason: ["Example field message"], other: ["Example other message"] },
      },
      { status: "ok", value: { message: "Example done." }, message: "Example done." },
    ];
    const sent: string[] = [];
    const action = vi.fn<WriteAction<Result>>(async (_state, formData) => {
      sent.push(String(formData.get("reason")));
      return answers.shift() ?? { status: "idle" };
    });
    const { container } = render(
      <Panel action={action} resendable={(type) => type.endsWith("example-unavailable")} />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText("Example service did not answer")).toBeDefined());
    expect(screen.getByText("req-example-1")).toBeDefined();
    expect(screen.getByText("Example form message")).toBeDefined();
    expect(screen.getByText("Example other message")).toBeDefined();
    expect(screen.queryByText("Example field message")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Send the same request again" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example done."));
    expect(sent).toEqual(["Example reason", "Example reason"]);
  });

  it("keeps a request whose answer never came and sends exactly it again", async () => {
    let calls = 0;
    const action = vi.fn<WriteAction<Result>>(async () => {
      calls += 1;
      if (calls === 1) throw new TypeError("Example connection dropped");
      return { status: "ok", value: { message: "Example done." }, message: "Example done." };
    });
    render(<Panel action={action} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText("No answer came back")).toBeDefined());
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Example done."));
    expect(action.mock.calls[1]?.[1]).toBe(action.mock.calls[0]?.[1]);
  });

  it("lets a redirect from the framework through", async () => {
    const redirect = Object.assign(new Error("NEXT_REDIRECT"), {
      digest: "NEXT_REDIRECT;replace;/sign-in",
    });
    const action = vi.fn<WriteAction<Result>>(async () => {
      throw redirect;
    });
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    class Boundary extends (await import("react")).Component<
      { children: React.ReactNode },
      { failed: boolean }
    > {
      override state = { failed: false };
      static getDerivedStateFromError() {
        return { failed: true };
      }
      override render() {
        return this.state.failed ? <p>Example boundary</p> : this.props.children;
      }
    }
    render(
      <Boundary>
        <Panel action={action} />
      </Boundary>,
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText("Example boundary")).toBeDefined());
    errors.mockRestore();
  });
});

describe("idempotencyKeyFor", () => {
  const RENDERED = "00000000-0000-4000-8000-0000000000b2";
  const SENT = "00000000-0000-4000-8000-0000000000b1";
  const unavailable = "urn:compliancewatch:problem:example-unavailable";
  const resendable = (type: string) => type === unavailable;

  function sentWith(key: string | null): FormData {
    const formData = new FormData();
    formData.set("reason", "Example reason");
    if (key !== null) formData.set("idempotency_key", key);
    return formData;
  }

  function attempt(
    last: ActionState<Result>,
    sent: FormData | null = sentWith(SENT),
    lost: FormData | null = null,
  ): WriteAttempt<Result> {
    return { last, sent, lost, count: sent === null ? 0 : 1 };
  }

  it("keeps the key of a request the service recorded but asks to send again", () => {
    const refused = attempt({
      status: "error",
      problem: { type: unavailable, title: "Example service did not answer" },
    });
    expect(idempotencyKeyFor(refused, RENDERED, resendable)).toBe(SENT);
  });

  it("keeps the key of a request whose answer never came", () => {
    const lost = attempt({ status: "idle" }, sentWith(SENT), sentWith(SENT));
    expect(idempotencyKeyFor(lost, RENDERED, resendable)).toBe(SENT);
  });

  it("takes the latest render's key once an answer settles the request, or before any", () => {
    expect(idempotencyKeyFor(attempt({ status: "idle" }, null), RENDERED, resendable)).toBe(
      RENDERED,
    );
    const done = attempt({ status: "ok", value: { message: "Example done." } });
    expect(idempotencyKeyFor(done, RENDERED, resendable)).toBe(RENDERED);
    const refused = attempt({
      status: "error",
      problem: { type: "urn:compliancewatch:problem:example-refused", title: "Example refusal" },
    });
    expect(idempotencyKeyFor(refused, RENDERED, resendable)).toBe(RENDERED);
    const form = attempt({ status: "error", fieldErrors: { reason: ["Example message"] } });
    expect(idempotencyKeyFor(form, RENDERED, resendable)).toBe(RENDERED);
    const keyless = attempt({ status: "idle" }, sentWith(null), sentWith(null));
    expect(idempotencyKeyFor(keyless, RENDERED, resendable)).toBe(RENDERED);
  });
});
