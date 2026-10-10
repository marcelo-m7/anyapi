"""Isolated Flask application factory; existing AnyAPI routes are not mounted."""
from __future__ import annotations

from flask import Flask, jsonify
from .settings import Settings
from .browser_auth import bp as auth_bp, SupabaseAuthProvider
from .mcp_http import bp as mcp_bp
from .oauth import bp as oauth_bp
from .oauth import AuthorizationService, ClientMetadataResolver
from importlib.util import find_spec


def create_app(settings: Settings | None = None, dependencies: dict | None = None) -> Flask:
    config = settings if settings is not None else Settings.from_env()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.session_key or None,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=65536,
    )
    app.extensions["odoo_mcp.settings"] = config
    if dependencies is not None:
        app.extensions["odoo_mcp.dependencies"] = dependencies
    app.extensions["odoo_mcp.auth_provider"] = (
        dependencies.get("supabase_auth") if dependencies is not None and "supabase_auth" in dependencies
        else (SupabaseAuthProvider(config.supabase_url, config.supabase_publishable_key)
              if config.supabase_url.startswith("https://") else None)
    )
    app.register_blueprint(auth_bp)
    app.extensions["odoo_mcp.authorizer"] = (
        dependencies.get("authorizer") if dependencies is not None else None)
    app.extensions["odoo_mcp.context_factory"] = (
        dependencies.get("context_factory") if dependencies is not None else None)
    app.register_blueprint(mcp_bp)
    if dependencies is not None and "oauth_store" in dependencies:
        oauth_store = dependencies["oauth_store"]
    elif (config.db_dsn.startswith(("postgresql://", "postgres://"))
          and find_spec("psycopg") is not None
          and find_spec("authlib") is not None):
        # Never require dedicated OAuth dependencies in the original AnyAPI CI.
        from .oauth_store import OAuthStore
        oauth_store = OAuthStore(config.db_dsn)
    else:
        oauth_store = None
    oauth_transport = (dependencies.get("oauth_client_transport")
                       if dependencies is not None else None)
    app.extensions["odoo_mcp.oauth_service"] = (
        AuthorizationService(oauth_store, ClientMetadataResolver(oauth_transport), config.public_url)
        if oauth_store is not None and config.public_url.startswith("https://") else None
    )
    app.register_blueprint(oauth_bp)
    @app.get("/health")
    def health():
        return jsonify(status="ok", service="odoo-mcp-saas")

    @app.get("/health/ready")
    def ready():
        checks = config.readiness()
        state = all(checks.values())
        return jsonify(ready=state, checks=checks), (200 if state else 503)

    return app
