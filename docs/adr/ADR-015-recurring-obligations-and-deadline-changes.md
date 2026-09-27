# ADR-015: Recurring obligations are materialised per period; deadline changes reschedule open obligations

- **Status:** Proposed
- **Date:** 2026-09-28
- **Deciders:** Core Product, Regulatory Intelligence, Regulatory Analysts

## Context

Most GST duties are not one-off. Returns are filed every month or every quarter depending on
the scheme a registration is under, annual returns once a financial year, and reconciliation
statements once a year above a turnover threshold. The regulator also moves dates: a
notification extends a due date for one period, corrects an earlier one, or withdraws a duty.
(The concrete forms, frequencies and dates are seed data in the rulebook, cited to their
notifications and marked for analyst review; this record is about the shape, not the facts.)

The domain today models one obligation per (business, rule version), idempotent on that pair,
with a template that carries `due_in_days`. That fits "display your certificate" and misses
"file this return every month", and it has no way to say that the September period's date
moved while October's did not. The knowledge model has relation kinds for supersession,
amendment, deadline extension, reference and exemption between rule versions (ADR-017); it
lacks correction and withdrawal.

Alternatives: one obligation per rule that the business ticks off repeatedly (loses the
period, the audit trail and the per-period reminders); generating every future period at
publication time (unbounded rows, and every deadline change touches them all); leaving
recurrence to the notification scheduler (hides a domain concept in infrastructure).

## Decision

A rule version may carry a `Recurrence`: a frequency (monthly, quarterly, annual), the day of
the period-following month the duty is due on, an optional offset, and the financial-year
alignment (India's financial year runs April to March). The kernel owns the value object and
the arithmetic that turns a recurrence and a date into the period it belongs to and the due
date of that period; the arithmetic is property-tested.

The obligation service materialises recurring obligations per period, idempotent on
(business, rule version, period), inside a rolling window (the current period and the next
one), by a scheduled job that runs daily and whenever a rule is published or a profile changes.
A materialised obligation records its period, so reminders, status and evidence are per period
and the audit log reconstructs each one.

Deadline changes are rule versions with a typed relation to the rule they change:
`extends_deadline` moves the due date of the named period for open obligations and emits
`obligation.rescheduled` with the old and new dates and the causing rule version;
`corrects` replaces what an earlier version said (dates, predicates, template) from its
effective date, rescheduling or re-evaluating as needed; `withdraws` closes open obligations
with reason `rule_withdrawn`. The relation kinds `corrects` and `withdraws` join the kernel's
`RelationKind`, both targeting a rule version only, and the rulebook's check constraint widens
accordingly. Every change writes an audit row and a notification template exists for each of
the three outcomes.

A change never edits history: an obligation whose period has passed keeps its original due
date and status; only open obligations in affected periods move.

## Consequences

- Businesses see one obligation per period with its own reminders and evidence, and a moved
  date arrives as a change with the notification that caused it, which is what a CA firm needs
  to show a client.
- The rolling window bounds the table size; a period is created at most twice (once per
  window entry, deduplicated by the idempotency key).
- The kernel's `RelationKind` grows to seven kinds; the extractor must recognise the language
  of extensions, corrections and withdrawals, and the seed calendar carries `TODO` questions
  where the analyst must confirm a frequency or a date rather than the engineer guessing.
- The scheduled materialisation job is a Temporal workflow on the worker scaffold; if it
  falls behind, the freshness alert fires before a due date is missed.
- Revisit if a regulator's duties are mostly event-driven (a filing within N days of an
  event) rather than periodic; the template's `due_in_days` still covers those.
