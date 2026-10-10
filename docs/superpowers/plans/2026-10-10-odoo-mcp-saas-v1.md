# Odoo MCP SaaS V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Deliver an isolated, multi-tenant hosted Odoo 19 MCP SaaS in the existing AnyAPI GitHub repository, sharing the existing Supabase project without changing AnyAPI behaviour, with OAuth, restricted read tools, explicit write opt-in and a Vercel preview that has passed real integration gates.

**Architecture:** A dedicated Flask application rooted at odoo_mcp/ is deployed as its own Vercel project. Browser identities use Supabase Auth and owner-scoped RLS; MCP callers use distinct OAuth-issued, audience-bound opaque tokens backed by private SQL storage. Every Odoo JSON-2 operation is constrained by the union of transport safeguards, tenant policy, OAuth grant and Odoo's own ACL/record rules.

**Tech Stack:** Python 3.12+, Flask 3.x, requests/httpx transport chosen for safe TLS/DNS pinning, Authlib (OAuth protocol validation), psycopg 3 (private transactional OAuth storage), cryptography (encrypted Odoo secrets), jsonschema, pytest, Supabase Postgres/Auth/PostgREST, Vercel Python WSGI, uv lockfile.

**Spec:** docs/superpowers/specs/2026-10-10-odoo-mcp-saas-design.md

## Global Constraints

