import AxeBuilder from "@axe-core/playwright";
import { expect, test as base } from "@playwright/test";
import type { Page } from "@playwright/test";

/** Impacts that fail a page; moderate and minor findings are reported by the unit-level axe. */
export const FAILING_IMPACTS: readonly string[] = ["serious", "critical"];

export interface ViolationSummary {
  id: string;
  impact: string;
  help: string;
  targets: string[];
}

/** Runs axe on the page (or one selector) and returns the serious and critical violations. */
export async function seriousViolations(page: Page, include?: string): Promise<ViolationSummary[]> {
  let builder = new AxeBuilder({ page });
  if (include !== undefined) builder = builder.include(include);
  const results = await builder.analyze();
  return results.violations
    .filter(
      (violation) =>
        typeof violation.impact === "string" && FAILING_IMPACTS.includes(violation.impact),
    )
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact ?? "unknown",
      help: violation.help,
      targets: violation.nodes.map((node) => node.target.join(" ")),
    }));
}

export interface A11yFixtures {
  /** Fails the test when the page, or the given selector, has a serious or critical finding. */
  checkA11y: (include?: string) => Promise<void>;
}

export const test = base.extend<A11yFixtures>({
  // Playwright calls the second argument "use"; it is named differently here so the React hooks
  // lint rule does not read it as a hook call.
  checkA11y: async ({ page }, provide) => {
    await provide(async (include) => {
      const violations = await seriousViolations(page, include);
      expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
    });
  },
});

export { expect };
