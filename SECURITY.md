# Security

ComplianceWatch handles business identifiers and tax data, so a security problem here is a
product problem. Please report anything you find privately.

## How to report

- Do not open a public issue or pull request for a vulnerability.
- Report it through GitHub private vulnerability reporting: open the repository's Security tab
  and choose 'Report a vulnerability'. The report is a draft security advisory that only you and
  the maintainer can see; the discussion and the fix stay in it until the advisory is published.
- Include what you found, where (file, endpoint, environment), how to reproduce it, and what
  you think the impact is. A proof of concept is welcome; exploiting real data is not.

## What to expect

- Acknowledgement within 3 working days.
- An assessment and a fix or a plan within 14 days for anything rated high or critical, and
  within 30 days for the rest.
- Credit in the release notes if you want it. There is no bug bounty.

## Scope

- The code in this repository, its container images and the GitHub Actions workflows.
- Deployed environments once they exist; until then there is nothing running outside local
  machines.
- Out of scope: the third-party services the product talks to (regulator websites, model
  providers, messaging providers). Report those to their owners.

## Supported versions

Only the `main` branch is supported. Fixes land there and ship with the next deployment.

## Secrets

No real secret belongs in this repository. `.env.example` holds placeholders only, gitleaks
runs in pre-commit and CI, and a leaked key is rotated as soon as it is noticed. If you find
one, treat it as a vulnerability and report it the same way.
