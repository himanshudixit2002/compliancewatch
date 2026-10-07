"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, CheckboxGroup, Field, Input, Select, Textarea } from "@compliancewatch/ui";
import { specificationFromMapping } from "@/entities/rule-version/mappers";
import { t } from "@/shared/i18n";
import { SpecificationView, describeSpecification, operatorWords } from "@/shared/ui/specification";
import { AttributeCombobox } from "./attribute-combobox";
import {
  addTo,
  attributeOf,
  combineRoot,
  emptyGroup,
  emptyPredicate,
  errorKey,
  fromMapping,
  idSource,
  isMulti,
  mapNode,
  moveNode,
  operatorsFor,
  parseJson,
  removeNode,
  toJson,
  toMapping,
  toggleNot,
  validateTree,
  withAttribute,
  withOperator,
  type EditorOntology,
  type GroupDraft,
  type IdSource,
  type NodeDraft,
  type PredicateDraft,
} from "./predicate-tree";

export interface PredicateEditorProps {
  /** Unique within the page, for the controls' ids. */
  idPrefix: string;
  /** The hidden field the form posts the condition's JSON in. */
  name: string;
  /** The hidden field holding the JSON it was rendered with, so an untouched condition is not sent. */
  baseName: string;
  /** The stored mapping (null or {} for none yet). */
  initial: unknown;
  ontology: EditorOntology | null;
  disabled: boolean;
  /** Show every shape problem: the form was submitted with some. */
  showErrors: boolean;
  /** The action's or the rulebook's message about the condition. */
  error?: string;
  /** How many shape problems the condition has now (an unapplied JSON text counts as one). */
  onProblems: (count: number) => void;
}

interface Context {
  idPrefix: string;
  ontology: EditorOntology | null;
  disabled: boolean;
  errors: Record<string, string>;
  showErrors: boolean;
  newId: IdSource;
  update: (change: (root: NodeDraft) => NodeDraft) => void;
}

function errorOf(
  context: Context,
  id: string,
  field: Parameters<typeof errorKey>[1],
): string | undefined {
  return context.showErrors ? context.errors[errorKey(id, field)] : undefined;
}

function controlId(context: Context, id: string, field: string): string {
  return `${context.idPrefix}-${id}-${field}`;
}

function ValueControl({ node, context }: { node: PredicateDraft; context: Context }) {
  const attribute = attributeOf(context.ontology, node.attribute);
  const multi = isMulti(node.operator);
  const error = errorOf(context, node.id, "value");
  const id = controlId(context, node.id, "value");
  const setValues = (values: string[]) =>
    context.update((root) =>
      mapNode(root, node.id, (found) =>
        found.kind === "predicate"
          ? { ...found, values, types: found.types.slice(0, values.length) }
          : found,
      ),
    );
  const options = attribute?.options ?? [];
  if (options.length > 0 && multi) {
    return (
      <CheckboxGroup
        id={id}
        legend={t("predicateEditor.values")}
        name={`${context.idPrefix}.${node.id}.values`}
        options={options.map((option) => ({ value: option.value, label: option.label }))}
        value={node.values}
        onValueChange={setValues}
        disabled={context.disabled}
        error={error}
        columns={2}
      />
    );
  }
  if (options.length > 0) {
    return (
      <Field id={id} label={t("predicateEditor.value")} error={error}>
        <Select
          value={node.values[0] ?? ""}
          placeholder={t("predicateEditor.choose")}
          disabled={context.disabled}
          onChange={(event) => setValues([event.target.value])}
          options={options.map((option) => ({ value: option.value, label: option.label }))}
        />
      </Field>
    );
  }
  if (attribute?.type === "boolean") {
    return (
      <Field id={id} label={t("predicateEditor.value")} error={error}>
        <Select
          value={node.values[0] ?? ""}
          placeholder={t("predicateEditor.choose")}
          disabled={context.disabled}
          onChange={(event) => setValues([event.target.value])}
          options={[
            { value: "true", label: t("ruleVersion.value.yes") },
            { value: "false", label: t("ruleVersion.value.no") },
          ]}
        />
      </Field>
    );
  }
  if (multi) {
    return (
      <Field
        id={id}
        label={t("predicateEditor.values")}
        description={t("predicateEditor.valuesHelp")}
        error={error}
      >
        <Textarea
          value={node.values.join("\n")}
          rows={3}
          disabled={context.disabled}
          onChange={(event) => setValues(event.target.value.split("\n"))}
        />
      </Field>
    );
  }
  const type = attribute?.type;
  return (
    <Field
      id={id}
      label={t("predicateEditor.value")}
      description={
        type === "date"
          ? t("predicateEditor.dateHelp")
          : type === "integer"
            ? t("predicateEditor.integerHelp")
            : type === "decimal"
              ? t("predicateEditor.decimalHelp")
              : undefined
      }
      error={error}
    >
      <Input
        type={type === "date" ? "date" : "text"}
        inputMode={type === "integer" ? "numeric" : type === "decimal" ? "decimal" : undefined}
        value={node.values[0] ?? ""}
        disabled={context.disabled}
        onChange={(event) => setValues([event.target.value])}
      />
    </Field>
  );
}

