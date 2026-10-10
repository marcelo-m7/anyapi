-- AnyAPI initial schema: profiles, projects, endpoints, immutable versions,
-- connectors, API keys, executions and serverless-safe rate limiting.

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

create or replace function public.anyapi_reserved_names()
returns text[]
language sql
immutable
set search_path = ''
as $$
  select array[
    'about','admin','anyapi','api','app','assets','auth','billing','blog','dashboard',
    'docs','favicon.ico','forgot-password','health','help','login','logout','new',
    'openapi','pricing','reset-password','robots.txt','settings','signup','static',
    'status','support','system','v1','www','_api','_next'
  ]::text[];
$$;

create or replace function public.anyapi_is_valid_slug(p text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select p is not null
     and p ~ '^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$'
     and p !~ '--';
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Profiles
-- ---------------------------------------------------------------------------

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profiles_username_format check (
    public.anyapi_is_valid_slug(username) and char_length(username) >= 3
  ),
  constraint profiles_username_not_reserved check (
    not (username = any (public.anyapi_reserved_names()))
  )
);

create or replace function public.profiles_lock_username()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.username is distinct from old.username then
    raise exception 'username cannot be changed' using errcode = '42501';
  end if;
  return new;
end;
$$;

drop trigger if exists profiles_lock_username on public.profiles;
create trigger profiles_lock_username before update on public.profiles
  for each row execute function public.profiles_lock_username();

drop trigger if exists profiles_updated_at on public.profiles;
create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles for select using (auth.uid() = id);
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles for update using (auth.uid() = id) with check (auth.uid() = id);

create or replace function public.username_available(p_username text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select public.anyapi_is_valid_slug(lower(p_username))
     and char_length(p_username) >= 3
     and not (lower(p_username) = any (public.anyapi_reserved_names()))
     and not exists (select 1 from public.profiles where username = lower(p_username));
$$;

revoke all on function public.username_available(text) from public;
grant execute on function public.username_available(text) to anon, authenticated, service_role;

-- Creates the profile atomically with the auth user. An invalid or taken
-- username aborts the sign-up instead of producing an orphan account.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_username text := lower(coalesce(new.raw_user_meta_data ->> 'username', ''));
begin
  insert into public.profiles (id, username, display_name)
  values (new.id, v_username, nullif(new.raw_user_meta_data ->> 'display_name', ''));
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Projects
-- ---------------------------------------------------------------------------

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  slug text not null check (public.anyapi_is_valid_slug(slug)),
  description text check (description is null or char_length(description) <= 500),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, slug)
);

create index if not exists projects_owner_idx on public.projects(owner_id);

drop trigger if exists projects_updated_at on public.projects;
create trigger projects_updated_at before update on public.projects
  for each row execute function public.set_updated_at();

alter table public.projects enable row level security;
drop policy if exists projects_select_own on public.projects;
create policy projects_select_own on public.projects for select using (auth.uid() = owner_id);
drop policy if exists projects_insert_own on public.projects;
create policy projects_insert_own on public.projects for insert with check (auth.uid() = owner_id);
drop policy if exists projects_update_own on public.projects;
create policy projects_update_own on public.projects for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);
drop policy if exists projects_delete_own on public.projects;
create policy projects_delete_own on public.projects for delete using (auth.uid() = owner_id);

-- ---------------------------------------------------------------------------
-- Endpoints and immutable versions
-- ---------------------------------------------------------------------------

create table if not exists public.endpoints (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  slug text not null check (public.anyapi_is_valid_slug(slug)),
  method text not null default 'POST' check (method in ('GET','POST','PUT','PATCH','DELETE')),
  description text check (description is null or char_length(description) <= 1000),
  visibility text not null default 'public' check (visibility in ('public','private')),
  status text not null default 'draft' check (status in ('draft','published','disabled','failed_validation')),
  input_schema jsonb not null default '{"type":"object","properties":{}}'::jsonb,
  output_schema jsonb not null default '{"type":"object","properties":{}}'::jsonb,
  processor jsonb not null default '{"type":"visual","steps":[]}'::jsonb,
  response_config jsonb not null default '{"status_code":200,"headers":{}}'::jsonb,
  settings jsonb not null default '{"rate_limit_per_minute":60,"timeout_ms":10000}'::jsonb,
  validation_errors jsonb,
  published_version_id uuid,
  published_at timestamptz,
  draft_updated_at timestamptz not null default now(),
  archived_at timestamptz,
  total_executions bigint not null default 0,
  last_executed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, slug)
);

create index if not exists endpoints_project_idx on public.endpoints(project_id);
create index if not exists endpoints_owner_idx on public.endpoints(owner_id);

drop trigger if exists endpoints_updated_at on public.endpoints;
create trigger endpoints_updated_at before update on public.endpoints
  for each row execute function public.set_updated_at();

