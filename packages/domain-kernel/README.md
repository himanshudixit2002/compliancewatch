# domain-kernel

The vocabulary every domain layer imports: typed ids, value objects, the ontology model, the
predicate algebra with its three-valued evaluation, the status machines, the protocols the
infrastructure implements, the error family and the event envelope. Standard library only, no
aggregates, no I/O. Services build their aggregates on top of it and never the other way round.

Design reference: Project Foundation guide, sections 6, 11 and 13.

- **Owns:** everything under `src/domain_kernel`
- **Owning team:** Platform and Infrastructure (custodian)
- **Consumes:** n/a (`packages/ontology` depends on this package, not the reverse)
- **Emits / publishes:** n/a (library)

## Modules

| Module | Contents |
| --- | --- |
| `errors` | `DomainError` family with stable problem type slugs (`type_uri`, `title`, `detail`) |
| `ids` | `EntityId` and thirteen typed subclasses (`TenantId`, `BusinessId`, `RuleVersionId`, ...) |
| `operators` | `Operator` enum with `symbol`; the ordered, multi-value and set operator groups |
| `confidence` | `Confidence` in [0, 1], `REVIEW_THRESHOLD`, `CERTAIN` and `ZERO` |
| `periods` | `EffectivePeriod`: half-open date range with `contains` and `overlaps` |
| `citations` | `Citation`: clause reference, verbatim quote, verified flag |
| `channels` | `Channel`: WhatsApp and email |
| `dedupe` | `DedupeKey` and the notification key (rule version, business, channel) |
| `ontology` | `AttributeType`, `AttributeSource`, `AttributeDefinition`, `Ontology`, `ALLOWED_OPERATORS` |
| `predicates` | `Predicate`, `AllOf`, `AnyOf`, `Not`, `Applicability`, `PredicateResult`, `evaluate_predicate` |
| `status` | `RuleVersionStatus`, `ObligationStatus`, `ClosureReason`, `TransitionTable`, the two tables |
| `events` | `DomainEvent` envelope (`event_id`, `occurred_at`, `tenant_id`, `correlation_id`, `causation_id`) |
| `profiles` | `ProfileSnapshot`: one version of a profile's attributes |
| `documents` | `DocumentRef`, `DiscoveredDocument`, `RawDocument`, `Clause`, `ParsedDocument`, `RuleCandidate` |
| `rules` | `ObligationTemplate`, `RuleVersionSnapshot` (read model of a published version) |
| `decisions` | `ApplicabilityDecision` |
| `llm` | `CompletionRequest`, `CompletionResponse` |
| `notifications` | `RenderedMessage`, `DeliveryStatus`, `DeliveryReceipt` |
| `vectors` | `Vector`, `EmbeddedClause`, `ClauseFilter`, `ScoredClause` |
| `protocols` | `SourceAdapter`, `DocumentParser`, `RuleExtractor`, `PredicateEvaluator`, `NotificationChannel`, `LLMProvider`, `VectorStore`, `RuleReader`, `DecisionRepository`, `WorkflowHandle` |

Every value object is a frozen, slotted dataclass whose `__post_init__` validates and raises
`InvariantViolationError`. Enums are `StrEnum` with lowercase values.

## What lives elsewhere

- Aggregates (`Rule`, `RuleVersion`, `BusinessProfile`, `Obligation`, `ReviewTask`) and the
  concrete events belong to their services; the kernel holds read models and the envelope.
- The attribute YAML, its loader and the `ontology-validate` command are in `packages/ontology`.
  The kernel owns the model and the structural validation; that package adds its house rules.
- JSON schemas for events and API payloads are in `packages/contracts`.

## Predicate semantics

- A structured predicate compares one profile attribute with an expected value through the
  ontology: both sides are coerced to the attribute's canonical form first, and a disallowed
  operator or malformed value raises rather than producing a verdict.
- Evaluation is three-valued (`applies`, `not_applicable`, `unsure`). A free-text predicate is
  always unsure; so is a structured one whose attribute is missing from the profile.
- `AllOf` and `AnyOf` follow Kleene's strong logic: any `not_applicable` decides an `AllOf`,
  any `applies` decides an `AnyOf`, otherwise any `unsure` makes the result unsure. `AllOf(())`
  is `applies` and `AnyOf(())` is `not_applicable`. `Not` swaps the two decided outcomes and
  keeps `unsure`. There is no excluded middle: `AnyOf((s, Not(s)))` may be unsure.
- `is_satisfied_by` is true only for `applies`. `evaluate_with(leaf)` lets the engine replace the
  deterministic leaf with a model-backed one; `evaluate_predicate` is the deterministic leaf
  with a confidence and a reason attached.
- `Ontology.check_predicate` validates a predicate against the ontology before it is stored.

## Ontology mapping schema

`Ontology.from_mapping` takes the plain mapping a YAML file parses to:

```yaml
version: "0.1.0"          # semver
attributes:
  - key: turnover_band     # [a-z][a-z0-9_]*
    type: ordered_enum     # enum | ordered_enum | enum_set | boolean | integer | decimal | date | string
    source: user_input     # gstin_lookup | user_input | derived
    definition: One or two plain sentences.
    allowed_values: [...]  # enum kinds only; order is the rank for ordered_enum
    min: 0                 # integer and decimal only; int, or Decimal for decimal
    max: 100000
    since: "0.1.0"         # semver, optional
    example: 12            # optional, stored in canonical form
```

`min` and `max` feed the `minimum` and `maximum` fields; unknown keys, missing required keys,
wrong containers, duplicate keys and an example that does not coerce all raise
`OntologyDefinitionError` naming `attributes[i]`.

## How to run

- `uv run pytest packages/domain-kernel` from the repo root; add
  `--cov=packages/domain-kernel/src --cov-branch --cov-report=term-missing` for coverage.
- `HYPOTHESIS_PROFILE=dev` runs fewer property-test examples; the default `ci` profile is
  deterministic.
- `make py-lint py-typecheck importlint` runs ruff, mypy (strict, tests included) and the
  import-linter contracts that keep this package free of I/O frameworks.
