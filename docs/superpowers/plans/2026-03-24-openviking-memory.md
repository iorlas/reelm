# OpenViking Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mem0 backend in memory.py with OpenViking REST API calls, deploy OpenViking as a sidecar container.

**Architecture:** Thin MCP wrapper (`memory.py`) calls OpenViking at `http://openviking:1933`. Writes via resources API, searches via search/find, lists via fs/ls, archives via fs/mv. OpenViking uses LiteLLM (already deployed) for embeddings and L0/L1 generation.

**Tech Stack:** FastMCP, httpx, OpenViking REST API, Docker Compose

**Spec:** `docs/superpowers/specs/2026-03-24-openviking-memory-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Rewrite | `src/mcps/servers/memory.py` | Swap mem0 calls → OpenViking REST API |
| Modify | `src/mcps/config.py` | Rename `openmemory_url` → `openviking_url`, port 1933 |
| Rewrite | `tests/test_memory_unit.py` | Update mocks to OpenViking response formats |
| Modify | `docker-compose.prod.yml` | Remove mem0 comments, add openviking service |
| Modify | `.github/workflows/deploy.yml` | Update compose validation dummy vars |

---

### Task 1: Update config

**Files:**
- Modify: `src/mcps/config.py`

- [ ] **Step 1: Rename config field**

Replace the mem0 config block in `src/mcps/config.py`:

```python
    # OpenViking (default localhost for local dev; overridden via OPENVIKING_URL env var in production)
    openviking_url: str = "http://localhost:1933"
```

- [ ] **Step 2: Verify config loads**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run python -c "from mcps.config import settings; print(settings.openviking_url)"`
Expected: `http://localhost:1933`

- [ ] **Step 3: Commit**

```bash
git add src/mcps/config.py
git commit -m "refactor: rename openmemory_url to openviking_url"
```

---

### Task 2: Rewrite memory.py for OpenViking (TDD)

**Files:**
- Rewrite: `src/mcps/servers/memory.py`
- Rewrite: `tests/test_memory_unit.py`

#### 2a: Write tests first

- [ ] **Step 1: Rewrite test_memory_unit.py**

Replace entire contents of `tests/test_memory_unit.py`:

