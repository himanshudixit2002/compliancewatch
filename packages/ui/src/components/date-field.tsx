import type { ReactNode } from "react";
import { Field } from "./field";
import { Input, type InputProps } from "./input";

export interface DateFieldProps extends Omit<InputProps, "id" | "type" | "min" | "max"> {
  /** The input's id; the description and error ids derive from it. */
  id: string;
  label: ReactNode;
  description?: ReactNode;
  error?: string | readonly string[];
  required?: boolean;
  /** Earliest allowed date, YYYY-MM-DD. */
  min?: string;
  /** Latest allowed date, YYYY-MM-DD. */
  max?: string;
  className?: string;
}

/**
 * A calendar date: the browser's own date input (its picker and its keyboard entry are
 * accessible, and the submitted value is always YYYY-MM-DD whatever the display format),
 * wired to a label, description and error through `Field`. No time and no time zone: a date
 * is a day, and the app renders days in IST.
 */
export function DateField({
  id,
  label,
  description,
  error,
  required,
  min,
  max,
  className,
  ...props
}: DateFieldProps) {
  return (
    <Field
      id={id}
      label={label}
      description={description}
      error={error}
      required={required}
      className={className}
    >
      <Input
        type="date"
        min={min}
        max={max}
        autoComplete="off"
        data-slot="date-field"
        className="max-w-48"
        {...props}
      />
    </Field>
  );
}
