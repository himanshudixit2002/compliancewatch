import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { Skeleton, SkeletonGroup } from "./skeleton";

describe("Skeleton", () => {
  it("hides the blocks and announces one loading status for the group", async () => {
    const { container } = render(
      <SkeletonGroup>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-24" />
      </SkeletonGroup>,
    );
    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toBe("Loading");
    const blocks = container.querySelectorAll('[data-slot="skeleton"]');
    expect(blocks).toHaveLength(2);
    expect(blocks[0]?.getAttribute("aria-hidden")).toBe("true");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("takes a custom label", () => {
    render(<SkeletonGroup label="Loading obligations" />);
    expect(screen.getByRole("status").textContent).toBe("Loading obligations");
  });
});
