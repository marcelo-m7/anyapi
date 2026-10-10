# AnyAPI

**Create APIs visually. Connect, transform and publish in minutes.**

AnyAPI is a Flask + Vercel SaaS that turns JSON Schema definitions and **catalogued Supabase Edge Functions** into public or API-key-protected HTTP endpoints without per-endpoint deployments.

## V1 architecture

- **Flask** handles user authentication, project management, the Studio, publishing, OpenAPI and the request gateway.
- **Supabase Auth + Postgres** store users, projects, endpoint drafts, immutable published versions, an administrator-managed central Edge Function catalog and execution logs.
- **Supabase Edge Functions** perform processing. AnyAPI invokes only registered and enabled functions in the central Supabase project; users cannot enter execution URLs or upload runnable code.
- **Studio** offers input/output schemas with JSON/YAML editing, a function picker, argument mappings, step ordering, test console, version rollback and API keys.

### Example pipeline

```json
{
  "type": "edge_pipeline",
  "steps": [{
    "id": "normalize",
    "function": "anyapi-normalize",
    "arguments": {
      "value": "{{input.value}}",
      "label": "{{input.label}}"
    },
    "on_error": "stop"
  }],
  "output": "{{steps.normalize.data}}"
}
```

Request to published endpoint:

```http
POST /marcelo-m7/api/normalize
Content-Type: application/json

{"value":"  Hello  ","label":"demo"}
```

Expected response from the reference function:

```json
{"value":"Hello","label":"demo","processed":true}
```

The public endpoint output is distinct from the internal Edge Function envelope, which is
`{"success":true,"data":{...},"error":null,"meta":{...}}`.

## Local development

Use Python 3.12:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
python -m flask --app main run --debug
pytest -q
```

Server-only environment variables:
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ANYAPI_SECRET_KEY` (stable and random)
- `ANYAPI_ENCRYPTION_KEY` (stable and random)
- `ANYAPI_PUBLIC_URL`
- `ANYAPI_EDGE_FUNCTION_JWT` (only when the Supabase service key is not a JWT; keep server-only)

Never expose service credentials to client-side JavaScript. Do not commit `.env`.

## Database and Edge Function deployment

Apply SQL migrations in order in `supabase/migrations/` and deploy the function
`supabase/functions/anyapi-normalize/index.ts` with JWT verification enabled.

The central V1 project is `aiosqtyvzopdtsolkpfg`. The catalog is managed by the AnyAPI backend and is not writable by application users.

## E2E and release process

GitHub Actions runs Python compilation and unit/integration tests on every PR. The tests include a mocked Flask gateway → catalog → Edge invocation flow. A real production-ready E2E **still requires** a Vercel preview with configured secrets and an authenticated Supabase user, followed by versioning, API-key, RLS and browser checks.

See [Edge Function V1 architecture](docs/EDGE_PIPELINE_V1.md) and [MVP status](docs/MVP_STATUS.md).

**No arbitrary Python or JavaScript code execution in V1.** Existing legacy visual processors may be read for backwards compatibility, but new publication uses catalogued Edge Function pipelines.