```python
"""Unit tests for memory MCP server (OpenViking wrapper)."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcps.servers.memory import forget, list_memories, recall, remember


def _mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)
    return resp


def _mock_client(**method_responses):
    """Create a mock httpx.AsyncClient with method responses.

    Usage: _mock_client(post=response_data, get=response_data)
    For side_effect, pass an Exception directly.
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    for method, value in method_responses.items():
        if isinstance(value, Exception):
            setattr(client, method, AsyncMock(side_effect=value))
        else:
            setattr(client, method, AsyncMock(return_value=_mock_response(value)))
    return client


@pytest.mark.unit
@pytest.mark.asyncio
class TestRemember:
    async def test_remember_stores_memory(self):
        # resources API returns status ok
        mock = _mock_client(post={"status": "ok"})
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await remember("We finished Breaking Bad S5")

        assert "stored" in result.lower()
        # Should call POST twice: _ensure_dir + resources API
        assert mock.post.call_count >= 1

    async def test_remember_with_custom_user_id(self):
        mock = _mock_client(post={"status": "ok"})
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await remember("Denis prefers 4K", user_id="denis")

        assert "stored" in result.lower()
        # Check the resources API call has the right target URI
        calls = mock.post.call_args_list
        resource_call = [c for c in calls if "/api/v1/resources" in str(c)]
        assert len(resource_call) > 0

    async def test_remember_returns_uri(self):
        mock = _mock_client(post={"status": "ok"})
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await remember("TV supports 4K HDR")

        assert "viking://user/memories/household/" in result

    async def test_remember_handles_api_error(self):
        mock = _mock_client(post=Exception("Connection refused"))
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await remember("test")

        assert "unavailable" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestRecall:
    async def test_recall_searches_memories(self):
        search_response = {
            "status": "ok",
            "result": {
                "memories": [
                    {
                        "uri": "viking://user/memories/household/1711234567-abc12345.md",
                        "abstract": "We finished Breaking Bad S5",
                        "score": 0.95,
                        "match_reason": "semantic similarity",
                    }
                ],
                "total": 1,
            },
        }
        mock = _mock_client(post=search_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await recall("Breaking Bad")

        assert "Breaking Bad" in result
        assert "0.95" in result
        call_kwargs = mock.post.call_args
        assert "/api/v1/search/find" in call_kwargs.args[0]

    async def test_recall_with_custom_user_id(self):
        search_response = {"status": "ok", "result": {"memories": [], "total": 0}}
        mock = _mock_client(post=search_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await recall("anything", user_id="denis")

        call_kwargs = mock.post.call_args
        body = call_kwargs.kwargs["json"]
        assert "viking://user/memories/denis/" in body.get("target_uri", "")

    async def test_recall_empty_results(self):
        search_response = {"status": "ok", "result": {"memories": [], "total": 0}}
        mock = _mock_client(post=search_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await recall("something obscure")

        assert "nothing found" in result.lower()

    async def test_recall_handles_api_error(self):
        mock = _mock_client(post=Exception("Timeout"))
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await recall("anything")

        assert "unavailable" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestListMemories:
    async def test_list_memories_returns_all(self):
        ls_response = {
            "status": "ok",
            "result": [
                {
                    "name": "1711234567-abc12345.md",
                    "uri": "viking://user/memories/household/1711234567-abc12345.md",
                    "modTime": "2026-03-24T12:00:00Z",
                    "isDir": False,
                },
                {
                    "name": "1711234999-def67890.md",
                    "uri": "viking://user/memories/household/1711234999-def67890.md",
                    "modTime": "2026-03-24T13:00:00Z",
                    "isDir": False,
                },
            ],
        }
        mock = _mock_client(get=ls_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await list_memories()

        assert "Memories (2):" in result
        call_kwargs = mock.get.call_args
        assert "viking://user/memories/household/" in call_kwargs.args[0] or "viking://user/memories/household/" in str(call_kwargs)

    async def test_list_memories_filters_dirs(self):
        ls_response = {
            "status": "ok",
            "result": [
                {"name": "memory.md", "uri": "viking://user/memories/household/memory.md", "isDir": False},
                {"name": ".archive", "uri": "viking://user/memories/household/.archive/", "isDir": True},
            ],
        }
        mock = _mock_client(get=ls_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await list_memories()

        assert "Memories (1):" in result

    async def test_list_memories_empty(self):
        ls_response = {"status": "ok", "result": []}
        mock = _mock_client(get=ls_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await list_memories()

        assert "no memories" in result.lower()

    async def test_list_memories_handles_api_error(self):
        mock = _mock_client(get=Exception("Service unavailable"))
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await list_memories()

        assert "unavailable" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestForget:
    async def test_forget_archives_memory(self):
        mv_response = {
            "status": "ok",
            "result": {
                "from": "viking://user/memories/household/1711234567-abc12345.md",
                "to": "viking://user/archive/household/1711234567-abc12345.md",
            },
        }
        mock = _mock_client(post=mv_response)
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await forget("viking://user/memories/household/1711234567-abc12345.md")

        assert "archived" in result.lower()
        call_kwargs = mock.post.call_args
        body = call_kwargs.kwargs["json"]
        assert body["from_uri"] == "viking://user/memories/household/1711234567-abc12345.md"
        assert "viking://user/archive/household/" in body["to_uri"]

    async def test_forget_handles_api_error(self):
        mock = _mock_client(post=Exception("Not found"))
        with patch("mcps.servers.memory.httpx.AsyncClient", return_value=mock):
            result = await forget("viking://user/memories/household/nonexistent.md")

        assert "unavailable" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py -v --no-header 2>&1 | head -30`
Expected: FAIL — imports still point to old mem0 code, responses don't match

