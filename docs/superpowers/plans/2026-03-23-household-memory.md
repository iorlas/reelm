# Household Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared household memory to Reelm via OpenMemory, exposed as 4 MCP tools in the gateway.

**Architecture:** Thin wrapper MCP server (`memory.py`) mounted directly in the gateway calls OpenMemory's REST API via httpx. OpenMemory runs as an internal Docker service with pgvector-enabled Postgres. LiteLLM (already deployed) provides LLM + embeddings.

**Tech Stack:** FastMCP, httpx, pydantic, OpenMemory REST API, pgvector/pgvector:pg16, Docker Compose

**Spec:** `docs/superpowers/specs/2026-03-23-household-memory-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/mcps/servers/memory.py` | Memory MCP server — 4 tools wrapping OpenMemory REST API |
| Create | `tests/test_memory_unit.py` | Unit tests for all 4 memory tools |
| Modify | `src/mcps/config.py` | Add `openmemory_url` setting |
| Modify | `src/mcps/gateway.py` | Mount memory tools, update instructions |
| Modify | `tests/test_gateway_tools.py` | Add memory namespace, update tool count |
| Modify | `tests/test_gateway_proxy.py` | Update tool count (17 → 21) |
| Modify | `docker-compose.prod.yml` | Add openmemory-api, openmemory-db, reelm-internal network |
| Modify | `.github/workflows/deploy.yml` | Add new secrets to validation + ENV_CONTENT |

---

### Task 1: Add openmemory_url to config

**Files:**
- Modify: `src/mcps/config.py` (add after `transmission_ssl: bool = False`)

Note: `httpx` is already a project dependency (used by `jackett.py` and `storage.py`).

- [ ] **Step 1: Add the config field**

In `src/mcps/config.py`, add after the `transmission_ssl: bool = False` line:

```python
    # OpenMemory (default localhost for local dev; overridden via OPENMEMORY_URL env var in production)
    openmemory_url: str = "http://localhost:8080"
```

- [ ] **Step 2: Verify config loads**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run python -c "from mcps.config import settings; print(settings.openmemory_url)"`
Expected: `http://localhost:8080`

- [ ] **Step 3: Commit**

```bash
git add src/mcps/config.py
git commit -m "feat: add openmemory_url to settings"
```

---

### Task 2: Create memory MCP server with tests (TDD)

**Files:**
- Create: `src/mcps/servers/memory.py`
- Create: `tests/test_memory_unit.py`

#### 2a: Write failing tests for `remember` tool

- [ ] **Step 1: Write test file with remember test**

Create `tests/test_memory_unit.py`:

```python
"""Unit tests for memory MCP server (OpenMemory wrapper)."""

from unittest.mock import AsyncMock, patch

import pytest

from mcps.servers.memory import remember


@pytest.mark.unit
@pytest.mark.asyncio
class TestRemember:
    async def test_remember_stores_memory(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"id": "mem_123", "event": "ADD", "memory": "We finished Breaking Bad"}]
        }
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await remember("We finished Breaking Bad")

        assert "mem_123" in result
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["user_id"] == "household"

    async def test_remember_with_custom_user_id(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"id": "mem_456", "event": "ADD", "memory": "Denis prefers original audio"}]
        }
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await remember("Denis prefers original audio", user_id="denis")

        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["user_id"] == "denis"

    async def test_remember_handles_api_error(self):
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client_cls.return_value = mock_client

            result = await remember("test")

        assert "error" in result.lower() or "unavailable" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcps.servers.memory'`

#### 2b: Implement memory server with `remember` tool

- [ ] **Step 3: Create memory.py with remember tool**

Create `src/mcps/servers/memory.py`:

```python
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
        result = await _post("/memories", json={
            "messages": [{"role": "user", "content": text}],
            "user_id": user_id,
        })
        entries = result.get("results", [])
        if not entries:
            return "Memory stored (no details returned)."
        parts = [f"- [{e.get('event', '?')}] {e.get('memory', '?')} (id: {e.get('id', '?')})" for e in entries]
        return "Stored:\n" + "\n".join(parts)
    except Exception as e:
        return f"Memory unavailable: {e}"
```

- [ ] **Step 4: Run remember tests**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py::TestRemember -v`
Expected: PASS (3 tests)

#### 2c: Add recall tool with tests

- [ ] **Step 5: Add recall tests to test_memory_unit.py**

Append to `tests/test_memory_unit.py`:

```python
from mcps.servers.memory import recall


