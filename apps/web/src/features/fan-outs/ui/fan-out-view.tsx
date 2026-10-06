import type { Route } from "next";
import Link from "next/link";
import {
  EmptyState,
  ErrorState,
  KeyValue,
  PageHeader,
  ProgressBar,
  StatusChip,
  type KeyValueItem,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { addDaysToKey, formatDate, formatDateTime } from "@/shared/lib/dates";
import { levelLabel } from "@/shared/ui/applicability";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { RuleVersionStatusChip, ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import {
  fanOutStatusLabel,
  fanOutStatusMeaning,
  fanOutStatusTone,
  flipsText,
  formatCount,
  lastChangeText,
  progressText,
} from "../model/fan-outs";
import type { FanOutPageView } from "../queries";
import { FanOutControls } from "./fan-out-controls";
import { HoldPanel } from "./hold-panel";
import { RollbackPanel } from "./rollback-panel";
import type { ControlAction } from "./use-control";

export interface FanOutViewProps {
  /** "Fan-out of example_rule v2". */
  title: string;
  /** "example_rule v2", for the dialogs. */
  name: string;
  crumbs: readonly Crumb[];
  view: FanOutPageView;
  /** Where each version the run supersedes opens, and this version's own page in the rulebook. */
  hrefs: {
    fanOut: (ruleVersionId: string) => string;
    version: string;
    /** The impact explorer with this version, for an admin; null for anyone else. */
    dryRun: string | null;
  };
  holdAction: ControlAction;
  controlAction: ControlAction;
  rollbackAction: ControlAction;
}

function RunSection({ view, hrefs }: Pick<FanOutViewProps, "view" | "hrefs">) {
  const { run, version } = view;
  if (run === null) {
    return (
      <EmptyState
        data-slot="no-run"
        title={t("fanOut.noRun.title")}
        body={
          version?.status === "published"
            ? t("fanOut.noRun.published")
            : version === null
              ? t("fanOut.noRun.unknown")
              : t("fanOut.noRun.notPublished", { status: ruleVersionStatusLabel(version.status) })
        }
      />
    );
  }
  const lastChange = lastChangeText(run);
  const items: KeyValueItem[] = [
    { key: "level", label: t("fanOut.facts.level"), value: levelLabel(run.level) },
    { key: "applies", label: t("fanOut.facts.applies"), value: formatCount(run.applies) },
    { key: "flips", label: t("fanOut.facts.flips"), value: flipsText(run) },
    {
      key: "supersedes",
      label: t("fanOut.facts.supersedes"),
      value:
        run.supersedes.length === 0 ? (
          t("fanOut.facts.supersedesNone")
        ) : (
          <ul className="flex flex-col gap-1">
            {run.supersedes.map((id) => (
              <li key={id}>
                <Link
                  href={hrefs.fanOut(id) as Route}
                  className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                >
                  {id}
                </Link>
              </li>
            ))}
          </ul>
        ),
    },
    {
      key: "started",
      label: t("fanOut.facts.started"),
      value: <time dateTime={run.startedAt}>{formatDateTime(run.startedAt)}</time>,
    },
    run.finishedAt === null
      ? {
          key: "updated",
          label: t("fanOut.facts.updated"),
          value: <time dateTime={run.updatedAt}>{formatDateTime(run.updatedAt)}</time>,
        }
      : {
          key: "finished",
          label: t("fanOut.facts.finished"),
          value: <time dateTime={run.finishedAt}>{formatDateTime(run.finishedAt)}</time>,
        },
    {
      key: "change",
      label: t("fanOut.facts.lastChange"),
      value: lastChange ?? t("fanOut.facts.noChange"),
    },
    {
      key: "trigger",
      label: t("fanOut.facts.trigger"),
      value: <code className="font-mono text-xs">{run.triggerEventId}</code>,
      copy: run.triggerEventId,
    },
  ];
  return (
    <div className="flex flex-col gap-4" data-slot="run" data-status={run.status}>
      <p className="flex flex-wrap items-center gap-2 text-sm text-fg">
        <StatusChip
          status={run.status}
          tone={fanOutStatusTone(run.status)}
          label={fanOutStatusLabel(run.status)}
        />
        <span>{fanOutStatusMeaning(run.status)}</span>
      </p>
      <ProgressBar
        label={t("fanOut.progressLabel")}
        value={run.evaluated}
        max={run.businessesTotal}
        valueText={progressText(run)}
        className="max-w-xl"
      />
      {run.lastError === "" ? null : (
        <ErrorState title={t("fanOut.failedTitle")} detail={run.lastError} />
      )}
      <KeyValue items={items} aria-label={t("fanOut.facts.label")} data-slot="run-facts" />
    </div>
  );
}

function VersionSection({ view, hrefs }: Pick<FanOutViewProps, "view" | "hrefs">) {
  const { version, versionFailure } = view;
  if (versionFailure !== null) {
    return (
      <ErrorState
        title={t("fanOut.version.failed")}
        detail={versionFailure.message}
        correlationId={versionFailure.correlationId ?? undefined}
      />
    );
  }
  if (version === null) {
    return <p className="text-sm text-fg-muted">{t("fanOut.version.notHeld")}</p>;
  }
  const items: KeyValueItem[] = [
    {
      key: "version",
      label: t("fanOut.version.name"),
      value: (
        <Link
          href={hrefs.version as Route}
          className="text-primary underline-offset-2 hover:underline"
        >
          {t("fanOuts.versionName", { rule: version.ruleKey, version: version.version })}
        </Link>
      ),
    },
    { key: "title", label: t("fanOut.version.title"), value: version.title },
    {
      key: "status",
      label: t("fanOut.version.status"),
      value: <RuleVersionStatusChip status={version.status} />,
    },
    {
      key: "effective",
      label: t("fanOut.version.effective"),
      value:
        version.effectiveTo === null
          ? t("fanOut.version.from", { from: formatDate(version.effectiveFrom) })
          : t("fanOut.version.between", {
              from: formatDate(version.effectiveFrom),
              to: formatDate(addDaysToKey(version.effectiveTo, -1)),
            }),
    },
    {
      key: "published",
      label: t("fanOut.version.published"),
      value:
        version.publishedAt === null
          ? t("fanOut.version.notPublished")
          : formatDateTime(version.publishedAt),
    },
  ];
  return (
    <div className="flex flex-col gap-3">
      <KeyValue items={items} aria-label={t("fanOut.version.label")} data-slot="version-facts" />
      {hrefs.dryRun === null ? null : (
        <p className="text-sm">
          <Link
            href={hrefs.dryRun as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("fanOut.version.dryRun")}
          </Link>
        </p>
      )}
    </div>
  );
}

/**
 * One rule version's fan-out, for the regulatory team: the global hold, the run (its status in
 * words, how far it got, its flips against the version it supersedes, who changed it last and
 * why, its error), the controls an admin may send it, the rollback through the rulebook's
 * withdraw with its warning, and the version as the rulebook holds it. Everyone else reads.
 */
export function FanOutView({
  title,
  name,
  crumbs,
  view,
  hrefs,
  holdAction,
  controlAction,
  rollbackAction,
}: FanOutViewProps) {
  return (
    <div data-slot="fan-out" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={view.version?.title ?? t("fanOut.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <HoldPanel hold={view.hold} canControl={view.canControl} action={holdAction} />
      <section aria-labelledby="fan-out-run" className="flex flex-col gap-3">
        <h2 id="fan-out-run" className="text-lg font-semibold text-fg">
          {t("fanOut.run.heading")}
        </h2>
        <RunSection view={view} hrefs={hrefs} />
      </section>
      {view.run === null ? null : (
        <section aria-labelledby="fan-out-controls" className="flex flex-col gap-3">
          <h2 id="fan-out-controls" className="text-lg font-semibold text-fg">
            {t("fanOut.control.heading")}
          </h2>
          <FanOutControls
            controls={view.controls}
            canControl={view.canControl}
            name={name}
            action={controlAction}
          />
        </section>
      )}
      <section aria-labelledby="fan-out-rollback" className="flex flex-col gap-3">
        <h2 id="fan-out-rollback" className="text-lg font-semibold text-fg">
          {t("fanOut.rollback.heading")}
        </h2>
        <RollbackPanel rollback={view.rollback} name={name} action={rollbackAction} />
      </section>
      <section aria-labelledby="fan-out-version" className="flex flex-col gap-3">
        <h2 id="fan-out-version" className="text-lg font-semibold text-fg">
          {t("fanOut.version.heading")}
        </h2>
        <VersionSection view={view} hrefs={hrefs} />
      </section>
    </div>
  );
}
