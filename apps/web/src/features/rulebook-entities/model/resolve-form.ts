import { ENTITY_TYPES, type EntityType } from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";

/**
 * The resolve tool's GET form: an entity type and a name, kept in the query string (entity
 * names are regulatory references, not personal data), so a resolution can be shared.
 */
export const RESOLVE_PARAMS = { type: "type", name: "name" } as const;

/** The rulebook takes a name of up to 400 characters. */
export const NAME_MAX_LENGTH = 400;

export type ResolveRead =
  | { kind: "empty" }
  | {
      kind: "invalid";
      values: { type: string; name: string };
      errors: Partial<Record<"type" | "name", string>>;
    }
  | { kind: "ok"; entityType: EntityType; name: string };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export function isEntityType(value: string): value is EntityType {
  return (ENTITY_TYPES as readonly string[]).includes(value);
}

/** The form's values from the query: nothing asked yet, refused fields, or a name to resolve. */
export function readResolve(query: Query): ResolveRead {
  const type = first(query, RESOLVE_PARAMS.type).trim();
  const name = first(query, RESOLVE_PARAMS.name);
  if (type === "" && name === "") return { kind: "empty" };
  const errors: Partial<Record<"type" | "name", string>> = {};
  if (!isEntityType(type)) errors.type = t("entities.resolve.typeRequired");
  if (name.trim() === "") errors.name = t("entities.resolve.nameRequired");
  else if (name.length > NAME_MAX_LENGTH) {
    errors.name = t("entities.resolve.nameTooLong", { max: NAME_MAX_LENGTH });
  }
  if (Object.keys(errors).length > 0 || !isEntityType(type)) {
    return { kind: "invalid", values: { type, name }, errors };
  }
  return { kind: "ok", entityType: type, name };
}
