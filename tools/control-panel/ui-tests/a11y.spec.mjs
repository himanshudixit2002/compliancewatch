// axe (WCAG 2.1 A and AA) on every view and on the palette, a confirm and the tour, in light
// and dark; and the keyboard basics: the skip link and visible focus.

import { axe, expect, setWorld, openApp, test, VIEWS } from "./helpers.mjs";

const WORLD = {
  docker: true,
  infra: true,
  services: 10,
  web: true,
  product: { internal: true, public: true, worker: true, web: true },
  branch: "pipeline-ops",
  sessions: "agent",
};

for (const scheme of ["light", "dark"]) {
  test.describe(`axe, ${scheme}`, () => {
    test.use({ colorScheme: scheme });

    test(`every view passes axe, ${scheme}`, async ({ page, request }) => {
      test.setTimeout(90000);
      await setWorld(request, { reset: true, prefs: { tour_done: true }, world: WORLD });
      await openApp(page);
      const found = {};
      for (const [view] of VIEWS) {
        await page.evaluate((v) => (window.location.hash = `#/${v}`), view);
        await expect(page.locator(`.view[data-view='${view}']`)).toBeVisible();
        await page.waitForTimeout(400);
        const violations = await axe(page);
        if (violations.length) found[view] = violations;
      }
      for (const section of ["parts", "recipes", "glossary", "trouble", "never", "more"]) {
        await page.evaluate((s) => (window.location.hash = `#/guide/${s}`), section);
        await page.waitForTimeout(300);
        const violations = await axe(page);
        if (violations.length) found[`guide/${section}`] = violations;
      }
      expect(found).toEqual({});
    });

    test(`dialogs and the tour pass axe, ${scheme}`, async ({ page, request }) => {
      await setWorld(request, { reset: true, prefs: { tour_done: true }, world: WORLD });
      await openApp(page);
      await page.keyboard.press("Meta+k");
      await page.keyboard.type("stop");
      expect(await axe(page)).toEqual([]);
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Stop everything" }).first().click();
      await expect(page.getByRole("dialog", { name: "Stop everything?" })).toBeVisible();
      expect(await axe(page)).toEqual([]);
      await page.keyboard.press("Escape");
      await page.locator("#activity-btn").click();
      expect(await axe(page)).toEqual([]);
      await page.keyboard.press("Escape");
      await page.evaluate(() => window.dispatchEvent(new CustomEvent("cw:tour")));
      await expect(
        page.getByRole("dialog", { name: "Start and stop everything here" }),
      ).toBeVisible();
      expect(await axe(page)).toEqual([]);
    });
  });
}

test("the skip link leads to the content, and focus is always visible", async ({
  page,
  request,
}) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true } });
  await openApp(page);
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to the content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press("Tab");
    const outline = await page.evaluate(() => {
      const el = document.activeElement;
      const style = el ? getComputedStyle(el) : null;
      return style ? `${style.outlineStyle} ${style.outlineWidth}` : "none";
    });
    expect(outline).not.toBe("none 0px");
  }
});
