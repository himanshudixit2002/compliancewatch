import type { ComponentProps } from "react";
import { ChevronDownIcon } from "lucide-react";
import { cn } from "../lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<ComponentProps<"select">, "children"> {
  /** Options rendered as <option> elements; pass children instead for grouped options. */
  options?: readonly SelectOption[];
  /** A disabled first option shown while the value is empty. */
  placeholder?: string;
  children?: ComponentProps<"select">["children"];
}

/**
 * A styled native <select>. The browser's own listbox gives keyboard support, type-ahead and
 * screen-reader semantics for free, so no custom popover is needed.
 */
export function Select({ className, options, placeholder, children, ...props }: SelectProps) {
  return (
    <div data-slot="select-wrapper" className="relative w-full">
      <select
        data-slot="select"
        className={cn(
          "h-9 w-full appearance-none rounded-md border border-line-strong bg-surface-raised py-1 pr-9 pl-3 text-base text-fg shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-focus focus-visible:ring-2 focus-visible:ring-focus/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger aria-invalid:ring-danger/30 md:text-sm",
          className,
        )}
        {...props}
      >
        {placeholder !== undefined ? (
          <option value="" disabled>
            {placeholder}
          </option>
        ) : null}
        {options
          ? options.map((option) => (
              <option key={option.value} value={option.value} disabled={option.disabled}>
                {option.label}
              </option>
            ))
          : children}
      </select>
      <ChevronDownIcon
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-fg-muted"
      />
    </div>
  );
}
