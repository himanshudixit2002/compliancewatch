# The control panel

The control panel is one window over the whole project: the dev stack, the services and their
workers, the product, the data, the quality gates, the pipeline's events, the flags and the
checkout's processes. Every button runs a make target of the repo, or a plain program, so the
panel adds no behaviour of its own; this page lists what each tab runs and what the panel never
does.

```bash
make control-panel           # open the window from a terminal, from this checkout's files
make control-panel-app       # build ComplianceWatch.app on the Desktop (DEST=~/Applications)
```

The window uses only Python's standard library (tkinter); `tools/control-panel/panel_core.py`
holds its logic (the probes, the parsers, the command plans, the checks and the runner) without
tkinter, and `tools/control-panel/tests` tests it without a display, Docker or a network.
`CW_CONTROL_PANEL_REPO=<path>` points the window at another checkout.

## The app

`make control-panel-app` builds ComplianceWatch.app on the Desktop, or in `DEST`. The bundle
carries its own copy of `control_panel.py` and `panel_core.py` in
`Contents/Resources/control-panel`, with a `BUILD` file that records when it was built, the
commit the files came from (`+changes` when they differ from it) and their hash. Its launcher
changes into the checkout, sets `CW_CONTROL_PANEL_REPO` to it and runs that copy with the
checkout's `.venv/bin/python` (after `uv sync --all-packages` when the venv is missing). The
window is therefore the one installed whatever branch the checkout is on; the make targets it
runs are the checkout's. The footer names the build: its date and commit, or "this checkout's
tools/control-panel" for `make control-panel`.

To update the app, run `make control-panel-app` again from a checkout that has the panel you
want; it replaces the bundle. From a copy of the panel outside a checkout, name the checkout:
`CW_CONTROL_PANEL_REPO=<checkout> tools/control-panel/install-app.sh [destination]`.

## How it runs things

- **No shell.** Every step is an argument list (`make product WEB_PORT=3400`, `colima start
  ...`), and links and files open through macOS's `open` the same way; nothing goes through a
  shell. A Finder-launched app gets a bare PATH, so the panel puts `/opt/homebrew/bin` and
  `/usr/local/bin` first and `~/.local/bin` last.
- **Checked where it starts.** Every program is checked where it starts, not only when its
  button is pressed: no shell, nothing that reads the regulator sites, no `--destructive`, the
  crawl off (`CW_PIPELINE_CRAWL_ENABLED=false` for everything the panel starts), make without
  options or shell characters, a destructive target only in a step that asked first, and only
  the checkout's make targets. A step the panel performs itself declares every program it runs,
  and the runner refuses any other. The panel passes none of `ARGS`, `MAKEFLAGS`, `MFLAGS`,
  `GNUMAKEFLAGS`, `MAKELEVEL`, `MAKEOVERRIDES`, `SERVICE`, `PROC`, `FOLLOW`, `FILE` or `WEB` on
  from the environment it was opened in, so `make control-panel ARGS=--destructive` reaches no
  target.
- **One step at a time.** A step is anything that starts, stops or changes something. While
  one runs, the other step buttons wait; links, status, tables and logs stay usable.
- **The output pane.** A step streams into the Steps tab of the pane at the bottom; logs and
  other reads (container logs, `make product-logs`, `make dev-ps`, the crawl report) stream
  into Logs and reads, so they never mix with a running step. Drag the bar above the pane to
  give it more room. When the window falls 20,000 lines behind a step, the pane says how many
  lines it left out.
- **Cancel.** Each step runs in a session of its own, so Cancel ends the running step's whole
  process group: SIGTERM, then, five seconds later, SIGKILL to whatever of the group is left,
  whether or not the step's first process has exited. Cancelling `make product` or
  `make web-stack` therefore also stops what they had started. A read stops by itself after
  three minutes.
- **Time limits.** Each step of a stop has one: the web app 1 minute, `make web-stack-down`
  and `make product-down` 2, the panel's workers and relays 1, `make dev-down` 3 and
  `colima stop` 2. A step that overruns is stopped the way Cancel stops it and shows as timed
  out. When `colima stop` times out, the panel offers `colima stop --force` as a question of its
  own; Stop everything never forces. While a step runs, the line above the output says which
  step of how many it is and for how long it has run. A step's output stops being read two
  seconds after its program exits, so a process it left behind holding the pipe cannot hold
  the step.
