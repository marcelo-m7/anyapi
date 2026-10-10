# AnyAPI — MVP in progress

AnyAPI turns declarative processors into HTTP endpoints without redeploying Vercel.

## Status
- Flask gateway: dynamic route `/{username}/{project}/{endpoint}`
- Supabase Auth: signup, login, recovery, encrypted session token storage
- Project and endpoint CRUD API, drafts, publish/rollback, test and logs
- Minimal landing/dashboard/editor; visual drag-and-drop UI not yet implemented
- Declarative runtime and safe HTTP connector plumbing (requires further security review)
- Python/JavaScript code execution **disabled until an isolated runner is configured and audited**

## Run locally

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
gunicorn main:app --bind 127.0.0.1:8000
```

The Supabase migration is in `supabase/migrations/0001_anyapi_init.sql`.
It was previously applied by the v0 agent to the named Supabase project, but that deployment could not be independently verified from this environment. Verify its migration history before applying any SQL again.

## Required configuration

```env
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
ANYAPI_SECRET_KEY=
ANYAPI_ENCRYPTION_KEY=
ANYAPI_PUBLIC_URL=https://anyapi.tech
ANYAPI_RUNNER_URL=
ANYAPI_RUNNER_TOKEN=
```

Set a strong, stable `ANYAPI_SECRET_KEY` and `ANYAPI_ENCRYPTION_KEY` **before deployment**.
The service role key must never be placed in client-side code.
Configure Supabase Auth redirect URL: `https://anyapi.tech/auth/callback`.

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /_api/projects | List own projects |
| POST | /_api/projects | Create project |
| GET | /_api/projects/{id}/endpoints | List endpoints |
| POST | /_api/projects/{id}/endpoints | Create endpoint |
| GET/PATCH | /_api/endpoints/{id} | Read/edit draft |
| POST | /_api/endpoints/{id}/test | Execute current draft |
| POST | /_api/endpoints/{id}/publish | Publish immutable version |
| POST | /_api/endpoints/{id}/rollback | Roll back |
| GET | /_api/endpoints/{id}/versions | Version history |
| GET | /_api/endpoints/{id}/executions | Recent logs |
| GET | /docs/{user}/{project}/{endpoint}/openapi.json | OpenAPI 3.1 |
| GET/POST/PUT/PATCH/DELETE | /{user}/{project}/{endpoint} | Public gateway |

All state-mutating management requests require a logged-in session and an `X-CSRF-Token` header, or a hidden `csrf_token` form field.

## Security limitations before public launch

- Dynamic HTTP connector egress currently validates DNS before making the request; a DNS rebinding race remains. Deploy an egress-protected worker/proxy before exposing arbitrary HTTP connectors publicly.
- The current fixed-window limiter fails open if Supabase is unavailable; change to fail-closed for abuse-sensitive endpoints before production.
- API keys are hashed. Connector secrets are encrypted at rest; never disclose these through the browser.
- User code must only run on a genuinely isolated, audited worker. Configuring an arbitrary runner URL is not equivalent to sandboxing.
- Avoid logging request/response bodies containing personal or secret data without consent and retention controls.
- Session tokens are encrypted into Flask cookies, but for production SaaS prefer opaque server-side sessions to support revocation and rotation.
- Schema migration permissions/RLS require verification through the target Supabase project.

## Next steps

1. Restore Supabase connector permissions and audit schema/RLS.
2. Fix any CI failures, deploy a preview, verify Auth registration/sign-in end to end.
3. Replace the JSON-only editor with a visual schema builder and drag-and-drop processor.
4. Add secure CRUD/configuration for HTTP connectors and API keys.
5. Configure isolated runner and full regression tests.


## Security update (MVP completion branch)

- Supabase migration `0003_anyapi_security_indexes.sql` has been applied to project `aiosqtyvzopdtsolkpfg` and adds FK indexes and revokes direct RPC invocation of internal trigger functions.
- HTTP connector configuration is normalized to `base_url`.
- Outbound HTTP requests are **disabled by default** until an independently protected egress network is deployed. Set `ANYAPI_HTTP_EGRESS_ENABLED=true` only behind a network firewall/egress proxy that prevents connections to private, local, and cloud metadata addresses even during DNS rebinding. The application-level DNS check alone is insufficient.
- The Python/JavaScript runner remains optional and disabled if no isolated worker is configured.
- Database-backed multi-user tests and browser E2E remain release blockers.
