-- Deterministic central V1 catalogue seed. Only service_role may mutate it.
insert into public.edge_function_catalog
  (slug, category, title, description, input_schema, output_schema, enabled)
values (
  'anyapi-normalize',
  'utilities',
  'Normalize object',
  'Return the supplied JSON object with processed=true.',
  '{"type":"object"}'::jsonb,
  '{"type":"object","required":["processed"],"properties":{"processed":{"type":"boolean"}}}'::jsonb,
  true
)
on conflict (slug) do update set
  category=excluded.category,
  title=excluded.title,
  description=excluded.description,
  input_schema=excluded.input_schema,
  output_schema=excluded.output_schema;
