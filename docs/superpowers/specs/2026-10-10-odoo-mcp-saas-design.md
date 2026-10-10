# Odoo MCP SaaS — Architecture and Product Design (V1)

**Date:** 2026-10-10  
**Status:** Design candidate — awaiting owner review; implementation NOT authorized by this document  
**Repository:** marcelo-m7/anyapi  
**Branch:** feat/odoo-mcp-saas (forked from main at 4e58e596b6ee8fa40cddaf7ddc29f7dc6816b01b)  
**Supabase:** aiosqtyvzopdtsolkpfg (shared infrastructure, isolated Odoo MCP tables)  
**Deployment:** new, independently configured Vercel project; production domain TBD  

## 1. Intent, users and success

Build a commercially usable, multi-tenant hosted MCP gateway for Odoo. An authenticated SaaS account can connect one or more authorized Odoo databases, choose permitted model-level and field-level operations, then connect an MCP-capable AI client (including ChatGPT, after real interoperability verification) without operating a separate MCP server.

V1 success is demonstrable when a test user can: sign in; register an Odoo 19 instance; verify credentials and supported external API capability; choose a restricted read-only policy; generate a private MCP endpoint; authorize an MCP client; list tools; retrieve allowed Odoo data; have unauthorized accesses rejected; opt into narrowly scoped create/update permissions; revoke access; and audit all attempted invocations. Cross-tenant access must fail both through the browser and the MCP endpoint.

**Not part of V1:** subscriptions/Stripe billing, organization/team membership, public tool marketplace, arbitrary model method execution, arbitrary Python execution, mass exports, DELETE/unlink operations, Odoo module installation, universal support for Odoo installations without authorized external API access, or a background worker.

## 2. Architectural separation

Choose **Option A**: an Odoo-specific SaaS product derived from AnyAPI's Flask/Vercel conventions, NOT an Odoo plug-in inside AnyAPI's generic endpoint catalog.

- Preserve AnyAPI main.py, its management/gateway routes, and PR #2 unchanged.
- Put Odoo-specific code under odoo_mcp/ with a separate Vercel WSGI entrypoint, tests, templates and configuration.
- Reuse selective stable utilities for Supabase REST/auth and cryptography after tests; do not couple Odoo models to AnyAPI projects, connectors or endpoints.
- A separate Vercel project builds from feat/odoo-mcp-saas, with a different domain and separate server-side environment secrets. Reusing the same Git repository/branch does not imply sharing deployment configuration or HTTP cookies.
- Use the **same Supabase project** for user identity, but only new odoo_mcp_* tables for product data, with distinct migrations and RLS. No schema or data mutations in this design phase. Any later extraction to a dedicated repository must preserve history, migrations and explicit configuration.

The open AnyAPI PR #2 (feat/anyapi-mvp-complete) is 57 commits ahead of main as of design. It already deployed Supabase catalog migrations. DO NOT merge its code into this branch implicitly or reapply existing migrations. Before applying Odoo migrations, compare live remote migration history, establish a conflict-free naming/version convention and test on a staging database or isolated schema. Never reset the shared production Supabase project.

## 3. Runtime and dataflow

Browser UI -> dedicated Flask WSGI app on Vercel -> Supabase Auth + scoped PostgREST/RLS.

MCP client -> HTTPS Streamable HTTP at /mcp/<opaque_server_id> -> OAuth bearer validation -> server/tenant/policy resolution -> tool authorization -> Odoo transport adapter -> user's Odoo instance -> result minimization -> MCP JSON-RPC response.

Supabase stores SaaS profiles, grants, allowlists, encrypted Odoo credentials, token hashes and redacted audit records. It does NOT store a replicated copy of the tenant's Odoo business records.

MCP uses stateless HTTP requests; NO long-lived in-memory sessions, WebSockets or required SSE streams in V1. A POST may respond with application/json; GET on the MCP endpoint returns 405 when no streaming subscription exists. Follow negotiated MCP version headers and JSON-RPC lifecycle; notifications return 202 without body. Operations exceeding the Vercel time budget fail with a structured timeout; clients may retry safe reads. Never retry writes automatically without idempotency protections.

## 4. Odoo adapter and eligibility

**Preferred V1 adapter:** Odoo 19 external JSON-2, HTTP POST to /json/2/<model>/<method> with Bearer API key and optional X-Odoo-Database. Use only explicitly allowlisted methods and schema-validated arguments. Honor the actual Odoo user's record rules and ACLs; SaaS policy is an additional restriction, never a replacement.

