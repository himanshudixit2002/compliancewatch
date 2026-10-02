import { LEGAL_DOCS } from "../src/shared/config/legal-docs.ts";
import { newTenantPersona } from "./business-helpers";
import { IS_CI, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

/**
 * A visitor's way in, with axe on every screen: read each legal document from the home page (a
 * draft, under its banner, also on paper), then ask for onboarding without a session, sign in on
 * the page that sends them to, and land back on the consent step, which names the same drafts
 * and versions the documents showed. The consent step reads the identity service, so the journey
 * runs with the services and the seed, like the other journeys.
 */
const DRAFT_BANNER_TEXT = "Draft - to be reviewed by a lawyer";

test.describe("journey: a visitor from the legal documents to the consent step", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("reads each document, then signs in and lands on the consent step", async ({
    page,
    checkA11y,
  }) => {
    const versions = new Map<string, string>();
    for (const doc of LEGAL_DOCS) {
      await page.goto("/");
      await page.getByRole("link", { name: doc.title, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/legal/${doc.name}$`));
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(doc.title);
      const banner = page.getByRole("status").filter({ hasText: DRAFT_BANNER_TEXT });
      await expect(banner).toBeVisible();
      const version = /Version (\S+-draft)\./.exec((await banner.textContent()) ?? "")?.[1];
      expect(version, doc.name).toBeDefined();
      versions.set(doc.title, version as string);
      await checkA11y();

      // On paper: the same document without the shell, still marked as a draft.
      await page.emulateMedia({ media: "print" });
      await expect(page.locator("[data-slot='app-shell'] > header")).toBeHidden();
      await expect(banner).toBeVisible();
      await expect(page.locator("[data-slot='legal-printed']")).toHaveText(
        `Printed from ComplianceWatch: ${doc.title}, version ${version}.`,
      );
      await page.emulateMedia({ media: "screen" });
    }

    // Onboarding asks for a session first, then comes back.
    await page.goto("/onboarding");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fonboarding$/);
    await checkA11y();
    await signInThroughForm(page, newTenantPersona(), "/onboarding");
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole("heading", { level: 1, name: "Get started" })).toBeVisible();
    await checkA11y();

    // The consent step names the documents at the versions the pages showed.
    for (const [title, version] of versions) {
      await expect(
        page.getByRole("link", { name: `${title}, version ${version}` }).first(),
      ).toHaveAttribute("href", /^\/legal\//);
    }
  });
});
