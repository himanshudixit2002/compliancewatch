// @vitest-environment node
import { fileURLToPath } from "node:url";
import { compile } from "@tailwindcss/node";
import { describe, expect, it } from "vitest";

/**
 * Runs the real Tailwind v4 engine over tokens.css the way apps/web's globals.css does, so the
 * utilities the components rely on are proven to exist and the default palette is proven gone.
 */
async function build(candidates: string[]): Promise<string> {
  const base = fileURLToPath(new URL(".", import.meta.url));
  const compiler = await compile('@import "tailwindcss"; @import "./tokens.css";', {
    base,
    onDependency: () => {},
  });
  return compiler.build(candidates).replace(/\s+/g, " ");
}

describe("tokens.css under Tailwind", () => {
  it("compiles the colour roles into utilities that read the token variables", async () => {
    const css = await build([
      "bg-bg",
      "bg-surface-raised",
      "text-fg",
      "text-fg-muted",
      "border-line",
      "border-line-strong",
      "ring-focus",
      "bg-danger",
      "text-danger-fg",
      "hover:bg-fg/5",
    ]);
    expect(css).toContain(".bg-bg { background-color: var(--bg); }");
    expect(css).toContain(".bg-surface-raised { background-color: var(--surface-raised); }");
    expect(css).toContain(".text-fg { color: var(--fg); }");
    expect(css).toContain(".text-fg-muted { color: var(--fg-muted); }");
    expect(css).toContain(".border-line { border-color: var(--line); }");
    expect(css).toContain(".border-line-strong { border-color: var(--line-strong); }");
    expect(css).toContain("--tw-ring-color: var(--focus);");
    expect(css).toContain(".bg-danger { background-color: var(--danger); }");
    expect(css).toContain(".text-danger-fg { color: var(--danger-fg); }");
    expect(css).toContain("color-mix(in oklab, var(--fg) 5%, transparent)");
  });

  it("removes the default palette so colours only come from the roles", async () => {
    const css = await build(["bg-red-500", "text-white", "border-gray-200", "bg-bg"]);
    expect(css).not.toContain("bg-red-500");
    expect(css).not.toContain("text-white");
    expect(css).not.toContain("border-gray-200");
    expect(css).toContain(".bg-bg");
  });

  it("emits both dark blocks and the class based dark variant", async () => {
    const css = await build(["dark:bg-surface"]);
    expect(css).toContain(".dark { color-scheme: dark; --bg: #0b1220;");
    expect(css).toContain("@media (prefers-color-scheme: dark) { :root:not(.light) {");
    expect(css).toContain(":where(.dark, .dark *)");
    expect(css).toContain("background-color: var(--surface)");
  });

  it("exposes the type scale, radii and font stacks", async () => {
    const css = await build(["text-xs", "text-3xl", "rounded-md", "font-sans", "font-mono", "p-4"]);
    expect(css).toContain("--text-xs: 0.75rem;");
    expect(css).toContain("--text-3xl--line-height: 2.25rem;");
    expect(css).toContain(".rounded-md { border-radius: var(--radius-md); }");
    expect(css).toContain(".font-sans { font-family: var(--font-sans); }");
    expect(css).toContain(".font-mono { font-family: var(--font-mono); }");
    expect(css).toContain(".p-4 { padding: calc(var(--spacing) * 4); }");
  });

  it("keeps the focus outline and reduced motion rules in the base layer", async () => {
    const css = await build([]);
    expect(css).toContain(
      "*:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }",
    );
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
