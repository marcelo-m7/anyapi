"""Conservative validation for direct browser-to-Supabase uploads."""
from __future__ import annotations

ALLOWED={
    "image/png":(".png","image_path",25_000_000),
    "image/jpeg":(".jpg","image_path",25_000_000),
    "image/webp":(".webp","image_path",25_000_000),
    "video/mp4":(".mp4","video_path",100_000_000),
    "audio/mpeg":(".mp3","voice_path",25_000_000),
    "audio/wav":(".wav","voice_path",25_000_000),
}
def validate_upload(mime,size):
    if mime not in ALLOWED or type(size) is not int or not 0<size<=ALLOWED[mime][2]:
        raise ValueError("Unsupported media type or size")
    return ALLOWED[mime]

def allowed_path(path,owner,project,scene):
    if not isinstance(path,str) or ".." in path or "//" in path:return False
    prefix=f"{owner}/{project}/{scene}/"
    suffix=path.removeprefix(prefix)
    return path.startswith(prefix) and suffix.startswith("manual-") and "/" not in suffix and len(suffix)<100
