"""Test that the gateway correctly lists tools from all mounted backends."""

import pytest
from fastmcp import Client, FastMCP

from mcps.servers.jackett import mcp as jackett_mcp
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
def gateway():
    gw = FastMCP("Reelm")
    for namespace, backend in BACKENDS.items():
        gw.mount(backend, namespace=namespace)
    return gw


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gateway_lists_all_tools(gateway):
    """Gateway should expose all backend tools with namespace prefixes."""
    client = Client(gateway)
    async with client:
        tools = await client.list_tools()

    tool_names = sorted(t.name for t in tools)
    assert len(tool_names) > 0, "Gateway returned no tools"

    # Check each namespace has at least one tool
    for namespace in BACKENDS:
        ns_tools = [t for t in tool_names if t.startswith(f"{namespace}_")]
        assert len(ns_tools) > 0, f"No tools found for namespace {namespace}"

    # Spot-check known tools exist
    assert "reelm_torrents_list_torrents" in tool_names
    assert "reelm_search_search_torrents" in tool_names
    assert "reelm_storage_list_dir" in tool_names
    assert "reelm_media_search_media" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gateway_tool_count(gateway):
    """Verify expected number of tools across all backends."""
    client = Client(gateway)
    async with client:
        tools = await client.list_tools()

    # transmission: 8, jackett: 2, storage: 4, tmdb: 3 = 17 total
    assert len(tools) == 17, f"Expected 17 tools, got {len(tools)}: {[t.name for t in tools]}"