Support Odoo Community, Enterprise and Odoo Online **only when the target deployment/version/plan actually offers permitted external API access**. The Odoo Custom-plan limitation must be clearly presented for applicable Online/Enterprise subscriptions. Detect capabilities with a safe, low-privilege probe; don't assume an arbitrary /doc URL or API method works on every installation. Provide actionable errors for 401/403, unsupported version, blocked API and incorrect database.

Legacy XML-RPC/JSON-RPC for older Odoo versions is **not required for the first production MVP**; design a versioned transport interface for subsequent compatibility. Odoo documents a deprecation timetable for legacy external RPC, so avoid building new workflows exclusively around it.

Credentials: enforce HTTPS; reject localhost, RFC1918/private/link-local/reserved networks, user-info URLs, URL fragments and non-approved ports by default; forbid following redirects; validate the DNS resolution and peer destination with protections against DNS rebinding/TOCTOU (fail closed if reliable pinning is unavailable). Timeouts, bounded response sizes and content-type checks are mandatory. Keep keys server-side encrypted using a dedicated versioned encryption key; never use the public Supabase key as encryption material and never expose service keys to clients. Provide test, rotate and delete-connection actions.

## 5. Tenancy and authorization model

V1 tenant = one Supabase Auth user (auth.uid()). One tenant may own N connections and N MCP servers, each server bound to exactly one connection. Team accounts are a post-V1 extension, not simulated through mutable user_metadata.

Every tenant-owned record includes owner_id uuid referencing auth.users, and every normal user RLS policy uses (select auth.uid()) = owner_id on reads and writes, with WITH CHECK on inserts/updates. Deny anon by default. Privileged service-role reads MUST first resolve verified authorization, then include explicit owner_id + server_id constraints; a service role is not a substitute for tenant authorization.

MCP access is granted via an OAuth authorization-code + PKCE user-consent flow, distinct from Supabase login. Supabase Auth establishes the person's identity; an OAuth authorization server issues audience-bound opaque tokens for the selected MCP server, with least-privilege scopes and expiry. Access/refresh tokens and authorization codes are stored hashed, with refresh rotation, revoke, short code TTL, replay protection, and audit. Validate redirect URI exactly, client identity, state, PKCE, resource indicator and issuer. Never accept unrelated Supabase JWTs as MCP resource tokens or pass through Odoo credentials to the client.

MCP authorization discovery includes RFC 9728 Protected Resource Metadata and RFC 8414 Authorization Server Metadata. Provide support for current MCP client identification conventions (Client ID Metadata Documents preferred in the 2025-11-25 spec; preregistered clients where necessary); optional Dynamic Client Registration only if safely implemented. Every supported client flow must be verified end to end, including ChatGPT, before claiming compatibility. Serve WWW-Authenticate with resource metadata for unauthorized connections.

OAuth scopes at minimum: odoo:read and odoo:write. Scope is an outer bound: the final permission is intersection of the tenant's configured server policy, the authorized client grant, the Odoo API user's ACLs and the exact tool's requested model/fields/action. Revocation/disable takes effect at the next request, including previously issued tokens. Permission tightening must take effect without waiting for token expiration.

## 6. Tools and policy engine

The MCP endpoint exposes exactly the tools authorized for its server; never expose arbitrary method names, raw execute_kw or unrestricted Odoo ORM access.

- odoo_list_models: return only approved, discoverable models; no inaccessible model enumeration.
- odoo_get_model_schema: return approved fields and types for one approved model; redact sensitive metadata.
- odoo_search_records: bounded, validated read with approved model, fields, predicates, sort and pagination.
- odoo_get_record: retrieve specified IDs on approved model, restricted to approved fields and row-level Odoo visibility.
- odoo_create_record: enabled ONLY with explicit write consent and configured model+field allowlist; no side-channel writes.
- odoo_update_record: same restrictions, explicit IDs and strict maximum batch size.

Defaults: all servers start read-only. Suggested initial caps to verify against performance are page_size 20, maximum page_size 100, maximum batch write 10, maximum execution 15 seconds inside a stricter Vercel runtime budget. No delete tool in V1. Reject unsupported domain operators, dangerous context keys, unbounded result sets, attachment binaries, field escalation, reserved models and relations that could expose nonapproved data. Sensitive technical models (e.g. res.users, ir.config_parameter, credential-bearing integrations) are denylisted and cannot be enabled in self-service V1. Validate both the incoming tool schema AND the policy at execution time, not just during discovery. Mutations require request audit with no raw secrets. Prefer a dedicated least-privilege Odoo service account per connection.

