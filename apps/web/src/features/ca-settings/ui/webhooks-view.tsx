import {
  Banner,
  Button,
  CheckboxGroup,
  EmptyState,
  Field,
  Input,
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
import { formatDate } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import {
  DELIVERY_TONE,
  WEBHOOK_EVENTS,
  WEBHOOK_EVENT_LABEL,
  WEBHOOK_FIELDS,
  WEBHOOK_STATUS_LABEL,
  WEBHOOK_STATUS_TONE,
  deliveryOutcome,
  deliveryText,
  webhookCounts,
} from "../model/webhooks";
import type { Webhook } from "../model/webhooks";
import { ConfirmAction } from "./confirm-action";

type FormAction = (formData: FormData) => Promise<void>;

export interface WebhooksViewProps {
  title: string;
  webhooks: readonly Webhook[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  /**
   * Registers an endpoint from WEBHOOK_FIELDS.url and every WEBHOOK_FIELDS.events value checked
   * (`formData.getAll`); the form is left out without it.
   */
  createAction?: FormAction;
  /** Sends a test event to the endpoint whose id is submitted as WEBHOOK_FIELDS.webhookId. */
  testAction?: FormAction;
  /** Removes the endpoint whose id is submitted as WEBHOOK_FIELDS.webhookId. */
  removeAction?: FormAction;
}

function CreateWebhookForm({ action }: { action: FormAction }) {
  return (
    <section
      aria-labelledby="webhook-create-title"
      data-slot="webhook-create"
      className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4"
    >
      <h2 id="webhook-create-title" className="text-base font-semibold text-fg">
        {t("caSettings.webhooks.create.title")}
      </h2>
      <form action={action} className="flex flex-col gap-4">
        <Field
          id="webhook-url"
          label={t("caSettings.webhooks.create.url")}
          description={t("caSettings.webhooks.create.urlHelp")}
          className="max-w-xl"
          required
        >
          <Input
            name={WEBHOOK_FIELDS.url}
            type="url"
            pattern="https://.+"
            maxLength={2048}
            autoComplete="off"
            required
          />
        </Field>
        <CheckboxGroup
          id="webhook-events"
          legend={t("caSettings.webhooks.create.events")}
          description={t("caSettings.webhooks.create.eventsHelp")}
          name={WEBHOOK_FIELDS.events}
          options={WEBHOOK_EVENTS.map((event) => ({
            value: event,
            label: t(WEBHOOK_EVENT_LABEL[event]),
          }))}
          defaultValue={WEBHOOK_EVENTS}
          columns={2}
        />
        <Button type="submit" className="self-start">
          {t("caSettings.webhooks.create.submit")}
        </Button>
      </form>
    </section>
  );
}

function RowActions({
  webhook,
  testAction,
  removeAction,
}: {
  webhook: Webhook;
  testAction?: FormAction;
  removeAction?: FormAction;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {testAction === undefined ? null : (
        <form action={testAction}>
          <input type="hidden" name={WEBHOOK_FIELDS.webhookId} value={webhook.id} />
          <Button type="submit" variant="ghost" size="sm">
            {t("caSettings.webhooks.test")} <span className="sr-only">{webhook.url}</span>
          </Button>
        </form>
      )}
      {removeAction === undefined ? null : (
        <ConfirmAction
          action={removeAction}
          fields={{ [WEBHOOK_FIELDS.webhookId]: webhook.id }}
          label={t("caSettings.webhooks.remove.label")}
          subject={webhook.url}
          title={t("caSettings.webhooks.remove.title")}
          description={t("caSettings.webhooks.remove.body", { url: webhook.url })}
          confirmLabel={t("caSettings.webhooks.remove.confirm")}
        />
      )}
    </div>
  );
}

function WebhookRow({
  webhook,
  testAction,
  removeAction,
}: {
  webhook: Webhook;
  testAction?: FormAction;
  removeAction?: FormAction;
}) {
  const outcome = deliveryOutcome(webhook.lastDelivery);
  const hasActions = testAction !== undefined || removeAction !== undefined;
  return (
    <TableRow data-webhook={webhook.id}>
      <TableCell className="align-top whitespace-normal">
        <code className="font-mono text-xs break-all text-fg">{webhook.url}</code>
        <span className="block pt-1 text-xs text-fg-muted">
          {t("caSettings.webhooks.added", { date: formatDate(webhook.createdAt) })}
        </span>
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        <ul className="flex flex-col gap-0.5 text-xs text-fg">
          {webhook.events.map((event) => (
            <li key={event}>{t(WEBHOOK_EVENT_LABEL[event])}</li>
          ))}
        </ul>
      </TableCell>
      <TableCell className="align-top">
        <StatusChip
          status={webhook.status}
          tone={WEBHOOK_STATUS_TONE[webhook.status]}
          label={t(WEBHOOK_STATUS_LABEL[webhook.status])}
        />
      </TableCell>
      <TableCell className="align-top whitespace-normal">
        <StatusChip
          status={outcome}
          tone={DELIVERY_TONE[outcome]}
          label={deliveryText(webhook.lastDelivery)}
        />
      </TableCell>
      {hasActions ? (
        <TableCell className="align-top">
          <RowActions webhook={webhook} testAction={testAction} removeAction={removeAction} />
        </TableCell>
      ) : null}
    </TableRow>
  );
}

/**
 * The webhooks settings page: the settings header, the form to add an endpoint when adding is
 * possible, a warning when deliveries to an endpoint are paused, and every endpoint with the
 * events it receives, whether it is active and how its latest delivery went.
 */
export function WebhooksView({
  title,
  webhooks,
  crumbs,
  tabs,
  createAction,
  testAction,
  removeAction,
}: WebhooksViewProps) {
  const counts = webhookCounts(webhooks);
  const hasActions = testAction !== undefined || removeAction !== undefined;
  return (
    <div data-slot="ca-webhooks" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("caSettings.webhooks.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {counts.paused === 0 ? null : (
        <Banner
          tone="warning"
          title={t("caSettings.webhooks.paused.title", {
            count: counts.paused,
            total: counts.total,
          })}
        >
          {t("caSettings.webhooks.paused.body")}
        </Banner>
      )}
      {createAction === undefined ? null : <CreateWebhookForm action={createAction} />}
      {webhooks.length === 0 ? (
        <EmptyState
          title={t("caSettings.webhooks.emptyTitle")}
          body={t("caSettings.webhooks.emptyBody")}
        />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("caSettings.webhooks.caption", { total: counts.total, paused: counts.paused })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("caSettings.webhooks.column.endpoint")}</TableHead>
              <TableHead>{t("caSettings.webhooks.column.events")}</TableHead>
              <TableHead>{t("caSettings.webhooks.column.status")}</TableHead>
              <TableHead>{t("caSettings.webhooks.column.lastDelivery")}</TableHead>
              {hasActions ? (
                <TableHead>
                  <span className="sr-only">{t("caSettings.column.actions")}</span>
                </TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {webhooks.map((webhook) => (
              <WebhookRow
                key={webhook.id}
                webhook={webhook}
                testAction={testAction}
                removeAction={removeAction}
              />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
