-- Central, server-managed Edge Function registry
create table if not exists public.edge_function_catalog (
 id uuid primary key default gen_random_uuid(),
 slug text not null unique check (slug ~ '^[a-z][a-z0-9-]{1,62}$'),
 category text not null default 'utilities',
 title text not null,
 description text not null default '',
 input_schema jsonb not null default '{"type":"object"}'::jsonb,
 output_schema jsonb not null default '{"type":"object"}'::jsonb,
 enabled boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
alter table public.edge_function_catalog enable row level security;
revoke all on public.edge_function_catalog from anon, authenticated;
grant select, insert, update, delete on public.edge_function_catalog to service_role;
create index if not exists edge_function_catalog_enabled_idx on public.edge_function_catalog (enabled, category);
