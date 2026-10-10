-- Odoo MCP SaaS V1. Generated migration name using Supabase CLI in GitHub Actions.
-- Apply only after staged verification, migration drift comparison and owner approval.
create schema if not exists odoo_mcp_private;
revoke all on schema odoo_mcp_private from public, anon, authenticated;
do $$ begin
  if not exists(select 1 from pg_roles where rolname='odoo_mcp_service')
  then create role odoo_mcp_service nologin;
  end if;
end $$;
grant usage on schema odoo_mcp_private to odoo_mcp_service;

create table public.odoo_mcp_connections (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 label text not null check (char_length(label) between 1 and 80),
 base_url text not null check (char_length(base_url) between 8 and 2048),
 database text not null check (char_length(database) between 1 and 128),
 api_version text not null default '19.0',
 status text not null default 'pending' check(status in ('pending','healthy','unavailable','disabled')),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (id, owner_id)
);

create table public.odoo_mcp_servers (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 connection_id uuid not null,
 public_id text not null unique check(length(public_id)>=32),
 label text not null check(char_length(label) between 1 and 80),
 enabled boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique (id,owner_id),
 foreign key (connection_id, owner_id) references public.odoo_mcp_connections(id, owner_id) on delete cascade
);

create table public.odoo_mcp_policies (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 server_id uuid not null,
 model_name text not null check (model_name ~ '^[a-z_][a-z0-9_.]*$'),
 action text not null check (action in ('read','create','update')),
 allowed_fields jsonb not null default '[]'::jsonb check(jsonb_typeof(allowed_fields)='array'),
 allowed_domain jsonb not null default '[]'::jsonb check(jsonb_typeof(allowed_domain)='array'),
 enabled boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 foreign key (server_id, owner_id) references public.odoo_mcp_servers(id, owner_id) on delete cascade,
 unique(server_id,model_name,action)
);

create table public.odoo_mcp_audit_events (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 server_id uuid not null,
 request_id text not null,
 actor_client_id text,
 tool_name text,
 model_name text,
 action text,
 allowed boolean not null default false,
 status text not null,
 duration_ms integer not null default 0 check(duration_ms>=0),
 occurred_at timestamptz not null default now(),
 redacted_error text,
 foreign key (server_id, owner_id) references public.odoo_mcp_servers(id,owner_id) on delete cascade
);

create table odoo_mcp_private.odoo_mcp_connection_secrets (
 connection_id uuid primary key,
 owner_id uuid not null,
 secret_ciphertext text not null,
 key_version smallint not null default 1 check(key_version>0),
 updated_at timestamptz not null default now(),
 foreign key (connection_id, owner_id) references public.odoo_mcp_connections(id, owner_id) on delete cascade
);

create table odoo_mcp_private.odoo_mcp_oauth_clients (
 id uuid primary key default gen_random_uuid(),
 client_id text not null unique,
 client_metadata jsonb not null default '{}'::jsonb,
 registration_type text not null check(registration_type in ('metadata_document','preregistered')),
 verified_at timestamptz,
 status text not null default 'active' check(status in ('active','revoked')),
 created_at timestamptz not null default now()
);

create table odoo_mcp_private.odoo_mcp_oauth_codes (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 server_id uuid not null,
 client_id text not null,
 code_hash text not null unique,
 pkce_challenge text not null,
 redirect_uri text not null,
 resource text not null,
 scopes text[] not null default '{}',
 expires_at timestamptz not null,
 consumed_at timestamptz,
 created_at timestamptz not null default now(),
 foreign key (server_id,owner_id) references public.odoo_mcp_servers(id,owner_id) on delete cascade
);

create table odoo_mcp_private.odoo_mcp_oauth_tokens (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 server_id uuid not null,
 client_id text not null,
 access_hash text not null unique,
 refresh_hash text unique,
 scopes text[] not null default '{}',
 resource text not null,
 issued_at timestamptz not null default now(),
 expires_at timestamptz not null,
 revoked_at timestamptz,
 rotated_at timestamptz,
 foreign key (server_id,owner_id) references public.odoo_mcp_servers(id,owner_id) on delete cascade
);