function PredicateFields({
  node,
  label,
  context,
}: {
  node: PredicateDraft;
  label: string;
  context: Context;
}) {
  const attribute = attributeOf(context.ontology, node.attribute);
  const operators = operatorsFor(context.ontology, node.attribute);
  const offered =
    node.operator === "" || operators.includes(node.operator)
      ? operators
      : [...operators, node.operator];
  const change = (next: (found: PredicateDraft) => PredicateDraft) =>
    context.update((root) =>
      mapNode(root, node.id, (found) => (found.kind === "predicate" ? next(found) : found)),
    );
  return (
    <fieldset
      className="flex min-w-0 flex-col gap-3 rounded-md border bg-surface-raised p-3"
      data-slot="predicate-fields"
      data-node={node.id}
    >
      <legend className="px-1 text-sm font-medium text-fg">{label}</legend>
      <Field
        id={controlId(context, node.id, "attribute")}
        label={t("predicateEditor.attribute")}
        description={
          node.attribute === ""
            ? t("predicateEditor.attributeHelp")
            : attribute === undefined
              ? t("predicateEditor.attributeUnknown")
              : attribute.definition
        }
        error={errorOf(context, node.id, "attribute")}
        required
      >
        <AttributeCombobox
          value={node.attribute}
          attributes={context.ontology?.attributes ?? []}
          disabled={context.disabled}
          onChange={(key) => change((found) => withAttribute(found, key, context.ontology))}
        />
      </Field>
      <Field
        id={controlId(context, node.id, "operator")}
        label={t("predicateEditor.operator")}
        error={errorOf(context, node.id, "operator")}
      >
        <Select
          value={node.operator}
          disabled={context.disabled}
          onChange={(event) => change((found) => withOperator(found, event.target.value))}
          options={[
            { value: "", label: t("predicateEditor.noOperator") },
            ...offered.map((operator) => ({ value: operator, label: operatorWords(operator) })),
          ]}
        />
      </Field>
      {node.operator === "" ? null : <ValueControl node={node} context={context} />}
      <Field
        id={controlId(context, node.id, "freeText")}
        label={t("predicateEditor.freeText")}
        description={t("predicateEditor.freeTextHelp")}
        error={errorOf(context, node.id, "freeText")}
      >
        <Textarea
          value={node.freeText}
          rows={2}
          disabled={context.disabled}
          onChange={(event) => change((found) => ({ ...found, freeText: event.target.value }))}
        />
      </Field>
    </fieldset>
  );
}

function PartControls({
  node,
  path,
  index,
  count,
  context,
}: {
  node: NodeDraft;
  /** "1.2": where the part stands in the condition. */
  path: string;
  index: number;
  count: number;
  context: Context;
}) {
  const label = path;
  return (
    <div className="flex flex-wrap gap-2" data-slot="part-controls">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={context.disabled || index === 0}
        onClick={() => context.update((root) => moveNode(root, node.id, -1))}
        aria-label={t("predicateEditor.moveUp", { part: label })}
      >
        {t("predicateEditor.up")}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={context.disabled || index === count - 1}
        onClick={() => context.update((root) => moveNode(root, node.id, 1))}
        aria-label={t("predicateEditor.moveDown", { part: label })}
      >
        {t("predicateEditor.down")}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={context.disabled}
        onClick={() => context.update((root) => toggleNot(root, node.id, context.newId))}
        aria-label={
          node.kind === "not"
            ? t("predicateEditor.unnegateNamed", { part: label })
            : t("predicateEditor.negateNamed", { part: label })
        }
      >
        {node.kind === "not" ? t("predicateEditor.unnegate") : t("predicateEditor.negate")}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={context.disabled}
        onClick={() => context.update((root) => removeNode(root, node.id))}
        aria-label={t("predicateEditor.removeNamed", { part: label })}
      >
        {t("predicateEditor.remove")}
      </Button>
    </div>
  );
}

