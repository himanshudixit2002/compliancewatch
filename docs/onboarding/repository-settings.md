# Repository settings

Some rules live in GitHub's settings rather than in files: which checks a merge needs, how pull
requests merge, and which security features are on. The repository owner applies them with the
`gh` commands below, authenticated as the owner (`gh auth login`). Each command sets a value, so
running it again is harmless. The last section lists what is still to decide.

The commands name the repository `himanshudixit2002/compliancewatch`; change that one path if
the repository moves.

## Merging: squash only, and the pull request title becomes the commit

Commits on `main` carry one short Conventional Commits subject and no body or trailers. Squash
merging alone would still put the branch's commit list and any `Co-authored-by` lines into the
body, so the title and message are set as well:

```bash
gh api -X PATCH repos/himanshudixit2002/compliancewatch -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=BLANK
gh api -X PATCH repos/himanshudixit2002/compliancewatch \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true
```

The pr-checks workflow checks the title ("Conventional Commit PR title"), so a title that would
make a bad commit cannot merge.

## Branch protection on main

A merge into `main` needs three checks: `CI gate` (ci.yml; it needs every other CI job and passes
only when each one succeeded or was skipped), `Conventional Commit PR title` and
`CODEOWNERS resolves` (both pr-checks.yml). The branch must be up to date with `main`, history
stays linear, and nobody can force-push or delete the branch, the owner included. `app_id` 15368
is GitHub Actions, so only a workflow job can report these checks.

```bash
gh api -X PUT repos/himanshudixit2002/compliancewatch/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      { "context": "CI gate", "app_id": 15368 },
      { "context": "Conventional Commit PR title", "app_id": 15368 },
      { "context": "CODEOWNERS resolves", "app_id": 15368 }
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
gh api repos/himanshudixit2002/compliancewatch/branches/main/protection \
  --jq '{checks: [.required_status_checks.checks[].context], linear: .required_linear_history.enabled, force_pushes: .allow_force_pushes.enabled}'
```

No review is required while the repository has a single owner, since GitHub does not let an
author approve their own pull request. Add `required_pull_request_reviews` with
`require_code_owner_reviews` once a second maintainer or GitHub teams exist (see `CODEOWNERS`).

No other CI job is required on its own. A job that the path filters skip reports as skipped,
which GitHub counts as passed, and the integration jobs are named after their matrix target, so
a list of required jobs would be both leaky and stale. `CI gate` turns every result into one
check. A new job in ci.yml goes into the gate's `needs`, and `make ci-gate-check` (in
`make check` and the ops job) fails until it does, so the branch protection above never needs to
change.

In an emergency the owner can lift the rule for themselves with
`gh api -X DELETE repos/himanshudixit2002/compliancewatch/branches/main/protection/enforce_admins`
and restore it afterwards with the same path and `-X POST`.

## Security features

```bash
# Dependabot alerts, and Dependabot security updates (pull requests for vulnerable dependencies).
# Version updates are configured in .github/dependabot.yml.
gh api -X PUT repos/himanshudixit2002/compliancewatch/vulnerability-alerts
gh api -X PUT repos/himanshudixit2002/compliancewatch/automated-security-fixes

# Secret scanning, and push protection, which refuses a push that contains a known secret format.
# gitleaks covers the same ground in pre-commit and CI; these also catch pushes that skip hooks.
gh api -X PATCH repos/himanshudixit2002/compliancewatch --input - <<'EOF'
{
  "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" }
  }
}
EOF

# Private vulnerability reporting: the "Report a vulnerability" button that SECURITY.md sends
# reporters to.
gh api -X PUT repos/himanshudixit2002/compliancewatch/private-vulnerability-reporting

# Check
gh api repos/himanshudixit2002/compliancewatch --jq .security_and_analysis
gh api repos/himanshudixit2002/compliancewatch/private-vulnerability-reporting --jq .enabled
```

Code scanning needs no setting on a public repository: the alerts appear once the sast and
dependency-scan jobs upload their first SARIF files (Security tab, Code scanning).

## Secrets and variables

```bash
# The nightly evals call a real model through this Vercel AI Gateway key. gh prompts for the
# value, so it never appears in the shell history. Until it is set the evals job exits green
# with a note in its summary.
gh secret set CW_AI_GATEWAY_API_KEY
```

Later, once a staging URL exists, the nightly API scan that arrives with the deployable stack
reads the repository variable `CW_DAST_TARGET_BASE`:
`gh variable set CW_DAST_TARGET_BASE --body https://<staging host>`. Nothing reads it yet.

## Still to decide: licence and visibility

The repository is public, while `LICENSE` reserves all rights: anyone can read the code, and
the licence grants no right to use it. The owner chooses between:

- keeping it public under the current licence;
- making it private (`gh repo edit himanshudixit2002/compliancewatch --visibility private
  --accept-visibility-change-consequences`). Code scanning, secret scanning and push protection
  on a private repository need GitHub Advanced Security. Without it the SARIF upload steps of
  the sast, dependency-scan and dependency-rescan jobs fail, and they would have to be removed
  or allowed to fail;
- publishing under an open source licence, which replaces `LICENSE`.
