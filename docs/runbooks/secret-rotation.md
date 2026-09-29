# Secret rotation

Design reference: guide sections 16 (security and privacy) and 17 (environments). Which secret
each app holds is in `infra/deploy/README.md` (the environment matrix); this runbook says who owns
each one, how often it changes and how to change it without an outage. Nothing here has been
applied: the accounts and the secrets manager are the maintainer's to set up (the manager is
chosen with the hosting platform; until then the holders are the Fly apps' secrets, the Vercel
project's environment variables and the repository's Actions secrets).

## Rules

- Every environment has its own value of every secret. Staging and production never share one,
  and nothing from either is used on a laptop. Local values are placeholders from `.env.example`
  or made on the machine (`openssl rand -hex 32`); `.env` is git-ignored.
- Rotate on the cadence below, at once when a value may have been exposed (committed, pasted in a
  ticket or chat, printed in a log, sent to the wrong recipient), and when someone who could read
  it leaves. An exposure is also a security report (`SECURITY.md`).
- The cadences are this runbook's defaults. The owning team may shorten one, or follow the
  provider when it sets a shorter lifetime.
- Local and test secrets stay local: `CW_IDENTITY_DEV_CLIENT_SECRET` is refused outside local and
  test, and `CW_AUTH_PROVIDER=fake` is refused in production, so neither can be carried over by
  mistake.

## Inventory

Owners use the flag registry's names: platform, core-product, regulatory-intelligence,
ai-platform and identity-partner.

