import type { Route } from "next";
import Link from "next/link";
import { t } from "@/shared/i18n";
import type { AttributesView as AttributesViewModel } from "../model/business-pages";
import { AnswerForm, type AnswerAction } from "./answer-form";
import { AttributesTable } from "./attributes-table";
import { BusinessPageHeader, type BusinessPageHeaderProps } from "./business-page-header";
import { NodeYearPicker } from "./node-year-picker";

export interface AttributesViewProps {
  title: string;
  view: AttributesViewModel;
  header: Omit<BusinessPageHeaderProps, "title" | "description">;
  /** The page without a query, and the same page for another node or without the edit form. */
  pageHref: string;
  nodeHref: (nodeId: string) => string;
  /** The page for this node and year with the edit form closed. */
  closeHref: string;
  saveAction: AnswerAction;
  fields: { businessId: string; nodeId: string; key: string; asOfFy: string; value: string };
}

/**
 * A node's attributes for one financial year: the values stored on it, those it inherits from
 * the business or its registration (each with the node that holds it), what is not answered yet,
 * and, after "Change" or "Answer", the form for one attribute with the same controls onboarding
 * uses. Saving says which profile version it made.
 */
export function AttributesView({
  title,
  view,
  header,
  pageHref,
  nodeHref,
  closeHref,
  saveAction,
  fields,
}: AttributesViewProps) {
  const { node, editing } = view;
  return (
    <div data-slot="attributes-view" className="flex max-w-5xl flex-col gap-6">
      <BusinessPageHeader
        {...header}
        title={title}
        description={t("business.pageIntro", { name: view.header.name, pan: view.header.pan })}
      />
      <NodeYearPicker
        action={pageHref}
        nodes={view.nodes}
        currentNodeId={node.id}
        fy={view.fy}
        fyChoices={view.fyChoices}
        nodeHref={nodeHref}
      />
      {editing === null ? null : (
        <section
          aria-labelledby="attribute-edit"
          data-slot="attribute-edit"
          className="flex flex-col gap-3 rounded-lg border border-line p-4"
        >
          <h2 id="attribute-edit" className="text-lg font-semibold text-fg">
            {t("attributes.editTitle", { label: editing.label, node: node.display })}
          </h2>
          {editing.asOfFy === null ? null : (
            <p className="text-sm text-fg-muted">{t("question.forYear", { fy: editing.asOfFy })}</p>
          )}
          <AnswerForm
            key={`${node.id}:${editing.key}:${editing.asOfFy ?? ""}`}
            action={saveAction}
            attribute={editing.attribute}
            id="attribute-edit-control"
            label={editing.question}
            description={editing.attribute.help || editing.attribute.definition}
            valueField={fields.value}
            defaultValue={editing.defaultValue}
            hidden={{
              [fields.businessId]: view.header.id,
              [fields.nodeId]: node.id,
              [fields.key]: editing.key,
              [fields.asOfFy]: editing.asOfFy ?? "",
            }}
          />
          <p className="text-sm">
            <Link href={closeHref as Route} className="text-primary underline">
              {t("attributes.closeEdit")}
            </Link>
          </p>
        </section>
      )}
      <section aria-labelledby="attributes-own" className="flex flex-col gap-3">
        <h2 id="attributes-own" className="text-lg font-semibold text-fg">
          {t("attributes.ownTitle", { name: node.display })}
        </h2>
        {view.own.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("attributes.ownNone")}</p>
        ) : (
          <AttributesTable
            rows={view.own}
            caption={t("attributes.ownCaption", { name: node.display, fy: view.fy })}
            variant="own"
          />
        )}
      </section>
      {view.inherited.length > 0 ? (
        <section aria-labelledby="attributes-inherited" className="flex flex-col gap-3">
          <h2 id="attributes-inherited" className="text-lg font-semibold text-fg">
            {t("attributes.inheritedTitle")}
          </h2>
          <p className="text-sm text-fg-muted">{t("attributes.inheritedIntro")}</p>
          <AttributesTable
            rows={view.inherited}
            caption={t("attributes.inheritedCaption", { name: node.display, fy: view.fy })}
            variant="inherited"
          />
        </section>
      ) : null}
      <section aria-labelledby="attributes-unanswered" className="flex flex-col gap-3">
        <h2 id="attributes-unanswered" className="text-lg font-semibold text-fg">
          {t("attributes.unansweredTitle")}
        </h2>
        {view.unanswered.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("attributes.unansweredNone")}</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {view.unanswered.map((item) => (
              <li key={item.key} className="flex flex-wrap gap-2">
                <span>{item.label}</span>
                {item.editHref === null ? null : (
                  <Link href={item.editHref as Route} className="text-primary underline">
                    {t("attributes.answer")} <span className="sr-only">{item.label}</span>
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
