"""Smoke tests for editorial controls and job lifecycle routes."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import render_template
from main import app

def test_editor_workflow_controls_present():
    with app.test_request_context('/video-studio'):
        html=render_template('video_studio.html',csrf='local-ci-token')
    for id_ in ('prevScene','nextScene','duplicateScene','playhead','renderDiagnostics','filmDuration','toastStack'):
        assert 'id="'+id_+'"' in html
    assert 'refreshReadiness' in html
    assert '/jobs/'+ "'" in html or '/jobs/' in html

def test_editor_routes_reject_guests():
    client=app.test_client()
    assert client.get('/_api/video-studio/projects/00000000-0000-0000-0000-000000000000/readiness').status_code==401
    assert client.post('/_api/video-studio/scenes/00000000-0000-0000-0000-000000000000/duplicate',json={}).status_code==401
    assert client.post('/_api/video-studio/projects/00000000-0000-0000-0000-000000000000/jobs/00000000-0000-0000-0000-000000000000/cancel',json={}).status_code==401
