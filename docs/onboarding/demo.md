# Five-minute demo

What to show a pilot business or a CA firm, in the order the product works. Everything runs
on a laptop with no accounts; the rules are the seed calendar, every one of them a draft
awaiting analyst review, so the demo is about the flow, not the numbers.

## Before

```bash
make install
make demo            # one process, no Docker: prints the transcript below in a few seconds
```

For the fuller version with the services running: `make dev`, `make migrate`, then
`make run SERVICE=profile` (and identity, notification) in separate terminals and replay the
same calls with curl against `localhost:8002`, `8001` and `8006`.

## Minute 1: consent and onboarding

`make demo` records four consents for the owner (terms, privacy notice, profile processing,
WhatsApp reminders) under the draft notice version, then registers the business by GSTIN. The
GSTIN lookup (static demo provider) pre-fills the registration type, status, constitution and
registration date; the owner answers the remaining questions until `next-question` is empty.
Point out: the consent record carries the notice version, so a changed notice means asking
again; a missing lookup provider opens a `verify_registration` task instead of guessing.

## Minute 2: which rules apply

Each seed rule's predicate tree is evaluated against the profile snapshot (entity attributes
inherited by the registration, per-financial-year turnover band). The transcript lists what
applies, what does not, and what is unsure (a missing attribute never becomes a silent no).
Point out: `seed_status: needs_review` and the TODO questions on every rule in
`services/rulebook/seed/gst_calendar.yaml`; nothing reaches a customer before an analyst
confirms it against the cited notification.

## Minute 3: the calendar

The obligation service materialises two periods per recurring rule (GSTR-1, GSTR-3B, the
annual return where the turnover band asks for it) with due dates at the end of the day in
IST, idempotent on (business, rule version, period): run it again and nothing duplicates.
Point out: a deadline extension notification later reschedules the open period
(`obligation.rescheduled`), it never creates a second obligation.

## Minute 4: the reminder

The first obligation is sent as a WhatsApp reminder in Hindi (the owner's preferred language),
through a fake channel in the demo and through the Cloud API once the Meta account exists.
Point out: the message ends with the HELP/STOP line; STOP typed back is honoured before
anything else; reminders are held during quiet hours (21:00 to 08:00 IST) and go out at 08:00.

## Minute 5: where it goes from here

- The pipeline fetches the real notifications (`make backfill SERVICE=pipeline ARGS="--source cbic_notifications --limit 3"`), parses them and the extractor drafts rule candidates behind the gateway; the eval harness (`make eval`) gates changes to that prompt.
- The web app and the CA multi-client view are the next product slices; the review workbench is where analysts approve the drafts shown above.
- What needs the maintainer: the accounts (Meta, Razorpay, GSTIN lookup, Supabase Auth, Vercel AI Gateway), a lawyer's review of `docs/legal`, and the analysts' review of the seed calendar and the extraction labels.
