"""Test gateway with proxy-mounted backends (matching production setup)."""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server import create_proxy

from mcps.servers.jackett import mcp as jackett_mcp
from mcps.servers.memory import mcp as memory_mcp
from mcps.servers.skills import mcp as skills_mcp
from mcps.servers.storage import mcp as storage_mcp
from mcps.servers.tmdb import mcp as tmdb_mcp
from mcps.servers.transmission import mcp as transmission_mcp

BACKENDS = {
    "reelm_torrents": transmission_mcp,
    "reelm_search": jackett_mcp,
    "reelm_storage": storage_mcp,
    "reelm_media": tmdb_mcp,
}


@pytest.fixture
def gateway_with_proxies():
    """Gateway that mounts backends via create_proxy (same as production)."""
    gw = FastMCP("Reelm")
    for namespace, backend in BACKENDS.items():
        gw.mount(create_proxy(backend), namespace=namespace)
    # Memory and skills are mounted directly (not proxied), matching production
    gw.mount(memory_mcp, namespace="reelm_memory")
    gw.mount(skills_mcp, namespace="reelm_skills")
    return gw


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_gateway_lists_all_tools(gateway_with_proxies):
    """Proxy-mounted gateway should expose all backend tools."""
    client = Client(gateway_with_proxies)
    async with client:
        tools = await client.list_tools()

    tool_names = sorted(t.name for t in tools)
    assert len(tool_names) == 23, f"Expected 23 tools, got {len(tool_names)}: {tool_names}"

    for namespace in [*BACKENDS, "reelm_memory", "reelm_skills"]:
        ns_tools = [t for t in tool_names if t.startswith(f"{namespace}_")]
        assert len(ns_tools) > 0, f"No tools found for namespace {namespace}"
