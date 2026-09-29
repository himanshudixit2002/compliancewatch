# Consumer contracts

What a consumer sends to a provider's HTTP API, and which parts of each answer it relies on,
recorded as files both sides test against. It is the consumer-driven contract idea without Pact:
the files live in this repository, and a broker is not needed while every consumer and provider
is built and tested here.

## Layout

```
consumers/
  <consumer>/<provider>.json
  whatsapp-bot/notification.json   # HttpPreferencesClient -> PUT and GET /v1/notification/preferences
  whatsapp-bot/identity.json       # HttpConsentLedger -> POST /v1/identity/channel-consents
```

A file names its `consumer` and `provider` and lists `interactions` in the order they happen.
Each interaction has a `description`, the exact `request` (`method`, `path`, `headers`, `body`)
and the `response` the consumer relies on: the `status` and a `body` that is a subset of what the
provider serves. Later interactions may depend on earlier ones, such as a read after a write or a
redelivered message.

## Who checks what

- **Consumer side:** the consumer's own test runs its real client against a fake transport that
  expects the recorded requests in order, fails on any difference, and answers with the recorded
  responses. For the bot: `apps/whatsapp-bot/src/contracts.test.ts`.
- **Provider side:** `services/<provider>/tests/contract/test_consumers.py` replays the requests
  in order against a fresh app with its memory stores, and requires each status to match and each
  recorded body to be a subset of the served one.

A change that breaks either side fails a test on that side. To change a contract, edit the file
and both tests in the same pull request. Values in the files are test values only: the service
token is the one each provider's `testing.py` configures (`identity.testing.CHANNEL_TOKEN`).

`turbo.json` lists `packages/contracts/consumers/**` as an input of the TypeScript tests, so a
changed contract reruns them. The Python tests run on every change under `packages/contracts/`.
