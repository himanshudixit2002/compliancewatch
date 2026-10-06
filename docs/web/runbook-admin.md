# Operator steps in the web app

What an admin does on the internal tools when a published rule is going wrong, or is about to:
hold every fan-out, pause or cancel one run, roll a version back, run a dry run first, settle a
decision the engine could not, and what a CA firm's bulk change card answers. The service-level
detail (the routes, the statuses, the Temporal workflow, what to check when a run does not move)
is in [`docs/runbooks/fan-out-control.md`](../runbooks/fan-out-control.md); this page is the same
work through the screens. [admin-tools.md](admin-tools.md) describes each screen and
[product-loop.md](product-loop.md) the loop they watch.

Every regulatory role reads these pages; only an admin sees a control (D-049). Each control asks
for a reason of ten characters or more, kept in the engine's or the rulebook's audit log.

## Hold every fan-out

Before anything that could make a whole fan-out wrong (a deploy of the engine or the ontology, a
rulebook data fix, an incident in the profile service):

1. Open **Fan-outs** (`/admin/fan-outs`) from the sidebar.
2. Choose **Hold every fan-out**, give the reason, confirm. The pages now lead with a red banner,
   "Every fan-out is on hold", with the reason, who set it and when. Running runs stop at their next
   batch boundary and show Held; a version published meanwhile waits before its first batch.
3. When done, **Release the hold** with a reason. Every held run carries on by itself; a run a
   person paused stays paused.

The engine records the hold and the release with the reason. Until identity issues tokens it
records them as `system:applicability-engine`, so say who you are in the reason.

## Pause, resume or cancel one run

1. Open the run from **Fan-outs** (its version's name). The page says its status in words, how
   many businesses it decided of how many, how many results flipped against the version it
   supersedes, and who changed it last and why.
2. **Pause** stops it at the next batch boundary until an admin resumes it; releasing the hold
   does not restart it. A run that paused itself on flips says so in its last change.
3. **Resume** decides the next batch at once (held again while the hold is set). Resuming a run
   that paused on flips turns the flip check off for the rest of the run, since you have seen them.
4. **Cancel the run** stops it for good. The decisions it made stay, and so do the obligations
   they made: to take them back, roll the version back.

A control the run's status does not allow is not offered; one refused anyway (the run moved on
meanwhile) shows the engine's problem and its correlation id under the controls.

## Roll a version back

Rolling back is the rulebook's withdraw, offered on a published version's fan-out page:

1. Read the warning: the version is withdrawn from today for every tenant; the engine cancels its
   run if it is still going; the obligation service closes every open obligation the version made,
   in every tenant, and tells their people; the decisions stay; nothing undoes it, and a corrected
   rule needs a new version through review.
2. **Roll back this version**, give the reason, confirm with **Withdraw the version**.
3. The page renders again: the version reads Withdrawn, and a run that had not finished reads
   Cancelled, by the system, with the withdrawal as its reason.
4. Check the effect: the rule version page shows the withdrawal; an obligation the version made
   reads "Closed when the rule was withdrawn" on its page, and its people get the withdrawal
   notice.

The rollback needs `web.publish_actions` on and `CW_WEB_RULEBOOK_REVIEW_TOKEN` set on the web
server; without either, the page says which and offers no button. Never roll back a seed rule on a
database others use: `make product-check --destructive` proves the rollback on CI's fresh database.

## Before publishing: a dry run

1. Open **Impact explorer** (`/admin/impact`), or "Dry run this version" on a fan-out page.
2. Give the version's id (any status), or a specification as the kernel's predicate tree in JSON
   with the level it is decided at; name a tenant to narrow it to that tenant's businesses.
3. Read the counts by result, the attributes that decided them and the sample decisions. Many more
   "Applies" or "Not sure" than the change should bring, or an attribute deciding what it should
   not touch, is the cue to return the version to draft.

A scope over the engine's maximum (`CW_APPLICABILITY_DRY_RUN_MAX`, 2,000 by default) is refused
with the way to narrow it. A dry run stores nothing but its audit entry.

## Settle a decision the engine could not

1. Open **Decision review** (`/admin/decisions`) and give the tenant's id (the review routes act
   for one tenant at a time).
2. Each open item shows the decision under review with every condition, and why it needs a person.
   A reviewer or an admin settles it: **It applies** or **It does not apply** appends a decision
   that the obligation service acts on; **Dismiss** closes the item and appends nothing. The note
   is kept with the item and in the audit log.

## A CA firm's bulk change card

On a change's affected clients (`/changes/[id]/impact`, linked from each change card for a CA
firm's people), the firm sends one change card to its affected clients' own people. Sending again
from the same page sends the same request: the service answers with its first answer and the page
says nothing was sent twice. If the page says bulk change cards are switched off, the notification
service runs with `CW_NOTIFICATION_BULK_ENABLED` off: nothing was sent; turn it on there.
