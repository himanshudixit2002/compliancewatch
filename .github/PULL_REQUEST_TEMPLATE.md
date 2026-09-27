## Summary

-

## Risk

- What could break, who is affected, and how we would notice.

## Rollback

- How this change is reverted (feature flag, git revert + Argo sync, migration contract phase not yet run).

## Checklist (definition of done, guide section 19)

- [ ] Conventional Commit title; squash merge
- [ ] Tests at the right levels (unit / contract / integration / e2e) and README or runbook updated
- [ ] Contract and schema changes published with a changelog entry
- [ ] Feature flag created with owner and expiry; metrics and alerts added for the new path
- [ ] Eval cases added if the change touches a model path (prompt, retrieval, applicability)
