"use client";

import { useId, useState } from "react";
import {
  Badge,
  Button,
  EmptyState,
  Input,
  Label,
  Select,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { SelectOption } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ALL_ROLES, filterMembers } from "./member-filter";
import type { MemberRow } from "./member-filter";

export interface MemberTableProps {
  rows: readonly MemberRow[];
  /** The roles the members hold, for the role filter. */
  roles: readonly SelectOption[];
}

/** The internal users table with a name-or-email search and a role filter. */
export function MemberTable({ rows, roles }: MemberTableProps) {
  const [query, setQuery] = useState("");
  const [role, setRole] = useState(ALL_ROLES);
  const searchId = useId();
  const roleId = useId();
  const shown = filterMembers(rows, query, role);

  return (
    <div data-slot="member-table" className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor={searchId}>{t("adminTeam.filter.search")}</Label>
          <Input
            id={searchId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5 sm:w-56">
          <Label htmlFor={roleId}>{t("adminTeam.filter.role")}</Label>
          <Select
            id={roleId}
            value={role}
            onChange={(event) => setRole(event.target.value)}
            options={[{ value: ALL_ROLES, label: t("adminTeam.filter.allRoles") }, ...roles]}
          />
        </div>
      </div>
      {shown.length === 0 ? (
        <EmptyState
          heading="h3"
          title={t("adminTeam.noMatchTitle")}
          body={t("adminTeam.noMatchBody")}
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setQuery("");
                setRole(ALL_ROLES);
              }}
            >
              {t("adminTeam.clearFilters")}
            </Button>
          }
        />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted" aria-live="polite">
            {t("adminTeam.caption", { shown: shown.length, total: rows.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("adminTeam.column.name")}</TableHead>
              <TableHead>{t("adminTeam.column.email")}</TableHead>
              <TableHead>{t("adminTeam.column.roles")}</TableHead>
              <TableHead>{t("adminTeam.column.status")}</TableHead>
              <TableHead>{t("adminTeam.column.joined")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.id} data-member={row.id}>
                <TableCell className="font-medium text-fg">{row.name}</TableCell>
                <TableCell>{row.email}</TableCell>
                <TableCell>
                  {row.roles.length === 0 ? (
                    <span className="text-fg-muted">{t("common.none")}</span>
                  ) : (
                    <ul className="flex flex-wrap gap-1">
                      {row.roles.map((held) => (
                        <li key={held.value}>
                          <Badge tone={held.tone}>{held.label}</Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </TableCell>
                <TableCell>
                  <StatusChip
                    status={row.status.value}
                    tone={row.status.tone}
                    label={row.status.label}
                  />
                </TableCell>
                <TableCell className="text-fg-muted">{row.joined}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
