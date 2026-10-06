// The Guide's words, kept as data so the views, the command palette and the tour share them.
// Every statement is about this project as it is (README.md, docs/onboarding, the Makefile and
// tools/control-panel/panel_core.py); docs/onboarding/control-panel.md says the same things.
// Where something is not built yet, the text says so.

export const PRODUCT_LINE =
  "ComplianceWatch watches regulators for rule changes, decides which changes apply to one specific business, and turns each into a dated obligation the owner can act on. It starts with Indian small businesses under GST.";

export const GUIDE_SECTIONS = [
  { id: "how", title: "How ComplianceWatch works", nav: "How it works", icon: "pipeline" },
  { id: "parts", title: "What each part does", nav: "The parts", icon: "layers" },
  { id: "recipes", title: "Step-by-step recipes", nav: "Recipes", icon: "list" },
  { id: "glossary", title: "Glossary", nav: "Glossary", icon: "book" },
  {
    id: "trouble",
    title: "When something goes wrong",
    nav: "When things go wrong",
    icon: "warning",
  },
  { id: "never", title: "What this app will never do", nav: "What it never does", icon: "shield" },
  { id: "more", title: "More to read", nav: "More to read", icon: "file" },
];

/** The flow the Guide draws, left to right. */
export const FLOW = [
  {
    id: "regulators",
    title: "Regulators",
    icon: "building",
    text: "Government sites publish notifications and circulars: CBIC, the GST Council, GSTN and Maharashtra GST.",
  },
  {
    id: "pipeline",
    title: "Pipeline",
    icon: "pipeline",
    text: "Reads those documents, works out what each one is, and drafts rule changes for people to review.",
  },
  {
    id: "rulebook",
    title: "Rulebook",
    icon: "book",
    text: "Keeps every rule, each version and the exact clauses it cites. Analysts review and publish them.",
  },
  {
    id: "engine",
    title: "Applicability engine",
    icon: "route",
    text: "Decides which rules apply to each business, from what the business told us about itself.",
  },
  {
    id: "obligations",
    title: "Obligations",
    icon: "calendar",
    text: "Turns each rule that applies into dated duties: what to file, and by when.",
  },
  {
    id: "notifications",
    title: "Notifications",
    icon: "message",
    text: "Sends change cards and reminders by WhatsApp and email, with quiet hours and daily digests.",
  },
  {
    id: "people",
    title: "Owners and CA firms",
    icon: "users",
    text: "See their obligations, calendar and changes in the web app, and act on them.",
  },
];

/** The services that help the flow from the side. */
export const HELPERS = [
  {
    title: "Profile",
    text: "Each business: its GSTINs, registrations and its answers to the onboarding questions.",
  },
  {
    title: "Identity",
    text: "Who is who: businesses and CA firms, their people and roles, sign-in and consents.",
  },
  { title: "Q&A", text: "Answers questions with citations, or says a question is not covered." },
  {
    title: "LLM gateway",
    text: "The only door to AI models. By default it answers from a fake model.",
  },
  { title: "Eval", text: "Measures the AI parts against golden sets of right answers." },
];

export const ON_THIS_MAC = [
  "Everything runs on this Mac. Nothing here is a service for real customers.",
  "Nothing this app starts reads the real regulator websites: the crawl stays off.",
  "The full product writes its messages to a file (the sink) instead of sending them. Real WhatsApp and email stay off unless someone turns them on in .env.",
  "The demo businesses and people are made up. Their names say so: synthetic.",
];

export const WAYS = [
  {
    id: "screens",
    title: "The screens (the UI-only stack)",
    icon: "globe",
    text: "Start everything on Home starts Docker, the databases and queues, the ten services (each on its own port, 8001 to 8010) and the web app at localhost:3000, then opens it. Use it to click through the screens. It has no worker, so publishing a rule does not turn into obligations or messages here.",
    action: "start-everything",
    label: "Start everything",
  },
  {
    id: "product",
    title: "The full product",
    icon: "package",
    text: "Run, The product starts the one app that holds every service, its worker (with the message queue and Temporal on) and its own web app at 127.0.0.1:3400. Here a published rule really becomes decisions, obligations and a change card. Fill it with sample data, then check it works.",
    action: "product-start",
    label: "Start the product",
  },
];

