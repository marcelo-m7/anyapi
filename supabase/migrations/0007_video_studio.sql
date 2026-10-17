-- AI Video Studio: isolated owner-scoped entities, no changes to AnyAPI's existing tables.
create table if not exists public.video_projects (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 title text not null check(length(title) between 1 and 160),
 topic text not null default '',
 script text not null default '',
 format text not null default 'both' check(format in ('documentary','short','both')),
 language text not null default 'pt-PT',
 status text not null default 'draft' check(status in ('draft','storyboard','ready')),
 created_at timestamptz not null default now()
);
create index if not exists video_projects_owner_created_idx on public.video_projects(owner_id,created_at desc);
create table if not exists public.video_scenes (
 id uuid primary key default gen_random_uuid(),
 project_id uuid not null references public.video_projects(id) on delete cascade,
 owner_id uuid not null references auth.users(id) on delete cascade,
 position integer not null default 0 check(position >= 0),
 title text not null default 'Nova cena',
 narration text not null default '',
 visual_prompt text not null default '',
 notes text not null default '',
 duration_seconds numeric(6,2) not null default 5 check(duration_seconds between 1 and 120),
 asset_url text,
 created_at timestamptz not null default now()
);
create index if not exists video_scenes_project_position_idx on public.video_scenes(project_id,position);
create index if not exists video_scenes_owner_idx on public.video_scenes(owner_id);
alter table public.video_projects enable row level security;
alter table public.video_scenes enable row level security;
create policy video_projects_owner on public.video_projects for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy video_scenes_owner on public.video_scenes for all to authenticated
 using ((select auth.uid()) = owner_id and exists (select 1 from public.video_projects p where p.id = project_id and p.owner_id = (select auth.uid())))
 with check ((select auth.uid()) = owner_id and exists (select 1 from public.video_projects p where p.id = project_id and p.owner_id = (select auth.uid())));
grant select, insert, update, delete on public.video_projects, public.video_scenes to authenticated;
revoke all on public.video_projects, public.video_scenes from anon;
