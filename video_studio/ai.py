"""Optional AI storyboard draft service; no API key or spend is required to use manual editing."""
import os
import requests

class StoryboardError(Exception):
    pass

def generate_storyboard(topic: str, script: str, *, api_key: str | None = None) -> list[dict]:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise StoryboardError("OPENAI_API_KEY is not configured on the server")
    if not topic.strip() or not script.strip():
        raise StoryboardError("Topic and script are required")
    if len(script) > 20000:
        raise StoryboardError("Script exceeds 20,000 characters")
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={
            "model": os.getenv("VIDEO_STUDIO_STORYBOARD_MODEL", "gpt-4.1-mini"),
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role":"system","content":"You are a documentary storyboard designer. Return a JSON object with key scenes containing 1 to 12 ordered scenes. Each scene requires title, narration, visual_prompt, duration_seconds (1 to 120). Use Portuguese narration; visual prompts must be cinematic and photorealistic. Preserve documented facts and never fabricate sources."},
                {"role":"user","content":"TOPIC:\n"+topic[:1000]+"\nSCRIPT:\n"+script},
            ],
            "max_completion_tokens": 2500,
        },
        timeout=65,
    )
    if not response.ok:
        raise StoryboardError("AI provider failed: HTTP " + str(response.status_code))
    try:
        import json
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        scenes = data["scenes"]
        if not isinstance(scenes, list) or not 1 <= len(scenes) <= 12:
            raise ValueError()
        result = []
        for s in scenes:
            duration = float(s["duration_seconds"])
            if not 1 <= duration <= 120:
                raise ValueError()
            result.append({"title": str(s["title"])[:160], "narration": str(s["narration"])[:10000], "visual_prompt": str(s["visual_prompt"])[:10000], "duration_seconds": duration})
        return result
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise StoryboardError("AI returned an invalid storyboard") from exc

def generate_script(topic: str, *, duration_minutes: int = 5, style: str = "") -> str:
    """Create a documentary script draft; claims must be verified by editor."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise StoryboardError("OPENAI_API_KEY is not configured on the server")
    if not topic.strip() or len(topic) > 1000:
        raise StoryboardError("Topic must be 1-1000 characters")
    duration_minutes=max(1,min(int(duration_minutes),20))
    response=requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
        json={"model":os.getenv("VIDEO_STUDIO_STORYBOARD_MODEL","gpt-4.1-mini"),
          "messages":[
           {"role":"system","content":"Draft a Portuguese documentary voice-over script. Target 130 words per minute. Open with a compelling factual hook, establish chronology and tension, use short narration sentences, separate confirmed facts from speculation, avoid fabricated quotes or sources, and end with a memorable accurate conclusion. Output only the narration, not markdown."},
           {"role":"user","content":f"Theme: {topic}\nMinutes: {duration_minutes}\nStyle bible: {style[:1500]}"}],
          "max_completion_tokens":min(8000,duration_minutes*350)},timeout=120)
    if not response.ok:
        raise StoryboardError("AI provider returned HTTP "+str(response.status_code))
    result=response.json()["choices"][0]["message"]["content"]
    if not isinstance(result,str) or not result.strip():
        raise StoryboardError("Provider returned an empty script")
    return result[:60000]
