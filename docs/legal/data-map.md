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
| WhatsApp number or email address and its preference (opted in, source, language, quiet hours, the last time the number wrote to the business) | notification `channel_preference` | Send only to those who agreed; the last inbound time opens WhatsApp's 24-hour customer service window | Until opt-out + 30 days; the opt-out itself kept as its record [lawyer] | The address is the key; no name stored. No tenant and no row-level security: consent is recorded before the address is linked to a tenant. No sweep removes preferences yet |
| Email address that bounced for good or complained (address, reason, SES's bounce or feedback type, time) | notification `suppression` | Never write again to a mailbox that refused the mail, which also protects the sending reputation | Until support lifts it [lawyer] | No tenant and no row-level security: a suppression holds for every tenant. Written from SES's reports through SNS |
| Recipients (user id, role, language, digest choice, the CA firm's label, WhatsApp numbers and email addresses in order, the businesses each hears about and their labels) | notification `recipient`, `recipient_address`, `recipient_business` | Who hears about which business, on which address | Life of account + 30 days | Row-level security by tenant. Registering an address gives no consent |
| Address directory (channel, address, tenant id, recipient id) | notification `address_directory` | Find the tenant of an address: delivery receipts and the retention sweep | Removed with its recipient | No row-level security; every statement names the tenant |
| PAN, GSTIN, legal and trade names | profile `profile_node` | Identify the entity and its registrations | Life of account + 30 days | PAN of a proprietor is personal data |
| Profile attributes (state, category, turnover band, filing scheme, ...) | profile `profile_attribute`, `profile_version` | Applicability of rules | Life of account + 30 days | Versioned; history deleted with the account |
| Obligations and their status | obligation `obligation` | The calendar | Life of account + 30 days | |
| Obligation change history (due dates before and after, status, reason, the user who acted) | obligation `obligation_change` | Audit of every change to an obligation (ADR-015) | Life of account + 30 days | Append-only; a tenant erasure (not built yet) must set `app.erasure=on` and delete the change rows before the obligations |
| Evidence uploads | object store [not built] | Proof an obligation was met | Life of account + 90 days after deletion request | Audit trail assumption from the guide |
| Questions and answers | qa (not built) | Answer, improve, analyst review | Life of account + 30 days; anonymised eval cases indefinitely | Identifiers masked before any model call |
| Notification record (recipient, address, occasion, template, dedupe key, state, attempts, error, dispatch and provider message ids; sent, delivered, read and failed times) and the values its message is filled with (business name, obligation title, dates, steps) | notification `notification`, with its `work_index` entry | Never send one occasion twice; delivery receipts; answer a dispute about a missed reminder | 2 years (guide section 9) [lawyer]; the message values emptied after 30 days once it has gone out or ended | Row-level security by tenant (`work_index` has none and holds only the tenant id, times and the provider message id). The rendered text is not stored. A daily sweep at 03:00 IST applies both periods. Replaces the 90-day sent log of the earlier draft; counsel to confirm |
| Model call ledger (tenant id, feature, tokens, cost) | llm-gateway `llm_call` | Budgets and cost | 13 months | No prompt text |
| Technical logs and traces | observability stack | Security and operations | 90 days (logs), 30 days (traces) | IP addresses in access logs; GSTINs, PANs, Aadhaar numbers, phone numbers and email addresses masked on every log line where the patterns recognise them (a name, an address or free text is not masked); trace spans are not masked |
| Billing customer and subscription ids, plan, quantity and status | identity `billing_customer`, `billing_subscription`, `billing_start` (billing, behind a flag) | Charging for the service | Life of account + 8 years for tax records [lawyer] | Card data never touches us; the payment provider holds it. Row-level security by tenant. Draft - to be reviewed by a lawyer |
| Billing contact's email address and name | identity `billing_customer` | Sent to the payment provider with the subscription; the provider bills and writes to this contact | Life of account + 8 years for tax records [lawyer] | Stored in plain text, one row per tenant; also held by the payment provider under its own terms. Removed only by a tenant erasure, which identity does not run yet. Draft - to be reviewed by a lawyer |
| Payment provider webhooks (event kind, time and id; the subscription's, payment's and invoice's ids, plan, status, quantity, times, amounts and currency; the tenant id and plan key from the subscription's notes) | identity `billing_event` | Proof of what the provider reported and when; dedupe of redeliveries | Life of account + 8 years for tax records [lawyer] | Only this allowlisted projection is kept, masked for personal identifiers, never the body: names, email addresses, phone numbers, UPI ids, addresses and card or bank details are dropped before storing. Append-only; a tenant erasure (not built yet) must set `app.erasure=on` to delete them. Draft - to be reviewed by a lawyer |

Data residency: the design assumes the Mumbai region (ap-south-1) for every store; Meta and
the payment provider process outside it under their own terms. Email stays off
(`CW_EMAIL_ENABLED`) until a sending domain in the region is verified with SES or another SMTP
provider.

Cross-border model processing (Draft - to be reviewed by a lawyer): every call the llm-gateway
makes to a real model sends text outside India, since no model it routes to runs inference in
India. The text is regulator documents and, for an answer, the user's question with its evidence,
with GSTINs, PANs, Aadhaar numbers, phone numbers and email addresses masked first where the
patterns recognise them; a name or another detail in a question's free text is not. The providers
are asked to retain nothing (zero data retention), and the traces of the calls hold the same masked
text. `CW_LLM_RESIDENCY=india_only` stops every such call and keeps the text out of the traces;
log lines and trace spans still go wherever their collectors run. Whether the product runs that
way, or keeps the calls and says so, is open (ADR-020).
