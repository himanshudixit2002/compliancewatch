import type {
  AwaitOwner,
  AwaitedFileLike,
  AwaitedItemView,
  AwaitedRouteLike,
  NotAvailableView,
  ScreenLike,
  ScreenRow,
  ScreenStatus,
  UsedRouteLike,
} from "./types";

const ROLE_LABELS: Readonly<Record<string, string>> = {
  owner: "Owner",
  staff: "Staff",
  ca_admin: "CA admin",
  ca_staff: "CA staff",
  compliance_lead: "Compliance lead",
  analyst: "Analyst",
  reviewer: "Reviewer",
  admin: "Admin",
};

const STATUS_LABELS: Readonly<Record<ScreenStatus, string>> = {
  live: "Available",
  ready: "Ready to build",
  waiting: "Waiting for a backend",
  planned: "No backend scheduled",
};

type StatusTone = "success" | "info" | "warning" | "neutral";

const STATUS_TONES: Readonly<Record<ScreenStatus, StatusTone>> = {
  live: "success",
  ready: "info",
  waiting: "warning",
  planned: "neutral",
};

const OWNER_LABELS: Readonly<Record<AwaitOwner, string>> = {
  "plan-a": "services track",
  "plan-k": "KAG track",
  unplanned: "not scheduled",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

export function roleLabels(roles: readonly string[] | "public"): string[] {
  return roles === "public" ? ["Public"] : roles.map(roleLabel);
}

export function statusLabel(status: ScreenStatus): string {
  return STATUS_LABELS[status];
}

/** The tone a StatusChip uses for a status; the label carries the meaning. */
export function statusTone(status: ScreenStatus): StatusTone {
  return STATUS_TONES[status];
}

/** "services track (WP22)", "KAG track", "not scheduled (indicative path)". */
export function ownerLabel(owner: AwaitOwner, ref?: string): string {
  const label = OWNER_LABELS[owner];
  return ref === undefined ? label : `${label} (${ref})`;
}

/** The route and who delivers it; a hardened route also says which header it must require. */
export function toAwaitedItem(route: AwaitedRouteLike): AwaitedItemView {
  const owner = ownerLabel(route.owner, route.ref);
  return {
    method: route.method,
    path: route.path,
    owner: route.header === undefined ? owner : `${owner}, requiring ${route.header}`,
  };
}

export function toAwaitedFileItem(file: AwaitedFileLike): AwaitedItemView {
  return { method: "file", path: file.path, owner: ownerLabel(file.owner, file.ref) };
}

/** A route the screen calls, labelled with its service: "rulebook service". */
export function toUsedItem(route: UsedRouteLike): AwaitedItemView {
  return { method: route.method, path: route.path, owner: `${route.service} service` };
}

/**
 * The awaited routes and files; a ready entry adds the routes it uses that it does not await,
 * so its notice lists the whole backend the screen will call.
 */
function noticeItems(screen: ScreenLike): AwaitedItemView[] {
  const items = [
    ...screen.awaits.map(toAwaitedItem),
    ...(screen.awaitsFiles ?? []).map(toAwaitedFileItem),
  ];
  if (screen.status !== "ready") return items;
  const listed = new Set(items.map((item) => `${item.method} ${item.path}`));
  const used = (screen.uses ?? []).filter((route) => !listed.has(`${route.method} ${route.path}`));
  return [...items, ...used.map(toUsedItem)];
}

/** Everything the "not available yet" notice needs; waitingFor is null when nothing is listed. */
export function toNotAvailableView(screen: ScreenLike): NotAvailableView {
  const items = noticeItems(screen);
  const view: NotAvailableView = {
    title: screen.title,
    guideRef: screen.guideRef,
    roles: roleLabels(screen.roles),
    backendReady: screen.status === "ready",
    waitingFor: items.length === 0 ? null : items,
  };
  if (screen.preview !== undefined) view.preview = screen.preview;
  if (screen.notes !== undefined) view.notes = screen.notes;
  return view;
}

export function toScreenRow(screen: ScreenLike): ScreenRow {
  return {
    id: screen.id,
    route: screen.route,
    title: screen.title,
    section: screen.section,
    roles: roleLabels(screen.roles),
    status: screen.status,
    statusLabel: statusLabel(screen.status),
    guideRef: screen.guideRef,
  };
}
