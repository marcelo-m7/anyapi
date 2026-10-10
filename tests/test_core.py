"""Regression checks for Flask routing and the declarative runtime."""
import pytest
from anyapi.runtime.engine import execute, validate_config, snapshot_config
from anyapi.runtime.code_runner import CodeRunner
from anyapi.security import SecretBox, generate_api_key, hash_api_key


def test_api_key_is_hashed():
    key,prefix,hashed=generate_api_key()
    assert key.startswith(prefix)
    assert hashed==hash_api_key(key)
    assert key not in hashed


def test_secret_encryption_roundtrip():
    box=SecretBox("test-secret-do-not-use-in-production")
    ciphertext=box.encrypt("sample-access-token")
    assert "sample-access-token" not in ciphertext
    assert box.decrypt(ciphertext)=="sample-access-token"


def test_code_processor_cannot_publish_without_runner():
    config={
        "input_schema":{"type":"object"},
        "output_schema":{"type":"object"},
        "processor":{"type":"code","language":"python","code":"def process(input, context): return input"},
    }
    problems=validate_config(config,set(),CodeRunner("",""))
    assert any("isolated runner" in problem["message"] for problem in problems)


def test_visual_processor_with_no_steps_returns_empty_object():
    config={
        "method":"POST",
        "input_schema":{"type":"object"},
        "output_schema":{"type":"object"},
        "processor":{"type":"visual","steps":[]},
    }
    result=execute(config,{},{"source":"test"},connectors={},runner=CodeRunner("",""))
    assert result.status_code==200
    assert result.body=={}


def test_invalid_input_returns_400():
    config={
        "input_schema":{"type":"object","required":["name"],"properties":{"name":{"type":"string"}}},
        "output_schema":{"type":"object"},
        "processor":{"type":"visual","steps":[]},
    }
    result=execute(config,{}, {},connectors={},runner=CodeRunner("",""))
    assert result.status_code==400
    assert result.error_type=="input_validation"


def test_gateway_uses_published_visibility(monkeypatch):
    """Changing the draft must not change published authentication."""
    from flask import Flask
    from anyapi import gateway
    app=Flask(__name__)
    published={"visibility":"public","config":{"visibility":"private"},"project_id":"p","endpoint_id":"e"}
    with app.test_request_context("/someone/api/test"):
        assert gateway.authorize(published) is False


def test_schema_conversion_requires_login():
    from flask import Flask
    from anyapi.schema_editor import bp
    app=Flask(__name__)
    app.register_blueprint(bp)
    with app.test_client() as client:
        result=client.post("/_api/schema/convert",json={"format":"json","text":"{}"})
        assert result.status_code in (400,401)


def test_visual_schema_invalid_input_rejected():
    from anyapi.runtime.schema import schema_problems
    problems=schema_problems({"type":"mystery"})
    assert problems

def test_rollback_rpc_contract_uses_version_uuid():
    from pathlib import Path
    source=Path("anyapi/management.py").read_text()
    assert '"p_version_id"' in source
    assert '"p_version":int(' not in source


def test_database_migration_hardening_present():
    from pathlib import Path
    sql=Path("supabase/migrations/0003_anyapi_security_indexes.sql").read_text()
    assert "REVOKE EXECUTE ON FUNCTION public.handle_new_user()" in sql
    assert "CREATE INDEX IF NOT EXISTS api_keys_endpoint_idx" in sql

def test_http_connector_egress_disabled_without_protected_network(monkeypatch):
    from anyapi.runtime.safe_http import request, EgressBlocked
    monkeypatch.delenv("ANYAPI_HTTP_EGRESS_ENABLED",raising=False)
    with pytest.raises(EgressBlocked,match="protected egress"):
        request("GET","https://example.com")


def test_v1_removes_arbitrary_connector_management():
    from pathlib import Path
    source=Path("anyapi/management.py").read_text()
    assert '@bp.route("/projects/<project_id>/connectors"' not in source


def test_edge_pipeline_rejects_unlisted_functions():
    from anyapi.runtime.edge_pipeline import validate_pipeline
    processor={"type":"edge_pipeline","steps":[{"id":"step1","function":"untrusted-function","arguments":{}}]}
    assert any("not registered" in e["message"] for e in validate_pipeline(processor,{}))


def test_edge_pipeline_sequential_mapping(monkeypatch):
    import time
    from types import SimpleNamespace
    from anyapi.runtime import edge_pipeline
    seen=[]
    def fake_post(url, json, **kwargs):
        seen.append((url,json))
        return SimpleNamespace(status_code=200,is_redirect=False,content=b"{}",json=lambda:{"success":True,"data":{**json,"processed":True},"error":None,"meta":{}})
    monkeypatch.setattr(edge_pipeline.requests,"post",fake_post)
    processor={"type":"edge_pipeline","steps":[
        {"id":"first","function":"anyapi-normalize","arguments":{"url":"{{input.url}}"}},
        {"id":"second","function":"anyapi-normalize","arguments":{"text":"{{steps.first.data.url}}"}}
    ],"output":"{{steps.second.data}}"}
    record={"input_schema":{"type":"object"},"output_schema":{"type":"object"}}
    settings=SimpleNamespace(supabase_url="https://example.supabase.co",supabase_service_key="fixture.test.signature")
    output=edge_pipeline.run_pipeline(processor,{"url":"video"}, {},{"anyapi-normalize":record},settings,time.monotonic()+10,lambda *args:None)
    assert seen[1][1]=={"text":"video"}
    assert output=={"text":"video","processed":True}

def test_edge_pipeline_disallows_forward_and_self_references():
    from anyapi.runtime.edge_pipeline import validate_pipeline
    steps=[
      {"id":"first","function":"anyapi-normalize","arguments":{"value":"{{steps.first.data}}"}},
      {"id":"second","function":"anyapi-normalize","arguments":{"value":"{{steps.third.data}}"}}
    ]
    errors=validate_pipeline({"type":"edge_pipeline","steps":steps,"output":"{{steps.second.data}}"},{"anyapi-normalize":{}})
    assert sum("unknown step" in e["message"] for e in errors)>=2


def test_edge_pipeline_refuses_non_https_supabase(monkeypatch):
    import time
    from types import SimpleNamespace
    from anyapi.runtime.edge_pipeline import run_pipeline
    from anyapi.runtime.code_runner import RunnerError
    from anyapi.runtime import edge_pipeline
    monkeypatch.setenv("ANYAPI_EDGE_FUNCTION_JWT","fixture.jwt.signature")
    monkeypatch.setattr(edge_pipeline.requests,"post",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("No outbound HTTP expected")))
    with pytest.raises(RunnerError,match="HTTPS"):
        run_pipeline(
            {"type":"edge_pipeline","steps":[{"id":"first","function":"anyapi-normalize","arguments":{"value":"hello"}}]},
            {},{},{"anyapi-normalize":{"input_schema":{"type":"object"},"output_schema":{"type":"object"}}},
            SimpleNamespace(supabase_url="http://bad.example",supabase_service_key="fixture.jwt.signature"),
            time.monotonic()+2,lambda *args:None
        )
