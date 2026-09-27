# legal

> Draft - to be reviewed by a lawyer. Nothing in this directory is in force or has been reviewed
> by counsel. Every document carries placeholders in square brackets for the facts only the
> company can supply (legal name, address, grievance officer).

Design reference: Project Foundation guide, section 16 (privacy under India's Digital Personal
Data Protection Act, 2023), and the architecture reference's privacy section.

| Document | Purpose | Consumed by |
| --- | --- | --- |
| [privacy-notice.md](privacy-notice.md) | What personal data ComplianceWatch collects, why, for how long, and the rights of the person | Onboarding (web), the notice version recorded on every consent |
| [terms-of-service.md](terms-of-service.md) | The service, what it is not (not legal or tax advice), accounts, fees, liability | Onboarding acceptance |
| [whatsapp-consent.md](whatsapp-consent.md) | The opt-in wording for WhatsApp reminders (English and Hindi) and how opt-out works | The bot's replies, Meta's template submissions |
| [data-map.md](data-map.md) | Every personal field, its purpose, retention and where it lives | The deletion pipeline, the privacy review in the definition of done |
| [consent-record.md](consent-record.md) | What a recorded consent contains and how it is queried and withdrawn | The identity service's consent API |

The notice and terms are versioned by the `Version:` line at the top; the identity service
stores that version with each consent, so a change to the wording is a new version and a new
consent, never a silent edit.

## Open questions for the lawyer

- Whether the company is a data fiduciary for the businesses' data and a data processor for a
  CA firm's clients, and what that changes in the notice.
- The retention period for evidence uploads after a deletion request (the guide assumes 90 days
  for the audit trail).
- The grievance officer's name and contact and the response time to publish.
- Whether WhatsApp opt-in by keyword alone is sufficient consent for reminders, or whether the
  onboarding checkbox is required first.
