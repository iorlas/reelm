"""MCP server apps -- one per service, each with OAuth at root.

Usage:
    uvicorn mcps.server:jackett --host 0.0.0.0 --port 8000
    uvicorn mcps.server:transmission --host 0.0.0.0 --port 8000
    uvicorn mcps.server:tmdb --host 0.0.0.0 --port 8000
    uvicorn mcps.server:storage --host 0.0.0.0 --port 8000
"""

from fastmcp.server.auth.providers.google import GoogleProvider

from mcps.config import settings
from mcps.servers.jackett import mcp as jackett_mcp
from mcps.servers.storage import mcp as storage_mcp
from mcps.servers.tmdb import mcp as tmdb_mcp
from mcps.servers.transmission import mcp as transmission_mcp


def _setup_auth(mcp_instance) -> None:
    """Configure Google OAuth on an MCP instance."""
    if not settings.google_client_id:
        return
    mcp_instance.auth = GoogleProvider(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        base_url=settings.auth_issuer,
        require_authorization_consent=False,
    )


_setup_auth(jackett_mcp)
_setup_auth(tmdb_mcp)
_setup_auth(transmission_mcp)
_setup_auth(storage_mcp)

# ASGI apps -- uvicorn targets these directly
jackett = jackett_mcp.http_app(path="/")
transmission = transmission_mcp.http_app(path="/")
tmdb = tmdb_mcp.http_app(path="/")
storage = storage_mcp.http_app(path="/")
