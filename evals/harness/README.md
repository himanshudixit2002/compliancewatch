# eval harness

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 8, 17 and 19.

- **Owns:** Runner, metrics and thresholds: context recall and precision, grounded-answer rate, citation correctness, extraction acceptance, applicability precision and recall, refusal accuracy, cost per feature
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** evals/golden; services/pipeline/prompts; Langfuse traces
- **Emits / publishes:** CI eval reports; a failing threshold blocks the merge or pages the AI team

## Layout

Flat for now; the in-repo eval harness is a Phase 1 deliverable (CI report), with the dashboard in Phase 3.

## How to run

`make eval` prints a notice until the harness lands in Phase 1.
