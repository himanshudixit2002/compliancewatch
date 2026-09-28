import { detectIntent, detectLanguage } from "./consent.ts";
import { reply } from "./replies.ts";
import type { InboundMessage } from "./webhook.ts";

/** What the conversation needs from the outside world; faked in tests. */
export interface PreferencesClient {
  setOptIn(phone: string, optedIn: boolean, language: "en" | "hi"): Promise<void>;
  isOptedIn(phone: string): Promise<boolean>;
}

export interface Sender {
  sendText(to: string, body: string): Promise<void>;
}

export interface QaClient {
  ask(phone: string, question: string): Promise<string | null>;
}

export interface Deps {
  readonly preferences: PreferencesClient;
  readonly sender: Sender;
  readonly qa: QaClient;
}

export interface Handled {
  readonly intent: string;
  readonly replied: string;
}

/**
 * One inbound message in, one reply out. Opt-out is honoured before anything else and never
 * needs an opt-in first; a question from someone who has not opted in gets the opt-in prompt.
 */
export async function handleInbound(message: InboundMessage, deps: Deps): Promise<Handled> {
  const language = detectLanguage(message.text);
  const intent = detectIntent(message.text);
  let body: string;
  switch (intent) {
    case "opt_out":
      await deps.preferences.setOptIn(message.from, false, language);
      body = reply("opt_out_confirmed", language);
      break;
    case "opt_in":
      await deps.preferences.setOptIn(message.from, true, language);
      body = reply("opt_in_confirmed", language);
      break;
    case "help":
      body = reply("help", language);
      break;
    default: {
      if (!(await deps.preferences.isOptedIn(message.from))) {
        body = reply("opt_in_needed", language);
        break;
      }
      const answer = message.text === null ? null : await deps.qa.ask(message.from, message.text);
      body = answer ?? reply("not_connected", language);
    }
  }
  await deps.sender.sendText(message.from, body);
  return { intent, replied: body };
}
