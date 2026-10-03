import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  EmptyState,
  Label,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import {
  DATA_REQUEST_FIELDS,
  DATA_REQUEST_KINDS,
  KIND_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
  newestFirst,
  openRequestOf,
} from "../model/data-rights";
import type { DataRequest, DataRequestKind } from "../model/data-rights";

type FormAction = (formData: FormData) => Promise<void>;

export interface DataRightsViewProps {
  title: string;
  requests: readonly DataRequest[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  /**
   * Records a request of the kind submitted as DATA_REQUEST_FIELDS.kind; a deletion also carries
   * DATA_REQUEST_FIELDS.confirm. The request forms are left out without it.
   */
  requestAction?: FormAction;
  /** Where a completed copy is downloaded; without it no download link is shown. */
  exportHref?: (requestId: string) => Route;
}

const SECTION_WORDS: Readonly<
  Record<DataRequestKind, { title: MessageKey; body: MessageKey; submit: MessageKey }>
> = {
  export: {
    title: "dataRights.export.title",
    body: "dataRights.export.body",
    submit: "dataRights.export.submit",
  },
  deletion: {
    title: "dataRights.deletion.title",
    body: "dataRights.deletion.body",
    submit: "dataRights.deletion.submit",
  },
};

function RequestSection({
  kind,
  open,
  action,
}: {
  kind: DataRequestKind;
  open: DataRequest | undefined;
  action: FormAction;
}) {
  const headingId = `data-rights-${kind}`;
  const words = SECTION_WORDS[kind];
  return (
    <section
      aria-labelledby={headingId}
      data-request-kind={kind}
      className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4"
    >
      <h2 id={headingId} className="text-base font-semibold text-fg">
        {t(words.title)}
      </h2>
      <p className="text-sm text-fg-muted">{t(words.body)}</p>
      {open === undefined ? (
        <form action={action} className="flex flex-col gap-3">
          <input type="hidden" name={DATA_REQUEST_FIELDS.kind} value={kind} />
          {kind === "deletion" ? (
            <div className="flex items-start gap-2">
              <input
                id="data-rights-confirm-deletion"
                type="checkbox"
                name={DATA_REQUEST_FIELDS.confirm}
                value="yes"
                required
                className="mt-0.5 size-4 shrink-0 accent-danger"
              />
              <Label htmlFor="data-rights-confirm-deletion" className="leading-snug">
                {t("dataRights.deletion.confirm")}
              </Label>
            </div>
          ) : null}
          <Button
            type="submit"
            variant={kind === "deletion" ? "danger" : "secondary"}
            className="self-start"
          >
            {t(words.submit)}
          </Button>
        </form>
      ) : (
        <p className="text-sm text-fg" data-slot="open-request">
          {t("dataRights.open", {
            date: formatDate(open.requestedAt),
            due: formatDate(open.dueBy),
          })}
        </p>
      )}
    </section>
  );
}

function RequestRow({
  request,
  exportHref,
}: {
  request: DataRequest;
  exportHref?: (requestId: string) => Route;
}) {
  const downloadHref =
    exportHref !== undefined && request.kind === "export" && request.status === "completed"
      ? exportHref(request.id)
      : undefined;
  return (
    <TableRow data-request={request.id}>
      <TableCell className="font-medium text-fg">
        {t(KIND_LABEL[request.kind])}
        {downloadHref === undefined ? null : (
          <Link
            href={downloadHref}
            className="block pt-1 text-xs font-normal text-primary underline-offset-2 hover:underline"
          >
            {t("dataRights.download")}{" "}
            <span className="sr-only">
              {t("dataRights.downloadOf", { date: formatDate(request.requestedAt) })}
            </span>
          </Link>
        )}
      </TableCell>
      <TableCell>
        <StatusChip
          status={request.status}
          tone={STATUS_TONE[request.status]}
          label={t(STATUS_LABEL[request.status])}
        />
      </TableCell>
      <TableCell className="text-fg-muted">{formatDate(request.requestedAt)}</TableCell>
      <TableCell className="text-fg-muted">{formatDate(request.dueBy)}</TableCell>
      <TableCell className="text-fg-muted">
        {request.closedAt === null ? t("dataRights.notClosed") : formatDate(request.closedAt)}
      </TableCell>
    </TableRow>
  );
}

/**
 * The data rights settings page: the settings header, a form to ask for a copy of the account's
 * data and one to ask for its deletion (each replaced by a note while such a request is open,
 * and left out when requests cannot be made), then every request newest first with its status,
 * when it was made, when it is due and when it closed, and the download of a completed copy.
 */
export function DataRightsView({
  title,
  requests,
  crumbs,
  tabs,
  requestAction,
  exportHref,
}: DataRightsViewProps) {
  return (
    <div data-slot="data-rights" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("dataRights.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {requestAction === undefined ? null : (
        <div className="grid gap-4 md:grid-cols-2">
          {DATA_REQUEST_KINDS.map((kind) => (
            <RequestSection
              key={kind}
              kind={kind}
              open={openRequestOf(requests, kind)}
              action={requestAction}
            />
          ))}
        </div>
      )}
      <section aria-labelledby="data-rights-requests" className="flex flex-col gap-3">
        <h2 id="data-rights-requests" className="text-lg font-semibold text-fg">
          {t("dataRights.requestsTitle")}
        </h2>
        {requests.length === 0 ? (
          <EmptyState
            heading="h3"
            title={t("dataRights.emptyTitle")}
            body={t("dataRights.emptyBody")}
          />
        ) : (
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("dataRights.caption")}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("dataRights.column.request")}</TableHead>
                <TableHead>{t("dataRights.column.status")}</TableHead>
                <TableHead>{t("dataRights.column.requested")}</TableHead>
                <TableHead>{t("dataRights.column.due")}</TableHead>
                <TableHead>{t("dataRights.column.closed")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {newestFirst(requests).map((request) => (
                <RequestRow key={request.id} request={request} exportHref={exportHref} />
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
