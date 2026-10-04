import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ANALYST, OWNER, expect, test } from "./fixtures";

/**
 * The flag console over packages/flags/registry.json. It calls no service: the registry is built
 * into the app and the values come from the web server's own flag reader, so the spec compares
 * the page with the registry file and only checks that each web flag got an answer.
 */
interface RegistryFlag {
  name: string;
  type: "bool" | "string";
  default: boolean | string;
  owner: string;
  description: string;
  expires: string;
  services: string[];
}

const REGISTRY = JSON.parse(
  readFileSync(resolve(__dirname, "../../../packages/flags/registry.json"), "utf8"),
) as { flags: RegistryFlag[] };

const EXPIRY = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
  year: "numeric",
});

function formatted(dateKey: string): string {
  return EXPIRY.format(new Date(`${dateKey}T12:00:00Z`));
}

test.describe("flag console", () => {
  test("an analyst sees every registry flag with its owner, default, value and expiry", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await page.goto("/admin");
    await page.locator("aside").getByRole("link", { name: "Feature flags" }).click();
    await expect(page).toHaveURL(/\/admin\/flags$/);
    await expect(page.getByRole("heading", { level: 1, name: "Feature flags" })).toBeVisible();
    await expect(page.locator("aside [aria-current='page']")).toHaveText("Feature flags");
    await expect(
      page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", {
        name: "Internal tools",
      }),
    ).toHaveAttribute("href", "/admin");
    await expect(page.locator("[data-slot='flag-provider']")).toContainText("env provider");

    const rows = page.locator("tbody tr[data-flag]");
    await expect(rows).toHaveCount(REGISTRY.flags.length);
    await expect(
      page.getByText(`${REGISTRY.flags.length} flags in the shared registry`),
    ).toBeVisible();
    for (const flag of REGISTRY.flags) {
      const row = page.locator(`tr[data-flag='${flag.name}']`);
      await expect(row).toContainText(flag.description);
      await expect(row).toContainText(flag.owner);
      await expect(row).toContainText(formatted(flag.expires));
      if (flag.type === "string") await expect(row).toContainText(String(flag.default));
      if (flag.services.includes("web")) {
        await expect(row).toHaveAttribute("data-value", /^(on|off)$/);
      } else {
        await expect(row).toHaveAttribute("data-value", "elsewhere");
        await expect(row).toContainText(`Read by ${flag.services.join(", ")}`);
      }
    }
    await expect(page.getByRole("button", { name: /turn|toggle|switch/i })).toHaveCount(0);
    await checkA11y();
  });

  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto("/admin/flags"))?.status()).toBe(404);
  });
});
