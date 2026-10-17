# Vercel deployment boundaries — AI Video Studio

## Frontend and Flask
The existing Vercel project for AnyAPI can deploy Flask entrypoint `main.py` from GitHub `main`. The editor route is `/video-studio`, and all its JSON APIs live under `/_api/video-studio/`. Signed-in users can inspect `/_api/video-studio/readiness` to see provider configuration booleans without exposing secrets.

Production Vercel environment must contain `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ANYAPI_SECRET_KEY`, `ANYAPI_ENCRYPTION_KEY`, `ANYAPI_PUBLIC_URL`, `OPENAI_API_KEY`, and `RUNWAYML_API_SECRET` (optional for paid video).

Configure the Supabase Auth redirect allowlist for the exact Vercel deployment domain `/auth/callback`.

## Long-running jobs
Do **not** run `python -m video_studio.worker` inside a Vercel Python function. Serverless instances are transient, and the current worker requires a persistent runtime, FFmpeg and media processing. Deploy the existing `deploy/video-studio/compose.yml` worker service to a persistent Docker host such as the owner's Coolify installation. Point its environment to the **same** Supabase project, and keep the service role credentials only in secured server-side environment variables. Scale to one worker initially.

Jobs remain queued until this worker is running. The deployed web application does not imply the video generation pipeline is operational.

## Connected-account status
Supabase project `aiosqtyvzopdtsolkpfg` was restored and migrations applied, but a Vercel connector session is required to inspect real deployments and set/check environment variables. Repo pushes alone do not prove successful deployment.

## Frontend design
The Obsidian Void editor restyles the existing functional Flask/Jinja interface following the supplied Stitch reference. Components retain API bindings, CSRF and user-specific data. No untrusted `code.html` execution was introduced.
