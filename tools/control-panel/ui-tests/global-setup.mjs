// Starts the helper the tests talk to and hands its address and token to them through the
// environment: panel_server.py --demo (the real helper with made-up data) by default, or the
// mock (mock-server.mjs) with PANEL_BACKEND=mock, offline and without Python. Both print
// {"port": ..., "token": ...} first, and both take the specs' world (helpers.mjs, setWorld).
// PANEL_SERVER names another helper script to run with --demo, PANEL_PYTHON its Python.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const server = process.env.PANEL_SERVER || join(here, "..", "panel_server.py");

function backend() {
  if (process.env.PANEL_BACKEND) return process.env.PANEL_BACKEND;
  return existsSync(server) ? "demo" : "mock";
}

function command(kind) {
  if (kind === "demo") {
    if (!existsSync(server)) throw new Error(`PANEL_BACKEND=demo needs ${server}`);
    return [process.env.PANEL_PYTHON || "python3", [server, "--demo"]];
  }
  return [
    process.execPath,
    [join(here, "mock-server.mjs"), "--speed", process.env.MOCK_SPEED || "3"],
  ];
}

export default async function globalSetup() {
  const kind = backend();
  const [program, args] = command(kind);
  // the helper is not pointed at any checkout: --demo reads none, and the mock needs none
  const { CW_CONTROL_PANEL_REPO: _, ...env } = process.env;
  const child = spawn(program, args, { stdio: ["ignore", "pipe", "inherit"], env });
  const handoff = await new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(
      () => reject(new Error("the helper did not print its port and token")),
      15000,
    );
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const line = buffer.split("\n").find((l) => l.trim().startsWith("{"));
      if (line) {
        clearTimeout(timer);
        resolve(JSON.parse(line));
      }
    });
    child.on("exit", (code) => reject(new Error(`the helper exited (${code})`)));
  });
  process.env.PANEL_URL = `http://127.0.0.1:${handoff.port}`;
  process.env.PANEL_TOKEN = handoff.token;
  process.env.PANEL_KIND = kind;
  console.log(
    `ui-tests: against the ${kind === "demo" ? "panel_server.py --demo" : "mock"} helper`,
  );
  return async () => {
    child.kill("SIGTERM");
  };
}
