import type { Route } from "next";
import Link from "next/link";
import { Banner } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { ServicesSummaryView } from "../model/services";

export interface ServicesSummaryProps {
  summary: ServicesSummaryView;
  /** The probe's time limit, in seconds, for the note under the summary. */
  timeoutSeconds: number;
}

/** How many services answer their health check, and the address and reason of each that does not. */
export function ServicesSummary({ summary, timeoutSeconds }: ServicesSummaryProps) {
  const allUp = summary.down.length === 0;
  return (
    <div data-slot="services-summary" className="flex flex-col gap-3">
      <Banner
        tone={allUp ? "success" : "warning"}
        title={
          allUp
            ? t("admin.services.allUp", { total: summary.total })
            : t("admin.services.someUp", { up: summary.up, total: summary.total })
        }
        action={
          summary.systemHref === null ? undefined : (
            <Link href={summary.systemHref as Route} className="text-primary underline">
              {t("admin.services.system")}
            </Link>
          )
        }
      >
        {allUp ? null : (
          <ul className="flex flex-col gap-1">
            {summary.down.map((service) => (
              <li key={service.service} data-service={service.service}>
                <span className="font-medium">{service.service}</span>{" "}
                <code className="font-mono text-xs">{service.baseUrl}</code>
                {": "}
                {service.reason}
              </li>
            ))}
          </ul>
        )}
      </Banner>
      <p className="text-xs text-fg-muted">
        {t("admin.services.note", { seconds: timeoutSeconds })}
      </p>
    </div>
  );
}
