"use client";

import { useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Icon,
  PageHeader,
  SearchInput,
  Select,
  StatCard,
  Table,
  Tabs,
} from "@compliancewatch/ui";
import type { AdminTeamView, AdminMember, AdminInvitation } from "../model/admin-team";
import { memberRoleBadge, memberStatusBadge } from "../model/admin-team";

export interface AdminTeamViewProps {
  view: AdminTeamView;
  inviteHref?: Route;
}

const TABS = [
  { value: "members", label: "Members" },
  { value: "invitations", label: "Invitations" },
  { value: "roles", label: "Roles" },
];

function MembersTable({ members }: { members: AdminMember[] }) {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");

  const filtered = members.filter((m) => {
    if (
      search &&
      !m.name.toLowerCase().includes(search.toLowerCase()) &&
      !m.email.toLowerCase().includes(search.toLowerCase())
    ) {
      return false;
    }
    if (roleFilter !== "all" && m.role !== roleFilter) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row">
        <SearchInput
          placeholder="Search members..."
          value={search}
          onChange={setSearch}
          className="flex-1"
        />
        <Select
          value={roleFilter}
          onChange={setRoleFilter}
          options={[
            { value: "all", label: "All roles" },
            ...members
              .filter((m, i, arr) => arr.findIndex((x) => x.role === m.role) === i)
              .map((m) => ({ value: m.role, label: m.roleLabel })),
          ]}
          className="w-full sm:w-48"
        />
        <Button asChild>
          <Link href="/admin/team/invite">Invite member</Link>
        </Button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<Icon name="users" className="h-8 w-8 text-fg-muted" />}
          title="No members found"
          description="Try adjusting your search or filters."
        />
      ) : (
        <div className="overflow-hidden rounded-md border border-line">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead>Last active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((member) => (
                <TableRow key={member.id}>
                  <TableCell className="font-medium text-fg">{member.name}</TableCell>
                  <TableCell>{member.email}</TableCell>
                  <TableCell>
                    <Badge
                      tone={
                        member.role === "admin"
                          ? "warning"
                          : member.role === "compliance_lead"
                            ? "info"
                            : "neutral"
                      }
                    >
                      {memberRoleBadge(member.role)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge
                      tone={
                        member.status === "active"
                          ? "success"
                          : member.status === "invited"
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {memberStatusBadge(member.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>{new Date(member.joinedAt).toLocaleDateString()}</TableCell>
                  <TableCell className="text-fg-muted">
                    {member.lastActiveAt ? new Date(member.lastActiveAt).toLocaleString() : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function InvitationsTable({ invitations }: { invitations: AdminInvitation[] }) {
  if (invitations.length === 0) {
    return (
      <EmptyState
        icon={<Icon name="mail" className="h-8 w-8 text-fg-muted" />}
        title="No pending invitations"
        description="All invitations have been accepted or expired."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-md border border-line">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Invited by</TableHead>
            <TableHead>Sent</TableHead>
            <TableHead>Expires</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invitations.map((inv) => (
            <TableRow key={inv.id}>
              <TableCell className="font-medium">{inv.email}</TableCell>
              <TableCell>
                <Badge tone={inv.role === "admin" ? "warning" : "neutral"}>{inv.roleLabel}</Badge>
              </TableCell>
              <TableCell>{inv.invitedBy}</TableCell>
              <TableCell>{new Date(inv.invitedAt).toLocaleDateString()}</TableCell>
              <TableCell className="text-fg-muted">
                {new Date(inv.expiresAt).toLocaleDateString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** The admin team management page. */
export function AdminTeamView({ view }: AdminTeamViewProps) {
  const [tab, setTab] = useState("members");
  const [search, setSearch] = useState("");

  const statCards = [
    { label: "Total members", value: view.totalMembers, tone: "info" },
    { label: "Pending invites", value: view.pendingInvitations.length, tone: "warning" },
    { label: "Roles available", value: view.availableRoles.length, tone: "neutral" },
  ];

  return (
    <div data-slot="admin-team" className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <PageHeader
          title="Team management"
          description="Manage team members, roles and invitations"
        />
        <div className="grid gap-4 sm:grid-cols-3">
          {statCards.map((stat) => (
            <StatCard key={stat.label} {...stat} />
          ))}
        </div>
      </div>

      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {tab === "members" && <MembersTable members={view.members} />}
      {tab === "invitations" && <InvitationsTable invitations={view.pendingInvitations} />}
      {tab === "roles" && (
        <Card>
          <h3 className="text-sm font-medium text-fg">Available roles</h3>
          <p className="mt-2 text-sm text-fg-muted">
            {view.availableRoles.map((role) => memberRoleBadge(role)).join(", ")}
          </p>
        </Card>
      )}
    </div>
  );
}
