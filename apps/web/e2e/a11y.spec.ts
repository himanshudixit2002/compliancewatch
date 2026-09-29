import { SCREENS, hrefFor, isCatchAll, routeParams } from "../src/shared/config/screens.ts";
import type { Screen } from "../src/shared/config/screens.ts";
import { PERSONAS, expect, personaFor, test } from "./fixtures";
import type { Persona } from "./fixtures";

/**
 * Every page in the registry: the public ones without a session, every other one signed in
 * as the first persona its roles and tenant kinds admit. Live pages are visited by their
 * route; planned, waiting and ready pages through the catch-all with "example" for each
 * parameter. A live page with parameters needs real ones (a legal document, a business of the
 * signed-in tenant; "example" is a 404 there by design), so its own spec visits it with them and
 * runs axe on each state it reaches.
 */
function exampleHref(screen: Screen): string {
  const params = Object.fromEntries(routeParams(screen.route).map((name) => [name, "example"]));
  return hrefFor(screen, params);
}

const PAGES = SCREENS.filter(
  (screen) =>
    screen.kind === "page" &&
    !isCatchAll(screen.route) &&
    !(screen.status === "live" && routeParams(screen.route).length > 0),
);

const GROUPS: readonly { label: string; persona: Persona | null; pages: Screen[] }[] = [
  { label: "without a session", persona: null, pages: [] },
  ...PERSONAS.map((persona) => ({ label: `as ${persona.key}`, persona, pages: [] as Screen[] })),
];

for (const screen of PAGES) {
  const persona = personaFor(screen);
  const group = GROUPS.find((candidate) => candidate.persona?.key === persona?.key);
  if (group === undefined) throw new Error(`no group for ${screen.id}`);
  group.pages.push(screen);
}

for (const group of GROUPS) {
  if (group.pages.length === 0) continue;
  test.describe(`every registered page ${group.label}`, () => {
    test.beforeEach(async ({ signIn }) => {
      if (group.persona !== null) await signIn(group.persona);
    });

    for (const screen of group.pages) {
      test(`${screen.id} (${screen.status}) renders with one h1 and no serious axe finding`, async ({
        page,
        checkA11y,
      }) => {
        const response = await page.goto(exampleHref(screen));
        expect(response?.status(), screen.route).toBe(200);
        await expect(page).toHaveURL(
          new RegExp(`${exampleHref(screen).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
        );
        await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
        if (screen.status !== "live") {
          await expect(page.getByText("Not available yet")).toBeVisible();
          await expect(page.getByRole("heading", { level: 1, name: screen.title })).toBeVisible();
        }
        await checkA11y();
      });
    }
  });
}
