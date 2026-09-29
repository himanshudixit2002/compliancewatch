import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

export interface JsonViewProps extends Omit<ComponentProps<"pre">, "children"> {
  value: unknown;
  /** Nesting depth that starts expanded; deeper nodes start collapsed. */
  openDepth?: number;
  label?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function Node({
  name,
  value,
  depth,
  openDepth,
}: {
  name?: string;
  value: unknown;
  depth: number;
  openDepth: number;
}) {
  const prefix = name === undefined ? null : <span className="text-fg-muted">{name}: </span>;
  if (Array.isArray(value) || isRecord(value)) {
    const entries = Array.isArray(value)
      ? value.map((item, index) => [String(index), item] as const)
      : Object.entries(value);
    const kind = Array.isArray(value) ? "array" : "object";
    return (
      <details open={depth < openDepth} data-kind={kind} className="pl-4">
        <summary className="-ml-4 cursor-pointer select-none">
          {prefix}
          <span className="text-fg-muted">
            {kind} ({entries.length})
          </span>
        </summary>
        {entries.map(([key, item]) => (
          <Node key={key} name={key} value={item} depth={depth + 1} openDepth={openDepth} />
        ))}
      </details>
    );
  }
  return (
    <div className="pl-4">
      <span className="-ml-4">
        {prefix}
        <span data-kind={value === null ? "null" : typeof value}>{JSON.stringify(value)}</span>
      </span>
    </div>
  );
}

/** A JSON value with collapsible objects and arrays, for admin screens and the catalogue. */
export function JsonView({
  value,
  openDepth = 2,
  label = "JSON",
  className,
  ...props
}: JsonViewProps) {
  return (
    <pre
      data-slot="json-view"
      aria-label={label}
      className={cn(
        "overflow-x-auto rounded-md border bg-surface p-3 font-mono text-xs text-fg",
        className,
      )}
      {...props}
    >
      <Node value={value} depth={0} openDepth={openDepth} />
    </pre>
  );
}
