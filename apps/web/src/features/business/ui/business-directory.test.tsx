import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import type { ActionState } from "@/shared/lib/action-state";
import { BusinessDirectory, type DirectoryPageData } from "./business-directory";

const FIELDS = { q: "q", cursor: "cursor", page: "page" };
const ROW = {
  id: "b1",
  name: "Example business",
  pan: "ABCDE1234F",
  gstins: "29ABCDE1234F1Z5",
  updatedAt: "4 Jan 2000, 5:30 am IST",
  href: "/b/b1",
};
const FIRST: DirectoryPageData = { q: "", page: 1, rows: [ROW], nextCursor: "c1" };

type State = ActionState<DirectoryPageData>;

function renderDirectory(action: (state: State, formData: FormData) => Promise<State>) {
  return render(
    <BusinessDirectory
      title="Clients"
      audience="clients"
      initial={FIRST}
      action={action}
      fields={FIELDS}
      addHref="/onboarding/business"
      startHref="/onboarding"
    />,
  );
}

describe("BusinessDirectory", () => {
  it("lists the first page with a search box, the add link and the next page", async () => {
    const { container } = renderDirectory(vi.fn());
    expect(screen.getByRole("heading", { level: 1, name: "Clients" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Add a client" }).getAttribute("href")).toBe(
      "/onboarding/business",
    );
    expect(screen.getByRole("search")).toBeDefined();
    expect(screen.getByRole("status").textContent).toBe("Page 1: 1 clients.");
    expect(screen.getByRole("link", { name: "Example business" }).getAttribute("href")).toBe(
      "/b/b1",
    );
    expect(screen.getByRole("button", { name: "Next page" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "First page" })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("posts the term, shows the matches and pages on with the cursor", async () => {
    const user = userEvent.setup();
    const sent: FormData[] = [];
    const action = vi.fn(async (_state: State, formData: FormData): Promise<State> => {
      sent.push(formData);
      const page = Number(formData.get("page"));
      return {
        status: "ok",
        value: {
          q: "example",
          page,
          rows: [{ ...ROW, id: `b${page}` }],
          nextCursor: page === 1 ? "c2" : null,
        },
      };
    });
    const { container } = renderDirectory(action);
    await user.type(screen.getByRole("textbox", { name: /Search/ }), "example");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe('Page 1: 1 matching "example".'),
    );
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("status")));
    expect(sent[0]?.get("q")).toBe("example");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Page 2"));
    expect(sent[1]?.get("cursor")).toBe("c2");
    expect(sent[1]?.get("q")).toBe("example");
    await user.click(screen.getByRole("button", { name: "First page" }));
    await waitFor(() => expect(sent[2]?.get("page")).toBe("1"));
    expect(sent[2]?.get("cursor")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps the last page and shows the problem when a read fails", async () => {
    const user = userEvent.setup();
    renderDirectory(async () => ({
      status: "error",
      problem: { type: "urn:x", title: "Example failure", correlationId: "req-example-3" },
    }));
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByText("Example failure")).toBeDefined());
    expect(screen.getByRole("link", { name: "Example business" })).toBeDefined();
  });

  it("words a failure the service gave no problem for", async () => {
    const user = userEvent.setup();
    renderDirectory(async () => ({ status: "error", formErrors: ["Example form error."] }));
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByText("The list could not be read")).toBeDefined());
    expect(screen.getByText("Example form error.")).toBeDefined();
  });

  it("says why the list is empty, with the way to start, or that nothing matches", async () => {
    const { container, unmount } = render(
      <BusinessDirectory
        title="Businesses"
        audience="owner"
        initial={{ q: "", page: 1, rows: [], nextCursor: null }}
        action={vi.fn()}
        fields={FIELDS}
        addHref={null}
        startHref="/onboarding"
      />,
    );
    expect(screen.getByRole("heading", { name: "No business yet" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Get started" }).getAttribute("href")).toBe(
      "/onboarding",
    );
    expect(screen.queryByRole("link", { name: "Add a business" })).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();
    render(
      <BusinessDirectory
        title="Businesses"
        audience="owner"
        initial={{ q: "zzz", page: 1, rows: [], nextCursor: null }}
        action={vi.fn()}
        fields={FIELDS}
        addHref={null}
        startHref={null}
      />,
    );
    expect(screen.getByRole("heading", { name: "Nothing matches the search" })).toBeDefined();
    expect(screen.queryByRole("link", { name: "Get started" })).toBeNull();
  });
});
