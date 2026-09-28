# Relation golden set

Expected relations per document for the relation stage (`extraction.rule_relations`, KAG
phase 2, ADR-017). A case names the extraction case that holds the document's clauses, the
document's own number, and the relations an analyst expects:

```yaml
case_id: 01-2026-central-tax
label_status: draft            # draft, reviewed or approved; an analyst moves it on
own_ref: 01/2026-Central Tax
extraction_case: extraction/cbic_notifications/cases/01-2026-central-tax.yaml
expected:
  relations:
    - relation: extends_deadline          # one of the seven RelationKind values
      target: {type: form, name: GSTR-3B} # entity type and canonical name, as the grammar names it
      evidence_clause_ref: en.p3
      evidence_quote: ...                  # copied exactly from the clause
      period: "2026-03"                    # extends_deadline only; else omit
      new_due_date: "2026-04-21"           # extends_deadline only; else omit
```

The harness (`make eval`) runs each case through the mention grammar and the relation stage and
compares candidates with the label on (relation, target type, target name). Every case here is
a draft until an analyst reviews it; the CI gates run on the scripted and fake providers only,
and the nightly relation numbers are reported, not gated, until at least five cases are
reviewed.
