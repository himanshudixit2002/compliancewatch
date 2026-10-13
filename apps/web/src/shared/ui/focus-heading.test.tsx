import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FocusHeading } from "./focus-heading";

describe("FocusHeading", () => {
  it("focuses the page's h1 when active, making it focusable by script only", async () => {
    const { container } = render(
      <main>
        <h1>Example question?</h1>
        <FocusHeading active />
      </main>,
    );
    const heading = container.querySelector("h1");
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(heading?.getAttribute("tabindex")).toBe("-1");
  });

  it("leaves focus alone when inactive or when there is no heading", async () => {
    render(
      <main>
        <h1>Example</h1>
        <FocusHeading active={false} />
        <FocusHeading active selector="h6" />
      </main>,
    );
    await waitFor(() => expect(document.activeElement).toBe(document.body));
  });

  it("keeps a tabindex the heading already has", () => {
    const { container } = render(
      <main>
        <h2 tabIndex={0}>Example</h2>
        <FocusHeading active selector="main h2" />
      </main>,
    );
    expect(container.querySelector("h2")?.getAttribute("tabindex")).toBe("0");
  });
});
