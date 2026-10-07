import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ALLOW_VARIABLE,
  DIR_VARIABLE,
  RECORD_FILE,
  SERVICES,
  decide,
  parseStackRecord,
  targets,
} from "./lib.mts";

/**
 * The end-to-end suite's guard against a Postgres-backed stack (lib.mts says why and how): asks
 * each service the run would use for `/health`, reads what `make web-stack` recorded in its
 * directory (CW_E2E_WEB_STACK_DIR, else var/web-stack) and the processes its pid files name, and
 * exits 1 with a plain message to refuse, 0 to let the run go on.
 *
 *   pnpm --filter web e2e:guard       what make web-e2e runs before its build
 *   e2e/stack-guard.setup.ts          what the chromium project runs first
 */
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

/** How long a service may take to answer `/health` before it counts as not running. */
const PROBE_MS = 1_500;

function readOrNull(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

async function answers(url: string): Promise<boolean> {
  try {
    await fetch(`${url}/health`, { signal: AbortSignal.timeout(PROBE_MS) });
    return true;
  } catch {
    return false;
  }
}

/** The command line of the live process a pid file names, or null when none runs. */
function commandOf(pidFile: string): string | null {
  const pid = Number((readOrNull(pidFile) ?? "").trim());
  if (!Number.isInteger(pid) || pid <= 0) return null;
  try {
    process.kill(pid, 0);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EPERM") return null;
  }
  try {
    return execFileSync("ps", ["-o", "command=", "-p", String(pid)], { encoding: "utf8" }).trim();
  } catch {
    return null;
  }
}

async function main(): Promise<number> {
  const env = process.env;
  const configured = env[DIR_VARIABLE]?.trim();
  const dir = configured ? resolve(REPO, configured) : join(REPO, "var", "web-stack");
  const shown = relative(REPO, dir);
  const list = targets(env);
  const answering = new Set<string>();
  await Promise.all(
    [...new Set(list.map((target) => target.url))].map(async (url) => {
      if (await answers(url)) answering.add(url);
    }),
  );
  const processes = new Map<string, string | null>(
    SERVICES.map((service) => [service, commandOf(join(dir, `${service}.pid`))]),
  );
  const decision = decide({
    targets: list,
    answering,
    record: parseStackRecord(readOrNull(join(dir, RECORD_FILE))),
    processes,
    allow: env[ALLOW_VARIABLE]?.trim() === "1",
    dir: shown === "" || shown.startsWith("..") || isAbsolute(shown) ? dir : shown,
  });
  if (!decision.run) {
    console.error(decision.message);
    return 1;
  }
  if (decision.note !== null) console.warn(decision.note);
  return 0;
}

main().then(
  (status) => {
    process.exitCode = status;
  },
  (error: unknown) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  },
);
