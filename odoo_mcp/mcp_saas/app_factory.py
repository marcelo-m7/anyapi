"""Isolated Flask application factory; existing AnyAPI routes are not mounted."""
from __future__ import annotations

from flask import Flask, jsonify
from importlib.util import find_spec
from .settings import Settings
from .browser_auth import bp as auth_bp, SupabaseAuthProvider
from .mcp_http import bp as mcp_bp
from .oauth import bp as oauth_bp
from .oauth import AuthorizationService, ClientMetadataResolver
from .oauth_store import OAuthStore


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
    oauth_store = (
        dependencies.get("oauth_store") if dependencies is not None and "oauth_store" in dependencies
        else (OAuthStore(config.db_dsn) if config.db_dsn.startswith(("postgresql://", "postgres://")) else None)
    )
    oauth_transport = (dependencies.get("oauth_client_transport")
                       if dependencies is not None else None)
    app.extensions["odoo_mcp.oauth_service"] = (
        AuthorizationService(oauth_store, ClientMetadataResolver(oauth_transport), config.public_url)
        if oauth_store is not None and config.public_url.startswith("https://") else None
    )
    app.register_blueprint(oauth_bp)
    if dependencies is not None and "oauth_service" in dependencies:
        app.extensions["odoo_mcp.oauth_service"] = dependencies["oauth_service"]
    elif (config.db_dsn.startswith(("postgresql://", "postgres://"))
          and config.public_url.startswith("https://")
          and find_spec("psycopg") is not None
          and find_spec("authlib") is not None):
        # Instantiate the service without connecting during Flask import.
        from .oauth_store import OAuthStore
        from .oauth import AuthorizationService, ClientMetadataResolver
        app.extensions["odoo_mcp.oauth_service"] = AuthorizationService(
            OAuthStore(config.db_dsn), ClientMetadataResolver(), config.public_url)
    else:
        app.extensions["odoo_mcp.oauth_service"] = None


    @app.get("/health")
    def health():
        return jsonify(status="ok", service="odoo-mcp-saas")

    @app.get("/health/ready")
    def ready():
        checks = config.readiness()
        state = all(checks.values())
        return jsonify(ready=state, checks=checks), (200 if state else 503)

    return app
