import { ENTITY_TYPES } from "@/entities/rulebook/types";
import { humanise } from "@/shared/lib/humanise";

/** An entity type as people read it: "hsn_code" is "HSN code". */
export function entityTypeLabel(entityType: string): string {
  return humanise(entityType);
}

/** The entity types for the form's select, in the kernel's order. */
export function entityTypeOptions(): { value: string; label: string }[] {
  return ENTITY_TYPES.map((value) => ({ value, label: entityTypeLabel(value) }));
}