export const DATA_NOTE =
  "Your data lives in Docker's storage (volumes) on this Mac: Postgres holds every service's data and Redpanda the messages between them. Stopping keeps it. Only Reset deletes it; it asks first and offers to back up. Backups are files in var/backups.";

// ---- the parts -------------------------------------------------------------------------------

export const INFRA_PARTS = [
  {
    id: "docker",
    title: "Docker",
    icon: "container",
    where: "Colima on this Mac",
    text: "A small virtual computer that runs the databases and the queue as containers. When it is not running, this app starts it with Colima (4 CPUs, 8 GB of memory). Nothing else works without it.",
  },
  {
    id: "postgres",
    title: "Postgres",
    icon: "database",
    where: "localhost:5432",
    text: "The database. Each service keeps its data in its own part of it (a schema).",
  },
  {
    id: "redis",
    title: "Redis",
    icon: "memory",
    where: "localhost:6379",
    text: "A fast store in memory for short-lived data.",
  },
  {
    id: "redpanda",
    title: "Redpanda, the message queue",
    icon: "wave",
    where: "localhost:19092",
    text: "Carries events between services: when one service changes something, the others hear about it here. It speaks Kafka's language.",
  },
  {
    id: "temporal",
    title: "Temporal",
    icon: "hourglass",
    where: "localhost:7233, its web page at localhost:8233",
    text: "Runs long jobs one step at a time and tries a failed step again, such as reading a document or deciding a new rule for every business.",
  },
];

export const SERVICE_PARTS = [
  {
    name: "identity",
    port: 8001,
    text: "Who is who: tenants (a business or a CA firm), their people and roles, sign-in, consent records and billing.",
  },
  {
    name: "profile",
    port: 8002,
    text: "Each business: its GSTINs and registrations, and its answers to the onboarding questions.",
  },
  {
    name: "rulebook",
    port: 8003,
    text: "The rules: every version with the regulator clauses it cites, the analysts' review and publishing, and the regulator documents.",
  },
  {
    name: "applicability-engine",
    port: 8004,
    text: "Decides which rules apply to each business, from the business's profile.",
  },
  {
    name: "obligation",
    port: 8005,
    text: "The dated duties: what each business must file and by when, and their tracking (start, assign, complete, comment).",
  },
  {
    name: "notification",
    port: 8006,
    text: "Change cards and reminders by WhatsApp and email, with quiet hours, batching and daily digests.",
  },
  {
    name: "qa",
    port: 8007,
    text: "Answers questions with citations, or says the question is not covered.",
  },
  {
    name: "llm-gateway",
    port: 8008,
    text: "The only door to AI models. By default it answers from a fake model, so nothing goes to a real one.",
  },
  {
    name: "eval",
    port: 8009,
    text: "Measures the AI parts' quality against golden sets of right answers.",
  },
  {
    name: "pipeline",
    port: 8010,
    text: "Reads regulators' documents, works out what each one is and drafts rule changes for review. Its crawl stays off here.",
  },
];

export const APP_PARTS = [
  {
    id: "web",
    title: "The web app",
    icon: "globe",
    where: "localhost:3000",
    text: "The screens: owners and CA firms see their obligations, calendar and changes; the internal team uses /admin. It talks to the ten services of the UI-only stack.",
  },
  {
    id: "product",
    title: "The full product",
    icon: "package",
    where: "app on 127.0.0.1:8000 and :8080, worker on :8081, web app on 127.0.0.1:3400",
    text: "Every service in one app, the way it is deployed; a worker that passes events on, makes obligations, sends reminders and change cards (to the sink) and runs fan-outs; and its own web app.",
  },
  {
    id: "workers",
    title: "Workers and outbox relays",
    icon: "cpu",
    where: "Run, Workers and relays",
    text: "Optional helpers for the UI-only stack: a worker runs one service's background jobs, a relay passes one service's events to the queue. The full product already runs all of them.",
  },
  {
    id: "tools",
    title: "Optional tools",
    icon: "gauge",
    where: "Run, Optional tools",
    text: "Observability (Grafana at localhost:3030, Prometheus, Tempo, Langfuse and a collector) shows traces and metrics; the fake LLM gateway runs the AI gateway in a container; Unleash serves flags from a server instead of .env.",
  },
];

// ---- recipes ---------------------------------------------------------------------------------
// A step may carry: do { action, params } runs an action, open "web" | "product" | "signin" opens
// a page, go "#/route" moves in the app, copy "text" offers a copy button, done "<part>" shows a
// tick when that part is already running.

