export type EntityGroupDecision =
  | { kind: "create_entity" }
  | { kind: "add_alias" }
  | { kind: "reject"; reason: RejectReason };

export type RejectReason =
  | "not_an_entity"
  | "wrong_type"
  | "text_artifact"
  | "out_of_scope";

export function entityDecisionLabel(kind: string): string {
  switch (kind) {
    case "create_entity":
      return "Create entity";
    case "add_alias":
      return "Add alias";
    case "reject":
      return "Reject";
    default:
      return "Submit";
  }
}
