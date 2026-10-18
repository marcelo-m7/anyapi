-- Non-destructive in-point for source footage; zero means start at source beginning.
alter table public.video_scenes add column if not exists trim_start_seconds numeric(8,2) not null default 0 check(trim_start_seconds between 0 and 600);
