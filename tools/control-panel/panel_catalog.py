"""The action catalog of ComplianceWatch Control: every action the window offers, in plain words.

Two kinds of entry:

- the curated actions, written for this app (``CURATED``), each with the ``panel_core`` plan
  behind it;
- every ``##``-documented target of the checkout's Makefile, as ``make:<target>``, with words
  written for the targets the repo has today (``MAKE_TEXTS``) and a careful guess for a target
  added later (:func:`guess`).

Each entry says what it does, what happens to the computer, how long it usually takes and how
safe it is: ``safe``, ``changes-data``, ``stops-things``, ``destructive``, or ``refused`` (never
run from here, with the reason). The words are read by people who are not developers.

Nothing here runs anything: :func:`build` turns an entry and its parameters into a ``Plan`` (or a
file to open), which the server then hands to ``panel_core``'s checked runner.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import panel_core as core

type Safety = Literal["safe", "changes-data", "stops-things", "destructive", "refused"]
type Kind = Literal["step", "read", "open"]

GROUPS: Final = (
    ("everything", "Everything"),
    ("docker", "Docker and databases"),
    ("services", "Services and the web app"),
    ("product", "The product"),
    ("data", "Data"),
    ("checks", "Checks"),
    ("pipeline", "Pipeline and events"),
    ("flags", "Flags"),
    ("tools", "Tools and files"),
    ("make", "Every make target"),
)


@dataclass(frozen=True)
class Param:
    """A parameter of an action. ``source`` names where its choices come from when they are
    live: services, workers, relays, backups, check-steps, product-procs, image-procs,
    containers."""

    name: str
    label: str
    kind: Literal["choice", "boolean", "text"] = "choice"
    required: bool = True
    default: Any = None
    help: str = ""
    source: str = ""
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Spec:
    """One action of the catalog. ``migrates``: it runs make migrate (the not-main warning
    names the shared database). ``takes``: what it stops or changes for other sessions
    (``docker``, ``product``). ``rewrites``: it rewrites files in the checkout. ``needs``: what
    must be running for it to make sense (``docker``, ``product``). ``calls_model``: it asks the
    model through the gateway (the confirm names the provider). ``target``: for a curated action,
    the make target it runs; the action is left out of a checkout whose Makefile lacks it."""

    id: str
    title: str
    summary: str
    what_happens: tuple[str, ...]
    duration: str
    group: str
    safety: Safety
    kind: Kind = "step"
    button: str = "Run"
    confirm: str = ""
    params: tuple[Param, ...] = ()
    migrates: bool = False
    takes: tuple[str, ...] = ()
    rewrites: bool = False
    needs: tuple[str, ...] = ()
    url: str = ""
    source: Literal["curated", "make"] = "curated"
    target: str = ""
    refused: str = ""
    covered_by: str = ""
    timeout: float | None = None
    calls_model: bool = False

    @property
    def needs_confirm(self) -> bool:
        """Whether it runs only after a question: anything that is not safe, and anything that
        calls the model, whatever its class."""
        return self.safety in ("changes-data", "stops-things", "destructive") or self.calls_model


# ---- the curated actions -----------------------------------------------------------------------

SERVICE = Param("service", "Service", source="services", help="Which of the ten services.")
OPTIONAL_SERVICE = replace(SERVICE, required=False, help="Leave empty for every service.")
WORKER = Param("service", "Service", source="workers", help="A service that has a worker.")
RELAY = Param("service", "Service", source="relays", help="A service that has an outbox relay.")
PRODUCT_PROC = Param(
    "proc", "Process", source="product-procs", default="app", help="Which part of the product."
)
IMAGE_PROC = Param(
    "proc", "Container", source="image-procs", default="app", help="Which container."
)
CONTAINER = Param("service", "Container", source="containers", help="Which container.")
STEP = Param(
    "step",
    "Step",
    required=False,
    source="check-steps",
    help="Leave empty to run every step. The rollback step is never offered.",
)
DUMP = Param("dump", "Backup", source="backups", help="Newest first, with size and age.")
BACKUP_FIRST = Param(
    "backup_first",
    "Back up first",
    kind="boolean",
    required=False,
    default=True,
    help="Take a backup into var/backups before anything is deleted.",
)

CONTRACTS_REWRITE: Final = (
    "contracts-check regenerates the event and API clients (make contracts) before it compares "
    "them: generated files that were out of date are rewritten in this checkout and show as "
    "changed."
)

MIGRATE_NOTE: Final = (
    "It runs make migrate, which applies this checkout's database changes (migrations) to the "
    "shared development database."
)


def _c(
    id: str,
    title: str,
    summary: str,
    what: Sequence[str],
    duration: str,
    group: str,
    safety: Safety,
    **extra: Any,
) -> Spec:
    return Spec(id, title, summary, tuple(what), duration, group, safety, **extra)


CURATED: Final[tuple[Spec, ...]] = (
    # everything
    _c(
        "start-everything",
        "Start everything",
        "Starts Docker, the databases, the ten services and the web app, then opens the web app.",
        (
            "Starts Docker (Colima) if it is not running.",
            "Starts the databases and queues: Postgres, Redis, Redpanda and Temporal.",
            "Brings the database up to date (make migrate).",
            "Starts the ten services and waits until each one answers.",
            "Starts the web app and opens it in your browser.",
        ),
        "2 to 4 minutes (longer the first time)",
        "everything",
        "changes-data",
        button="Start",
        confirm="Everything starts. " + MIGRATE_NOTE,
        migrates=True,
    ),
    _c(
        "stop-everything",
        "Stop everything",
        "Stops the web app, the services, the product and Docker, to free memory.",
        (
            "Stops the web app and the ten services.",
            "Stops the product's app, worker and web app.",
            "Stops the workers and relays this app started.",
            "Stops the databases and queues. Their data stays on disk.",
            "Shuts Docker (Colima) down. If it takes longer than 2 minutes, you can force it.",
        ),
        "about 1 minute",
        "everything",
        "stops-things",
        button="Stop",
        confirm="Everything this checkout runs stops, for every session that uses it.",
        takes=("docker", "product"),
    ),
    # docker and databases
    _c(
        "docker-start",
        "Start Docker",
        "Starts Docker (Colima), the program that runs the databases.",
        ("Starts Colima with 4 CPUs and 8 GB of memory, if it is not running already.",),
        "about 1 minute",
        "docker",
        "safe",
        button="Start",
    ),
    _c(
        "docker-stop",
        "Stop Docker",
        "Shuts Docker (Colima) down to free memory. Every container stops with it.",
        (
            "Postgres, Redis, Redpanda and Temporal stop, for every session using them.",
            "The data stays in Docker's volumes; it is there again at the next start.",
        ),
        "under 1 minute",
        "docker",
        "stops-things",
        button="Stop",
        confirm="Docker stops, and every container with it.",
        takes=("docker",),
    ),
    _c(
        "force-stop-docker",
        "Force-stop Docker",
        "Stops Colima at once when a normal stop hangs. Only use it after Stop Docker timed out.",
        (
            "Colima's virtual machine stops immediately, without a clean shutdown.",
            "The databases get no time to close their files. Postgres repairs itself at the next "
            "start; anything being written at that moment is lost.",
        ),
        "under 1 minute",
        "docker",
        "destructive",
        button="Force stop",
        confirm="Colima stops at once, without letting the databases shut down cleanly.",
        takes=("docker",),
    ),
    _c(
        "databases-start",
        "Start the databases",
        "Starts Postgres, Redis, Redpanda and Temporal in Docker and waits until they are healthy.",
        (
            "Runs make dev: creates .env the first time, then starts the containers.",
            "Waits until every container reports healthy.",
        ),
        "about 1 minute",
        "docker",
        "safe",
        button="Start",
        needs=("docker",),
    ),
    _c(
        "databases-stop",
        "Stop the databases",
        "Stops the database and queue containers. Their data stays on disk.",
        ("Runs make dev-down: every container of the dev stack stops; the volumes stay.",),
        "under 1 minute",
        "docker",
        "stops-things",
        button="Stop",
        confirm="The databases and queues stop, for every session using them.",
        takes=("docker",),
        needs=("docker",),
    ),
    _c(
        "dev-observability",
        "Start the monitoring tools",
        "Adds Langfuse, the OpenTelemetry collector, Prometheus, Tempo and Grafana to the stack.",
        ("Runs make dev-observability: starts the monitoring containers beside the databases.",),
        "1 to 2 minutes",
        "docker",
        "safe",
        button="Start",
        needs=("docker",),
    ),
    _c(
        "dev-llm",
        "Start the fake AI model",
        "Builds and starts the LLM gateway with the fake provider, so nothing calls a paid model.",
        ("Runs make dev-llm: builds the gateway image and starts its container.",),
        "1 to 3 minutes",
        "docker",
        "safe",
        button="Start",
        needs=("docker",),
    ),
    _c(
        "dev-flags",
        "Start Unleash (feature flags)",
        "Starts Unleash, the feature-flag server, for when flags come from Unleash.",
        ("Runs make dev-flags: starts Unleash and creates its database the first time.",),
        "about 1 minute",
        "docker",
        "safe",
        button="Start",
        needs=("docker",),
    ),
    _c(
        "dev-ps",
        "Show the containers",
        "Lists every container of the dev stack with its state and health.",
        ("Runs make dev-ps and shows what it prints. Nothing changes.",),
        "a few seconds",
        "docker",
        "safe",
        kind="read",
        button="Show",
        needs=("docker",),
    ),
    _c(
        "container-logs",
        "A container's log",
        "Shows the last 200 lines of one container's log.",
        ("Reads the log with docker compose logs. Nothing changes.",),
        "a few seconds",
        "docker",
        "safe",
        kind="read",
        button="Show",
        params=(CONTAINER,),
        needs=("docker",),
    ),
    # services and the web app
    _c(
        "ui-start",
        "Start the services",
        "Starts the ten services on the shared Postgres, so the web app has an API to talk to.",
        (
            "Runs make web-stack STORE=postgres: each service starts in the background.",
            "Waits until every service answers its health check.",
        ),
        "about 1 minute",
        "services",
        "safe",
        button="Start",
        needs=("docker",),
    ),
    _c(
        "ui-stop",
        "Stop the services",
        "Stops the ten services this checkout started (and the web app, if the stack started it).",
        ("Runs make web-stack-down: stops only the processes its pid files name.",),
        "a few seconds",
        "services",
        "stops-things",
        button="Stop",
        confirm="The ten services stop.",
    ),
    _c(
        "ui-restart",
        "Restart the services",
        "Stops and starts the ten services again, for example after you changed their code.",
        (
            "Stops the services (make web-stack-down).",
            "Starts them again on Postgres and waits until each one answers.",
        ),
        "about 1 minute",
        "services",
        "stops-things",
        button="Restart",
        confirm="The ten services stop, then start again.",
        needs=("docker",),
    ),
    _c(
        "ui-wait",
        "Wait for the services",
        "Waits until every service answers its health check.",
        ("Runs make web-stack-wait. Nothing changes.",),
        "up to 1 minute",
        "services",
        "safe",
        button="Wait",
    ),
    _c(
        "web-start",
        "Start the web app",
        "Starts the ComplianceWatch web app on port 3000.",
        ("Starts next dev in the background and waits until the page answers.",),
        "20 to 60 seconds",
        "services",
        "safe",
        button="Start",
    ),
    _c(
        "web-stop",
        "Stop the web app",
        "Stops the web app on port 3000.",
        ("Stops exactly the web app processes the confirm names; nothing else.",),
        "a few seconds",
        "services",
        "stops-things",
        button="Stop",
        confirm="The web app stops.",
    ),
    _c(
        "worker-start",
        "Start a worker",
        "Starts one service's worker: its event consumers, outbox relay and periodic jobs.",
        (
            "Runs make worker SERVICE=<service> in the background, with crawling turned off.",
            "Its log goes to var/control-panel.",
        ),
        "a few seconds",
        "services",
        "safe",
        button="Start",
        params=(WORKER,),
        needs=("docker",),
    ),
    _c(
        "worker-stop",
        "Stop a worker",
        "Stops a worker this app started.",
        ("Sends it a stop signal, and a forced stop if it is still running after 5 seconds.",),
        "a few seconds",
        "services",
        "stops-things",
        button="Stop",
        params=(WORKER,),
        confirm="The worker stops.",
    ),
    _c(
        "relay-start",
        "Start an outbox relay",
        "Starts one service's outbox relay, which publishes its saved events to Redpanda.",
        ("Runs make relay SERVICE=<service> in the background.",),
        "a few seconds",
        "services",
        "safe",
        button="Start",
        params=(RELAY,),
        needs=("docker",),
    ),
    _c(
        "relay-stop",
        "Stop an outbox relay",
        "Stops a relay this app started.",
        ("Sends it a stop signal, and a forced stop if it is still running after 5 seconds.",),
        "a few seconds",
        "services",
        "stops-things",
        button="Stop",
        params=(RELAY,),
        confirm="The relay stops.",
    ),
    # the product
    _c(
        "product-start",
        "Start the product",
        "Starts the whole product: the databases, the app, the worker and its web app on port "
        "3400.",
        (
            "Starts Docker and the databases if they are not running.",
            "Brings the database up to date (make migrate) and loads the rulebook's seed calendar.",
            "Starts the product's app, its worker and its web app.",
        ),
        "2 to 5 minutes",
        "product",
        "changes-data",
        button="Start",
        confirm="The product starts. " + MIGRATE_NOTE,
        migrates=True,
    ),
    _c(
        "product-stop",
        "Stop the product",
        "Stops the product's app, worker and web app. The databases keep running.",
        ("Runs make product-down: stops only the processes the product recorded.",),
        "a few seconds",
        "product",
        "stops-things",
        button="Stop",
        confirm="The product's app, worker and web app stop.",
        takes=("product",),
    ),
    _c(
        "product-wait",
        "Wait for the product",
        "Waits until the product's app, worker and web app all answer.",
        ("Runs make product-wait. Nothing changes.",),
        "up to 2 minutes",
        "product",
        "safe",
        button="Wait",
    ),
    _c(
        "product-role",
        "Refresh the product's database role",
        "Creates or refreshes the database login the product uses under row-level security.",
        ("Runs make product-role on the running Postgres.",),
        "a few seconds",
        "product",
        "changes-data",
        confirm="The product's database role is created or refreshed.",
        needs=("docker",),
    ),
    _c(
        "product-seed",
        "Fill the product with sample data",
        "Adds made-up businesses, a sample rule publication and first decisions to the running "
        "product.",
        ("Runs make product-seed (cw-product seed) against the running product.",),
        "about 1 minute",
        "product",
        "changes-data",
        button="Fill",
        confirm="Sample businesses and a sample publication are added to the product.",
        needs=("product",),
    ),
    _c(
        "product-check",
        "Check the product works",
        "Proves the running product works, step by step: sign-up, rules, decisions, obligations, "
        "notifications.",
        (
            "Runs make product-check (cw-product check). Each step says what it proved.",
            "It adds made-up test records to the product as it goes. It never runs the rollback "
            "step.",
        ),
        "2 to 5 minutes",
        "product",
        "changes-data",
        confirm="The check adds made-up test records to the running product.",
        params=(STEP,),
        needs=("product",),
    ),
    _c(
        "product-e2e",
        "Click through the product in a browser",
        "Builds the web app and lets a robot browser click through the product's main journeys.",
        (
            "Runs make product-e2e: builds the web app, then Playwright tests against the product.",
            "The robot signs up and clicks like a person would, adding test records.",
        ),
        "5 to 10 minutes",
        "product",
        "changes-data",
        confirm="A robot browser clicks through the product, adding test records.",
        needs=("product",),
    ),
    _c(
        "product-logs",
        "The product's log",
        "Shows the end of one product process's log.",
        ("Runs make product-logs PROC=<process> FOLLOW=0. Nothing changes.",),
        "a few seconds",
        "product",
        "safe",
        kind="read",
        button="Show",
        params=(PRODUCT_PROC,),
    ),
    _c(
        "mvp-image",
        "Build the product's image",
        "Builds the product's Docker image, the one a server would run.",
        ("Runs make mvp-image (docker build). Nothing running changes.",),
        "3 to 10 minutes",
        "product",
        "safe",
        button="Build",
        needs=("docker",),
    ),
    _c(
        "product-image",
        "Start the product from its image",
        "Runs the product from its Docker image instead of from the code, like a server would.",
        (
            "Builds the image unless it exists, then starts the release, app and worker "
            "containers.",
            "The release step brings the database up to date (migrations).",
        ),
        "3 to 10 minutes",
        "product",
        "changes-data",
        button="Start",
        confirm="The product's containers start. Their release step migrates the shared "
        "development database.",
        migrates=True,
        needs=("docker",),
    ),
    _c(
        "product-image-down",
        "Stop the product's image",
        "Removes the image product's containers. The databases keep running.",
        ("Runs make product-image-down.",),
        "a few seconds",
        "product",
        "stops-things",
        button="Stop",
        confirm="The image product's containers are removed.",
        takes=("product",),
        needs=("docker",),
    ),
    _c(
        "product-image-logs",
        "The image product's log",
        "Shows the end of one image container's log.",
        ("Runs make product-image-logs PROC=<container> FOLLOW=0. Nothing changes.",),
        "a few seconds",
        "product",
        "safe",
        kind="read",
        button="Show",
        params=(IMAGE_PROC,),
        needs=("docker",),
    ),
    # data
    _c(
        "load-demo-data",
        "Load demo data",
        "Fills the services with a demo business and the rulebook's sample rules, so the web app "
        "has something to show.",
        (
            "Loads the rulebook's seed calendar as draft rules (make seed SERVICE=rulebook).",
            "Adds the demo tenant and a recorded notification to the services (make web-seed).",
        ),
        "about 1 minute",
        "data",
        "changes-data",
        button="Load",
        confirm="Demo records are added to the shared development database and the services.",
        needs=("docker",),
    ),
    _c(
        "demo",
        "Run the demo story",
        "Plays the demo tenant end to end in one process: consent, profile, rules, obligations "
        "and a reminder.",
        ("Runs make demo. It uses no database and changes nothing.",),
        "under 1 minute",
        "data",
        "safe",
        button="Run",
    ),
    _c(
        "migrate",
        "Update the database (migrate)",
        "Brings the database tables up to date with this checkout's code.",
        (
            "Runs make migrate for every service, or for the one you pick.",
            "Changes the shared development database's tables to this branch's version.",
        ),
        "under 1 minute",
        "data",
        "changes-data",
        confirm=MIGRATE_NOTE,
        params=(OPTIONAL_SERVICE,),
        migrates=True,
        needs=("docker",),
    ),
    _c(
        "migrations-check",
        "Check the migration files",
        "Checks the database change files: one head per service, names, downgrades.",
        ("Runs make migrations-check. It reads files only.",),
        "under 1 minute",
        "data",
        "safe",
        button="Check",
    ),
    _c(
        "migrations-catalog",
        "Check row-level security",
        "Checks that every tenant table in the database has row-level security switched on.",
        ("Runs make migrations-catalog against the running database. It only reads.",),
        "under 1 minute",
        "data",
        "safe",
        button="Check",
        needs=("docker",),
    ),
    _c(
        "data-quality",
        "Check the rulebook's data",
        "Runs the rulebook's data-quality checks on the local database.",
        ("Runs make data-quality. It only reads.",),
        "under 1 minute",
        "data",
        "safe",
        button="Check",
        needs=("docker",),
    ),
    _c(
        "seed-check",
        "Check the seed calendar",
        "Checks the rulebook's seed calendar without loading it.",
        ("Runs make seed SERVICE=rulebook ARGS=--check. It only reads.",),
        "under 1 minute",
        "data",
        "safe",
        button="Check",
    ),
    _c(
        "backup",
        "Back up the database",
        "Saves a copy of the development database into var/backups.",
        ("Runs make dev-backup (pg_dump). The database itself does not change.",),
        "under 1 minute",
        "data",
        "safe",
        button="Back up",
        needs=("docker",),
    ),
    _c(
        "restore",
        "Restore a backup",
        "Replaces the development database with a backup you pick.",
        (
            "Checks the backup can be read first.",
            "Drops the database (ending every open connection) and creates it again from the "
            "backup.",
            "Everything written since that backup was taken is lost.",
        ),
        "1 to 3 minutes",
        "data",
        "destructive",
        button="Restore",
        confirm="The development database is replaced by the backup. Everything written since "
        "it was taken is lost.",
        params=(DUMP, BACKUP_FIRST),
        takes=("docker",),
        needs=("docker",),
    ),
    _c(
        "reset",
        "Start fresh (reset the database)",
        "Deletes all local data and builds an empty database again, with the sample rules.",
        (
            "Takes a backup first, unless you untick it.",
            "Stops the services, the product and this app's workers.",
            "Deletes the containers and every data volume (make dev-reset).",
            "Starts the databases again, migrates them and loads the seed calendar.",
        ),
        "3 to 5 minutes",
        "data",
        "destructive",
        button="Reset",
        confirm="All local data is deleted: the database, the queues and the monitoring data.",
        params=(BACKUP_FIRST,),
        migrates=True,
        takes=("docker", "product"),
        needs=("docker",),
    ),
    _c(
        "psql",
        "Open the database prompt",
        "Opens Terminal with a psql prompt on the development database.",
        ("Opens Terminal and runs make dev-psql there. What you type there is up to you.",),
        "a few seconds",
        "data",
        "safe",
        kind="open",
        button="Open",
        needs=("docker",),
    ),
    _c(
        "open-doc",
        "Open a document",
        "Opens one of the project's guides or folders.",
        ("Opens it in its usual app. Nothing changes.",),
        "instant",
        "tools",
        "safe",
        kind="open",
        button="Open",
        params=(Param("doc", "Document", source="docs"),),
    ),
    _c(
        "open-backups-folder",
        "Open the backups folder",
        "Shows var/backups in Finder.",
        ("Opens the folder. Nothing changes.",),
        "instant",
        "data",
        "safe",
        kind="open",
        button="Open",
    ),
    # checks
    _c(
        "gates-in-order",
        "Run all checks (as CI does)",
        "Runs every check CI runs, one after another, and shows which passed.",
        (
            "Runs the checks of make check one by one, then the evals, the contract checks, "
            "the ops checks, the integration tests and the security scans.",
            "A failed check does not stop the next one; the summary lists each result.",
            CONTRACTS_REWRITE,
            "The other checks change no tracked file. They write git-ignored caches and reports "
            "(.mypy_cache, .ruff_cache, .pytest_cache, .turbo, coverage, evals/reports, "
            "semgrep.sarif).",
        ),
        "20 to 40 minutes",
        "checks",
        "changes-data",
        button="Run all",
        confirm=CONTRACTS_REWRITE,
        rewrites=True,
    ),
    # pipeline
    _c(
        "crawl-report",
        "Crawl report",
        "Shows crawl runs, failures, gaps and detection delays per regulator source.",
        ("Runs make crawl-report. It only reads; nothing is crawled.",),
        "under 1 minute",
        "pipeline",
        "safe",
        kind="read",
        button="Show",
        needs=("docker",),
    ),
    _c(
        "extract-backlog-count",
        "Count documents waiting for extraction",
        "Counts, per source, the classified documents still waiting for their rule extraction.",
        (
            "Runs make extract-backlog ARGS=--dry-run. It only reads; nothing is extracted.",
            "Shows how many documents wait per source, and whether the extraction switch is on.",
        ),
        "under 1 minute",
        "pipeline",
        "safe",
        kind="read",
        button="Count",
        needs=("docker",),
        target="extract-backlog",
    ),
    _c(
        "extract-backlog",
        "Extract the documents waiting",
        "Starts the rule extraction for the documents the pipeline classified while the "
        "extraction was off.",
        (
            "Starts extraction for documents already classified (make extract-backlog); the "
            "worker does it in the background.",
            "Each document asks the model through the gateway: the free fake model on this Mac, "
            "a paid model if one is configured.",
            "It runs only while the worker's extraction switch (CW_PIPELINE_EXTRACTION_ENABLED) "
            "is on; with it off, nothing is extracted.",
            "At most 1,000 documents in one run; run it again for the rest.",
        ),
        "under 1 minute to start; the worker takes longer",
        "pipeline",
        "changes-data",
        button="Extract",
        confirm="It starts the rule extraction for the documents waiting, at most 1,000, and "
        "each one is a call to the model through the gateway.",
        needs=("docker",),
        target="extract-backlog",
        calls_model=True,
    ),
    # flags
    _c(
        "flags-check",
        "Check the flag registry",
        "Checks the feature-flag registry: owners, expiry dates, safe defaults.",
        ("Runs make flags-check. It only reads.",),
        "a few seconds",
        "flags",
        "safe",
        button="Check",
    ),
    _c(
        "open-env",
        "Open the .env file",
        "Opens the checkout's .env settings file in your text editor.",
        ("Opens the file. This app never changes it.",),
        "instant",
        "flags",
        "safe",
        kind="open",
        button="Open",
    ),
    # tools
    _c(
        "doctor",
        "Which tools are installed",
        "Lists the tools the project needs and whether each one is installed.",
        ("Runs make doctor. Nothing changes.",),
        "a few seconds",
        "tools",
        "safe",
        kind="read",
        button="Check",
    ),
    _c(
        "open-logs-folder",
        "Open the logs folder",
        "Shows var/web-stack, where the services and the web app write their logs, in Finder.",
        ("Opens the folder. Nothing changes.",),
        "instant",
        "tools",
        "safe",
        kind="open",
        button="Open",
    ),
)

GATE_TEXTS: Final[Mapping[str, tuple[str, str, str]]] = {
    # target: (title, summary, duration)
    "check": ("Run make check", "Every check CI runs before the Docker tests.", "10 to 20 minutes"),
    "lint": ("Check code style", "ruff, eslint and prettier on the whole repo.", "1 to 3 minutes"),
    "typecheck": ("Check types", "mypy --strict and tsc on every package.", "2 to 5 minutes"),
    "test": ("Run the unit tests", "pytest and vitest, with the coverage gate.", "5 to 10 minutes"),
    "py-test-integration": (
        "Run the integration tests",
        "Tests against real Postgres, Redpanda and Temporal containers.",
        "5 to 15 minutes",
    ),
    "eval": ("Run the evals", "The eval harness, ci profile, with the fake model.", "2 to 5 min"),
    "eval-check": ("Check the golden set", "The eval golden set and world.", "under 1 minute"),
    "openapi-compat": (
        "Check API compatibility",
        "The committed API specs break no client of main.",
        "1 to 2 minutes",
    ),
    "contracts-check": (
        "Check the generated clients",
        "Regenerates the event and API clients, then checks nothing changed.",
        "1 to 3 minutes",
    ),
    "alerts-check": ("Check the alert rules", "promtool on the Prometheus alerts.", "under 1 min"),
    "flags-check": ("Check the flag registry", "The feature-flag registry.", "a few seconds"),
    "migrations-check": ("Check the migration files", "Static migration checks.", "under 1 min"),
    "sast": ("Security scan (code)", "Semgrep on the code; needs the network.", "2 to 5 minutes"),
    "deps-scan": ("Security scan (dependencies)", "Trivy on the dependencies.", "2 to 5 minutes"),
    "web-screens-check": ("Check the screens list", "docs/web/screens.md is current.", "seconds"),
    "web-e2e": (
        "Click through the web app",
        "Playwright with accessibility checks; needs the services running and seeded.",
        "5 to 10 minutes",
    ),
    "ci-lint": ("Check the CI files", "actionlint and the pre-commit config.", "under 1 minute"),
}


GATE_WRITES: Final[Mapping[str, str]] = {
    "check": CONTRACTS_REWRITE + " The other gates write git-ignored caches and reports "
    "(.mypy_cache, .ruff_cache, .pytest_cache, .turbo, coverage).",
    "contracts-check": CONTRACTS_REWRITE,
    "lint": "It changes no tracked file; ruff and eslint keep git-ignored caches (.ruff_cache, "
    ".eslintcache, .turbo).",
    "typecheck": "It changes no tracked file; mypy and tsc keep git-ignored caches (.mypy_cache, "
    "*.tsbuildinfo, .turbo).",
    "test": "It changes no tracked file; it writes git-ignored coverage reports and caches "
    "(.coverage, coverage, .pytest_cache, .turbo).",
    "py-test-integration": "It starts throwaway containers in Docker and removes them after; it "
    "changes no tracked file.",
    "eval": "It writes its report into evals/reports (git-ignored); it changes no tracked file.",
    "eval-check": "It only reads.",
    "openapi-compat": "It reads the specs here and on origin/main; it changes no file.",
    "alerts-check": "It runs promtool in a container that reads the alert rules; it changes no "
    "file.",
    "flags-check": "It only reads.",
    "migrations-check": "It only reads.",
    "sast": "It writes its findings to semgrep.sarif (git-ignored) in the checkout; it changes "
    "no tracked file.",
    "deps-scan": "It reads the checkout in a container and keeps Trivy's cache in a Docker "
    "volume; it changes no file here.",
    "web-screens-check": "It only reads.",
    "web-e2e": "It builds the web app into .next and writes Playwright's reports "
    "(playwright-report, test-results); all git-ignored.",
    "ci-lint": "It only reads.",
}
"""What each CI gate writes when it runs here: nothing tracked but contracts-check's clients."""


