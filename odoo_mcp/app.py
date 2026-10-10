"""Vercel WSGI entrypoint for an independently deployed Odoo MCP service."""
from mcp_saas.app_factory import create_app

app = create_app()
