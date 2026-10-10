# AnyAPI V1 — Central Supabase Edge Function catalog

## Architecture

- One central Supabase project: `aiosqtyvzopdtsolkpfg`.
- PostgreSQL `edge_function_catalog` is owned by the AnyAPI service; public and authenticated database roles cannot manage or read it directly.
- Flask lists only enabled functions via authenticated `GET /_api/edge-functions`. Client only sees name, category and JSON input/output schemas.
- `processor: {type: "edge_pipeline", steps: [...], output: "..."}` is saved in each endpoint draft, and an immutable snapshot is published in `endpoint_versions`.
- Runtime resolves function slugs **only through the server-owned catalog**. User-defined function URLs are never executed.
- Python and JavaScript user-code processors are unavailable for new V1 publication.
- The older, generic connector configuration remains in legacy database rows, but is not part of the V1 Studio. Outbound generic HTTP stays disabled unless separately secured.

## Standard Edge Function contract

```json
{"success": true, "data": {"processed": true}, "error": null, "meta": {"duration_ms": 1}}
```

Errors:

```json
{"success": false, "data": null, "error": {"code": "BAD_INPUT", "message": "Invalid JSON object"}, "meta": {}}
```

Functions must respond over HTTPS with the standard JSON envelope. The envelope and `data` JSON Schema are verified before continuing.

## Pipeline example

```json
{
  "type": "edge_pipeline",
  "steps": [
    {
      "id": "first",
      "function": "anyapi-normalize",
      "arguments": {"url": "{{input.url}}"},
      "on_error": "stop"
    },
    {
      "id": "second",
      "function": "anyapi-normalize",
      "arguments": {"source": "{{steps.first.data}}"},
      "on_error": "stop"
    }
  ],
  "output": "{{steps.second.data}}"
}
```

Mappings support previous successful step envelopes: `steps.first.data`, `steps.first.meta`. A failing step uses `on_error=stop` by default; `continue` stores the error envelope.

## Deployment

1. `0004_edge_function_catalog.sql` has been applied to the central Supabase project.
2. The sample Edge Function `anyapi-normalize` was deployed with **JWT verification enabled**. Source: `supabase/functions/anyapi-normalize/index.ts`.
3. It was registered in the catalog, category `utilities`, and enabled.
4. Flask invokes `https://<SUPABASE_PROJECT>.supabase.co/functions/v1/<catalog-slug>` with service credentials kept server-side. **Verify that the configured credential is a valid JWT for Edge Function JWT validation.** New-style `sb_secret_` API keys are not JWTs; if in use, supply `ANYAPI_EDGE_FUNCTION_JWT` as a compatible server-only signed JWT or implement an explicitly audited alternative authentication protocol. Never disable `verify_jwt` without independent authentication.
5. Publish the feature branch to a **Vercel preview**, configure secrets server-side and run authenticated E2E tests before merging.

## Release acceptance

- Create a fresh endpoint in Studio (defaults to an empty `edge_pipeline`).
- Add `anyapi-normalize`; set `arguments` and `output`; define input and output schema.
- Test draft; inspect log and HTTP status. Confirm missing/unlisted slugs fail validation.
- Publish version 1; invoke its public URL; confirm response data and execution log.
- Edit draft, publish version 2; roll back to version 1 and verify original output.
- Make the endpoint private; create a scoped API key; verify 401 without key, 200 with key, 401 after revocation.
- Check different accounts cannot read each other's resources.
- Confirm invalid edge envelopes, timeouts, retries and unsupported redirects are rejected.

The Edge Function deployment and database registry were verified via Supabase management operations; **a full live gateway invocation has not yet been verified**. Do not call this a production-ready E2E until these checks pass.
