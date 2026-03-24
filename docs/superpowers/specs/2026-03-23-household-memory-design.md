# Household Memory for Reelm

**Date:** 2026-03-23
**Status:** Approved design

## Problem

Reelm is an MCP-based media agent compatible with any AI client (Claude, ChatGPT, Copilot). Individual AI clients have their own memory, but there's no **shared household context** — what the family has watched, wants to watch, quality preferences, content rules. This context needs to survive switching between clients and be shared across household members.

## Decision

Integrate OpenMemory (mem0's self-hosted variant) into Reelm's compose stack as a household memory engine. Expose it through a thin wrapper MCP server mounted directly in the gateway.

### Why OpenMemory

- Proven memory engine (186M API calls/quarter in production)
- Handles fact extraction, deduplication, semantic search
- Supports pgvector — no need for a separate Qdrant container
- Native LLM provider configuration — points at LiteLLM (already deployed on shen)
- `user_id` scoping fits household vs per-person memory naturally

### Why a wrapper (not direct proxy)

- Tool descriptions frame memory as "shared household media context," avoiding confusion with the AI client's built-in personal memory
- Default `user_id` to "household" for shared facts
- Future extensibility — watchlist tools and scheduler integration will live in this wrapper

## Architecture

```
Client LLM (Claude/ChatGPT/Copilot)
  -> Reelm Gateway (OAuth 2.1, tool federation)
       -> reelm_memory_* tools (mounted directly, not proxied)
            -> OpenMemory REST API (internal container)
                 -> LiteLLM Proxy (via dokploy-network, already deployed)
                 -> Postgres 16 + pgvector (vector + relational storage)
```

### Key architectural choices

- **Memory tools in gateway process, not a separate container.** Unlike transmission/jackett/storage/tmdb (which are reusable standalone MCP servers), household memory is Reelm-specific. No separate service until there's reuse demand. This is the first use of `gateway.mount(local_mcp)` instead of `create_proxy(url)` — verify FastMCP supports mixing both patterns with the auth provider.
- **OpenMemory as internal infra.** No Traefik labels, no external access. `openmemory-api` lives on `reelm-internal` only. Gateway joins `reelm-internal` to reach it. `openmemory-api` also joins `dokploy-network` solely for LiteLLM access.
- **pgvector instead of Qdrant.** One Postgres instance handles both relational and vector storage. Fewer containers, fewer volumes.
- **LiteLLM for LLM + embeddings.** Already deployed as platform infrastructure on shen. OpenMemory points at `http://litellm:4000` via `dokploy-network`. Models: `llama3.2:3b` (extraction/dedup), `nomic-embed-text` (embeddings).

## Tools

Four tools exposed under `reelm_memory` namespace:

| Tool | Signature | Purpose |
|------|-----------|---------|
| `remember` | `(text: str, user_id: str = "household") -> str` | Store a household media fact |
| `recall` | `(query: str, user_id: str = "household") -> str` | Search household memory semantically |
| `list_memories` | `(user_id: str = "household") -> str` | List all stored memories |
| `forget` | `(memory_id: str) -> str` | Delete a specific memory |

`user_id` defaults to `"household"` for shared facts (e.g., "TV supports 4K", "we finished Breaking Bad"). Per-person context uses a name (e.g., `"denis"`, `"wife"`).

### Gateway instructions update

```
Use reelm_memory tools to store and recall shared household media context — what the
household has watched, wants to watch, quality preferences, content rules. This is NOT
your personal memory — it persists across all AI clients (Claude, ChatGPT, Copilot)
and is shared by all household members.
```

## Docker Compose Changes

New services added to `docker-compose.prod.yml`:

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
    openmemory-db: { condition: service_healthy }
  healthcheck:
    test: ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 15s
  networks: [dokploy-network, reelm-internal]
  restart: unless-stopped

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
  networks: [reelm-internal]
  restart: unless-stopped
```

New network and volume:

```yaml
networks:
  reelm-internal:
    internal: true    # Isolated — no external access

volumes:
  openmemory-pgdata:
```

Gateway service changes:

```yaml
gateway:
  environment:
    OPENMEMORY_URL: http://openmemory-api:8080
  depends_on:
    openmemory-api: { condition: service_healthy }
  networks: [dokploy-network, reelm-internal]  # Add reelm-internal
```

## Code Changes

### New: `src/mcps/servers/memory.py` (~80-100 lines)

Thin wrapper over OpenMemory REST API using `httpx`. Follows existing server pattern — `FastMCP` instance, `@mcp.tool` decorated functions, Pydantic models for responses.

### Modified: `src/mcps/gateway.py`

```python
from mcps.servers.memory import mcp as memory_mcp

# Mount directly (not proxied — memory is Reelm-internal)
gateway.mount(memory_mcp, namespace="reelm_memory")
```

### Modified: `src/mcps/config.py`

```python
openmemory_url: str = "http://openmemory-api:8080"
```

### Tests

Unit tests with mocked OpenMemory API responses (httpx mock), following existing patterns. Coverage for all 4 tools + error handling. Update `test_gateway_proxy.py` tool count to include the 4 new memory tools.

## Secrets & CI/CD

New GitHub secrets:

| Secret | Purpose |
|--------|---------|
| `LITELLM_MASTER_KEY` | Auth for LiteLLM proxy |
| `OPENMEMORY_POSTGRES_USER` | OpenMemory DB user |
| `OPENMEMORY_POSTGRES_PASSWORD` | OpenMemory DB password |

Added to `deploy.yml`:
- `Validate required secrets` step
- `ENV_CONTENT` block
- `Validate compose syntax` step — add dummy values for new env vars

## Not In Scope

- **Scheduler** — automatic episode downloads, watchlist polling (next phase)
- **Watchlist tools** — structured `add_to_watchlist`/`remove_from_watchlist` (future, lives in memory.py wrapper)
- **Per-user auth** — household shares one Reelm instance, `user_id` is honor-system for now
- **Migration tooling** — no existing memory data to migrate
- **Backup strategy** — `openmemory-pgdata` volume contains irreplaceable data; backup implementation deferred but needed before production reliance
- **Graceful degradation** — if OpenMemory is down, memory tools should return an error message rather than crash the gateway; implementation detail for memory.py