For tool replies: return structured, bounded JSON with stable tool-specific error codes (authentication_failed, not_authorized, unsupported_odoo_api, invalid_input, rate_limited, timeout, upstream_error) and request_id. Do not leak stack traces, bearer tokens, SQL, personal data from unrelated records or complete upstream error bodies.

## 7. Data model (proposed; do not execute yet)

Tenant-facing tables belong in public with RLS enabled before grants; OAuth code/token/client internals must be in a non-exposed private schema, or strictly service-only tables with no anon/authenticated grants. Only columns necessary for V1 are listed. No existing AnyAPI rows or tables are modified:

| Table | Minimum columns / responsibility |
| --- | --- |
| odoo_mcp_connections | id, owner_id, label, base_url, database, api_version, secret_ciphertext, key_version, status, created_at, updated_at |
| odoo_mcp_servers | id, owner_id, connection_id, label, enabled, public_id (nonenumerable random ID), created_at |
| odoo_mcp_policies | id, owner_id, server_id, model_name, action, allowed_fields jsonb, allowed_domain jsonb, enabled; unique policy per model/action |
| odoo_mcp_oauth_clients | id, client_id, client_metadata, registration_type, verified_at, status; no secrets unless confidential client |
| odoo_mcp_oauth_codes | id, owner_id, server_id, client_id, code_hash, pkce_challenge, redirect_uri, resource, scopes, expires_at, consumed_at |
| odoo_mcp_oauth_tokens | id, owner_id, server_id, client_id, access_hash, refresh_hash, scopes, resource, issued_at, expires_at, revoked_at, rotated_at |
| odoo_mcp_audit_events | id, owner_id, server_id, request_id, actor_client_id, tool_name, model_name, action, allowed, status, duration_ms, occurred_at, redacted_error |
| odoo_mcp_rate_limits | server_id, actor_key_hash, window_start, count; short-lived atomic quotas |

OAuth client registration records are global service-managed metadata, not tenant-owned business records. Keep code/token internals private and unavailable from the Data API; validate client metadata document URLs against SSRF and redirect attacks before making outbound requests. No browser-readable OAuth secret/token records. Include indexes on all owner_id, server_id, status, token hashes, expiry and audit timestamps; avoid unnecessary exposed SECURITY DEFINER functions. Use atomically enforced token exchange and rate limits; do not implement read-then-write races.

Migration convention must be reviewed against the currently applied Supabase history and the pending PR #2 migrations. Run Supabase security and performance advisors before staging approval. Never use service_role from the browser.

## 8. HTTP and UX contracts

Browser dashboard features: sign-up/sign-in; connections list/create/test/rotate/delete; model+field policy editor; server create/enable/disable; generated MCP URL + OAuth connection instructions; OAuth consent screen; client grant list + revoke; execution log with safe filters; clear capability and plan errors. Use accessible, responsive pages in PT/EN; avoid coupling design copy to AnyAPI branding.

