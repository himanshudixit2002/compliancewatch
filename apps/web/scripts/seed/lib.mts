import { createHash } from "node:crypto";
import { z } from "zod";
import { financialYearLabel, financialYearOf } from "../../src/shared/lib/financial-year.ts";
import { isUuid } from "../../src/shared/lib/identifiers.ts";

/**
 * The seed's pure parts: the demo tenant's facts, the configuration rules, the argument parser,
 * and the checks that keep the recorded rulebook fixtures honest. Nothing here touches the
 * network or the file system, so seed.test.mts covers it without a service.
 *
 * The demo facts are the ones tools/demo/src/cw_demo/tenant.py uses (made up; the GSTIN is the
 * profile service's static demo lookup value), so `make demo` and `make web-seed` describe the
 * same business. Attribute levels follow packages/ontology attributes.yaml: state, category,
 * turnover, peak turnover and headcount sit on the entity node (turnover per financial year),
 * the filing and supply facts on the registration node.
 */
export const SEED_SERVICES = [
  "identity",
  "profile",
  "rulebook",
  "applicability-engine",
  "obligation",
  "notification",
  "qa",
  "llm-gateway",
  "eval",
  "pipeline",
] as const;

export type SeedService = (typeof SEED_SERVICES)[number];

export const DEFAULT_PORT_BASE = 8000;

/** What `make web-stack` gives the rulebook when .env sets no token; not a secret. */
export const PLACEHOLDER_WRITE_TOKEN = "local-write-token";

export const DEFAULT_STATE_PATH = "../../var/seed/last.json";

export type EnvRecord = Readonly<Record<string, string | undefined>>;

export interface AttributeChange {
  key: string;
  value: unknown;
  as_of_fy?: string;
}

export const DEMO = {
  ownerPhone: "919876543210",
  noticeVersion: "0.1-draft",
  gstin: "29ABCDE1234F1Z5",
  entityName: "Acme Traders Private Limited",
  registrationName: "Acme Bengaluru",
  asOf: "2026-09-28",
  consentSource: "web_onboarding",
  consentPurposes: ["terms", "privacy_notice", "profile_processing", "whatsapp_reminders"],
  consentEvidence: "onboarding checkbox (seed)",
  whatsappLanguage: "hi",
  quietHours: { start: "21:00", end: "08:00" },
  entityAttributes: [
    { key: "state_codes", value: ["29"] },
    { key: "business_category", value: "wholesale_trade" },
    { key: "turnover_band", value: "2_crore_to_5_crore", perFinancialYear: true },
    { key: "peak_turnover_band", value: "2_crore_to_5_crore" },
    { key: "employee_count", value: 12 },
  ],
  registrationAttributes: [
    { key: "supply_type", value: "goods" },
    { key: "filing_scheme", value: "regular_monthly" },
    { key: "return_filing_frequency", value: "monthly" },
    { key: "makes_inter_state_supplies", value: true },
    { key: "makes_zero_rated_supplies", value: false },
    { key: "ecommerce_role", value: "none" },
    { key: "pays_reverse_charge", value: false },
    { key: "generates_eway_bills", value: true },
  ],
} as const;

/** The financial-year label the seed answers for: `2026-27` for 28 September 2026. */
export function seedFinancialYear(asOf: string = DEMO.asOf): string {
  return financialYearLabel(financialYearOf(asOf));
}

/** The attribute PUT bodies per node; turnover carries the financial year it applies to. */
export function attributeChanges(fy: string = seedFinancialYear()): {
  entity: AttributeChange[];
  registration: AttributeChange[];
} {
  const entity = DEMO.entityAttributes.map((attribute) => {
    const change: AttributeChange = { key: attribute.key, value: attribute.value };
    if ("perFinancialYear" in attribute && attribute.perFinancialYear) change.as_of_fy = fy;
    return change;
  });
  const registration = DEMO.registrationAttributes.map((attribute) => ({
    key: attribute.key,
    value: attribute.value,
  }));
  return { entity, registration };
}

