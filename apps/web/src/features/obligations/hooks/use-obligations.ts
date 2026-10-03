"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { obligation } from "@compliancewatch/contracts/openapi";
import { ok, type Result } from "@/server/result";
import { obligationClient } from "@/server/api/services";
import { emptyObligations, type ObligationView, type ObligationFilter } from "../model/obligations";

export type ObligationSort = "due" | "status" | "created" | "title";

export function useObligations(
  businessId: string,
  filter: ObligationFilter = "all",
  sort: ObligationSort = "due",
) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ObligationView>(() => emptyObligations(businessId));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const client = obligationClient({ session: null as any, tenantId: businessId });
      const response = await client.GET("/v1/obligation/obligations", {});
      if (response.error) {
        setError(response.error.detail || "Failed to load obligations");
        return;
      }
      const obligations: obligation.components["schemas"]["ObligationOut"][] = response.data ?? [];
      const now = new Date();
      const mapped: ObligationView["obligations"] = obligations.map((o) => ({
        id: o.obligation_id,
        businessId: o.business_id,
        title: o.title,
        description: "",
        status: o.status,
        dueAt: o.due_at,
        evidenceType: o.evidence_type,
        steps: o.steps,
        ruleVersionId: o.rule_version_id,
        decisionId: o.decision_id,
        closedAt: o.closed_at,
        closedReason: o.closed_reason ?? null,
        periodStart: o.period_start,
        periodEnd: o.period_end,
        periodLabel: o.period_label,
      }));
      const openCount = mapped.filter((o) => o.status === "open").length;
      const inProgressCount = mapped.filter((o) => o.status === "in_progress").length;
      const doneCount = mapped.filter((o) => o.status === "done").length;
      const overdueCount = mapped.filter((o) => {
        if (
          !o.dueAt ||
          o.status === "done" ||
          o.status === "waived" ||
          o.status === "closed_not_applicable"
        )
          return false;
        return new Date(o.dueAt) < now;
      }).length;

      setView({
        obligations: mapped,
        businessId,
        totalCount: mapped.length,
        openCount,
        inProgressCount,
        doneCount,
        overdueCount,
        filter,
        sort,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load obligations");
    } finally {
      setLoading(false);
    }
  }, [businessId, filter, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  return useMemo(
    () => ({
      view,
      loading,
      error,
      refresh: load,
    }),
    [view, loading, error, load],
  );
}
