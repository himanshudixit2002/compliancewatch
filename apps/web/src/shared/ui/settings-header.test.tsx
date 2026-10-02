import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { SettingsHeader } from "./settings-header";

const CRUMBS = [
  { id: "owner.settings", href: "/settings", label: "Settings" },
  { id: "owner.settings.consents", href: "/settings/consents", label: "Consents" },
];
const TABS = [
  { id: "owner.settings.consents", href: "/settings/consents", label: "Consents" },
  { id: "owner.settings.notifications", href: "/settings/notifications", label: "Notifications" },
];

describe("SettingsHeader", () => {
  it("renders the breadcrumbs, the one heading and the settings tabs", async () => {
    vi.mocked(usePathname).mockReturnValue("/settings/consents");
    const { container } = render(
      <SettingsHeader
        title="Consents"
        description="Example description"
        crumbs={CRUMBS}
        tabs={TABS}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Consents" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/settings");
    const tabs = screen.getByRole("navigation", { name: "Settings pages" });
    expect(tabs.querySelector("[aria-current='page']")?.textContent).toBe("Consents");
    expect(screen.getByText("Example description")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
