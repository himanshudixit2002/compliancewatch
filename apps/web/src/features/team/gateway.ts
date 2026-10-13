import "server-only";

import { call } from "@/server/api/client";
import { identityClient, type ClientContext, type IdentityClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, mapResult, type Result } from "@/server/result";
import type { Role } from "@/shared/config/roles";
import { teamMemberFromDto, type TeamMember } from "./model/team";

/**
 * The tenant's users over the typed identity client, with the session's bearer: identity's
 * user routes answer a tenant admin's token and nothing else outside header mode. Reads are
 * never cached: the page must show the member just invited, promoted or disabled.
 */
export class TeamGateway {
  private readonly identity: IdentityClient;

  constructor(ctx: ClientContext) {
    this.identity = identityClient(ctx);
  }

  async list(): Promise<Result<TeamMember[]>> {
    const result = await call(this.identity.GET("/v1/identity/users", { ...uncachedRead() }));
    return mapBody(result, (body) => body.items.map(teamMemberFromDto));
  }

  async invite(input: {
    contact: { email?: string; phone?: string };
    displayName: string;
    roles: readonly Role[];
  }): Promise<Result<TeamMember>> {
    const result = await call(
      this.identity.POST("/v1/identity/users", {
        body: {
          ...(input.contact.email === undefined ? {} : { email: input.contact.email }),
          ...(input.contact.phone === undefined ? {} : { phone: input.contact.phone }),
          display_name: input.displayName,
          roles: [...input.roles],
        },
      }),
    );
    return mapBody(result, teamMemberFromDto);
  }

  async changeRoles(userId: string, roles: readonly Role[]): Promise<Result<TeamMember>> {
    const result = await call(
      this.identity.PUT("/v1/identity/users/{user_id}/roles", {
        params: { path: { user_id: userId } },
        body: { roles: [...roles] },
      }),
    );
    return mapBody(result, teamMemberFromDto);
  }

  async disable(userId: string): Promise<Result<TeamMember>> {
    const result = await call(
      this.identity.POST("/v1/identity/users/{user_id}/disable", {
        params: { path: { user_id: userId } },
      }),
    );
    return mapResult(mapBody(result, teamMemberFromDto), (member) => member);
  }
}

export function teamGateway(ctx: ClientContext): TeamGateway {
  return new TeamGateway(ctx);
}