function GroupFields({
  node,
  path,
  context,
}: {
  node: GroupDraft;
  path: string;
  context: Context;
}) {
  const label = t("predicateEditor.group", { label: path });
  return (
    <fieldset
      className="flex min-w-0 flex-col gap-3 rounded-md border border-line-strong p-3"
      data-slot="group-fields"
      data-node={node.id}
      data-mode={node.kind}
    >
      <legend className="px-1 text-sm font-medium text-fg">{label}</legend>
      <Field id={controlId(context, node.id, "mode")} label={t("predicateEditor.groupMode")}>
        <Select
          value={node.kind}
          disabled={context.disabled}
          onChange={(event) =>
            context.update((root) =>
              mapNode(root, node.id, (found) =>
                found.kind === "all_of" || found.kind === "any_of"
                  ? { ...found, kind: event.target.value === "any_of" ? "any_of" : "all_of" }
                  : found,
              ),
            )
          }
          options={[
            { value: "all_of", label: t("predicateEditor.allOf") },
            { value: "any_of", label: t("predicateEditor.anyOf") },
          ]}
        />
      </Field>
      {node.items.length === 0 ? (
        <p className="text-sm text-fg-muted">
          {node.kind === "any_of"
            ? t("ruleVersion.spec.emptyAnyOf")
            : t("ruleVersion.spec.emptyAllOf")}
        </p>
      ) : (
        <ol className="flex flex-col gap-3">
          {node.items.map((item, index) => {
            const itemPath = `${path}.${index + 1}`;
            return (
              <li key={item.id} className="flex flex-col gap-2">
                <NodeFields node={item} path={itemPath} context={context} />
                <PartControls
                  node={item}
                  path={itemPath}
                  index={index}
                  count={node.items.length}
                  context={context}
                />
              </li>
            );
          })}
        </ol>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={context.disabled}
          onClick={() =>
            context.update((root) => addTo(root, node.id, emptyPredicate(context.newId())))
          }
          aria-label={t("predicateEditor.addConditionTo", { group: label })}
        >
          {t("predicateEditor.addCondition")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={context.disabled}
          onClick={() =>
            context.update((root) => addTo(root, node.id, emptyGroup(context.newId(), "any_of")))
          }
          aria-label={t("predicateEditor.addGroupTo", { group: label })}
        >
          {t("predicateEditor.addGroup")}
        </Button>
      </div>
    </fieldset>
  );
}

function NodeFields({ node, path, context }: { node: NodeDraft; path: string; context: Context }) {
  switch (node.kind) {
    case "all_of":
    case "any_of":
      return <GroupFields node={node} path={path} context={context} />;
    case "not":
      return (
        <div
          className="flex flex-col gap-2 rounded-md border border-dashed border-line-strong p-3"
          data-slot="not-fields"
        >
          <p className="text-sm font-medium text-fg">
            {t("predicateEditor.notLead", { label: path })}
          </p>
          <NodeFields node={node.item} path={`${path}.1`} context={context} />
        </div>
      );
    case "predicate":
      return (
        <PredicateFields
          node={node}
          label={t("predicateEditor.condition", { label: path })}
          context={context}
        />
      );
    case "raw":
      return (
        <div
          className="flex flex-col gap-1 rounded-md border border-dashed p-3"
          data-slot="raw-part"
        >
          <p className="text-sm text-fg">{t("predicateEditor.raw", { label: path })}</p>
          <code className="font-mono text-xs break-all text-fg-muted">
            {JSON.stringify(node.raw)}
          </code>
        </div>
      );
  }
}

/**
 * The condition of a draft, built over the kernel's grammar: groups (all of, at least one of)
 * nested at will, a negation around any part, and predicates whose attribute is suggested from
 * the ontology, whose comparison is one the ontology allows on the attribute's type and whose
 * values are the ontology's options where it has them; or free text a person has to judge. The
 * words below it say the condition as the version page will. Experts may edit the JSON instead,
 * which is read back and checked for shape only, within the bounds of D-064 (32 levels, 500
 * parts): the rulebook checks it against the ontology when the draft is saved. The form posts the
 * condition's JSON in a hidden field. Its flagged parts hold the form back only once the condition
 * changed from the one it was rendered with, since an untouched one is never sent.
 */
export function PredicateEditor({
  idPrefix,
  name,
  baseName,
  initial,
  ontology,
  disabled,
  showErrors,
  error,
  onProblems,
}: PredicateEditorProps) {
  const [newId] = useState(() => idSource(`${idPrefix.replace(/[^A-Za-z0-9_-]/g, "")}n`));
  const [start] = useState(() => {
    const tree = fromMapping(initial, newId);
    return { tree, json: JSON.stringify(toMapping(tree, ontology)) };
  });
  const [root, setRoot] = useState<NodeDraft>(start.tree);
  const [mode, setMode] = useState<"build" | "json">("build");
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const errors = useMemo(() => validateTree(root, ontology), [root, ontology]);
  const mapping = useMemo(() => toMapping(root, ontology), [root, ontology]);
  const pendingJson = mode === "json" && jsonText.trim() !== toJson(root, ontology).trim();
  // A condition left as it was rendered is not sent (the form posts it beside its base), so its
  // flagged parts hold nothing back; only a changed one counts them, and an unapplied JSON text.
  const changed = JSON.stringify(mapping) !== start.json;
  const problems = (changed ? Object.keys(errors).length : 0) + (pendingJson ? 1 : 0);

  useEffect(() => {
    onProblems(problems);
  }, [problems, onProblems]);

  const context: Context = {
    idPrefix,
    ontology,
    disabled,
    errors,
    showErrors,
    newId,
    update: (change) => setRoot((current) => change(current)),
  };
  const words = useMemo(() => {
    const node = specificationFromMapping(mapping);
    return node === null ? null : describeSpecification(node, ontology);
  }, [mapping, ontology]);
  const isGroup = root.kind === "all_of" || root.kind === "any_of";
  const jsonId = `${idPrefix}-json`;

  return (
    <fieldset
      className="flex min-w-0 flex-col gap-4"
      data-slot="predicate-editor"
      disabled={disabled}
    >
      <legend className="text-base font-semibold text-fg">{t("predicateEditor.legend")}</legend>
      <p className="max-w-prose text-sm text-fg-muted">{t("predicateEditor.intro")}</p>
      {ontology === null ? (
        <p className="text-sm text-fg-muted">{t("predicateEditor.noOntology")}</p>
      ) : null}
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("predicateEditor.modes")}>
        <Button
          type="button"
          size="sm"
          variant={mode === "build" ? "primary" : "secondary"}
          aria-pressed={mode === "build"}
          onClick={() => {
            setMode("build");
            setJsonError(null);
          }}
        >
          {t("predicateEditor.builder")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={mode === "json" ? "primary" : "secondary"}
          aria-pressed={mode === "json"}
          onClick={() => {
            setJsonText(toJson(root, ontology));
            setJsonError(null);
            setMode("json");
          }}
        >
          {t("predicateEditor.json")}
        </Button>
      </div>
      {mode === "build" ? (
        <div className="flex flex-col gap-3" data-slot="predicate-builder">
          <NodeFields node={root} path="1" context={context} />
          {isGroup ? null : (
            <div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() =>
                  setRoot((current) => combineRoot(current, emptyPredicate(newId()), newId))
                }
              >
                {t("predicateEditor.combine")}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2" data-slot="predicate-json">
          <Field
            id={jsonId}
            label={t("predicateEditor.jsonLabel")}
            description={t("predicateEditor.jsonHelp")}
            error={
              jsonError ??
              (showErrors && pendingJson ? t("predicateEditor.jsonPending") : undefined)
            }
          >
            <Textarea
              value={jsonText}
              rows={14}
              spellCheck={false}
              className="font-mono text-xs"
              onChange={(event) => {
                setJsonText(event.target.value);
                setJsonError(null);
              }}
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => {
                const parsed = parseJson(jsonText, newId);
                if (!parsed.ok) {
                  setJsonError(parsed.problem);
                  return;
                }
                setRoot(parsed.node);
                setJsonError(null);
                setMode("build");
              }}
            >
              {t("predicateEditor.applyJson")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setMode("build");
                setJsonError(null);
              }}
            >
              {t("predicateEditor.discardJson")}
            </Button>
          </div>
        </div>
      )}
      {error === undefined ? null : (
        <p role="alert" className="text-sm text-danger" data-slot="predicate-error">
          {error}
        </p>
      )}
      <div className="flex flex-col gap-2 rounded-md bg-surface p-3" data-slot="predicate-preview">
        <p className="text-sm font-semibold text-fg">{t("predicateEditor.preview")}</p>
        {words === null ? (
          <p className="text-sm text-fg-muted">{t("ruleVersion.spec.none")}</p>
        ) : (
          <SpecificationView line={words} />
        )}
      </div>
      <input type="hidden" name={name} value={JSON.stringify(mapping)} />
      <input type="hidden" name={baseName} value={start.json} />
    </fieldset>
  );
}
