import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { Input } from "@compliancewatch/ui";

export interface FilterBarProps {
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
  };
  children?: ReactNode;
  onClear?: () => void;
}

export function FilterBar({ search, children, onClear }: FilterBarProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      {search ? (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted" />
          <Input
            type="search"
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
            placeholder={search.placeholder ?? "Search…"}
            className="pl-9"
          />
        </div>
      ) : (
        <div />
      )}
      <div className="flex items-center gap-2">
        {children}
        {onClear && (search?.value || children) ? (
          <button
            type="button"
            onClick={onClear}
            className="text-sm text-fg-muted underline-offset-4 hover:text-fg hover:underline"
          >
            Clear
          </button>
        ) : null}
      </div>
    </div>
  );
}
