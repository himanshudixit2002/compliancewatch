import type { Ref } from "react";
import { Banner, KeyValue } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

/**
 * What creating the business returned (the business model's BusinessStepResult, structurally):
 * a new business or one already on file, and the GSTIN lookup's answer as a list of the values
 * it gave, with the attributes it stored. Without a lookup answer it says so plainly and names
 * the review task the service opened; it never shows a value the lookup did not give.
 */
export interface PrefillPanelResult {
  businessName: string;
  pan: string;
  gstin: string;
  created: boolean;
  lookedUp: boolean;
  rows: readonly { key: string; label: string; value: string }[];
  applied: readonly string[];
  reviewTaskId: string | null;
  progressText: string;
}

export interface PrefillPanelProps {
  result: PrefillPanelResult;
  /** The heading, focused when the panel appears so a screen reader starts here. */
  headingRef?: Ref<HTMLHeadingElement>;
}

export function PrefillPanel({ result, headingRef }: PrefillPanelProps) {
  return (
    <section
      data-slot="prefill-panel"
      aria-labelledby="prefill-panel-heading"
      className="flex flex-col gap-4"
    >
      <h2
        id="prefill-panel-heading"
        ref={headingRef}
        tabIndex={-1}
        className="text-lg font-semibold text-fg outline-none"
      >
        {result.created
          ? t("prefill.created", { name: result.businessName })
          : t("prefill.existing", { name: result.businessName })}
      </h2>
      <KeyValue
        items={[
          { key: "pan", label: t("prefill.pan"), value: result.pan },
          { key: "gstin", label: t("prefill.gstin"), value: result.gstin },
          { key: "progress", label: t("prefill.progress"), value: result.progressText },
        ]}
      />
      {result.lookedUp ? (
        <div data-slot="prefill-lookup" className="flex flex-col gap-3">
          <h3 className="text-base font-semibold text-fg">{t("prefill.lookedUpTitle")}</h3>
          <KeyValue
            items={result.rows.map((row) => ({ key: row.key, label: row.label, value: row.value }))}
          />
          {result.applied.length > 0 ? (
            <p className="text-sm text-fg-muted">
              {t("prefill.applied", { attributes: result.applied.join(", ") })}
            </p>
          ) : (
            <p className="text-sm text-fg-muted">{t("prefill.appliedNone")}</p>
          )}
        </div>
      ) : (
        <Banner tone="info" title={t("prefill.notLookedUpTitle")} data-slot="prefill-manual">
          <p>{t("prefill.notLookedUp")}</p>
          {result.reviewTaskId === null ? null : (
            <p>{t("prefill.reviewTask", { id: result.reviewTaskId })}</p>
          )}
          {result.applied.length > 0 ? (
            <p>{t("prefill.applied", { attributes: result.applied.join(", ") })}</p>
          ) : null}
        </Banner>
      )}
    </section>
  );
}
