-- AnyAPI: security and index hardening (non-destructive)
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.executions_bump_counters() FROM PUBLIC, anon, authenticated;

CREATE INDEX IF NOT EXISTS api_keys_endpoint_idx ON public.api_keys(endpoint_id);
CREATE INDEX IF NOT EXISTS api_keys_owner_idx ON public.api_keys(owner_id);
CREATE INDEX IF NOT EXISTS connectors_owner_idx ON public.connectors(owner_id);
CREATE INDEX IF NOT EXISTS endpoint_connectors_owner_idx ON public.endpoint_connectors(owner_id);
CREATE INDEX IF NOT EXISTS endpoint_versions_owner_idx ON public.endpoint_versions(owner_id);
CREATE INDEX IF NOT EXISTS endpoints_published_version_idx ON public.endpoints(published_version_id);
CREATE INDEX IF NOT EXISTS executions_version_idx ON public.executions(version_id);