- **Confirms.** Stop everything, reset, restore, stopping Docker and Cancel ask first and say
  what they remove or stop. So does stopping a process this panel did not start: the UI-only
  stack or the product when another window or a terminal started them, the web app (its confirm
  names each pid its stop reaches), and anything on the Processes tab. Before Docker or the
  product stops (Stop everything, Docker or Databases Stop, Product Stop, a restore or a reset),
  the confirm names other sessions' processes in the checkout that use them, such as another
  terminal's `pytest` or `make product-check`, and says the stop will break them. A question
  opens in a small window of the panel's own, not a macOS sheet: the panel keeps drawing,
  polling and streaming while it is open.
- **What it writes.** Nothing until you start something. Then: `var/control-panel/registry.json`
  (the process group of every step and background process it started, so it can tell them
  from another session's), the pid and log file of each worker and relay it starts in
  `var/control-panel/`, the web app's in `var/web-stack/web.pid` and `web.log` as before, and
  `var/control-panel/psql.command` for the psql button. A `hang-<time>.log` appears there only
  when the window stopped responding. `var/` is git-ignored.
- **Probes.** The status (Docker, the containers, every `/health` and `/ready`) refreshes every
  four seconds on a background thread. git, `ps` and `lsof` run every 30 seconds and when a tab
  needs them. rpk runs on demand, at most once every 30 seconds however it is asked: the
  button, a visit to the Pipeline tab or its 30-second box. Only one probe of each kind runs at
  a time, and each program a probe runs has a hard limit (6 seconds for `docker info`, 8 for
  `docker compose ps`, which hang while Colima stops): past it, SIGKILL goes to the program's
  whole process group. No probe thread touches the window; each hands its result to the window's
  own loop.
- **When the window stops responding.** A watch thread notices when the window's event loop has
  not run for five seconds and writes `var/control-panel/hang-<time>.log`: the main thread's
  Python stack, the other threads' stacks and the timers and idle callbacks that were waiting.
  When the window answers again, a banner under the title names the log.

Closing the window leaves the stack, the services and the panel's workers running; Stop
everything shuts them down. Closing it while a step runs cancels that step, after a confirm.

## The tabs

### Overview

The status the panel always showed (Docker, the databases and queues, the web app on 3000, the
product on 8080 and the ten services' `/health`), the big buttons (Start everything, Stop
everything, and the two web apps), and quick start and stop buttons for Docker, the databases,
the UI-only stack, the web app and the product.

Stop for the web app reads the processes first. It reaches the process tree of the web app the
panel recorded (`var/web-stack/web.pid`, while that pid still runs it) and of whatever of this
checkout listens on the web port, from the top of its pnpm and next chain, and names each pid
in its confirm when this panel did not start them all. It never signals a process group: a
`make product` from a terminal whose web app holds the port keeps its app and worker, which
share that group. A pid that appears after the confirm is left alone.

**The code the stack runs** reads the checkout through `git --no-optional-locks`, which takes
no lock: the branch, the short sha and subject, the count of uncommitted files, and how far HEAD
is ahead of and behind `origin/main` as last fetched (the panel never fetches). A branch other
than `main` shows in amber, here and beside the window's title.

**Not started by this panel** lists, when there are any, the checkout's processes that another
session started: another terminal's `make check` or `pytest`, a `make product-check`, another
control panel window. Click it for the Processes tab.

### Stack

The containers of every compose profile with their state, health and ports (`docker compose
ps -a`); `make dev` and `make dev-down`; `make dev-observability` (Langfuse, the OTel collector,
Prometheus, Tempo, Grafana), `make dev-llm` and `make dev-flags`; `make dev-ps`; and the last
200 lines of one container's log (`docker compose logs --tail 200`, never `--follow`). Links
open what the stack serves: the Temporal UI, Grafana, Prometheus, Langfuse, Unleash, the
OTel collector's health and the fake LLM gateway's docs. Redpanda has no console in this stack,
so its admin API and schema registry stand for it.

### Services

The ten services of the UI-only stack with their port and `/health`, a link to each one's
`/docs` and its log (the last 200 lines, or the whole file in Console). Start and Stop for
`make web-stack STORE=postgres`. `make web-stack-down` signals a pid of `var/web-stack` only
while it still runs that file's service (its uvicorn, or the web app's pnpm or next); a pid that
now belongs to another program is left alone and its file removed.

