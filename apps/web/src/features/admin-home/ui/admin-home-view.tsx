import type { Route } from "next";
import Link from "next/link";
import {
  PageHeader,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { AwaitedItemView } from "@/entities/screen/types";
import { t } from "@/shared/i18n";
import { RefreshButton } from "@/shared/ui/refresh-button";
import { ScreenStatusChip } from "@/shared/ui/screen-status-chip";
import type { CountTileView } from "../model/counts";
import type { ServicesSummaryView } from "../model/services";
import type { AdminTool, AdminToolGroup } from "../model/tools";
import { CountTiles } from "./count-tiles";
import { ServicesSummary } from "./services-summary";

export interface AdminHomeViewProps {
  groups: readonly AdminToolGroup[];
  tiles: readonly CountTileView[];
  services: ServicesSummaryView;
  /** The health probe's time limit in seconds, named under the services summary. */
  probeTimeoutSeconds: number;
}

const SHOWN_AWAITS = 3;

function Awaits({ items }: { items: readonly AwaitedItemView[] }) {
  if (items.length === 0) return <span className="text-fg-muted">{t("common.none")}</span>;
  const shown = items.slice(0, SHOWN_AWAITS);
  const rest = items.length - shown.length;
  return (
    <ul className="flex flex-col gap-1">
      {shown.map((item) => (
        <li key={`${item.method} ${item.path}`} className="flex flex-wrap items-center gap-1">
          <code className="rounded-sm bg-surface px-1 py-0.5 font-mono text-xs text-fg">
            {item.method} {item.path}
          </code>
          <span className="text-xs text-fg-muted">{item.owner}</span>
        </li>
      ))}
      {rest > 0 ? (
        <li className="text-xs text-fg-muted">{t("sitemap.more", { count: rest })}</li>
      ) : null}
    </ul>
  );
}

function Services({ tool }: { tool: AdminTool }) {
  if (tool.services.length === 0) return <span className="text-fg-muted">{t("common.none")}</span>;
  return (
    <ul className="flex flex-col gap-1">
      {tool.services.map((service) => (
        <li key={service}>
          <code className="font-mono text-xs text-fg">{t("admin.readmePath", { service })}</code>
        </li>
      ))}
    </ul>
  );
}

/**
 * The admin home: counts of the review queues and registries, whether every service answers,
 * and the internal tools from the registry, grouped like the sidebar, with their status and
 * what each waits for.
 */
export function AdminHomeView({
  groups,
  tiles,
  services,
  probeTimeoutSeconds,
}: AdminHomeViewProps) {
  return (
    <div data-slot="admin-home" className="flex flex-col gap-8">
      <PageHeader
        title={t("admin.title")}
        description={t("admin.intro")}
        actions={<RefreshButton />}
      />
      <section aria-labelledby="admin-counts" className="flex flex-col gap-3">
        <h2 id="admin-counts" className="text-lg font-semibold text-fg">
          {t("admin.counts.heading")}
        </h2>
        <CountTiles tiles={tiles} />
      </section>
      <section aria-labelledby="admin-services" className="flex flex-col gap-3">
        <h2 id="admin-services" className="text-lg font-semibold text-fg">
          {t("admin.services.heading")}
        </h2>
        <ServicesSummary summary={services} timeoutSeconds={probeTimeoutSeconds} />
      </section>
      <h2 className="text-lg font-semibold text-fg">{t("admin.tools")}</h2>
      {groups.map((group) => (
        <Table key={group.key} data-group={group.key}>
          <TableCaption className="text-left text-base font-semibold text-fg">
            {group.label ?? t("admin.group.other")}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.column.tool")}</TableHead>
              <TableHead>{t("admin.column.route")}</TableHead>
              <TableHead>{t("admin.column.roles")}</TableHead>
              <TableHead>{t("admin.column.status")}</TableHead>
              <TableHead>{t("admin.column.waitsFor")}</TableHead>
              <TableHead>{t("admin.column.services")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {group.tools.map((tool) => (
              <TableRow key={tool.id} data-tool={tool.id}>
                <TableCell className="align-top whitespace-normal">
                  <div className="flex flex-col gap-1">
                    {tool.href === null ? (
                      <span className="font-medium text-fg">{tool.title}</span>
                    ) : (
                      <Link
                        href={tool.href as Route}
                        className="font-medium text-primary hover:underline"
                      >
                        {tool.title}
                      </Link>
                    )}
                    {tool.kind !== "page" ? (
                      <span className="text-xs text-fg-muted">
                        {t(`sitemap.kind.${tool.kind}`)}
                      </span>
                    ) : null}
                    <span className="text-xs text-fg-muted">{tool.id}</span>
                  </div>
                </TableCell>
                <TableCell className="align-top">
                  <code className="font-mono text-xs text-fg">{tool.route}</code>
                </TableCell>
                <TableCell className="align-top whitespace-normal text-fg-muted">
                  {tool.roles.join(", ")}
                </TableCell>
                <TableCell className="align-top">
                  <ScreenStatusChip status={tool.status} />
                </TableCell>
                <TableCell className="align-top whitespace-normal">
                  <Awaits items={tool.waitsFor} />
                </TableCell>
                <TableCell className="align-top whitespace-normal">
                  <Services tool={tool} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ))}
    </div>
  );
}
