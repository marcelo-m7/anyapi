"""Video Studio editorial workflow tests for the new pure helpers."""
import pytest
from video_studio.workflow import validate_reorder, duplicate_scene, render_readiness, timestamp_srt

def test_duplicate_copies_editorial_not_generated_assets():
    source={"id":"abc","project_id":"a","owner_id":"b","position":0,"title":"Sun",
            "narration":"An eclipse","visual_prompt":"wide shot","duration_seconds":5,
            "image_path":"private.png","voice_path":"voice.mp3","video_path":"video.mp4","asset_url":"https://example.com/pic.png"}
    item=duplicate_scene(source,position=2)
    assert item["title"]=="Sun (cópia)"
    assert item["position"]==2
    assert "image_path" not in item and "voice_path" not in item and "video_path" not in item
    assert "asset_url" not in item and "id" not in item
    assert item["visual_prompt"]=="wide shot"

def test_reorder_rejects_duplicates_and_missing():
    assert validate_reorder(["a","b"],{"a","b"}) is True
    with pytest.raises(ValueError):validate_reorder(["a","a"],{"a","b"})
    with pytest.raises(ValueError):validate_reorder(["a"],{"a","b"})

def test_readiness_flags_missing_assets():
    result=render_readiness([
        {"id":"a","title":"One","duration_seconds":5,"image_path":"one.png"},
        {"id":"b","title":"Two","duration_seconds":8,"image_path":None,"video_path":None}
    ])
    assert result["duration_seconds"]==13
    assert result["render_ready"] is False
    assert result["missing_scene_ids"]==["b"]

def test_subtitle_time_format():
    assert timestamp_srt(65.25)=="00:01:05,250"