def gate_spec(gate: core.Gate) -> Spec:
    title, summary, duration = GATE_TEXTS.get(
        gate.target, (f"Run {gate.label}", gate.note or f"make {gate.target}", "a few minutes")
    )
    rewrites = gate.target in ("check", "contracts-check")
    return Spec(
        id=f"gate:{gate.target}",
        title=title,
        summary=summary,
        what_happens=(
            f"Runs {' '.join(gate.argv)} and shows whether it passed.",
            GATE_WRITES.get(gate.target, "It should change no tracked file."),
        ),
        duration=duration,
        group="checks",
        safety="changes-data" if rewrites else "safe",
        button="Check",
        confirm=CONTRACTS_REWRITE if rewrites else "",
        rewrites=rewrites,
        needs=("docker",)
        if gate.target in ("py-test-integration", "alerts-check", "sast", "deps-scan")
        else (),
    )


# ---- every make target -------------------------------------------------------------------------


@dataclass(frozen=True)
class MakeText:
    title: str
    summary: str
    what: tuple[str, ...]
    duration: str
    safety: Safety
    kind: Kind = "step"
    group: str = "make"
    refused: str = ""
    covered_by: str = ""
    migrates: bool = False
    rewrites: bool = False
    takes: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    calls_model: bool = False


def _m(
    title: str, summary: str, what: str, duration: str, safety: Safety, **extra: Any
) -> MakeText:
    return MakeText(title, summary, (what,), duration, safety, **extra)


