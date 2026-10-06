import {
  Button,
  Field,
  Input,
  KeyValue,
  PageHeader,
  ProgressBar,
  Select,
  StatusChip,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import { USAGE_PARAMS, featureOptions, type UsageRead, type UsageRow } from "../model/usage";
import type { UsageView as UsageViewModel } from "../queries";

export interface UsageViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The page itself, without a query: the form's action. */
  pageHref: string;
  read: UsageRead;
  view: UsageViewModel | null;
  error?: ServiceErrorLike;
}

function values(read: UsageRead): { tenant: string; feature: string; month: string } {
  if (read.kind === "invalid") return read.values;
  if (read.kind === "overview") return { tenant: "", feature: "", month: read.month };
  return { tenant: read.tenantId ?? "", feature: read.feature ?? "", month: read.month };
}

function UsageCard({ row }: { row: UsageRow }) {
  return (
    <section
      aria-label={t("llm.usage.cardLabel", { scope: row.scopeLabel, key: row.keyLabel })}
      data-usage={row.key}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-fg">
          {row.scopeLabel}:{" "}
          <span className={row.key.startsWith("tenant:") ? "font-mono text-sm" : undefined}>
            {row.keyLabel}
          </span>
        </h3>
        {row.alarmed ? (
          <StatusChip status="alarmed" tone="danger" label={t("llm.usage.alarmed")} />
        ) : (
          <StatusChip status="within" tone="success" label={t("llm.usage.within")} />
        )}
      </div>
      <ProgressBar
        label={t("llm.usage.share")}
        value={row.barValue}
        valueText={t("llm.usage.shareText", { percent: row.percent, budget: row.budget })}
      />
      <KeyValue
        items={[
          { key: "spent", label: t("llm.usage.spent"), value: row.spent },
          { key: "budget", label: t("llm.usage.budget"), value: row.budget },
          { key: "resets", label: t("llm.usage.resetsAt"), value: row.resetsAt },
        ]}
      />
    </section>
  );
}

/**
 * Spend against the gateway's monthly budgets: every feature's for a month by default, or one
 * tenant's (narrowed to a feature when one is chosen) or one feature's, asked with a GET form.
 * Each budget shows the spend and the ceiling in rupees as the ledger keeps them, the share
 * spent, whether the gateway raised its alarm, and when the budget starts again. Read-only: the
 * budgets are the gateway's settings.
 */
export function UsageView({ title, crumbs, pageHref, read, view, error }: UsageViewProps) {
  const form = values(read);
  const errors = read.kind === "invalid" ? read.errors : {};
  return (
    <div data-slot="llm-usage" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("llm.usage.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("llm.usage.formLabel")}
        data-slot="usage-form"
        noValidate
        className="grid max-w-4xl items-end gap-3 sm:grid-cols-[2fr_1fr_1fr_auto]"
      >
        <Field
          id="usage-tenant"
          label={t("llm.usage.tenant")}
          description={t("llm.usage.tenantHelp")}
          error={errors.tenant}
        >
          <Input
            name={USAGE_PARAMS.tenant}
            defaultValue={form.tenant}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field id="usage-feature" label={t("llm.usage.feature")} error={errors.feature}>
          <Select
            name={USAGE_PARAMS.feature}
            defaultValue={form.feature}
            options={featureOptions()}
          />
        </Field>
        <Field
          id="usage-month"
          label={t("llm.usage.month")}
          description={t("llm.usage.monthHelp")}
          error={errors.month}
        >
          <Input
            name={USAGE_PARAMS.month}
            defaultValue={form.month}
            autoComplete="off"
            inputMode="numeric"
            spellCheck={false}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("llm.usage.submit")}
        </Button>
      </form>
      <p className="max-w-prose text-sm text-fg-muted">{t("llm.usage.budgetsNote")}</p>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {view === null ? null : (
        <section aria-labelledby="usage-results" className="flex flex-col gap-4">
          <h2 id="usage-results" className="text-lg font-semibold text-fg">
            {view.overview
              ? t("llm.usage.overviewTitle", { month: view.monthLabel })
              : t("llm.usage.oneTitle", { month: view.monthLabel })}
          </h2>
          <div className="grid gap-4 md:grid-cols-2" data-slot="usage-cards">
            {view.rows.map((row) => (
              <UsageCard key={row.key} row={row} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
