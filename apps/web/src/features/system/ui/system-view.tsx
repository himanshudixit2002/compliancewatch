import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  KeyValue,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RefreshButton } from "@/shared/ui/refresh-button";
import { StatCard } from "@/shared/ui/stat-card";
import type { ServiceRow, SystemSummary } from "../model/system";
import type { WebFacts } from "./system-shared";

export interface SystemViewProps {
  title: string;
  crumbs: readonly Crumb[];
  rows: readonly ServiceRow[];
  summary: SystemSummary;
  facts: WebFacts;
  probeTimeoutSeconds: number;
}

const READY_TONES = { ready: "success", not_ready: "warning", down: "neutral" } as const;

function yesNo(value: boolean): string {
  return value ? t("system.set") : t("system.notSet");
}

/** OpenTelemetry as it registered when this server started, never the flag's value now. */
function telemetryText(telemetry: WebFacts["telemetry"]): string {
  if (telemetry === null) return t("system.telemetryUnknown");
  if (telemetry.failed === true) return t("system.telemetryFailed");
  if (!telemetry.enabled) return t("system.telemetryOff");
  return telemetry.exporting ? t("system.telemetryExporting") : t("system.telemetryLocal");
}

function factItems(facts: WebFacts) {
  return [
    { key: "environment", label: t("system.fact.environment"), value: facts.environment },
    {
      key: "auth",
      label: t("system.fact.authProvider"),
      value: facts.authProvider ?? t("system.notConfigured"),
    },
    { key: "build", label: t("system.fact.build"), value: facts.build ?? t("system.devBuild") },
    { key: "node", label: t("system.fact.node"), value: facts.node },
    {
      key: "timeout",
      label: t("system.fact.timeout"),
      value: t("system.ms", { ms: facts.requestTimeoutMs }),
    },
    { key: "write", label: t("system.fact.writeToken"), value: yesNo(facts.writeToken) },
    { key: "review", label: t("system.fact.reviewToken"), value: yesNo(facts.reviewToken) },
    {
      key: "flags",
      label: t("system.fact.flags"),
      value: facts.flagProvider.ok
        ? facts.flagProvider.name
        : t("system.flagsFailed", { reason: facts.flagProvider.reason }),
    },
    {
      key: "telemetry",
      label: t("system.fact.telemetry"),
      value: telemetryText(facts.telemetry),
    },
  ];
}

/**
 * The services behind the web app as this server sees them: each one's liveness (with its
 * version and the time it took) and readiness (with each dependency check), what the screen
 * registry says about it (the built screens that call it, the routes screens still wait for),
 * and the web server's own facts. The probes run again on Refresh; a stopped service is a row
 * that says so, never a failed page.
 */
