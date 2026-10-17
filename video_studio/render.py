"""Offline deterministic MP4 renderer for exported Video Studio manifests.

Renders a sequence of local image assets, without downloading untrusted URLs.
Requires ffmpeg on PATH. No AI API keys or external costs are involved.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}

def render(manifest: dict, assets_dir: Path, output: Path, *, fps: int = 24):
    if fps not in (24, 25, 30):
        raise ValueError("fps must be 24, 25 or 30")
    scenes = manifest.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Manifest must contain scenes")
    if not assets_dir.is_dir():
        raise ValueError("Assets directory does not exist")
    assets_dir = assets_dir.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="video-studio-") as temp:
        clips = []
        for i, scene in enumerate(scenes):
            identifier = scene.get("id")
            if not isinstance(identifier, str) or not identifier.replace("-", "").isalnum():
                raise ValueError("Unsafe scene identifier")
            duration = float(scene.get("duration_seconds", 0))
            if not 1 <= duration <= 120:
                raise ValueError("Invalid scene duration")
            options = [assets_dir / (identifier + ext) for ext in SUPPORTED]
            image = next((p for p in options if p.is_file() and p.resolve().is_relative_to(assets_dir)), None)
            if image is None:
                raise ValueError(f"Missing image asset for scene {identifier}")
            clip = Path(temp) / f"clip-{i:04d}.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-i", str(image), "-t", str(duration),
                "-vf", f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(clip),
            ], check=True, timeout=300)
            clips.append(clip)
        concat = Path(temp) / "concat.txt"
        concat.write_text("".join("file '" + str(p) + "'\n" for p in clips), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy", "-movflags", "+faststart", str(output),
        ], check=True, timeout=600)
    return output

def main():
    parser = argparse.ArgumentParser(description="Render Video Studio scene images to an MP4")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(render(data, args.assets_dir, args.output))

if __name__ == "__main__":
    main()
