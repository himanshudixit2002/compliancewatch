import type { ReactNode } from "react";
import { Slot } from "radix-ui";
import { cn } from "../lib/cn";
import { describedBy, fieldIds } from "../lib/ids";
import { Label } from "./label";

export interface FieldProps {
  /** The control's id; the description and error ids derive from it. */
  id: string;
  label: ReactNode;
  description?: ReactNode;
  /** One message or the list a validator returns; the field is invalid when any is present. */
  error?: string | readonly string[];
  required?: boolean;
  /** Exactly one control element; it receives id, aria-describedby, aria-invalid and required. */
  children: ReactNode;
  className?: string;
}

/**
 * Label, control, description and error wired together: the control is described by the
 * description and the error, and marked aria-invalid while an error shows.
 */
export function Field({
  id,
  label,
  description,
  error,
  required,
  children,
  className,
}: FieldProps) {
  const ids = fieldIds(id);
  const errors = typeof error === "string" ? [error] : (error ?? []);
  const invalid = errors.length > 0;
  return (
    <div
      data-slot="field"
      data-invalid={invalid || undefined}
      className={cn("grid gap-1.5", className)}
    >
      <Label htmlFor={ids.control}>
        {label}
        {required ? (
          <span aria-hidden="true" className="text-danger">
            *
          </span>
        ) : null}
      </Label>
      <Slot.Root
        id={ids.control}
        aria-describedby={describedBy(
          description ? ids.description : undefined,
          invalid ? ids.error : undefined,
        )}
        aria-invalid={invalid || undefined}
        aria-required={required || undefined}
      >
        {children}
      </Slot.Root>
      {description ? (
        <p id={ids.description} data-slot="field-description" className="text-sm text-fg-muted">
          {description}
        </p>
      ) : null}
      {invalid ? (
        <p id={ids.error} data-slot="field-error" className="text-sm text-danger">
          {errors.join(" ")}
        </p>
      ) : null}
    </div>
  );
}
