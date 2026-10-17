"""Personal video studio, isolated from the AnyAPI endpoint builder."""
from __future__ import annotations
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from anyapi.auth import current_user, login_required, verify_csrf
from anyapi.supabase import SupabaseError

bp = Blueprint("video_studio", __name__)
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
    allowed = {k: v for k, v in data.items() if k in ("title", "topic", "script", "status", "format")}
    if not allowed:
        return fail("Nothing to update.")
    if "title" in allowed and (not isinstance(allowed["title"], str) or not 1 <= len(allowed["title"].strip()) <= 160):
        return fail("Invalid title.")
    if "format" in allowed and allowed["format"] not in FORMATS:
        return fail("Invalid format.")
    if "status" in allowed and allowed["status"] not in ("draft", "storyboard", "ready"):
        return fail("Invalid status.")
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