- Approved architectural option A: independent Odoo MCP product derived from AnyAPI, deployed separately, sharing Supabase project aiosqtyvzopdtsolkpfg.
- Implement from branch feat/odoo-mcp-saas based on main commit 4e58e596b6ee8fa40cddaf7ddc29f7dc6816b01b. The existing AnyAPI PR #2 is unrelated and must not be merged as part of this work.
- Do not modify main.py or existing anyapi/ application files; leave the AnyAPI dashboard, generic endpoints, and database tables alone. Add a dedicated CI workflow without weakening existing CI.
- The **separate Vercel project root directory is odoo_mcp/**, containing app.py (exported Flask app), pyproject.toml, uv.lock and internal mcp_saas package. The existing main AnyAPI Vercel project retains its root configuration.
- One tenant = one Supabase Auth user. All owner-facing tables have owner_id and RLS; OAuth codes/tokens and Odoo key ciphertext are **private and not browser-accessible**.
- Odoo 19 external JSON-2 only in V1; legacy XML-RPC/JSON-RPC is outside this plan. Restrict supported instances to those whose permitted external API is reachable.
- MCP transport: Streamable HTTP, stateless, JSON-RPC, 2025-11-25 negotiation and spec-compatible fallback; no in-memory sessions, WebSockets or SSE requirement. Authentication is OAuth access token, never browser session cookies.
- Implement OAuth 2.1-compatible code + PKCE S256 and OAuth resource/auth server metadata; strict resource audience; short-lived hashed opaque tokens; replay-safe transaction handling. Confirm client registration mechanism against real client; add secure DCR only if required to meet the ChatGPT interoperability gate.
- Default read-only. Read tools: odoo_list_models, odoo_get_model_schema, odoo_search_records, odoo_get_record. Write tools: odoo_create_record and odoo_update_record only when explicitly enabled, scoped per model/field. Never expose raw ORM method execution, unlink/delete, modules or administrative models.
- Defaults: 20 records/page, maximum 100 records/page, maximum 10 records per write call, maximum 15 seconds for each execution but strictly below observed Vercel runtime limits. Apply bounded payload and response sizes. Never automatically retry writes.
- Dedicated encryption key distinct from session key and Supabase credentials. Do not include Odoo business payloads or secrets in persisted audit logs.
- Use pytest RED -> GREEN -> refactor for each task; run the entire new test suite AND the pre-existing AnyAPI suite before moving to the next task. Do not report success from an individual test alone.
- Generate, inspect and reconcile migrations against the live Supabase migration history (currently includes 20261010123943 through 20261010140853; PR #2 affected those versions) and test in disposable/staging Postgres before any shared-project application. Never reset Supabase production.
- Before implementation: human reviews THIS PLAN and chooses an execution method. Treat all task checkboxes below as pending until then.

## Review Focus

These input conditions must be tested even if they are absent from happy-path fixtures; they are referenced by owning tasks:
1. DNS rebinding/private-IP and 30x redirects when validating an Odoo host — Task 4 must fail closed before any upstream request.
2. A forged nested server/connection ID accessed via service credentials — Tasks 2, 3 and 9 must fail owner/server constraints.
3. OAuth authorization code replay, refresh-token rotation race and mismatched resource — Tasks 7 and 8 must reject atomically.
4. Odoo allowed records containing sensitive relational fields or a specially crafted domain/context — Task 5 must minimize and reject.
5. Write transport timeouts after uncertain remote commit — Task 11 must not retry automatically and must report indeterminate outcome.

## Dependency map and package structure

The service code below lives exclusively inside odoo_mcp/ (except the explicitly named new .github workflow); relative paths in subsequent tasks are under this directory. Use the following stable interfaces, or adjust the plan **before starting Task 1**, not ad hoc in different tasks.

- mcp_saas/settings.py: Settings.from_env() -> Settings with explicit, validated ODOO_MCP_* environment variables; never log secret fields.
- mcp_saas/app_factory.py: create_app(settings: Settings | None = None, dependencies: dict | None = None) -> Flask.
- mcp_saas/store.py: TenantStore(user_jwt: str).get_owned_connection(owner_id: str, connection_id: str) -> dict | None, TenantStore.get_owned_server(owner_id: str, server_id: str) -> dict | None; methods insert/update/list for tenant-owned records; use authenticated PostgREST RLS.
- mcp_saas/private_store.py: PrivateStore(db_dsn: str), using parameterized psycopg transactions for secrets and OAuth state only; operations always explicitly include owner_id/server_id. It must not expose a generic execute endpoint.
- mcp_saas/credentials.py: CredentialsService.encrypt_key(plaintext: str) -> str, decrypt_key(ciphertext: str) -> str; version key and test rotation.
- mcp_saas/network.py: assert_safe_odoo_url(url: str) -> str and PinnedHttpsTransport.post_json(url: str, headers: dict, payload: dict, timeout_s: int) -> object; verify that the *actual TLS peer* matches public resolved IP and hostname, fail closed if unavailable.
- mcp_saas/odoo_json2.py: OdooJSON2.call(connection: dict, api_key: str, model: str, method: str, args: dict) -> object and probe_connection(...) -> dict; API methods from strict allowlist.
- mcp_saas/policies.py: PolicyEngine.authorize(server: dict, policies: list[dict], granted_scopes: set[str], action: str, model: str, fields: list[str]) -> AuthorizedOperation; validate_filter(...) -> list and sanitize_records(...) -> list[dict].
- mcp_saas/tools.py: ToolRegistry.list_tools(context: ToolContext) -> list[dict] and ToolRegistry.invoke(context: ToolContext, name: str, arguments: dict) -> dict; ToolContext includes owner_id, server_id, scopes, policies, connection and an OdooJSON2 adapter; never trusts caller-supplied tenant IDs.
- mcp_saas/mcp_http.py: dispatch_rpc(context: ToolContext, message: dict) -> tuple[dict | None, int] and blueprint /mcp/<public_id>; HTTP transport must delegate auth to AuthorizationService.authenticate_access_token(...).
- mcp_saas/oauth_store.py: OAuthStore.issue_code(...), consume_code(...), issue_tokens(...), rotate_refresh(...), revoke_token(...), authenticate_access_token(...); one-use operations performed inside SQL transactions.
- mcp_saas/oauth.py: build_oauth_blueprint(...) and AuthorizationService, Authlib-backed protocol validation (grant, PKCE, redirect URI, client identity, issuer and resource).
- mcp_saas/management.py: build_management_blueprint(...) for authenticated CRUD and OAuth grant revocation; HTML pages under templates/ and minimal JS under static/.
- mcp_saas/audit.py: AuditService.log_event(...), QuotaService.consume(...) with atomic database updates; no sensitive request/response body persistence.
- mcp_saas/errors.py: AppError(code: str, status: int, message: str) and error helpers for OAuth, MCP, Odoo transport.

The production app must never import test-only authorization bypasses. Unit tests may inject a stub AuthorizationService through create_app(dependencies=...), while runtime uses the real service.

## Baseline and execution workflow

Record baseline BEFORE changes: git status --short; git branch --show-current; git merge-base HEAD main; python -m pytest -q tests. The baseline is from the existing AnyAPI root. If baseline fails, investigate and document separately; never hide existing failures. For each task, run its targeted pytest, then both: (1) cd odoo_mcp && uv run pytest -q and (2) from repository root python -m pytest -q tests. Use a protected isolated Git worktree if available and approved per Superpowers; otherwise work only in the dedicated branch. Commits per task; no automatic merge.

## Slice A — independently testable safe read path (NOT public until OAuth)

### Task 1: Isolated Flask WSGI app and configuration

**Files:**
- Create: odoo_mcp/pyproject.toml, odoo_mcp/uv.lock (generated using uv), odoo_mcp/.env.example, odoo_mcp/app.py, odoo_mcp/mcp_saas/__init__.py, odoo_mcp/mcp_saas/settings.py, odoo_mcp/mcp_saas/app_factory.py
- Test: odoo_mcp/tests/test_entrypoint.py

**Interfaces:** Produces Settings.from_env() and create_app(settings=None, dependencies=None) -> Flask. All other modules consume these.

- [ ] Step 1 — RED: create test_health_with_missing_credentials_has_no_secrets() and test_anyapi_entrypoint_not_mounted(). Assert GET /health returns 200; GET /health/ready with missing critical configuration returns 503 with only boolean readiness states; GET /_api/projects returns 404.
- [ ] Step 2 — Run cd odoo_mcp && uv run pytest tests/test_entrypoint.py -q; expected initial fail due to missing app factory.
- [ ] Step 3 — GREEN: implement Settings (minimum: SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY, ODOO_MCP_DB_DSN, ODOO_MCP_ENCRYPTION_KEY, ODOO_MCP_SESSION_KEY, ODOO_MCP_PUBLIC_URL) via prefixed environment entries, startup validation and WSGI export. Keep import side effects minimal; dependency injection is test-only. Generate and pin uv.lock.
- [ ] Step 4 — Run targeted tests, uv run pytest -q and root python -m pytest -q tests. Verify entrypoint app callable and no changes outside odoo_mcp/.
- [ ] Step 5 — Commit: git add odoo_mcp && git commit -m "feat(odoo-mcp): isolate Flask service and configuration".

### Task 2: Supabase relational schema, RLS and private access

**Files:**
- Create: odoo_mcp/supabase/migrations/<CLI-generated-timestamp>_odoo_mcp_init.sql (derive actual name from CLI, not hand-made), odoo_mcp/mcp_saas/store.py, odoo_mcp/mcp_saas/private_store.py
- Test: odoo_mcp/tests/test_schema.py, odoo_mcp/tests/integration/test_rls.py
- Documentation: odoo_mcp/docs/database.md

**Interfaces:** Produces TenantStore and PrivateStore from dependency map. Consumes Settings.

- [ ] Step 1 — RED: tests assert tables public.odoo_mcp_connections, public.odoo_mcp_servers, public.odoo_mcp_policies, public.odoo_mcp_audit_events; private.odoo_mcp_connection_secrets, private.odoo_mcp_oauth_clients, private.odoo_mcp_oauth_codes, private.odoo_mcp_oauth_tokens, private.odoo_mcp_rate_limits. Anon sees zero rows; a user A cannot SELECT/UPDATE rows owned by B, including nested connection/server ID; browser roles cannot read private tables or ciphertext.
- [ ] Step 2 — Run schema tests against disposable local/staging Postgres before migration; expected missing tables/policies. Snapshot and compare live migration versions READ-ONLY; check pending PR #2 migration numbers and collision risk.
- [ ] Step 3 — Generate migration using supabase migration new odoo_mcp_init (discover flags with supabase migration new --help), create owner FK and server+connection composite ownership constraints, minimum necessary grants/RLS (SELECT, INSERT, UPDATE with USING and WITH CHECK). Private OAuth tables accessible only to dedicated least-privilege runtime DB role; no anon/authenticated grants; private schema not in Data API exposed schemas. Implement narrow stores; wrap token-related future operations in SQL transactions.
- [ ] Step 4 — Run test_schema.py and test_rls.py using TWO real Auth JWTs against an isolated database, then both suites. Run Supabase advisors; preserve output and blockers. Only apply to the shared live project after explicit deployment/schema gate and verified migration reconciliation.
- [ ] Step 5 — Commit SQL + stores + tests + database guide: git commit -m "feat(odoo-mcp): add isolated data schema and tenant RLS".

### Task 3: User authentication boundaries and encrypted connection keys

**Files:**
- Create: odoo_mcp/mcp_saas/browser_auth.py, odoo_mcp/mcp_saas/credentials.py, odoo_mcp/tests/test_browser_auth.py, odoo_mcp/tests/test_credentials.py
- Modify: odoo_mcp/mcp_saas/app_factory.py

**Interfaces:** Produces require_current_user(request) -> BrowserIdentity and CredentialsService.encrypt_key/decrypt_key; consumes TenantStore, PrivateStore and Settings.

- [ ] Step 1 — RED: test_missing_cookie_redirects_to_login(), test_forged_cookie_denied(), test_cross_tenant_secret_unreadable(), test_ciphertext_roundtrip_and_wrong_key_fails(). Assert OAuth tokens are not accepted as SaaS sessions; Supabase session JWT is not an MCP bearer.
- [ ] Step 2 — Run target tests; expected missing auth/secrets handlers.
- [ ] Step 3 — Implement Supabase Auth browser session integration with server-verifiable identity and signed/encrypted HttpOnly Secure SameSite=Lax cookie, CSRF for all state mutations, token refresh, explicit logout and safe redirect targets. Keep Odoo key ciphertext in private store only; use dedicated encryption key with key version, no insecure session-key fallback.
- [ ] Step 4 — Run targeted tests plus both suites; test with two Supabase users in staging; prove no secret value in browser API, HTML, logging or headers.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): authenticate SaaS owners and protect Odoo secrets".

### Task 4: SSRF-safe HTTPS client and Odoo 19 JSON-2 adapter

**Files:**
- Create: odoo_mcp/mcp_saas/network.py, odoo_mcp/mcp_saas/odoo_json2.py, odoo_mcp/mcp_saas/errors.py
- Test: odoo_mcp/tests/test_network.py, odoo_mcp/tests/test_odoo_json2.py, odoo_mcp/tests/fixtures/fake_odoo.py

**Interfaces:** Produces assert_safe_odoo_url, PinnedHttpsTransport.post_json, OdooJSON2.call and probe_connection.

- [ ] Step 1 — RED: test_rejects_private_ips_and_credentials_in_url(), test_rebinding_public_dns_to_private_peer_denied(), test_redirect_never_followed(), test_json2_search_read_uses_named_args_and_bearer(), test_unsupported_plan_is_actionable(). Simulate private networks, loopback, IPv6, embedded credentials, 302/307, oversized responses, 401/403/429/503, invalid JSON and timeout.
- [ ] Step 2 — Run target tests; expected failures because transport and adapter do not exist.
- [ ] Step 3 — Implement HTTPS public-address-only validation plus safe peer pinning/TLS hostname verification with redirect=False; if runtime transport cannot guarantee peer pinning, fail closed (no insecure fallback). JSON-2 sends POST /json/2/<model>/<method>, Authorization bearer, optional X-Odoo-Database and named JSON arguments. Define allowlisted method mapping: search_read, read, fields_get, create, write (only authorized by higher-level tool); probe a harmless configured model and report unsupported cases.
- [ ] Step 4 — Run targeted tests, malicious-host fixture tests and both suites. Document the deployed transport proof including DNS-resolved IP and actual peer checks; verify Odoo ACLs are not bypassed.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): secure Odoo JSON-2 transport and probe".

### Task 5: Read-only policy engine, model schema and tool registry

**Files:**
- Create: odoo_mcp/mcp_saas/policies.py, odoo_mcp/mcp_saas/tools.py
- Test: odoo_mcp/tests/test_policies.py, odoo_mcp/tests/test_tools_read.py

**Interfaces:** Produces PolicyEngine.authorize/validate_filter/sanitize_records and ToolRegistry.list_tools/invoke; consumes OdooJSON2 and the TenantStore policies.

- [ ] Step 1 — RED: test_default_server_has_no_write_tools(), test_allowlist_hides_forbidden_models(), test_secret_fields_and_relations_redacted(), test_untrusted_domain_context_rejected(), test_query_max_100_and_default_20(). Verify strict model name, primitive field types, field projection, forbidden technical models (res.users, ir.config_parameter), limits and OAuth read scope intersection.
- [ ] Step 2 — Run target tests; expected failures because registry/policy does not exist.
- [ ] Step 3 — Implement exactly four V1 read tools: odoo_list_models, odoo_get_model_schema, odoo_search_records, odoo_get_record. Only preconfigured allowed models appear in discovery; fields_get may be invoked solely for such models. Allow flat AND-only whitelist predicates in V1; mandatory policy domain is combined as additional AND clauses. Context must be platform-generated (no user-supplied dangerous keys); sanitize relational values and reject unapproved/binary fields. Validate JSON schemas and policy AGAIN on invoke.
- [ ] Step 4 — Run targeted tests, both suites and fake Odoo end-to-end read. Confirm no administrative model is visible, even if Odoo API credentials have admin privileges.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): enforce read-only tool and field policies".

### Task 6: Stateless MCP Streamable HTTP transport (local contract)

**Files:**
- Create: odoo_mcp/mcp_saas/mcp_http.py
- Test: odoo_mcp/tests/test_mcp_http.py, odoo_mcp/tests/integration/test_mcp_read_contract.py
- Modify: odoo_mcp/mcp_saas/app_factory.py

**Interfaces:** Produces dispatch_rpc(context, message) -> (body | None, status), MCP blueprint and authenticated context resolution hook. The production AuthorizationService remains deny-all until Slice B.

- [ ] Step 1 — RED: test_initialize_negotiates_2025_11_25(), test_tools_list_only_authorized(), test_notifications_return_202_empty(), test_get_stream_returns_405(), test_invalid_origin_403(), test_invalid_version_400(), test_wrong_accept_rejected(), test_unknown_method_jsonrpc_error(). Assert no MCP-Session-Id is issued and unauthenticated POST is 401 with a placeholder spec-compatible challenge when OAuth not configured.
- [ ] Step 2 — Run target tests with injected test-only fake identity; expected missing endpoint. Never add a public authentication bypass.
- [ ] Step 3 — Implement initialize, notifications/initialized, ping, tools/list, tools/call and JSON-RPC errors; enforce Accept with application/json AND text/event-stream; Content-Type application/json; request JSON object size bounds, Origin and negotiated version header semantics. POST replies one JSON object, GET replies 405; DELETE without sessions replies 405; tool execution uses ToolRegistry and authenticated server+policy resolution.
- [ ] Step 4 — Run targeted tests, both suites and MCP protocol test client locally. Enforce full request path isolation, per-request context resolution and no state persisted in Flask memory.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): implement stateless Streamable HTTP read gateway".

**Slice A exit gate:** local fake Odoo and test-only authenticated MCP can successfully list/read permitted records; real public MCP stays locked until OAuth Slice B. Do not claim production client compatibility.

## Slice B — OAuth grant and client interoperability

### Task 7: OAuth metadata, safe client identification and transactional grant store

**Files:**
- Create: odoo_mcp/mcp_saas/oauth_store.py, odoo_mcp/mcp_saas/oauth.py
- Test: odoo_mcp/tests/test_oauth_metadata.py, odoo_mcp/tests/test_oauth_store.py, odoo_mcp/tests/test_oauth_clients.py
- Modify: odoo_mcp/mcp_saas/app_factory.py

**Interfaces:** Produces OAuthStore one-time code/token methods, AuthorizationService and discovery endpoints. Consumes PrivateStore and PinnedHttpsTransport for client metadata downloads.

- [ ] Step 1 — RED: test_protected_resource_uses_exact_canonical_mcp_url(), test_authorization_server_metadata_matches_issuer(), test_client_metadata_redirect_uri_must_match(), test_client_metadata_ssrf_denied(), test_duplicate_code_consumption_1_of_2_only(), test_cross_server_grant_cannot_resolve(). Verify private token/code rows inaccessible through anon and browser.
- [ ] Step 2 — Run tests; expected no OAuth routes/store.
- [ ] Step 3 — Implement RFC 9728 resource metadata at /.well-known/oauth-protected-resource/mcp/<public_id>, RFC 8414 AS metadata at /.well-known/oauth-authorization-server, WWW-Authenticate Bearer resource_metadata in 401, metadata-document clients over safe HTTPS with strict client_id equality and redirect URI validation, plus preregistered client support. Implement OAuthStore operations with parameterized SQL, atomic code consume and ownership/audience scoping. Select Authlib validators; use cryptographically random hashes and database timestamps.
- [ ] Step 4 — Run target tests, both suites and OAuth metadata HTTP conformance tests; no untrusted URL fetch to private networks. Record explicit decisions on client metadata refresh/cache.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): add OAuth discovery and one-time grant storage".

### Task 8: OAuth authorization-code + PKCE consent, token and refresh flows

**Files:**
- Modify: odoo_mcp/mcp_saas/oauth.py, odoo_mcp/mcp_saas/oauth_store.py
- Create: odoo_mcp/templates/oauth_consent.html
- Test: odoo_mcp/tests/test_oauth_flows.py, odoo_mcp/tests/integration/test_oauth_atomic.py

**Interfaces:** Produces POST /oauth/token, GET+POST /oauth/authorize, POST /oauth/revoke and AuthorizationService.authenticate_access_token(token: str, canonical_resource: str) -> GrantContext. Consumes Supabase browser session identity.

- [ ] Step 1 — RED: test_code_pkce_s256_happy_path(), test_without_consent_rejected(), test_wrong_redirect_or_resource_rejected(), test_pkce_plain_rejected(), test_replayed_code_rejected(), test_concurrent_refresh_only_one_succeeds(), test_revoked_expired_tokens_denied(), test_consent_cannot_grant_unconfigured_write().
- [ ] Step 2 — Run tests; expected missing flows/token state.
- [ ] Step 3 — Use Authlib OAuth validation. Require exact registered redirect_uri, state roundtrip, resource indicator bound to canonical MCP URL, S256 PKCE, logged-in owner approval for that server, explicit scopes. Codes expire within 5 minutes, single-use by SQL compare-and-update; access expires in 15 minutes, rotating refresh tokens revoke previous family members on replay. Reject token exchange without verified client and grant. Consent uses server-side CSRF and displays instance, client name and read/write scopes.
- [ ] Step 4 — Run all OAuth unit+SQL atomic concurrency tests, both suites. Confirm no raw bearer, Odoo key or refresh token persists in browser-readable data or logs.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): implement OAuth PKCE consent and token lifecycle".

### Task 9: Bind MCP calls to OAuth grants and prove tenant isolation

**Files:**
- Modify: odoo_mcp/mcp_saas/mcp_http.py, odoo_mcp/mcp_saas/tools.py, odoo_mcp/mcp_saas/oauth.py
- Test: odoo_mcp/tests/integration/test_mcp_oauth_e2e.py, odoo_mcp/tests/integration/test_tenant_isolation.py

**Interfaces:** Consumes AuthorizationService.authenticate_access_token and TenantStore.get_owned_server; outputs a real authenticated ToolContext. No auth bypass in production.

- [ ] Step 1 — RED: test_user_a_token_cannot_access_user_b_server(), test_server_a_token_cannot_access_server_b(), test_browser_cookie_alone_cannot_call_mcp(), test_revoked_token_denied_immediately(), test_policy_tightening_denies_existing_token(), test_mcp_scope_missing_denies_write(). Model an attempted foreign owner_id with service DB access.
- [ ] Step 2 — Run tests; expected failure until OAuth grant resolution is wired.
- [ ] Step 3 — Bind public_id -> server+owner, authenticate opaque access hash against exact audience, then load server policies+connection scoped by both IDs. Validate enabled status, current policy, OAuth grant and Odoo-user capability for every request; failures reveal neither existence nor foreign tenant data. Include WWW-Authenticate challenge and safe request_id.
- [ ] Step 4 — Run targeted tests, both suites and a real MCP SDK local client with fake Odoo upstream; capture initialization -> tools/list -> tools/call and negative cases.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): enforce audience-bound MCP authorization".

**Slice B exit gate:** a real MCP client can authorize and read with the account owner's permission, codes/tokens cannot be replayed, cross-tenant and cross-server calls fail. Claim ChatGPT compatibility only after actual ChatGPT OAuth testing in Slice D.

## Slice C — owner-facing SaaS and write opt-in

### Task 10: Owner dashboard and connection/server/policy CRUD

**Files:**
- Create: odoo_mcp/mcp_saas/management.py, odoo_mcp/templates/{layout,login,dashboard,connection,server}.html, odoo_mcp/static/{app.css,app.js}, odoo_mcp/tests/test_management.py
- Modify: odoo_mcp/mcp_saas/app_factory.py, odoo_mcp/mcp_saas/store.py

**Interfaces:** Provides authenticated HTML and /_api/odoo-mcp/* CRUD endpoints, CSRF protection, create/list/test/rotate/delete connection and enable/disable server. Consumes BrowserIdentity, TenantStore, PrivateStore and OdooJSON2.probe_connection.

- [ ] Step 1 — RED: test_anonymous_management_redirects(), test_csrf_missing_returns_400(), test_foreign_connection_404(), test_secret_never_returned(), test_server_requires_owned_connection(), test_new_server_has_no_write_policy(), test_connection_rotation_does_not_expose_old_key(), test_disabled_server_revokes_future_calls().
- [ ] Step 2 — Run tests; expected missing routes/templates.
- [ ] Step 3 — Implement Supabase browser login/signup (reuse existing project identity semantics without AnyAPI branding), connections and servers, connection validation, per-model/field allowlists, OAuth grants and revoke action, generated private MCP URL and setup help. Use only safe DOM insertion, escaping, responsive PT/EN templates, clear API-plan errors; no implicit successful connection claim before probe response.
- [ ] Step 4 — Run target tests and both suites; perform browser-level local desktop/mobile smoke tests with a seeded test tenant; verify no session or secret leakage in rendered HTML or API.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): provide tenant dashboard and server management".

### Task 11: Explicitly authorized create/update tools with ambiguity protection

**Files:**
- Modify: odoo_mcp/mcp_saas/tools.py, odoo_mcp/mcp_saas/policies.py, odoo_mcp/mcp_saas/odoo_json2.py, odoo_mcp/mcp_saas/management.py
- Test: odoo_mcp/tests/test_tools_write.py, odoo_mcp/tests/integration/test_write_boundary.py

**Interfaces:** Extends ToolRegistry with odoo_create_record and odoo_update_record only if server policy and OAuth odoo:write both permit them; OdooJSON2.call maps to create/write with named arguments.

- [ ] Step 1 — RED: test_write_hidden_until_enabled(), test_write_requires_scope_and_model_fields(), test_admin_and_sensitive_models_never_writable(), test_create_respects_max_batch_10(), test_update_rejects_other_owner(), test_timeout_returns_indeterminate_without_retry(), test_missing_field_permissions_prevents_upstream_call().
- [ ] Step 2 — Run targeted tests; expected denied tools.
- [ ] Step 3 — Implement exact model+field allowlists and explicit write consent, maximum 10 records per write request, no unlink, no raw methods, no caller-supplied context, and no blind writes to unapproved related fields. Mutations fail closed before Odoo call on any policy ambiguity. A write timeout produces a structured indeterminate outcome and audit entry; never auto-retry.
- [ ] Step 4 — Run targeted tests, both suites and dedicated low-privilege Odoo staging API-user create/update tests, validating resulting records; verify forbidden operations are absent from network capture.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): add bounded explicit Odoo write tools".

### Task 12: Atomic quotas, redacted logs, revocation and audit UI

**Files:**
- Create: odoo_mcp/mcp_saas/audit.py, odoo_mcp/tests/test_audit.py, odoo_mcp/tests/integration/test_quotas.py
- Modify: odoo_mcp/mcp_saas/mcp_http.py, odoo_mcp/mcp_saas/management.py, odoo_mcp/templates/server.html

**Interfaces:** Produces AuditService.log_event and QuotaService.consume(owner_id: str, server_id: str, actor_hash: str, limit: int, now: datetime) -> QuotaResult. Consumes PrivateStore, no arbitrary SQL runner.

- [ ] Step 1 — RED: test_log_redacts_secret_and_payload(), test_quota_61st_call_rejected_under_concurrency(), test_disabled_server_immediate_denial(), test_grant_revocation_visible_in_dashboard(), test_audit_owner_filter_blocks_other_tenant().
- [ ] Step 2 — Run tests; expected missing audit/quota operations.
- [ ] Step 3 — Implement atomic SQL upsert/increment with time-window key and no read-modify-write race; default 60 requests/min per server+actor, configurable only downward for V1. Log status, duration, request_id, tool, model, actor and safe error category; omit raw request/response data. Dashboard shows paginated logs, grant revocation and usage counters. Deny on quota store failure for protected MCP operations, with bounded safe errors.
- [ ] Step 4 — Run concurrency integration tests, both suites, verify revoked grants and tightened policies take effect on immediate next request.
- [ ] Step 5 — Commit: git commit -m "feat(odoo-mcp): audit calls and enforce atomic rate limits".

**Slice C exit gate:** SaaS owner flow supports multiple connections, policy editor, OAuth grants and logs; writes remain disabled by default and cannot exceed tenant, field or OAuth scope.

## Slice D — deployment and release gates

### Task 13: CI, Vercel preview, real Odoo/MCP E2E and security release review

**Files:**
- Create: .github/workflows/odoo-mcp-ci.yml, odoo_mcp/docs/deployment.md, odoo_mcp/docs/security.md, odoo_mcp/docs/runbook.md, odoo_mcp/tests/integration/test_preview_smoke.py
- Modify: odoo_mcp/pyproject.toml, odoo_mcp/uv.lock, odoo_mcp/.env.example only as required by proven deployment behaviour

**Interfaces:** External Vercel project configured with Root Directory = odoo_mcp, distinct environment and domain; no existing AnyAPI deployment configuration changes. This task owns release gate verification, not major feature rewrites.

- [ ] Step 1 — RED: write smoke tests asserting /health, /health/ready, 401 resource-metadata challenge, 405 GET /mcp/<id>, no session cookie exposure, no wildcard CORS, OAuth discovery, tool call scoped read and disabled write. Add a CI job running the new uv-pinned suite and existing root AnyAPI suite; initially verify the missing preview configuration is reported as an explicit blocked gate.
- [ ] Step 2 — Run CI locally where possible, then record missing preview/staging prerequisites. Do not mark environmental blockers as passing tests.
- [ ] Step 3 — Register **new** Vercel project from same GitHub repository with root directory odoo_mcp, configure restricted server-side secrets (separate encryption/session keys and least-privilege DB credentials), HTTPS, Supabase auth redirect allowlist and preview deployment. Confirm Vercel function timeout measured; apply migrations only after staging proof + migration reconciliation + authorization gate. Use a dedicated nonproduction Odoo 19 account/database for read, write and negative tests. If the actual ChatGPT client requires Dynamic Client Registration (DCR), stop this task, record the interoperability failure and amend this plan with a dedicated TDD task for abuse-protected DCR, then obtain review of that amendment before resuming; never silently expand the release task or claim unsupported compatibility.
- [ ] Step 4 — Run CI, Supabase security/performance advisors, two-tenant RLS and OAuth expiry/revocation checks, DNS rebinding tests, Vercel integration tests, desktop/mobile UI test, actual ChatGPT client authorization+read and optional explicitly permitted write. Document the exact commands, test counts, preview commit and evidence links in runbook. Run git diff main...HEAD and independently review security-sensitive changes. If any mandatory gate fails, leave Draft and report blocker.
- [ ] Step 5 — Commit: git commit -m "test(odoo-mcp): verify isolated preview and security release gates". Request whole-branch Superpowers code review, resolve critical/important issues via RED->GREEN tests, then prepare PR for owner review. **Do not merge or launch production without explicit user approval.**

## Self-review checklist for the plan author

- [ ] Spec requirements 1–12 are covered by Tasks 1–13 or explicitly deferred by the spec.
- [ ] Each task names exact files and interfaces; no competing names for tenant, server, token or transport methods.
- [ ] Each task provides RED test assertions, failing run, implementation signature, passing suite and a commit.
- [ ] Each Review Focus risk has a specific test in its owning task.
- [ ] Shared Supabase remains untouched until staging and migration reconciliation; AnyAPI PR #2 is independent.
- [ ] OAuth access tokens and Supabase Auth session tokens are never interchangeable.
- [ ] Vercel deployment assumptions are independently proven, not inferred from local tests.
- [ ] Before execution, a human has reviewed this plan and explicitly chosen Subagent-driven or Native execution.

## Execution method for approval

**Recommendation: Subagent-driven** with a fresh reviewer per security-sensitive task, if an actual subagent execution tool is available. OAuth, SSRF and tenant isolation have high blast radius and benefit from independent review. Otherwise use **Native** via superpowers:executing-plans, with evidence-backed per-task tests, a decisions ledger and a final whole-branch self-review clearly labelled as weaker than independent review.

Document is an executable plan **for review**, not evidence of implemented code or deployed infrastructure.
