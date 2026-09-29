import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { NotAvailableYet } from "./not-available-yet";

describe("NotAvailableYet", () => {
  it("names the screen, its roles, guide reference and the awaited routes", async () => {
    const { container } = render(
      <NotAvailableYet
        title="Example screen"
        guideRef="15"
        roles={["owner", "staff"]}
        waitingFor={[{ method: "GET", path: "/v1/example", owner: "Example team" }]}
        backHref="/home"
      />,
    );
    expect(screen.getByText("Not available yet")).toBeDefined();
    expect(screen.getByRole("heading", { level: 1, name: "Example screen" })).toBeDefined();
    expect(screen.getByText("owner, staff")).toBeDefined();
    expect(screen.getByText("15")).toBeDefined();
    expect(screen.getByText("GET /v1/example").tagName).toBe("CODE");
    expect(screen.getByText("Example team")).toBeDefined();
    expect(screen.getByRole("link", { name: "Back" }).getAttribute("href")).toBe("/home");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when no backend exists at all", () => {
    render(<NotAvailableYet title="Example" guideRef="2" roles={["admin"]} waitingFor={null} />);
    expect(screen.getByText("No backend exists for this tool yet.")).toBeDefined();
    expect(screen.getByRole("link", { name: "Back" }).getAttribute("href")).toBe("/");
  });

  it("says the backend is on main and lists what a ready screen will use", async () => {
    const { container } = render(
      <NotAvailableYet
        title="Example"
        guideRef="2"
        roles={["admin"]}
        waitingFor={[{ method: "file", path: "example/registry.json", owner: "Example team" }]}
        backendReady
      />,
    );
    expect(
      screen.getByText(
        "The backend for this screen is on main. The screen itself has not been built yet.",
      ),
    ).toBeDefined();
    expect(screen.getByText("It will use:")).toBeDefined();
    expect(screen.getByText("file example/registry.json").tagName).toBe("CODE");
    expect(screen.queryByText("This screen waits for:")).toBeNull();
    expect(screen.queryByText("No backend exists for this tool yet.")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps the ready sentence when a ready screen lists nothing", () => {
    render(
      <NotAvailableYet
        title="Example"
        guideRef="2"
        roles={["admin"]}
        waitingFor={null}
        backendReady
      />,
    );
    expect(screen.getByText(/The backend for this screen is on main/)).toBeDefined();
    expect(screen.queryByText("It will use:")).toBeNull();
  });

  it("treats an empty list like no backend", () => {
    render(<NotAvailableYet title="Example" guideRef="2" roles={["admin"]} waitingFor={[]} />);
    expect(screen.getByText("No backend exists for this tool yet.")).toBeDefined();
  });
});
