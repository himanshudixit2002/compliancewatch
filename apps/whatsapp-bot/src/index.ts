import { serve } from "@hono/node-server";
import { createApp } from "./app.ts";
import { identityTokenSource } from "./auth.ts";
import {
  CloudApiSender,
  DEFAULT_NOTIFICATION_API_URL,
  HttpPreferencesClient,
  LoggingSender,
  NotConnectedQa,
  consentLedger,
  receiptsClient,
} from "./clients.ts";

const env = process.env;
const port = Number(env.PORT ?? 8080);
const sendEnabled = env.WHATSAPP_SEND_ENABLED === "true";
const sender =
  sendEnabled && env.WHATSAPP_PHONE_NUMBER_ID && env.WHATSAPP_ACCESS_TOKEN
    ? new CloudApiSender(
        env.WHATSAPP_PHONE_NUMBER_ID,
        env.WHATSAPP_ACCESS_TOKEN,
        env.WHATSAPP_API_VERSION ?? "v21.0",
      )
    : new LoggingSender();
// The bot's own access token: with BOT_SERVICE_CLIENT_SECRET set, BOT_SERVICE_CLIENT_ID (default
// whatsapp-bot) gets one from identity at IDENTITY_API_URL, and every call to notification and
// identity carries it. Without the secret no token is sent and the shared tokens alone apply.
const tokens = identityTokenSource(env);
// Keyword opt-ins and opt-outs are recorded with identity only when
// WHATSAPP_CONSENT_RECORDING_ENABLED=true; on, it needs IDENTITY_API_URL and
// IDENTITY_SERVICE_TOKEN or the service token.
const consentRecording = env.WHATSAPP_CONSENT_RECORDING_ENABLED === "true";
const consents = consentLedger(env, fetch, console.log, tokens);
// Delivery statuses and inbound times go to notification with NOTIFICATION_BOT_TOKEN or the
// service token; without either they are not forwarded, and the bot says so once at start.
const receipts = receiptsClient(env, fetch, console.warn, tokens);

const app = createApp(
  {
    verifyToken: env.WHATSAPP_VERIFY_TOKEN ?? "",
    appSecret: env.WHATSAPP_APP_SECRET ?? "",
    requireSignature: env.WHATSAPP_REQUIRE_SIGNATURE !== "false",
  },
  {
    preferences: new HttpPreferencesClient(
      env.NOTIFICATION_API_URL || DEFAULT_NOTIFICATION_API_URL,
      fetch,
      tokens,
    ),
    consents,
    sender,
    qa: new NotConnectedQa(),
  },
  receipts,
);

const server = serve({ fetch: app.fetch, port }, (info) => {
  console.log(
    `whatsapp-bot listening on http://localhost:${info.port} (send ${sendEnabled ? "enabled" : "disabled"}, consent recording ${consentRecording ? "enabled" : "disabled"}, service token ${tokens === null ? "off" : `for client ${tokens.clientId}`})`,
  );
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
  });
}
