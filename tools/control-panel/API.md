# ComplianceWatch Control: the local API (version 1)

The contract between `panel_server.py` (the helper, agent A) and the window's UI in `ui/`
(agent B). It replaces the spec's provisional API and answers `API-REQUESTS.md`; the section
"Changes from API-REQUESTS.md" at the end lists what differs from what the UI asked for.

Everything here is served by one process, `panel_server.py`, on `127.0.0.1` only. The UI is the
only intended client. The helper re-checks every request: it never trusts the UI to have asked,
checked or confirmed anything.

## 1. Starting, the hand-off and the lifetime

```
.venv/bin/python tools/control-panel/panel_server.py [--demo] [--open [browser|app]] [--detach] [--port N]
```

- It binds `127.0.0.1` on a random free port (`--port 0`, the default) and makes a random token
  for this launch (`secrets.token_urlsafe(32)`).
- When it is listening it prints exactly one line on stdout, then nothing else there:

  ```json
  {"port": 52341, "token": "kq3...Zt8"}
  ```

  The token is written nowhere else: not to disk, not to stderr, not to a log. Run by a person
  in a terminal with `--open` (`make control-panel`), it prints a plain line with the address
  and without the token instead, since it opens the window itself.
- **No token ever travels in a URL.** The window loads
  `http://127.0.0.1:<port>/#launch=<code>`: a single-use launch code that the program which holds
  the token got from `POST /api/launch-code` (the app shell, with the token from the hand-off
  line) or that the helper made itself (`--open`). The page clears the address bar at once, then
  swaps the code for the token with `POST /api/launch` (section 2) and keeps the token in memory
  only. A code lasts 30 s and works once; after the swap it is worth nothing.
- `--open` also opens such an address in the default browser (for `make control-panel` from a
  terminal); `--open app` opens it in Google Chrome's app mode when Chrome is installed (the
  app's fallback when it has no Swift window). `--demo` serves canned data from a fake core
  (section 9).
