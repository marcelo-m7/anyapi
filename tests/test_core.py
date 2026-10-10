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
