# Legal pages

How the web app shows the legal documents in `docs/legal`, how their versions reach the consent
records, why production onboarding is closed while they are drafts, and how they print. The
documents themselves, and the questions still open for a lawyer, are described in
[docs/legal/README.md](../legal/README.md). Nothing here is legal advice, and every document is a
draft until a lawyer has reviewed it.

## The pages: `/legal/[doc]`

Three documents are published, listed in `LEGAL_DOCS` (`apps/web/src/shared/config/legal-docs.ts`):
`privacy-notice`, `terms-of-service` and `whatsapp-consent`. The other files in `docs/legal`
(`data-map.md`, `consent-record.md`, the README) are internal notes and are not rendered. The
home page links the three, and the consent step links each one next to the box that refers to
it.

The page is public (`system.legal`). It is prerendered at build time from the three names
(`generateStaticParams`, `dynamicParams = false`), so any other name is a 404; `turbo.json` lists
`docs/legal/*.md` as a build input, so a changed document rebuilds the app.

## The loader: `server/legal.ts`

- `legalDir()` finds `docs/legal` from the working directory: the repository root, or
  `../../docs/legal` from `apps/web`, where `next build` and `next start` run.
- `readLegalDocument(name)` reads `<name>.md`, takes the title from the first `# ` heading and the
  version from the `Version:` line (`Version: 0.1-draft`), and renders the markdown with `marked`
  (GitHub tables included). `marked` does not sanitise: the directory is repository-owned, and a
  unit test fails when a published document contains a raw HTML tag, so only the markdown's own
  structure reaches the page.
- `readLegalVersions()` reads every published document's title and version without rendering,
  on each call (three small files). The consent step, the consents settings page and the
  analytics gate call it at request time, so a consent records the version the running build
  ships.

## The draft banner

While a document's version ends in `-draft`, the page opens with the fixed banner "Draft - to be
reviewed by a lawyer" and the version; once the version is a reviewed one (`1.0`), a plain
version line replaces it. The consent step shows the same banner, naming each draft it refers to
with its version, because that is what a record will carry.

## What a consent records

Every consent record carries `notice_version` as `<document>@<Version line>`
(`privacy-notice@0.1-draft`): the documents share version numbers, so the version alone could not
say which one was agreed to (D-026). Each purpose refers to one document (`PURPOSE_DOCUMENT` in
`features/consents/model/purposes.ts`): the terms to `terms-of-service`; the privacy notice,
profile processing, email reminders and analytics to `privacy-notice`; WhatsApp reminders to
`whatsapp-consent`. A new Version line therefore makes the consent step ask again for the
purposes that refer to that document and for nothing else; a new privacy notice version also
stops the product events until the analytics consent is given again at that version.

## Onboarding is closed in production while a required document is a draft

Nobody should agree to a draft in production. `onboardingGate()` in `server/legal.ts` closes
onboarding when `CW_WEB_ENV` is `prod` and any required document has a Version line ending in
`-draft` (D-035). The required documents (`REQUIRED_LEGAL_DOCS`) are the ones the required
purposes refer to, the terms and the privacy notice; a unit test holds the list to
`PURPOSE_DOCUMENT`. The WhatsApp notice covers an optional purpose and closes nothing.

| When closed                    | What happens                                                                                    |
| ------------------------------ | ----------------------------------------------------------------------------------------------- |
| `/onboarding`                  | The step's heading, the draft banner, each draft with its version and link, no form             |
| `/onboarding/business`         | The same notice, no form                                                                        |
| `recordConsents`               | Refuses before any call: "Onboarding is closed until the legal documents are reviewed"          |
| `createBusiness`               | Refuses before any call, with the same message                                                  |
| `changeConsent` on the settings page | Refuses to give a consent; a withdrawal is always recorded                               |

Local, test and staging stay open, with the draft banner, so the flow can be built, tested and
reviewed before the wording is approved. The questions, the summary and the business pages stay
open, because they change a business that already exists. The e2e suite runs with
`CW_WEB_ENV=test` and never sees the closed state; the unit tests cover it (`server/legal.test.ts`,
the consent and business actions, `shared/ui/onboarding-closed.test.tsx`).

Production onboarding opens with the release that carries the reviewed Version lines. No flag or
setting opens it earlier.

## Printing

`apps/web/src/app/globals.css` carries a print stylesheet, written for these pages first:

- the shell's header (product name, navigation, user menu) and the skip link are left out, and
  the content takes the page's width;
- every colour role falls back to the paper's system colours (black on white), whatever scheme
  the screen uses, because browsers drop backgrounds when printing;
- the draft banner stays, with a border, so a printed draft still says it is one;
- a line shown on paper only names the document and its version ("Printed from ComplianceWatch:
  Privacy notice, version 0.1-draft.");
- inside a document, a link to another site is followed by its address, a table row is not split
  across pages, and a heading stays with the text after it.

`e2e/legal.spec.ts` prints the privacy notice in the light and the dark scheme and checks the
shell is gone, the banner and the paper line are there, and the text is black on white.

## Deployment

The pages are prerendered, but the onboarding steps, the consents settings page and the
analytics gate read `docs/legal` when a request arrives. `next start` from the repository finds
the directory; an image or a Vercel deployment must ship `docs/legal` with the app (Next's
`outputFileTracingIncludes`, or a copy step), or those pages fail with the loader's "docs/legal
not found" error.

## Adding or changing a document

1. Write `docs/legal/<name>.md` with a `# ` title and a `Version:` line (`0.1-draft` until a
   lawyer has reviewed it), markdown only, no raw HTML.
2. Add `{ name, title }` to `LEGAL_DOCS` in `shared/config/legal-docs.ts`; the page, the home
   links and the sitemap pick it up.
3. If a consent purpose refers to it, map the purpose in `PURPOSE_DOCUMENT`, and add the document
   to `REQUIRED_LEGAL_DOCS` when the purpose is required.
4. A reviewed wording is a new Version line (`1.0`), never an edit under the old one: the
   records keep the version they were given under, and the consent step asks again.
