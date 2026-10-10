"""Flask request-to-Edge-pipeline integration tests with isolated external mocks."""
from types import SimpleNamespace

from main import app
from anyapi import gateway, services
from anyapi.runtime import edge_pipeline


def resolved(visibility="public", method="POST"):
    return {
        "endpoint_id": "endpoint-fixture",
        "owner_id": "owner-fixture",
        "project_id": "project-fixture",
        "version_id": "version-fixture",
        "version": 1,
        "config": {
            "name": "Normalize",
            "method": method,
            "visibility": visibility,
            "input_schema": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
            "output_schema": {"type": "object", "required": ["processed"], "properties": {"processed": {"type": "boolean"}}},
            "processor": {
                "type": "edge_pipeline",
                "steps": [{"id": "normalize", "function": "anyapi-normalize", "arguments": {"url": "{{input.url}}"}}],
                "output": "{{steps.normalize.data}}",
            },
        },
    }


def test_gateway_edge_pipeline_e2e_mocked(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture.jwt.signature")
    monkeypatch.setenv("ANYAPI_EDGE_FUNCTION_JWT", "fixture.jwt.signature")
    monkeypatch.setattr(gateway, "resolve", lambda *args: resolved())
    monkeypatch.setattr(gateway, "consume_rate_limit", lambda *args: (True, 59, 123))
    monkeypatch.setattr(gateway, "log_execution", lambda **kwargs: "run1")
    class StubService:
        def select(self, table, params):
            assert table == "edge_function_catalog"
            return [{"slug": "anyapi-normalize", "input_schema": {"type": "object"}, "output_schema": {"type": "object"}}]
    monkeypatch.setattr(services, "supabase", lambda: SimpleNamespace(service=lambda: StubService()))
    called=[]
    def edge_post(url, json, **kwargs):
        called.append((url, json))
        return SimpleNamespace(status_code=200, is_redirect=False, content=b"ok",
                               json=lambda: {"success": True, "data": {"url": json["url"], "processed": True}, "error": None, "meta": {}})
    monkeypatch.setattr(edge_pipeline.requests, "post", edge_post)
    with app.test_client() as client:
        response=client.post("/tester/project/endpoint", json={"url": "https://example.com/demo"})
    assert response.status_code==200
    assert response.json=={"url":"https://example.com/demo","processed":True}
    assert len(called)==1
    assert called[0][0]=="https://fixture.supabase.co/functions/v1/anyapi-normalize"


def test_gateway_public_endpoint_rejects_wrong_method(monkeypatch):
    monkeypatch.setattr(gateway, "resolve", lambda *args: resolved())
    with app.test_client() as client:
        response=client.get("/tester/project/endpoint")
    assert response.status_code==405
    assert response.headers["Allow"]=="POST"


def test_gateway_rejects_invalid_body(monkeypatch):
    monkeypatch.setattr(gateway, "resolve", lambda *args: resolved())
    monkeypatch.setattr(gateway, "consume_rate_limit", lambda *args: (True, 59, 123))
    with app.test_client() as client:
        response=client.post("/tester/project/endpoint",data="not-json",headers={"Content-Type":"text/plain"})
    assert response.status_code==415


def test_gateway_rate_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(gateway, "resolve", lambda *args: resolved())
    monkeypatch.setattr(gateway, "consume_rate_limit", lambda *args: (False, 0, 123))
    with app.test_client() as client:
        response=client.post("/tester/project/endpoint",json={"url":"https://example.com"})
    assert response.status_code==429
