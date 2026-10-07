-- Dev stack only: each service role of roles.sql gets its own name as its password, which is what
-- make run, make worker, make relay, make seed and make web-stack STORE=postgres connect with.
-- These are placeholders, not secrets, like the superuser's cw/cw in .env.example: they guard a
-- database on a developer's machine that holds synthetic data only. A deployment never runs this
-- file; it sets each role's password from its secret store (infra/deploy/README.md).
--
-- Run after roles.sql, by make db-roles and by the postgres image on a fresh volume. Safe to
-- repeat: it sets the same values again.

ALTER ROLE cw_identity PASSWORD 'cw_identity';
ALTER ROLE cw_profile PASSWORD 'cw_profile';
ALTER ROLE cw_rulebook PASSWORD 'cw_rulebook';
ALTER ROLE cw_applicability PASSWORD 'cw_applicability';
ALTER ROLE cw_obligation PASSWORD 'cw_obligation';
ALTER ROLE cw_notification PASSWORD 'cw_notification';
ALTER ROLE cw_qa PASSWORD 'cw_qa';
ALTER ROLE cw_llm_gateway PASSWORD 'cw_llm_gateway';
ALTER ROLE cw_eval PASSWORD 'cw_eval';
ALTER ROLE cw_pipeline PASSWORD 'cw_pipeline';