FOREGROUND: Final = "It runs until it is stopped, in a terminal; this app cannot show it that way."
MAKE_TEXTS: Final[Mapping[str, MakeText]] = {
    "help": _m(
        "List the make targets",
        "Prints every make target with its help.",
        "Reads the Makefile.",
        "instant",
        "safe",
        kind="read",
    ),
    "doctor": _m(
        "Which tools are installed",
        "Prints which required tools are present.",
        "Checks the PATH for each tool.",
        "a few seconds",
        "safe",
        kind="read",
        covered_by="doctor",
    ),
    "dev": _m(
        "Start the databases",
        "Starts Postgres, Redis, Redpanda and Temporal and waits for them.",
        "Starts the dev stack's containers in Docker.",
        "about 1 minute",
        "safe",
        covered_by="databases-start",
        needs=("docker",),
    ),
    "dev-observability": _m(
        "Start the monitoring tools",
        "Adds Langfuse, the collector, Prometheus, Tempo, Grafana.",
        "Starts the monitoring containers.",
        "1 to 2 minutes",
        "safe",
        covered_by="dev-observability",
        needs=("docker",),
    ),
    "dev-llm": _m(
        "Start the fake AI model",
        "Builds and starts the LLM gateway with the fake provider.",
        "Builds an image and starts a container.",
        "1 to 3 minutes",
        "safe",
        covered_by="dev-llm",
        needs=("docker",),
    ),
    "dev-down": _m(
        "Stop the databases",
        "Stops the dev stack's containers; the data stays.",
        "Every container of the dev stack stops.",
        "under 1 minute",
        "stops-things",
        covered_by="databases-stop",
        takes=("docker",),
        needs=("docker",),
    ),
    "dev-reset": _m(
        "Delete the databases",
        "Stops the stack and deletes every data volume.",
        "Deletes all local data.",
        "1 to 2 minutes",
        "refused",
        refused="It deletes all local data without a backup. Use Start fresh, which offers one.",
        covered_by="reset",
    ),
    "dev-logs": _m(
        "Follow the container logs",
        "Tails the containers' logs until stopped.",
        "Follows the logs.",
        "until stopped",
        "refused",
        refused="It follows the logs until stopped. Use Logs, or A container's log.",
        covered_by="container-logs",
    ),
    "dev-ps": _m(
        "Show the containers",
        "Container status and health.",
        "Lists the containers.",
        "a few seconds",
        "safe",
        kind="read",
        covered_by="dev-ps",
        needs=("docker",),
    ),
    "dev-psql": _m(
        "Database prompt",
        "psql into the application database.",
        "Opens a prompt.",
        "until closed",
        "refused",
        refused="It needs a terminal to type in. Use Open the database prompt, which opens one.",
        covered_by="psql",
    ),
    "dev-backup": _m(
        "Back up the database",
        "pg_dump the dev database into var/backups.",
        "Writes a backup file; the database does not change.",
        "under 1 minute",
        "safe",
        covered_by="backup",
        needs=("docker",),
    ),
    "dev-restore": _m(
        "Restore a backup",
        "Restores the dev database from a dump.",
        "Replaces the database.",
        "1 to 3 minutes",
        "refused",
        refused="It needs a backup file and replaces the database. Use Restore a backup, which "
        "checks the file and asks first.",
        covered_by="restore",
    ),
    "compose-config": _m(
        "Check docker-compose.yml",
        "Validates docker-compose.yml without Docker running.",
        "Reads the file.",
        "a few seconds",
        "safe",
        kind="read",
    ),
    "py-sync": _m(
        "Install the Python packages",
        "Syncs the Python workspace into .venv.",
        "Installs or updates the packages in .venv, which this app also runs from.",
        "1 to 3 minutes",
        "changes-data",
    ),
    "lock-check": _m(
        "Check uv.lock",
        "Fails if uv.lock is out of date with the pyproject files.",
        "Reads the lock file.",
        "a few seconds",
        "safe",
    ),
    "py-lint": _m(
        "Check Python style",
        "ruff check and ruff format --check.",
        "Reads the code.",
        "under 1 minute",
        "safe",
    ),
    "py-format": _m(
        "Format the Python code",
        "ruff format and ruff check --fix.",
        "Rewrites Python files in the checkout.",
        "under 1 minute",
        "changes-data",
        rewrites=True,
    ),
    "py-typecheck": _m(
        "Check Python types",
        "mypy --strict per package.",
        "Reads the code.",
        "2 to 4 minutes",
        "safe",
    ),
    "py-test": _m(
        "Run the Python unit tests",
        "pytest with the coverage gate; no Docker needed.",
        "Runs the tests.",
        "3 to 8 minutes",
        "safe",
    ),
    "py-test-integration": _m(
        "Run the integration tests",
        "Tests against real containers (testcontainers).",
        "Starts temporary containers, runs the tests, removes them.",
        "5 to 15 minutes",
        "safe",
        covered_by="gate:py-test-integration",
        needs=("docker",),
    ),
    "importlint": _m(
        "Check the import rules",
        "No cross-service imports; the domain imports no I/O.",
        "Reads the code.",
        "under 1 minute",
        "safe",
    ),
    "ts-install": _m(
        "Install the JavaScript packages",
        "pnpm install --frozen-lockfile.",
        "Installs node_modules.",
        "1 to 3 minutes",
        "changes-data",
    ),
    "ts-lint": _m(
        "Check JavaScript style",
        "eslint per package and the prettier check.",
        "Reads the code.",
        "1 to 2 minutes",
        "safe",
    ),
    "ts-format": _m(
        "Format the JavaScript code",
        "prettier --write.",
        "Rewrites files in the checkout.",
        "under 1 minute",
        "changes-data",
        rewrites=True,
    ),
    "ts-typecheck": _m(
        "Check TypeScript types",
        "tsc --noEmit per package.",
        "Reads the code.",
        "1 to 2 minutes",
        "safe",
    ),
    "ts-test": _m(
        "Run the JavaScript tests",
        "vitest with coverage per package.",
        "Runs the tests.",
        "2 to 5 minutes",
        "safe",
    ),
    "ts-build": _m(
        "Build the web app",
        "next build and the TypeScript builds.",
        "Writes build output (ignored by git).",
        "2 to 5 minutes",
        "safe",
    ),
    "ts-dev": _m(
        "Web and WhatsApp dev servers",
        "next dev and the WhatsApp bot with reload.",
        "Runs two dev servers.",
        "until stopped",
        "refused",
        refused=FOREGROUND + " Use Start the web app.",
        covered_by="web-start",
    ),
    "install": _m(
        "Install everything",
        "Installs both toolchains (Python and JavaScript).",
        "Installs .venv and node_modules.",
        "2 to 5 minutes",
        "changes-data",
    ),
    "lint": _m(
        "Check code style",
        "Lint both sides (CI step 1).",
        "Reads the code.",
        "1 to 3 minutes",
        "safe",
        covered_by="gate:lint",
    ),
    "format": _m(
        "Format all code",
        "Auto-formats both sides.",
        "Rewrites files in the checkout.",
        "1 to 2 minutes",
        "changes-data",
        rewrites=True,
    ),
    "typecheck": _m(
        "Check types",
        "mypy --strict and tsc --strict.",
        "Reads the code.",
        "2 to 5 minutes",
        "safe",
        covered_by="gate:typecheck",
    ),
    "test": _m(
        "Run the unit tests",
        "Unit and contract tests on both sides.",
        "Runs the tests.",
        "5 to 10 minutes",
        "safe",
        covered_by="gate:test",
    ),
    "check": _m(
        "Run make check",
        "Everything CI runs before the integration tests.",
        "Runs every gate of make check; contracts-check among them may rewrite generated files.",
        "10 to 20 minutes",
        "changes-data",
        rewrites=True,
        covered_by="gate:check",
    ),
    "runbooks-check": _m(
        "Check the runbooks",
        "Every alert links an existing runbook.",
        "Reads files.",
        "a few seconds",
        "safe",
    ),
    "eval": _m(
        "Run the evals",
        "The eval harness against the golden set.",
        "Runs the harness and writes a report.",
        "2 to 5 minutes",
        "safe",
        covered_by="gate:eval",
    ),
    "eval-check": _m(
        "Check the golden set",
        "The KAG golden set and world are well formed.",
        "Reads files.",
        "under 1 minute",
        "safe",
        covered_by="gate:eval-check",
    ),
    "demo": _m(
        "Run the demo story",
        "The demo tenant end to end in one process.",
        "Runs in memory; nothing is stored.",
        "under 1 minute",
        "safe",
        covered_by="demo",
    ),
    "label": _m(
        "Labelling tool",
        "Builds and checks the extraction golden set.",
        "Its index step reads the live regulator sites.",
        "varies",
        "refused",
        refused="Its index step contacts the live regulator websites, which this app never does.",
    ),
    "migrate": _m(
        "Update the database (migrate)",
        "alembic upgrade head for every service.",
        "Changes the shared development database's tables.",
        "under 1 minute",
        "changes-data",
        covered_by="migrate",
        migrates=True,
        needs=("docker",),
    ),
    "run": _m(
        "Run one service",
        "Runs one service with reload.",
        "Runs a server.",
        "until stopped",
        "refused",
        refused=FOREGROUND + " Use Start the services.",
        covered_by="ui-start",
    ),
    "seed": _m(
        "Load a seed",
        "Loads the rulebook seed calendar as draft rules.",
        "Writes draft rules into the database.",
        "under 1 minute",
        "refused",
        refused="It needs a service name. Use Load demo data, or Check the seed calendar.",
        covered_by="load-demo-data",
    ),
    "backfill": _m(
        "Backfill a regulator source",
        "Fetches a regulator source's history into var/raw.",
        "Downloads from a regulator's website.",
        "varies",
        "refused",
        refused="It downloads from the live regulator websites, which this app never does.",
    ),
    "crawl-report": _m(
        "Crawl report",
        "Crawl runs, failures, gaps and delays per source.",
        "Reads the store.",
        "under 1 minute",
        "safe",
        kind="read",
        covered_by="crawl-report",
        needs=("docker",),
    ),
    "worker": _m(
        "Run a worker",
        "Runs a service's worker in the foreground.",
        "Runs a process.",
        "until stopped",
        "refused",
        refused=FOREGROUND + " Use Start a worker.",
        covered_by="worker-start",
    ),
    "relay": _m(
        "Run an outbox relay",
        "Runs one service's relay in the foreground.",
        "Runs a process.",
        "until stopped",
        "refused",
        refused=FOREGROUND + " Use Start an outbox relay.",
        covered_by="relay-start",
    ),
    "openapi": _m(
        "Export a service's API spec",
        "Writes packages/contracts/openapi/<service>.v1.json.",
        "Rewrites a spec file.",
        "under 1 minute",
        "refused",
        refused="It needs a service name. Run it in a terminal: make openapi SERVICE=<name>.",
    ),
    "contracts": _m(
        "Generate the clients",
        "Generates the event clients and the Python REST models.",
        "Rewrites generated files in the checkout.",
        "1 to 2 minutes",
        "changes-data",
        rewrites=True,
    ),
    "contracts-check": _m(
        "Check the generated clients",
        "Event schemas, generated clients and the public spec.",
        "Regenerates the clients, then compares them.",
        "1 to 3 minutes",
        "changes-data",
        rewrites=True,
        covered_by="gate:contracts-check",
    ),
    "hooks": _m(
        "Install the git hooks",
        "Installs the pre-commit and commit-msg hooks.",
        "Changes your git setup.",
        "a few seconds",
        "refused",
        refused="It changes your git hooks. Run it once in a terminal: make hooks.",
    ),
    "ci-lint": _m(
        "Check the CI files",
        "Validates the workflows and the pre-commit config.",
        "Reads files.",
        "under 1 minute",
        "safe",
        covered_by="gate:ci-lint",
    ),
    "migrations-check": _m(
        "Check the migration files",
        "One head per service, names, downgrades.",
        "Reads files.",
        "under 1 minute",
        "safe",
        covered_by="migrations-check",
    ),
    "migrations-catalog": _m(
        "Check row-level security",
        "Tenant tables have forced row-level security.",
        "Reads the database.",
        "under 1 minute",
        "safe",
        covered_by="migrations-catalog",
        needs=("docker",),
    ),
    "alerts-check": _m(
        "Check the alert rules",
        "promtool: the alert rules and their tests.",
        "Runs promtool in Docker.",
        "under 1 minute",
        "safe",
        covered_by="gate:alerts-check",
        needs=("docker",),
    ),
    "openapi-check": _m(
        "Check the API specs",
        "Every service with routes commits its spec and a test.",
        "Reads files.",
        "under 1 minute",
        "safe",
    ),
    "openapi-compat": _m(
        "Check API compatibility",
        "Committed specs break no client of main.",
        "Compares with main.",
        "1 to 2 minutes",
        "safe",
        covered_by="gate:openapi-compat",
    ),
    "sast": _m(
        "Security scan (code)",
        "Semgrep: an ERROR finding fails.",
        "Scans the code and writes semgrep.sarif.",
        "2 to 5 minutes",
        "safe",
        covered_by="gate:sast",
        needs=("docker",),
    ),
    "deps-scan": _m(
        "Security scan (dependencies)",
        "Trivy: fixable HIGH and CRITICAL findings fail.",
        "Scans the dependencies.",
        "2 to 5 minutes",
        "safe",
        covered_by="gate:deps-scan",
        needs=("docker",),
    ),
    "ci-gate-check": _m(
        "Check the CI gate job",
        "Every CI job is in the required gate's needs.",
        "Reads files.",
        "a few seconds",
        "safe",
    ),
    "data-quality": _m(
        "Check the rulebook's data",
        "Data-quality checks on the local rulebook schema.",
        "Reads the database.",
        "under 1 minute",
        "safe",
        covered_by="data-quality",
        needs=("docker",),
    ),
    "flags": _m(
        "Copy the flag registry",
        "Writes py-common's copy of the flag registry, then checks it.",
        "Rewrites a file in the checkout.",
        "a few seconds",
        "changes-data",
        rewrites=True,
    ),
    "flags-check": _m(
        "Check the flag registry",
        "Schema, owners, expiry and safe defaults.",
        "Reads files.",
        "a few seconds",
        "safe",
        covered_by="flags-check",
    ),
    "dev-flags": _m(
        "Start Unleash",
        "Starts Unleash for flags from Unleash.",
        "Starts a container.",
        "about 1 minute",
        "safe",
        covered_by="dev-flags",
        needs=("docker",),
    ),
    "openapi-public": _m(
        "Build the public API spec",
        "Merges the public operations into public.v1.json.",
        "Rewrites spec and model files in the checkout.",
        "1 to 2 minutes",
        "changes-data",
        rewrites=True,
    ),
    "web-dev": _m(
        "Web app dev server",
        "next dev on the web port.",
        "Runs a dev server.",
        "until stopped",
        "refused",
        refused=FOREGROUND + " Use Start the web app.",
        covered_by="web-start",
    ),
    "web-stack": _m(
        "Start the services (in memory)",
        "Every service with memory stores, no worker.",
        "Starts ten processes in the background.",
        "about 1 minute",
        "safe",
        covered_by="ui-start",
    ),
    "web-stack-wait": _m(
        "Wait for the services",
        "Waits until every service answers /health.",
        "Waits.",
        "up to 1 minute",
        "safe",
        covered_by="ui-wait",
    ),
    "web-stack-down": _m(
        "Stop the services",
        "Stops the web-stack services by their pid files.",
        "Stops the services.",
        "a few seconds",
        "stops-things",
        covered_by="ui-stop",
    ),
    "extract-backlog": _m(
        "Extract the documents waiting",
        "Starts the rule extraction for the classified documents still waiting.",
        "Starts extraction for documents already classified; each one is a model call through "
        "the gateway.",
        "under 1 minute to start",
        "changes-data",
        covered_by="extract-backlog",
        needs=("docker",),
        calls_model=True,
    ),
    "replay": _m(
        "Replay a dead letter",
        "Lists a dead-letter topic, or sends one of its messages back to where it came from.",
        "Needs a topic and an event id.",
        "varies",
        "refused",
        refused="Needs a topic and an event id: run it from a terminal, see "
        "docs/runbooks/outbox-relay.md.",
    ),
    "golden-export": _m(
        "Export draft golden cases",
        "Writes decided rule candidates as draft golden cases.",
        "Needs a date and an output folder.",
        "varies",
        "refused",
        refused="Needs a date and an output folder: run it from a terminal, see the rulebook "
        "README.",
    ),
    "control-panel": _m(
        "Open this app",
        "Opens the control app in a browser.",
        "Starts another copy.",
        "instant",
        "refused",
        refused="That is this app; it is already open.",
    ),
    "control-panel-app": _m(
        "Rebuild this app",
        "Builds ComplianceWatch.app.",
        "Rebuilds the app you are using.",
        "under 1 minute",
        "refused",
        refused="It rebuilds this app while it runs. Run it from a terminal.",
    ),
    "web-stack-logs": _m(
        "Follow a service's log",
        "Tails a web-stack service's log.",
        "Follows a log.",
        "until stopped",
        "refused",
        refused="It follows the log until stopped. Use Logs.",
    ),
    "web-seed": _m(
        "Seed the services",
        "The demo tenant and a recorded notification.",
        "Adds demo records to the services.",
        "under 1 minute",
        "changes-data",
        covered_by="load-demo-data",
    ),
    "web-e2e-install": _m(
        "Download the test browser",
        "Downloads Chromium for Playwright, once per machine.",
        "Downloads about 150 MB from the internet.",
        "1 to 5 minutes",
        "changes-data",
    ),
    "web-e2e": _m(
        "Click through the web app",
        "Playwright with accessibility checks.",
        "Builds the web app and runs browser tests.",
        "5 to 10 minutes",
        "safe",
        covered_by="gate:web-e2e",
    ),
    "web-screens": _m(
        "Regenerate the screens list",
        "Rewrites docs/web/screens.md from the registry.",
        "Rewrites a file in the checkout.",
        "a few seconds",
        "changes-data",
        rewrites=True,
    ),
    "web-screens-check": _m(
        "Check the screens list",
        "docs/web/screens.md matches the registry.",
        "Reads files.",
        "a few seconds",
        "safe",
        covered_by="gate:web-screens-check",
    ),
    "openapi-ts": _m(
        "Generate the TypeScript API types",
        "From packages/contracts/openapi.",
        "Rewrites generated files in the checkout.",
        "under 1 minute",
        "changes-data",
        rewrites=True,
    ),
    "openapi-ts-check": _m(
        "Check the TypeScript API types",
        "The generated types match the specs.",
        "Reads files.",
        "under 1 minute",
        "safe",
    ),
    "product": _m(
        "Start the product (web on 3000)",
        "make dev, migrate, the seed calendar, app, worker, web.",
        "Migrates the shared database and starts the product.",
        "2 to 5 minutes",
        "changes-data",
        covered_by="product-start",
        migrates=True,
    ),
    "product-role": _m(
        "Refresh the product's database role",
        "Creates or refreshes the product's role.",
        "Changes a database role.",
        "a few seconds",
        "changes-data",
        covered_by="product-role",
        needs=("docker",),
    ),
    "product-wait": _m(
        "Wait for the product",
        "The app, the worker and the web app answer.",
        "Waits.",
        "up to 2 minutes",
        "safe",
        covered_by="product-wait",
    ),
    "product-seed": _m(
        "Fill the product with sample data",
        "Synthetic tenants, a publication, decisions.",
        "Adds sample records to the product.",
        "about 1 minute",
        "changes-data",
        covered_by="product-seed",
        needs=("product",),
    ),
    "product-check": _m(
        "Check the product works",
        "Proves the running product works, step by step.",
        "Adds test records to the product.",
        "2 to 5 minutes",
        "changes-data",
        covered_by="product-check",
        needs=("product",),
    ),
    "product-e2e": _m(
        "Click through the product",
        "Playwright against the running product.",
        "Builds the web app and runs browser tests.",
        "5 to 10 minutes",
        "changes-data",
        covered_by="product-e2e",
        needs=("product",),
    ),
    "product-down": _m(
        "Stop the product",
        "Stops the pids make product recorded, with their children.",
        "Stops the product.",
        "a few seconds",
        "stops-things",
        covered_by="product-stop",
        takes=("product",),
    ),
    "product-logs": _m(
        "Follow the product's log",
        "Shows a product process's log.",
        "Follows a log.",
        "until stopped",
        "refused",
        refused="On its own it follows the log until stopped. Use The product's log.",
        covered_by="product-logs",
    ),
    "mvp-image": _m(
        "Build the product's image",
        "Builds compliancewatch-mvp:local.",
        "Builds an image.",
        "3 to 10 minutes",
        "safe",
        covered_by="mvp-image",
        needs=("docker",),
    ),
    "product-image": _m(
        "Start the product from its image",
        "The image, release, app and worker in containers.",
        "Migrates the shared database and starts containers.",
        "3 to 10 minutes",
        "changes-data",
        covered_by="product-image",
        migrates=True,
        needs=("docker",),
    ),
    "product-image-down": _m(
        "Stop the product's image",
        "Removes the image product's containers.",
        "Removes containers.",
        "a few seconds",
        "stops-things",
        covered_by="product-image-down",
        takes=("product",),
        needs=("docker",),
    ),
    "product-image-logs": _m(
        "Follow the image product's log",
        "Shows a container's log.",
        "Follows a log.",
        "until stopped",
        "refused",
        refused="On its own it follows the log until stopped. Use The image product's log.",
        covered_by="product-image-logs",
    ),
}

