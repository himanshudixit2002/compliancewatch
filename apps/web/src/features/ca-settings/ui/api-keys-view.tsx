import {
  Banner,
  Button,
  CopyButton,
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
import { formatDate, formatDateTime } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import {
  API_KEY_FIELDS,
  API_KEY_NAME_MAX,
  API_KEY_STATUS_LABEL,
  API_KEY_STATUS_TONE,
  apiKeyCounts,
  apiKeyStatus,
  keyHint,
  sortApiKeys,
} from "../model/api-keys";
import type { ApiKey, NewApiKey } from "../model/api-keys";
import { ConfirmAction } from "./confirm-action";

type FormAction = (formData: FormData) => Promise<void>;

export interface ApiKeysViewProps {
  title: string;
  keys: readonly ApiKey[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  /** Creates a key named by API_KEY_FIELDS.name; the create form is left out without it. */
  createAction?: FormAction;
  /** Revokes the key whose id is API_KEY_FIELDS.keyId; no revoke buttons show without it. */
  revokeAction?: FormAction;
  /** The key the create action has just made: the only time its whole secret is shown. */
  newKey?: NewApiKey;
}

function NewKeyBanner({ newKey }: { newKey: NewApiKey }) {
  return (
    <Banner
      tone="success"
      title={t("caSettings.apiKeys.newKey.title", { name: newKey.name })}
      data-slot="new-api-key"
    >
      <p>{t("caSettings.apiKeys.newKey.body")}</p>
      <div className="mt-2 flex items-center gap-1">
        <code className="rounded-sm border border-line bg-surface px-2 py-1 font-mono text-xs break-all text-fg">
          {newKey.secret}
        </code>
        <CopyButton value={newKey.secret} label={t("caSettings.apiKeys.newKey.copy")} />
      </div>
    </Banner>
  );
}

function CreateKeyForm({ action }: { action: FormAction }) {
  return (
    <section
      aria-labelledby="api-key-create-title"
      data-slot="api-key-create"
      className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4"
    >
      <h2 id="api-key-create-title" className="text-base font-semibold text-fg">
        {t("caSettings.apiKeys.create.title")}
      </h2>
      <form action={action} className="flex max-w-md flex-col gap-3">
        <Field
          id="api-key-name"
          label={t("caSettings.apiKeys.create.name")}
          description={t("caSettings.apiKeys.create.nameHelp")}
          required
        >
          <Input
            name={API_KEY_FIELDS.name}
            maxLength={API_KEY_NAME_MAX}
            autoComplete="off"
            required
          />
        </Field>
        <Button type="submit" className="self-start">
          {t("caSettings.apiKeys.create.submit")}
        </Button>
      </form>
    </section>
  );
}

function KeyRow({ apiKey, revokeAction }: { apiKey: ApiKey; revokeAction?: FormAction }) {
  const status = apiKeyStatus(apiKey);
  return (
    <TableRow data-api-key={apiKey.id}>
      <TableCell className="font-medium text-fg">{apiKey.name}</TableCell>
      <TableCell>
        <code className="font-mono text-xs text-fg">{keyHint(apiKey)}</code>
      </TableCell>
      <TableCell className="text-fg-muted">{formatDate(apiKey.createdAt)}</TableCell>
      <TableCell className="text-fg-muted">
        {apiKey.lastUsedAt === null ? t("caSettings.never") : formatDateTime(apiKey.lastUsedAt)}
      </TableCell>
      <TableCell>
        <StatusChip
          status={status}
          tone={API_KEY_STATUS_TONE[status]}
          label={t(API_KEY_STATUS_LABEL[status])}
        />
        {apiKey.revokedAt === null ? null : (
          <span className="block pt-1 text-xs text-fg-muted">
            {t("caSettings.apiKeys.revokedOn", { date: formatDate(apiKey.revokedAt) })}
          </span>
        )}
      </TableCell>
      {revokeAction === undefined ? null : (
        <TableCell>
          {status === "active" ? (
            <ConfirmAction
              action={revokeAction}
              fields={{ [API_KEY_FIELDS.keyId]: apiKey.id }}
              label={t("caSettings.apiKeys.revoke.label")}
              subject={apiKey.name}
              title={t("caSettings.apiKeys.revoke.title", { name: apiKey.name })}
              description={t("caSettings.apiKeys.revoke.body")}
              confirmLabel={t("caSettings.apiKeys.revoke.confirm")}
            />
          ) : null}
        </TableCell>
      )}
    </TableRow>
  );
}

/**
 * The API keys settings page: the settings header, the new key's secret right after it is made,
 * the create form when creating is possible, and every key (working ones first) by its name,
 * its first and last characters, when it was made and last used, and whether it still works.
 */
export function ApiKeysView({
  title,
  keys,
  crumbs,
  tabs,
  createAction,
  revokeAction,
  newKey,
}: ApiKeysViewProps) {
  const counts = apiKeyCounts(keys);
  return (
    <div data-slot="ca-api-keys" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("caSettings.apiKeys.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {newKey === undefined ? null : <NewKeyBanner newKey={newKey} />}
      {createAction === undefined ? null : <CreateKeyForm action={createAction} />}
      {keys.length === 0 ? (
        <EmptyState
          title={t("caSettings.apiKeys.emptyTitle")}
          body={t("caSettings.apiKeys.emptyBody")}
        />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("caSettings.apiKeys.caption", { active: counts.active, revoked: counts.revoked })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("caSettings.apiKeys.column.name")}</TableHead>
              <TableHead>{t("caSettings.apiKeys.column.key")}</TableHead>
              <TableHead>{t("caSettings.apiKeys.column.created")}</TableHead>
              <TableHead>{t("caSettings.apiKeys.column.lastUsed")}</TableHead>
              <TableHead>{t("caSettings.apiKeys.column.status")}</TableHead>
              {revokeAction === undefined ? null : (
                <TableHead>
                  <span className="sr-only">{t("caSettings.column.actions")}</span>
                </TableHead>
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortApiKeys(keys).map((apiKey) => (
              <KeyRow key={apiKey.id} apiKey={apiKey} revokeAction={revokeAction} />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
