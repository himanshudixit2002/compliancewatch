"use server";

import { isProblemOf } from "@/entities/problem/mappers";
import { pipelineWrites } from "@/server/api/pipeline-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { sourcesGateway } from "./gateway";
import { changedText, parseSettings, reasonOf } from "./model/source";
import { plainRefusal } from "./refusals";
import {
  FETCH_FIELDS,
  SETTINGS_FIELDS,
  type FetchResult,
  type SettingsResult,
} from "./ui/source-shared";

/**
 * A source's writes: its settings (PATCH, only what changed) and a crawl started by hand. Each
 * runs the page's gate again (the proxy is not on an action's path), refuses anyone but an admin
 * (`admin.sources.write`) before any request, checks the form's shape, and goes through
 * `server/api/pipeline-write.ts`, which sends the shared write token and names the session's user
 * as the actor; the pipeline keeps the reason in its audit entry. Its refusals are said plainly,
 * a fetch refused while crawling is off above all. On success the list and the source's page
 * render again.
 */
const LIST = screenById("admin.sources");
const PAGE = screenById("admin.source");

const SOURCE_KEY = /^[a-z][a-z0-9_]{0,62}$/;

function refresh(key: string): void {
  afterMutation({ paths: [hrefFor(LIST), hrefFor(PAGE, { key })] });
}

function adminOnly<T>(): ActionState<T> {
  return actionFailure(t("adminSources.access.adminOnly"));
}

function unknownSource<T>(): ActionState<T> {
  return actionFailure(t("adminSources.refusal.notFound"));
}

/** Saves the settings that changed, against the source as the pipeline holds it now. */
export async function editSource(
  key: string,
  _state: ActionState<SettingsResult>,
  formData: FormData,
): Promise<ActionState<SettingsResult>> {
  const session = await requireScreenSession(PAGE, { key });
  if (!can(session, "admin.sources.write")) return adminOnly();
  if (!SOURCE_KEY.test(key)) return unknownSource();
  const sources = await sourcesGateway().sources();
  if (!sources.ok) return toActionState<SettingsResult>({ ok: false, error: sources.error });
  const current = sources.value.find((source) => source.key === key);
  if (current === undefined) return unknownSource();
  const parsed = parseSettings(formData, current);
  if (!parsed.ok) {
    return parsed.formError === undefined
      ? fieldFailure(parsed.fieldErrors)
      : actionFailure(parsed.formError, parsed.fieldErrors);
  }
  const result = await pipelineWrites({ session }, "admin.sources.write").editSource(
    key,
    parsed.edit,
    parsed.reason,
  );
  if (!result.ok) {
    const state = plainRefusal<SettingsResult>(result.error);
    // The adapter type refused the parameters: say so under the field too.
    if (isProblemOf(result.error.problem, "pipeline-source-invalid") && state.status === "error") {
      return {
        ...state,
        fieldErrors: {
          ...state.fieldErrors,
          [SETTINGS_FIELDS.parameters]: [t("adminSources.refusal.invalidField")],
        },
      };
    }
    return state;
  }
  refresh(key);
  const message = t("adminSources.settings.saved", { changed: changedText(parsed.changed) });
  return actionSuccess({ message, changed: parsed.changed }, message);
}

/** Starts a crawl of the source now, with the reason the pipeline keeps. */
export async function fetchSource(
  key: string,
  _state: ActionState<FetchResult>,
  formData: FormData,
): Promise<ActionState<FetchResult>> {
  const session = await requireScreenSession(PAGE, { key });
  if (!can(session, "admin.sources.write")) return adminOnly();
  if (!SOURCE_KEY.test(key)) return unknownSource();
  const reason = reasonOf(formData, FETCH_FIELDS.reason);
  if (!reason.ok) return fieldFailure(reason.fieldErrors);
  const result = await pipelineWrites({ session }, "admin.sources.write").fetchSource(
    key,
    reason.reason,
  );
  if (!result.ok) return plainRefusal<FetchResult>(result.error);
  refresh(key);
  const message = t("adminSources.fetch.started", {
    run: result.value.runId,
    workflow: result.value.workflowId,
  });
  return actionSuccess({ message }, message);
}