const URL_KEYS: Readonly<Record<SeedService, string>> = {
  identity: "CW_WEB_IDENTITY_URL",
  profile: "CW_WEB_PROFILE_URL",
  rulebook: "CW_WEB_RULEBOOK_URL",
  "applicability-engine": "CW_WEB_APPLICABILITY_ENGINE_URL",
  obligation: "CW_WEB_OBLIGATION_URL",
  notification: "CW_WEB_NOTIFICATION_URL",
  qa: "CW_WEB_QA_URL",
  "llm-gateway": "CW_WEB_LLM_GATEWAY_URL",
  eval: "CW_WEB_EVAL_URL",
  pipeline: "CW_WEB_PIPELINE_URL",
};

function present(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed === "" ? undefined : trimmed;
}

/** SERVICE_PORT_BASE from the environment (the root .env, sourced by make), else 8000. */
export function portBase(env: EnvRecord): number {
  const raw = present(env.SERVICE_PORT_BASE);
  if (raw === undefined) return DEFAULT_PORT_BASE;
  const base = Number(raw);
  if (!Number.isInteger(base) || base < 0 || base > 65_525) {
    throw new Error(`SERVICE_PORT_BASE must be a port number below 65526, got ${raw}`);
  }
  return base;
}

/** The app's own variable wins; otherwise the stack's port from SERVICE_PORT_BASE. */
export function serviceUrl(service: SeedService, env: EnvRecord): string {
  const own = present(env[URL_KEYS[service]]);
  if (own !== undefined) return own.replace(/\/+$/, "");
  return `http://localhost:${portBase(env) + SEED_SERVICES.indexOf(service) + 1}`;
}

export function serviceUrls(env: EnvRecord): Record<SeedService, string> {
  const urls = {} as Record<SeedService, string>;
  for (const service of SEED_SERVICES) urls[service] = serviceUrl(service, env);
  return urls;
}

/** The web app's write token, else the services' own variable, else the stack's placeholder. */
export function writeToken(env: EnvRecord): string {
  return (
    present(env.CW_WEB_RULEBOOK_WRITE_TOKEN) ??
    present(env.CW_RULEBOOK_WRITE_TOKEN) ??
    PLACEHOLDER_WRITE_TOKEN
  );
}

export interface SeedOptions {
  tenantId: string;
  ownerId: string;
  json: boolean;
  skipRulebook: boolean;
  /** Where the state file goes, as given (resolved against the working directory later). */
  statePath: string;
  help: boolean;
}

export const USAGE = `usage: pnpm --filter web seed [-- options]
  --tenant <uuid>   the tenant to fill (default: a new id)
  --owner <uuid>    the owner's user id (default: a new id)
  --skip-rulebook   leave the rulebook alone (no write token needed)
  --json            print the report as JSON
  --state <path>    where to record the last seeded tenant (default: CW_WEB_SEED_STATE_PATH
                    or ${DEFAULT_STATE_PATH}, relative to apps/web)
  --help            this text`;

export class UsageError extends Error {
  override readonly name = "UsageError";
}

function takeValue(argv: readonly string[], index: number, flag: string): string {
  const value = argv[index + 1];
  if (value === undefined || value.startsWith("--")) {
    throw new UsageError(`${flag} needs a value`);
  }
  return value;
}

function takeUuid(argv: readonly string[], index: number, flag: string): string {
  const value = takeValue(argv, index, flag).toLowerCase();
  if (!isUuid(value)) throw new UsageError(`${flag} must be a UUID, got ${value}`);
  return value;
}

/** Parses the command line; throws UsageError with the message to print. */
export function parseArgs(
  argv: readonly string[],
  defaults: { tenantId: string; ownerId: string; statePath: string },
): SeedOptions {
  const options: SeedOptions = {
    ...defaults,
    json: false,
    skipRulebook: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    switch (flag) {
      case "--tenant":
        options.tenantId = takeUuid(argv, index, flag);
        index += 1;
        break;
      case "--owner":
        options.ownerId = takeUuid(argv, index, flag);
        index += 1;
        break;
      case "--state":
        options.statePath = takeValue(argv, index, flag);
        index += 1;
        break;
      case "--json":
        options.json = true;
        break;
      case "--skip-rulebook":
        options.skipRulebook = true;
        break;
      case "--help":
      case "-h":
        options.help = true;
        break;
      case "--":
        break;
      default:
        throw new UsageError(`unknown option ${flag}`);
    }
  }
  return options;
}

