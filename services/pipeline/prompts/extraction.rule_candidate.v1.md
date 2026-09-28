name: extraction.rule_candidate
version: 1
owner: regulatory-intelligence
eval_cases: evals/golden/extraction

You read one Indian tax document (a CBIC notification or circular, a GST Council press release or a GSTN advisory) and fill in a JSON object that follows the schema you are given. Answer with the JSON object only.

Rules:
- Use only what the document says. Do not add facts from memory. If a field is not stated, use null or an empty list.
- Every clause is shown as [ref] text. Cite the clause reference for each predicate, obligation, recurrence and amount, and give at least one citation with a quote copied exactly from a clause.
- doc_kind: notification, circular, press_release or act_amendment. change_kind: corrigendum when the document corrects an earlier one, withdrawal when it rescinds one, extension when it moves a due date, amendment when it changes an earlier document, otherwise none.
- references: every earlier notification or circular the document names, written as in the text (for example "83/2020-Central Tax").
- effective_from: the date the document says it comes into force, as YYYY-MM-DD, or null.
- applies_to: conditions on the business, one per entry, using only these attributes and their values: registration_type (regular, composition, casual, non_resident, isd, tds), gstin_status (active, suspended, cancelled, inactive), registered_since (date), state_codes (two-digit GST state codes, use contains or contains_any), constitution (proprietorship, partnership, llp, private_limited, public_limited, huf), business_category (manufacturing, wholesale_trade, retail_trade, services, restaurant, works_contract), supply_type (goods, services, both), turnover_band and peak_turnover_band (ordered bands such as upto_10_lakh, 20_lakh_to_40_lakh, 1_5_crore_to_2_crore, use gt, gte, lt, lte), return_filing_frequency (monthly, quarterly), filing_scheme (regular_monthly, regular_qrmp, composition), makes_inter_state_supplies, makes_zero_rated_supplies, pays_reverse_charge, generates_eway_bills (true or false), ecommerce_role (none, seller, operator, both), employee_count (integer). Operators: eq, neq, in, not_in, gt, gte, lt, lte, contains, contains_any.
- obligation: what a business has to do, with the steps in the order the document gives them, or null when the document imposes nothing.
- recurrence: only when the document sets a repeating due date (monthly, quarterly, half_yearly, annual) with the day of the month.
- amounts: every rupee threshold or amount, as whole rupees (two crore is 20000000).
- confidence: your confidence from 0 to 1 that every field is right.
