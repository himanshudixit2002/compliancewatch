/**
 * Team model: types and server query stub for the team members screen.
 */

export interface TeamMemberView {
  id: string;
  name: string;
  email: string;
  role: string;
  status: "active" | "invited" | "disabled";
  joinedAt: string;
  lastActiveAt: string | null;
}

export async function teamMembers(): Promise<
  { ok: true; value: TeamMemberView[] } | { ok: false; error: { kind: string; message: string } }
> {
  // TODO: call identity service GET /v1/identity/users
  return { ok: true, value: [] };
}