| Secret | Holders | Owner | Cadence | Procedure |
| --- | --- | --- | --- | --- |
| `CW_IDENTITY_SIGNING_KEYS` (ES256 keys of the access tokens) | identity | identity-partner | 90 days | [Identity signing keys](#identity-signing-keys) |
| Service client secrets: `CW_SERVICE_CLIENT_SECRET` (notification, pipeline, qa), `BOT_SERVICE_CLIENT_SECRET` (WhatsApp bot) | the caller; identity keeps only a SHA-256 | the caller's team, with identity-partner | 180 days | [Service client secrets](#service-client-secrets) |
| `CW_RULEBOOK_WRITE_TOKEN` | rulebook, pipeline, the web server (`CW_WEB_RULEBOOK_WRITE_TOKEN`) | regulatory-intelligence | 180 days, until token mode retires it | [Shared tokens](#shared-tokens-between-two-services) |
| `CW_RULEBOOK_REVIEW_TOKEN` | rulebook, the analyst workbench | regulatory-intelligence | 180 days, until token mode retires it | [Shared tokens](#shared-tokens-between-two-services) |
| `CW_IDENTITY_CHANNEL_TOKEN` (bot: `IDENTITY_SERVICE_TOKEN`) | identity, WhatsApp bot | core-product | 180 days, until token mode retires it | [Shared tokens](#shared-tokens-between-two-services) |
| `CW_NOTIFICATION_BOT_TOKEN` (bot: `NOTIFICATION_BOT_TOKEN`) | notification, WhatsApp bot | core-product | 180 days, until token mode retires it | [Shared tokens](#shared-tokens-between-two-services) |
| `CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN` | notification, the SNS subscription URL | core-product | 180 days | [Shared tokens](#shared-tokens-between-two-services) |
| `CW_SUPABASE_SERVICE_ROLE_KEY`, `CW_SUPABASE_JWT_SECRET` (legacy projects only); Supabase's own signing keys | identity; Supabase | identity-partner | 180 days | [Supabase keys](#supabase-keys) |
| Database role passwords (inside `CW_DATABASE_URL` per service, relay and worker; `CW_DQ_DATABASE_URL`) | every service with a schema; the Actions secret of the data-quality job | platform | 180 days | [Database role passwords](#database-role-passwords) |
| `CW_RAZORPAY_KEY_SECRET` (with `CW_RAZORPAY_KEY_ID`), `CW_RAZORPAY_WEBHOOK_SECRET` | identity | identity-partner | 180 days, once billing is on | [Provider keys](#provider-keys) |
| `CW_WHATSAPP_ACCESS_TOKEN` (bot: `WHATSAPP_ACCESS_TOKEN`), `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | notification, WhatsApp bot | core-product | 180 days, once WhatsApp is on | [Provider keys](#provider-keys) |
| `CW_AI_GATEWAY_API_KEY` | llm-gateway; the Actions secret of the nightly eval | ai-platform | 180 days | [Provider keys](#provider-keys) |
| `CW_LANGFUSE_SECRET_KEY` (with `CW_LANGFUSE_PUBLIC_KEY`) | llm-gateway | ai-platform | 180 days | [Provider keys](#provider-keys) |
| `CW_SMTP_PASSWORD` | notification | core-product | 180 days, once email is on | [Provider keys](#provider-keys) |
| `CW_PROFILE_GSTIN_LOOKUP_API_KEY` | profile | core-product | 180 days, once the HTTP lookup is on | [Provider keys](#provider-keys) |
| `CW_UNLEASH_API_TOKEN` | services that read flags through `py_common.flags` | platform | 180 days, once Unleash runs | [Provider keys](#provider-keys) |
| OTLP endpoint header, Kafka SASL credentials, Temporal client certificate | every service; relays and consumers; the pipeline worker | platform | 180 days, or the certificate's expiry | [Provider keys](#provider-keys) |
| `CW_WEB_SESSION_SECRET` | the web server | core-product | 180 days | [Web session secret](#web-session-secret) |

## Procedures

Each procedure ends the same way: check `/ready` on every app that changed, look for a rise in
`auth-token-invalid`, `service-token-unavailable` or 401 answers in the logs, and note the date of
the rotation next to the secret in the secrets manager.

### Identity signing keys

`CW_IDENTITY_SIGNING_KEYS` is a JSON list of keys: the first signs, and every key is published at
`/v1/identity/.well-known/jwks.json`. The other services cache that key set for an hour and fetch
it again at once, at most every 30 seconds, when a token names a key they do not hold (ADR-014's
addendum). A scheduled rotation publishes the new key before it signs:

1. Make the key: `identity-admin signing-key new --kid <yyyy-mm>` prints a key set with one key.
   Join it to the current set as the second entry, for example
   `jq -c -s '.[0] + .[1]' current.json new.json`, and delete both files afterwards.
2. Set the joined set on identity and deploy it. `GET /v1/identity/.well-known/jwks.json` now
   lists both `kid`s; tokens are still signed with the old key.
3. Wait at least an hour, so every service's cache holds the new key.
4. Swap the order (new key first) and deploy identity. New tokens carry the new `kid`; tokens
   signed with the old key keep verifying.
5. Wait at least the longest token lifetime plus the leeway (`CW_ACCESS_TOKEN_TTL_SECONDS` and
   `CW_SERVICE_TOKEN_TTL_SECONDS`, 600 by default, plus 30 seconds), then set the new key alone
   and deploy identity.

When the private key may have leaked, do not wait: make a new key, set it alone and deploy
identity, then restart every other service so its cached copy of the old key is dropped (on Fly,
`fly apps restart <app>`). Every session ends; people sign in again and services fetch new service
tokens by themselves.

### Service client secrets

A client has one secret, and a client id is never reused, so a rotation creates a new client for
the caller:

1. `identity-admin service-client list` shows the caller's client and its scopes.
2. `identity-admin service-client create --id <caller>-<yyyy-mm> --scope <scope> ...` with the same
   scopes. It prints the secret once.
3. On the caller, set `CW_SERVICE_CLIENT_ID` and `CW_SERVICE_CLIENT_SECRET` (the bot:
   `BOT_SERVICE_CLIENT_ID` and `BOT_SERVICE_CLIENT_SECRET`) to the new pair and deploy it. Its log
   lines now name `service:<caller>-<yyyy-mm>` as the actor.
4. When its calls succeed, `identity-admin service-client revoke --id <old id>`. Tokens the old
   client already holds expire within `CW_SERVICE_TOKEN_TTL_SECONDS`.

When the secret may have leaked, revoke the old client first. The caller's calls then fail with
`service-token-unavailable` (503) until it has the new pair; stop the pipeline worker for that
window, so its activities do not use up their retries.

### Shared tokens between two services

The rulebook's write and review tokens, the bot's two tokens and the SES feedback token are shared
secrets, and the receiving service accepts one value at a time. The first four open routes only
while `CW_AUTH_MODE` is `header` or `dual`: once an environment runs `token`, the callers' access
tokens replace them, so unset them there instead of rotating them. The SES feedback token stays in
every mode, because SNS cannot send an access token.

1. Make the value: `openssl rand -hex 32`. The write and review tokens must differ.
2. For the write token, stop the pipeline worker first: a rulebook write refused with 401 is not
   retried, and the document stays unregistered (`registered=False` in the ingest result).
3. Set the value on the receiving service and deploy it, then on every caller and deploy them.
   Between the two deploys the callers get 401: the workbench shows the refusal, the bot fails an
   opt-in closed and logs `consents: 401` (`docs/runbooks/whatsapp.md`), and delivery statuses are
   not forwarded. Start the pipeline worker again once it has the new value.
4. For `CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN`, replace the SNS subscription with one whose URL
   carries the new password (`docs/runbooks/notification-delivery.md`) right after the
   notification deploy. Bounces and complaints that arrive in between are refused, so keep the two
   steps close together.

### Supabase keys

Identity uses the project's service-role key for the admin API (invitations, the internal tenant's
first admin) and verifies sign-in tokens against the project's published signing keys.

- **Service-role key.** Create a new secret key for the project in its API key settings, set it
  as `CW_SUPABASE_SERVICE_ROLE_KEY` on identity and deploy, then delete the old key. A project
  still on the legacy keys can only replace them by changing its legacy JWT secret, which also
  ends every Supabase session; check Supabase's documentation for the current behaviour and plan
  that as a maintenance window.
- **Signing keys.** Supabase rotates its asymmetric signing keys in the project settings, with the
  next key published before it signs. Identity fetches the project's key set again when a token
  names a key it does not hold, so nothing changes on our side. `CW_SUPABASE_JWT_SECRET` is needed
  only while the project signs with its legacy HS256 secret; remove it once asymmetric keys are on.

### Database role passwords

1. Change the role's password in the database provider's console, or as the owner with
   `ALTER ROLE <role> PASSWORD '<new>'` (from a session whose statements are not logged).
2. At once, set the new `CW_DATABASE_URL` on every app that connects as that role (the service,
   its relay and its worker) and deploy them. Connections already open keep working; new ones with
   the old password fail until the deploy.
3. For the data-quality role, update the `CW_DQ_DATABASE_URL` Actions secret.

### Provider keys

For Razorpay, WhatsApp, the AI gateway, Langfuse, SMTP, the GSTIN lookup provider, Unleash, the
OTLP header, Kafka and Temporal the pattern is the same, and the provider's own console is where
the new value comes from:

1. Create the new key, token or certificate at the provider, next to the old one where the
   provider allows two.
2. Set it on every holder in the inventory and deploy them (and update the Actions secret where
   one is listed).
3. Revoke or delete the old one at the provider.

Where the provider replaces the value in place (a reset app secret, a regenerated webhook secret),
requests signed with the old value are refused until the holder is deployed: set the new value
right after the reset. For WhatsApp, the manual steps in `docs/runbooks/whatsapp.md` name each
value; after changing `WHATSAPP_VERIFY_TOKEN`, verify the webhook again in the app dashboard.

### Web session secret

`CW_WEB_SESSION_SECRET` encrypts the web app's session cookie (ADR-019). Set a new value
(`openssl rand -base64 32`) on the web project and redeploy it. Cookies made with the old value
can no longer be read, so everyone signed in to the web app signs in again; rotate outside
working hours.