create table odoo_mcp_private.odoo_mcp_rate_limits (
 server_id uuid not null references public.odoo_mcp_servers(id) on delete cascade,
 actor_key_hash text not null,
 window_start timestamptz not null,
 count integer not null default 0 check(count>=0),
 primary key(server_id,actor_key_hash,window_start)
);
alter table public.odoo_mcp_connections enable row level security;
alter table public.odoo_mcp_servers enable row level security;
alter table public.odoo_mcp_policies enable row level security;
alter table public.odoo_mcp_audit_events enable row level security;
create policy odoo_mcp_connections_select on public.odoo_mcp_connections for select to authenticated using (owner_id = (select auth.uid()));
create policy odoo_mcp_connections_insert on public.odoo_mcp_connections for insert to authenticated with check (owner_id = (select auth.uid()));
create policy odoo_mcp_connections_update on public.odoo_mcp_connections for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy odoo_mcp_connections_delete on public.odoo_mcp_connections for delete to authenticated using (owner_id = (select auth.uid()));
create policy odoo_mcp_servers_select on public.odoo_mcp_servers for select to authenticated using (owner_id = (select auth.uid()));
create policy odoo_mcp_servers_insert on public.odoo_mcp_servers for insert to authenticated with check (owner_id = (select auth.uid()));
create policy odoo_mcp_servers_update on public.odoo_mcp_servers for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy odoo_mcp_servers_delete on public.odoo_mcp_servers for delete to authenticated using (owner_id = (select auth.uid()));
create policy odoo_mcp_policies_select on public.odoo_mcp_policies for select to authenticated using (owner_id = (select auth.uid()));
create policy odoo_mcp_policies_insert on public.odoo_mcp_policies for insert to authenticated with check (owner_id = (select auth.uid()));
create policy odoo_mcp_policies_update on public.odoo_mcp_policies for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy odoo_mcp_policies_delete on public.odoo_mcp_policies for delete to authenticated using (owner_id = (select auth.uid()));
create policy odoo_mcp_audit_events_select on public.odoo_mcp_audit_events for select to authenticated using (owner_id = (select auth.uid()));
revoke all on public.odoo_mcp_connections, public.odoo_mcp_servers, public.odoo_mcp_policies, public.odoo_mcp_audit_events from public, anon, authenticated;
grant select, insert, update, delete on public.odoo_mcp_connections, public.odoo_mcp_servers, public.odoo_mcp_policies to authenticated;
grant select on public.odoo_mcp_audit_events to authenticated;
revoke all on all tables in schema odoo_mcp_private from public, anon, authenticated;
alter table odoo_mcp_private.odoo_mcp_connection_secrets enable row level security;
create policy odoo_mcp_connection_secrets_service on odoo_mcp_private.odoo_mcp_connection_secrets for all to odoo_mcp_service using (true) with check (true);
alter table odoo_mcp_private.odoo_mcp_oauth_clients enable row level security;
create policy odoo_mcp_oauth_clients_service on odoo_mcp_private.odoo_mcp_oauth_clients for all to odoo_mcp_service using (true) with check (true);
alter table odoo_mcp_private.odoo_mcp_oauth_codes enable row level security;
create policy odoo_mcp_oauth_codes_service on odoo_mcp_private.odoo_mcp_oauth_codes for all to odoo_mcp_service using (true) with check (true);
alter table odoo_mcp_private.odoo_mcp_oauth_tokens enable row level security;
create policy odoo_mcp_oauth_tokens_service on odoo_mcp_private.odoo_mcp_oauth_tokens for all to odoo_mcp_service using (true) with check (true);
alter table odoo_mcp_private.odoo_mcp_rate_limits enable row level security;
create policy odoo_mcp_rate_limits_service on odoo_mcp_private.odoo_mcp_rate_limits for all to odoo_mcp_service using (true) with check (true);
grant select, insert, update, delete on all tables in schema odoo_mcp_private to odoo_mcp_service;
grant select on public.odoo_mcp_connections, public.odoo_mcp_servers, public.odoo_mcp_policies to odoo_mcp_service;
grant insert, select on public.odoo_mcp_audit_events to odoo_mcp_service;
create policy odoo_mcp_connections_service on public.odoo_mcp_connections for select to odoo_mcp_service using (true);
create policy odoo_mcp_servers_service on public.odoo_mcp_servers for select to odoo_mcp_service using (true);
create policy odoo_mcp_policies_service on public.odoo_mcp_policies for select to odoo_mcp_service using (true);
create policy odoo_mcp_audit_service on public.odoo_mcp_audit_events for insert to odoo_mcp_service with check (true);
create index odoo_mcp_connections_owner_idx on public.odoo_mcp_connections(owner_id);
create index odoo_mcp_servers_owner_connection_idx on public.odoo_mcp_servers(owner_id, connection_id);
create index odoo_mcp_policies_owner_server_idx on public.odoo_mcp_policies(owner_id, server_id);
create index odoo_mcp_audit_owner_date_idx on public.odoo_mcp_audit_events(owner_id, occurred_at desc);
create index odoo_mcp_codes_owner_server_idx on odoo_mcp_private.odoo_mcp_oauth_codes(owner_id, server_id, expires_at);
create index odoo_mcp_tokens_owner_server_idx on odoo_mcp_private.odoo_mcp_oauth_tokens(owner_id, server_id, expires_at);
create index odoo_mcp_tokens_expiry_idx on odoo_mcp_private.odoo_mcp_oauth_tokens(expires_at) where revoked_at is null;