export const SIGNIN_TENANTS = {
  caFirm: "00000000-0000-4000-8000-0000000d0002",
  business: "00000000-0000-4000-8000-0000000d0001",
};

export const RECIPES = [
  {
    id: "see-screens",
    title: "See the app's screens",
    icon: "globe",
    time: "About 10 minutes the first time",
    intro:
      "The quickest way to click through ComplianceWatch: the web app on the UI-only stack, with a demo business in it.",
    steps: [
      {
        text: "Start everything.",
        detail:
          "Docker, the databases and queues, the ten services and the web app start one after another. The first time, Docker downloads about 2 GB.",
        do: { action: "start-everything" },
        done: "web",
      },
      {
        text: "Load the demo data.",
        detail:
          "Adds the thirteen standing GST rules as drafts, a demo business with its answers, and one recorded CBIC notification.",
        do: { action: "load-demo-data" },
      },
      { text: "Open the web app.", do: { open: "web" } },
      {
        text: "Sign in.",
        detail:
          'On the sign-in page choose the tenant kind Business, tick Owner, type any display name, press "Use the last seeded tenant", then Sign in. Nothing is checked on this sign-in page; it exists only on your Mac.',
      },
    ],
  },
  {
    id: "run-product",
    title: "Run the whole product",
    icon: "package",
    time: "About 10 minutes",
    intro:
      "The full product, where a published rule really becomes decisions, obligations and a change card.",
    steps: [
      {
        text: "Start the product.",
        detail:
          "Starts Docker if needed, updates the databases, then the product's app, its worker and its web app, and waits until all of them answer.",
        do: { action: "product-start" },
        done: "product",
      },
      {
        text: "Fill it with sample data.",
        detail:
          "Two made-up customers, a business (Demo Traders) and a CA firm (Demo CA Associates), and a made-up publication of the three GSTR-3B rules.",
        do: { action: "product-seed" },
      },
      {
        text: "Check it works.",
        detail:
          "The product check runs its steps one after another and says which passed. Its rollback step always reports itself skipped here.",
        do: { action: "product-check" },
      },
      { text: "Open the product's sign-in page.", do: { open: "signin" } },
    ],
  },
  {
    id: "as-owner",
    title: "Try it as a business owner",
    icon: "building",
    time: "2 minutes, with the product running",
    intro:
      "See what a small business sees: its obligations, its calendar and the rule changes that affect it.",
    steps: [
      {
        text: "Make sure the product is running and filled with sample data.",
        detail: 'Steps 1 and 2 of "Run the whole product".',
        do: { action: "product-start" },
        done: "product",
      },
      { text: "Open the product's sign-in page.", do: { open: "signin" } },
      {
        text: "Choose the tenant kind Business, tick Owner and type a display name.",
      },
      {
        text: 'Press "Use the last seeded tenant", then Sign in.',
        detail:
          "Demo Traders (synthetic) opens with its obligations, calendar and changes. The Ask tab appears only when the web app's Q&A flag is on.",
      },
    ],
  },
  {
    id: "as-ca",
    title: "Try it as a CA firm",
    icon: "briefcase",
    time: "2 minutes, with the product running",
    intro: "See what an accountants' firm sees for its clients.",
    steps: [
      {
        text: "Make sure the product is running and filled with sample data.",
        do: { action: "product-start" },
        done: "product",
      },
      { text: "Open the product's sign-in page.", do: { open: "signin" } },
      { text: "Choose the tenant kind CA firm, tick CA admin and type a display name." },
      {
        text: "Paste this tenant id, then Sign in.",
        detail:
          "It is Demo CA Associates (synthetic), with two client businesses. A change's Affected clients page lists the clients it applies to. A page listing all clients is not built yet.",
        copy: SIGNIN_TENANTS.caFirm,
      },
    ],
  },
  {
    id: "as-admin",
    title: "Try it as an admin",
    icon: "key",
    time: "2 minutes, with the product running",
    intro:
      "The internal team's tools: rules, documents, decisions, fan-outs, notifications and flags.",
    steps: [
      {
        text: "Make sure the product is running.",
        do: { action: "product-start" },
        done: "product",
      },
      { text: "Open the product's sign-in page.", do: { open: "signin" } },
      {
        text: "Choose the tenant kind Internal (regulatory team), tick Admin, type a display name and leave the tenant id empty. Sign in.",
        detail:
          "Internal tools (/admin) opens. Pages that are not built yet, such as the review queue, say so.",
      },
    ],
  },
  {
    id: "five-minute-demo",
    title: "Show the five-minute demo",
    icon: "sparkles",
    time: "A few seconds, no Docker needed",
    intro:
      "A demo business from consent to its first reminder, printed as a story, in one program.",
    steps: [
      {
        text: "Run the demo.",
        detail:
          "It records consents, registers the business by GSTIN, decides which rules apply, makes the calendar and sends a reminder in Hindi through a fake channel.",
        do: { action: "demo" },
      },
      {
        text: "Read the story in its output.",
        detail: "docs/onboarding/demo.md says what to point out at each minute.",
      },
    ],
  },
  {
    id: "checks",
    title: "Check your work before sharing it",
    icon: "checks",
    time: "Several minutes",
    intro:
      "Run the same checks CI runs, so a pull request does not fail on something you could have seen.",
    steps: [
      {
        text: "Run the quick checks.",
        detail:
          "make check: code style, types, tests and the project's own rules. No Docker needed.",
        do: { action: "gate:check" },
      },
      {
        text: "If one fails, open it.",
        detail:
          "Its name turns red in Checks. Read its output, fix the cause, then run that check alone again from Checks.",
        go: "#/checks",
      },
      {
        text: "For a bigger change, run every CI check in order.",
        detail:
          "It needs Docker, takes much longer and carries on past a failure, then lists each result.",
        do: { action: "gates-in-order" },
      },
    ],
  },
  {
    id: "free-memory",
    title: "Stop everything to free memory",
    icon: "power",
    time: "About a minute",
    intro:
      "Docker's virtual machine keeps memory while it runs. Stop everything when you are done; your data is kept.",
    steps: [
      {
        text: "Stop everything.",
        detail:
          "Stops the web app, the services, the product, this app's workers and relays, the databases and Docker itself. If another session is working in this checkout, the confirm names it first.",
        do: { action: "stop-everything" },
      },
    ],
  },
  {
    id: "start-fresh",
    title: "Start fresh",
    icon: "rotate",
    time: "A few minutes",
    intro: "When the local data is in a bad state, reset it and start again with empty databases.",
    steps: [
      {
        text: "Reset the database, with a backup first.",
        detail:
          'Reset stops the services and the product, deletes all local data (Docker\'s storage for this project), then starts the databases again: empty, updated and with the seed rules. Keep "Back up first" ticked.',
        do: { action: "reset" },
      },
      { text: "Start everything again.", do: { action: "start-everything" }, done: "web" },
      { text: "Load the demo data again.", do: { action: "load-demo-data" } },
    ],
  },
  {
    id: "broken",
    title: "What to do when something breaks",
    icon: "help",
    time: "",
    intro: "Most problems have a plain reason and a one-click fix.",
    steps: [
      {
        text: "Look at the lights at the top.",
        detail: "Grey is stopped, amber is partly running, red needs attention.",
      },
      {
        text: "Read the error where it happened.",
        detail:
          "A failed card says what went wrong in plain words, with a button that fixes it when there is one. Show technical details has the exact lines.",
      },
      { text: "Open the part's log.", go: "#/logs" },
      { text: "Look up the problem.", go: "#/guide/trouble" },
      {
        text: "Still stuck? Copy the output and send it to a developer.",
        detail: "Every output has a Copy button.",
      },
    ],
  },
];

