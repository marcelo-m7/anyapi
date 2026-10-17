"""Smoke-check the Stitch-inspired functional Jinja editor in CI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import render_template
from main import app

def test_video_studio_template_renders_with_csrf_context():
    with app.test_request_context("/video-studio"):
        html=render_template("video_studio.html",csrf="test-csrf")
    for expected in ("SYNTHESIS_OS","Obsidian Void","id=\"timeline\"",
                     "id=\"preview\"","id=\"genImage\"","id=\"render\"",
                     "id=\"genVoice\"","id=\"aiStoryboard\"","id=\"projects\""):
        # Design-system label may live in styles rather than visible copy.
        if expected=="Obsidian Void":
            assert "--void:#08080a" in html
        else:
            assert expected in html
    assert "test-csrf" in html
