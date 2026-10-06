import "server-only";

import { randomUUID } from "node:crypto";
import { createElement, type ReactElement } from "react";
import type { RouteRef } from "@/shared/config/services";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { isUuid } from "@/shared/lib/identifiers";
import { mapResult, type Result } from "../result";
import { call, type CallOutcome } from "./client";

/**
 * The Idempotency-Key a creating write may carry, so a form submitted twice (a retry after a
 * lost response, a double click the pending state did not catch) records one thing.
 *
 * The key is minted once per render: a page puts `<IdempotencyKeyInput />` inside the form,
 * the browser sends the same hidden value on every submit of that render, and the server action
 * turns it into the header with `idempotencyHeaders(formData, operation)`. The header is sent
 * only for an operation in `IDEMPOTENT_OPERATIONS`: the routes that read it, which answer 428
 * without it and replay the first response for 24 hours (py-common's idempotency module): the
 * business API's two creating POSTs, the applicability engine's evaluate, which appends a
 * decision each time, the obligation service's status, assignee and comment writes, which the
 * public API serves under `/v1/obligations` as well, and a CA firm's bulk change card. The
 * pipeline's retry of a stored document reads it too, but keeps the key on the retry it records:
 * the same request replays its attempt for as long as the retry is kept, not for 24 hours. The
 * other creating writes are safe to repeat without it because each has a natural key on the
 * service:
 *
 *   profile registration     the GSTIN: a second POST returns the existing node, created false
 *   profile entity           the PAN, the same way
 *   profile location         the label under its registration
 *   identity consents        append-only: a repeat adds a row and the state stays the same
 *   rulebook documents       the sha256: 201 created, 200 unchanged, 409 when the metadata
 *                            differs
 *   rulebook mentions and    the document and the extractor: a repeat reports `unchanged`
 *   relation candidates
 *   notification preference  PUT by channel and recipient: a replacement, not an addition
 *
 * When another route starts reading the header, its operation joins `IDEMPOTENT_ROUTES` and
 * nothing else changes; idempotency.test.ts fails until it does. A key that is not a UUID is
 * ignored: the form value cannot inject an arbitrary header.
 */
export const IDEMPOTENCY_KEY_HEADER = "Idempotency-Key";

/** The hidden input's name; the action reads it from the FormData under this key. */
export { IDEMPOTENCY_KEY_FIELD };

/**
 * The header a service adds to an answer it replays for a repeated key and request (py-common's
 * idempotency module): the write happened once, earlier, and this is its first answer again.
 */
export const REPLAYED_HEADER = "Idempotent-Replayed";

/**
 * The operations whose route requires Idempotency-Key, named `<service>.<verb>`, with that
 * route. idempotency.test.ts holds the list to the committed specs both ways: every route here
 * declares the header, and every route that requires it is here.
 */
export const IDEMPOTENT_ROUTES = {
  "profile.create-business": { service: "profile", method: "POST", path: "/v1/businesses" },
  "profile.add-registration": {
    service: "profile",
    method: "POST",
    path: "/v1/businesses/{business_id}/registrations",
  },
  "applicability-engine.evaluate": {
    service: "applicability-engine",
    method: "POST",
    path: "/v1/applicability-engine/businesses/{business_id}/decisions",
  },
  "obligation.change-status": {
    service: "obligation",
    method: "POST",
    path: "/v1/obligation/obligations/{obligation_id}/status",
  },
  "obligation.assign": {
    service: "obligation",
    method: "PUT",
    path: "/v1/obligation/obligations/{obligation_id}/assignee",
  },
  "obligation.comment": {
    service: "obligation",
    method: "POST",
    path: "/v1/obligation/obligations/{obligation_id}/comments",
  },
  "obligation.public-change-status": {
    service: "obligation",
    method: "POST",
    path: "/v1/obligations/{obligation_id}/status",
  },
  "obligation.public-assign": {
    service: "obligation",
    method: "PUT",
    path: "/v1/obligations/{obligation_id}/assignee",
  },
  "obligation.public-comment": {
    service: "obligation",
    method: "POST",
    path: "/v1/obligations/{obligation_id}/comments",
  },
  "notification.bulk": {
    service: "notification",
    method: "POST",
    path: "/v1/notification/bulk",
  },
  "pipeline.retry-document": {
    service: "pipeline",
    method: "POST",
    path: "/v1/pipeline/documents/{document_id}/retry",
  },
} as const satisfies Readonly<Record<string, RouteRef>>;

export type IdempotentOperation = keyof typeof IDEMPOTENT_ROUTES;

/** The names in `IDEMPOTENT_ROUTES`, the operations `idempotencyHeaders` sends a key for. */
export const IDEMPOTENT_OPERATIONS: ReadonlySet<string> = new Set<string>(
  Object.keys(IDEMPOTENT_ROUTES),
);

export function newIdempotencyKey(): string {
  return randomUUID();
}

export function isIdempotentOperation(
  operation: string,
  operations: ReadonlySet<string> = IDEMPOTENT_OPERATIONS,
): boolean {
  return operations.has(operation);
}

/** The key the form carried, or undefined when absent or not a UUID. */
export function idempotencyKeyOf(formData: FormData): string | undefined {
  const value = formData.get(IDEMPOTENCY_KEY_FIELD);
  return typeof value === "string" && isUuid(value) ? value : undefined;
}

/**
 * `{ "Idempotency-Key": key }` when the operation is allow-listed and the form carried a valid
 * key; `{}` otherwise. Spread into the call's headers: `headers: { ...idempotencyHeaders(...) }`.
 */
export function idempotencyHeaders(
  formData: FormData,
  operation: string,
  operations: ReadonlySet<string> = IDEMPOTENT_OPERATIONS,
): Readonly<Record<string, string>> {
  if (!isIdempotentOperation(operation, operations)) return {};
  const key = idempotencyKeyOf(formData);
  return key === undefined ? {} : { [IDEMPOTENCY_KEY_HEADER]: key };
}

/** An idempotent write's answer, and whether the service replayed it for a repeated key. */
export interface Replayable<T> {
  value: T;
  replayed: boolean;
}

/**
 * `call()` for a write sent with an Idempotency-Key: the value, plus whether the answer is the
 * replay of an earlier one (`Idempotent-Replayed: true`), so a form can say that a retry recorded
 * nothing twice. A failure is the same `ApiError` `call` gives.
 */
export async function callIdempotent<T>(
  promise: Promise<CallOutcome<T>>,
): Promise<Result<Replayable<T>>> {
  let replayed = false;
  const result = await call(
    promise.then((outcome) => {
      replayed = outcome.response.headers.get(REPLAYED_HEADER) === "true";
      return outcome;
    }),
  );
  return mapResult(result, (value) => ({ value, replayed }));
}

/** A hidden input holding one key for this render of the form; a server component. */
export function IdempotencyKeyInput(): ReactElement {
  return createElement("input", {
    type: "hidden",
    name: IDEMPOTENCY_KEY_FIELD,
    value: newIdempotencyKey(),
  });
}