_WRITES = re.compile(r"\b(write|writes|rewrite|regenerate|generate|format|install|sync)\b", re.I)
_STOPS = re.compile(r"\b(stop|stops|remove|removes|down|kill)\b", re.I)
_DESTROYS = re.compile(r"\b(delete|deletes|drop|drops|reset|restore|wipe|destroy)\b", re.I)
_FOLLOWS = re.compile(r"\b(tail|follow|foreground|with reload|watch)\b", re.I)
_REGULATOR = re.compile(r"\b(backfill|crawl now|live regulator|scrape)\b", re.I)
_NEEDS_VALUE = re.compile(r"(?<![\[A-Za-z0-9_])[A-Z][A-Z0-9_]*=")
"""A variable its usage sets outside ``[...]``: the target needs it, and this app passes none."""
NEEDS_ARGUMENTS: Final = (
    "It needs arguments (such as ARGS=...) that this app never passes; run it in a terminal."
)


def guess(target: str, description: str) -> MakeText:
    """Words and a safety class for a target this app has no words for yet, from its name and
    its ``##`` help: a careful guess that leans to asking first."""
    text = f"{target} {description}"
    summary = description.strip() or f"make {target}"
    title = f"make {target}"
    if target in core.FORBIDDEN_TARGETS or _REGULATOR.search(text):
        return MakeText(
            title,
            summary,
            ("Contacts the live regulator websites.",),
            "varies",
            "refused",
            refused="It may contact the live regulator websites, which this app never does.",
        )
    if _NEEDS_VALUE.search(description):
        return MakeText(
            title,
            summary,
            ("Needs arguments, given in a terminal.",),
            "varies",
            "refused",
            refused=NEEDS_ARGUMENTS,
        )
    if _FOLLOWS.search(text) or target.endswith(("-logs", "-dev")):
        return MakeText(
            title,
            summary,
            ("Runs until it is stopped.",),
            "until stopped",
            "refused",
            refused=FOREGROUND,
        )
    if _DESTROYS.search(text):
        return MakeText(
            title,
            summary,
            ("It may delete or replace data.",),
            "varies",
            "destructive",
        )
    if _STOPS.search(text) or target.endswith(("-down", "-stop")):
        return MakeText(title, summary, ("It stops something.",), "varies", "stops-things")
    if target.endswith(("-check", "-lint")) or target in ("lint", "test", "typecheck"):
        return MakeText(
            title, summary, ("It checks; it should change no tracked file.",), "varies", "safe"
        )
    if _WRITES.search(text):
        return MakeText(
            title,
            summary,
            ("It may change files or data.",),
            "varies",
            "changes-data",
            rewrites=True,
        )
    return MakeText(
        title, summary, ("This app has no words for this target yet.",), "varies", "changes-data"
    )


