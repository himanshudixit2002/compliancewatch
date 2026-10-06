import "server-only";

import { isProblemOf } from "@/entities/problem/mappers";
import { toActionState, type ApiError } from "@/server/result";
import { t, type MessageKey } from "@/shared/i18n";
import type { ActionState } from "@/shared/lib/action-state";

/**
 * The pipeline's refusals of a source's writes, said in the source pages' own words: a fetch
 * while crawling is off above all, which the page explains rather than passing on a 503.
 */
interface Wording {
  title: MessageKey;
  detail?: MessageKey;
}

/** The pipeline's refusals the source pages say in their own words, by problem slug. */
const REFUSALS: Readonly<Record<string, Wording>> = {
  "pipeline-crawl-disabled": {
    title: "adminSources.refusal.crawlOff",
    detail: "adminSources.refusal.crawlOffDetail",
  },
  "pipeline-crawl-running": {
    title: "adminSources.refusal.crawlRunning",
    detail: "adminSources.refusal.crawlRunningDetail",
  },
  "pipeline-source-upload-only": {
    title: "adminSources.refusal.uploadOnly",
    detail: "adminSources.refusal.uploadOnlyDetail",
  },
  "pipeline-crawl-unavailable": {
    title: "adminSources.refusal.crawlUnavailable",
    detail: "adminSources.refusal.crawlUnavailableDetail",
  },
  "pipeline-source-not-found": {
    title: "adminSources.refusal.notFound",
    detail: "adminSources.refusal.notFoundDetail",
  },
  "pipeline-source-invalid": { title: "adminSources.refusal.invalid" },
};

/**
 * A refusal as the form shows it: in the page's words when it is one the page knows (the
 * pipeline's own detail kept where the page has none, as it names what was wrong), else the
 * pipeline's problem as it came, always with the correlation id.
 */
export function plainRefusal<T>(error: ApiError): ActionState<T> {
  const state = toActionState<T>({ ok: false, error });
  if (state.status !== "error" || state.problem === undefined) return state;
  for (const [slug, wording] of Object.entries(REFUSALS)) {
    if (!isProblemOf(error.problem, slug)) continue;
    const detail = wording.detail === undefined ? state.problem.detail : t(wording.detail);
    return {
      ...state,
      problem: {
        ...state.problem,
        title: t(wording.title),
        ...(detail === undefined ? {} : { detail }),
      },
    };
  }
  return state;
}
