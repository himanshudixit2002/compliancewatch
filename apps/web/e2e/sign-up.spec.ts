import { ANY_CODE, signInByPhone, uniqueEmail, uniquePhone } from "./auth-helpers";
import { expect, test } from "./fixtures";

/**
 * The real sign-in on the fake adapter: a person identity does not know yet signs in by phone,
 * creates a business and lands on onboarding; the same person later signs in straight to their
 * home; the email link, shown instead of sent, comes back through the callback; and the
 * sign-in page's notices (an expired link, nothing to sign up).
 */
test.describe("sign-up", () => {
  test("a new person signs in by phone, creates a business and lands on onboarding", async ({
    page,
    checkA11y,
  }) => {
    const phone = uniquePhone();
    await page.goto("/sign-in?method=phone");
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.getByText(/any six digits pass/)).toBeVisible();
    await checkA11y();
    await page.getByLabel(/Mobile number/).fill(phone);
    await page.getByRole("button", { name: "Send code" }).click();
    await expect(page.getByLabel(/^Code/)).toBeVisible();
    await expect(page.locator("[data-slot='code-sent-to']")).toContainText(phone);
    await expect(page.locator("[data-slot='resend']")).toBeDisabled();
    await checkA11y();
    await page.getByLabel(/^Code/).fill("12");
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page.getByText("Enter the 6 digits of the code.")).toBeVisible();
    await expect(page.locator("[data-slot='sign-in-errors']")).toBeFocused();
    await page.getByLabel(/^Code/).fill(ANY_CODE);
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page).toHaveURL(/\/sign-up$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Create your account" }),
    ).toBeVisible();
    await expect(page.getByText(phone)).toBeVisible();
    await checkA11y();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByText("Enter a name.")).toBeVisible();
    await page.getByRole("radio", { name: /Business/ }).click();
    await page.getByLabel(/Name of the business or firm/).fill("Example New Traders");
    await page.getByLabel(/^Your name/).fill("Example new owner");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole("heading", { level: 1, name: "Get started" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Account" })).toContainText(
      "Example new owner",
    );
    // The account page reads /me: the phone, the account's name, and no second factor.
    await page.goto("/account");
    const facts = page.locator("dl[data-slot='key-value']");
    await expect(facts).toContainText(phone);
    await expect(facts).toContainText("Example New Traders");
    await expect(facts).toContainText("Owner");
    await expect(facts).toContainText("Not verified");
    await expect(page.locator("[data-slot='banner']")).toHaveCount(0);
    await checkA11y();
    // A second sign-in by the same person goes straight to their home.
    await page.request.post("/sign-out");
    await signInByPhone(page, phone, "/account");
    await expect(page).toHaveURL(/\/account$/);
    await expect(facts).toContainText("Example new owner");
  });

  test("the email link is shown instead of sent, and signs the person in through the callback", async ({
    page,
    checkA11y,
  }) => {
    const email = uniqueEmail("owner");
    await page.goto("/sign-in?method=email&next=%2Faccount");
    await expect(page.getByLabel(/Email address/)).toBeVisible();
    await checkA11y();
    await page.getByLabel(/Email address/).fill(email);
    await page.getByRole("button", { name: "Send link" }).click();
    await expect(page).toHaveURL(/\/sign-in\/email-sent$/);
    await expect(page.getByRole("heading", { level: 1, name: "Check your email" })).toBeVisible();
    await expect(page.getByText("Development: nothing was sent")).toBeVisible();
    await checkA11y();
    const link = page.getByRole("link", { name: "Open the sign-in link" });
    await expect(link).toHaveAttribute("href", /\/auth\/callback\?/);
    expect(await link.getAttribute("href")).toContain("next=%2Faccount");
    await link.click();
    // Nobody yet: the callback keeps the proof in the cookie and asks what to create.
    await expect(page).toHaveURL(/\/sign-up$/);
    await expect(page.getByText(email)).toBeVisible();
    await page.getByRole("radio", { name: /Business/ }).click();
    await page.getByLabel(/Name of the business or firm/).fill("Example Mail Traders");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.locator("dl[data-slot='key-value']")).toContainText(email);
  });

  test("an expired link and an empty sign-up each say so", async ({ page, checkA11y }) => {
    await page.goto("/auth/callback?token_hash=not-a-token&type=email");
    await expect(page).toHaveURL(/\/sign-in\?error=link-expired$/);
    await expect(page.getByText(/That sign-in link is not valid any more/)).toBeVisible();
    await checkA11y();
    await page.goto("/sign-up");
    await expect(page).toHaveURL(/\/sign-up$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Create your account" }),
    ).toBeVisible();
    await expect(
      page.getByText(/Sign in with your mobile number or email address first/),
    ).toBeVisible();
    await page.getByRole("main").getByRole("link", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/sign-in$/);
    await checkA11y();
  });

  test("the other ways in are linked from each form", async ({ page }) => {
    await page.goto("/sign-in");
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    const methods = page.getByRole("navigation", { name: "Other ways to sign in" });
    await methods.getByRole("link", { name: "Sign in with an email link" }).click();
    await expect(page).toHaveURL(/method=email/);
    await expect(page.getByLabel(/Email address/)).toBeVisible();
    await methods.getByRole("link", { name: "Development sign-in" }).click();
    await expect(page.getByLabel("Tenant kind")).toBeVisible();
  });
});
