import { detectIntent, detectLanguage, normaliseKeyword } from "./consent.ts";
import { reply } from "./replies.ts";
import type { Language } from "./replies.ts";
import type { InboundMessage } from "./webhook.ts";

/** What the conversation needs from the outside world; faked in tests. */
export interface PreferencesClient {
  setOptIn(phone: string, optedIn: boolean, language: Language): Promise<void>;
  isOptedIn(phone: string): Promise<boolean>;
}

/**
 * Where a keyword opt-in or opt-out is kept as consent evidence (the identity service).
 * `record` rejects when the consent could not be recorded.
 */
export interface ConsentLedger {
  record(
    phone: string,
    granted: boolean,
    keyword: string,
    messageId: string,
    language: Language,
  ): Promise<void>;
}

export interface Sender {
  sendText(to: string, body: string): Promise<void>;
}

export interface QaClient {
  ask(phone: string, question: string): Promise<string | null>;
}

export interface Deps {
  readonly preferences: PreferencesClient;
  readonly consents: ConsentLedger;
  readonly sender: Sender;
  readonly qa: QaClient;
  /** Where a consent that could not be recorded is reported; console.error by default. */
  readonly log?: (line: string) => void;
}

export interface Handled {
  readonly intent: string;
  readonly replied: string;
}

/** The last four digits of a number, the rest masked, for log lines. */
export function maskNumber(phone: string): string {
  return phone.slice(-4).padStart(phone.length, "*");
}

/**
 * One inbound message in, one reply out. Opt-out is honoured before anything else and never
 * needs an opt-in first; a question from someone who has not opted in gets the opt-in prompt.
 *
 * Both keywords are recorded as consents. An opt-in is recorded first and takes effect only
 * once the record exists: without the evidence nothing is switched on, and the person is asked
 * to try again. An opt-out takes effect first, always; recording the withdrawal is best effort
 * and a failure is only logged.
 */
export async function handleInbound(message: InboundMessage, deps: Deps): Promise<Handled> {
  const language = detectLanguage(message.text);
  const intent = detectIntent(message.text);
  const keyword = normaliseKeyword(message.text ?? "");
  const log = deps.log ?? console.error;
  let body: string;
  switch (intent) {
    case "opt_out":
      await deps.preferences.setOptIn(message.from, false, language);
      try {
        await deps.consents.record(message.from, false, keyword, message.id, language);
      } catch (error) {
        log(
          `whatsapp-bot: opt-out of ${maskNumber(message.from)} honoured but not recorded: ${String(error)}`,
        );
      }
      body = reply("opt_out_confirmed", language);
      break;
    case "opt_in":
      try {
        await deps.consents.record(message.from, true, keyword, message.id, language);
      } catch (error) {
        log(
          `whatsapp-bot: opt-in of ${maskNumber(message.from)} not recorded, so not applied: ${String(error)}`,
        );
        body = reply("try_again_later", language);
        break;
      }
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
