import type {
  AwaitOwner,
  AwaitedFileLike,
  AwaitedItemView,
  AwaitedRouteLike,
  NotAvailableView,
  ScreenLike,
  ScreenRow,
  ScreenStatus,
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
  waiting: "Waiting for a backend",
  planned: "No backend scheduled",
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
export function statusTone(status: ScreenStatus): "success" | "warning" | "neutral" {
  if (status === "live") return "success";
  if (status === "waiting") return "warning";
  return "neutral";
}

/** "services track (WP22)", "KAG track", "not scheduled (indicative path)". */
export function ownerLabel(owner: AwaitOwner, ref?: string): string {
  const label = OWNER_LABELS[owner];
  return ref === undefined ? label : `${label} (${ref})`;
}

export function toAwaitedItem(route: AwaitedRouteLike): AwaitedItemView {
  return { method: route.method, path: route.path, owner: ownerLabel(route.owner, route.ref) };
}

export function toAwaitedFileItem(file: AwaitedFileLike): AwaitedItemView {
  return { method: "file", path: file.path, owner: ownerLabel(file.owner, file.ref) };
}

/** Everything the "not available yet" notice needs; waitingFor is null when nothing is scheduled. */
export function toNotAvailableView(screen: ScreenLike): NotAvailableView {
  const items = [
    ...screen.awaits.map(toAwaitedItem),
    ...(screen.awaitsFiles ?? []).map(toAwaitedFileItem),
  ];
  const view: NotAvailableView = {
    title: screen.title,
    guideRef: screen.guideRef,
    roles: roleLabels(screen.roles),
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
