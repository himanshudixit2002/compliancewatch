# ComplianceWatch Control

ComplianceWatch Control is the Mac app that runs ComplianceWatch on this Mac and shows what it
is doing. It is for everyone on the team, technical or not: every button says what it does,
what happens to the computer, how long it usually takes and how safe it is, and the technical
detail (commands, logs, process ids) is always one click away under "Show technical details".

ComplianceWatch watches regulators for rule changes, decides which changes apply to one
specific business, and turns each into a dated obligation the owner can act on. It starts with
Indian small businesses under GST.

## Open it

```bash
make control-panel-app       # build the app on the Desktop (DEST=~/Applications puts it there)
make control-panel           # open the same window in your browser, from a terminal
```

Building it again replaces the app in place: the new one is built beside the old one and swapped
in only when it is complete, and on any failure the old one stays. Built somewhere else
(`DEST=...`), macOS stops listing the old copy, and the build names it so you can delete it.

Open the app like any other. It starts a small helper on this Mac, and the window talks only to
that helper. The first time, a short tour shows you around (five steps; skip it whenever you
like, and replay it from the Guide). If your checkout is on the Desktop (or in Documents or
Downloads), macOS first asks whether the app may use that folder: click Allow. It asks again
after each new build of the app.

To close it, close the window or press Quit at the bottom of the sidebar (or ⌘Q). With nothing
running it quits at once. If something is still running, closing the window asks first: Keep
Running in Background closes the window and lets it finish (click ComplianceWatch Control in the
Dock to bring the window back), Quit stops it now. Quit and ⌘Q always quit, within a few
seconds, and stop whatever runs. The helper's messages are kept in
`~/Library/Logs/ComplianceWatch Control/helper.log`.

On this Mac:

- Everything runs on this Mac. Nothing here is a service for real customers.
- Nothing this app starts reads the real regulator websites: the crawl stays off.
- The full product writes its messages to a file (the sink) instead of sending them. Real
  WhatsApp and email stay off unless someone turns them on in `.env`.
- The demo businesses and people are made up. Their names say so: synthetic.

## The window

On the left, the sections: **Home**; to do things, **Run**, **Data** and **Checks**; to see
things, **Features**, **Pipeline & events**, **Flags**, **Processes** and **Logs**; to find
things, **Commands** and the **Guide**.

Along the top:

- **The lights** for Docker, Databases, Services, Product and Web. Each light has a shape as
  well as a colour: a filled green dot is running, a half-filled amber dot partly running, a
  spinning blue ring starting or stopping, an empty ring stopped, a red diamond needs attention.
  Choose one to go to its controls.
- **Activity**: what is running now, with its step and progress, and everything that ran since
  the window opened, each with its steps and output.
