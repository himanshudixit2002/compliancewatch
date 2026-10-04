import { Badge } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { SpecLine } from "../model/specification";

export interface SpecificationViewProps {
  line: SpecLine;
}

function Line({ line }: { line: SpecLine }) {
  switch (line.kind) {
    case "group":
      return (
        <div data-slot="spec-group" data-mode={line.mode} className="flex flex-col gap-2">
          <p className="text-sm font-medium text-fg">{line.lead}</p>
          <ul className="ml-5 flex list-disc flex-col gap-2">
            {line.items.map((item, index) => (
              <li key={index} className="text-sm">
                <Line line={item} />
              </li>
            ))}
          </ul>
        </div>
      );
    case "predicate":
      return (
        <div
          data-slot="spec-predicate"
          data-attribute={line.attribute}
          className="flex flex-col gap-1"
        >
          <p className="flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-sm text-fg">
            <code className="rounded-sm bg-surface px-1 font-mono text-xs">{line.attribute}</code>
            {line.condition === null ? null : <span>{line.condition}</span>}
            {line.inOntology ? null : (
              <Badge tone="warning">{t("ruleVersion.spec.notInOntology")}</Badge>
            )}
          </p>
          {line.judgement === null ? null : (
            <p className="text-sm text-fg" data-slot="spec-judgement">
              {t("ruleVersion.spec.judgement", { text: line.judgement })}
            </p>
          )}
          {line.definition === null ? null : (
            <p className="text-xs text-fg-muted">{line.definition}</p>
          )}
        </div>
      );
    case "unreadable":
      return (
        <div data-slot="spec-unreadable" className="flex flex-col gap-1">
          <p className="text-sm text-fg">{t("ruleVersion.spec.unreadable")}</p>
          <code className="font-mono text-xs break-all text-fg-muted">{line.json}</code>
        </div>
      );
  }
}

/**
 * A version's applicability condition in words: the groups that combine predicates, then each
 * predicate with its attribute, the condition worded with the ontology's labels, what an analyst
 * has to judge where it is free text, and the ontology's meaning of the attribute.
 */
export function SpecificationView({ line }: SpecificationViewProps) {
  return (
    <div data-slot="specification" className="flex flex-col gap-2">
      <Line line={line} />
    </div>
  );
}