Workers and outbox relays start and stop here as background processes the panel keeps:
`make worker SERVICE=<service>` for the five services with a worker module and
`make relay SERVICE=<service>` for those whose migrations create an outbox, each in a session
of its own, with its pid and log in `var/control-panel/worker-<service>.*` or
`relay-<service>.*`. A recorded pid counts only while its command line is still that worker's
or relay's, so a pid reused after a reboot neither reads as running nor blocks a start. Each
starts with `CW_PIPELINE_CRAWL_ENABLED=false`, whatever `.env` says. The product's own worker
already runs every relay and consumer, so these are for the UI-only stack.

### Product

Each listener and process of `make product` with its health: the app's internal listener
(`/ready`), its public listener (`/health`), the worker (`/health`, and a link to `/loops`) and
the web app on 3400, with the pid listening on each port and who started it; and the three
containers of `make product-image`.

| Button | Runs |
| --- | --- |
| Start, Stop, Wait, Role | `make product WEB_PORT=3400`, `make product-down`, `make product-wait WEB_PORT=3400`, `make product-role` |
| Seed | `make product-seed`, only while the product's internal listener answers `/ready` |
| Check all, Check this step | `make product-check`, or `make product-check ARGS="--step <step>"` with a step from `cw-product check`'s own list |
| Web journey | `make product-e2e PRODUCT_E2E_PORT=3401` (3400 is the product's web app) |
| Logs app, worker, web | `make product-logs PROC=<proc> FOLLOW=0` |
| Image: Build, Start, Stop, logs | `make mvp-image`, `make product-image`, `make product-image-down`, `make product-image-logs PROC=<proc> FOLLOW=0` |

The web app on 3400 opens at `127.0.0.1`, so its session stays apart from the UI-only web app's
on `localhost:3000` (product.md, "Signing in on the web"). The links under it go to the admin
pages the web app's screen registry (`apps/web/src/shared/config/screens.ts`) marks live; a page
it does not, such as the review queue today, is named as not built yet.

### Data

`make migrate` for every service or one, `make migrations-check`, `make migrations-catalog`,
`make data-quality`, the seed calendar's check (`make seed SERVICE=rulebook ARGS=--check`),
Load demo data (`make seed SERVICE=rulebook`, then `make web-seed` for the UI-only stack) and
Run the demo (`make demo`). psql opens Terminal on `make dev-psql`.

Back up runs `make dev-backup`. Restore offers the dumps of `var/backups` newest first, each
with its size and age, and leaves out an empty one: `make dev-backup` creates its file before
`pg_dump` writes to it, so a failed or cancelled backup leaves one behind. Before the confirm,
the panel reads the picked dump with `pg_restore --list` in the Postgres container (the file on
its standard input, as `make dev-restore` gives it) and refuses one it cannot read; the confirm
says what it read and that `make dev-restore` drops the database first. The restore reads the
dump again as its first step.

Reset DB asks whether to back up first, then stops the UI-only stack, the product's processes
and the panel's workers and relays, and runs `make dev-reset`, `make dev`, `make migrate` and
the seed calendar. Its confirm lists every named volume `make dev-reset` removes, read from
`docker-compose.yml` with the compose project's name (`compliancewatch_postgres_data`,
`compliancewatch_redis_data`, `compliancewatch_redpanda_data`,
`compliancewatch_prometheus_data`, `compliancewatch_tempo_data`,
`compliancewatch_grafana_data` today), with what each holds.

### Gates

One button per gate: `make check`, `lint`, `typecheck`, `test`, `py-test-integration` (with
`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`), `eval EVAL_PROFILE=ci`,
`eval-check`, `openapi-compat`, `contracts-check`, `alerts-check`, `flags-check`,
`migrations-check`, `sast`, `deps-scan`, `web-screens-check`, `web-e2e` and `ci-lint`.

**Run the CI gates in order** runs the gates of `make check` one by one in the order of CI's
jobs, then `eval-check` and `eval`, `openapi-compat`, the ops checks, `py-test-integration`,
`sast` and `deps-scan`, carrying on past a failure, and ends with each gate's result and
duration; the table keeps them. It leaves out `make check` itself (its gates run one by one),
`web-e2e` (it needs the seeded UI-only stack), CI's dev-stack job, whose
`make product-check ARGS="--destructive"` needs a database made for the run, and any gate the
checkout's Makefile does not have.

### Pipeline