- **The branch chip**: the branch of the checkout. Amber means it is not `main`; red means
  another session (for example Claude's build agent running tests) is working in the checkout.
  Choose it for the details.
- **Search actions (⌘K)**: type what you want ("backup", "check", "start") to find any action,
  any place in the app or any Guide entry, and press Return.

### Every action says the same four things

Each action is a card with a title, a plain line, how long it usually takes and a safety badge:

| Badge           | Means                                                    |
| --------------- | -------------------------------------------------------- |
| Safe            | Starts or reads things. Nothing is lost.                 |
| Changes data    | Writes to your local databases or files.                 |
| Stops things    | Stops running parts. Anything using them is interrupted. |
| Deletes data    | Removes local data. You are always asked first.          |
| Never runs here | This app never runs it; the reason says why.             |

"What happens" lists the steps in plain words, and "Show technical details" the exact commands.
While an action runs, its card shows a progress bar, the step it is on ("Step 3 of 7: Migrate
databases"), how long it has run, Cancel, and its live output behind "Show the live output".
One action that starts, stops or changes something runs at a time; the others wait and say
what they are waiting for. A card that cannot run now says why ("Start the product first").

### Questions before risky actions

Anything that changes data, stops or deletes asks first, in plain words, and names exactly
what stops or changes; so does anything that asks the AI model. The question also warns when:

- the checkout is not on `main` (the action runs that branch's code and commands);
- another session is working in the checkout, naming it ("Claude's build agent is running
  make check"), because stopping what it uses breaks its work;
- the action asks the model and the model may be a paid one: "This may call a paid model" when
  the app cannot tell which model the gateway uses (the product is not running, or its log does
  not say), and the provider by name when it is a paid one.

Stopping the web app (and so Stop everything) first lists the processes it will reach, read
afresh when the question opens. Reset and Restore offer to back up the database first, and a
deletion needs a tick in "I understand that this deletes local data". Every such question is
asked, on `main` too; the window never answers one itself. "Run all checks" and the contracts
check ask too, since `make contracts-check` regenerates the generated clients.

### When something fails

A failed action says what went wrong in plain words ("Docker is not running"), what to do
about it, and offers the button that does it ("Start Docker"), with "Try again" and the exact
lines under "Show technical details". A notice in the corner says the same, and finished actions
say so there too, with the obvious next step ("Open the app").

## What each section does

**Home.** One big Start or Stop. Start everything starts Docker, the databases and queues, the
ten services and the web app at `localhost:3000`, then opens it; Stop everything stops all of
it, Docker included, and keeps your data. Below: "What is running", the parts as connected
boxes coloured as they run (choose one to start or stop it on its own); four quick tasks (open
the app, load demo data, run the checks, free up memory); recent activity; and the code the app
runs (branch, last change, uncommitted files, how far from `origin/main`).

**Run.** Each part on its own: Docker, the databases and queues, the services, the web app,
the full product and the product from its image, the optional tools (observability, the fake AI
gateway, Unleash), and a table of workers and outbox relays per service.

**Data.** Demo data (for the screens, for the product, and the five-minute demo); keeping the
databases up to date (all services or one) and their checks; Back up the database, Restore a
backup (the backups of `var/backups`, newest first, with size and age) and Start fresh (reset
the database); a database prompt in Terminal.

**Checks.** The quick checks (`make check`, what CI runs before Docker) and every CI check in
order; the product check (every step, or one) and the product's web journey; each check on its
own, Click through the web app among them; and the result of each check you ran since the
window opened.

**Click through the web app** runs the web app's browser tests, where a robot browser clicks
through every page and checks each one for accessibility problems, on a separate, temporary
copy of the services with throwaway data. The copy starts, the tests run against it, then it
stops: when the tests pass or fail, and when you cancel. Your own data and running app are never
touched: the copy uses none of your services, databases or ports, and the web app you have open
keeps running while the check builds its own. The robot browser is Playwright's own Chromium
when it is downloaded on this Mac; when it is not, the check uses your installed Google Chrome,
and with neither it stops at the start and offers Download the test browser (about 150 MB,
asked first). It takes 10 to 15 minutes. Its steps:

1. Check that the test copy can start: no other web check or browser tests running in the
   checkout, a browser for the tests, and its ports (9401 to 9410 for the services, 3410 for the
   web app) free. What an earlier check left running is stopped first.
2. Start a separate test copy of the services.
3. Wait until the test copy answers.
4. Add made-up demo data to the test copy.
5. Build the web app and click through it in a robot browser.
6. Stop the test copy.

**Features.** What the product can do today: live numbers from the running product (review
queue, pipeline tasks, fan-outs, obligations, changes, messages through the sink, flags, the
last product check and eval report), links to the web app's pages that exist, and "Not built
yet" where the product has no route for something.

**Pipeline & events.** How events move between the services: each consumer group with how far
behind it is, each topic with its messages, and dead-letter topics that hold messages in red.
It reads the queue at most once every 30 seconds. The crawl report is here too, and links to the
Temporal UI, the worker's loops and the pipeline's own answers.

**Flags.** Every switch in `packages/flags/registry.json`, in plain words, with the value this
Mac gives it and where that comes from; open a row for the full description, the variable, the
owner and when it goes away. This app never changes a flag: "Open .env" opens the file in your
editor.

**Processes.** Every port the project uses with the program on it, and the programs running
from this checkout with how long each has run and who started it. Stop shows exactly which
processes it would reach, and offers the process group or the process with its children when
they differ. It signals only the processes the question named, one by one, and leaves alone
(by name, in its log) anything that started after the question. It never stops another
control window, what an editor or Claude Code runs (language servers included), your terminal
itself, or anything outside the checkout, and it says why when it will not. A `make check` you
started in a terminal of this checkout can be stopped.

**Logs.** The end of each log (the services, the web app, the product, the workers and relays,
the containers): the last 200, 500 or 2,000 lines, find in the log, keep at the latest line,
copy.

**Commands.** Every action the app can run, the project's documented make targets among them,
searchable and grouped, filtered by safety. An action that may never run here (such as
`make backfill`) is listed with the reason. A make target that an action already does
(`make dev` is Start the databases) stays out of the list until you search for it, and then
names that action.

**Guide.** How ComplianceWatch works, what each part does, the recipes below with a button for
each step the app can do, a glossary, what to do when something goes wrong, what this app will never do,
the project's own guides, and the tour again.

## Two ways to run it

- **The screens (the UI-only stack).** Start everything on Home starts Docker, the databases
  and queues, the ten services (each on its own port, 8001 to 8010) and the web app at
  `localhost:3000`, then opens it. Use it to click through the screens. It has no worker, so
  publishing a rule does not turn into obligations or messages here.
- **The full product.** Run, The product starts the one app that holds every service, its
  worker (with the message queue and Temporal on) and its own web app at `127.0.0.1:3400`. Here a
  published rule really becomes decisions, obligations and a change card. Fill it with sample
  data, then check it works ([product.md](product.md)).

Your data lives in Docker's storage (volumes) on this Mac: Postgres holds every service's data
and Redpanda the messages between them. Stopping keeps it. Only Reset deletes it; it asks first
and offers to back up. Backups are files in `var/backups`.

## Recipes

The Guide has these with a button for each step the app can do, and a tick on a step that is
already done.

**See the app's screens** (about 10 minutes the first time)

1. Start everything. The first time, Docker downloads about 2 GB.
2. Load the demo data: the thirteen standing GST rules as drafts, a demo business with its
   answers, and one recorded CBIC notification.
3. Open the web app.
4. Sign in: choose the tenant kind Business, tick Owner, type any display name, press "Use the
   last seeded tenant", then Sign in. Nothing is checked on this sign-in page; it exists only on
   your Mac.

**Run the whole product** (about 10 minutes)

1. Start the product. It starts Docker if needed, updates the databases, then the product's
   app, its worker and its web app, and waits until all of them answer.
2. Fill it with sample data: two made-up customers, a business (Demo Traders) and a CA firm
   (Demo CA Associates), and a made-up publication of the three GSTR-3B rules.
3. Check it works: the product check runs its steps one after another and says which passed.
   Its rollback step always reports itself skipped here.
4. Open the product's sign-in page.

**Try it as a business owner.** With the product running and filled, open its sign-in page,
choose the tenant kind Business, tick Owner, type a display name, press "Use the last seeded
tenant", then Sign in. Demo Traders (synthetic) opens with its obligations, calendar and changes.
The Ask tab appears only when the web app's Q&A flag is on.

**Try it as a CA firm.** On the product's sign-in page choose the tenant kind CA firm, tick CA
admin, type a display name, paste the tenant id `00000000-0000-4000-8000-0000000d0002` and sign
in. It is Demo CA Associates (synthetic), with two client businesses. A change's Affected
clients page lists the clients it applies to; a page listing all clients is not built yet.

**Try it as an admin.** On the product's sign-in page choose the tenant kind Internal
(regulatory team), tick Admin, type a display name, leave the tenant id empty and sign in.
Internal tools (`/admin`) opens. Pages that are not built yet, such as the review queue, say
so.

**Show the five-minute demo** (a few seconds, no Docker needed). Run the demo: it records
consents, registers the business by GSTIN, decides which rules apply, makes the calendar and
sends a reminder in Hindi through a fake channel. [demo.md](demo.md) says what to point out at
each minute.

**Check your work before sharing it.** Run the quick checks (`make check`: code style, types,
tests and the project's own rules; no Docker needed). If one fails, its name turns red in
Checks; read its output, fix the cause, then run that check alone again. If you changed the web
app or a service it uses, click through the web app: its browser tests run on a separate,
temporary copy of the services, never on your own data. For a bigger change, run every CI check
in order: it needs Docker, takes much longer and carries on past a failure, then lists each
result.

**Stop everything to free memory.** Stop everything stops the web app, the services, the
product, this app's workers and relays, the databases and Docker itself. If another session is
working in this checkout, the question names it first.

**Start fresh.** Start fresh (reset the database) with "Back up first" ticked: Reset stops the services and
the product, deletes all local data (Docker's storage for this project), then starts the
databases again, empty, updated and with the seed rules. Then Start everything and load the demo
data again.

**When something breaks.** Look at the lights (grey is stopped, amber partly running, red needs
attention); read the error where it happened, with its fix button; open the part's log; look the
problem up below. Still stuck? Every output has a Copy button: send it to a developer.

## When something goes wrong

| What you see                                           | Why                                                                                                     | What to do                                                                                                                                                  |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Docker is not running                                  | The databases and the queue run inside Docker.                                                          | Start Docker. The first start takes a minute or two.                                                                                                        |
| Start everything stopped part-way                      | One of its steps failed; the card names the step and the reason.                                        | Use the fix button the card offers, or read Show technical details. Then press Start everything again.                                                      |
| A port is already in use                               | Another program, perhaps a second copy of the project, listens on a port this needs.                    | Processes lists every port with the program on it. Stop it there if it belongs to this checkout; otherwise quit that program, or change the port in `.env`. |
| Click through the web app says a port is in use        | Its test copy needs ports 9401 to 9410 and 3410, and another program listens on one of them.            | Processes shows which program. What an earlier check left (for example after the app was quit during the check) is stopped by the next check on its own; stop anything else there, or wait for it, then check again. |
| Click through the web app says there is no browser     | Its robot browser is Playwright's own Chromium, which is not downloaded on this Mac, and Google Chrome is not installed either. | Press Download the test browser (about 150 MB; it asks first), or install Google Chrome, then check again.                                                  |
| Click through the web app says browser tests are running | Another session (another control window, or Claude's build agent) runs the web check or the web app's browser tests in this checkout; they share their results folder. | Wait for them to finish, then check again.                                                                                                                  |
| The web app does not open                              | The first start builds it, which takes a minute or two.                                                 | Wait until the Web light turns green. If it stays grey, read its log in Logs, then stop and start the web app from Run.                                     |
| The product check fails                                | One of its steps found something wrong; the others still run.                                           | Run that step on its own from Checks and read its output. [product.md](product.md) has a troubleshooting list for each step.                                |
| "make ... is not a target of this checkout's Makefile" | The checkout is on a branch that does not have that command.                                            | Switch the checkout to `main` in a terminal, or ask whoever works on that branch.                                                                           |
| A tool is missing                                      | A command needs a program that is not installed (for example uv, pnpm or colima).                       | Run Which tools are installed. [local-dev.md](local-dev.md) says how to install each one.                                                                   |
| Docker did not stop in time                            | Each step of a stop has a time limit, and `colima stop` overran its 2 minutes.                          | The failure offers Force-stop Docker, which asks first: a forced stop gives the databases no time to close their files.                                     |
| The branch chip at the top is red                      | Another session is working in this checkout, for example Claude's build agent running tests.            | Wait for it to finish, or see what it is in Processes. Stop everything, Start fresh and Restore a backup would break its work, and their questions say so.  |
| The window says it lost its connection                 | The app's helper stopped, or the Mac went to sleep.                                                     | Wait a few seconds; it reconnects by itself. If it does not, quit the app and open it again.                                                                |
| The app asks to use your Desktop folder, or says it is waiting for macOS | Your checkout is in a folder macOS keeps private (Desktop, Documents or Downloads). macOS asks once, and again after each new build of the app. | Click Allow. If you clicked Don't Allow: System Settings, Privacy & Security, Files & Folders, turn on the folder under ComplianceWatch Control, then press Try again. |
| Closing the window asks what to do                     | Something is still running, and closing the window would stop it.                                       | Keep Running in Background closes the window and lets it finish; click ComplianceWatch Control in the Dock to bring the window back. Quit stops it now. Quit at the bottom of the sidebar, or ⌘Q, always quits. |
| The window says "Open this window from the app"        | The page was reloaded without the key the app gives it.                                                 | Open the app again (or run `make control-panel` again).                                                                                                     |
| The window is empty, or says it could not load         | Part of the window did not arrive from the app's helper. The window loads itself again once on its own. | Press ⌘R to load it again. If it stays empty, quit the app and open it again.                                                                               |
| The Mac feels slow                                     | Docker's virtual machine uses memory and processor time while it runs.                                  | Stop everything when you are done. Your data is kept for next time.                                                                                         |

## What this app will never do

These rules are checked where each program starts, not only when you press a button, so no
button can get around them.

- **Run anything it was not built to run.** Every button runs one of the project's own make
  commands or a plain program, never through a shell, and only commands this checkout's
  Makefile has.
- **Read the real regulator websites.** It never runs `make backfill` or `make label`, which
  read those sites, and the crawl stays off for everything it starts, whatever `.env` says.
- **Withdraw a published rule.** It never runs the product check's rollback step
  (`--destructive`). Only CI runs that, on a database made for the run.
- **Fill the product with extra options.** Filling the product with sample data runs with no
  options, and only while the product answers.
- **Stop what is not this project's.** It never stops itself, another control window, what
  Claude Code or an editor runs, or anything outside this checkout, such as your terminal
  itself. Stopping a process names every process it reaches before it happens, and signals
  only those.
- **Touch git.** It never fetches, commits, pushes or switches branches, and it writes nothing
  in the checkout before you start something.
- **Change your settings.** It never changes a flag, `.env` or the project's files itself. The
  commands it runs write what they always write, such as test reports, and
  `make contracts-check` regenerates the generated clients before it compares them.
- **Delete data without asking.** Reset and Restore ask first, say what they delete and offer a
  backup.
- **Test against your own data.** The web app's browser tests run on a separate test copy with
  throwaway data, never on your own services, web app or database: Click through the web app
  starts the copy and stops it, and `make web-e2e` on its own is never run from here.
- **Run two changes at once.** One step runs at a time, and Cancel stops the running one with
  everything it started.

## Words

| Word                | Meaning                                                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Analyst             | A person on the regulatory team who checks a rule against the regulator's text before it is published.                               |
| Backup              | A copy of the database in a file in `var/backups`, made with Back up the database. Restore a backup puts it back.                    |
| Branch              | A line of work in the code. `main` is the shared, reviewed version; other branches hold work in progress.                            |
| CA firm             | A firm of chartered accountants that looks after the compliance of several client businesses.                                        |
| Change card         | The message that tells a business about a rule change that applies to it.                                                            |
| Check               | An automatic test of the code or the data. CI runs the same checks on every change. Also called a gate.                              |
| Checkout            | The folder with the project's code on this Mac. This app runs its commands there.                                                    |
| CI                  | Continuous integration: GitHub runs the checks on every change before it is merged.                                                  |
| Citation            | The exact regulator clause a rule is based on, quoted word for word.                                                                 |
| Colima              | The free tool this app uses to run Docker on a Mac.                                                                                  |
| Consumer group      | A named reader of the message queue. It remembers how far it has read each topic.                                                    |
| Container           | One program running inside Docker, such as the Postgres database.                                                                    |
| Crawl               | Reading the regulators' websites on a schedule. Always off for everything this app starts.                                           |
| Database            | Where the data is kept. Here it is Postgres, running in Docker.                                                                      |
| Dead letters        | Messages that could not be handled. They wait in a topic whose name ends in `.dlq` until someone looks at them.                      |
| Docker              | Software that runs programs in containers. The databases and the queue run in it.                                                    |
| Eval                | A measured test of the AI parts against a golden set of right answers.                                                               |
| Fan-out             | Deciding a newly published rule for every business at once, in batches.                                                              |
| Flag                | A switch or setting for a feature, usually set in `.env`. This app shows flags but never changes them.                               |
| GSTIN               | A business's GST registration number.                                                                                                |
| Hold                | A pause an admin puts on every fan-out until it is released.                                                                         |
| Lag                 | How many messages a consumer group still has to read.                                                                                |
| LLM gateway         | The one service that talks to AI models (large language models). By default it uses a fake model.                                    |
| make                | The tool that runs the project's named commands, such as `make dev` or `make check`. Most buttons here run one or more of them.      |
| Migration           | A step that updates the database's structure to match the code.                                                                      |
| Obligation          | A dated duty for a business, such as a GST return to file by a due date.                                                             |
| Outbox relay        | A helper that passes a service's saved events on to the message queue.                                                               |
| Pid                 | The number the Mac gives each running program (its process id).                                                                      |
| Port                | A numbered door a program listens on, like 3000 for the web app.                                                                     |
| Process             | A running program.                                                                                                                   |
| Product check       | A test of the running product from end to end, one step at a time: health, the loop from rule to message, tenant isolation and more. |
| Queue               | The message queue, Redpanda, which carries events between services in topics. It speaks Kafka's language.                            |
| Rule version        | One version of a rule. It starts as a draft, analysts review it, and then it is published.                                           |
| Seed                | Loading starter data: the thirteen standing GST rules as drafts, or the made-up demo businesses.                                     |
| Service             | One part of ComplianceWatch with one job, such as obligations or notifications.                                                      |
| Sink                | A file, `var/product/sink.jsonl`, where the full product writes its messages instead of sending them.                                |
| Synthetic           | Made up for tests and demos. Synthetic businesses and people are not real.                                                           |
| Temporal            | Runs long jobs as steps and tries a failed step again.                                                                               |
| Tenant              | One customer account: a business or a CA firm. A tenant never sees another tenant's data.                                            |
| Test copy           | A separate, temporary copy of the ten services with throwaway data, for the web app's browser tests. It stops when the check ends.   |
| Topic               | A named stream of events in the queue, such as `obligation.created`.                                                                 |
| UI-only stack       | The ten services and the web app, for clicking through screens. It has no worker.                                                    |
| Uncommitted changes | Edits in the checkout that are not yet saved in git. This app shows how many there are.                                              |
| Volume              | Docker's storage on this Mac, where the databases keep their data between runs.                                                      |
| Worker              | A program that does background work: it reads events, sends reminders and runs long jobs.                                            |

## For developers

### How it fits together

- `tools/control-panel/panel_core.py` holds the logic and the safety rules, with no window: the
  probes, the parsers, the plan behind every action, the checks every program passes where it
  starts, the process rules and the runner. `tools/control-panel/tests` tests it without a
  display, Docker or a network.
- `tools/control-panel/panel_server.py` serves the window and a JSON API with server-sent
  events, on `127.0.0.1` and a random free port, with a random token per launch. Its contract is
  `tools/control-panel/API.md`; `--demo` serves made-up data from a fake core (no program runs,
  nothing is signalled), and `--open` opens the default browser.
- `tools/control-panel/ui/` is the window: plain HTML, CSS and JavaScript modules, no build step
  and nothing from the network. `guide.js` holds the Guide's words; `model.js` turns the API's
  answers into what the views read; `api.js` holds the token, the requests and the event
  stream.
- `tools/control-panel/shell/` is the Mac app around it; `install-app.sh` builds it.
- `CW_CONTROL_PANEL_REPO=<path>` points the helper at another checkout.

### Security

No token ever travels in a URL. The app opens the window with a single-use launch code in the
address's fragment (`http://127.0.0.1:<port>/#launch=...`), which it asks the helper for with
the token. The window clears the address bar at once, swaps the code for the token with a
`POST` that the helper accepts only from its own page (the `Origin` and `Host` are checked), and
keeps the token in memory only (never in storage). A code lasts 30 seconds and works once, so a
copied or reloaded address is worth nothing. The window sends the token as `X-Panel-Token` on
every request, the event stream included (read with `fetch`). The helper also checks that `Host`
is `127.0.0.1:<port>` and that an `Origin`, when present, is the window's own, so another
website or a DNS rebinding cannot reach it. A reload without the app says "Open this window
from the app". The window's content security policy allows nothing but its own files and its
own helper.

### How it runs things

- **No shell.** Every step is an argument list (`make product WEB_PORT=3400`,
  `colima start ...`), and links and files open through macOS's `open` the same way. A
  Finder-launched app gets a bare PATH, so `/opt/homebrew/bin` and `/usr/local/bin` go first and
  `~/.local/bin` last.
- **Checked where it starts.** Every program is checked where it starts, not only when its
  button is pressed: no shell, nothing that reads the regulator sites, no `--destructive`, the
  crawl off (`CW_PIPELINE_CRAWL_ENABLED=false` for everything it starts), make without options
  or shell characters, a destructive target only in a step that asked first, and only the
  checkout's make targets. A step the app performs itself declares every program it runs, and
  the runner refuses any other. None of `ARGS`, `MAKEFLAGS`, `MFLAGS`, `GNUMAKEFLAGS`,
  `MAKELEVEL`, `MAKEOVERRIDES`, `SERVICE`, `PROC`, `FOLLOW`, `FILE`, `WEB` or
  `E2E_ALLOW_POSTGRES` is passed on from the environment the app was opened in.
- **One step at a time.** Reads (logs, the container list, the crawl report) may run beside a
  step.
- **Cancel.** Each step runs in a session of its own, so Cancel ends the running step's whole
  process group: SIGTERM, then, five seconds later, SIGKILL to whatever of the group is left.
  Cancelling `make product` or `make web-stack` therefore also stops what they had started. The
  browser tests get SIGINT first (Playwright stops the web app it started on SIGINT, and leaves
  it running on SIGTERM), SIGTERM 15 seconds later and SIGKILL five after that. A clean-up step
  (the web check's "Stop the test copy") runs after a failure or a Cancel too, and Cancel does
  not stop it; the Cancel question names it.
- **The web check.** Click through the web app runs `make web-e2e` on a test copy, never on the
  services Start everything runs (8001 to 8010, whose data is the shared development database)
  or on `next dev`. Every make step gets `STORE=memory WEB_STACK_DIR=var/web-stack-check
  SERVICE_PORT_BASE=9400` (make hands command-line variables to its recipes, where they win over
  `.env`), and `make web-e2e` gets `WEB_PORT=3410`. Ports 9401 to 9410 and 3410 clash with
  nothing else of the project's: the product (8000, 8080, 8081, 3400, 3401) and a second clone
  (9201 to 9210, 3200; 3217 for a build agent's). The seed and the tests get every `CW_WEB_*_URL` on the test copy (they win
  over `apps/web/.env.local`, which names your services) and `CW_WEB_SEED_STATE_PATH` in
  `var/web-stack-check`, never `var/seed/last.json`. The test copy's services get no database,
  Temporal, Kafka or Redis of yours (an address nothing listens on), keep uploads in memory,
  send no telemetry, message or paid model call, and call each other on the test ports (as
  `make web-stack` itself now arranges for every base; the app keeps its own settings for an
  older Makefile). The tests drive Playwright's own Chromium when the headless shell of the
  revision `playwright-core/browsers.json` names is downloaded, else Google Chrome
  (`CW_E2E_BROWSER_CHANNEL=chrome`, read by `apps/web/playwright.config.ts`); the app finds out
  from those files, without starting a browser or using the network. The web
  app is built into `apps/web/.next/web-check` (`WEB_DIST_DIR`): Next.js 16 builds `next dev`
  into `.next/dev`, which no build touches, so building beside a running `next dev` is safe, but
  `next build` first empties its own folder (all but `cache`, `dev`, `lock` and `trace`), and a
  build into `.next` would delete `make product`'s `.next/product` under its running dev server.
  Before it starts, the check refuses while another web check (another control window's, whose
  test copy it leaves alone) or another browser test run works in the checkout (the runs share
  `apps/web/test-results`), or while anything answers on its ports, and it stops what an earlier
  check left: only the pids of `var/web-stack-check` that still run that service on its
  test port. At the end it stops the test copy (`make web-stack-down` with the same variables),
  and the web app the browser tests left, if any: this checkout's `next start` on 3410, started
  since they began.
- **Time limits.** Each step of a stop has one: the web app 1 minute, `make web-stack-down` and
  `make product-down` 2, the workers and relays 1, `make dev-down` 3 and `colima stop` 2. A step
  that overruns is stopped the way Cancel stops it and shows as timed out. When `colima stop`
  times out, the window offers `colima stop --force` as a question of its own; Stop everything
  never forces. A step's output stops being read two seconds after its program exits.
- **What it writes.** Nothing until you start something. Then: `var/control-panel/registry.json`
  (the process group of every step and background process it started, so it can tell them from
  another session's), the pid and log file of each worker and relay it starts in
  `var/control-panel/`, the web app's in `var/web-stack/web.pid` and `web.log`, and
  `var/control-panel/psql.command` for the database prompt. The web check writes its test
  copy's pid files, logs and seed state in `var/web-stack-check/`, its build in
  `apps/web/.next/web-check/` (and, as every `next build` does, `apps/web/next-env.d.ts`), and
  Playwright's results in `apps/web/test-results/`. All of it is git-ignored.
- **Live updates.** One poller in the helper reads the status (Docker, the containers, every
  `/health` and `/ready`, git, the processes) and pushes changes to the window over the event
  stream; the window never polls, it only sends a heartbeat every 20 seconds. rpk runs at most
  once every 30 seconds. Every program a probe runs has a hard time limit.
- **Bounded.** A window keeps one event stream, and lets go of it while it is hidden or after it
  reloads; the helper keeps at most four streams (a fifth closes the oldest) and 48 connections,
  and an idle connection lets go of its thread after 20 seconds. A run whose runner stopped
  without saying how it ended shows as "It stopped unexpectedly" two seconds later, so nothing
  shows as running when nothing runs.
- **Its lifetime.** The app holds a pipe on the helper's input: closing it (quitting) stops the
  helper, and while the app runs the helper stays up, hidden window or not. A helper nobody
  holds (`make control-panel`, the browser fallback) stops ten minutes after the last window. A
  helper told to stop exits within three seconds. Quitting the app always ends within five
  seconds: the input closes, SIGTERM two seconds later, SIGKILL a second after that; SIGTERM to
  the app does the same, even while a question is open.

### Developing the window

```bash
node tools/control-panel/ui-tests/run.mjs                      # the Playwright suite, against panel_server.py --demo
PANEL_BACKEND=mock node tools/control-panel/ui-tests/run.mjs   # against the mock, without Python
node tools/control-panel/ui-tests/run.mjs --both               # both, one after the other
.venv/bin/python tools/control-panel/panel_server.py --demo --open   # look at the window with made-up data
```

The suite uses the checkout's own Playwright and axe (`apps/web/node_modules`) and the installed
Google Chrome, headless. It runs against the real helper in `--demo` mode and sets the made-up world
each test needs (another session at work, a branch that is not main, a step that fails or times out)
through `POST /api/demo/state`. `ui-tests/mock-server.mjs` is a stand-in that speaks the same API
with the catalog's own words, for checks without Python; it is never part of the app. The suite
checks that every view renders, the palette, a run streaming and being cancelled, the questions and
their warnings, errors with their fixes, the tour, events that land while a read is on its way,
double clicks (one question, one start), tables at 1280, 1100 and 900 px, first paint and layout
shift, and axe (WCAG 2.1 AA) in light and dark. It saves light and dark screenshots of every view in
`var/screenshots/`. `prettier --check` covers the window's files like the rest of the repo.
