# Settings

The settings pages of a tenant user: the index, the consents, the notification preferences and
billing. They are the registry entries `owner.settings`, `owner.settings.consents`,
`owner.settings.notifications` and `owner.settings.billing`; the session facts and signing out
are on `/account` (`account.home`). The client-level detail of each call is in
[data-layer.md](data-layer.md) under "Consents", "Notification preferences" and "Billing".

| Page                      | Who                                                   | Calls                                                                                              |
| ------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `/settings`               | every tenant member role                              | none: the list comes from the screen registry                                                      |
| `/settings/consents`      | every tenant member role                              | identity consents (read, append); the WhatsApp preference (set) when WhatsApp reminders change     |
| `/settings/notifications` | every tenant member role                              | notification preference per channel and recipient (read, replace), templates, identity consents |
| `/settings/billing`       | `owner`, `ca_admin`                                   | identity billing plans (read), subscriptions (start)                                              |

## The index: `/settings`

Linked from the header ("Settings"). It lists every settings page and account page the session
may open, from the registry in navigation order, each with its status as words (Available,
Ready to build, Waiting for a backend, No backend scheduled) and one sentence on what it is for. Pages not built yet
are listed too, and their links lead to the notice naming the route they wait for: data rights
and team (identity work), activity (the audit trail), and for a CA admin the webhooks, API keys
and digests, which no one has scheduled. Billing is listed only for the roles that may open it.
Every settings page shares a header: breadcrumbs back to Settings, the h1, and tabs for the
settings pages that are built.

## Consents: `/settings/consents`

What the signed-in user agreed to, from `GET /v1/identity/consents?subject=<user id>`:

- One row per purpose with its latest record: given or withdrawn, the notice version
  (`<document>@<Version line>`), when in IST, and the source. Every record follows, oldest first:
  records are append-only, so nothing here edits or deletes one.
- The required purposes (terms, privacy notice, profile processing) are shown, not changed:
  withdrawing them ends the service, and the page points to the data rights request, which is
  waiting for its identity routes.
- The optional purposes (WhatsApp reminders, email reminders, product analytics) can be given or
  withdrawn. A confirm dialog says exactly what is recorded (a new record with `granted` true or
  false, the source, the time); no reason is asked, because the route takes none.
- A change is one new record: `source` is `web_onboarding` (the identity service has no settings
  source yet), a grant carries the current notice version, a withdrawal the version of the grant
  it withdraws, and the evidence is `Confirmed on the settings page: ` with the sentence the
  dialog showed. A change that is already the state records nothing and says so.
- WhatsApp reminders also move the number (D-031). A withdrawal opts the number out on the
  notification service first, then records the withdrawal, so a failure leaves reminders
  stopped; with no number known it records the withdrawal alone. Giving records the consent,
  then opts the number in. A CA firm has no WhatsApp row.
- While onboarding is closed in production (a required legal document still a draft; see
  [legal-pages.md](legal-pages.md)), giving is refused and withdrawing still works.

## Recipients remembered on this device

The identity service does not return a user's own phone number or email address yet (`GET
/v1/identity/me` is awaited), so the pages remember the recipients the user last named on this
device in `cw_prefs_recipient`: an httpOnly cookie encrypted under the session key and bound to
the user id (another user on the same browser reads it as empty), path `/`, 30 days, expired at
sign-out. The consent step writes the WhatsApp number it opts in; the settings actions write a
number or address they use; pages only read it. The path is the whole site because the consent
step posts to `/onboarding`: a cookie scoped to `/settings` would not reach it, and its write
would replace a remembered address with the number alone. A preference is keyed by the recipient as
the notification service keys it: a WhatsApp number as digits without the plus, an address in
lower case.

## Notifications: `/settings/notifications`

One section per channel, WhatsApp then email, for the remembered recipient; without one the
section asks for it (E.164 with the plus, or an address) and remembers it. Each section shows
the recorded preference (`GET /v1/notification/preferences/{channel}/{recipient}`; a 404 means
nothing was ever recorded, and the form starts from the service's defaults) and whether the
user's consent to that channel's reminders is on file.

- Reminders on or off, the language (those the channel has templates in, English first, named
  in words), and the quiet hours in IST.
- Quiet hours: a reminder due in the window is held and sent when it ends. A window may run past
  midnight (22:00 to 07:00); the same start and end means no quiet hours. Nothing recorded starts
  from the service's default, 21:00 to 08:00. Both ends are always sent, because the service keeps
  a window only when both arrive.
- `savePreference` replaces the preference for the remembered recipient only (the form carries
  no recipient field, so it cannot be aimed at another number), with `source: web_onboarding`.
  It refuses to switch reminders on while the channel's consent (`whatsapp_reminders` or
  `email_reminders`) is not granted, because the notification service does not check it (D-032);
  opting out, the language and the quiet hours are never held back.
- The email section says that the notification service does not deliver email yet: a preference
  is recorded all the same and applies once the channel is connected.
- A number opted in by writing START on WhatsApp shows as opted in, with a note when the web
  consent is not on file.

## Billing: `/settings/billing`

For the owner and the CA admin (`billing.manage`).

- The plans as the identity service states them (`GET /v1/identity/billing/plans`): the name,
  the amount in paise shown in rupees with its period, and the service's description. The web
  app decides no price; a zero amount is the service's placeholder and its description says so.
- Starting a subscription posts the plan, a billing email and a billing name
  (`POST /v1/identity/billing/subscriptions`). No card or bank detail is ever a field: the
  provider's checkout page takes payment.
- The answer is shown as it is (D-033): the subscription with its status, the provider's id, the
  start in IST and a link to the checkout page when one is returned; or, with no billing provider
  connected (`CW_BILLING_PROVIDER=none`, the default of `make web-stack` and CI), the 503
  `billing-disabled` as its own state: "Billing is not connected yet", nothing was started and
  nothing was charged, with the request id. `make web-stack BILLING=memory` starts identity with
  the in-memory provider for a demo.
- The route takes no Idempotency-Key, so the button is disabled while a submit is pending.

## Account: `/account`

The session's facts (display name, user id, tenant id and kind, roles, the second factor, the
sign-in provider, when the session began and expires in IST) with copy controls, and signing out (`POST /sign-out`, which expires
the session and the remembered recipients). The second-factor page waits for the identity work.

## Product events

When `web.analytics_enabled` is on and the person's analytics consent is current, a recorded
consent change emits `consent_changed` (the purpose and give or withdraw), a saved preference
`notification_preference_saved` (the channel and on or off, never the recipient) and a started
subscription `subscription_started` (the plan key). A withdrawal of the analytics consent stops
the next event. See [feature-flags.md](feature-flags.md).

## What waits

- The user's own phone number and email address, instead of the per-device memory: `GET
  /v1/identity/me`.
- A settings source for consent and preference records: `web_onboarding` is sent until the
  identity and notification services add one.
- Withdrawing the required consents: the data rights routes.
- Entitlements and usage on the billing page: the identity entitlements route.
- Team, activity, and a CA firm's webhooks, API keys and digests: listed on the index with the
  routes they wait for.
