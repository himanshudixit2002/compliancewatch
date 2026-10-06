import "server-only";

import { LLM_FEATURES } from "@/entities/llm/types";
import type { ClientContext } from "@/server/api/services";
import { mapResult, ok, type Result } from "@/server/result";
import { llmRegistryGateway } from "./gateway";
import { modelRows, promptRows, type ModelRow, type PromptRow } from "./model/registry";
import { monthLabel, usageRow, type UsageRead, type UsageRow } from "./model/usage";

/**
 * The LLM gateway pages' reads: the prompts and the model routes (cached), and the spend for the
 * question the usage form asked (fresh): one budget, or every feature's for the month, one read
 * per feature in parallel, failing as a whole when the gateway fails one of them.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export async function getPrompts(deps: QueryDeps = {}): Promise<Result<PromptRow[]>> {
  return mapResult(await llmRegistryGateway(deps).prompts(), promptRows);
}

export async function getModels(deps: QueryDeps = {}): Promise<Result<ModelRow[]>> {
  return mapResult(await llmRegistryGateway(deps).models(), modelRows);
}

export interface UsageView {
  month: string;
  monthLabel: string;
  /** Every feature's budget, or the one the form asked for. */
  overview: boolean;
  rows: UsageRow[];
}

export async function getUsage(
  read: Exclude<UsageRead, { kind: "invalid" }>,
  deps: QueryDeps = {},
): Promise<Result<UsageView>> {
  const gateway = llmRegistryGateway(deps);
  const asked =
    read.kind === "overview"
      ? LLM_FEATURES.map((feature) => ({ feature, month: read.month }))
      : [
          {
            month: read.month,
            ...(read.tenantId === undefined ? {} : { tenantId: read.tenantId }),
            ...(read.feature === undefined ? {} : { feature: read.feature }),
          },
        ];
  const results = await Promise.all(asked.map((query) => gateway.usage(query)));
  const rows: UsageRow[] = [];
  for (const result of results) {
    if (!result.ok) return result;
    rows.push(usageRow(result.value));
  }
  return ok({
    month: read.month,
    monthLabel: monthLabel(read.month),
    overview: read.kind === "overview",
    rows,
  });
}
