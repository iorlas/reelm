"""Reelm MCP Gateway — OAuth 2.1 + multi-backend federation via FastMCP.

Google OAuth 2.1 via FastMCP GoogleProvider, JWT validation, tool prefixing.
Future: output compression, rate limiting, custom orchestration tools.

Usage:
    uvicorn mcps.gateway:app --host 0.0.0.0 --port 3000
"""

import os

from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.auth.providers.google import GoogleProvider

from mcps.servers.memory import mcp as memory_mcp

# Google OAuth config from environment
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
BASE_URL = os.environ.get("BASE_URL", "https://reelm.shen.iorlas.net")

# Backend MCP server URLs (internal Docker network)
TRANSMISSION_URL = os.environ.get("TRANSMISSION_MCP_URL", "http://reelm-transmission:8000/mcp/")
JACKETT_URL = os.environ.get("JACKETT_MCP_URL", "http://reelm-jackett:8000/mcp/")
STORAGE_URL = os.environ.get("STORAGE_MCP_URL", "http://reelm-storage:8000/mcp/")
TMDB_URL = os.environ.get("TMDB_MCP_URL", "http://reelm-tmdb:8000/mcp/")

# --- Auth ---
auth = GoogleProvider(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    base_url=BASE_URL,
    require_authorization_consent=False,
)

# --- Gateway server ---
gateway = FastMCP(
    "Reelm",
    instructions=(
        "Reelm is your personal media agent. "
        "Use reelm_torrents tools to manage downloads, "
        "reelm_search tools to find torrents, "
        "reelm_media tools to discover movies/TV, "
        "reelm_storage tools to manage files on the NAS. "
        "Use reelm_memory tools to store and recall shared household media context — "
        "what the household has watched, wants to watch, quality preferences, content rules. "
        "This is NOT your personal memory — it persists across all AI clients "
        "(Claude, ChatGPT, Copilot) and is shared by all household members."
    ),
    auth=auth,
)

# --- Mount backends with tool prefixing ---
gateway.mount(create_proxy(TRANSMISSION_URL), namespace="reelm_torrents")
gateway.mount(create_proxy(JACKETT_URL), namespace="reelm_search")
gateway.mount(create_proxy(STORAGE_URL), namespace="reelm_storage")
gateway.mount(create_proxy(TMDB_URL), namespace="reelm_media")
gateway.mount(memory_mcp, namespace="reelm_memory")

# --- ASGI app for uvicorn ---
app = gateway.http_app(path="/mcp")
