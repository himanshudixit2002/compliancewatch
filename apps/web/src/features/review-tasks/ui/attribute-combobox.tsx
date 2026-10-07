"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { cn } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { EditorAttribute } from "./predicate-tree";

export interface AttributeComboboxProps {
  /** Given by the Field around it, with its description and error. */
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  "aria-required"?: boolean | "true" | "false";
  value: string;
  attributes: readonly EditorAttribute[];
  disabled?: boolean;
  onChange: (key: string) => void;
}

/** The most suggestions the list shows at once. */
const SHOWN = 30;

/** The attributes whose key or meaning holds every word typed, an exact key first. */
export function matchAttributes(
  attributes: readonly EditorAttribute[],
  query: string,
): EditorAttribute[] {
  const words = query
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word !== "");
  const found = attributes.filter((attribute) => {
    const text = `${attribute.key} ${attribute.definition}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
  const exact = query.trim();
  return found.sort((a, b) => Number(b.key === exact) - Number(a.key === exact)).slice(0, SHOWN);
}

/**
 * The attribute of a predicate: a text field that suggests the ontology's attributes by key and
 * meaning as one types (the ARIA combobox with a list: Down and Up move through the suggestions,
 * Enter takes one, Escape closes them, Tab leaves). A key the ontology does not hold may still be
 * typed, for a free-text predicate on an attribute the ontology has yet to gain.
 */
export function AttributeCombobox({
  id,
  value,
  attributes,
  disabled,
  onChange,
  ...aria
}: AttributeComboboxProps) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const matches = open ? matchAttributes(attributes, value) : [];
  const shown = open && matches.length > 0;
  const optionId = (index: number) => `${listId}-option-${index}`;

  const choose = (key: string) => {
    onChange(key);
    setOpen(false);
    setActive(-1);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setOpen(true);
      setActive((current) =>
        Math.min(current + 1, Math.max(matchAttributes(attributes, value).length - 1, 0)),
      );
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter" && shown && active >= 0) {
      event.preventDefault();
      const chosen = matches[active];
      if (chosen !== undefined) choose(chosen.key);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="relative w-full" data-slot="attribute-combobox">
      <input
        id={id}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={shown}
        aria-controls={listId}
        aria-activedescendant={shown && active >= 0 ? optionId(active) : undefined}
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false);
          setActive(-1);
        }}
        onKeyDown={onKeyDown}
        className="h-9 w-full min-w-0 rounded-md border border-line-strong bg-surface-raised px-3 py-1 font-mono text-sm text-fg shadow-xs outline-none focus-visible:border-focus focus-visible:ring-2 focus-visible:ring-focus/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger aria-invalid:ring-danger/30"
        {...aria}
      />
      <ul
        id={listId}
        role="listbox"
        aria-label={t("predicateEditor.suggestions")}
        hidden={!shown}
        className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-line-strong bg-surface-raised py-1 shadow-lg"
      >
        {matches.map((attribute, index) => (
          <li
            key={attribute.key}
            id={optionId(index)}
            role="option"
            aria-selected={index === active}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => choose(attribute.key)}
            className={cn(
              "flex cursor-pointer flex-col gap-0.5 px-3 py-1.5 text-sm",
              index === active ? "bg-primary text-primary-fg" : "text-fg hover:bg-fg/5",
            )}
          >
            <span className="font-mono text-xs">{attribute.key}</span>
            <span className={cn("text-xs", index === active ? "text-primary-fg" : "text-fg-muted")}>
              {attribute.definition}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
