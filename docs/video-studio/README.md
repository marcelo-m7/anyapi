# AI Video Studio — Personal MVP

An isolated Flask Blueprint mounted on the existing AnyAPI application at `/video-studio`. Reuses existing encrypted session/Supabase authentication, CSRF protection, and per-user PostgREST RLS.

## Implemented
- Private dashboard, project creation, script editor, scene CRUD, visual storyboard and timeline.
- Scene inspector: narration, video prompt, HTTPS asset URL, duration.
- Downloadable production manifest JSON for offline rendering.
- Owner-scoped REST endpoints and SQL RLS migration.

## Not implemented (do not describe as E2E cinematic generation)
- Paid AI video/image/voice APIs, worker queues, FFmpeg render, generated subtitles, timeline drag-and-drop, 9:16 export.
- No secrets or third-party bills are required for the current functionality.
- Offline MP4 render from local JPG/PNG/WebP assets is available via FFmpeg CLI; it does not yet include audio or generated visuals.
- Existing AnyAPI landing, project APIs and open PRs are unchanged.

## Configuration
1. Apply `supabase/migrations/0007_video_studio.sql` to a verified development database after checking existing migrations. **Do not apply automatically to the shared AnyAPI production database**.
2. Set existing AnyAPI Supabase/auth environment variables.
3. Run `pip install -e '.[test]'`, then `gunicorn main:app`.
4. Sign in and open `/video-studio`.

## HTTP endpoints
- `GET/POST /_api/video-studio/projects`
- `GET/PATCH /_api/video-studio/projects/<uuid>`
- `POST /_api/video-studio/projects/<uuid>/scenes`
- `PATCH/DELETE /_api/video-studio/scenes/<uuid>`
- `GET /_api/video-studio/projects/<uuid>/manifest`

Mutation requires the existing AnyAPI CSRF token. Every PostgREST query uses the end-user JWT and explicit owner filters; database policies enforce ownership as a second layer.

## Next iterations
Provider adapters (mock provider and credentialed production providers), async render queue with cancel/retry, durable media storage, Remotion/FFmpeg worker and independent visual QA in staging.

## Offline render

Install `ffmpeg` and place images in a directory named `<scene-id>.png` (or jpg/jpeg/webp) for each scene. Export the manifest from the editor, then run:

```sh
python -m video_studio.render video-manifest.json --assets-dir ./scene-images --output ./documentary.mp4
```

This creates a silent 1920×1080 H.264 MP4 with fixed-duration scenes. It makes no network requests and refuses missing assets or unsafe scene IDs.
