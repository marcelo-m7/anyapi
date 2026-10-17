-- Editorial consistency, provenance and soundtrack metadata.
alter table public.video_projects
  add column if not exists visual_bible text not null default '',
  add column if not exists sources jsonb not null default '[]'::jsonb,
  add column if not exists soundtrack_path text,
  add column if not exists music_volume numeric(3,2) not null default 0.15
    check (music_volume between 0 and 1);
