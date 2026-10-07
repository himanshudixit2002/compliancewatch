import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { settingsIndexView } from "../model/cards";
import { SettingsIndex } from "./settings-index";

describe("SettingsIndex", () => {
  it("lists the pages with their status and what each is for", async () => {
    const { container } = render(
      <SettingsIndex
        title="Settings"
        view={settingsIndexView({ roles: ["owner"], tenantKind: "business" })}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Your settings" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Your account" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Consents" }).getAttribute("href")).toBe(
      "/settings/consents",
    );
    const dataRights = container.querySelector("[data-screen='owner.settings.data-rights']");
    expect(dataRights?.textContent).toContain("Ready to build");
    expect(
      await runAxe(container.querySelector("#settings-pages")?.parentElement as Element),
    ).toHaveNoViolations();
  });

  it("leaves out an empty group", () => {
    render(<SettingsIndex title="Settings" view={{ settings: [], account: [] }} />);
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });
});