alter table public.endpoints enable row level security;
drop policy if exists endpoints_select_own on public.endpoints;
create policy endpoints_select_own on public.endpoints for select using (auth.uid() = owner_id);
drop policy if exists endpoints_insert_own on public.endpoints;
create policy endpoints_insert_own on public.endpoints for insert with check (
  auth.uid() = owner_id
  and exists (select 1 from public.projects p where p.id = endpoints.project_id and p.owner_id = auth.uid())
);
drop policy if exists endpoints_update_own on public.endpoints;
create policy endpoints_update_own on public.endpoints for update using (auth.uid() = owner_id) with check (
  auth.uid() = owner_id
  and exists (select 1 from public.projects p where p.id = endpoints.project_id and p.owner_id = auth.uid())
);
drop policy if exists endpoints_delete_own on public.endpoints;
create policy endpoints_delete_own on public.endpoints for delete using (auth.uid() = owner_id);

-- Publishing state is only changed by publish_endpoint / rollback_endpoint.
revoke update (published_version_id, published_at, total_executions, last_executed_at)
  on public.endpoints from authenticated, anon;

create table if not exists public.endpoint_versions (
  id uuid primary key default gen_random_uuid(),
  endpoint_id uuid not null references public.endpoints(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  version integer not null check (version > 0),
  config jsonb not null,
  notes text check (notes is null or char_length(notes) <= 500),
  created_at timestamptz not null default now(),
  unique (endpoint_id, version)
);

create index if not exists endpoint_versions_endpoint_idx on public.endpoint_versions(endpoint_id, version desc);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'endpoints_published_version_fk') then
    alter table public.endpoints
      add constraint endpoints_published_version_fk
      foreign key (published_version_id) references public.endpoint_versions(id)
      on delete set null deferrable initially deferred;
  end if;
end $$;

create or replace function public.endpoint_versions_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' then
    raise exception 'endpoint versions are immutable' using errcode = '42501';
  end if;
  -- Deletes are only allowed as part of deleting the parent endpoint.
  if exists (select 1 from public.endpoints e where e.id = old.endpoint_id) then
    raise exception 'endpoint versions are immutable' using errcode = '42501';
  end if;
  return old;
end;
$$;

drop trigger if exists endpoint_versions_immutable on public.endpoint_versions;
create trigger endpoint_versions_immutable before update or delete on public.endpoint_versions
  for each row execute function public.endpoint_versions_immutable();

alter table public.endpoint_versions enable row level security;
drop policy if exists endpoint_versions_select_own on public.endpoint_versions;
create policy endpoint_versions_select_own on public.endpoint_versions for select using (auth.uid() = owner_id);

-- ---------------------------------------------------------------------------
-- Connectors
-- ---------------------------------------------------------------------------

