import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  StatusChip,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import { entityTypeOptions } from "../model/entity-type";
import { NAME_MAX_LENGTH, RESOLVE_PARAMS, type ResolveRead } from "../model/resolve-form";
import type { ResolutionView } from "../model/resolution";

export interface ResolveViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The tool itself, without a query: the form's action. */
  pageHref: string;
  read: ResolveRead;
  /** The rulebook's answer; null before a name is asked, or when the read failed. */
  resolution: ResolutionView | null;
  error?: ServiceErrorLike;
}

function values(read: ResolveRead): { type: string; name: string } {
  if (read.kind === "ok") return { type: read.entityType, name: read.name };
  if (read.kind === "invalid") return read.values;
  return { type: "", name: "" };
}

function Result({ resolution }: { resolution: ResolutionView }) {
  return (
    <section
      aria-labelledby="resolution-heading"
      data-slot="resolution"
      data-status={resolution.status}
      className="flex flex-col gap-4"
    >
      <div className="flex flex-col gap-2">
        <h2 id="resolution-heading" className="text-lg font-semibold text-fg">
          {t("entities.resolve.resultHeading", {
            type: resolution.typeLabel,
            name: resolution.name,
          })}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip
            status={resolution.status}
            tone={resolution.tone}
            label={resolution.statusLabel}
          />
          <span className="text-sm text-fg-muted">{resolution.meaning}</span>
        </div>
        <p className="text-sm text-fg" data-slot="normalised">
          {t("entities.resolve.normalised")}{" "}
          <code className="rounded-sm bg-surface px-1 font-mono">
            {resolution.normalised === ""
              ? t("entities.resolve.nothingLeft")
              : resolution.normalised}
          </code>
        </p>
      </div>
      {resolution.choices.length === 0 ? null : (
        <div className="flex flex-col gap-2">
          <h3 className="text-base font-semibold text-fg">
            {resolution.status === "ambiguous"
              ? t("entities.resolve.pickOne")
              : t("entities.resolve.theEntity")}
          </h3>
          <ul className="flex flex-col gap-2" data-slot="entity-choices">
            {resolution.choices.map((choice) => (
              <li
                key={choice.entityId}
                data-entity={choice.entityId}
                className="flex flex-col gap-1 rounded-md border border-line p-3"
              >
                <Link
                  href={choice.href as Route}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  {t("entities.resolve.open", { type: choice.typeLabel, name: choice.name })}
                </Link>
                <span className="text-sm text-fg-muted">
                  {choice.aliases.length === 0
                    ? t("entities.noAliases")
                    : t("entities.aliasesLine", { aliases: choice.aliases.join(", ") })}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/**
 * The resolve tool: an entity type and a name give what the rulebook's alignment would make of
 * the name (the kernel's normalisation, then the canonical names and aliases), with the status
 * and the entities it points at to open. No route lists the entities, so this is the way in.
 */
export function ResolveView({
  title,
  crumbs,
  pageHref,
  read,
  resolution,
  error,
}: ResolveViewProps) {
  const current = values(read);
  const errors = read.kind === "invalid" ? read.errors : {};
  return (
    <div data-slot="entity-resolve" className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("entities.resolve.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("entities.resolve.formLabel")}
        data-slot="resolve-form"
        noValidate
        className="grid max-w-3xl items-end gap-3 sm:grid-cols-[14rem_1fr_auto]"
      >
        <Field id="resolve-type" label={t("entities.resolve.type")} error={errors.type} required>
          <Select
            name={RESOLVE_PARAMS.type}
            defaultValue={current.type}
            placeholder={t("entities.resolve.typePlaceholder")}
            options={entityTypeOptions()}
          />
        </Field>
        <Field id="resolve-name" label={t("entities.resolve.name")} error={errors.name} required>
          <Input
            name={RESOLVE_PARAMS.name}
            defaultValue={current.name}
            maxLength={NAME_MAX_LENGTH}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("entities.resolve.submit")}
        </Button>
      </form>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {resolution !== null ? (
        <Result resolution={resolution} />
      ) : read.kind === "empty" ? (
        <EmptyState
          title={t("entities.resolve.emptyTitle")}
          body={t("entities.resolve.emptyBody")}
        />
      ) : null}
    </div>
  );
}
