import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import type { SessionDto } from "@/entities/session/types";
import { AccountView } from "./account-view";

const session: SessionDto = {
  userId: "00000000-0000-4000-8000-000000000001",
  tenantId: "00000000-0000-4000-8000-000000000002",
  tenantKind: "ca_firm",
  roles: ["ca_admin", "compliance_lead"],
  displayName: "Example CA admin",
  mfa: true,
  provider: "fake",
  issuedAt: 1_790_676_000,
  expiresAt: 1_790_704_800,
};

describe("AccountView", () => {
  it("lists the session facts in IST with copy buttons and a sign-out form", async () => {
    const { container } = render(<AccountView session={session} />);
    expect(screen.getByRole("heading", { level: 1, name: "Account" })).toBeDefined();
    const list = container.querySelector("dl[data-slot='key-value']") as HTMLElement;
    expect(list.getAttribute("aria-label")).toBe("Session facts");
    expect(list.textContent).toContain("Example CA admin");
    expect(list.textContent).toContain("CA firm");
    expect(list.textContent).toContain("CA admin, Compliance lead");
    expect(list.textContent).toContain("Asserted by the development sign-in, not verified");
    expect(list.textContent).toContain("29 Sept 2026, 3:30 pm IST");
    expect(list.textContent).toContain("29 Sept 2026, 11:30 pm IST");
    expect(list.textContent).toContain("Development (fake)");
    expect(screen.getByRole("button", { name: "Copy User id" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Copy Tenant id" })).toBeDefined();
    const form = container.querySelector("form[data-slot='sign-out']");
    expect(form?.getAttribute("action")).toBe("/sign-out");
    expect(form?.getAttribute("method")).toBe("post");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDefined();
    expect(container.querySelector("[data-slot='banner']")?.textContent).toContain("/me");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("words the second factor by provider and state", () => {
    const { container, rerender } = render(<AccountView session={{ ...session, mfa: false }} />);
    const facts = () => container.querySelector("dl[data-slot='key-value']")?.textContent ?? "";
    expect(facts()).toContain("Not verified");
    rerender(<AccountView session={{ ...session, provider: "supabase" }} />);
    expect(facts()).toContain("Verified");
    expect(facts()).not.toContain("Asserted");
    expect(facts()).toContain("Supabase");
    rerender(<AccountView session={{ ...session, tenantKind: "internal", roles: ["admin"] }} />);
    expect(facts()).toContain("Internal (regulatory team)");
  });
});
