# Rulebook data quality

What to do when the nightly `data-quality` job fails (the nightly issue then carries the label
`data-quality`) or `make data-quality` reports violations. Owner: Regulatory Intelligence. The
checks are in `services/rulebook/src/rulebook/domain/quality.py`.

## How it works

- `rulebook-quality` reads every rule version with its citation counts and open analyst
  questions, and every relation between rule versions, on a read-only connection. It runs five
  checks and prints each with up to 10 samples (`--json` for the same as JSON). Exit code 0 is
  clean, 1 means at least one violation, 2 means the database could not be read.
- `make data-quality` points it at the local stack's `rulebook` schema, or at
  `CW_DQ_DATABASE_URL` when that is set.
- The nightly workflow (`.github/workflows/nightly.yml`, job `data-quality`) runs it on a fresh
  Postgres after `make migrate SERVICE=rulebook` and `make seed SERVICE=rulebook`, or, when the
  repository secret `CW_DQ_DATABASE_URL` exists, on that database. The run summary lists the
  count per check and the artifact `data-quality-report` holds the JSON report.

The checks never change data. Every fix below is an analyst's decision against the cited
instrument, recorded through the review flow where one exists; a fix by SQL is reviewed by a
second person and noted in the issue.

## A check failed

### in_force_without_verified_citation

A published or superseded version has no citation, or a citation that is not verified. Every
citation must be verified before publication (ADR-006), so the version went out without that
check. An analyst compares each unverified quote with its clause text and verifies it, or adds
the missing citation; a version that cannot be cited is withdrawn. Never set `verified` without
reading the clause.

### overlapping_in_force_periods

Two published or superseded versions of one rule are in force on the same dates, usually
because the older version was not closed when the newer one took over. The analyst reads both
instruments and sets the older version's `effective_to` to the date the newer one starts, if the
instruments say so; the check treats periods as `[from, to)`, so the two dates may be equal.

### supersession_cycle

Versions replace each other in a loop over `supersedes` and `corrects` edges, so no version is
the latest. The sample lists the versions in order. Approval refuses a supersession that would
close a loop, so the edge came from a correction or from a write outside the review flow. The
analyst checks each edge's evidence clause and removes the wrong one.

### unknown_predicate_attribute

A version's specification names an attribute the packaged ontology does not define, or cannot
be read. Either the ontology changed (an attribute was renamed or removed in a new version) or
the rule was written against an attribute that never existed. The analyst rewrites the
predicate on an existing attribute, or proposes the attribute for the next ontology version. A
free-text predicate may keep a new attribute while the decision is open, if the version carries
the question in its `todo` list (the seed's ITC-04 rules do). Resolve a finding by adding such a
question, or by fixing the predicate; never by loosening the check.

### effective_dates_disordered

A version ends on or before it starts. `ck_rule_version_effective` refuses such a row, so a
violation means the constraint is missing or the row was loaded around it. Check the constraint
(`\d rulebook.rule_version` in psql), restore it with the migration, and ask the analyst for the
correct dates.

## The job fails with exit code 2

The database could not be read: the local stack is down (`make dev`), the migrations have not
run, or the `CW_DQ_DATABASE_URL` secret is wrong or its role lacks a grant. The job prints
`data quality: cannot read the rulebook` and the error class.

## A read-only role for CW_DQ_DATABASE_URL

On the deployed database, as its owner (placeholders in angle brackets):

```sql
CREATE ROLE cw_data_quality LOGIN PASSWORD '<a new password>';
ALTER ROLE cw_data_quality SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA rulebook TO cw_data_quality;
GRANT SELECT ON rulebook.rule, rulebook.rule_version, rulebook.citation, rulebook.rule_relation
  TO cw_data_quality;
```

Then add the repository secret `CW_DQ_DATABASE_URL` as
`postgresql+psycopg://cw_data_quality:<password>@<host>:<port>/<database>`. The command sets the
search path to `rulebook` itself.

## Local checks

```bash
make dev
make migrate SERVICE=rulebook
make seed SERVICE=rulebook
make data-quality              # or ARGS=--json
```

The seed calendar is clean: every version is a draft, and the ITC-04 rules' free-text
predicate carries its analyst question.
