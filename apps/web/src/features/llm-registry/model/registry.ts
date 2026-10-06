import { LLM_FEATURES, type LlmFeature, type ModelRoute, type Prompt } from "@/entities/llm/types";
import { toAwaitedItem } from "@/entities/screen/mappers";
import type { AwaitedItemView } from "@/entities/screen/types";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";

/**
 * The gateway's prompt registry and model routes as the read-only pages show them. A prompt with
 * no eval case is flagged, since no golden set guards a change to it; a route the gateway's
 * environment overrode names the variable it reads (`CW_LLM_ROUTES__<FEATURE>`, the gateway's
 * settings), since that is where the route is changed.
 */
export interface PromptRow {
  key: string;
  name: string;
  version: string;
  owner: string;
  evalCases: number;
  /** No eval case guards the prompt. */
  unguarded: boolean;
  /** The first twelve characters of the hash, the whole one for copying; null without one. */
  shortHash: string | null;
  sha256: string | null;
  description: string;
}

const HASH_SHOWN = 12;

export function promptRows(prompts: readonly Prompt[]): PromptRow[] {
  return [...prompts]
    .sort(
      (a, b) =>
        a.name.localeCompare(b.name) || a.version.localeCompare(b.version, "en", { numeric: true }),
    )
    .map((prompt) => ({
      key: `${prompt.name}@${prompt.version}`,
      name: prompt.name,
      version: prompt.version,
      owner: prompt.owner,
      evalCases: prompt.evalCases,
      unguarded: prompt.evalCases === 0,
      shortHash: prompt.sha256 === null ? null : prompt.sha256.slice(0, HASH_SHOWN),
      sha256: prompt.sha256,
      description: prompt.description,
    }));
}

/** A feature as people read it: "qa" is "QA", "classification" is "Classification". */
export function featureLabel(feature: string): string {
  return feature === "qa" ? t("llm.feature.qa") : humanise(feature);
}

/** The gateway setting that overrides a feature's route. */
export function overrideVariable(feature: LlmFeature): string {
  return `CW_LLM_ROUTES__${feature.toUpperCase()}`;
}

export interface ModelRow {
  feature: LlmFeature;
  featureLabel: string;
  primary: string;
  fallback: string | null;
  only: readonly string[];
  has: readonly string[];
  sort: string | null;
  reasoningEffort: string | null;
  timeout: string;
  overridden: boolean;
  sourceLabel: string;
  /** Set for an overridden route: the variable the gateway read it from. */
  variable: string | null;
}

function featureOrder(feature: string): number {
  const index = (LLM_FEATURES as readonly string[]).indexOf(feature);
  return index === -1 ? LLM_FEATURES.length : index;
}

export function modelRows(routes: readonly ModelRoute[]): ModelRow[] {
  return [...routes]
    .sort((a, b) => featureOrder(a.feature) - featureOrder(b.feature))
    .map((route) => ({
      feature: route.feature,
      featureLabel: featureLabel(route.feature),
      primary: route.primary,
      fallback: route.fallback,
      only: route.only,
      has: route.has,
      sort: route.sort,
      reasoningEffort: route.reasoningEffort,
      timeout: t("llm.models.seconds", { count: route.timeoutSeconds }),
      overridden: route.source === "override",
      sourceLabel: route.source === "override" ? t("llm.models.override") : t("llm.models.default"),
      variable: route.source === "override" ? overrideVariable(route.feature) : null,
    }));
}

/** What the read-only pages say about editing: the registry entry that plans it. */
export interface EditNote {
  title: string;
  waitingFor: AwaitedItemView[];
}

export function editNote(): EditNote {
  const edits = screenById("admin.llm.edit-controls");
  return { title: edits.title, waitingFor: edits.awaits.map(toAwaitedItem) };
}
