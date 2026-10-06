import "server-only";

import type { FanOutRun } from "@/entities/applicability/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { rulebookWorkflowAccess } from "@/server/api/rulebook-write";
import type { ClientContext } from "@/server/api/services";
import { err, ok, type ApiError, type Result } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import { fanOutsGateway } from "./gateway";
import {
  FAN_OUT_PAGE_SIZE,
  controlsFor,
  fanOutRow,
  holdView,
  listHrefs,
  type FanOutControl,
  type FanOutRow,
  type HoldView,
} from "./model/fan-outs";
import type { ReadFailure, RollbackState } from "./ui/controls-shared";

/**
 * The fan-out screens' reads. A run belongs to no tenant, so nothing here names one; the session
 * only decides what the page offers: every regulatory role reads, and the controls (the hold,
 * pause, resume, cancel and the rollback through the rulebook's withdraw) are the admin's
 * (`admin.fan_outs.control`, D-049). The hold is read on both pages; when its read fails the page
 * still shows the runs, with the failure where the hold would be.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

/** The hold, or why it could not be read. */
export type HoldRead = { ok: true; hold: HoldView } | { ok: false; failure: ReadFailure };

function failureOf(error: ApiError): ReadFailure {
  return { message: error.message, correlationId: error.requestId === "" ? null : error.requestId };
}

function versionHref(ruleVersionId: string): string {
  return hrefFor(screenById("admin.fan-out"), { ruleVersionId });
}

export interface FanOutListView {
  hold: HoldRead;
  rows: readonly FanOutRow[];
  canControl: boolean;
  nextHref: string | null;
  firstHref: string | null;
}

/** The runs, newest first, each named by its version (read from the rulebook, in parallel). */
export async function getFanOutList(
  session: QuerySession,
  cursor: string | null,
  deps: QueryDeps = {},
): Promise<Result<FanOutListView>> {
  const gateway = fanOutsGateway({ fetchImpl: deps.fetchImpl });
  const [hold, page] = await Promise.all([
    gateway.hold(),
    gateway.list({ limit: FAN_OUT_PAGE_SIZE, ...(cursor === null ? {} : { cursor }) }),
  ]);
  if (!page.ok) return page;
  const ids = [...new Set(page.value.items.map((run) => run.ruleVersionId))];
  const versions = await Promise.all(ids.map((id) => gateway.version(id)));
  const named = new Map<string, RuleVersion>();
  for (const version of versions)
    if (version.ok) named.set(version.value.ruleVersionId, version.value);
  return ok({
    hold: hold.ok
      ? { ok: true, hold: holdView(hold.value) }
      : { ok: false, failure: failureOf(hold.error) },
    rows: page.value.items.map((run) =>
      fanOutRow(run, named.get(run.ruleVersionId) ?? null, versionHref(run.ruleVersionId)),
    ),
    canControl: can(session, "admin.fan_outs.control"),
    ...listHrefs(hrefFor(screenById("admin.fan-outs")), cursor, page.value.nextCursor),
  });
}

export interface FanOutPageView {
  ruleVersionId: string;
  /** The run, or null when the version has had none. */
  run: FanOutRun | null;
  /** The version as the rulebook holds it; null when it does not hold it or could not answer. */
  version: RuleVersion | null;
  /** Why the version could not be read, when the rulebook failed rather than not holding it. */
  versionFailure: ReadFailure | null;
  hold: HoldRead;
  canControl: boolean;
  controls: readonly FanOutControl[];
  rollback: RollbackState;
}

function isNotFound(error: ApiError): boolean {
  return error.kind === "not_found";
}

async function rollbackFor(
  session: QuerySession,
  canControl: boolean,
  version: RuleVersion | null,
): Promise<RollbackState> {
  if (!canControl) return { state: "not_admin" };
  if (version === null) return { state: "unknown_version" };
  if (version.status !== "published") {
    return { state: "not_published", statusLabel: ruleVersionStatusLabel(version.status) };
  }
  const access = await rulebookWorkflowAccess({ session });
  return {
    state: "offered",
    access: access.allowed
      ? { allowed: true }
      : {
          allowed: false,
          title: access.error.message,
          ...(access.error.problem?.detail === undefined || access.error.problem.detail === null
            ? {}
            : { detail: access.error.problem.detail }),
        },
  };
}

/**
 * One version's fan-out page: the run (or that there has been none), the version, the hold and
 * what the session may do. Neither the engine nor the rulebook knowing the id is the not-found
 * page; a version without a run is shown as such, since a published version with no run is a
 * case the runbook covers (`docs/runbooks/fan-out-control.md`, "No run for a published version").
 */
export async function getFanOutPage(
  session: QuerySession,
  ruleVersionId: string,
  deps: QueryDeps = {},
): Promise<Result<FanOutPageView>> {
  const gateway = fanOutsGateway({ fetchImpl: deps.fetchImpl });
  const [run, version, hold] = await Promise.all([
    gateway.get(ruleVersionId),
    gateway.version(ruleVersionId),
    gateway.hold(),
  ]);
  if (!run.ok && !isNotFound(run.error)) return run;
  if (!run.ok && !version.ok && isNotFound(version.error)) return err(run.error);
  const canControl = can(session, "admin.fan_outs.control");
  const found = version.ok ? version.value : null;
  const runValue = run.ok ? run.value : null;
  return ok({
    ruleVersionId,
    run: runValue,
    version: found,
    versionFailure: version.ok || isNotFound(version.error) ? null : failureOf(version.error),
    hold: hold.ok
      ? { ok: true, hold: holdView(hold.value) }
      : { ok: false, failure: failureOf(hold.error) },
    canControl,
    controls: runValue === null ? [] : controlsFor(runValue.status),
    rollback: await rollbackFor(session, canControl, found),
  });
}