- **It exits** (stopping any running step first, SIGTERM to the step's process group) when:
  - its standard input reaches end of file, when that input is a pipe (the app shell keeps a pipe
    open and closes it on quit; an input that is not a pipe, such as `/dev/null`, is ignored);
  - its parent process exits (not with `--detach`, which the browser fallback uses: it then
    lives until the idle rule below);
  - ten minutes pass with no authenticated request (the UI's heartbeat, every 20 s, keeps it
    alive), but only when nobody owns it: while its standard input is a pipe (the app shell
    holds it), the owner decides, and closing the pipe is what stops it;
  - `POST /api/quit` asks it to (the window's Quit outside the app);
  - it gets SIGTERM, SIGINT or SIGHUP.
- Once told to stop, it exits within 3 s, whatever is still in flight (a slow probe, an open
  connection).
- Diagnostics go to stderr, without the token or any request's query string. The last line says
  why it exited (`panel_server: exiting: stdin closed`). The app shell appends them to
  `~/Library/Logs/ComplianceWatch Control/helper.log`.

## 2. Security

| Rule | What the helper does |
| --- | --- |
| Token | Every `/api/*` request but `POST /api/launch` must carry `X-Panel-Token: <token>`, compared in constant time. Missing or wrong: `401 unauthorized`. |
| Launch codes | `POST /api/launch-code` (token required) → `{"code": "l-...", "expires_in": 30}`. `POST /api/launch` with `{"code": "l-..."}` → `{"token": "..."}`: the only route without the token, `POST` only, and only with an `Origin` of exactly `http://127.0.0.1:<port>` (which a browser always sends on a page's `POST`; missing or other: `403 bad-origin`, and the code stays unused). The code is burned on its first swap; a used, expired or made-up code is `401 launch-expired`. |
| Event stream | `GET /api/events` takes the same header (the UI reads it with `fetch()`). A client that cannot set headers (`EventSource`) may instead pass `?ticket=<t>` from `POST /api/events/ticket`: single use, valid 30 s, accepted on `/api/events` only. |
| Host | The `Host` header must be exactly `127.0.0.1:<port>`, on every request, static files included. Otherwise `403 bad-host` (this stops DNS rebinding). |
| Origin | An `Origin` header, when present, must be exactly `http://127.0.0.1:<port>`; `null` is refused. A `Sec-Fetch-Site` header, when present, must be `same-origin` or `none`. Otherwise `403 bad-origin`. |
| CORS | None. No `Access-Control-*` header is ever sent; `OPTIONS` is `405`. |
| Connections | At most 48 at once (one past it is closed unanswered); a kept-alive connection idle for 20 s is closed. At most 4 event streams at once: a fifth closes the oldest (a window keeps one, and lets go of it while hidden). |
| Bodies | Only `POST` and `PUT` take a body, sent with a `Content-Length`: a body sent with `Transfer-Encoding` (chunked) is `411`, and a request without a `Content-Length` is read as an empty body (`{}`), which a route that needs fields then refuses (`400 bad-params`, or `428` without a confirm token). A body that is not empty must be `Content-Type: application/json` (else `415`), at most 64 KiB (else `413`), and a JSON object (else `400 bad-json`). |
| Static files | `GET` only, from `ui/` only (no path outside it, no dotfiles, known types only), with `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and on HTML a CSP: `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`. |
| Every response | `Cache-Control: no-store`; JSON is `application/json; charset=utf-8`. |
| Actions | Run only through `panel_core`'s checked runner: the refusal rules apply where each program starts. Anything that stops things, changes data, destroys data or asks a model (`calls_model`) needs a confirm token from a preview (section 4). |

## 3. Errors

Every error is JSON with one shape, in plain words first:

```json
{
  "error": {
    "code": "busy",
    "message": "Stop everything is still running.",
    "detail": "One task of this kind runs at a time. Wait for it to finish, or cancel it.",
    "fix": "Wait for it to finish, or press Cancel.",
    "action": null
  }
}
```

- `message`: one plain sentence for the person (the UI shows it as the title).
- `detail`: more words, or the technical lines (shown under "Show technical details").
- `fix`: what to do, in plain words; may be `""`.
- `action`: an action id the UI can offer as a button (`"docker-start"`), or `null`.

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `bad-json`, `bad-request`, `bad-params` | The body or a parameter is wrong; `message` names it. |
| 401 | `unauthorized` | No token or the wrong one. |
| 401 | `launch-expired` | `POST /api/launch` with a launch code that was used, has expired or was never given. |
| 403 | `bad-host`, `bad-origin` | See section 2. |
| 403 | `refused` | The safety rules refuse it; `detail` lists why. |
| 403 | `disabled` | The action cannot run now (`message` says why, `action` may fix it). |
| 404 | `not-found` | No such route, action, run, log source, document or process; or a file to open that does not exist yet. |
| 405 | `method-not-allowed` | |
| 409 | `busy` | Another task of the same kind is running. |
| 409 | `not-running` | Cancel on a run that has finished. |
| 411, 413, 415 | `length-required`, `too-large`, `unsupported-media-type` | |
| 428 | `confirm-required` | No confirm token, or one that is expired, used, or for other parameters. Preview again. |
| 500 | `internal` | A defect in the helper; `detail` has the exception. |
| 503 | `scan-slow`, `scan-failed` | A question that names processes (a stop preview, the web app's stop, Stop everything, the sessions warnings) reads them afresh first; the read took longer than 15 s, or failed. Ask again. |

Times are Unix seconds (float), named `*_at`; durations are seconds, named `seconds`. Fields
marked optional may be missing or `null`; unknown fields must be ignored.

## 4. Actions and runs

### `GET /api/actions` → the catalog

```json
{
  "groups": [{ "id": "everything", "title": "Everything" }],
  "actions": [
    {
      "id": "stop-everything",
      "title": "Stop everything",
      "summary": "Stops the web app, the services, the product and Docker, to free memory.",
      "what_happens": [
        "Stops the web app and the ten services.",
        "Stops the product's app, worker and web app.",
        "Stops the workers and relays this app started.",
        "Stops the databases and queues. Their data stays on disk.",
        "Shuts Docker (Colima) down. If it takes longer than 2 minutes, you can force it."
      ],
      "duration": "about 1 minute",
      "group": "everything",
      "safety": "stops-things",
      "needs_confirm": true,
      "preview": true,
      "calls_model": false,
      "confirm": "Everything this checkout runs stops, for every session that uses it.",
      "enabled": true,
      "reason": "",
      "fix_action": null,
      "kind": "step",
      "button": "Stop",
      "params": [],
      "steps": ["stop the web app", "stop the UI-only stack", "...", "stop Docker (colima stop)"],
      "command": "make web-stack-down\nmake product-down\nmake dev-down\ncolima stop",
      "url": null,
      "source": "curated",
      "covered_by": null,
      "keywords": "everything stop"
    }
  ]
}
```

- `safety`: `safe` | `changes-data` | `stops-things` | `destructive` | `refused`. A `refused`
  entry is always `enabled: false`, with `reason` saying why it is never run from here.
- `needs_confirm` (and its twin `preview`): true for every safety but `safe` and `refused`, and
  for every action with `calls_model`. Such an action is previewed first, always asks, and runs
  only with the preview's token; the window never answers that question itself. `confirm` is the
  action's own sentence; the full confirm, with today's warnings, comes from the preview.
- `calls_model`: the action asks the model through the gateway (Extract the documents waiting),
  which may be a paid call per document; its preview carries a `provider` warning.
- The CI gates that rewrite tracked files are `changes-data`, not `safe`: `gate:contracts-check`
  (it regenerates the generated clients before it compares them), `gate:check` and
  `make:check` (which run it), and `gates-in-order`. Their confirm says what they rewrite.
- `enabled: false` comes with a plain `reason` ("Docker is not running.") and, when an action
  fixes it, `fix_action` (`"docker-start"`). What an action needs (Docker, the running product,
  a backup to choose, the `.env` file) is checked here, so a `safe` action that cannot run yet
  says so before anyone presses it.
- `kind`: `step` (changes something; one at a time), `read` (logs and reads; one at a time,
  beside a step), `open` (opens a file, folder or Terminal at once; no run).
- `params`: `[{"name", "label", "kind": "choice" | "boolean", "choices": [{"value", "label"}],
  "default", "required", "help"}]`. Choices are filled live (services, backups, product-check
  steps, documents). For an optional `choice` (`required: false`), `""` or a missing value means
  "not given": `product-check` then checks every step and `migrate` migrates every service.
- `steps` and `command`: the plan with the default parameters; `command` has one program per
  line ("Show details").
- `url`: set on actions the UI opens itself (a web page).
- `source`: `curated` (written for this app) or `make` (a `##`-documented Makefile target,
  `"id": "make:<target>"`, discovered and classified; ids of curated actions are listed in
  section 10). A make entry that a curated action already covers names it in `covered_by`
  (`make:dev-down` → `databases-stop`); the UI may hide those from lists and keep them for search.
- `keywords`: extra words the command palette matches (the make target, the id's words, the
  group).
- The catalog changes when Docker or the product starts or stops, and when backups or the
  `.env` file appear; an `actions` event says so.

### `POST /api/actions/{id}/preview` → what will happen, and the confirm token

Request: `{"params": {"service": "pipeline"}}` (the body may be omitted when there are none).

```json
{
  "action_id": "stop-everything",
  "params": {},
  "confirm": {
    "title": "Stop everything?",
    "text": "Everything this checkout runs stops, for every session that uses it.",
    "what_happens": ["..."],
    "warnings": [
      {
        "code": "sessions",
        "tone": "danger",
        "title": "Other sessions are using Docker's databases and queues",
        "message": "Claude's build agent is running make check (pid 61000, 3m 12s) with 3 more in this checkout. Stopping Docker or replacing its data will break them.",
        "items": ["Claude's build agent: make check (pid 61000, 3m 12s) with 3 more"]
      }
    ],
    "button": "Stop everything",
    "details": "The plan's own technical confirm, and the lines naming each pid the web app's stop reaches.",
    "reaches": [{ "pid": 76165, "command": "node /opt/homebrew/bin/pnpm --filter web dev", "origin": "panel web app" }]
  },
  "reaches": [{ "pid": 76165, "command": "node /opt/homebrew/bin/pnpm --filter web dev", "origin": "panel web app" }],
  "confirm_token": "c-4Kq...",
  "expires_in": 120,
  "steps": ["stop the web app", "..."],
  "command": "..."
}
```

- For a `safe` action, `confirm` and `confirm_token` are `null`: run it straight away.
- A preview of an action that needs a confirm reads the processes afresh (at most 15 s, else
  `503 scan-slow`), so its `reaches` and `sessions` warning are as of the question.
- The token is single use, lasts 120 s, and is bound to this action and these exact parameters.
  For Stop everything and the web app's stop, it is also bound to the pids the preview named in
  `reaches` (the same list at the top level and inside `confirm`), each with the program it ran:
  the stop signals only pids that are both named there and still running that program, one by
  one, and leaves alone, by name in the log, anything that started after the question. When the
  web app's processes changed since the question, that step fails with `changed`: ask again.
- **Warning**: `{"code", "tone": "danger" | "warning" | "info", "title", "message", "items"}`.
  `code`s:
  - `not-main`: the checkout is not on main and the action changes something (`danger` when it
    migrates: it applies that branch's database changes to the shared development database);
  - `sessions`: other sessions' processes use what the action stops or changes; `items` names
    each one;
  - `docker-down`, `product-down`: what the action needs is not running (normally the action is
    disabled first, see above);
  - `dirty`: uncommitted changes, when the action rewrites files;
  - `provider`: the action asks the model through the gateway. With the running product's
    gateway provider known (from its log), `info` for the free `fake`, `warning` for a paid one,
    which it names; when it is unknown (the product is not running, or its log does not say),
    a `warning` titled "This may call a paid model", since `CW_LLM_PROVIDER` may name one.

### `POST /api/actions/{id}/run` → start it

Request: `{"params": {...}, "confirm_token": "c-4Kq..."}` (`confirm_token` only when the preview
gave one; `confirm` is accepted as another name for it).

- `step` and `read` actions: `202 {"run_id": "r12"}`. Progress then arrives as events.
- `open` actions: `200 {"ok": true, "opened": true, "target": "/Users/.../.env", "message":
  "Opened .env"}`.
- Errors: `428 confirm-required`, `409 busy`, `403 refused`, `403 disabled`, `400 bad-params`,
  `404 not-found`.

### Runs

```json
{
  "run_id": "r12",
  "action_id": "stop-everything",
  "title": "Stop everything",
  "kind": "step",
  "params": {},
  "state": "running",
  "started_at": 1791290000.0,
  "finished_at": null,
  "seconds": 12.4,
  "current_step": 1,
  "steps": [
    { "label": "stop the web app", "state": "ok", "seconds": 1.2 },
    { "label": "stop the UI-only stack", "state": "running", "seconds": 11.2 },
    { "label": "stop Docker (colima stop)", "state": "queued", "seconds": 0 }
  ],
  "error": null,
  "lines": [{ "text": "▸ stop the web app", "tag": "step" }]
}
```

- `state`: `running` | `ok` | `failed` | `cancelled`. Step `state`: `queued` | `running` | `ok`
  | `failed` | `timeout` | `cancelled` | `skipped`.
- `tag` of a line: `step` | `err` | `ok` | `muted` | `null`.
- `error` (on `failed`): `{"code", "message", "detail", "fix", "action"}` as in section 3, read
  from the run's own output, matched in this order: `docker-down` (`action: "docker-start"`),
  `product-down` (`action: "product-start"`), `databases-down` (`action: "databases-start"`),
  `extraction-off` (`action: "extract-backlog-count"`), `changed` (a stop found processes that
  were not in its question: ask again), `port-in-use`, `no-target`, `refused` (only the runner's
  own `error: ... refused: ...` lines, never a program's "connection refused"), `missing-tool`;
  else `timeout` or `failed`. When `colima stop` overran its two minutes, `message` is "Docker
  did not stop in time" and `action` is `"force-stop-docker"`.
- `GET /api/runs?limit=20` (1 to 50) → `{"runs": [Run without "lines"]}`, newest first, this
  launch only. A run is `running` only while its runner is at work: one whose runner went idle
  without its end (a defect) is finished as `failed` two seconds later, with `error.code`
  `stopped` ("It stopped unexpectedly") and a `run.finished` event, and a run that could not
  start is `failed` at once.
- `GET /api/runs/{run_id}` → the Run with its last 2,000 `lines`.
- `POST /api/runs/{run_id}/cancel` → `{"ok": true}`: SIGTERM to the running step's process
  group, SIGKILL five seconds later to what is left. Every step starts its program in a new
  session of its own, so that group holds only what the step started. `409 not-running` when it
  has finished.

## 5. The event stream: `GET /api/events`

`Content-Type: text/event-stream`, `Cache-Control: no-store`. The helper starts with `retry:
3000`, sends `: ping` every 15 s, and gives every event an `id:` (a rising integer). On
reconnect it honours `Last-Event-ID`: it replays the events after it from its last 500, or, when
that id is too old, sends `hello` with `"resync": true` and the UI fetches everything again.

| event | data |
| --- | --- |
| `hello` | `{"api": 1, "demo": false, "build": "...", "resync": false}`, first on every connection |
| `status` | the status body (section 6), right after `hello` and whenever it changes |
| `actions` | `{}`: the catalog changed; fetch it again |
| `processes` | `{"taken_at": ...}`: a new process scan; fetch `/api/processes` when shown |
| `kafka` | the `/api/kafka` body, when a read finishes |
| `features` | `{}`: a features read finished; fetch `/api/features` |
| `github` | `{}`: a GitHub read finished; fetch `/api/github` |
| `run.started` | `{"run_id", "action_id", "title", "kind", "steps": ["..."], "started_at", "params"}` |
| `run.step` | `{"run_id", "index", "label", "state", "seconds"}` |
| `run.output` | `{"run_id", "lines": [{"text", "tag"}]}`, batched (at most every 100 ms, 200 lines) |
| `run.finished` | `{"run_id", "action_id", "state", "ok", "cancelled", "seconds", "finished_at", "steps": [...], "error": Error or null}` |
| `toast` | `{"level": "info" \| "success" \| "warning" \| "error", "title", "body", "action", "run_id"}`; `run_id` is set when the notice is about a run (the UI shows its own notice for runs and drops these) |

A slow client that falls 1,000 events behind is disconnected; it reconnects and resumes.

`POST /api/events/ticket` → `{"ticket": "t-...", "expires_in": 30}` for `EventSource`
clients (`/api/events?ticket=t-...`).

## 6. Status: `GET /api/status`

Served from the shared poller's cache at once, never by probing in the request. The poller
reads every 2 s while a window is connected and every 15 s otherwise (processes every 10 s or
30 s, git every 30 s or 60 s), one read of each kind at a time.

```json
{
  "taken_at": 1791290000.0,
  "loading": false,
  "demo": false,
  "summary": "The web app and 10 of 10 services are running. The product is stopped.",
  "level": "partial",
  "docker": { "up": true, "detail": "Colima" },
  "infra": [
    { "service": "postgres", "label": "Postgres (the database)", "profile": "core", "state": "running",
      "health": "healthy", "up": true, "ports": [5432], "status": "Up 2 hours (healthy)", "exit_code": 0 }
  ],
  "services": [{ "name": "identity", "port": 8001, "up": true, "url": "http://localhost:8001", "docs_url": "http://localhost:8001/docs" }],
  "web": { "up": true, "port": 3000, "url": "http://localhost:3000" },
  "product": {
    "internal": { "up": false, "port": 8080, "url": "http://127.0.0.1:8080" },
    "public": { "up": false, "port": 8000, "url": "http://127.0.0.1:8000" },
    "worker": { "up": false, "port": 8081, "url": "http://127.0.0.1:8081" },
    "web": { "up": false, "port": 3400, "url": "http://127.0.0.1:3400" },
    "pids": { "app": null, "worker": null, "web": null },
    "llm_provider": null
  },
  "background": [{ "key": "worker-pipeline", "label": "pipeline worker", "kind": "worker", "service": "pipeline", "pid": null }],
  "checkout": { "branch": "pipeline-ops", "sha": "99c7e87", "subject": "...", "when": "2 hours ago",
                "dirty": 2, "ahead": 29, "behind": 1, "is_main": false, "error": "" },
  "sessions": [{ "pid": 4242, "label": "make check", "elapsed": 192, "kind": "agent",
                 "uses": ["docker"], "text": "make check (pid 4242, 3m 12s) with 6 more" }],
  "warnings": [{ "code": "not-main", "tone": "warning", "title": "This checkout is on pipeline-ops, not main",
                 "message": "This checkout is on pipeline-ops, not main: anything you start runs that branch's code.", "items": [] }]
}
```

- `loading: true` (and the probe parts `null` or empty) until the first reads have landed.
- `level`: `running` (everything up) | `partial` | `stopped` | `unknown`.
- `infra` lists every container `docker compose ps -a` reports, all profiles.
- `product.llm_provider`: the model provider of the running product's gateway (`fake`,
  `vercel`), read from the `gateway_wired` line of `var/product/app.log`; `null` while the
  product is not running or its log does not say.
- `sessions` are other sessions' process groups in this checkout. `kind`: `agent` (under Claude
  Code), `terminal` (under a terminal app), `panel` (another control window), `other`. `uses`:
  `docker` and/or `product`, what a stop would break.
- `warnings` has the Warning shape of section 4: `not-main`, and `sessions` when other sessions
  use the stack.

## 7. The other reads

| Route | Response |
| --- | --- |
| `GET /api/meta` | `{"api": 1, "demo": false, "build": "...", "repo": "/Users/.../compliancewatch", "started_at": ...}` |
| `GET /api/flags` | `{"flags": [{"name", "type", "owner", "default", "env", "value", "source", "description", "removal", "expires"}], "error": ""}` |
| `GET /api/processes` | `{"taken_at", "ports": [{"port", "what", "group", "url", "pid", "command", "origin"}], "processes": [{"pid", "pgid", "ppid", "elapsed", "command", "origin", "kind": "this-app" \| "other"}], "error"}` |
| `GET /api/processes/{pid}/stop-preview` | `{"pid", "command", "options": [{"mode": "group" \| "tree", "pgid", "text", "pids": [{"pid", "command", "origin"}], "refused": ""}], "warnings": [Warning], "confirm_token", "expires_in": 120}`, from a fresh read of the processes (`503 scan-slow` past 15 s; `404` when the pid is not running). `confirm_token` is `null` when every option is refused. What an editor or Claude Code (or another agent) runs in the checkout is listed with the origin `run by Claude Code` or `run by an editor` and is always refused ("Claude Code runs it; stop it there"), as is a process group that holds a process this app may not stop, and language servers and editor helpers are never the checkout's processes |
| `POST /api/processes/{pid}/stop` | body `{"mode": "group", "confirm_token": "..."}` → `202 {"run_id"}` (a run titled "Stop process N"). The token carries the pids that mode named, each with its program. The step reads the processes again and sends SIGTERM, one `kill` per pid, only to pids both named and found running the same program (never a signal to a whole group), then SIGKILL after 5 s to those still running it; it logs by name what it left alone, and fails with `changed` when something new joined since the question |
| `GET /api/logs` | `{"sources": [{"id", "label", "group", "path", "kind": "file" \| "container", "available"}]}`; `available` is false while a file log does not exist yet |
| `GET /api/logs/{id}?tail=500` | `{"id", "label", "lines": ["..."], "truncated", "path", "taken_at", "error"}`; `tail` 1 to 2000 |
| `GET /api/features` | `{"features": [Feature], "loading", "reading"}`: the last read at once; a read older than 30 s starts in the background and a `features` event says when it lands. The first read is waited for up to 1.5 s; when it takes longer, the answer is `loading: true` with an empty list, and the event follows |
| `GET /api/kafka` | `{"taken_at", "groups": [{"group", "state", "members", "total_lag"}], "topics": [{"name", "partitions", "messages", "dead_letters"}], "error", "next_in", "reading"}`: the last read, at once (`taken_at: null` before the first) |
| `POST /api/kafka/refresh` | `{"started": true, "next_in": 30}` or `{"started": false, "next_in": 12}`; the result arrives as a `kafka` event (rpk runs at most once every 30 s) |
| `GET /api/docs` | `{"docs": [{"id", "label", "path", "kind": "doc" \| "folder", "action": "open-doc", "params": {"doc": "<id>"}}]}`, only those that exist in the checkout |
| `POST /api/docs/{id}/open` | `{"ok": true, "opened": true, "target": "...", "message": "Opened Onboarding"}` (macOS `open`) |
| `GET /api/github` | `{"available": true, "reason": "", "repo_url", "branch", "links": [{"label", "url"}], "prs": [{"number", "title", "url", "branch", "checks": "passing" \| "failing" \| "pending" \| "none"}], "loading", "reading"}`; read-only through `gh` when it is installed and signed in, cached 60 s, read like the features (a `github` event when a read lands); otherwise `available: false`, a plain `reason`, and the links |
| `POST /api/heartbeat` | `{"ok": true, "idle_exit_in": 600}` |
| `POST /api/quit` | `202 {"ok": true, "quitting": true}`: the helper stops 0.3 s later, cancelling what runs (the window's Quit outside the app; in the app the window asks the app, which stops the helper itself). `"quitting": false` when nothing owns the stop (tests). |
| `GET /api/prefs` | `{"tour_done": false, "last_view": "", "dismissed": []}` |
| `PUT /api/prefs` | the same keys, any subset → the merged prefs. Kept in `~/Library/Application Support/ComplianceWatch Control/prefs.json` (or `$CW_CONTROL_PREFS`), never in the checkout; in `--demo`, in memory only. Other keys: `400 bad-params`. |

**Feature**

```json
{
  "id": "review-queue",
  "title": "Review queue",
  "summary": "Drafts waiting for a person to check them.",
  "state": "live",
  "numbers": [{ "label": "Waiting", "value": 12, "hint": "drafts in the queue" }],
  "links": [{ "label": "Review queue", "url": "http://127.0.0.1:3400/admin/review", "live": true }],
  "note": "",
  "source": "GET /v1/rulebook/review/stats"
}
```

`state`: `live` (numbers read from the running product), `not-running` (the route exists, the
product is stopped), `not-built` (no route in the committed OpenAPI specs yet; `note` says so),
`error` (the product did not answer this read; `note` says so in plain words and `error` has
the technical reason). Ids: `review-queue`, `pipeline-tasks`, `dead-outbox`, `runs`, `fan-out`,
`obligations`, `changes`, `notifications`, `flags`, `product-check`, `eval-report`. A link's
`live` is true when the web app's screen list marks that screen live; the UI shows the others as
"not built yet".

## 8. What the helper will never do

The safety rules in `panel_core`, re-checked here: no shell; nothing that contacts the regulator
sites (backfill, label index, a live crawl); no `--destructive` and no rollback step;
`product-seed` only without arguments and while the product answers; no `ARGS`, `MAKEFLAGS` or
similar passed on; the crawl forced off; no stop that reaches a process outside the checkout, a
control window, or what an editor, Claude Code or another agent runs (language servers and
editor helpers are never the checkout's processes); every stop previews the pids it reaches and
signals only those, one by one, never a whole process group it did not start; no model call
without a question. Make gets an `ARGS` only from a fixed allowlist keyed by action id
(`extract-backlog-count`: `--dry-run`; `seed-check`: `--check`; `product-check`: `--step` and one
of the checkout's steps), never from what a person types. It never writes the token, never
fetches, and never runs a git command that writes.

## 9. `--demo`

The same routes, from a fake core: realistic canned status, catalog, features, flags,
processes, logs, Kafka and GitHub data; no subprocess, no signal, no network, no file written.
Runs are simulated: they stream output step by step at a realistic pace and can be cancelled,
and when they finish they change the demo world (Start everything brings everything up, Stop
everything takes it down), so `status` follows what was run.

As it starts, the demo shows its error paths:

- the product is stopped, so `product-seed`, `product-check` and `product-e2e` are disabled
  with "The product is not running." and `fix_action: "product-start"`;
- `gate:lint` fails with eslint's own lines;
- Claude's build agent is running `make check`, so the stops and `restore`/`reset` warn that they
  break it (`sessions`);
- the checkout is on a branch (`demo-branch`), not main, so the `not-main` warning shows.

### `POST /api/demo/state` (only with `--demo`)

For the UI's tests: sets the made-up world. Token required; without `--demo` it is `404`. The
whole body is checked before anything changes (`400 bad-params` names the first problem), and
the stream then sees the new world at once (`status`, `processes` and `actions` events). Every
key is optional:

```json
{
  "reset": true,
  "world": {
    "docker": true,
    "infra": true,
    "tools": false,
    "services": 10,
    "web": true,
    "product": { "internal": true, "public": true, "worker": true, "web": false },
    "workers": ["pipeline"],
    "relays": [],
    "branch": "pipeline-ops",
    "dirty": 2,
    "sessions": "agent",
    "mishaps": false
  },
  "fail_next": { "action": "docker-stop", "step": 0, "state": "timeout", "lines": ["waiting for the VM to stop..."] },
  "prefs": { "tour_done": true },
  "speed": 3,
  "expire_tokens": true
}
```

- `reset`: first cancels any run and forgets every run, unarms `fail_next`, drops the confirm
  tokens and the Kafka read, and sets the world the tests start from: everything stopped, on
  main, no other session, none of the demo's own failures, the canned backups.
- `world` (merged into the current world):
  - `services`: how many of the ten answer (0 to 10; `true` is 10);
  - `product`: the parts that answer, merged (`true` or `false` sets all four);
  - `tools`: the observability containers;
  - `workers`, `relays`: the services whose worker or relay this app runs (or the mock's
    `background: {"worker-pipeline": 52000}`);
  - `sessions`: `"agent"` (Claude's build agent runs `make check` here) or `"none"`;
  - `mishaps`: the demo's own failures (`gate:lint`).
- `fail_next` (or `failNext`): the next run of `action` prints `lines` at step `step` (0 is the
  first; default 0) and ends there `failed` (default) or `timeout`; the run's `error` is read
  from those lines as for a real run. `null` unarms it.
- `prefs`: as `PUT /api/prefs`.
- `speed`: how much faster than the demo's own pace runs play (0.1 to 50).
- `expire_tokens` (or `expireTokens`): every confirm token issued so far stops working.

Answer: `{"ok": true, "world": {... the whole world, "fail_next", "speed"}, "prefs": {...}}`.

## 10. Curated action ids

`start-everything`, `stop-everything`, `docker-start`, `docker-stop`, `force-stop-docker`,
`databases-start`, `databases-stop`, `ui-start`, `ui-stop`, `ui-restart`, `ui-wait`,
`web-start`, `web-stop`, `product-start`, `product-stop`, `product-wait`, `product-role`,
`product-seed`, `product-check` (param `step`, optional), `product-e2e`, `product-logs` (param
`proc`), `mvp-image`, `product-image`, `product-image-down`, `product-image-logs` (param
`proc`), `load-demo-data`, `demo`, `migrate` (param `service`, optional), `migrations-check`,
`migrations-catalog`, `data-quality`, `seed-check`, `backup`, `restore` (params `dump` and
`backup_first`, boolean, default true), `reset` (param `backup_first`, boolean, default true),
`psql`, `gates-in-order`, `gate:<target>` (for example `gate:check`, `gate:lint`),
`crawl-report`, `extract-backlog-count` and `extract-backlog` (both only where the checkout's
Makefile has `extract-backlog`), `flags-check`, `doctor`, `dev-observability`, `dev-llm`,
`dev-flags`, `dev-ps`,
`container-logs` (param `service`), `worker-start`, `worker-stop`, `relay-start`, `relay-stop`
(param `service`), `open-env`, `open-logs-folder`, `open-backups-folder`, `open-doc` (param
`doc`).

Every `##`-documented Makefile target not covered above is in the catalog as `make:<target>`,
classified; targets that contact the regulator sites, run forever in the foreground, need a
terminal or arguments (`replay`, `golden-export`), or change the app or the git hooks are
`refused` with the reason.

## Changes from API-REQUESTS.md

- **Errors** carry `message` (what the request called `title`), plus `detail`, `fix`, `action`
  and `code`. `ui/api.js` already reads `message`.
- **Confirms** use a token, not `confirm: true`: `POST /api/actions/{id}/preview` gives the
  server's confirm text and warnings with a `confirm_token`, which `run` takes back (`confirm`
  is accepted as its other name). Safe actions need no preview. Process stops work the same way.
- **Previews** name the pids a stop reaches (`reaches`, at the top level and in `confirm`).
  Warnings have a `tone`, a `title` and `items`.
- **Runs**: `run.started` has `params`; `run.finished` has `state`, `action_id` and
  `finished_at`; a `colima stop` that timed out ends with `error.action: "force-stop-docker"`.
  A `toast` about a run carries its `run_id`.
- **Optional choices**: `""` means "not given" for `product-check`'s `step` and `migrate`'s
  `service`, in previews and runs.
- **Needs**: an action whose needs are unmet is `enabled: false` with a plain `reason` and a
  `fix_action`, before anyone presses it.
- **Event stream**: the header on `fetch()` works as asked, `id:` and `Last-Event-ID` too; a
  ticket exists for `EventSource`. New events: `processes`, `kafka`.
- **Kafka**: `GET /api/kafka` never runs rpk; `POST /api/kafka/refresh` does.
- **Prefs**: as asked, plus `last_view` and `dismissed`.
- **Logs**: a source says `available` (the UI also reads `exists`).
- **Tests against `--demo`**: `POST /api/demo/state` takes the mock's `/__mock/state` body.
- **Launch codes**: the window's address carries a single-use launch code, never the token
  (`POST /api/launch-code`, `POST /api/launch`).
- **Quit**: `POST /api/quit` for the window's Quit outside the app.
- **New**: `GET /api/meta`, `POST /api/docs/{id}/open`, `safety: "refused"`, status `level` and
  `warnings`, session `uses`, run `kind` and `current_step`, step state `queued`, catalog
  `preview` and `keywords`, feature state `error`, and the ids `migrations-check`,
  `product-image-logs`, `container-logs`, `open-logs-folder`, `open-backups-folder`,
  `force-stop-docker`, `open-doc`.