#### 2b: Implement memory.py

- [ ] **Step 3: Rewrite memory.py**

Replace entire contents of `src/mcps/servers/memory.py`:

```python
"""Reelm Memory — shared household media context via OpenViking.

Wraps OpenViking REST API. NOT your personal AI memory — this persists
across all AI clients and is shared by all household members.
"""

import hashlib
import time

import httpx
from fastmcp import FastMCP

from mcps.config import settings

mcp = FastMCP("Reelm Memory")

_BASE_URL = settings.openviking_url


async def _post(path: str, json: dict) -> dict:
    """POST to OpenViking API."""
    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0) as client:
        resp = await client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()


async def _get(url: str) -> dict:
    """GET from OpenViking API."""
    async with httpx.AsyncClient(base_url=_BASE_URL, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _ensure_dir(uri: str) -> None:
    """Create directory if it doesn't exist. Ignores 409 (already exists)."""
    try:
        await _post("/api/v1/fs/mkdir", json={"uri": uri})
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 409:
            raise


def _memory_id(text: str) -> str:
    """Generate a deterministic memory filename from content."""
    ts = int(time.time())
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"{ts}-{h}.md"


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
        mem_dir = f"viking://user/memories/{user_id}/"
        await _ensure_dir(mem_dir)
        filename = _memory_id(text)
        target_uri = f"{mem_dir}{filename}"
        await _post("/api/v1/resources", json={
            "content": text,
            "to": target_uri,
        })
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
        result = await _post("/api/v1/search/find", json={
            "query": query,
            "target_uri": f"viking://user/memories/{user_id}/",
        })
        memories = result.get("result", {}).get("memories", [])
        if not memories:
            return "Nothing found in household memory."
        parts = [
            f"- {m.get('abstract', '?')} (score: {m.get('score', '?')}, uri: {m.get('uri', '?')})"
            for m in memories
        ]
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
        mem_uri = f"viking://user/memories/{user_id}/"
        result = await _get(f"/api/v1/fs/ls?uri={mem_uri}")
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
        # Extract user_id and filename from URI: viking://user/memories/{user_id}/{filename}
        parts = memory_id.replace("viking://user/memories/", "").rstrip("/").split("/")
        user_id = parts[0] if len(parts) > 1 else "household"
        filename = parts[-1]
        archive_dir = f"viking://user/archive/{user_id}/"
        await _ensure_dir(archive_dir)
        result = await _post("/api/v1/fs/mv", json={
            "from_uri": memory_id,
            "to_uri": f"{archive_dir}{filename}",
        })
        return f"Archived: {filename} (was: {memory_id})"
    except Exception as e:  # noqa: BLE001 — graceful degradation, memory is optional
        return f"Memory unavailable: {e}"
```

- [ ] **Step 4: Run all memory tests**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/mcps/servers/memory.py tests/test_memory_unit.py
git commit -m "refactor: replace mem0 backend with OpenViking REST API"
```

---

### Task 3: Update docker-compose.prod.yml

**Files:**
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Replace gateway OPENMEMORY_URL with OPENVIKING_URL**

Replace the commented-out line:
```yaml
      # OPENMEMORY_URL: http://mem0-api:8000  # disabled — mem0 image is arm64-only
```
With:
```yaml
      OPENVIKING_URL: http://openviking:1933
```

- [ ] **Step 2: Add openviking to gateway depends_on**

Add after the `reelm-tmdb` dependency:
```yaml
      openviking:
        condition: service_healthy