Initial route layout (subject to gateway/framework contract tests):
- GET /health and GET /health/ready with no secrets
- GET /dashboard and /_api/odoo-mcp/* for authenticated SaaS management
- POST /mcp/<public_id> for MCP JSON-RPC, GET /mcp/<public_id> returns 405 in stateless V1
- GET /.well-known/oauth-protected-resource/mcp/<public_id> for resource metadata
- GET /.well-known/oauth-authorization-server for AS metadata
- GET/POST /oauth/authorize for consent; POST /oauth/token and POST /oauth/revoke
- Client identification / registration routes only as needed by the verified MCP client compatibility contract

API management operations require active browser session and CSRF protection; MCP operations require bearer auth, never the SaaS cookie alone. Generic CORS wildcard is prohibited; validate Origin on MCP requests as specified. HTTP and OAuth failures use correct status codes and headers, with safe, stable error envelopes.

## 9. Deployment, observability and risks

Vercel project uses a dedicated root/entrypoint from this branch, distinct environment variables, HTTPS and separate domain from anyapi.tech. Do not switch the existing AnyAPI deployment or mutate shared Vercel production secrets. Validate Python runtime and actual serverless timeout limits in preview; do not depend on process memory for persistent sessions or rate limits. Configure Supabase Auth allowed redirect URLs explicitly for the new dashboard host. Audit logs carry request ID, user/tenant ID, Odoo server ID, action and safe error category, but do not persist raw Odoo payloads by default.

Primary risks and mitigations:
1. Shared Supabase migration drift with PR #2 -> inspect live versions, use a forward-only, uniquely named migration and staging first.
2. Cross-tenant authorization through service_role -> explicit server+owner scoping, test IDOR and forged grants.
3. SSRF or DNS rebinding when connecting custom Odoo URLs -> strict HTTPS/public-IP validation, redirect refusal, safe connection policy.
4. OAuth client compatibility -> metadata/PKCE/resource indicator interoperability tests with real ChatGPT connection, no unverified claims.
5. Odoo plan restrictions and record-rule gaps -> capability probe, explicit feature gates, least-privilege Odoo account.
6. Serverless runtime limitations -> stateless MCP, bounded upstream calls and an execution budget enforced below deployed limit.
7. Unintended writes and retries -> disabled by default, granular allowlists, no implicit write retries and consent review.

## 10. Delivery slices and acceptance gates

**Slice A — secure read path:** isolated Flask entrypoint and config, migrations, RLS, encrypted connector, Odoo JSON-2 adapter, read-only policies, stateless MCP initialize/tools/list/tools/call, pytest contract suite and local fake Odoo test server. Deliverable: authenticated and policy-limited read against a nonproduction Odoo 19 database.

**Slice B — OAuth + client interoperability:** Authorization Server Metadata, Protected Resource Metadata, OAuth code+PKCE, consent, token lifecycle, ChatGPT-compatible connection and negative auth tests. Deliverable: genuine MCP client connects via OAuth and reads an allowed Odoo record without tenant crossover.

**Slice C — SaaS management + writes:** responsive dashboard, per-model/field policy editor, test connection, write opt-in create/update, logs, revocation, quotas. Deliverable: full owner journey and positive/negative write tests.

**Slice D — preview hardening:** independent Vercel preview, deployment secrets, Supabase migration replay/staging security review, end-to-end user flow, actual Odoo backend tests, mobile checks and operational runbook. No production merge or public-launch claim before passing gates.

**Verification gates:** entire existing AnyAPI suite still passes; Odoo MCP suite passes; no changes to main.py or existing AnyAPI DB tables; RLS isolation proves user A cannot read/write B's resources; a stolen/expired/revoked token is denied; a token issued for server A cannot access server B; writes denied until enabled; forbidden field/model denied even when Odoo credentials permit it; responses are bounded; OAuth metadata and flows conform; user-visible errors are safe; external API restrictions are reported; preview supports MCP without SSE/WebSocket dependence; repeatable migrations reconcile cleanly with live Supabase state.

**Review focus not covered by basic happy-path tests:** DNS rebinding and unexpected redirect; OAuth authorization-code replay and refresh race; service-role IDOR through nested server/connection IDs; Odoo model with a sensitive relational field; transient timeout during write causing ambiguous completion.

## 11. Open implementation choices (not a reversal of the approved design)

- Final product name, domain, visual identity and pricing are deferred; technical route examples are provisional until the deployment URL is assigned.
- Choose the exact OAuth library and persistence implementation during the written implementation plan, but not a noncompliant shortcut.
- Reconcile current Supabase migrations, RLS, and PR #2 before applying new schema; no database mutation at design stage.
- If the deployed Vercel environment cannot safely support a required OAuth or upstream operation, preserve the approved architecture by introducing a narrowly scoped alternative worker later only after design review, not silently.
- ChatGPT's specific connection capabilities must be validated with a live client; other MCP clients are additional interoperability targets.

## 12. Authoritative references

- MCP Streamable HTTP 2025-11-25: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP OAuth 2025-11-25: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- Odoo 19 JSON-2: https://www.odoo.com/documentation/19.0/developer/reference/external_api.html
- Odoo legacy external RPC deprecation: https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html
- Supabase Auth/RLS: https://supabase.com/docs/guides/auth/row-level-security
- AnyAPI PR #2 (separate work): https://github.com/marcelo-m7/anyapi/pull/2

**Design-review gate:** the owner reviews this committed spec. Only after approval invoke the writing-plans process and prepare executable tasks. No product implementation, SQL migrations or Vercel deployment in this design commit.