create table if not exists public.connectors (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  type text not null default 'http' check (type in ('http')),
  config jsonb not null default '{}'::jsonb,
  secret_ciphertext text,
  secret_hint text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists connectors_project_idx on public.connectors(project_id);

drop trigger if exists connectors_updated_at on public.connectors;
create trigger connectors_updated_at before update on public.connectors
  for each row execute function public.set_updated_at();

alter table public.connectors enable row level security;
drop policy if exists connectors_select_own on public.connectors;
create policy connectors_select_own on public.connectors for select using (auth.uid() = owner_id);
drop policy if exists connectors_insert_own on public.connectors;
create policy connectors_insert_own on public.connectors for insert with check (
  auth.uid() = owner_id
  and exists (select 1 from public.projects p where p.id = connectors.project_id and p.owner_id = auth.uid())
);
drop policy if exists connectors_update_own on public.connectors;
create policy connectors_update_own on public.connectors for update using (auth.uid() = owner_id) with check (
  auth.uid() = owner_id
  and exists (select 1 from public.projects p where p.id = connectors.project_id and p.owner_id = auth.uid())
);
drop policy if exists connectors_delete_own on public.connectors;
create policy connectors_delete_own on public.connectors for delete using (auth.uid() = owner_id);

-- Encrypted credentials are write-only for end users.
revoke select on public.connectors from anon, authenticated;
grant select (id, project_id, owner_id, name, type, config, secret_hint, created_at, updated_at)
  on public.connectors to authenticated;

create table if not exists public.endpoint_connectors (
  endpoint_id uuid not null references public.endpoints(id) on delete cascade,
  connector_id uuid not null references public.connectors(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (endpoint_id, connector_id)
);

create index if not exists endpoint_connectors_connector_idx on public.endpoint_connectors(connector_id);

alter table public.endpoint_connectors enable row level security;
drop policy if exists endpoint_connectors_select_own on public.endpoint_connectors;
create policy endpoint_connectors_select_own on public.endpoint_connectors for select using (auth.uid() = owner_id);
drop policy if exists endpoint_connectors_insert_own on public.endpoint_connectors;
create policy endpoint_connectors_insert_own on public.endpoint_connectors for insert with check (
  auth.uid() = owner_id
  and exists (
    select 1 from public.endpoints e
    join public.connectors c on c.project_id = e.project_id
    where e.id = endpoint_connectors.endpoint_id
      and c.id = endpoint_connectors.connector_id
      and e.owner_id = auth.uid()
      and c.owner_id = auth.uid()
  )
);
drop policy if exists endpoint_connectors_delete_own on public.endpoint_connectors;
create policy endpoint_connectors_delete_own on public.endpoint_connectors for delete using (auth.uid() = owner_id);

-- ---------------------------------------------------------------------------
-- API keys (only SHA-256 hashes are stored)
-- ---------------------------------------------------------------------------

create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete cascade,
  project_id uuid not null references public.projects(id) on delete cascade,
  endpoint_id uuid references public.endpoints(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  prefix text not null,
  key_hash text not null unique,
  last_used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists api_keys_project_idx on public.api_keys(project_id);

alter table public.api_keys enable row level security;
drop policy if exists api_keys_select_own on public.api_keys;
create policy api_keys_select_own on public.api_keys for select using (auth.uid() = owner_id);
drop policy if exists api_keys_insert_own on public.api_keys;
create policy api_keys_insert_own on public.api_keys for insert with check (
  auth.uid() = owner_id
  and exists (select 1 from public.projects p where p.id = api_keys.project_id and p.owner_id = auth.uid())
  and (
    api_keys.endpoint_id is null
    or exists (select 1 from public.endpoints e where e.id = api_keys.endpoint_id and e.project_id = api_keys.project_id)
  )
);
drop policy if exists api_keys_update_own on public.api_keys;
create policy api_keys_update_own on public.api_keys for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);
drop policy if exists api_keys_delete_own on public.api_keys;
create policy api_keys_delete_own on public.api_keys for delete using (auth.uid() = owner_id);

revoke select on public.api_keys from anon, authenticated;
grant select (id, owner_id, project_id, endpoint_id, name, prefix, last_used_at, revoked_at, created_at)
  on public.api_keys to authenticated;

-- ---------------------------------------------------------------------------
-- Executions (written by the gateway with the service role only)
-- ---------------------------------------------------------------------------

create table if not exists public.executions (
  id uuid primary key default gen_random_uuid(),
  endpoint_id uuid not null references public.endpoints(id) on delete cascade,
  owner_id uuid not null references public.profiles(id) on delete cascade,
  version_id uuid references public.endpoint_versions(id) on delete set null,
  version integer,
  source text not null check (source in ('live','test')),
  request_id text not null,
  method text not null,
  status_code integer not null,
  duration_ms integer not null,
  success boolean not null,
  error_type text,
  error_message text,
  request_body jsonb,
  response_body jsonb,
  logs jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists executions_endpoint_created_idx on public.executions(endpoint_id, created_at desc);
create index if not exists executions_owner_created_idx on public.executions(owner_id, created_at desc);
create index if not exists executions_created_idx on public.executions(created_at);

alter table public.executions enable row level security;
drop policy if exists executions_select_own on public.executions;
create policy executions_select_own on public.executions for select using (auth.uid() = owner_id);

create or replace function public.executions_bump_counters()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.source = 'live' then
    update public.endpoints
       set total_executions = total_executions + 1,
           last_executed_at = new.created_at
     where id = new.endpoint_id;
  end if;
  return new;
end;
$$;

drop trigger if exists executions_bump_counters on public.executions;
create trigger executions_bump_counters after insert on public.executions
  for each row execute function public.executions_bump_counters();

-- ---------------------------------------------------------------------------
-- Rate limiting (shared across serverless instances)
-- ---------------------------------------------------------------------------

create table if not exists public.rate_limits (
  key text not null,
  window_start timestamptz not null,
  count integer not null default 0,
  primary key (key, window_start)
);

alter table public.rate_limits enable row level security;

create or replace function public.consume_rate_limit(p_key text, p_limit integer, p_window_seconds integer)
returns table (allowed boolean, remaining integer, reset_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_window timestamptz := to_timestamp(floor(extract(epoch from now()) / p_window_seconds) * p_window_seconds);
  v_count integer;
begin
  insert into public.rate_limits as r (key, window_start, count)
  values (p_key, v_window, 1)
  on conflict (key, window_start) do update set count = r.count + 1
  returning r.count into v_count;

  return query select v_count <= p_limit,
                      greatest(p_limit - v_count, 0),
                      v_window + make_interval(secs => p_window_seconds);
end;
$$;

revoke all on function public.consume_rate_limit(text, integer, integer) from public, anon, authenticated;
grant execute on function public.consume_rate_limit(text, integer, integer) to service_role;

-- ---------------------------------------------------------------------------
-- Publishing (atomic) and rollback
-- ---------------------------------------------------------------------------

create or replace function public.publish_endpoint(p_endpoint_id uuid, p_config jsonb, p_notes text default null)
returns public.endpoint_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_endpoint public.endpoints;
  v_next integer;
  v_version public.endpoint_versions;
begin
  select * into v_endpoint from public.endpoints where id = p_endpoint_id for update;
  if not found or v_endpoint.owner_id is distinct from auth.uid() then
    raise exception 'endpoint not found' using errcode = 'P0002';
  end if;
  if v_endpoint.archived_at is not null then
    raise exception 'archived endpoints cannot be published' using errcode = '22023';
  end if;

  select coalesce(max(version), 0) + 1 into v_next
    from public.endpoint_versions where endpoint_id = p_endpoint_id;

  insert into public.endpoint_versions (endpoint_id, owner_id, version, config, notes)
  values (p_endpoint_id, v_endpoint.owner_id, v_next, p_config, p_notes)
  returning * into v_version;

  update public.endpoints
     set published_version_id = v_version.id,
         published_at = now(),
         status = 'published',
         validation_errors = null
   where id = p_endpoint_id;

  return v_version;
end;
$$;

revoke all on function public.publish_endpoint(uuid, jsonb, text) from public, anon;
grant execute on function public.publish_endpoint(uuid, jsonb, text) to authenticated;

create or replace function public.rollback_endpoint(p_endpoint_id uuid, p_version_id uuid)
returns public.endpoint_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_endpoint public.endpoints;
  v_version public.endpoint_versions;
begin
  select * into v_endpoint from public.endpoints where id = p_endpoint_id for update;
  if not found or v_endpoint.owner_id is distinct from auth.uid() then
    raise exception 'endpoint not found' using errcode = 'P0002';
  end if;

  select * into v_version from public.endpoint_versions
   where id = p_version_id and endpoint_id = p_endpoint_id;
  if not found then
    raise exception 'version not found' using errcode = 'P0002';
  end if;

  update public.endpoints
     set published_version_id = v_version.id,
         published_at = now(),
         status = 'published'
   where id = p_endpoint_id;

  return v_version;
end;
$$;

revoke all on function public.rollback_endpoint(uuid, uuid) from public, anon;
grant execute on function public.rollback_endpoint(uuid, uuid) to authenticated;

create or replace function public.set_endpoint_status(p_endpoint_id uuid, p_status text, p_errors jsonb default null)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_status not in ('draft','disabled','failed_validation','published') then
    raise exception 'invalid status' using errcode = '22023';
  end if;
  update public.endpoints
     set status = case
                    when p_status = 'published' and published_version_id is null then 'draft'
                    else p_status
                  end,
         validation_errors = p_errors
   where id = p_endpoint_id and owner_id = auth.uid();
  if not found then
    raise exception 'endpoint not found' using errcode = 'P0002';
  end if;
end;
$$;

revoke all on function public.set_endpoint_status(uuid, text, jsonb) from public, anon;
grant execute on function public.set_endpoint_status(uuid, text, jsonb) to authenticated;

-- ---------------------------------------------------------------------------
-- Gateway resolution (service role only)
-- ---------------------------------------------------------------------------

create or replace function public.resolve_endpoint(p_username text, p_project text, p_endpoint text)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'endpoint_id', e.id,
    'owner_id', e.owner_id,
    'project_id', p.id,
    'username', pr.username,
    'project_slug', p.slug,
    'project_name', p.name,
    'endpoint_slug', e.slug,
    'name', e.name,
    'status', e.status,
    'visibility', e.visibility,
    'archived', e.archived_at is not null,
    'version_id', v.id,
    'version', v.version,
    'published_at', e.published_at,
    'config', v.config
  )
  from public.profiles pr
  join public.projects p on p.owner_id = pr.id and p.slug = lower(p_project)
  join public.endpoints e on e.project_id = p.id and e.slug = lower(p_endpoint)
  left join public.endpoint_versions v on v.id = e.published_version_id
  where pr.username = lower(p_username);
$$;

revoke all on function public.resolve_endpoint(text, text, text) from public, anon, authenticated;
grant execute on function public.resolve_endpoint(text, text, text) to service_role;

-- ---------------------------------------------------------------------------
-- Retention
-- ---------------------------------------------------------------------------

create or replace function public.purge_old_executions(p_days integer default 30)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_deleted integer;
begin
  delete from public.executions where created_at < now() - make_interval(days => p_days);
  get diagnostics v_deleted = row_count;
  delete from public.rate_limits where window_start < now() - interval '1 day';
  return v_deleted;
end;
$$;

revoke all on function public.purge_old_executions(integer) from public, anon, authenticated;
grant execute on function public.purge_old_executions(integer) to service_role;