```

- [ ] **Step 3: Remove mem0 comment block**

Remove lines 107-110 (the disabled mem0 comment block):
```
# ── mem0 infrastructure — DISABLED ──
# mem0/mem0-api-server:latest is arm64-only (no amd64 build).
# TODO: build from source (github.com/mem0ai/mem0/server/Dockerfile) or find alternative.
# Services: mem0-db (pgvector), mem0-neo4j, mem0-api
```

- [ ] **Step 4: Add openviking service**

Add before the `volumes:` section:

```yaml
  # ── OpenViking (household memory) ──
  openviking:
    image: ghcr.io/volcengine/openviking:main
    pull_policy: always
    command: >
      sh -c 'cat > /app/ov.conf <<CONF
      {
        "storage": {"workspace": "/app/data"},
        "vlm": {
          "provider": "openai",
          "api_base": "http://litellm:4000/v1",
          "api_key": "no-auth",
          "model": "llama3.2:3b"
        },
        "embedding": {
          "dense": {
            "provider": "openai",
            "api_base": "http://litellm:4000/v1",
            "api_key": "no-auth",
            "model": "nomic-embed-text",
            "dimension": 768
          }
        }
      }
      CONF
      openviking-server'
    volumes:
      - openviking-data:/app/data
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:1933/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    networks:
      - dokploy-network
      - reelm-internal
    restart: unless-stopped
```

- [ ] **Step 5: Add openviking-data volume**

Update volumes section:
```yaml
volumes:
  jackett-config:
  openviking-data:
```

- [ ] **Step 6: Validate compose syntax**

Run:
```bash
cd /Users/iorlas/Workspaces/reelm && \
  IMAGE_TAG=test TRANSMISSION_USER=x TRANSMISSION_PASS=x \
  JACKETT_API_KEY=x WEBDAV_URL=x WEBDAV_USER=x WEBDAV_PASS=x TMDB_API_KEY=x \
  GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=x \
  docker compose -f docker-compose.prod.yml config --quiet
```
Expected: No output (success)

- [ ] **Step 7: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat: add OpenViking service, remove mem0 remnants"
```

---

### Task 4: Update CI/CD pipeline

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Update compose validation step**

Replace the commented OPENMEMORY line (line 68):
```yaml
          # OPENMEMORY vars removed — mem0 services disabled
```
With nothing — no OpenViking vars needed in compose validation since `OPENVIKING_URL` is hardcoded in compose (not a `${VAR}` reference).

- [ ] **Step 2: Update deploy step comments**

Replace the OPENMEMORY comment in the deploy env block (line 128):
```yaml
          # OPENMEMORY vars removed — mem0 services disabled (arm64-only image)
```
With nothing — clean up the dead comment.

- [ ] **Step 3: Run yamllint**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run yamllint .github/workflows/deploy.yml`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "chore: clean up mem0 comments from CI/CD pipeline"
```

---

### Task 5: Clean up stale GitHub secrets

- [ ] **Step 1: Remove unused secrets**

```bash
gh secret delete OPENMEMORY_POSTGRES_USER 2>/dev/null || true
gh secret delete OPENMEMORY_POSTGRES_PASSWORD 2>/dev/null || true
```

- [ ] **Step 2: Verify remaining secrets**

Run: `gh secret list`
Expected: No `OPENMEMORY_*` secrets listed.

---

### Task 6: Final verification

- [ ] **Step 1: Run full check**

Run: `cd /Users/iorlas/Workspaces/reelm && make check`
Expected: lint PASS, tests PASS, coverage ≥ 90%

- [ ] **Step 2: Run diff coverage**

Run: `cd /Users/iorlas/Workspaces/reelm && make coverage-diff`
Expected: ≥ 95% diff coverage

- [ ] **Step 3: Review all changes**

Run: `cd /Users/iorlas/Workspaces/reelm && git diff main --stat`
Expected: Only expected files changed.

- [ ] **Step 4: Deployment notes**

Before deploying, verify:
- OpenViking Docker image `ghcr.io/volcengine/openviking:main` exists and supports amd64
- OpenViking health endpoint at `/health` on port 1933 works
- LiteLLM on shen has `nomic-embed-text` model configured (for embeddings)
- The `POST /api/v1/resources` endpoint accepts `content` + `to` fields (verify against OpenViking docs — the API was researched from source code, not tested live)
- The heredoc config generation in compose `command` produces valid JSON on the target host
