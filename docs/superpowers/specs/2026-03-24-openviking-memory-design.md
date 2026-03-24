# Household Memory via OpenViking

**Date:** 2026-03-24
**Status:** Approved design
**Supersedes:** `2026-03-23-household-memory-design.md` (mem0/OpenMemory approach — rejected due to arm64-only images, double-LLM problem, neglected self-hosting)

## Problem

Reelm needs shared household media context (what we've watched, preferences, content rules) that persists across all AI clients. The client LLM already extracts facts — the memory backend should store and retrieve, not re-process.

## Decision

Replace mem0/OpenMemory with **OpenViking** (ByteDance's context database). Direct filesystem writes — no internal LLM for memory extraction. OpenViking handles storage, vectorization, and semantic search.

### Why OpenViking over mem0

- **No double-LLM problem.** Direct filesystem writes skip mem0's internal extraction pipeline. The client LLM already did the thinking.
- **Single container.** No Postgres, no Neo4j, no Qdrant. Built-in vector DB on local disk.
- **Future-ready.** The `viking://` filesystem supports skills (`viking://agent/skills/`) — Reelm's next feature after memory.
- **Working Docker image.** `ghcr.io/volcengine/openviking:main` supports amd64+arm64.
- **Apache 2.0.** ByteDance-backed, 15K stars, actively maintained.

## Architecture

```
Client LLM (Claude/ChatGPT/Copilot)
  → Reelm Gateway (OAuth 2.1, tool federation)
       → reelm_memory_* tools (memory.py, mounted directly in gateway)
            → OpenViking REST API (http://openviking:1933)
                 → LiteLLM Proxy (http://litellm:4000, for embeddings + search)
                 → Local disk (/app/data volume)
```

### Key choices

- **Write via resources API.** `remember` uses `POST /api/v1/resources` with a `to` URI. There is no direct "write file" HTTP endpoint — the resources API is OpenViking's ingestion path. This triggers vectorization + L0/L1 summary generation via VLM. Acceptable overhead for a side feature.
- **OpenViking as sidecar in Reelm compose.** Memory is a product feature, not shared infra.
- **Config inline in compose.** `ov.conf` generated at container startup via heredoc in `command`. No external config file — Dokploy-friendly.
- **Archive on forget, not delete.** `forget` moves files to `viking://user/archive/{user_id}/` (separate from memories). OpenViking's search recurses into subdirectories, so `.archive/` inside the memories dir would leak forgotten items into `recall` results.
- **LiteLLM for VLM + embeddings.** Already deployed on shen, no auth. OpenViking uses it for L0/L1 generation on `remember`, vectorization, and search intent analysis. VLM config IS needed even though we skip sessions API.
- **Memory IDs.** Each memory gets a timestamped filename: `{unix_ts}-{short_hash}.md`. The full `viking://` URI is the `memory_id` returned to the user and used by `forget`.
- **`mkdir` is not idempotent.** Returns 409 if directory exists. `_ensure_dir` must catch 409 and ignore it.

## Tools

Four tools under `reelm_memory` namespace:

| Tool | Signature | OpenViking API | Notes |
|------|-----------|---------------|-------|
| `remember` | `(text: str, user_id: str = "household") -> str` | `POST /api/v1/resources` with `to=viking://user/memories/{user_id}/{ts}-{hash}.md` | Creates dir on first use via `_ensure_dir`. Triggers vectorization + L0/L1 via VLM. |
| `recall` | `(query: str, user_id: str = "household") -> str` | `POST /api/v1/search/find` with `target_uri=viking://user/memories/{user_id}/` | Returns `memories[]` with `uri`, `abstract`, `score`, `match_reason`. |
| `list_memories` | `(user_id: str = "household") -> str` | `GET /api/v1/fs/ls?uri=viking://user/memories/{user_id}/` | Returns entries with `name`, `uri`, `modTime`, `isDir`. |
| `forget` | `(memory_id: str) -> str` | `POST /api/v1/fs/mv` with `from_uri={memory_id}` `to_uri=viking://user/archive/{user_id}/{name}` | Archive outside search path. Timestamps in filenames prevent collision. |

`user_id` maps to subdirectories: `viking://user/memories/household/`, `viking://user/memories/denis/`, etc.
Archive goes to `viking://user/archive/{user_id}/` — separate from memories, so `recall` never returns forgotten items.

### Response formats (from OpenViking source)

**search/find response:**
```json
{
  "status": "ok",
  "result": {
    "memories": [{"uri": "viking://...", "abstract": "...", "score": 0.95, "match_reason": "..."}],
    "total": 1
  }
}
```

**fs/ls response:**
```json
{
  "status": "ok",
  "result": [{"name": "...", "uri": "viking://...", "modTime": "2026-...", "isDir": false}]
}
```

**fs/mv response:**
```json
{"status": "ok", "result": {"from": "viking://...", "to": "viking://..."}}
```

### Gateway instructions

```
Use reelm_memory tools to store and recall shared household media context — what the
household has watched, wants to watch, quality preferences, content rules. This is NOT
your personal memory — it persists across all AI clients (Claude, ChatGPT, Copilot)
and is shared by all household members.
```

## Docker Compose Changes

### New service

```yaml
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

### Gateway changes

```yaml
gateway:
  environment:
    OPENVIKING_URL: http://openviking:1933
  depends_on:
    openviking:
      condition: service_healthy
```

### Cleanup

- Remove commented-out mem0 services entirely
- Remove `OPENMEMORY_POSTGRES_USER` and `OPENMEMORY_POSTGRES_PASSWORD` from CI/CD secrets validation and ENV_CONTENT
- Replace `OPENMEMORY_URL` with `OPENVIKING_URL`

### New volume

```yaml
volumes:
  openviking-data:
```

## Code Changes

### Modified: `src/mcps/servers/memory.py`

Rewrite HTTP calls from mem0 format to OpenViking REST API:
- `_BASE_URL` reads from `settings.openviking_url`
- `remember` → `POST /api/v1/resources` with `to=viking://user/memories/{user_id}/{ts}-{hash}.md`. Write text as a temp file, pass path to resources API. Filename: `{unix_timestamp}-{first_8_chars_of_content_hash}.md`
- `recall` → `POST /api/v1/search/find` with `target_uri=viking://user/memories/{user_id}/`. Parse `result.memories[]` for `uri`, `abstract`, `score`.
- `list_memories` → `GET /api/v1/fs/ls?uri=viking://user/memories/{user_id}/`. Parse `result[]` for `name`, `uri`, `modTime`.
- `forget` → `POST /api/v1/fs/mv` with `from_uri=<memory_uri>`, `to_uri=viking://user/archive/{user_id}/{filename}`. Archive path is outside memories search scope.
- Helper `_ensure_dir(uri)` → `POST /api/v1/fs/mkdir` body `{"uri": uri}`. Catch HTTP 409 (already exists) and ignore.

### Modified: `src/mcps/config.py`

- Rename `openmemory_url` → `openviking_url`, default `http://localhost:1933`

### Modified: `src/mcps/gateway.py`

- No changes needed — memory is already mounted, instructions already set

### Modified: `docker-compose.prod.yml`

- Remove all mem0 services and comments
- Add `openviking` service (as above)
- Update gateway env: `OPENVIKING_URL`
- Add `openviking-data` volume
- Remove `mem0-pgdata`, `mem0-neo4j` volumes

### Modified: `.github/workflows/deploy.yml`

- Remove `OPENMEMORY_POSTGRES_USER` and `OPENMEMORY_POSTGRES_PASSWORD` from:
  - Compose validation step
  - Validate required secrets step
  - Sync compose + env step / ENV_CONTENT
- Add `OPENVIKING_URL` dummy to compose validation

### Modified: `tests/test_memory_unit.py`

- Update all mocks from mem0 response format to OpenViking response format
- Same test coverage (remember, recall, list, forget + error handling)

## Secrets & CI/CD

**Removed secrets** (no longer needed):
- `OPENMEMORY_POSTGRES_USER`
- `OPENMEMORY_POSTGRES_PASSWORD`

**No new secrets.** OpenViking config is inline in compose. LiteLLM has no auth.

## Not In Scope

- **Skills distribution** — future phase, will use `viking://agent/skills/`
- **Sessions API / auto-extraction** — not needed; client LLM handles extraction
- **OpenViking UI** — no dashboard needed
- **Backup strategy** — volume backup deferred
- **Scheduler** — next phase after memory
- **Archive pruning** — `.archive/` grows unboundedly; cleanup deferred
- **Data migration** — no existing memory data to migrate (mem0 was never deployed due to arm64 issue)
- **Graceful degradation** — if OpenViking or LiteLLM is down, memory tools return error; does not affect core Reelm functionality (search, download, storage)
