import { serve } from "@hono/node-server";
import { createApp } from "./app.ts";
import { CloudApiSender, HttpPreferencesClient, LoggingSender, NotConnectedQa } from "./clients.ts";

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

const app = createApp(
  {
    verifyToken: env.WHATSAPP_VERIFY_TOKEN ?? "",
    appSecret: env.WHATSAPP_APP_SECRET ?? "",
    requireSignature: env.WHATSAPP_REQUIRE_SIGNATURE !== "false",
  },
  {
    preferences: new HttpPreferencesClient(env.NOTIFICATION_API_URL ?? "http://localhost:8006"),
    sender,
    qa: new NotConnectedQa(),
  },
);

const server = serve({ fetch: app.fetch, port }, (info) => {
  console.log(
    `whatsapp-bot listening on http://localhost:${info.port} (send ${sendEnabled ? "enabled" : "disabled"})`,
  );
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
  });
}
