import axe from "axe-core";
import type { AxeResults, ElementContext, Result, RunOptions } from "axe-core";

/**
 * Accessibility assertions for component tests, written over axe-core (already in the
 * workspace) so no extra matcher package is needed. apps/web extends its `expect` with the
 * same matcher through the package's `./test/axe` export.
 *
 * `region` is off because a component rendered on its own has no landmarks, and
 * `color-contrast` is off because jsdom has no layout or canvas to measure it with; page-level
 * checks run in the Playwright suite and src/contrast.test.ts covers the colours.
 */
export async function runAxe(
  context: ElementContext,
  options: RunOptions = {},
): Promise<AxeResults> {
  return axe.run(context, {
    ...options,
    rules: {
      region: { enabled: false },
      "color-contrast": { enabled: false },
      ...options.rules,
    },
  });
}

export function formatViolations(violations: readonly Result[]): string {
  return violations
    .map((violation) => {
      const nodes = violation.nodes
        .map((node) => `  ${node.target.join(" ")}\n    ${node.failureSummary ?? ""}`.trimEnd())
        .join("\n");
      return `${violation.id} (${violation.impact ?? "unknown"}): ${violation.help}\n${nodes}`;
    })
    .join("\n\n");
}

export const axeMatchers = {
  toHaveNoViolations(received: AxeResults) {
    const { violations } = received;
    const pass = violations.length === 0;
    return {
      pass,
      message: () =>
        pass
          ? "expected axe violations but found none"
          : `expected no axe violations but found ${violations.length}:\n\n${formatViolations(violations)}`,
    };
  },
};

declare module "vitest" {
  // The type parameter must match vitest's own declaration to merge with it.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  interface Matchers<T = any> {
    toHaveNoViolations(): T;
  }
}
