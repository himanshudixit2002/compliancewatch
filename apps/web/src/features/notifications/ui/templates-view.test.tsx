import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { messageTemplateFromDto } from "@/entities/notification/mappers";
import { TEMPLATE_DTOS } from "@/test/notification-fixture";
import { templateRows } from "../model/templates";
import { TemplatesView } from "./templates-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.notifications", href: "/admin/notifications", label: "Notifications" },
  {
    id: "admin.notifications.templates",
    href: "/admin/notifications/templates",
    label: "Message templates",
  },
];

describe("TemplatesView", () => {
  it("lists every template with its channel, language, approval, placeholders and text", async () => {
    const rows = templateRows([
      ...TEMPLATE_DTOS.map(messageTemplateFromDto),
      messageTemplateFromDto({
        key: "example_due",
        channel: "whatsapp",
        language: "en",
        status: "approved",
        meta_name: "cw_example_due_en",
        placeholders: ["business_name", "due_date"],
        body: "Example {business_name}\nis due on {due_date}.",
      }),
    ]);
    const { container } = render(
      <TemplatesView title="Message templates" crumbs={CRUMBS} rows={rows} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Message templates" })).toBeDefined();
    expect(
      [...container.querySelectorAll("[data-slot='stat-card'] dd")].map((node) => node.textContent),
    ).toEqual(["4", "2"]);
    const due = container.querySelector("[data-template='example_due:whatsapp:en']") as HTMLElement;
    expect(due.textContent).toContain("At Meta: cw_example_due_en");
    expect(due.textContent).toContain("Approved");
    expect(due.textContent).toContain("business_name, due_date");
    expect(due.textContent).toContain("is due on {due_date}.");
    const hindi = container.querySelector(
      "[data-template='example_template:whatsapp:hi']",
    ) as HTMLElement;
    expect(hindi.textContent).toContain("Hindi");
    expect(hindi.textContent).toContain("Draft");
    expect(hindi.textContent).toContain("None");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when the service holds no template", async () => {
    const { container } = render(
      <TemplatesView title="Message templates" crumbs={CRUMBS} rows={[]} />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No templates" })).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
