/**
 * Session replies the bot sends inside the 24-hour customer service window (no Meta template
 * needed for a reply to an inbound message). Business-initiated reminders are rendered by the
 * notification service from its template registry, not here.
 */
export type Language = "en" | "hi";

const REPLIES: Record<string, Record<Language, string>> = {
  opt_in_confirmed: {
    en: "You will now receive ComplianceWatch reminders on WhatsApp. Reply STOP at any time to opt out.",
    hi: "अब आपको ComplianceWatch की याद दिलाने वाली सूचनाएँ WhatsApp पर मिलेंगी। बंद करने के लिए कभी भी STOP लिखें।",
  },
  opt_out_confirmed: {
    en: "You will not receive further ComplianceWatch messages on WhatsApp. Reply START to opt in again.",
    hi: "अब आपको ComplianceWatch के संदेश WhatsApp पर नहीं मिलेंगे। फिर से शुरू करने के लिए START लिखें।",
  },
  help: {
    en: "ComplianceWatch sends GST reminders for your business. Reply START to receive them, STOP to opt out, or ask a question about a filing.",
    hi: "ComplianceWatch आपके व्यवसाय के लिए GST की याद दिलाता है। पाने के लिए START, बंद करने के लिए STOP लिखें, या किसी फाइलिंग के बारे में पूछें।",
  },
  opt_in_needed: {
    en: "Reply START to receive ComplianceWatch reminders on this number.",
    hi: "इस नंबर पर ComplianceWatch की सूचनाएँ पाने के लिए START लिखें।",
  },
  try_again_later: {
    en: "We could not record your opt-in just now, so reminders are not switched on yet. Please send START again in a few minutes.",
    hi: "हम अभी आपकी सहमति दर्ज नहीं कर सके, इसलिए सूचनाएँ अभी शुरू नहीं हुई हैं। कृपया कुछ मिनट बाद फिर से START लिखें।",
  },
  not_connected: {
    en: "Questions are not answered on WhatsApp yet. Reply HELP for what this number can do.",
    hi: "अभी WhatsApp पर प्रश्नों के उत्तर नहीं दिए जाते। यह नंबर क्या कर सकता है, जानने के लिए HELP लिखें।",
  },
};

export function reply(key: keyof typeof REPLIES | string, language: Language): string {
  const entry = REPLIES[key];
  if (!entry) throw new Error(`unknown reply ${key}`);
  return entry[language] ?? entry.en;
}

export const REPLY_KEYS = Object.keys(REPLIES);
