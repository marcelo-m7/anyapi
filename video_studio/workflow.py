"""Validated, framework-agnostic editorial operations for Video Studio."""
from __future__ import annotations

def validate_reorder(scene_ids: list[str], known: set[str]) -> bool:
    if not isinstance(scene_ids,list) or len(scene_ids)>500 or len(scene_ids)!=len(set(scene_ids)) or set(scene_ids)!=known:
        raise ValueError("Scene order must contain each scene exactly once")
    return True

def duplicate_scene(source:dict,position:int)->dict:
    """Never clone generated files; regeneration of the duplicate is deliberate."""
    if not isinstance(position,int) or position<0:raise ValueError("Invalid position")
    return {"project_id":source["project_id"],"owner_id":source["owner_id"],
            "position":position,"title":(source["title"]+" (cópia)")[:160],
            "narration":source.get("narration") or "",
            "visual_prompt":source.get("visual_prompt") or "",
            "notes":source.get("notes") or "",
            "duration_seconds":source["duration_seconds"],"trim_start_seconds":source.get("trim_start_seconds") or 0}

def render_readiness(scenes:list[dict])->dict:
    missing=[s["id"] for s in scenes if not (s.get("image_path") or s.get("video_path"))]
    return {"scene_count":len(scenes),
            "duration_seconds":sum(float(s.get("duration_seconds") or 0) for s in scenes),
            "missing_scene_ids":missing,
            "render_ready":bool(scenes) and not missing}

def timestamp_srt(t:float)->str:
    t=max(0,float(t));milliseconds=round(t*1000)
    hours,remaining=divmod(milliseconds,3600000)
    minutes,remaining=divmod(remaining,60000)
    seconds,ms=divmod(remaining,1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"

def validate_trim_start(value):
    if value is None:return 0
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not 0<=value<=600:
        raise ValueError("Trim offset must be from 0 to 600 seconds")
    return value
