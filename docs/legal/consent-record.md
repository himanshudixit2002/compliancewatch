# Consent record

> Draft - to be reviewed by a lawyer. The schema is implemented in the identity service; the
> wording of purposes is what needs review.

Version: 0.1-draft

A consent record is written whenever a person agrees to, or withdraws from, a purpose. Records
are append-only: a withdrawal is a new record with `granted: false`, never an edit. The latest
record per subject and purpose is the current state.

| Field | Meaning |
| --- | --- |
| `consent_id` | Unique id |
| `tenant_id` | The tenant the subject belongs to (row-level security) |
| `subject` | Who consented: a user id, or an E.164 phone number for a WhatsApp keyword opt-in before the number is linked to a user |
| `purpose` | One of `terms`, `privacy_notice`, `profile_processing`, `whatsapp_reminders`, `email_reminders`, `analytics` |
| `notice_version` | The version line of the notice or terms the person saw (required when granting) |
| `granted` | true for consent, false for withdrawal |
| `source` | `web_onboarding`, `whatsapp_keyword`, `api`, `support` |
| `recorded_at` | When we recorded it (UTC) |
| `evidence` | Free text: the checkbox label shown, the keyword received, the support ticket |
| `recorded_by` | The user or system component that wrote it |

API: `POST /v1/identity/consents` records; `GET /v1/identity/consents?subject=...` lists the
current state per purpose with history; `POST /v1/identity/consents/withdraw` records a
withdrawal. Granting without a `notice_version` is refused.