def make_spec(target: str, description: str) -> Spec:
    words = MAKE_TEXTS.get(target) or guess(target, description)
    what = words.what
    if words.migrates:
        what = (*what, MIGRATE_NOTE)
    return Spec(
        id=f"make:{target}",
        title=words.title,
        summary=words.summary,
        what_happens=(*what, f"Runs: make {target}"),
        duration=words.duration,
        group=words.group,
        safety=words.safety,
        kind=words.kind,
        button="Run",
        confirm=words.what[0] if words.safety not in ("safe", "refused") else "",
        migrates=words.migrates,
        takes=words.takes,
        rewrites=words.rewrites,
        needs=words.needs,
        source="make",
        target=target,
        refused=words.refused,
        covered_by=words.covered_by,
        timeout=core.MAKE_DOWN_SECONDS if words.safety == "stops-things" else None,
        calls_model=words.calls_model,
    )


# ---- the documents the Docs view opens ---------------------------------------------------------

DOCS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("onboarding", "Onboarding", "docs/onboarding/README.md", "doc"),
    ("local-dev", "Local development", "docs/onboarding/local-dev.md", "doc"),
    ("product", "The local product", "docs/onboarding/product.md", "doc"),
    ("demo", "The demo", "docs/onboarding/demo.md", "doc"),
    ("control-panel", "This app's guide", "docs/onboarding/control-panel.md", "doc"),
    ("repository-settings", "Repository settings", "docs/onboarding/repository-settings.md", "doc"),
    ("readme", "README", "README.md", "doc"),
    ("contributing", "Contributing", "CONTRIBUTING.md", "doc"),
    ("screens", "Web screens", "docs/web/screens.md", "doc"),
    ("runbooks", "Runbooks", "docs/runbooks", "folder"),
    ("adr", "Decision records (ADRs)", "docs/adr", "folder"),
)
"""(id, label, path in the checkout, doc or folder)."""