// ---- the glossary ----------------------------------------------------------------------------

export const GLOSSARY = [
  [
    "Analyst",
    "A person on the regulatory team who checks a rule against the regulator's text before it is published.",
  ],
  [
    "Backup",
    "A copy of the database in a file in var/backups, made with Back up the database. Restore a backup puts it back.",
  ],
  [
    "Branch",
    "A line of work in the code. main is the shared, reviewed version; other branches hold work in progress.",
  ],
  [
    "CA firm",
    "A firm of chartered accountants that looks after the compliance of several client businesses.",
  ],
  ["Change card", "The message that tells a business about a rule change that applies to it."],
  [
    "Check",
    "An automatic test of the code or the data. CI runs the same checks on every change. Also called a gate.",
  ],
  ["Checkout", "The folder with the project's code on this Mac. This app runs its commands there."],
  ["CI", "Continuous integration: GitHub runs the checks on every change before it is merged."],
  ["Citation", "The exact regulator clause a rule is based on, quoted word for word."],
  ["Colima", "The free tool this app uses to run Docker on a Mac."],
  [
    "Consumer group",
    "A named reader of the message queue. It remembers how far it has read each topic.",
  ],
  ["Container", "One program running inside Docker, such as the Postgres database."],
  [
    "Crawl",
    "Reading the regulators' websites on a schedule. Always off for everything this app starts.",
  ],
  ["Database", "Where the data is kept. Here it is Postgres, running in Docker."],
  [
    "Dead letters",
    "Messages that could not be handled. They wait in a topic whose name ends in .dlq until someone looks at them.",
  ],
  ["Docker", "Software that runs programs in containers. The databases and the queue run in it."],
  ["Eval", "A measured test of the AI parts against a golden set of right answers."],
  ["Fan-out", "Deciding a newly published rule for every business at once, in batches."],
  [
    "Flag",
    "A switch or setting for a feature, usually set in .env. This app shows flags but never changes them.",
  ],
  ["GSTIN", "A business's GST registration number."],
  ["Hold", "A pause an admin puts on every fan-out until it is released."],
  ["Lag", "How many messages a consumer group still has to read."],
  [
    "LLM gateway",
    "The one service that talks to AI models (large language models). By default it uses a fake model.",
  ],
  [
    "make",
    "The tool that runs the project's named commands, such as make dev or make check. Most buttons here run one or more of them.",
  ],
  ["Migration", "A step that updates the database's structure to match the code."],
  ["Obligation", "A dated duty for a business, such as a GST return to file by a due date."],
  ["Outbox relay", "A helper that passes a service's saved events on to the message queue."],
  ["Pid", "The number the Mac gives each running program (its process id)."],
  ["Port", "A numbered door a program listens on, like 3000 for the web app."],
  ["Process", "A running program."],
  [
    "Product check",
    "A test of the running product from end to end, one step at a time: health, the loop from rule to message, tenant isolation and more.",
  ],
  [
    "Queue",
    "The message queue, Redpanda, which carries events between services in topics. It speaks Kafka's language.",
  ],
  [
    "Rule version",
    "One version of a rule. It starts as a draft, analysts review it, and then it is published.",
  ],
  [
    "Seed",
    "Loading starter data: the thirteen standing GST rules as drafts, or the made-up demo businesses.",
  ],
  ["Service", "One part of ComplianceWatch with one job, such as obligations or notifications."],
  [
    "Sink",
    "A file, var/product/sink.jsonl, where the full product writes its messages instead of sending them.",
  ],
  ["Synthetic", "Made up for tests and demos. Synthetic businesses and people are not real."],
  ["Temporal", "Runs long jobs as steps and tries a failed step again."],
  [
    "Tenant",
    "One customer account: a business or a CA firm. A tenant never sees another tenant's data.",
  ],
  ["Topic", "A named stream of events in the queue, such as obligation.created."],
  [
    "UI-only stack",
    "The ten services and the web app, for clicking through screens. It has no worker.",
  ],
  [
    "Uncommitted changes",
    "Edits in the checkout that are not yet saved in git. This app shows how many there are.",
  ],
  ["Volume", "Docker's storage on this Mac, where the databases keep their data between runs."],
  [
    "Worker",
    "A program that does background work: it reads events, sends reminders and runs long jobs.",
  ],
].map(([term, text]) => ({ term, text, id: termId(term) }));

