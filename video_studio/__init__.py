"""Personal video studio, isolated from the AnyAPI endpoint builder."""
from __future__ import annotations
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from anyapi.auth import current_user, login_required, verify_csrf
from anyapi.supabase import SupabaseError

bp = Blueprint("video_studio", __name__)

@bp.before_request
def studio_upload_limit():
    # Only media upload needs a higher ceiling than the AnyAPI JSON gateway.
    if request.endpoint in ("video_studio.upload_scene_asset", "video_studio.upload_soundtrack"):
        request.max_content_length = 20_100_000
FORMATS = {"documentary", "short", "both"}
SCENE_FIELDS = {"title", "narration", "visual_prompt", "duration_seconds", "position", "asset_url", "notes"}

def client():
    user = current_user()
    return current_app.extensions["anyapi.supabase"].user(user["access_token"])

def uid():
    return current_user()["id"]

def fail(message, code=400):
    return jsonify(error={"message": message}), code

def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def project_or_404(project_id):
    return client().select_one("video_projects", {"id": f"eq.{project_id}", "owner_id": f"eq.{uid()}", "select": "*"})

def scene_or_404(scene_id):
    return client().select_one("video_scenes", {"id": f"eq.{scene_id}", "owner_id": f"eq.{uid()}", "select": "*"})

@bp.errorhandler(SupabaseError)
def db_error(exc):
    current_app.logger.warning("video_studio database error %s %s", exc.status, exc.code)
    return fail("Video Studio database unavailable. Check migrations and configuration.", 503)

@bp.get("/video-studio")
@login_required
def editor():
    return render_template("video_studio.html", csrf=__import__("anyapi.auth", fromlist=["csrf_token"]).csrf_token())

@bp.get("/_api/video-studio/projects")
@login_required
def projects():
    return jsonify(client().select("video_projects", {"owner_id": f"eq.{uid()}", "select": "*", "order": "created_at.desc", "limit": "100"}))

@bp.post("/_api/video-studio/projects")
@login_required
def create_project():
    verify_csrf()
    data = body()
    title = str(data.get("title", "")).strip()
    if not 1 <= len(title) <= 160:
        return fail("Title must be between 1 and 160 characters.")
    kind = data.get("format", "both")
    if kind not in FORMATS:
        return fail("Invalid format.")
    result = client().insert("video_projects", {"owner_id": uid(), "title": title, "topic": str(data.get("topic", title))[:1000], "format": kind, "language": "pt-PT"})
    return jsonify(result), 201

@bp.get("/_api/video-studio/projects/<uuid:project_id>")
@login_required
def get_project(project_id):
    project = project_or_404(project_id)
    if not project:
        return fail("Project not found.", 404)
    scenes = client().select("video_scenes", {"project_id": f"eq.{project_id}", "owner_id": f"eq.{uid()}", "select": "*", "order": "position.asc", "limit": "500"})
    return jsonify({**project, "scenes": scenes})

@bp.patch("/_api/video-studio/projects/<uuid:project_id>")
@login_required
def update_project(project_id):
    verify_csrf()
    if not project_or_404(project_id):
        return fail("Project not found.", 404)
    data = body()
    allowed = {k: v for k, v in data.items() if k in ("title", "topic", "script", "status", "format", "visual_bible", "sources", "music_volume")}
    if not allowed:
        return fail("Nothing to update.")
    if "title" in allowed and (not isinstance(allowed["title"], str) or not 1 <= len(allowed["title"].strip()) <= 160):
        return fail("Invalid title.")
    if "format" in allowed and allowed["format"] not in FORMATS:
        return fail("Invalid format.")
    if "status" in allowed and allowed["status"] not in ("draft", "storyboard", "ready"):
        return fail("Invalid status.")
    if "visual_bible" in allowed and (not isinstance(allowed["visual_bible"],str) or len(allowed["visual_bible"])>5000):return fail("Invalid visual bible.")
    if "sources" in allowed and (not isinstance(allowed["sources"],list) or len(allowed["sources"])>100):return fail("Invalid sources.")
    if "music_volume" in allowed and (not isinstance(allowed["music_volume"],(int,float)) or not 0<=allowed["music_volume"]<=1):return fail("Invalid music level.")
    rows = client().update("video_projects", {"id": f"eq.{project_id}", "owner_id": f"eq.{uid()}"}, allowed)
    return jsonify(rows[0]) if rows else fail("Project not found.", 404)

@bp.post("/_api/video-studio/projects/<uuid:project_id>/scenes")
@login_required
def add_scene(project_id):
    verify_csrf()
    if not project_or_404(project_id):
        return fail("Project not found.", 404)
    data = body()
    duration = data.get("duration_seconds", 5)
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 1 <= duration <= 120:
        return fail("Duration must be between 1 and 120 seconds.")
    rows = client().select("video_scenes", {"project_id": f"eq.{project_id}", "owner_id": f"eq.{uid()}", "select": "position", "order": "position.desc", "limit": "1"})
    position = (rows[0]["position"] + 1) if rows else 0
    row = {"project_id": str(project_id), "owner_id": uid(), "position": position, "title": str(data.get("title", "Nova cena"))[:160], "narration": str(data.get("narration", ""))[:10000], "visual_prompt": str(data.get("visual_prompt", ""))[:10000], "duration_seconds": duration}
    return jsonify(client().insert("video_scenes", row)), 201

