# Data map

> Draft - to be reviewed by a lawyer and by the Platform team. Retention periods are the
> engineering assumptions from the design guide (section 16) until counsel confirms them.

Version: 0.1-draft

Every personal field, where it lives, why it is held and how long. "Deletion" means the
deletion pipeline that runs after `tenant.deletion.requested` (deadline 30 days).

| Field | Service and table | Purpose | Retention | Notes |
| --- | --- | --- | --- | --- |
| Account name, email, mobile | identity (users, via Supabase Auth per ADR-014) | Sign-in, contact | Life of account + 30 days after deletion request | Supabase project not yet created |
| Consent records (subject, purpose, notice version, time, source) | identity `consent_record` | Proof of consent and withdrawal | Life of account + 3 years [lawyer] | Kept after deletion as the record of the deletion itself, with the subject pseudonymised |
| WhatsApp number and its keyword opt-ins and opt-outs (number, keyword, message id, time, language, notice version) | identity `channel_consent` | Proof of what a number asked for before anyone has an account | [lawyer] | No tenant and no row-level security; append-only, so not removed by a deletion today; whether an erasure request must remove it is open. Written only with the bot's `WHATSAPP_CONSENT_RECORDING_ENABLED` on |
| WhatsApp number and preference (opted in, language, quiet hours) | notification (in memory until its migration) | Send reminders only to those who agreed | Until opt-out + 30 days; opt-out itself kept as a suppression record | Number is the key; no name stored |
| PAN, GSTIN, legal and trade names | profile `profile_node` | Identify the entity and its registrations | Life of account + 30 days | PAN of a proprietor is personal data |
| Profile attributes (state, category, turnover band, filing scheme, ...) | profile `profile_attribute`, `profile_version` | Applicability of rules | Life of account + 30 days | Versioned; history deleted with the account |
| Obligations and their status | obligation `obligation` | The calendar | Life of account + 30 days | |
| Obligation change history (due dates before and after, status, reason, the user who acted) | obligation `obligation_change` | Audit of every change to an obligation (ADR-015) | Life of account + 30 days | Append-only; a tenant erasure (not built yet) must set `app.erasure=on` and delete the change rows before the obligations |
| Evidence uploads | object store [not built] | Proof an obligation was met | Life of account + 90 days after deletion request | Audit trail assumption from the guide |
| Questions and answers | qa (not built) | Answer, improve, analyst review | Life of account + 30 days; anonymised eval cases indefinitely | Identifiers masked before any model call |
| Notification sent log (dedupe key, time, provider message id) | notification (in memory until its migration) | Never send one change twice; delivery receipts | 90 days | Contains no message text |
| Model call ledger (tenant id, feature, tokens, cost) | llm-gateway `llm_call` | Budgets and cost | 13 months | No prompt text |
| Technical logs and traces | observability stack | Security and operations | 90 days (logs), 30 days (traces) | IP addresses in access logs |
| Billing customer and subscription ids | identity (billing, behind a flag) | Charging for the service | Life of account + 8 years for tax records [lawyer] | Card data never touches us; the payment provider holds it |

Data residency: the design assumes the Mumbai region (ap-south-1) for every store; Meta and
the payment provider process outside it under their own terms.
