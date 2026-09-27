# ADR-006: No rule is published without human approval; two-person rule for high-impact

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Regulatory Intelligence, Regulatory Analysts, Core Product, AI Platform

## Context

The extractor turns regulator documents into rule candidates with a language model. The target
is that at least nine in ten candidates are approved without edits, which still leaves one in
ten that is wrong in some way, and a wrong rule fans out to thousands of businesses as
obligations with due dates. That is the highest-impact risk in the register. Regulator documents
are untrusted input, so an instruction hidden in a PDF must never become a published rule. At
the same time the classifier, the extraction prompts and the eval suite all need labelled data,
and the only people who can produce it are the analysts, whose hiring is already on the critical
path.

## Decision

A rule version cannot reach the published status without an approver identity in the audit log.
The rule is enforced in code and in the database, not by process: `RuleVersion.publish` refuses
without at least one verified citation and at least one approver, and the status transition is
guarded by a trigger. A rule tagged high-impact needs two different approvers. The workbench
shows the source and the extracted rule side by side, every edit is stored as a diff on the
review task, and every approval, edit and rejection becomes an eval case and a training label.
Before publication the analyst sees a dry-run count of affected businesses; after publication
the fan-out can be paused and rolled back, closing obligations with a reason. The analyst is
responsible for the decision and the head of Regulatory Intelligence is accountable for it.

## Consequences

- Extraction errors do not reach customers, and the quality number that matters is measured at
  the gate rather than estimated afterwards.
- Every review produces labelled data. Golden sets grow without a separate labelling effort, and
  a prompt change is judged against real analyst edits.
- Publication latency depends on people. Meeting the 24-hour target needs queue assignment by
  regulator and load, part-time reviewers, and an alert when the queue goes quiet.
- The workbench has to be fast (median under four minutes per rule) or the gate becomes the
  bottleneck the risk register warns about.
- Two-person approval slows high-impact rules, and the tag must be applied consistently; the
  second approval is enforced in code once the tag is set.
- Revisit only to allow automatic approval of a narrow class, for example date-only amendments,
  once the eval suite shows sustained acceptance above 99 percent on that class, and then with
  sampled review rather than none.