@bp.patch("/_api/video-studio/scenes/<uuid:scene_id>")
@login_required
def update_scene(scene_id):
    verify_csrf()
    if not scene_or_404(scene_id):
        return fail("Scene not found.", 404)
    values = {k: v for k, v in body().items() if k in SCENE_FIELDS}
    if not values:
        return fail("Nothing to update.")
    if "duration_seconds" in values and (not isinstance(values["duration_seconds"], (float, int)) or isinstance(values["duration_seconds"], bool) or not 1 <= values["duration_seconds"] <= 120):
        return fail("Invalid duration.")
    for field in ("title", "narration", "visual_prompt", "notes"):
        if field in values and (not isinstance(values[field], str) or len(values[field]) > 10000):
            return fail("Invalid text field.")
    if "asset_url" in values and values["asset_url"] is not None and (not isinstance(values["asset_url"], str) or len(values["asset_url"]) > 2000 or not values["asset_url"].startswith("https://")):
        return fail("Asset URL must use HTTPS.")
    rows = client().update("video_scenes", {"id": f"eq.{scene_id}", "owner_id": f"eq.{uid()}"}, values)
    return jsonify(rows[0]) if rows else fail("Scene not found.", 404)

@bp.delete("/_api/video-studio/scenes/<uuid:scene_id>")
@login_required
def delete_scene(scene_id):
    verify_csrf()
    if not scene_or_404(scene_id):
        return fail("Scene not found.", 404)
    client().delete("video_scenes", {"id": f"eq.{scene_id}", "owner_id": f"eq.{uid()}"})
    return "", 204

@bp.get("/_api/video-studio/projects/<uuid:project_id>/manifest")
@login_required
def manifest(project_id):
    project = project_or_404(project_id)
    if not project:
        return fail("Project not found.", 404)
    scenes = client().select("video_scenes", {"project_id": f"eq.{project_id}", "owner_id": f"eq.{uid()}", "select": "*", "order": "position.asc"})
    return jsonify({"version": 1, "project_id": str(project_id), "title": project["title"], "format": project["format"], "language": project["language"], "scenes": scenes, "duration_seconds": sum(float(s["duration_seconds"]) for s in scenes)})

@bp.post("/_api/video-studio/projects/<uuid:project_id>/storyboard-draft")
@login_required
def ai_storyboard_draft(project_id):
    verify_csrf()
    project = project_or_404(project_id)
    if not project:
        return fail("Project not found.", 404)
    from .ai import StoryboardError, generate_storyboard
    try:
        scenes = generate_storyboard(project["topic"] or project["title"], project.get("script", ""))
    except StoryboardError as exc:
        return fail(str(exc), 422)
    return jsonify({"scenes": scenes, "saved": False})

@bp.get("/_api/video-studio/projects/<uuid:project_id>/jobs")
@login_required
def list_jobs(project_id):
    if not project_or_404(project_id):return fail("Project not found.",404)
    jobs=client().select("video_jobs",{"owner_id":f"eq.{uid()}","project_id":f"eq.{project_id}","select":"*","order":"created_at.desc","limit":"100"})
    return jsonify(jobs)

@bp.post("/_api/video-studio/projects/<uuid:project_id>/jobs")
@login_required
def enqueue_job(project_id):
    verify_csrf()
    if not project_or_404(project_id):return fail("Project not found.",404)
    data=body()
    operation=data.get("operation")
    if operation not in ("image","video","voice","render","episode"):
        return fail("Invalid operation")
    scene_id=data.get("scene_id")
    if operation in ("image","video","voice"):
        from uuid import UUID
        try:scene_uuid=UUID(str(scene_id))
        except (ValueError,TypeError):return fail("Valid scene_id required")
        sc=scene_or_404(scene_uuid)
        if not sc or sc["project_id"]!=str(project_id):
            return fail("Scene not found.",404)
    else:
        scene_id=None
    options={"portrait":data.get("portrait") is True}
    row={"owner_id":uid(),"project_id":str(project_id),"scene_id":str(scene_id) if scene_id else None,
         "operation":operation,"options":options}
    job=client().insert("video_jobs",row)
    return jsonify(job),201

@bp.get("/_api/video-studio/projects/<uuid:project_id>/media")
@login_required
def project_media(project_id):
    """Only allow signing assets referenced by the authenticated owner's project."""
    if not project_or_404(project_id):return fail("Project not found.",404)
    path=request.args.get("path","")
    if not path or not path.startswith(f"{uid()}/{project_id}/") or ".." in path:
        return fail("Invalid asset path")
    scenes=client().select("video_scenes",{"owner_id":f"eq.{uid()}","project_id":f"eq.{project_id}",
         "select":"image_path,video_path,voice_path,subtitles_path"})
    jobs=client().select("video_jobs",{"owner_id":f"eq.{uid()}","project_id":f"eq.{project_id}",
         "select":"result_path","status":"eq.completed"})
    allowed={x.get(field) for x in scenes for field in ("image_path","video_path","voice_path","subtitles_path")}
    project=project_or_404(project_id)
    allowed.add(project.get("soundtrack_path"))
    allowed.update(j.get("result_path") for j in jobs)
    allowed.update(str(j.get("result_path"))+".srt" for j in jobs if j.get("result_path"))
    if path not in allowed:return fail("Asset not found.",404)
    from .providers import Media,ProviderError
    try:return jsonify(url=Media().signed(path))
    except ProviderError:return fail("Media unavailable.",503)

