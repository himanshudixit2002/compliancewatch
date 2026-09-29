import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { Button } from "./button";

describe("Button", () => {
  it("renders a type=button with the primary variant and medium size by default", async () => {
    const { container } = render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button.getAttribute("type")).toBe("button");
    expect(button.dataset.variant).toBe("primary");
    expect(button.dataset.size).toBe("md");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps an explicit submit type and applies the requested variant and size", () => {
    render(
      <Button type="submit" variant="danger" size="sm">
        Delete
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.getAttribute("type")).toBe("submit");
    expect(button.dataset.variant).toBe("danger");
    expect(button.dataset.size).toBe("sm");
    expect(button.className).toContain("bg-danger");
  });

  it("calls onClick when activated with the keyboard", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is busy and disabled while loading and shows the spinner", async () => {
    const onClick = vi.fn();
    const { container } = render(
      <Button loading onClick={onClick}>
        Saving
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Saving" });
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(container.querySelector('[data-slot="button-spinner"]')).not.toBeNull();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders the child element when asChild is set, without a type or spinner", async () => {
    const { container } = render(
      <Button asChild loading variant="link">
        <a href="/next">Next</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Next" });
    expect(link.tagName).toBe("A");
    expect(link.hasAttribute("type")).toBe(false);
    expect(link.getAttribute("aria-busy")).toBe("true");
    expect(link.className).toContain("text-primary");
    expect(container.querySelector('[data-slot="button-spinner"]')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