`make crawl-report`, which only reads the pipeline store, and the consumer groups with their
lag and the topics with their message counts, read through
`docker compose exec -T redpanda rpk group describe` and `rpk topic describe`, at most once
every 30 seconds. A dead-letter topic that holds messages shows in red. The links open the
Temporal UI, the worker's `/loops`, the source manager's and the task queue's JSON on the
internal listener, and the admin pipeline and review pages once the screen registry marks them
live.

### Flags

A read-only table of `packages/flags/registry.json`: each flag's owner, default, the variable
that sets it (its own `env`, or `CW_FLAG_<NAME>`) and the value `.env` gives it, or
`apps/web/.env.local` for a web flag and `apps/whatsapp-bot/.env` for the bot's. Pick a flag to
read what it does and when it is removed. `make flags-check` and Open .env (`open -t .env`) are
here; the panel never changes a flag.

### Processes

Every port the project uses, both stacks, the infrastructure and the tools, with the pid and
command listening on it (`lsof -iTCP -sTCP:LISTEN` and `ps`); Docker's ports show as Colima's
port forwarding. Below them, the checkout's processes: make, `uv run`, pnpm, the repo's Python
and Node scripts of the checkout, running in it or naming a path in it, and their children that
stay in it, each with how long it has run and who started it (this panel, `make web-stack` or
`make product` by their pid files, another control panel window, or another session). Shells,
Claude Code and the tools an agent fetches (`uvx`, `uv tool`, MCP servers), editors, Colima's
own processes and anything in a worktree under `.claude/` are never the checkout's, even when
they run in its directory.

Stop selected sends SIGTERM after a confirm that names every process it reaches: the process
group, when every member is the checkout's and none is a control panel window; or the process
and its children, which the confirm offers too when the group holds more. It refuses a control
panel window, this one or another, and a process with a window under it (the make behind
`make control-panel`).

### Docs

Opens the onboarding guides, the README, CONTRIBUTING and the runbooks and ADR folders,
`make doctor` (which tools are on the PATH), and the repository's pull requests, Actions, the
current branch and its comparison with `main` on GitHub (from `git remote get-url origin`).

## What it never does

- Run anything through a shell, a program a step did not declare, or a step while another
  runs.
- Run `make backfill`, `make label` or anything else that contacts the live regulator sites,
  or start anything with the crawl on.
- Pass `--destructive` to `make product-check`: its rollback step withdraws gstr9_annual, which
  the shared dev database keeps published (product.md, "Honesty"). Rollback is not in the list
  of single steps either, and an `ARGS` or `MAKEFLAGS` in the environment the panel was opened
  in reaches no target.
- Run `make product-seed` with arguments, or while the product does not answer.
- Signal itself, another control panel window, a process outside the checkout, or a process
  group that holds a control panel window.
- Write anything in the checkout before you start something (but a hang log, when the window
  stopped responding), fetch, or run a git command that writes.
- Force-stop Colima without asking: `colima stop --force` runs only after its own question.
- Edit a flag, `.env` or a tracked file itself. The make targets it runs write what they always
  write: `make dev` creates `.env` from `.env.example` when it is missing; `make contracts-check`
  regenerates the generated clients, which are tracked files, before it compares them;
  `make test`, `make sast` and `make eval` write their reports (`coverage.xml`, `semgrep.sarif`,
  `evals/reports/`); and the web builds write under `apps/web/.next`. All of these but the
  generated clients are git-ignored.

## When something is off

- **The app opens an older panel.** The footer names the build; run `make control-panel-app`
  again from a checkout that has the panel you want.
- **`make X is not a target of this checkout's Makefile`.** The checkout is on a branch without
  that target; the panel checks every step's targets against the Makefile before it runs one.
- **A tool is missing in a step started from the app.** Run Docs, Which tools are installed
  (`make doctor`): the app's PATH is Homebrew's and the system's.
- **Another session's processes.** The Overview names them and the Processes tab lists them;
  a reset, a restore or Stop everything affects them too, and their confirms say so.
- **The window stopped responding.** The banner names the log in `var/control-panel/`; attach
  it to the report. Before this build, a tab never opened could re-lay itself out for ever once
  its text changed (after Stop everything, the Product tab), and the next tab click froze the
  window at full CPU; the tabs now keep a width of their own.
- **colima stop timed out.** Answer the force-stop question, or leave Colima as it is and run
  `colima stop` in a terminal to watch it.