# ---- building: what the catalog needs from the core, and what running an action means ----------


class Context(Protocol):
    """What the catalog reads: the checkout and its plans, and the live lists the parameters
    choose from."""

    @property
    def project(self) -> core.Project: ...

    @property
    def plans(self) -> core.Plans: ...

    def backups(self) -> list[core.Dump]: ...

    def compose_services(self) -> list[str]: ...

    def doc_choices(self) -> list[tuple[str, str]]: ...


class ParamError(ValueError):
    """A parameter is missing, unknown or not one of its choices; the message says which."""


@dataclass(frozen=True)
class Built:
    """What running an action means: a plan for the runner, or something to open."""

    plan: core.Plan | None = None
    open_path: Path | None = None
    text_editor: bool = False
    psql: bool = False


@dataclass
class Catalog:
    """Every action, by id: the curated ones, one per gate, and one per make target."""

    specs: dict[str, Spec] = field(default_factory=dict)

    @classmethod
    def load(cls, project: core.Project) -> Catalog:
        specs: dict[str, Spec] = {
            spec.id: spec
            for spec in CURATED
            if not spec.target
            or project.known_targets is None
            or spec.target in project.make_targets
        }
        for gate in core.GATES:
            if project.known_targets is None or gate.target in project.make_targets:
                specs[f"gate:{gate.target}"] = gate_spec(gate)
        for target, description in project.make_targets.items():
            if description.strip():  # only the ## documented targets: the rest are helpers
                specs[f"make:{target}"] = make_spec(target, description)
        return cls(specs)

    def get(self, action_id: str) -> Spec | None:
        return self.specs.get(action_id)


