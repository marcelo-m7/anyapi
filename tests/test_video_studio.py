"""Video Studio route contract smoke tests, no live Supabase credentials."""
import uuid
from unittest.mock import patch
import main

def test_video_studio_requires_login():
    client = main.app.test_client()
    response = client.get("/video-studio")
    assert response.status_code in (302, 303)
    assert "/login" in response.location

def test_video_api_requires_login():
    client = main.app.test_client()
    response = client.get("/_api/video-studio/projects")
    assert response.status_code == 401

def test_video_api_does_not_allow_anonymous_mutation():
    client = main.app.test_client()
    response = client.post("/_api/video-studio/projects", json={"title":"test"})
    assert response.status_code == 401

def test_non_uuid_project_is_not_a_route():
    client = main.app.test_client()
    assert client.get("/_api/video-studio/projects/not-a-uuid").status_code == 404
