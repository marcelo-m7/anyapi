"""Renderer validates manifests without invoking ffmpeg for bad inputs."""
from pathlib import Path
import pytest
from video_studio.render import render

def test_empty_manifest_rejected(tmp_path):
    with pytest.raises(ValueError, match="contain scenes"):
        render({"scenes":[]},tmp_path,tmp_path/"out.mp4")

def test_missing_asset_rejected(tmp_path):
    with pytest.raises(ValueError, match="Missing image asset"):
        render({"scenes":[{"id":"scene-123","duration_seconds":5}]},tmp_path,tmp_path/"out.mp4")

def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsafe scene identifier"):
        render({"scenes":[{"id":"../../etc/passwd","duration_seconds":5}]},tmp_path,tmp_path/"out.mp4")

def test_invalid_duration_rejected(tmp_path):
    with pytest.raises(ValueError, match="Invalid scene duration"):
        render({"scenes":[{"id":"scene-123","duration_seconds":0}]},tmp_path,tmp_path/"out.mp4")

def test_invalid_fps_rejected(tmp_path):
    with pytest.raises(ValueError, match="fps"):
        render({"scenes":[]},tmp_path,tmp_path/"out.mp4",fps=120)
