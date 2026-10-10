# Odoo MCP SaaS — Implementation checkpoint

Date: 2026-10-10
Branch: `feat/odoo-mcp-saas`
PR: https://github.com/marcelo-m7/anyapi/pull/3
Status: **Development only; not production ready.**
Plan: `docs/superpowers/plans/2026-10-10-odoo-mcp-saas-v1.md`

## Last green verification

- Commit: `04b52084740800c68329fe463997da5c18879290`
- Odoo MCP CI: https://github.com/marcelo-m7/anyapi/actions/runs/38091376208 — 100 passed
- Root AnyAPI CI: https://github.com/marcelo-m7/anyapi/actions/runs/38091376198 — success
- AnyAPI regression suite exercised in isolated CI: 5 passed
- PostgreSQL 17 runs as a disposable GitHub Actions service; no shared Supabase migration applied.

## Implemented

1. Independent `odoo_mcp/` Flask application, WSGI entrypoint and pinned uv dependencies.
2. Multi-tenant Odoo MCP SQL schema migration and private OAuth/credential schema; tenant-owned public RLS controls and PostgreSQL isolation tests.
3. Supabase Auth browser sign-in, encrypted session, CSRF and Odoo API key encryption.
4. Pinned-public-IP TLS, restricted Odoo JSON-2 interface with tests rejecting redirects, private hosts and unsafe response payloads.
5. Allowlisted read-only policy engine and four discovery/read tools.
6. Stateless MCP JSON-RPC HTTP handling with fail-closed authentication.
7. OAuth AS and resource metadata, Client ID Metadata verification, atomic one-use codes.
8. OAuth authorization-code PKCE consent/token/revoke HTTP routes, hashed opaque tokens, expiry, refresh rotation with token-family replay revocation.
9. Owner/server/connection/secret policy resolver `ContextResolver` with cross-tenant, audience and immediate policy-disable tests.

## Critical open integration and security gates

- The real production Flask MCP endpoint still intentionally has no `context_factory` or `authorizer` wired for Odoo tool calls; it rejects unauthorized calls. Do not remove this gate before audit and quota enforcement.
- Some OAuth endpoints are implemented but still require independent conformance and security review, including state/CSRF binding to consent, client ID metadata validity, redirect validation, session renewal, refresh-token family security, and issuer/resource handling.
- There is no completed owner management UI/CRUD for connections and model-level policies.
- Write tools are not implemented (the approved default read-only policy remains).
- Request-level quota service, persistently redacted audit log and production operational alerting are not yet implemented.
- Schema migration has been validated on temporary PostgreSQL, but NOT reconciled against nor applied to shared Supabase `aiosqtyvzopdtsolkpfg`; schema security/performance advisors have not been run on the live project.
- No independent Vercel project has been provisioned. The existing AnyAPI Vercel deployment is not a valid release target for Odoo MCP.
- No live Odoo 19 or ChatGPT OAuth/MCP end-to-end integration has been verified.
- Do not merge this Draft PR or enable public access until all release gates in the plan pass.

## Superpowers execution ledger (milestone)

- Tasks 1–6: locally implemented via GitHub and validated by separate CI; read-only MCP with simulated authenticated context.
- Tasks 7–8: OAuth discovery/code/token implementation and HTTP consent tests green in CI; needs comprehensive audit and real client interoperability.
- Task 9: `ContextResolver` tested independently; production wiring remains pending by design.
- Tasks 10–13: remaining.
- Ruling: keep live MCP access disabled until quotas, auditing and full auth-to-context binding tests are completed; cost is deferred public client interoperability.
- Ruling: apply Supabase migrations only after drift reconciliation and staging validation; cost is deferred database-backed preview.
- Ruling: remote GitHub Actions is the authoritative test environment because no authenticated private repository clone/worktree is available locally; an independent reviewer should repeat all tests and inspect the full diff.

## Immediate next tasks

1. Finish Task 9 production MCP grant context binding, with real OAuth Store and two-tenant negative tests and hard limits.
2. Implement Tasks 10–12 (owner CRUD/dashboard, opt-in bounded writes, audit and atomic rate quotas) via TDD.
3. Reconcile/apply only approved Supabase migration in staging, create separate Vercel project and verify Odoo + ChatGPT E2E.
4. Review the entire branch with explicit SSRF/OAuth/tenant/write-timeout adversarial cases, then request owner review. No automatic merge.

Environment note: The suggested Vercel connector is not yet confirmed connected; deployment operations through that service require the user to connect it.
