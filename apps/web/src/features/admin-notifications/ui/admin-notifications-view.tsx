import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  ProgressBar,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@compliancewatch/ui";
import type { Channel } from "@/entities/notification/types";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  activeDigestCount,
  channelLabelKey,
  connectedCount,
  digestModeKey,
  dispatchSummary,
  occasionLabelKey,
  stateBucket,
  stateLabelKey,
  stateTone,
} from "../model/admin-notifications";
import type {
  AdminNotificationsData,
  ChannelHealth,
  DigestSchedule,
  DispatchEntry,
} from "../model/admin-notifications";
import { DispatchLogTable } from "./dispatch-log-table";
import type { DispatchRow } from "./dispatch-rows";

export interface AdminNotificationsViewProps {
  data: AdminNotificationsData;
  /** A channel's settings screen; without it the channel cards show no configure link. */
  configureHref?: (channel: Channel) => Route;
}

function lastSent(instant: string | null): string {
  return instant === null ? t("adminNotifications.neverSent") : formatDateTime(instant);
}

function ChannelCard({
  health,
  configureHref,
}: {
  health: ChannelHealth;
  configureHref?: (channel: Channel) => Route;
}) {
  const name = t(channelLabelKey(health.channel));
  return (
    <Card data-channel={health.channel} className="gap-3">
      <CardHeader className="flex flex-row items-center justify-between gap-2 px-4">
        <CardTitle className="text-base font-semibold text-fg">
          <h2>{name}</h2>
        </CardTitle>
        <Badge tone={health.connected ? "success" : "warning"}>
          {t(health.connected ? "adminNotifications.connected" : "adminNotifications.notConnected")}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-4 text-sm text-fg-muted">
        {health.dailyQuota === null ? (
          <p>{t("adminNotifications.sentTodayNoQuota", { count: health.sentToday })}</p>
        ) : (
          <ProgressBar
            label={t("adminNotifications.quotaLabel", { channel: name })}
            value={health.sentToday}
            max={health.dailyQuota}
            valueText={t("adminNotifications.quotaValue", {
              used: health.sentToday,
              limit: health.dailyQuota,
            })}
          />
        )}
        <p>{t("adminNotifications.lastSent", { when: lastSent(health.lastSentAt) })}</p>
        {configureHref === undefined ? null : (
          <Link
            href={configureHref(health.channel)}
            className="w-fit text-primary underline-offset-2 hover:underline"
          >
            {t("adminNotifications.configure", { channel: name })}
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

function DigestTable({ digests }: { digests: readonly DigestSchedule[] }) {
  if (digests.length === 0) {
    return (
      <EmptyState
        title={t("adminNotifications.digests.emptyTitle")}
        body={t("adminNotifications.digests.emptyBody")}
      />
    );
  }
  return (
    <Table data-slot="digest-table">
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("adminNotifications.digests.caption")}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("adminNotifications.column.digest")}</TableHead>
          <TableHead scope="col">{t("adminNotifications.column.mode")}</TableHead>
          <TableHead scope="col">{t("adminNotifications.column.recipients")}</TableHead>
          <TableHead scope="col">{t("adminNotifications.column.lastSent")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {digests.map((digest) => (
          <TableRow key={digest.id} data-digest={digest.id}>
            <TableCell>{digest.label}</TableCell>
            <TableCell>
              <Badge tone={digest.mode === "off" ? "neutral" : "info"}>
                {t(digestModeKey(digest.mode))}
              </Badge>
            </TableCell>
            <TableCell>{digest.recipientCount}</TableCell>
            <TableCell className="whitespace-nowrap text-fg-muted">
              {lastSent(digest.lastSentAt)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function toDispatchRow(entry: DispatchEntry): DispatchRow {
  return {
    id: entry.id,
    occasionLabel: t(occasionLabelKey(entry.occasion)),
    channelLabel: t(channelLabelKey(entry.channel)),
    recipient: entry.recipient,
    state: entry.state,
    stateLabel: t(stateLabelKey(entry.state)),
    tone: stateTone(entry.state),
    bucket: stateBucket(entry.state),
    createdLabel: formatDateTime(entry.createdAt),
  };
}

/** The notifications console: channel health, digest schedules and the latest dispatches. */
export function AdminNotificationsView({ data, configureHref }: AdminNotificationsViewProps) {
  const summary = dispatchSummary(data.dispatchLog);
  return (
    <div data-slot="admin-notifications" className="flex flex-col gap-6">
      <PageHeader
        title={t("adminNotifications.title")}
        description={t("adminNotifications.intro")}
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label={t("adminNotifications.stat.dispatched")} value={summary.total} />
        <StatCard
          label={t("adminNotifications.stat.deliveryRate")}
          value={
            summary.deliveryRate === null
              ? t("adminNotifications.noRate")
              : t("adminNotifications.rate", { rate: summary.deliveryRate })
          }
          tone={summary.failed > 0 ? "warning" : "success"}
          hint={t("adminNotifications.stat.deliveryRateHint", {
            delivered: summary.delivered,
            failed: summary.failed,
          })}
        />
        <StatCard
          label={t("adminNotifications.stat.channels")}
          value={t("adminNotifications.ofTotal", {
            count: connectedCount(data.channels),
            total: data.channels.length,
          })}
          tone="info"
        />
        <StatCard
          label={t("adminNotifications.stat.digests")}
          value={activeDigestCount(data.digests)}
        />
      </div>
      <Tabs defaultValue="channels">
        <TabsList aria-label={t("adminNotifications.tabsLabel")}>
          <TabsTrigger value="channels">{t("adminNotifications.tab.channels")}</TabsTrigger>
          <TabsTrigger value="digests">{t("adminNotifications.tab.digests")}</TabsTrigger>
          <TabsTrigger value="dispatch">{t("adminNotifications.tab.dispatch")}</TabsTrigger>
        </TabsList>
        <TabsContent value="channels" className="pt-2">
          {data.channels.length === 0 ? (
            <EmptyState
              title={t("adminNotifications.channels.emptyTitle")}
              body={t("adminNotifications.channels.emptyBody")}
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {data.channels.map((health) => (
                <ChannelCard key={health.channel} health={health} configureHref={configureHref} />
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="digests" className="pt-2">
          <DigestTable digests={data.digests} />
        </TabsContent>
        <TabsContent value="dispatch" className="pt-2">
          {data.dispatchLog.length === 0 ? (
            <EmptyState
              title={t("adminNotifications.dispatch.emptyTitle")}
              body={t("adminNotifications.dispatch.emptyBody")}
            />
          ) : (
            <DispatchLogTable rows={data.dispatchLog.map(toDispatchRow)} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
