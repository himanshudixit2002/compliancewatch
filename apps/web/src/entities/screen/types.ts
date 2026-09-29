/**
 * View types for screens: what a page, a sitemap row or a "not available yet" notice shows.
 * The registry (shared/config/screens.ts) is the input, described structurally here so this
 * layer stays free of config imports.
 */
export type ScreenStatus = "live" | "ready" | "waiting" | "planned";

export type AwaitOwner = "plan-a" | "plan-k" | "unplanned";

export interface AwaitedRouteLike {
  method: string;
  path: string;
  owner: AwaitOwner;
  ref?: string;
}

export interface AwaitedFileLike {
  path: string;
  owner: AwaitOwner;
  ref?: string;
}

export interface UsedRouteLike {
  service: string;
  method: string;
  path: string;
}

export interface ScreenLike {
  id: string;
  route: string;
  title: string;
  section: string;
  roles: readonly string[] | "public";
  status: ScreenStatus;
  uses?: readonly UsedRouteLike[];
  awaits: readonly AwaitedRouteLike[];
  awaitsFiles?: readonly AwaitedFileLike[];
  guideRef: string;
  preview?: string;
  notes?: string;
}

/** One awaited dependency as the notice lists it: "GET /v1/qa/ask" plus who delivers it. */
export interface AwaitedItemView {
  method: string;
  path: string;
  owner: string;
}

/** The props of the NotAvailableYet component, derived from a registry entry. */
export interface NotAvailableView {
  title: string;
  guideRef: string;
  roles: string[];
  /** True for a ready entry: the backend is on main and only the screen is missing. */
  backendReady: boolean;
  /** What the screen waits for; for a ready entry, the routes and files it will use. */
  waitingFor: AwaitedItemView[] | null;
  preview?: string;
  notes?: string;
}

export interface ScreenRow {
  id: string;
  route: string;
  title: string;
  section: string;
  roles: string[];
  status: ScreenStatus;
  statusLabel: string;
  guideRef: string;
}
