import { mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { serviceUrl } from "./fixtures";

/**
 * A spec that moves one of the seed calendar's drafts owns it by its rule's position in key order
 * (D-042, D-063), and no other spec moves that draft. Under `fullyParallel` two copies of one test
 * can still run at once (a `--repeat-each` run, a retry beside the first attempt), and both would
 * move the same draft, so a test holds its position while it works: a directory made with mkdir,
 * which one holder at a time can create, under the temp folder and named after the stack's
 * rulebook, with the holder's process id in it. A holder whose process is gone (an interrupted
 * run) is taken over at once; one that left no id is taken over once its directory is older than
 * `STALE_MS`. A waiting test spends its own time limit, so the tests that hold a position give
 * themselves more of it.
 */
const STALE_MS = 180_000;
const WAIT_MS = 250;

function positionDir(position: number): string {
  const stack = serviceUrl("rulebook").replace(/[^A-Za-z0-9]+/g, "_");
  return join(tmpdir(), "cw-e2e-positions", stack, `position-${position}`);
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** Whether the holder of the directory is gone: its process ended, or it never named one. */
async function abandoned(dir: string): Promise<boolean> {
  const owner = await readFile(join(dir, "owner"), "utf8").catch(() => null);
  if (owner !== null) {
    const pid = Number(owner.trim());
    return Number.isInteger(pid) && pid > 0 && !alive(pid);
  }
  const age = await stat(dir).then(
    (found) => Date.now() - found.mtimeMs,
    () => 0,
  );
  return age > STALE_MS;
}

export async function holdingPosition<T>(position: number, work: () => Promise<T>): Promise<T> {
  const dir = positionDir(position);
  await mkdir(join(dir, ".."), { recursive: true });
  for (;;) {
    try {
      await mkdir(dir);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      if (await abandoned(dir)) await rm(dir, { recursive: true, force: true });
      else await new Promise((resolve) => setTimeout(resolve, WAIT_MS));
    }
  }
  await writeFile(join(dir, "owner"), String(process.pid));
  try {
    return await work();
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}
