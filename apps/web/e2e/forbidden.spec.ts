import { expect, test } from "./fixtures";

test("the forbidden page explains the missing role and offers a way out", async ({
  page,
  checkA11y,
}) => {
  await page.goto("/forbidden");
  await expect(
    page.getByRole("heading", { level: 1, name: "You cannot open this page" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to the home page" })).toHaveAttribute(
    "href",
    "/",
  );
  await expect(page.getByRole("link", { name: "Sign in with another account" })).toHaveAttribute(
    "href",
    "/sign-in",
  );
  await checkA11y();
});
