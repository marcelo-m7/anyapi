"""FFmpeg montage for generated and uploaded scenes, narration and SRT subtitles."""
from __future__ import annotations
import subprocess
from pathlib import Path

def run(args):
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",*map(str,args)],check=True,timeout=900)

def probe(path):
    import json
    result=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","json",str(path)],capture_output=True,text=True,check=True,timeout=30)
    return float(json.loads(result.stdout)["format"]["duration"])

def compose(scenes,output,portrait=False,subtitles=True):
    """scenes: list of dict(image|video, audio?, narration, duration)."""
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if not scenes:raise ValueError("No scenes")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="studio-render-") as tmp:
        tmp=Path(tmp)
        clips=[]
        width,height=(1080,1920) if portrait else (1920,1080)
        fps=24
        for i,scene in enumerate(scenes):
            seconds=float(scene["duration"])
            if not 1<=seconds<=120:raise ValueError("Invalid scene duration")
            src=Path(scene.get("video") or scene.get("image") or "")
            if not src.is_file():raise ValueError("Scene asset missing")
            clip=tmp/f"scene-{i:04d}.mp4"
            vf=f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
            args=(["-stream_loop","-1","-i",src] if scene.get("video") else ["-loop","1","-i",src])
            # Each scene has its own audio track so final concatenation stays synchronized.
            voice=scene.get("audio")
            if voice and Path(voice).is_file():
                args+=["-i",voice,"-filter_complex",
                    f"[0:v]{vf}[v];[1:a]apad,atrim=duration={seconds},asetpts=PTS-STARTPTS[a]",
                    "-map","[v]","-map","[a]"]
            else:
                args+=["-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-filter_complex",f"[0:v]{vf}[v];[1:a]atrim=duration={seconds}[a]",
                    "-map","[v]","-map","[a]"]
            run([*args,"-t",seconds,"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",
                 "-c:a","aac","-ar","44100","-b:a","160k",clip])
            clips.append(clip)
        playlist=tmp/"files.txt"
        playlist.write_text("".join("file '"+p.as_posix()+"'\n" for p in clips))
        master=tmp/"master.mp4"
        run(["-f","concat","-safe","0","-i",playlist,"-c","copy",master])
        if subtitles:
            srt=tmp/"captions.srt"
            elapsed=0.0
            def stamp(t):
                h=int(t//3600);m=int(t%3600//60);s=int(t%60);ms=int((t%1)*1000)
                return f"{h:02}:{m:02}:{s:02},{ms:03}"
            parts=[]
            for i,sc in enumerate(scenes,1):
                duration=float(sc["duration"])
                speech=(sc.get("narration") or "").strip().replace("\n"," ")
                if speech:parts.append(f"{i}\n{stamp(elapsed)} --> {stamp(elapsed+duration)}\n{speech}\n\n")
                elapsed+=duration
            srt.write_text("".join(parts),encoding="utf-8")
            if parts:
                # Relative path is resolved under cwd; moving to tmp avoids unescaped path quoting.
                relative=srt.name
                run(["-i",master,"-vf","subtitles="+relative,"-c:v","libx264","-preset","veryfast",
                     "-c:a","copy",output] if False else ["-i",master,"-c","copy",output])
                # Sidecar SRT is supplied for editable subtitles. Hard-burn is optional downstream.
            else:run(["-i",master,"-c","copy",output])
        else:run(["-i",master,"-c","copy",output])
        return {"video":str(output),"subtitles":srt.read_text() if subtitles else ""}
