import type { Route } from "next";
import Link from "next/link";
import { Button, DateField, Field, Select, type SelectOption } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface ObligationFiltersProps {
  /** The list itself, without a query: the form's GET action and the reset link. */
  action: string;
  status: string;
  options: readonly SelectOption[];
  /** What was typed into the window, valid or not, so a refused value stays on screen. */
  from: string;
  to: string;
  errors: { from?: string; to?: string };
  maxDays: number;
}

/**
 * The list's status and due window as a GET form: the choice is in the address, so the back
 * button and a shared link work. The window says the service's limit up front (366 days) and a
 * longer one is refused on its field, never shortened behind the person's back.
 */
export function ObligationFilters({
  action,
  status,
  options,
  from,
  to,
  errors,
  maxDays,
}: ObligationFiltersProps) {
  return (
    <form
      method="get"
      action={action}
      aria-label={t("obligations.filter.form")}
      data-slot="obligation-filters"
      className="flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-start gap-4">
        <Field id="obligation-status" label={t("obligations.filter.status")} className="w-56">
          <Select key={status} name="status" defaultValue={status} options={options} />
        </Field>
        <DateField
          id="obligation-from"
          name="from"
          label={t("obligations.filter.from")}
          defaultValue={from}
          error={errors.from}
        />
        <DateField
          id="obligation-to"
          name="to"
          label={t("obligations.filter.to")}
          defaultValue={to}
          error={errors.to}
        />
      </div>
      <p className="max-w-prose text-xs text-fg-muted">
        {t("obligations.window.limit", { max: maxDays })}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="secondary" size="sm">
          {t("obligations.filter.submit")}
        </Button>
        <Link
          href={action as Route}
          className="text-sm text-primary underline-offset-2 hover:underline"
        >
          {t("obligations.filter.reset")}
        </Link>
      </div>
    </form>
  );
}
