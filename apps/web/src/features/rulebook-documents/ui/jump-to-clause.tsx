"use client";

import { useId, useState } from "react";
import { Button, Select } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface JumpOption {
  anchorId: string;
  label: string;
}

export interface JumpToClauseProps {
  options: readonly JumpOption[];
}

/**
 * Moves to one clause: sets the address's #fragment (so the position can be shared and Back
 * returns) and puts focus on the clause, so keyboard and screen-reader users land there too.
 * Every clause also has its own anchor link, so this is a shortcut, not the only way.
 */
export function JumpToClause({ options }: JumpToClauseProps) {
  const id = useId();
  const [anchorId, setAnchorId] = useState(options[0]?.anchorId ?? "");
  if (options.length === 0) return null;
  function jump() {
    const target = document.getElementById(anchorId);
    if (target === null) return;
    window.location.hash = anchorId;
    target.focus();
  }
  return (
    <form
      aria-label={t("documents.jump.label")}
      data-slot="jump-to-clause"
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        jump();
      }}
    >
      <div className="grid gap-1.5">
        <label htmlFor={`${id}-clause`} className="text-sm font-medium text-fg">
          {t("documents.jump.clause")}
        </label>
        <Select
          id={`${id}-clause`}
          value={anchorId}
          onChange={(event) => setAnchorId(event.target.value)}
          options={options.map((option) => ({ value: option.anchorId, label: option.label }))}
          className="min-w-48"
        />
      </div>
      <Button type="submit" variant="secondary">
        {t("documents.jump.go")}
      </Button>
    </form>
  );
}
