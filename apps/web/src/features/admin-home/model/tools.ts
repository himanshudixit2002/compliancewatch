import { roleLabels, toAwaitedFileItem, toAwaitedItem } from "@/entities/screen/mappers";
import type { AwaitedItemView } from "@/entities/screen/types";
import { NAV_GROUPS, isNavGroupKey } from "@/shared/config/nav";
import type { NavGroupKey } from "@/shared/config/nav";
import { SCREENS, hrefFor, isCatchAll, routeParams, screenById } from "@/shared/config/screens";
import type { Screen, ScreenId, ScreenKind, ScreenStatus } from "@/shared/config/screens";

export interface AdminTool {
  id: string;
  title: string;
  route: string;
  kind: ScreenKind;
  /** Set for static routes: the tool itself, or its not-available notice. */
  href: string | null;
  roles: string[];
  status: ScreenStatus;
  waitsFor: AwaitedItemView[];
  /** The services the tool calls or waits for, each with its README path in the repository. */
  services: string[];
}

export interface AdminToolGroup {
  key: string;
  /** A navigation group label, or the "other" key for tools without a placement. */
  label: string | null;
  tools: AdminTool[];
}

const ADMIN_GROUP_ORDER: readonly NavGroupKey[] = [
  "rulebook",
  "review",
  "operations",
  "engine",
  "evals",
  "identity",
];

export const OTHER_GROUP = "other";

/** The tool's own navigation group, or the nearest ancestor's; "other" when none has one. */
export function groupOf(screen: Screen): string {
  let current: Screen | undefined = screen;
  while (current !== undefined) {
    const group = current.nav?.group;
    if (group !== undefined && isNavGroupKey(group)) return group;
    current = current.parent === undefined ? undefined : screenById(current.parent as ScreenId);
  }
  return OTHER_GROUP;
}

export function toAdminTool(screen: Screen): AdminTool {
  const staticRoute = screen.kind === "page" && routeParams(screen.route).length === 0;
  const services = new Set<string>();
  for (const route of [...screen.uses, ...screen.awaits]) services.add(route.service);
  return {
    id: screen.id,
    title: screen.title,
    route: screen.route,
    kind: screen.kind,
    href: staticRoute ? hrefFor(screen) : null,
    roles: roleLabels(screen.roles),
    status: screen.status,
    waitsFor: [
      ...screen.awaits.map(toAwaitedItem),
      ...(screen.awaitsFiles ?? []).map(toAwaitedFileItem),
    ],
    services: [...services].sort(),
  };
}

function orderOf(screen: Screen): number {
  return screen.nav?.order ?? Number.MAX_SAFE_INTEGER;
}

/** Every admin tool but the home page and the catch-all, grouped like the sidebar. */
export function adminToolGroups(screens: readonly Screen[] = SCREENS): AdminToolGroup[] {
  const tools = screens.filter(
    (screen) =>
      screen.section === "admin" && screen.id !== "admin.home" && !isCatchAll(screen.route),
  );
  const keys: string[] = [...ADMIN_GROUP_ORDER, OTHER_GROUP];
  return keys
    .map((key) => ({
      key,
      label: isNavGroupKey(key) ? NAV_GROUPS[key] : null,
      tools: tools
        .filter((screen) => groupOf(screen) === key)
        .sort((a, b) => orderOf(a) - orderOf(b) || a.title.localeCompare(b.title))
        .map(toAdminTool),
    }))
    .filter((group) => group.tools.length > 0);
}
