import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Timeline } from "./timeline";

describe("Timeline", () => {
  it("lists dated events in order with their tone", async () => {
    const { container } = render(
      <Timeline
        events={[
          {
            id: "1",
            label: "1 Jan 2000, 10:00",
            dateTime: "2000-01-01T10:00:00+05:30",
            title: "Created",
            tone: "info",
          },
          {
            id: "2",
            label: "2 Jan 2000, 09:00",
            title: "Closed",
            body: "Example note",
            tone: "success",
          },
          { id: "3", label: "3 Jan 2000", title: "Noted" },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]?.dataset.tone).toBe("info");
    expect(items[2]?.dataset.tone).toBe("neutral");
    expect(container.querySelector("time")?.getAttribute("datetime")).toBe(
      "2000-01-01T10:00:00+05:30",
    );
    expect(screen.getByText("Example note")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
