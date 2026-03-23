"""Reelm Memory — shared household media context via OpenMemory.

Wraps OpenMemory REST API. NOT your personal AI memory — this persists
across all AI clients and is shared by all household members.
"""

import httpx
from fastmcp import FastMCP

from mcps.config import settings

mcp = FastMCP("Reelm Memory")

_BASE_URL = settings.openmemory_url


async def _post(path: str, json: dict) -> dict:
    """POST to OpenMemory API with error handling."""
    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0) as client:
        resp = await client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()


async def _get(path: str, params: dict | None = None) -> dict | list:
    """GET from OpenMemory API with error handling."""
    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0) as client:
        resp = await client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


async def _delete(path: str) -> dict:
    """DELETE from OpenMemory API with error handling."""
    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0) as client:
        resp = await client.delete(path)
        resp.raise_for_status()
        return resp.json()


@mcp.tool
async def remember(
    text: str,
    user_id: str = "household",
) -> str:
    """Store a shared household media fact — what you've watched, want to watch,
    quality preferences, or content rules. This persists across all AI clients
    (Claude, ChatGPT, Copilot) and is shared by all household members.

    Args:
        text: The fact to remember (e.g., "We finished Breaking Bad S5",
              "Kids can't watch R-rated content", "TV supports 4K HDR")
        user_id: Who this applies to. Default "household" for shared facts.
                 Use a name (e.g., "denis") for personal preferences.
    """
    try:
        result = await _post(
            "/memories",
            json={
                "messages": [{"role": "user", "content": text}],
                "user_id": user_id,
            },
        )
        entries = result.get("results", [])
        if not entries:
            return "Memory stored (no details returned)."
        parts = [f"- [{e.get('event', '?')}] {e.get('memory', '?')} (id: {e.get('id', '?')})" for e in entries]
        return "Stored:\n" + "\n".join(parts)
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"


@mcp.tool
async def recall(
    query: str,
    user_id: str = "household",
) -> str:
    """Search household memory for relevant context — watched shows, preferences,
    content rules. This searches the shared household memory, not your personal memory.

    Args:
        query: What to search for (e.g., "What sci-fi have we watched?",
               "Any content rules for kids?")
        user_id: Filter by household member. Default "household" for shared facts.
    """
    try:
        result = await _post(
            "/memories/search",
            json={
                "query": query,
                "user_id": user_id,
            },
        )
        entries = result.get("results", result) if isinstance(result, dict) else result
        if not entries:
            return "Nothing found in household memory."
        parts = [f"- {e.get('memory', '?')} (score: {e.get('score', '?')}, id: {e.get('id', '?')})" for e in entries]
        return "Found:\n" + "\n".join(parts)
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"


@mcp.tool
async def list_memories(
    user_id: str = "household",
) -> str:
    """List all stored household memories for review or cleanup.

    Args:
        user_id: Filter by household member. Default "household" for shared facts.
    """
    try:
        result = await _get("/memories", params={"user_id": user_id})
        entries = result.get("results", result) if isinstance(result, dict) else result
        if not entries:
            return "No memories stored yet."
        parts = [f"- {e.get('memory', '?')} (id: {e.get('id', '?')})" for e in entries]
        return f"Memories ({len(entries)}):\n" + "\n".join(parts)
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"


@mcp.tool
async def forget(
    memory_id: str,
) -> str:
    """Delete a specific memory from household storage.

    Args:
        memory_id: The ID of the memory to delete (from recall or list_memories results).
    """
    try:
        await _delete(f"/memories/{memory_id}")
        return f"Forgotten (id: {memory_id})."
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"
