# Consent record

> Draft - to be reviewed by a lawyer. The schema is implemented in the identity service; the
> wording of purposes is what needs review.

Version: 0.1-draft

A consent record is written whenever a person agrees to, or withdraws from, a purpose. Records
are append-only: a withdrawal is a new record with `granted: false`, never an edit. The latest
record per subject and purpose is the current state.

There are two kinds. A **consent record** belongs to a tenant: what a signed-in user, or a
number a tenant knows, agreed to. A **channel consent** belongs to no tenant: what a phone
number asked for by writing a keyword to the WhatsApp number, before anyone has an account.

## Consent records (`consent_record`)

| Field | Meaning |
| --- | --- |
| `consent_id` | Unique id |
| `tenant_id` | The tenant the subject belongs to (row-level security) |
| `subject` | Who consented: a user id, or an E.164 phone number |
| `purpose` | One of `terms`, `privacy_notice`, `profile_processing`, `whatsapp_reminders`, `email_reminders`, `analytics` |
| `notice_version` | The version line of the notice or terms the person saw (required when granting) |
| `granted` | true for consent, false for withdrawal |
| `source` | `web_onboarding`, `whatsapp_keyword`, `api`, `support` |
| `recorded_at` | When we recorded it (UTC) |
| `evidence` | Free text: the checkbox label shown, the keyword received, the support ticket |
| `recorded_by` | The user or system component that wrote it |

API, with the tenant in `x-tenant-id`: `POST /v1/identity/consents` records a consent, or a
withdrawal with `granted: false`; `GET /v1/identity/consents?subject=...` lists the current
state per purpose with the history. Granting without a `notice_version` is refused.

## Channel consents (`channel_consent`)

A person who writes START to the WhatsApp number opts in to WhatsApp reminders, and STOP opts
out. When `WHATSAPP_CONSENT_RECORDING_ENABLED` is on in the WhatsApp bot (it stays off until the
keyword question in [README.md](README.md) is answered), each keyword is recorded here:

| Field | Meaning |
| --- | --- |
| `id` | Unique id |
| `channel` | `whatsapp` |
| `subject` | The phone number in E.164 form without the plus, as WhatsApp reports it |
| `purpose` | `whatsapp_reminders`, the only purpose a WhatsApp keyword answers for |
| `granted` | true for START, false for STOP |
| `source` | `whatsapp_keyword` |
| `notice_version` | The version of [whatsapp-consent.md](whatsapp-consent.md) the opt-in prompt refers to (required when granting) |
| `evidence` | `keyword <K> in WhatsApp message <id> at <time>, language <en or hi>` |
| `message_id` | WhatsApp's id of the message; the same message delivered twice returns the first record instead of writing a second |
| `recorded_at` | When we recorded it (UTC) |

There is no tenant, so there is no row-level security. The rows are reached only through two
routes that need the bot's service token: `POST /v1/identity/channel-consents` and
`GET /v1/identity/channel-consents/{channel}/{subject}`. The table refuses UPDATE and DELETE.
An opt-in takes effect only once its record exists; an opt-out takes effect at once, and its
record is written afterwards on a best-effort basis.

A channel consent stays the keyword evidence of what that number asked for. The tenant user's
own `whatsapp_reminders` consent is a separate consent record, written when the user signs up
on the web. Nothing links a channel consent to a consent record, and no such link is promised.

Open for the lawyer: whether an erasure request must remove a number's channel consents, which
today cannot be deleted, and whether a keyword opt-in on its own is valid consent.
