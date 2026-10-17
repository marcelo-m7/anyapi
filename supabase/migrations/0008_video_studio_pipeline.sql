-- Video Studio runtime. Apply after 0007_video_studio.sql.
alter table public.video_scenes
  add column if not exists image_path text,
  add column if not exists video_path text,
  add column if not exists voice_path text,
  add column if not exists subtitles_path text;
create table if not exists public.video_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  scene_id uuid references public.video_scenes(id) on delete cascade,
  operation text not null check (operation in ('image','voice','video','render','episode')),
  options jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (status in ('queued','running','completed','failed','cancelled')),
  progress integer not null default 0 check (progress between 0 and 100),
  attempt integer not null default 0,
  error text,
  result_path text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index if not exists video_jobs_claim_idx on public.video_jobs(status, created_at) where status='queued';
create index if not exists video_jobs_owner_idx on public.video_jobs(owner_id,project_id,created_at desc);
alter table public.video_jobs enable row level security;
create policy video_jobs_read on public.video_jobs for select to authenticated
  using (owner_id=(select auth.uid()));
create policy video_jobs_create on public.video_jobs for insert to authenticated
  with check (owner_id=(select auth.uid()) and status='queued'
  and exists(select 1 from public.video_projects p where p.id=project_id and p.owner_id=(select auth.uid()))
  and (scene_id is null or exists(select 1 from public.video_scenes s where s.id=scene_id and s.project_id=project_id and s.owner_id=(select auth.uid()))));
grant select, insert on public.video_jobs to authenticated;
revoke all on public.video_jobs from anon;

-- Atomic job claiming from a trusted worker; never callable by browsers.
create or replace function public.video_claim_job()
returns setof public.video_jobs
language plpgsql security definer
set search_path = ''
as $$
begin
  return query
  update public.video_jobs j
  set status='running', started_at=now(), attempt=j.attempt+1
  where j.id = (
    select id from public.video_jobs
    where status='queued'
    order by created_at, id
    for update skip locked limit 1
  )
  returning j.*;
end;
$$;
revoke all on function public.video_claim_job() from public, anon, authenticated;
grant execute on function public.video_claim_job() to service_role;
-- Storage bucket is provisioned separately when Supabase Storage service is available.
-- See docs/video-studio/STORAGE.md for setup instructions.