def choices(ctx: Context, param: Param) -> list[tuple[str, str]]:
    """The values a parameter may take now, as (value, label)."""
    project = ctx.project
    if param.choices:
        return list(param.choices)
    if param.source == "services":
        return [(name, name) for name in core.SERVICES]
    if param.source == "workers":
        return [(name, name) for name in project.workers]
    if param.source == "relays":
        return [(name, name) for name in project.relays]
    if param.source == "backups":
        now = time.time()
        return [(dump.path, dump.describe(now)) for dump in ctx.backups()]
    if param.source == "check-steps":
        return [(step, step) for step in core.selectable_steps(project.check_steps)]
    if param.source == "product-procs":
        return [("app", "the app"), ("worker", "the worker"), ("web", "the web app")]
    if param.source == "image-procs":
        return [("app", "the app"), ("worker", "the worker"), ("release", "the release step")]
    if param.source == "containers":
        return [(name, name) for name in ctx.compose_services()]
    if param.source == "docs":
        return ctx.doc_choices()
    return []


def normalise(ctx: Context, spec: Spec, raw: Mapping[str, Any]) -> dict[str, Any]:
    """The parameters checked against the spec: no unknown name, each value one of its choices,
    booleans as booleans; a missing optional one takes its default."""
    known = {param.name for param in spec.params}
    if unknown := sorted(set(raw) - known):
        raise ParamError(f"unknown parameter: {', '.join(unknown)}")
    values: dict[str, Any] = {}
    for param in spec.params:
        value = raw.get(param.name)
        if value in (None, ""):
            if param.required and param.default is None:
                raise ParamError(f"{param.label} is required")
            values[param.name] = param.default
            continue
        if param.kind == "boolean":
            if not isinstance(value, bool):
                raise ParamError(f"{param.label} must be true or false")
            values[param.name] = value
            continue
        if not isinstance(value, str):
            raise ParamError(f"{param.label} must be text")
        allowed = {choice for choice, _ in choices(ctx, param)}
        if param.kind == "choice" and value not in allowed:
            raise ParamError(f"{value!r} is not one of the choices for {param.label}")
        values[param.name] = value
    return values


