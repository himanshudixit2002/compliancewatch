import type { ReactNode } from "react";
import {
  CheckboxGroup,
  DateField,
  Field,
  Input,
  Label,
  NumberField,
  RadioGroup,
  RadioGroupItem,
  cn,
  describedBy,
  fieldIds,
} from "@compliancewatch/ui";
import type { OntologyAttribute, OntologyOption } from "@/entities/ontology/types";
import { t } from "@/shared/i18n";

/**
 * The one place a control is chosen for an attribute, by its ontology type:
 *
 *   enum, ordered_enum   radio buttons in the ontology's order (ascending for ordered bands)
 *   boolean              Yes and No radio buttons
 *   enum_set             a checkbox group; long lists run in columns
 *   integer, decimal     a number field with the range from the ontology
 *   date                 the browser's date input
 *   string               a text input
 *
 * Every control submits under `name` (every ticked box of a set under the same name), so the
 * action reads `formData.getAll(name)` and parses it with `parseAnswer`. The labels are the
 * ontology's wording, never the app's; the state of the answer (known, not sure, does not
 * apply) is chosen by the form's submit buttons (`AnswerButtons`), not here.
 */
export interface AttributeControlProps {
  attribute: OntologyAttribute;
  /** Prefix for the control's element ids; unique on the page. */
  id: string;
  /** The form field the value is submitted under. */
  name?: string;
  /** What the control is labelled with: the question, or the attribute's name. */
  label: ReactNode;
  /** Shown under the label: the ontology's help line or definition. */
  description?: ReactNode;
  /** Keeps the label for screen readers only, when a heading already asks the question. */
  hideLabel?: boolean;
  defaultValue?: string | readonly string[];
  error?: string;
  disabled?: boolean;
}

/** Sets longer than this lay their options out in columns. */
const COLUMN_THRESHOLD = 8;

function booleanOptions(): OntologyOption[] {
  return [
    { value: "true", label: t("attribute.yes") },
    { value: "false", label: t("attribute.no") },
  ];
}

function single(value: string | readonly string[] | undefined): string | undefined {
  return typeof value === "string" ? value : value?.[0];
}

interface ChoiceProps extends Omit<AttributeControlProps, "attribute"> {
  options: readonly OntologyOption[];
}

/** Radio buttons labelled by the question: Radix's radiogroup, arrow keys move the choice. */
function Choice({
  id,
  name,
  label,
  description,
  hideLabel,
  options,
  defaultValue,
  error,
  disabled,
}: ChoiceProps) {
  const ids = fieldIds(id);
  const labelId = `${id}-label`;
  return (
    <div data-slot="attribute-choice" className="grid gap-2">
      <p id={labelId} className={cn("text-sm font-medium text-fg", hideLabel && "sr-only")}>
        {label}
      </p>
      {description ? (
        <p id={ids.description} className="text-sm text-fg-muted">
          {description}
        </p>
      ) : null}
      <RadioGroup
        id={id}
        name={name}
        defaultValue={single(defaultValue)}
        disabled={disabled}
        aria-labelledby={labelId}
        aria-describedby={describedBy(
          description ? ids.description : undefined,
          error ? ids.error : undefined,
        )}
        aria-invalid={error ? true : undefined}
        className={cn("gap-2", options.length > COLUMN_THRESHOLD && "sm:grid-cols-2")}
      >
        {options.map((option) => {
          const optionId = `${id}-${option.value}`;
          return (
            <div key={option.value} className="flex items-center gap-2">
              <RadioGroupItem id={optionId} value={option.value} />
              <Label htmlFor={optionId}>{option.label}</Label>
            </div>
          );
        })}
      </RadioGroup>
      {error ? (
        <p id={ids.error} data-slot="field-error" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function AttributeControl(props: AttributeControlProps) {
  const {
    attribute,
    id,
    name = "value",
    label,
    description,
    hideLabel,
    defaultValue,
    error,
    disabled,
  } = props;
  const visibleLabel = hideLabel ? <span className="sr-only">{label}</span> : label;
  switch (attribute.type) {
    case "enum":
    case "ordered_enum":
      return <Choice {...props} name={name} options={attribute.options} />;
    case "boolean":
      return <Choice {...props} name={name} options={booleanOptions()} />;
    case "enum_set":
      return (
        <CheckboxGroup
          id={id}
          name={name}
          legend={visibleLabel}
          description={description}
          options={attribute.options}
          defaultValue={typeof defaultValue === "string" ? [defaultValue] : defaultValue}
          error={error}
          disabled={disabled}
          columns={attribute.options.length > COLUMN_THRESHOLD ? 3 : 1}
        />
      );
    case "integer":
    case "decimal":
      return (
        <NumberField
          id={id}
          name={name}
          label={visibleLabel}
          description={description}
          integer={attribute.type === "integer"}
          min={attribute.min}
          max={attribute.max}
          defaultValue={single(defaultValue)}
          error={error}
          disabled={disabled}
        />
      );
    case "date":
      return (
        <DateField
          id={id}
          name={name}
          label={visibleLabel}
          description={description}
          defaultValue={single(defaultValue)}
          error={error}
          disabled={disabled}
        />
      );
    case "string":
      return (
        <Field id={id} label={visibleLabel} description={description} error={error}>
          <Input
            name={name}
            defaultValue={single(defaultValue)}
            disabled={disabled}
            autoComplete="off"
          />
        </Field>
      );
  }
}
