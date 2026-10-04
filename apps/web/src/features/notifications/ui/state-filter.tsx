import { Button, Field, Select } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { StateOption } from "../model/notifications";

export interface StateFilterProps {
  /** The page itself, without a query. */
  action: string;
  state: string | undefined;
  options: readonly StateOption[];
  /** The other query values the page keeps, such as an admin lookup's tenant and business. */
  keep?: Readonly<Record<string, string>>;
}

/**
 * Which delivery state the history shows, as a GET form: the choice is in the URL, so the back
 * button and a shared link work, and choosing starts again from the newest page.
 */
export function StateFilter({ action, state, options, keep = {} }: StateFilterProps) {
  return (
    <form
      method="get"
      action={action}
      aria-label={t("notificationLog.filterForm")}
      data-slot="state-filter"
      className="flex flex-wrap items-end gap-2"
    >
      {Object.entries(keep).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      <Field id="notification-state" label={t("notificationLog.filterLabel")} className="w-56">
        <Select key={state ?? ""} name="state" defaultValue={state ?? ""} options={options} />
      </Field>
      <Button type="submit" variant="secondary" size="sm">
        {t("notificationLog.filterSubmit")}
      </Button>
    </form>
  );
}
