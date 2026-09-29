import { describe, expect, it } from "vitest";
import { axeMatchers, formatViolations, runAxe } from "./axe";

describe("runAxe", () => {
  it("passes an accessible fragment", async () => {
    const root = document.createElement("div");
    root.innerHTML = '<button type="button">Save</button>';
    document.body.append(root);
    expect(await runAxe(root)).toHaveNoViolations();
    root.remove();
  });

  it("reports a violation with its node and fails the matcher", async () => {
    const root = document.createElement("div");
    root.innerHTML = '<img src="x.png">';
    document.body.append(root);
    const results = await runAxe(root);
    expect(results.violations.map((v) => v.id)).toContain("image-alt");
    const outcome = axeMatchers.toHaveNoViolations(results);
    expect(outcome.pass).toBe(false);
    expect(outcome.message()).toContain("image-alt");
    expect(outcome.message()).toContain("img");
    root.remove();
  });

  it("honours rule overrides passed by the caller", async () => {
    const root = document.createElement("div");
    root.innerHTML = '<img src="x.png">';
    document.body.append(root);
    const results = await runAxe(root, { rules: { "image-alt": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).not.toContain("image-alt");
    expect(axeMatchers.toHaveNoViolations(results).message()).toBe(
      "expected axe violations but found none",
    );
    root.remove();
  });
});

describe("formatViolations", () => {
  it("prints one block per violation", () => {
    const text = formatViolations([
      {
        id: "label",
        impact: "critical",
        help: "Form elements must have labels",
        description: "",
        helpUrl: "",
        tags: [],
        nodes: [
          {
            target: ["input"],
            failureSummary: "Fix any of the following: ...",
            html: "<input>",
            any: [],
            all: [],
            none: [],
          },
        ],
      },
    ]);
    expect(text).toBe(
      "label (critical): Form elements must have labels\n  input\n    Fix any of the following: ...",
    );
  });
});
