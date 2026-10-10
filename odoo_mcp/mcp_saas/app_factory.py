"""Isolated Flask application factory; existing AnyAPI routes are not mounted."""
from __future__ import annotations

from flask import Flask, jsonify
from .settings import Settings
from .browser_auth import bp as auth_bp, SupabaseAuthProvider


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

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="odoo-mcp-saas")

    @app.get("/health/ready")
    def ready():
        checks = config.readiness()
        state = all(checks.values())
        return jsonify(ready=state, checks=checks), (200 if state else 503)

    return app
