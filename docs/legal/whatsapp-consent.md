# WhatsApp consent

> Draft - to be reviewed by a lawyer. Not in force. The Hindi wording is a first draft for the
> analysts to review.

Version: 0.1-draft

## What a person agrees to

By opting in, a person agrees to receive on their WhatsApp number: reminders about the GST
obligations of the business they registered, notices when a rule that applies to the business
changes, and replies to questions they send. Nothing else. No marketing.

## How consent is collected

1. **Onboarding (web).** A checkbox, unticked by default, next to the mobile number field:
   "Send me GST reminders for this business on WhatsApp. I can reply STOP at any time." The
   consent is recorded by the identity service with the notice version, the time and the
   source `web_onboarding`, and the notification service's preference for the number is set
   to opted in.
2. **Keyword (WhatsApp).** A person who writes START (or JOIN, SUBSCRIBE, YES, HAAN, हाँ, शुरू)
   to the business number is opted in from that message, source `whatsapp_keyword`. With the
   bot's `WHATSAPP_CONSENT_RECORDING_ENABLED` on, the identity service first records a channel
   consent for the number: the keyword, the message id, the time, the language and the version
   of this notice ([consent-record.md](consent-record.md)). The opt-in takes effect only once
   that record exists; if it cannot be written, the person is asked to try again later and is
   not opted in. The flag stays off until the question below is answered. The channel consent
   is the evidence of what the number asked for; the account holder's own consent is recorded
   separately at onboarding, and the two are not linked.
3. **Meta's own opt-in rules.** Business-initiated messages use templates Meta has approved;
   the templates are drafts in `services/notification` until the maintainer submits them.

## How consent is withdrawn

Reply STOP (or UNSUBSCRIBE, CANCEL, END, QUIT, BAND, BAND KARO, बंद, रोकें). The bot records the
opt-out before anything else happens and confirms it. With consent recording on, the
withdrawal is then also written as a channel consent; if that write fails the opt-out still
stands. No further business-initiated message is
sent to that number until it opts in again. Withdrawal is also possible from the web settings
page and by writing to the grievance officer.

## Wording

| Where | English | Hindi (draft) |
| --- | --- | --- |
| Onboarding checkbox | Send me GST reminders for this business on WhatsApp. I can reply STOP at any time. | इस व्यवसाय के लिए GST की याद दिलाने वाली सूचनाएँ मुझे WhatsApp पर भेजें। मैं कभी भी STOP लिखकर बंद कर सकता/सकती हूँ। |
| Opt-in confirmed | You will now receive ComplianceWatch reminders on WhatsApp. Reply STOP at any time to opt out. | अब आपको ComplianceWatch की याद दिलाने वाली सूचनाएँ WhatsApp पर मिलेंगी। बंद करने के लिए कभी भी STOP लिखें। |
| Opt-out confirmed | You will not receive further ComplianceWatch messages on WhatsApp. Reply START to opt in again. | अब आपको ComplianceWatch के संदेश WhatsApp पर नहीं मिलेंगे। फिर से शुरू करने के लिए START लिखें। |
| Opt-in not recorded (consent recording on, identity unavailable) | We could not record your opt-in just now, so reminders are not switched on yet. Please send START again in a few minutes. | हम अभी आपकी सहमति दर्ज नहीं कर सके, इसलिए सूचनाएँ अभी शुरू नहीं हुई हैं। कृपया कुछ मिनट बाद फिर से START लिखें। |
| Every reminder ends with | Reply HELP for help or STOP to opt out. | मदद के लिए HELP और बंद करने के लिए STOP लिखें। |

## Quiet hours

Reminders are not sent between 21:00 and 08:00 Indian Standard Time; a reminder due in that
window goes out at 08:00. A person can change the window in settings [when the settings page
exists].