@pytest.mark.unit
@pytest.mark.asyncio
class TestRecall:
    async def test_recall_searches_memories(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"id": "mem_123", "memory": "We finished Breaking Bad", "score": 0.95},
            ]
        }
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await recall("What have we watched?")

        assert "Breaking Bad" in result
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["query"] == "What have we watched?"

    async def test_recall_empty_results(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await recall("anything about cats")

        assert "no memories" in result.lower() or "nothing found" in result.lower()

    async def test_recall_handles_api_error(self):
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client_cls.return_value = mock_client

            result = await recall("test")

        assert "error" in result.lower() or "unavailable" in result.lower()
```

- [ ] **Step 6: Implement recall tool**

Add to `src/mcps/servers/memory.py`:

```python
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
        result = await _post("/memories/search", json={
            "query": query,
            "user_id": user_id,
        })
        entries = result.get("results", result) if isinstance(result, dict) else result
        if not entries:
            return "Nothing found in household memory."
        parts = [f"- {e.get('memory', '?')} (score: {e.get('score', '?')}, id: {e.get('id', '?')})" for e in entries]
        return "Found:\n" + "\n".join(parts)
    except Exception as e:
        return f"Memory unavailable: {e}"
```

- [ ] **Step 7: Run recall tests**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py::TestRecall -v`
Expected: PASS (3 tests)

#### 2d: Add list_memories tool with tests

- [ ] **Step 8: Add list_memories tests to test_memory_unit.py**

Append to `tests/test_memory_unit.py`:

```python
from mcps.servers.memory import list_memories


@pytest.mark.unit
@pytest.mark.asyncio
class TestListMemories:
    async def test_list_memories_returns_all(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "mem_1", "memory": "TV supports 4K", "user_id": "household"},
            {"id": "mem_2", "memory": "We like sci-fi", "user_id": "household"},
        ]
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await list_memories()

        assert "4K" in result
        assert "sci-fi" in result

    async def test_list_memories_empty(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await list_memories()

        assert "no memories" in result.lower() or "empty" in result.lower()
```

- [ ] **Step 9: Implement list_memories tool**

Add to `src/mcps/servers/memory.py`:

```python
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
    except Exception as e:
        return f"Memory unavailable: {e}"
```

- [ ] **Step 10: Run list_memories tests**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py::TestListMemories -v`
Expected: PASS (2 tests)

#### 2e: Add forget tool with tests

- [ ] **Step 11: Add forget tests to test_memory_unit.py**

Append to `tests/test_memory_unit.py`:

```python
from mcps.servers.memory import forget


@pytest.mark.unit
@pytest.mark.asyncio
class TestForget:
    async def test_forget_deletes_memory(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Memory deleted"}
        mock_response.raise_for_status = AsyncMock()

        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.delete = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await forget("mem_123")

        assert "deleted" in result.lower() or "forgotten" in result.lower()
        mock_client.delete.assert_called_once()

    async def test_forget_handles_api_error(self):
        with patch("mcps.servers.memory.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.delete = AsyncMock(side_effect=Exception("Not found"))
            mock_client_cls.return_value = mock_client

            result = await forget("nonexistent")

        assert "error" in result.lower() or "unavailable" in result.lower()
```

- [ ] **Step 12: Implement forget tool**

Add to `src/mcps/servers/memory.py`:

```python
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
    except Exception as e:
        return f"Memory unavailable: {e}"
```

- [ ] **Step 13: Run all memory tests**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_memory_unit.py -v`
Expected: PASS (10 tests)

- [ ] **Step 14: Commit**

```bash
git add src/mcps/servers/memory.py tests/test_memory_unit.py
git commit -m "feat: add memory MCP server wrapping OpenMemory REST API"
```

---

### Task 3: Mount memory in gateway

**Files:**
- Modify: `src/mcps/gateway.py`
- Modify: `tests/test_gateway_tools.py`
- Modify: `tests/test_gateway_proxy.py`

- [ ] **Step 1: Update gateway.py**

In `src/mcps/gateway.py`, add import after existing imports (line 14):

```python
from mcps.servers.memory import mcp as memory_mcp
```

Add `OPENMEMORY_URL` is not needed here — `memory.py` reads from `settings` directly.

Update the instructions string (line 38-44) to include memory:

```python
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
```

Add memory mount after the existing mounts (after line 52):

```python
gateway.mount(memory_mcp, namespace="reelm_memory")
```

- [ ] **Step 2: Update test_gateway_tools.py**

In `tests/test_gateway_tools.py`, add memory import (line 9):

```python
from mcps.servers.memory import mcp as memory_mcp
```

Add to the `BACKENDS` dict (line 16):

```python
    "reelm_memory": memory_mcp,
```

Update `test_gateway_tool_count` (line 58-59) — change `17` to `21`:

```python
    # transmission: 8, jackett: 2, storage: 4, tmdb: 3, memory: 4 = 21 total
    assert len(tools) == 21, f"Expected 21 tools, got {len(tools)}: {[t.name for t in tools]}"
```

Add spot-check in `test_gateway_lists_all_tools` (after line 47):

```python
    assert "reelm_memory_remember" in tool_names
```

- [ ] **Step 3: Update test_gateway_proxy.py**

In `tests/test_gateway_proxy.py`, add memory import (after line 10):

```python
from mcps.servers.memory import mcp as memory_mcp
```

**Important:** Do NOT add memory to the `BACKENDS` dict — that dict is for proxy-mounted backends. Memory is mounted directly in production. Update the fixture to mount memory separately:

```python
@pytest.fixture
def gateway_with_proxies():
    """Gateway that mounts backends via create_proxy (same as production)."""
    gw = FastMCP("Reelm")
    for namespace, backend in BACKENDS.items():
        gw.mount(create_proxy(backend), namespace=namespace)
    # Memory is mounted directly (not proxied), matching production
    gw.mount(memory_mcp, namespace="reelm_memory")
    return gw
```

Update tool count assertion — change `17` to `21`:

```python
    assert len(tool_names) == 21, f"Expected 21 tools, got {len(tool_names)}: {tool_names}"
```

Update the namespace check to also verify `reelm_memory`:

```python
    for namespace in [*BACKENDS, "reelm_memory"]:
```

- [ ] **Step 4: Run all gateway tests**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run pytest tests/test_gateway_tools.py tests/test_gateway_proxy.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/iorlas/Workspaces/reelm && make test`
Expected: PASS with coverage ≥ 90%

- [ ] **Step 6: Commit**

```bash
git add src/mcps/gateway.py tests/test_gateway_tools.py tests/test_gateway_proxy.py
git commit -m "feat: mount memory tools in gateway with household instructions"
```

---

### Task 4: Update docker-compose.prod.yml

**Files:**
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Add reelm-internal network and openmemory volume**

At the bottom of `docker-compose.prod.yml`, update volumes and networks sections:

```yaml
volumes:
  jackett-config:
  openmemory-pgdata:

networks:
  dokploy-network:
    external: true
  reelm-internal:
    internal: true
```

- [ ] **Step 2: Add openmemory-db service**

Add after the `jackett` service block:

```yaml
  # ── OpenMemory infrastructure (internal, no external access) ──
  openmemory-db:
    image: pgvector/pgvector:pg16
    pull_policy: always
    environment:
      POSTGRES_USER: ${OPENMEMORY_POSTGRES_USER}
      POSTGRES_PASSWORD: ${OPENMEMORY_POSTGRES_PASSWORD}
      POSTGRES_DB: openmemory
    volumes:
      - openmemory-pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${OPENMEMORY_POSTGRES_USER:-postgres}"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - reelm-internal
    restart: unless-stopped
```

- [ ] **Step 3: Add openmemory-api service**

Add after `openmemory-db`:

```yaml
  openmemory-api:
    image: ghcr.io/mem0ai/openmemory:latest
    pull_policy: always
    environment:
      LLM_PROVIDER: openai
      LLM_BASE_URL: http://litellm:4000
      LLM_API_KEY: ${LITELLM_MASTER_KEY}
      LLM_MODEL: llama3.2:3b
      EMBEDDER_PROVIDER: openai
      EMBEDDER_BASE_URL: http://litellm:4000
      EMBEDDER_API_KEY: ${LITELLM_MASTER_KEY}
      EMBEDDER_MODEL: nomic-embed-text
      DATABASE_URL: postgresql://${OPENMEMORY_POSTGRES_USER}:${OPENMEMORY_POSTGRES_PASSWORD}@openmemory-db:5432/openmemory
      VECTOR_STORE_PROVIDER: pgvector
    depends_on:
      openmemory-db:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 15s
    networks:
      - dokploy-network
      - reelm-internal
    restart: unless-stopped
```

- [ ] **Step 4: Update gateway service**

Add to gateway's `environment` block:

```yaml
      OPENMEMORY_URL: http://openmemory-api:8080
```

Add to gateway's `depends_on` block:

```yaml
      openmemory-api:
        condition: service_healthy
```

Add `reelm-internal` to gateway's networks. The gateway inherits `networks: [dokploy-network]` from the `x-reelm` anchor. Adding an explicit `networks` key to the gateway service block **overrides** the anchor (YAML merge does not deep-merge lists). So add both networks explicitly:

```yaml
    networks:
      - dokploy-network
      - reelm-internal
```

- [ ] **Step 5: Validate compose syntax locally**

Run:
```bash
cd /Users/iorlas/Workspaces/reelm && \
  IMAGE_TAG=test TRANSMISSION_USER=x TRANSMISSION_PASS=x \
  JACKETT_API_KEY=x WEBDAV_URL=x WEBDAV_USER=x WEBDAV_PASS=x TMDB_API_KEY=x \
  GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=x \
  OPENMEMORY_POSTGRES_USER=x OPENMEMORY_POSTGRES_PASSWORD=x LITELLM_MASTER_KEY=x \
  docker compose -f docker-compose.prod.yml config --quiet
```
Expected: No output (success)

- [ ] **Step 6: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat: add openmemory services to production compose"
```

---

### Task 5: Update CI/CD pipeline

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Update compose validation step**

In `.github/workflows/deploy.yml`, update the "Validate compose syntax" step (line 60-65). Add after line 63:

```yaml
          export OPENMEMORY_POSTGRES_USER=x OPENMEMORY_POSTGRES_PASSWORD=x LITELLM_MASTER_KEY=x
```

- [ ] **Step 2: Update "Validate required secrets" step**

Add to the `env` block (after line 121):

```yaml
          LITELLM_MASTER_KEY: ${{ secrets.LITELLM_MASTER_KEY }}
          OPENMEMORY_POSTGRES_USER: ${{ secrets.OPENMEMORY_POSTGRES_USER }}
          OPENMEMORY_POSTGRES_PASSWORD: ${{ secrets.OPENMEMORY_POSTGRES_PASSWORD }}
```

Add to the validation checks (after line 135):

```bash
          [ -z "$LITELLM_MASTER_KEY" ] && MISSING="$MISSING LITELLM_MASTER_KEY"
          [ -z "$OPENMEMORY_POSTGRES_USER" ] && MISSING="$MISSING OPENMEMORY_POSTGRES_USER"
          [ -z "$OPENMEMORY_POSTGRES_PASSWORD" ] && MISSING="$MISSING OPENMEMORY_POSTGRES_PASSWORD"
```

- [ ] **Step 3: Update "Sync compose + env" step**

Add to the `env` block (after line 155):

```yaml
          LITELLM_MASTER_KEY: ${{ secrets.LITELLM_MASTER_KEY }}
          OPENMEMORY_POSTGRES_USER: ${{ secrets.OPENMEMORY_POSTGRES_USER }}
          OPENMEMORY_POSTGRES_PASSWORD: ${{ secrets.OPENMEMORY_POSTGRES_PASSWORD }}
```

Add to `ENV_CONTENT` printf (after line 170):

```bash
            "LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}" \
            "OPENMEMORY_POSTGRES_USER=${OPENMEMORY_POSTGRES_USER}" \
            "OPENMEMORY_POSTGRES_PASSWORD=${OPENMEMORY_POSTGRES_PASSWORD}" \
```

- [ ] **Step 4: Run lint on workflow file**

Run: `cd /Users/iorlas/Workspaces/reelm && uv run yamllint .github/workflows/deploy.yml`
Expected: No errors (or only existing warnings)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "feat: add openmemory secrets to CI/CD pipeline"
```

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
Verify only expected files changed.

- [ ] **Step 4: Note for deployment (human gate)**

Before deploying, the following GitHub secrets must be set:
- `LITELLM_MASTER_KEY` — from LiteLLM proxy config on shen
- `OPENMEMORY_POSTGRES_USER` — choose a username (e.g., `openmemory`)
- `OPENMEMORY_POSTGRES_PASSWORD` — generate with `openssl rand -hex 32`

Also verify:
- OpenMemory Docker image exists at `ghcr.io/mem0ai/openmemory` and exposes `/health` endpoint on port 8080
- OpenMemory supports `VECTOR_STORE_PROVIDER=pgvector` env var configuration
- LiteLLM has `nomic-embed-text` model configured and working

These need verification during first deploy — the OpenMemory image, port, health endpoint, and env var names may differ from documentation.
