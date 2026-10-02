import type { ReactNode } from "react";
import { Field } from "./field";
import { Input, type InputProps } from "./input";

export interface NumberFieldProps extends Omit<
  InputProps,
  "id" | "type" | "inputMode" | "min" | "max" | "step"
> {
  /** The input's id; the description and error ids derive from it. */
  id: string;
  label: ReactNode;
  description?: ReactNode;
  error?: string | readonly string[];
  required?: boolean;
  /** Whole numbers only (the default); false allows a decimal point. */
  integer?: boolean;
  min?: number | null;
  max?: number | null;
  /** Replaces the range sentence built from min and max; null shows none. */
  rangeHint?: ReactNode;
  className?: string;
}

const NUMBER = new Intl.NumberFormat("en-IN");

/** "Between 0 and 1,00,000.", "At least 1.", "At most 10.", or null without bounds. */
export function rangeText(min?: number | null, max?: number | null): string | null {
  const low = typeof min === "number" ? NUMBER.format(min) : null;
  const high = typeof max === "number" ? NUMBER.format(max) : null;
  if (low !== null && high !== null) return `Between ${low} and ${high}.`;
  if (low !== null) return `At least ${low}.`;
  if (high !== null) return `At most ${high}.`;
  return null;
}

/**
 * A number typed as text: a text input with the numeric (or decimal) keyboard on phones, and
 * the allowed range said in words under it, because a native number input changes its value on
 * a scroll and reads out poorly. The server parses and checks the value; this field only
 * describes what it accepts. Label, description, range and error are wired through `Field`.
 */
export function NumberField({
  id,
  label,
  description,
  error,
  required,
  integer = true,
  min,
  max,
  rangeHint,
  className,
  ...props
}: NumberFieldProps) {
  const range = rangeHint === undefined ? rangeText(min, max) : rangeHint;
  const hint =
    description && range ? (
      <>
        {description} {range}
      </>
    ) : (
      (description ?? range ?? undefined)
    );
  return (
    <Field
      id={id}
      label={label}
      description={hint}
      error={error}
      required={required}
      className={className}
    >
      <Input
        type="text"
        inputMode={integer ? "numeric" : "decimal"}
        autoComplete="off"
        data-slot="number-field"
        className="max-w-48"
        {...props}
      />
    </Field>
  );
}