@bp.post("/_api/video-studio/projects/<uuid:project_id>/upload")
@login_required
def upload_scene_asset(project_id):
    verify_csrf()
    if not project_or_404(project_id):return fail("Project not found.",404)
    from uuid import UUID
    try:scene_id=UUID(request.form["scene_id"])
    except (ValueError,KeyError):return fail("Scene id required.")
    scene=scene_or_404(scene_id)
    if not scene or scene["project_id"]!=str(project_id):return fail("Scene not found.",404)
    upload=request.files.get("file")
    if not upload:return fail("File required.")
    data=upload.read(20_000_001)
    if len(data)>20_000_000:return fail("File exceeds 20MB.")
    header=data[:16]
    if header.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):suffix,mime="png","image/png"
    elif header.startswith(b"\\xff\\xd8\\xff"):suffix,mime="jpg","image/jpeg"
    elif header.startswith(b"RIFF") and data[8:12]==b"WEBP":suffix,mime="webp","image/webp"
    else:return fail("Only PNG, JPEG or WebP uploads are accepted.")
    path=f"{uid()}/{project_id}/{scene_id}/manual-{__import__('uuid').uuid4()}.{suffix}"
    from .providers import Media,ProviderError
    try:Media().put(path,data,mime)
    except ProviderError:return fail("Media unavailable.",503)
    client().update("video_scenes",{"id":f"eq.{scene_id}","owner_id":f"eq.{uid()}"},{"image_path":path})
    return jsonify(path=path),201

@bp.post("/_api/video-studio/projects/<uuid:project_id>/reorder")
@login_required
def reorder_scenes(project_id):
    verify_csrf()
    if not project_or_404(project_id):return fail("Project not found.",404)
    values=body().get("scene_ids")
    if not isinstance(values,list) or not 1<=len(values)<=500 or len(values)!=len(set(map(str,values))):
        return fail("Invalid scene order.")
    scenes=client().select("video_scenes",{"owner_id":f"eq.{uid()}","project_id":f"eq.{project_id}","select":"id"})
    known={s["id"] for s in scenes}
    if known!=set(values):return fail("Scene order must contain each scene exactly once.")
    for index,scene_id in enumerate(values):
        client().update("video_scenes",{"owner_id":f"eq.{uid()}","project_id":f"eq.{project_id}","id":f"eq.{scene_id}"},{"position":index})
    return jsonify({"ok":True})

@bp.post("/_api/video-studio/projects/<uuid:project_id>/script-draft")
@login_required
def script_draft(project_id):
    verify_csrf()
    project=project_or_404(project_id)
    if not project:return fail("Project not found.",404)
    from .ai import StoryboardError,generate_script
    data=body()
    minutes=data.get("duration_minutes",5)
    if not isinstance(minutes,int) or isinstance(minutes,bool) or not 1<=minutes<=20:
        return fail("Duration must be 1-20 minutes.")
    try:
        script=generate_script(project.get("topic") or project["title"],duration_minutes=minutes,
            style=data.get("style","") if isinstance(data.get("style",""),str) else "")
    except StoryboardError as exc:return fail(str(exc),422)
    return jsonify({"script":script,"saved":False})

@bp.post("/_api/video-studio/projects/<uuid:project_id>/soundtrack")
@login_required
def upload_soundtrack(project_id):
    verify_csrf()
    if not project_or_404(project_id):return fail("Project not found.",404)
    upload=request.files.get("file")
    if not upload:return fail("Soundtrack file required.")
    data=upload.read(20_000_001)
    if len(data)>20_000_000:return fail("Soundtrack exceeds 20 MB.")
    # MP3 sync/header ID3, or RIFF WAVE.
    if data.startswith(b"ID3") or (len(data)>2 and data[0]==255 and (data[1]&0xE0)==0xE0):
        suffix,mime="mp3","audio/mpeg"
    elif data.startswith(b"RIFF") and data[8:12]==b"WAVE":
        suffix,mime="wav","audio/wav"
    else:return fail("Only MP3 or WAV supported.")
    from uuid import uuid4
    path=f"{uid()}/{project_id}/music/{uuid4()}.{suffix}"
    from .providers import Media,ProviderError
    try:Media().put(path,data,mime)
    except ProviderError:return fail("Media unavailable.",503)
    client().update("video_projects",{"id":f"eq.{project_id}","owner_id":f"eq.{uid()}"},{"soundtrack_path":path})
    return jsonify(path=path),201