OPEN_TARGETS: Final[Mapping[str, tuple[str, bool]]] = {
    "open-env": (".env", True),
    "open-logs-folder": ("var/web-stack", False),
    "open-backups-folder": ("var/backups", False),
}

_PLANS: Final[Mapping[str, Callable[[core.Plans, Mapping[str, Any]], core.Plan]]] = {
    "start-everything": lambda p, v: p.start_everything(),
    "docker-start": lambda p, v: p.docker_start(),
    "docker-stop": lambda p, v: p.docker_stop(),
    "force-stop-docker": lambda p, v: p.colima_force_stop(),
    "databases-start": lambda p, v: p.databases_start(),
    "databases-stop": lambda p, v: p.databases_stop(),
    "dev-observability": lambda p, v: p.dev_observability(),
    "dev-llm": lambda p, v: p.dev_llm(),
    "dev-flags": lambda p, v: p.dev_flags(),
    "dev-ps": lambda p, v: p.dev_ps(),
    "container-logs": lambda p, v: p.container_logs(v["service"]),
    "ui-start": lambda p, v: p.ui_start(),
    "ui-stop": lambda p, v: p.ui_stop(),
    "ui-restart": lambda p, v: p.ui_restart(),
    "ui-wait": lambda p, v: p.ui_wait(),
    "web-start": lambda p, v: p.web_start(),
    "worker-start": lambda p, v: p.worker_start(v["service"]),
    "worker-stop": lambda p, v: p.worker_stop(v["service"]),
    "relay-start": lambda p, v: p.relay_start(v["service"]),
    "relay-stop": lambda p, v: p.relay_stop(v["service"]),
    "product-start": lambda p, v: p.product_start(),
    "product-stop": lambda p, v: p.product_stop(),
    "product-wait": lambda p, v: p.product_wait(),
    "product-role": lambda p, v: p.product_role(),
    "product-seed": lambda p, v: p.product_seed(),
    "product-check": lambda p, v: p.product_check(v.get("step") or None),
    "product-e2e": lambda p, v: p.product_e2e(),
    "product-logs": lambda p, v: p.product_logs(v["proc"]),
    "mvp-image": lambda p, v: p.mvp_image(),
    "product-image": lambda p, v: p.product_image(),
    "product-image-down": lambda p, v: p.product_image_down(),
    "product-image-logs": lambda p, v: p.product_image_logs(v["proc"]),
    "load-demo-data": lambda p, v: p.load_demo_data(),
    "demo": lambda p, v: p.demo(),
    "migrate": lambda p, v: p.migrate(v.get("service") or None),
    "migrations-catalog": lambda p, v: p.migrations_catalog(),
    "data-quality": lambda p, v: p.data_quality(),
    "seed-check": lambda p, v: p.seed_check(),
    "backup": lambda p, v: p.backup(),
    "reset": lambda p, v: p.reset(bool(v.get("backup_first", True))),
    "gates-in-order": lambda p, v: p.gates_in_order(),
    "crawl-report": lambda p, v: p.crawl_report(),
    "extract-backlog-count": lambda p, v: core.Plan(
        "count the documents waiting for extraction",
        (core.make("extract-backlog", "ARGS=--dry-run"),),
    ),
    "extract-backlog": lambda p, v: core.Plan(
        "extract the documents waiting", (core.make("extract-backlog"),)
    ),
    "flags-check": lambda p, v: p.flags_check(),
    "doctor": lambda p, v: p.doctor(),
}


FIXED_ARGS: Final[Mapping[str, frozenset[str]]] = {
    "extract-backlog-count": frozenset({"--dry-run"}),
    "seed-check": frozenset({"--check"}),
}
"""The only ``ARGS=`` values an action may hand to make, by action id: fixed words written here,
never a person's input. ``product-check`` takes ``--step <step>`` for a step of the checkout's
list (:func:`args_allowed`); every other action passes no ``ARGS`` at all."""


def args_allowed(ctx: Context, action_id: str, value: str) -> bool:
    """Whether action ``action_id`` may run make with ``ARGS=value``: exactly an allowed value of
    that action, nothing else."""
    if action_id == "product-check":
        steps = core.selectable_steps(ctx.project.check_steps)
        return value in {f"--step {step}" for step in steps}
    return value in FIXED_ARGS.get(action_id, frozenset())


def check_arguments(ctx: Context, spec: Spec, plan: core.Plan) -> None:
    """Refuses a plan whose make commands pass an ``ARGS`` its action may not."""
    for step in plan.steps:
        for argv in core.step_commands(step):
            if not argv or Path(argv[0]).name != "make":
                continue
            for part in argv[1:]:
                if part.startswith("ARGS=") and not args_allowed(ctx, spec.id, part[5:]):
                    raise ParamError(f"{spec.title} may not pass {part!r} to make")


def build(
    ctx: Context,
    spec: Spec,
    values: Mapping[str, Any],
    *,
    expected: Mapping[int, str] | None = None,
) -> Built:
    """What running ``spec`` with checked ``values`` means. ``expected``: for the stops that
    reach the web app, the pids the question named with the program each ran; only those are
    signalled. A plan that passes make an ``ARGS`` its action may not is refused
    (:func:`check_arguments`)."""
    built = _build(ctx, spec, values, expected=expected)
    if built.plan is not None:
        check_arguments(ctx, spec, built.plan)
    return built


def _build(
    ctx: Context,
    spec: Spec,
    values: Mapping[str, Any],
    *,
    expected: Mapping[int, str] | None,
) -> Built:
    plans = ctx.plans
    if spec.id in OPEN_TARGETS:
        relative, editor = OPEN_TARGETS[spec.id]
        return Built(open_path=ctx.project.repo / relative, text_editor=editor)
    if spec.id == "psql":
        return Built(psql=True)
    if spec.id == "stop-everything":
        return Built(plan=plans.stop_everything(expected_web=expected))
    if spec.id == "web-stop":
        return Built(plan=plans.web_stop(expected=expected))
    if spec.id == "restore":
        plan = plans.restore(str(values["dump"]))
        if values.get("backup_first") and plan.steps:
            first = core.make("dev-backup", label="back up the database first")
            plan = core.Plan(plan.title, (first, *plan.steps), confirm=plan.confirm)
        return Built(plan=plan)
    if spec.id == "open-doc":
        doc = next(d for d in DOCS if d[0] == values["doc"])
        return Built(open_path=ctx.project.repo / doc[2])
    if spec.id == "migrations-check":
        gate = next(g for g in core.GATES if g.target == "migrations-check")
        return Built(plan=plans.gate(gate))
    if spec.id.startswith("gate:"):
        target = spec.id.split(":", 1)[1]
        gate = next(g for g in core.GATES if g.target == target)
        return Built(plan=plans.gate(gate))
    if spec.source == "make":
        step = core.make(spec.target, timeout=spec.timeout)
        confirm = spec.confirm or None
        return Built(plan=core.Plan(f"make {spec.target}", (step,), confirm=confirm))
    builder = _PLANS.get(spec.id)
    if builder is None:
        raise ParamError(f"{spec.id} has no plan")
    return Built(plan=builder(plans, values))