export function sha256Hex(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

const SHA256 = /^[0-9a-f]{64}$/;

/** The kernel's rule: a document's id is the first half of its digest read as a UUID. */
export function documentIdFor(sha256: string): string {
  if (!SHA256.test(sha256)) throw new Error(`sha256 must be 64 lowercase hex digits: ${sha256}`);
  const hex = sha256.slice(0, 32);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** domain_kernel.documents.PARSER_VERSION_PATTERN, which the rulebook applies to extractors too. */
export const VERSION_PATTERN = /^[a-z][a-z0-9_-]*@[0-9]+$/;
const CLAUSE_REF = /^(?:[a-z]{2,3}\.)?p[1-9][0-9]{0,3}$/;

const clauseRef = z.string().regex(CLAUSE_REF);
const span = z.number().int().nonnegative();

/** The rulebook spec's EntityType and RelationKind, so a fixture is typed as the request body. */
export const ENTITY_TYPES = [
  "notification",
  "circular",
  "section",
  "rule",
  "form",
  "hsn_code",
  "sac_code",
  "tax_rate",
  "threshold",
  "state",
] as const;
export const RELATION_KINDS = [
  "supersedes",
  "amends",
  "refers_to",
  "exempts",
  "extends_deadline",
  "corrects",
  "withdraws",
] as const;

export const documentFixtureSchema = z.object({
  source_id: z.uuid(),
  sha256: z.string().regex(SHA256),
  regulator: z.string().min(1).max(40),
  doc_type: z.enum(["notification", "circular", "press_release", "act_amendment"]),
  external_ref: z.string().max(200),
  url: z.string().min(1).max(2000),
  title: z.string().max(2000),
  language: z.string().min(1).max(8),
  media_type: z.string().min(1).max(80),
  parser_version: z.string().max(40).regex(VERSION_PATTERN),
  published_at: z.iso.date().nullable(),
  fetched_at: z.iso.datetime({ offset: true }),
  raw_uri: z.string().max(2000).nullable(),
  clauses: z
    .array(
      z.object({
        clause_ref: clauseRef,
        text: z.string().min(1).max(50_000),
        page: z.number().int().min(1).nullable(),
      }),
    )
    .min(1),
});

export const mentionsFixtureSchema = z.object({
  extractor: z.string().max(60).regex(VERSION_PATTERN),
  mentions: z.array(
    z.object({
      clause_ref: clauseRef,
      entity_type: z.enum(ENTITY_TYPES),
      text: z.string().min(1).max(2000),
      span_start: span,
      span_end: z.number().int().min(1),
      proposed_name: z.string().max(400),
    }),
  ),
});

export const EVIDENCE_QUOTE_LENGTH = { min: 8, max: 400 } as const;

export const relationsFixtureSchema = z.object({
  extractor: z.string().min(1).max(60),
  model: z.string().max(120),
  outcome: z.enum(["ok", "needs_review", "no_targets", "unparseable", "failed"]),
  run_issues: z.array(z.object({ code: z.string().min(1).max(60), detail: z.string().max(2000) })),
  candidates: z.array(
    z.object({
      relation: z.enum(RELATION_KINDS),
      target_type: z.enum(ENTITY_TYPES),
      target_name: z.string().min(1).max(400),
      target_clause_ref: clauseRef,
      target_span_start: span,
      target_span_end: z.number().int().min(1),
      rule_key: z.string().max(80).nullable(),
      evidence_clause_ref: clauseRef,
      evidence_quote: z.string().min(EVIDENCE_QUOTE_LENGTH.min).max(EVIDENCE_QUOTE_LENGTH.max),
      quote_score: z.number().min(0).max(1),
      period_label: z.string().max(16).nullable(),
      new_due_on: z.iso.date().nullable(),
      confidence: z.number().min(0).max(1),
      issues: z.array(z.object({ code: z.string().min(1).max(60), detail: z.string().max(2000) })),
      needs_review: z.boolean(),
    }),
  ),
});

export type DocumentFixture = z.output<typeof documentFixtureSchema>;
export type MentionsFixture = z.output<typeof mentionsFixtureSchema>;
export type RelationsFixture = z.output<typeof relationsFixtureSchema>;

export interface RulebookFixtures {
  document: DocumentFixture;
  mentions: MentionsFixture;
  relations: RelationsFixture;
}

/**
 * Every way the three files could have drifted from each other or from the recorded PDF: the
 * digest, a mention span that no longer slices its clause, a candidate whose target is not one
 * of the recorded mentions (the rulebook links a candidate to the mention at its target span;
 * the target name is that mention's proposed name, not the clause text), an evidence quote that
 * is not in its clause. Empty means consistent.
 */
export function fixtureProblems(fixtures: RulebookFixtures, pdfBytes: Uint8Array): string[] {
  const problems: string[] = [];
  const digest = sha256Hex(pdfBytes);
  if (digest !== fixtures.document.sha256) {
    problems.push(
      `the recorded PDF hashes to ${digest}, the document fixture says ${fixtures.document.sha256}`,
    );
  }
  const clauses = new Map(fixtures.document.clauses.map((clause) => [clause.clause_ref, clause]));
  for (const mention of fixtures.mentions.mentions) {
    const clause = clauses.get(mention.clause_ref);
    if (clause === undefined) {
      problems.push(`mention "${mention.text}" names an unknown clause ${mention.clause_ref}`);
      continue;
    }
    if (clause.text.slice(mention.span_start, mention.span_end) !== mention.text) {
      problems.push(
        `mention "${mention.text}" is not ${mention.clause_ref}[${mention.span_start}:${mention.span_end}]`,
      );
    }
  }
  for (const candidate of fixtures.relations.candidates) {
    const target = fixtures.mentions.mentions.find(
      (mention) =>
        mention.clause_ref === candidate.target_clause_ref &&
        mention.span_start === candidate.target_span_start &&
        mention.span_end === candidate.target_span_end &&
        mention.entity_type === candidate.target_type &&
        mention.proposed_name === candidate.target_name,
    );
    if (target === undefined) {
      problems.push(
        `candidate target "${candidate.target_name}" (${candidate.target_type}) is not a recorded mention at ${candidate.target_clause_ref}[${candidate.target_span_start}:${candidate.target_span_end}]`,
      );
    }
    const evidence = clauses.get(candidate.evidence_clause_ref);
    if (evidence === undefined || !evidence.text.includes(candidate.evidence_quote)) {
      problems.push(
        `candidate evidence quote is not in ${candidate.evidence_clause_ref}: "${candidate.evidence_quote}"`,
      );
    }
  }
  return problems;
}

/** The candidates with `rule_key` kept only when the target rulebook lists that rule. */
export function withKnownRules(
  relations: RelationsFixture,
  knownRuleKeys: readonly string[],
): RelationsFixture {
  const known = new Set(knownRuleKeys);
  return {
    ...relations,
    candidates: relations.candidates.map((candidate) => ({
      ...candidate,
      rule_key:
        candidate.rule_key !== null && known.has(candidate.rule_key) ? candidate.rule_key : null,
    })),
  };
}

/** The shape features/auth/queries.ts reads back for "use the last seeded tenant". */
export interface SeedState {
  tenant_id: string;
  owner_id: string;
  entity_node_id: string;
  registration_node_id: string;
  document_id: string | null;
  seeded_at: string;
  services: Record<SeedService, string>;
}

export function seedStateJson(state: SeedState): string {
  return `${JSON.stringify(state, null, 2)}\n`;
}
