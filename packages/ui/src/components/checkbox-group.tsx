"use client";

import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";
import { describedBy, fieldIds } from "../lib/ids";
import { useControllableState } from "../hooks/use-controllable-state";
import { Checkbox } from "./checkbox";
import { Label } from "./label";

export interface CheckboxGroupOption {
  value: string;
  label: ReactNode;
  /** A line under the option's label; the box is described by it. */
  description?: ReactNode;
  disabled?: boolean;
}

export interface CheckboxGroupProps extends Omit<
  ComponentProps<"fieldset">,
  "defaultValue" | "onChange" | "id"
> {
  /** The group's id; the description, error and option ids derive from it. */
  id: string;
  /** The question the group answers, rendered as the fieldset's legend. */
  legend: ReactNode;
  description?: ReactNode;
  /** One message or several; the group is invalid while any is present. */
  error?: string | readonly string[];
  /** The form field name every checked box submits its value under. */
  name: string;
  options: readonly CheckboxGroupOption[];
  /** The checked values, for a controlled group. */
  value?: readonly string[];
  defaultValue?: readonly string[];
  onValueChange?: (value: string[]) => void;
  required?: boolean;
  /** Options per row from the sm breakpoint up. */
  columns?: 1 | 2 | 3;
}

const COLUMNS = { 1: "", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3" } as const;

/**
 * Several choices under one question: a fieldset whose legend is the question, one checkbox per
 * option, each with its own label. Tab moves between the boxes and Space toggles one (Radix
 * Checkbox). Inside a form every checked box submits `name=value`, so the server reads the
 * choice with `formData.getAll(name)`. The fieldset is described by the description and the
 * error and marked invalid while an error shows.
 */
export function CheckboxGroup({
  id,
  legend,
  description,
  error,
  name,
  options,
  value,
  defaultValue = [],
  onValueChange,
  required,
  columns = 1,
  disabled,
  className,
  ...props
}: CheckboxGroupProps) {
  const ids = fieldIds(id);
  const errors = typeof error === "string" ? [error] : (error ?? []);
  const invalid = errors.length > 0;
  const [checked, setChecked] = useControllableState<readonly string[]>({
    value,
    defaultValue,
    onChange: onValueChange ? (next) => onValueChange([...next]) : undefined,
  });

  const toggle = (option: string, on: boolean) => {
    const next = on ? [...checked, option] : checked.filter((item) => item !== option);
    // Keep the options' order, whatever order the boxes were ticked in.
    setChecked(options.map((item) => item.value).filter((candidate) => next.includes(candidate)));
  };

  return (
    <fieldset
      id={id}
      data-slot="checkbox-group"
      data-invalid={invalid || undefined}
      aria-describedby={describedBy(
        description ? ids.description : undefined,
        invalid ? ids.error : undefined,
      )}
      aria-invalid={invalid || undefined}
      disabled={disabled}
      className={cn("grid gap-2", className)}
      {...props}
    >
      <legend className="mb-1 text-sm font-medium text-fg">
        {legend}
        {required ? (
          <>
            <span aria-hidden="true" className="text-danger">
              {" "}
              *
            </span>
            <span className="sr-only"> (required)</span>
          </>
        ) : null}
      </legend>
      {description ? (
        <p id={ids.description} data-slot="field-description" className="text-sm text-fg-muted">
          {description}
        </p>
      ) : null}
      <div className={cn("grid gap-2", COLUMNS[columns])}>
        {options.map((option) => {
          const boxId = `${id}-${option.value}`;
          const hintId = `${boxId}-description`;
          return (
            <div key={option.value} className="flex items-start gap-2">
              <Checkbox
                id={boxId}
                name={name}
                value={option.value}
                checked={checked.includes(option.value)}
                onCheckedChange={(state) => toggle(option.value, state === true)}
                disabled={disabled || option.disabled}
                aria-describedby={option.description ? hintId : undefined}
                className="mt-0.5"
              />
              <div className="grid gap-0.5">
                <Label htmlFor={boxId} className="leading-snug">
                  {option.label}
                </Label>
                {option.description ? (
                  <p id={hintId} className="text-xs text-fg-muted">
                    {option.description}
                  </p>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      {invalid ? (
        <p id={ids.error} data-slot="field-error" className="text-sm text-danger">
          {errors.join(" ")}
        </p>
      ) : null}
    </fieldset>
  );
}
