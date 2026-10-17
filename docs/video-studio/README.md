# AI Video Studio — local setup

Personal video-creation workspace integrated into the AnyAPI Flask application.

## Architecture
- Existing Flask and Supabase Auth session, login and CSRF.
- Owner-scoped projects, scenes, jobs and private storage; changes isolated to video_studio package.
- Worker polls atomic Supabase job claims; OpenAI provides storyboards/images/voice and Runway provides video.
- FFmpeg composes 1080p H.264 horizontal or vertical exports and sidecar SRT.

## Setup
1. Create or restore a development Supabase project and apply existing AnyAPI migrations plus 0007_video_studio.sql and 0008_video_studio_pipeline.sql.
2. Copy .env.example to .env and populate the existing SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY and ANYAPI keys.
3. Set OPENAI_API_KEY and RUNWAYML_API_SECRET for paid generation.
4. Optional models: STUDIO_IMAGE_MODEL=gpt-image-1, STUDIO_VOICE_MODEL=gpt-4o-mini-tts, STUDIO_VOICE=coral, STUDIO_VIDEO_MODEL=gen4.5.
5. Run docker compose -f deploy/video-studio/compose.yml up --build.
6. Open http://localhost:8000/video-studio after signing in.

## Usage
Create a project, write a script, draft scenes with optional AI, attach/upload reference images, generate voice/images/video selectively, render 16:9 or 9:16 and open signed media links in the editor.
Scene-level regenerations avoid regenerating the whole episode. Production-quality consistency is guided by video_studio/CINEMATOGRAPHY.md.

## Limitations
- The connected Supabase project was INACTIVE at inspection. No migrations were executed against it.
- Live provider and authenticated end-to-end verification are intentionally left for local validation.
- Subtitle files are SRT sidecars, not hard-burned captions; no soundtrack mixing or final audio mastering.
- The frontend is the existing Flask-integrated JavaScript stack, not React.
- Worker jobs incur third-party usage charges; the editor asks before paid generation.
- Public hosting needs additional security, rate-limit, resource and cost controls.