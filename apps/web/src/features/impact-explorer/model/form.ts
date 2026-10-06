import type { DryRunRequest } from "@/entities/applicability/types";
import { t } from "@/shared/i18n";
import { isHexUuid, isUuid } from "@/shared/lib/identifiers";
import {
  DEFAULT_SAMPLES,
  DRY_RUN_FIELDS,
  MAX_SAMPLES,
  SPECIFICATION_MAX_LENGTH,
  type DryRunFormValues,
  type LevelChoice,
} from "../ui/dry-run-shared";

/**
 * The dry run form, read and checked before the engine is asked: a rule version by its id, or a
 * specification (the kernel's predicate tree as JSON, with the level it is decided at); one tenant
 * or every tenant; how many decisions to keep as samples. The engine owns the rules (a malformed
 * predicate, a level that is not the version's, a scope over its maximum): its refusals come back
 * as its problem.
 */
export const LEVELS: readonly Exclude<LevelChoice, "">[] = ["entity", "registration", "location"];

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function isLevel(value: string): value is LevelChoice {
  return value === "" || (LEVELS as readonly string[]).includes(value);
}

/** What the form held when it was sent, for the form to show back whatever came of it. */
export function formValues(formData: FormData): DryRunFormValues {
  const level = text(formData, DRY_RUN_FIELDS.level);
  return {
    subject:
      text(formData, DRY_RUN_FIELDS.subject) === "specification" ? "specification" : "version",
    ruleVersionId: text(formData, DRY_RUN_FIELDS.ruleVersionId),
    specification: text(formData, DRY_RUN_FIELDS.specification),
    level: isLevel(level) ? level : "",
    tenantId: text(formData, DRY_RUN_FIELDS.tenantId),
    sampleSize: text(formData, DRY_RUN_FIELDS.sampleSize),
  };
}

/** The values a fresh form starts with: a version, maybe named by the address. */
export function initialValues(ruleVersionId: string | null): DryRunFormValues {
  return {
    subject: "version",
    ruleVersionId: ruleVersionId ?? "",
    specification: "",
    level: "",
    tenantId: "",
    sampleSize: String(DEFAULT_SAMPLES),
  };
}

/** A specification as a JSON object, or null when the text is not one. */
export function parseSpecification(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export type ParsedDryRun =
  | { ok: true; request: DryRunRequest }
  | { ok: false; fieldErrors: Record<string, readonly string[]> };

export function parseDryRunForm(values: DryRunFormValues): ParsedDryRun {
  const errors: Record<string, string[]> = {};
  let ruleVersionId: string | null = null;
  let specification: Record<string, unknown> | null = null;
  if (values.subject === "version") {
    const id = values.ruleVersionId.trim().toLowerCase();
    if (!isHexUuid(id)) errors[DRY_RUN_FIELDS.ruleVersionId] = [t("impact.error.version")];
    else ruleVersionId = id;
  } else {
    const raw = values.specification.trim();
    specification = raw.length > SPECIFICATION_MAX_LENGTH ? null : parseSpecification(raw);
    if (specification === null) {
      errors[DRY_RUN_FIELDS.specification] = [
        t("impact.error.specification", { max: SPECIFICATION_MAX_LENGTH }),
      ];
    }
    if (values.level === "") errors[DRY_RUN_FIELDS.level] = [t("impact.error.level")];
  }
  const tenant = values.tenantId.trim().toLowerCase();
  if (tenant !== "" && !isUuid(tenant))
    errors[DRY_RUN_FIELDS.tenantId] = [t("impact.error.tenant")];
  const samples = values.sampleSize.trim();
  const sampleSize = Number(samples);
  if (!/^\d+$/.test(samples) || sampleSize > MAX_SAMPLES) {
    errors[DRY_RUN_FIELDS.sampleSize] = [t("impact.error.samples", { max: MAX_SAMPLES })];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    request: {
      ruleVersionId,
      specification,
      level: values.level === "" ? null : values.level,
      tenantId: tenant === "" ? null : tenant,
      sampleSize,
    },
  };
}
