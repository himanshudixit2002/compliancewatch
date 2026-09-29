"use client";

import { useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { Button, type ButtonProps } from "./button";

export interface CopyButtonProps extends Omit<ButtonProps, "onClick" | "children"> {
  /** The text written to the clipboard. */
  value: string;
  /** Accessible name; the visible label is an icon. */
  label?: string;
}

type CopyState = "idle" | "copied" | "failed";

/** Copies a value (a correlation id, an identifier) and announces the outcome. */
export function CopyButton({
  value,
  label = "Copy",
  variant = "ghost",
  ...props
}: CopyButtonProps) {
  const [state, setState] = useState<CopyState>("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <span data-slot="copy-button" className="inline-flex items-center gap-1">
      <Button
        variant={variant}
        size="icon"
        aria-label={label}
        data-state={state}
        onClick={() => void copy()}
        {...props}
      >
        {state === "copied" ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
      </Button>
      <span role="status" className="sr-only">
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : ""}
      </span>
    </span>
  );
}
