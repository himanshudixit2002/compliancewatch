import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { LocationForm, type LocationFormResult } from "./location-form";

const FIELDS = {
  businessId: "business_id",
  registrationId: "registration_id",
  label: "label",
  name: "name",
};

type State = ActionState<LocationFormResult>;

function renderForm(action: (state: State, formData: FormData) => Promise<State>) {
  return render(
    <LocationForm
      action={action}
      businessId="b1"
      registrationId="r1"
      gstin="29ABCDE1234F1Z5"
      fields={FIELDS}
    />,
  );
}

describe("LocationForm", () => {
  it("asks for a label and a name under the registration", async () => {
    const { container } = renderForm(vi.fn());
    expect(
      screen.getByRole("form", { name: "Add a location under 29ABCDE1234F1Z5" }),
    ).toBeDefined();
    expect(screen.getByRole("textbox", { name: /Label/ }).getAttribute("aria-required")).toBe(
      "true",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("sends the hidden ids and says what was added, with links to the location's pages", async () => {
    const user = userEvent.setup();
    let sent: FormData | undefined;
    const { container } = renderForm(async (_state, formData) => {
      sent = formData;
      return {
        status: "ok",
        value: {
          id: "l1",
          label: "EX-01",
          name: "Example branch",
          created: true,
          attributesHref: "/b/b1/attributes?node=l1",
          snapshotHref: "/b/b1/snapshot?node=l1",
        },
      };
    });
    await user.type(screen.getByRole("textbox", { name: /Label/ }), "EX-01");
    await user.type(screen.getByRole("textbox", { name: /Name/ }), "Example branch");
    await user.click(screen.getByRole("button", { name: "Add the location" }));
    await waitFor(() => expect(screen.getByText("Location EX-01 is added")).toBeDefined());
    expect(sent?.get("business_id")).toBe("b1");
    expect(sent?.get("registration_id")).toBe("r1");
    expect(screen.getByRole("link", { name: "Its snapshot" }).getAttribute("href")).toBe(
      "/b/b1/snapshot?node=l1",
    );
    expect((screen.getByRole("textbox", { name: /Label/ }) as HTMLInputElement).value).toBe("");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when the label was already there", async () => {
    const user = userEvent.setup();
    renderForm(async () => ({
      status: "ok",
      value: {
        id: "l1",
        label: "EX-01",
        name: "Example branch",
        created: false,
        attributesHref: "/a",
        snapshotHref: "/s",
      },
    }));
    await user.click(screen.getByRole("button", { name: "Add the location" }));
    await waitFor(() =>
      expect(screen.getByText("Location EX-01 was already under this registration")).toBeDefined(),
    );
  });

  it("keeps what was typed and shows the field, form and service errors", async () => {
    const user = userEvent.setup();
    renderForm(async () => ({
      status: "error",
      problem: { type: "urn:x", title: "Example problem" },
      formErrors: ["Example form error."],
      fieldErrors: { label: ["Example label error."] },
    }));
    await user.type(screen.getByRole("textbox", { name: /Name/ }), "Example branch");
    await user.click(screen.getByRole("button", { name: "Add the location" }));
    await waitFor(() => expect(screen.getByText("Example label error.")).toBeDefined());
    expect(screen.getByText("Example problem")).toBeDefined();
    expect(screen.getByText("Example form error.")).toBeDefined();
    expect((screen.getByRole("textbox", { name: /Name/ }) as HTMLInputElement).value).toBe(
      "Example branch",
    );
  });
});
