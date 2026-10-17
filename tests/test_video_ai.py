import pytest
from unittest.mock import Mock, patch
from video_studio.ai import generate_storyboard, StoryboardError

def test_missing_key_does_not_call_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StoryboardError, match="not configured"):
        generate_storyboard("science","a script")

def test_storyboard_response_validation():
    response = Mock(ok=True)
    response.json.return_value={"choices":[{"message":{"content":'{"scenes":[{"title":"Sol","narration":"Texto","visual_prompt":"Cinematic sun","duration_seconds":5}]}'}}]}
    with patch("video_studio.ai.requests.post", return_value=response) as post:
        scenes=generate_storyboard("Sun","Script",api_key="test")
    assert scenes[0]["duration_seconds"] == 5
    assert post.call_args.kwargs["timeout"] == 65

def test_invalid_provider_response_rejected():
    response=Mock(ok=True)
    response.json.return_value={"choices":[{"message":{"content":'{"scenes":[]}'}}]}
    with patch("video_studio.ai.requests.post", return_value=response):
        with pytest.raises(StoryboardError, match="invalid"):
            generate_storyboard("Sun","Script",api_key="test")
