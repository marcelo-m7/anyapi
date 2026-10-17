"""Run separately: python -m video_studio.worker. Polls private Supabase jobs."""
from __future__ import annotations
import os
import time
from pathlib import Path
from datetime import datetime,timezone
from tempfile import TemporaryDirectory
from anyapi.config import load_settings
from anyapi.supabase import Supabase
from .providers import Media, ProviderError, image, voice, video
from .render_engine import compose

def run_job(job,sb,media):
    owner=str(job["owner_id"]);project=str(job["project_id"])
    op=job["operation"];scene_id=job.get("scene_id")
    db=sb.service()
    if op in ("image","video","voice") and not scene_id:
        raise ValueError("Scene id required")
    if op in ("image","video","voice"):
        scene=db.select_one("video_scenes",{"id":f"eq.{scene_id}","owner_id":f"eq.{owner}","project_id":f"eq.{project}"})
        if not scene:raise ValueError("Scene does not belong to project")
        path=f"{owner}/{project}/{scene_id}/{op}-{job['id']}."
        if op=="image":
            data=image(scene["visual_prompt"],bool(job.get("options",{}).get("portrait")))
            path+="png";mime="image/png";field="image_path"
        elif op=="voice":
            data=voice(scene["narration"]);path+="mp3";mime="audio/mpeg";field="voice_path"
        else:
            ref=media.get(scene["image_path"]) if scene.get("image_path") else None
            data=video(scene["visual_prompt"],ref);path+="mp4";mime="video/mp4";field="video_path"
        media.put(path,data,mime)
        db.update("video_scenes",{"id":f"eq.{scene_id}","owner_id":f"eq.{owner}"},{field:path})
        return path
    if op in ("render","episode"):
        scenes=db.select("video_scenes",{"owner_id":f"eq.{owner}","project_id":f"eq.{project}",
            "select":"*","order":"position.asc"})
        if not scenes:raise ValueError("Project has no scenes")
        with TemporaryDirectory(prefix="ai-video-studio-") as directory:
            directory=Path(directory)
            sources=[]
            for i,s in enumerate(scenes):
                asset=s.get("video_path") or s.get("image_path")
                if not asset:raise ValueError(f"Scene {s['id']} needs an image or video")
                suffix=".mp4" if s.get("video_path") else ".png"
                file=directory/f"asset-{i}{suffix}"
                file.write_bytes(media.get(asset))
                audio=None
                if s.get("voice_path"):
                    audio=directory/f"narration-{i}.mp3"
                    audio.write_bytes(media.get(s["voice_path"]))
                sources.append({"video":file if s.get("video_path") else None,
                    "image":None if s.get("video_path") else file,"audio":audio,
                    "narration":s.get("narration",""),"duration":float(s["duration_seconds"])})
            portrait=bool(job.get("options",{}).get("portrait"))
            output=directory/"final.mp4"
            render=compose(sources,output,portrait=portrait)
            prefix="vertical" if portrait else "horizontal"
            target=f"{owner}/{project}/renders/{job['id']}-{prefix}.mp4"
            media.put(target,output.read_bytes(),"video/mp4")
            if render["subtitles"]:
                media.put(target+".srt",render["subtitles"].encode(),"text/plain")
            return target
    raise ValueError("Unsupported job operation")

def process_once():
    sb=Supabase(load_settings())
    rows=sb.service().rpc("video_claim_job",{})
    if not rows:return False
    job=rows[0] if isinstance(rows,list) else rows
    try:
        result=run_job(job,sb,Media())
        sb.service().update("video_jobs",{"id":f"eq.{job['id']}"},
            {"status":"completed","progress":100,"result_path":result,"finished_at":datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        import logging
        logging.exception("Video job %s failed",job["id"])
        sb.service().update("video_jobs",{"id":f"eq.{job['id']}"},
            {"status":"failed","error":str(exc)[:500],"finished_at":datetime.now(timezone.utc).isoformat()})
    return True

def main():
    interval=max(1,int(os.getenv("STUDIO_POLL_SECONDS","4")))
    while True:
        try:
            if not process_once():time.sleep(interval)
        except Exception:
            import logging
            logging.exception("Video worker error")
            time.sleep(interval)

if __name__=="__main__":main()