export function SystemView({
  title,
  crumbs,
  rows,
  summary,
  facts,
  probeTimeoutSeconds,
}: SystemViewProps) {
  return (
    <div data-slot="system" className="flex flex-col gap-6">
      <PageHeader
        title={title}
        description={t("system.intro", { seconds: probeTimeoutSeconds })}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={<RefreshButton />}
      />
      <div className="grid gap-3 sm:grid-cols-3" data-slot="system-summary">
        <StatCard
          label={t("system.stat.up")}
          value={t("system.ofTotal", { count: summary.up, total: summary.total })}
          tone={summary.up === summary.total ? "success" : "danger"}
        />
        <StatCard
          label={t("system.stat.ready")}
          value={t("system.ofTotal", { count: summary.ready, total: summary.total })}
          tone={summary.ready === summary.total ? "success" : "warning"}
        />
        <StatCard label={t("system.stat.services")} value={summary.total} />
      </div>
      {summary.up === summary.total ? null : (
        <Banner tone="danger" title={t("system.someDown", { count: summary.total - summary.up })}>
          {t("system.someDownBody")}
        </Banner>
      )}
      <Table scrollLabel={t("system.servicesRegion")} data-slot="services-table">
        <TableCaption className="text-left text-sm text-fg-muted">
          {t("system.servicesCaption", { count: rows.length })}
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>{t("system.column.service")}</TableHead>
            <TableHead>{t("system.column.health")}</TableHead>
            <TableHead>{t("system.column.ready")}</TableHead>
            <TableHead>{t("system.column.address")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.service} data-service={row.service}>
              <TableCell className="align-top">
                <code className="font-mono text-sm text-fg">{row.service}</code>
              </TableCell>
              <TableCell className="align-top text-sm">
                <div className="flex flex-col gap-1">
                  <StatusChip
                    status={row.up ? "up" : "down"}
                    tone={row.up ? "success" : "danger"}
                    label={row.healthLabel}
                  />
                  {row.version === null ? null : (
                    <span className="text-xs text-fg-muted">
                      {t("system.version", { version: row.version })}
                    </span>
                  )}
                  <span className="text-xs text-fg-muted">{row.latency}</span>
                  {row.reason === null ? null : (
                    <span className="text-xs text-fg-muted">{row.reason}</span>
                  )}
                </div>
              </TableCell>
              <TableCell className="align-top text-sm">
                <div className="flex flex-col gap-1">
                  <StatusChip
                    status={row.ready}
                    tone={READY_TONES[row.ready]}
                    label={row.readyLabel}
                  />
                  {row.checks.length === 0 ? null : (
                    <ul className="flex flex-col gap-0.5 text-xs text-fg-muted">
                      {row.checks.map((check) => (
                        <li key={check.name}>
                          {check.passed
                            ? t("system.checkPassed", { name: check.name })
                            : t("system.checkFailed", { name: check.name })}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </TableCell>
              <TableCell className="align-top">
                <code className="font-mono text-xs text-fg-muted">{row.baseUrl}</code>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <section aria-labelledby="system-registry" className="flex flex-col gap-3">
        <h2 id="system-registry" className="text-lg font-semibold text-fg">
          {t("system.registryTitle")}
        </h2>
        <p className="max-w-prose text-sm text-fg-muted">{t("system.registryIntro")}</p>
        <Table scrollLabel={t("system.registryRegion")} data-slot="registry-table">
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("system.registryCaption")}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("system.column.service")}</TableHead>
              <TableHead>{t("system.column.screens")}</TableHead>
              <TableHead>{t("system.column.awaited")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.service} data-registry={row.service}>
                <TableCell className="align-top">
                  <code className="font-mono text-sm text-fg">{row.service}</code>
                </TableCell>
                <TableCell className="align-top text-sm">
                  {row.registry.liveScreens.length === 0 ? (
                    <span className="text-fg-muted">{t("common.none")}</span>
                  ) : (
                    <details>
                      <summary className="cursor-pointer">
                        {t("system.screensCount", { count: row.registry.liveScreens.length })}
                      </summary>
                      <ul className="mt-1 flex flex-col gap-0.5">
                        {row.registry.liveScreens.map((screen) => (
                          <li key={screen.id}>
                            {screen.href === null ? (
                              screen.title
                            ) : (
                              <Link
                                href={screen.href as Route}
                                className="text-primary underline-offset-2 hover:underline"
                              >
                                {screen.title}
                              </Link>
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </TableCell>
                <TableCell className="align-top text-sm">
                  {row.registry.awaited.length === 0 ? (
                    <span className="text-fg-muted">{t("common.none")}</span>
                  ) : (
                    <details>
                      <summary className="cursor-pointer">
                        {t("system.awaitedCount", { count: row.registry.awaited.length })}
                      </summary>
                      <ul className="mt-1 flex flex-col gap-1">
                        {row.registry.awaited.map((item) => (
                          <li key={`${item.method} ${item.path}`}>
                            <code className="font-mono text-xs">{`${item.method} ${item.path}`}</code>{" "}
                            <span className="text-xs text-fg-muted">{item.owner}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
      <section aria-labelledby="system-web" className="flex flex-col gap-3">
        <h2 id="system-web" className="text-lg font-semibold text-fg">
          {t("system.webTitle")}
        </h2>
        <KeyValue items={factItems(facts)} data-slot="web-facts" />
      </section>
    </div>
  );
}