export function termId(term) {
  return String(term)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

// ---- troubleshooting -------------------------------------------------------------------------

export const TROUBLE = [
  {
    title: "Docker is not running",
    why: "The databases and the queue run inside Docker.",
    fix: "Start Docker. The first start takes a minute or two.",
    action: "docker-start",
  },
  {
    title: "Start everything stopped part-way",
    why: "One of its steps failed. The card names the step and the reason.",
    fix: "Use the fix button the card offers, or read Show technical details. Then press Start everything again.",
  },
  {
    title: "A port is already in use",
    why: "Another program, perhaps a second copy of the project, listens on a port this needs.",
    fix: "Processes lists every port with the program on it. Stop it there if it belongs to this checkout; otherwise quit that program, or change the port in .env.",
    go: "#/processes",
  },
  {
    title: "The web app does not open",
    why: "The first start builds it, which takes a minute or two.",
    fix: "Wait until the Web light turns green. If it stays grey, read its log in Logs, then stop and start the web app from Run.",
    go: "#/logs",
  },
  {
    title: "The product check fails",
    why: "One of its steps found something wrong; the others still run.",
    fix: "Run that step on its own from Checks and read its output. docs/onboarding/product.md has a troubleshooting list for each step.",
    go: "#/checks",
  },
  {
    title: 'It says "make ... is not a target of this checkout\'s Makefile"',
    why: "The checkout is on a branch that does not have that command.",
    fix: "Switch the checkout to main in a terminal, or ask whoever works on that branch.",
  },
  {
    title: "A tool is missing",
    why: "A command needs a program that is not installed (for example uv, pnpm or colima).",
    fix: "Run Which tools are installed. The Local development guide says how to install each one.",
    action: "doctor",
  },
  {
    title: "Docker did not stop in time",
    why: "Each step of a stop has a time limit, and colima stop overran its 2 minutes.",
    fix: "The failure offers Force-stop Docker, which asks first: a forced stop gives the databases no time to close their files.",
  },
  {
    title: "The branch chip at the top is red",
    why: "Another session is working in this checkout, for example Claude's build agent running tests.",
    fix: "Wait for it to finish, or see what it is in Processes. Stop everything, Start fresh and Restore a backup would break its work, and their questions say so.",
    go: "#/processes",
  },
  {
    title: "The window says it lost its connection",
    why: "The app's helper stopped, or the Mac went to sleep.",
    fix: "Wait a few seconds; it reconnects by itself. If it does not, quit the app and open it again.",
  },
  {
    title: 'The window says "Open this window from the app"',
    why: "The page was reloaded without the key the app gives it.",
    fix: "Open the app again (or run make control-panel again).",
  },
  {
    title: "The window is empty, or says it could not load",
    why: "Part of the window did not arrive from the app's helper. The window loads itself again once on its own.",
    fix: "Press ⌘R to load it again. If it stays empty, quit the app and open it again.",
  },
  {
    title: "The Mac feels slow",
    why: "Docker's virtual machine uses memory and processor time while it runs.",
    fix: "Stop everything when you are done. Your data is kept for next time.",
    action: "stop-everything",
  },
];

// ---- what this app never does ----------------------------------------------------------------

export const NEVER = [
  {
    title: "Run anything it was not built to run",
    text: "Every button runs one of the project's own make commands or a plain program, never through a shell, and only commands this checkout's Makefile has.",
  },
  {
    title: "Read the real regulator websites",
    text: "It never runs make backfill or make label, which read those sites, and the crawl stays off for everything it starts, whatever .env says.",
  },
  {
    title: "Withdraw a published rule",
    text: "It never runs the product check's rollback step (--destructive). Only CI runs that, on a database made for the run.",
  },
  {
    title: "Fill the product with extra options",
    text: "Filling the product with sample data runs with no options, and only while the product answers.",
  },
  {
    title: "Stop what is not this project's",
    text: "It never stops itself, another control window, what Claude Code or an editor runs, or anything outside this checkout, such as your terminal itself. A make check you started in a terminal can be stopped from Processes: the question names every process the stop reaches, and only those are signalled.",
  },
  {
    title: "Touch git",
    text: "It never fetches, commits, pushes or switches branches, and it writes nothing in the checkout before you start something.",
  },
  {
    title: "Change your settings",
    text: "It never changes a flag, .env or the project's files itself. The commands it runs write what they always write, such as test reports, and make contracts-check regenerates the generated clients before it compares them.",
  },
  {
    title: "Delete data without asking",
    text: "Reset and Restore ask first, say what they delete and offer a backup.",
  },
  {
    title: "Run two changes at once",
    text: "One step runs at a time, and Cancel stops the running one with everything it started.",
  },
];

// ---- the documents ---------------------------------------------------------------------------

export const DOCS_FALLBACK = [
  { label: "Local development", path: "docs/onboarding/local-dev.md" },
  { label: "The local product", path: "docs/onboarding/product.md" },
  { label: "The five-minute demo", path: "docs/onboarding/demo.md" },
  { label: "This app", path: "docs/onboarding/control-panel.md" },
  { label: "README", path: "README.md" },
  { label: "Contributing", path: "CONTRIBUTING.md" },
];

// ---- the tour --------------------------------------------------------------------------------

export const TOUR = [
  {
    target: "[data-tour='hero']",
    route: "#/home",
    title: "Start and stop everything here",
    text: "One button starts ComplianceWatch on this Mac and opens it. The same place stops it when you are done; your data is kept.",
  },
  {
    target: "[data-tour='pills']",
    route: "#/home",
    title: "See what is running",
    text: "These lights show each part at a glance: green is running, amber partly running, grey stopped, red needs attention.",
  },
  {
    target: "[data-tour='diagram']",
    route: "#/home",
    title: "How the parts connect",
    text: "Each box is a part of ComplianceWatch, coloured as it runs. Choose one to start or stop it on its own.",
  },
  {
    target: "[data-tour='palette']",
    route: "#/home",
    title: "Find any action",
    text: "Press ⌘K and type what you want, like backup or check. Every action says what it does and whether it is safe before it runs.",
  },
  {
    target: "[data-tour='guide']",
    route: "#/home",
    title: "Help in plain words",
    text: "The Guide explains each part, has step-by-step recipes with buttons that do the work, and lists what this app will never do. You can replay this tour from there.",
  },
];

// ---- flags in plain words ----------------------------------------------------------------------

export const PLAIN_FLAGS = {
  "applicability.fanout":
    "When a rule is published, decide it for every business at once (a fan-out), in batches, behind a hold.",
  "applicability.recompute":
    "When a business changes its profile, decide its rules again by itself.",
  "auth.mode":
    "How services check who is calling: a header (the local default), a sign-in token, or both.",
  "flags.provider": "Where flags are read from: .env on this Mac, or an Unleash server.",
  "identity.auth_provider": "Who signs people in: a fake provider on this Mac, or Supabase.",
  "identity.billing_provider":
    "Which billing provider starts subscriptions: none, a pretend one in memory, or Razorpay.",
  "llm_gateway.provider":
    "Which AI models answer: a fake model, or real ones through the Vercel AI Gateway (needs a key).",
  "mvp.worker_kafka": "The product's worker passes events on and reads the message queue.",
  "mvp.worker_temporal": "The product's worker runs the long Temporal jobs.",
  "notification.bulk": "A CA firm can send one change card to all its affected clients at once.",
  "notification.email": "Email is sent through an SMTP server.",
  "notification.whatsapp": "WhatsApp messages are sent.",
  "obligation.reminder_sweep":
    "Reminders go out 7, 3 and 1 days before a due date, and each day adds the next periods.",
  "obligation.rule_events":
    "A withdrawn, replaced or rescheduled rule changes the obligations it made.",
  "pipeline.crawl":
    "The pipeline reads the live regulator websites on a schedule. Off on this Mac.",
  "pipeline.extraction":
    "The pipeline asks the AI gateway to draft a rule from each new regulator document.",
  "pipeline.knowledge": "The pipeline hands documents to the rulebook and indexes their clauses.",
  "profile.gstin_category_prefill": "A business's category is filled in from its GSTIN lookup.",
  "profile.gstin_lookup":
    "How a GSTIN is looked up: by a person (a task), from a demo table, or from a provider.",
  "qa.kag": "Q&A reasons over the rulebook (its KAG layer) before it searches the clauses.",
  "rulebook.candidate_intake": "Rules the pipeline drafts land in the analysts' review queue.",
  "rulebook.publish": "Rule versions can be published and withdrawn.",
  "web.admin_rulebook_writes": "The admin screens may save entity and relation decisions.",
  "web.analytics_enabled": "The web app records product events for people who agreed to analytics.",
  "web.otel_enabled": "The web app sends traces (OpenTelemetry).",
  "web.publish_actions": "The rule version page shows the review and publish buttons.",
  "web.qa_enabled": "The web app shows the Ask screen.",
  "web.tenant_header_off": "The web app stops sending the tenant header, once tokens carry it.",
  "whatsapp_bot.consent_recording": "The WhatsApp bot records opt-ins and opt-outs as consents.",
  "whatsapp_bot.send": "The WhatsApp bot's replies are really sent.",
};

/** Plain words for the parts the status names, used by the pills and the Home diagram. */
export const PART_WORDS = {
  docker: { title: "Docker", short: "Docker", icon: "container" },
  infra: { title: "Databases and queues", short: "Databases", icon: "database" },
  services: { title: "Services", short: "Services", icon: "server" },
  web: { title: "Web app", short: "Web", icon: "globe" },
  product: { title: "The product", short: "Product", icon: "package" },
};
