import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { OUTPUT_PATH, formatRolesDoc, renderRolesDoc } from "../../scripts/roles-doc.mts";
import { CAPABILITY_NAMES } from "../shared/config/permissions.ts";
import { ROLES } from "../shared/config/roles.ts";
import { SCREENS } from "../shared/config/screens.ts";

describe("generated roles doc", () => {
  it("docs/web/roles.md is what the generator writes", async () => {
    const expected = await formatRolesDoc(renderRolesDoc());
    const committed = readFileSync(OUTPUT_PATH, "utf8");
    expect(committed, "run: pnpm --filter web roles:gen").toBe(expected);
  });

  it("lists every role, every capability and every live page or handler", () => {
    const markdown = renderRolesDoc();
    for (const role of ROLES) expect(markdown).toContain(`| \`${role}\` |`);
    for (const name of CAPABILITY_NAMES) expect(markdown).toContain(`| \`${name}\` |`);
    const live = SCREENS.filter(
      (screen) => screen.status === "live" && (screen.kind === "page" || screen.kind === "handler"),
    );
    for (const screen of live) {
      expect(markdown, screen.id).toContain(`| \`${screen.route}\` |`);
    }
    expect(markdown).toContain("needs a second factor");
    expect(markdown).toContain("first user of a business");
  });
});
