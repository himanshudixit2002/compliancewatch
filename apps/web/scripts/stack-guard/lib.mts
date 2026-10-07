/**
 * Whether the end-to-end suite may run against the services it would use. The chromium specs
 * stage synthetic data through the services: the review items of the entity and relation specs,
 * and the sources, uploads, retries and requeues of the source and pipeline specs. On a memory
 * stack all of it goes when the stack stops; on Postgres (`make web-stack STORE=postgres`, the
 * shared development database) it would stay for good, and a stored document cannot be deleted.
 * So the suite runs only against a memory stack that `make web-stack` started and recorded, unless
 * E2E_ALLOW_POSTGRES=1 says otherwise:
 *
 *   make web-stack       writes $(WEB_STACK_DIR)/store: `store=memory|postgres` and
 *                        `base=<port base>`, or `store=unknown` when it found services running
 *                        that it had not started
 *   make web-stack-down  removes it once no service of the stack is left
 *   make web-e2e         runs this check before its build, with CW_E2E_WEB_STACK_DIR set to its
 *                        WEB_STACK_DIR and E2E_ALLOW_POSTGRES passed on
 *   Playwright           the chromium project depends on the stack-guard setup project, which
 *                        runs it too, so running Playwright directly is guarded as well
 *
 * A service that answers is vouched for only when the record says memory, the service's address
 * is the record's base plus its place, and the stack's pid file for it names a live process started
 * on that port. A service nothing answers on cannot be written to, so it passes. Anything else
 * counts as Postgres: a record saying postgres or unknown, no record, or services the record does
 * not describe.
 */
export const SERVICES = [
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

export type Service = (typeof SERVICES)[number];

/** The web app's own default base: its CW_WEB_<SERVICE>_URL defaults are 8001-8010. */
export const APP_PORT_BASE = 8000;

/** The record's file name in the stack's directory. */
export const RECORD_FILE = "store";

export const ALLOW_VARIABLE = "E2E_ALLOW_POSTGRES";
export const DIR_VARIABLE = "CW_E2E_WEB_STACK_DIR";

export type EnvRecord = Readonly<Record<string, string | undefined>>;

export interface Target {
  service: Service;
  url: string;
}

function present(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed === "" ? undefined : trimmed;
}

function urlVariable(service: Service): string {
  return `CW_WEB_${service.toUpperCase().replace(/-/g, "_")}_URL`;
}

/**
 * The service addresses a run uses, each once: the specs' (CW_WEB_<SERVICE>_URL, else
 * SERVICE_PORT_BASE plus the service's place, as e2e/fixtures.ts reads them) and the app's
 * (CW_WEB_<SERVICE>_URL, else the product listener when CW_E2E_PRODUCT_URL names it, else 8001-8010).
 */
export function targets(env: EnvRecord): Target[] {
  const base = Number(present(env.SERVICE_PORT_BASE) ?? APP_PORT_BASE);
  const product = present(env.CW_E2E_PRODUCT_URL)?.replace(/\/+$/, "");
  const found: Target[] = [];
  SERVICES.forEach((service, index) => {
    const own = present(env[urlVariable(service)])?.replace(/\/+$/, "");
    const specs = own ?? `http://localhost:${base + index + 1}`;
    const app = own ?? product ?? `http://localhost:${APP_PORT_BASE + index + 1}`;
    for (const url of [specs, app]) {
      if (!found.some((target) => target.url === url && target.service === service)) {
        found.push({ service, url });
      }
    }
  });
  return found;
}

export type RecordedStore = "memory" | "postgres" | "unknown";

export interface StackRecord {
  store: RecordedStore;
  /** The port base the stack was started on; null when the record names none. */
  base: number | null;
}

/** The record `make web-stack` wrote, or null when there is none. */
export function parseStackRecord(text: string | null): StackRecord | null {
  if (text === null) return null;
  const values = new Map<string, string>();
  for (const line of text.split(/\r?\n/)) {
    const at = line.indexOf("=");
    if (at > 0) values.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
  }
  const said = values.get("store");
  const store: RecordedStore = said === "memory" || said === "postgres" ? said : "unknown";
  const base = values.get("base") ?? "";
  return { store, base: /^\d+$/.test(base) ? Number(base) : null };
}

/** Whether the address is this machine's, on the port. */
export function isLocalPort(url: string, port: number): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  const host = parsed.hostname.replace(/^\[|\]$/g, "");
  const local = host === "localhost" || host === "127.0.0.1" || host === "::1";
  return local && parsed.port === String(port);
}

export interface GuardInput {
  targets: readonly Target[];
  /** The addresses that answered `/health`. */
  answering: ReadonlySet<string>;
  record: StackRecord | null;
  /** Each service's process from the stack's pid file: its command line, or null when none runs. */
  processes: ReadonlyMap<string, string | null>;
  allow: boolean;
  /** The stack's directory, as the messages name it. */
  dir: string;
}

export type GuardDecision = { run: true; note: string | null } | { run: false; message: string };

function vouched(target: Target, input: GuardInput): boolean {
  const record = input.record;
  if (record === null || record.store !== "memory" || record.base === null) return false;
  const port = record.base + SERVICES.indexOf(target.service) + 1;
  if (!isLocalPort(target.url, port)) return false;
  const command = input.processes.get(target.service);
  return typeof command === "string" && new RegExp(`--port[ =]${port}(\\s|$)`).test(command);
}

/** Why the services that answer count as Postgres, in words. */
function why(input: GuardInput): string {
  const record = input.record;
  if (record === null) return `nothing in ${input.dir} says which store they use`;
  if (record.store === "postgres") return `${input.dir}/${RECORD_FILE} says they run on Postgres`;
  if (record.store === "unknown") {
    return `${input.dir}/${RECORD_FILE} says their store is unknown (make web-stack found services running that it had not started)`;
  }
  const range =
    record.base === null ? "" : ` on ${record.base + 1}-${record.base + SERVICES.length}`;
  return `${input.dir}/${RECORD_FILE} records a memory stack${range}, but these are not its running services`;
}

/**
 * Run, or refuse with a plain message: every service that answers must be the memory stack's,
 * unless the run is allowed onto Postgres.
 */
export function decide(input: GuardInput): GuardDecision {
  const live = input.targets.filter((target) => input.answering.has(target.url));
  const doubtful = live.filter((target) => !vouched(target, input));
  if (doubtful.length === 0) return { run: true, note: null };
  const urls = [...new Set(doubtful.map((target) => target.url))].join(", ");
  if (input.allow) {
    return {
      run: true,
      note: `${ALLOW_VARIABLE}=1: running the end-to-end suite against ${urls}, though ${why(input)}. What the specs stage there stays there.`,
    };
  }
  return {
    run: false,
    message: [
      `The end-to-end suite will not run against the services at ${urls}: ${why(input)}, so they count as backed by Postgres.`,
      "The specs stage synthetic sources, uploads, retries, requeues and review items through these services; in Postgres (the shared development database of make web-stack STORE=postgres) they would stay for good, and a stored document cannot be deleted.",
      "Run the suite against a memory stack instead: make web-stack-down, then make web-stack (memory is the default), or point the run at one on other ports (SERVICE_PORT_BASE, or CW_WEB_<SERVICE>_URL with CW_E2E_WEB_STACK_DIR naming its directory).",
      `To run against these services anyway, set ${ALLOW_VARIABLE}=1.`,
    ].join("\n"),
  };
}
