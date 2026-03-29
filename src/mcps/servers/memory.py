"""Hub Memory — shared household media context via OpenViking.

Wraps OpenViking REST API. NOT your personal AI memory — this persists
across all AI clients and is shared by all household members.
"""

import hashlib
import io
import time

import httpx
from fastmcp import FastMCP

from mcps.config import settings

mcp = FastMCP("Hub Memory")

_BASE_URL = settings.openviking_url
_HEADERS: dict[str, str] = {
    "X-OpenViking-Account": "hub",
    "X-OpenViking-User": "household",
}
if settings.openviking_api_key:
    _HEADERS["X-API-Key"] = settings.openviking_api_key


async def _post(path: str, json: dict) -> dict:
    """POST to OpenViking API."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_HEADERS, timeout=30.0) as client:
        resp = await client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()


async def _get(url: str) -> dict:
    """GET from OpenViking API."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_HEADERS, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _upload_and_store(text: str, filename: str, target_uri: str) -> dict:
    """Upload text via temp_upload, then store as resource."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_HEADERS, timeout=60.0) as client:
        upload_resp = await client.post(
            "/api/v1/resources/temp_upload",
            files={"file": (filename, io.BytesIO(text.encode()), "text/markdown")},
        )
        upload_resp.raise_for_status()
        temp_path = upload_resp.json()["result"]["temp_path"]

        add_resp = await client.post(
            "/api/v1/resources",
            json={"temp_path": temp_path, "to": target_uri, "wait": True},
        )
        add_resp.raise_for_status()
        return add_resp.json()


def _memory_id(text: str) -> str:
    """Generate a deterministic memory filename from content."""
    ts = int(time.time())
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"{ts}-{h}.md"


def _mem_uri(user_id: str, filename: str = "") -> str:
    """Build a viking://resources/memories/... URI."""
    base = f"viking://resources/memories/{user_id}/"
    return f"{base}{filename}" if filename else base


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
        filename = _memory_id(text)
        target_uri = _mem_uri(user_id, filename)
        await _upload_and_store(text, filename, target_uri)
        return f"Stored: {text[:80]}{'...' if len(text) > 80 else ''} (uri: {target_uri})"
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
            "/api/v1/search/find",
            json={
                "query": query,
                "target_uri": _mem_uri(user_id),
            },
        )
        memories = result.get("result", {}).get("memories", [])
        if not memories:
            return "Nothing found in household memory."
        parts = [f"- {m.get('abstract', '?')} (score: {m.get('score', '?')}, uri: {m.get('uri', '?')})" for m in memories]
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
        result = await _get(f"/api/v1/fs/ls?uri={_mem_uri(user_id)}")
        entries = [e for e in result.get("result", []) if not e.get("isDir", False)]
        if not entries:
            return "No memories stored yet."
        parts = [f"- {e.get('name', '?')} (uri: {e.get('uri', '?')})" for e in entries]
        return f"Memories ({len(entries)}):\n" + "\n".join(parts)
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"


@mcp.tool
async def forget(
    memory_id: str,
) -> str:
    """Archive a specific memory from household storage (recoverable).

    Args:
        memory_id: The URI of the memory to archive (from recall or list_memories results).
    """
    try:
        parts = memory_id.replace("viking://resources/memories/", "").rstrip("/").split("/")
        user_id = parts[0] if len(parts) > 1 else "household"
        filename = parts[-1]
        await _post(
            "/api/v1/fs/mv",
            json={
                "from_uri": memory_id,
                "to_uri": f"viking://resources/archive/{user_id}/{filename}",
            },
        )
        return f"Archived: {filename} (was: {memory_id})"
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"
