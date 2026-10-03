import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { useRouter } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { RefreshButton } from "./refresh-button";

describe("RefreshButton", () => {
  it("asks the router to render the page again", async () => {
    const refresh = vi.fn();
    const router = vi.mocked(useRouter)();
    vi.mocked(useRouter).mockReturnValue({ ...router, refresh });
    const { container } = render(<RefreshButton />);
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
