import "server-only";

import { answerFromDto, questionToDto } from "@/entities/answer/mappers";
import type { Answer, Question } from "@/entities/answer/types";
import { businessFromDto } from "@/entities/business/mappers";
import type { Business } from "@/entities/business/types";
import { documentFromDto } from "@/entities/rulebook/mappers";
import type { RulebookDocument } from "@/entities/rulebook/types";
import { call } from "@/server/api/client";
import {
  profileClient,
  qaClient,
  rulebookClient,
  type ClientContext,
  type ProfileClient,
  type QaClient,
  type RulebookClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { AskPort } from "./ports";

/**
 * The ask screen over the typed clients: the qa service's public ask (`POST /v1/qa`, x-tenant-id
 * from the session; an answer is never cached), the business from the profile service, and a
 * cited document from the rulebook, the same for every tenant and kept five minutes under its tag.
 */
export class AskGateway implements AskPort {
  private readonly qa: QaClient;
  private readonly profile: ProfileClient;
  private readonly rulebook: RulebookClient;

  constructor(ctx: ClientContext) {
    this.qa = qaClient(ctx);
    this.profile = profileClient(ctx);
    this.rulebook = rulebookClient({ fetchImpl: ctx.fetchImpl });
  }

  async ask(question: Question): Promise<Result<Answer>> {
    const result = await call(this.qa.POST("/v1/qa", { body: questionToDto(question) }));
    return mapBody(result, answerFromDto);
  }

  async business(businessId: string): Promise<Result<Business>> {
    const result = await call(
      this.profile.GET("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, businessFromDto);
  }

  async document(documentId: string): Promise<Result<RulebookDocument>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/documents/{document_id}", {
        params: { path: { document_id: documentId } },
        ...cachedRead([tags.rulebook.document(documentId)]),
      }),
    );
    return mapBody(result, documentFromDto);
  }
}

export function askGateway(ctx: ClientContext): AskGateway {
  return new AskGateway(ctx);
}
