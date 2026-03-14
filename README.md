# mcps

Remote MCP servers for Jackett (torrent search), Transmission (torrent management), and TMDB (movie discovery).

## Setup

```bash
cp .env.example .env
# Edit .env with your API keys and credentials
uv sync
uv run uvicorn mcps.server:app --host 0.0.0.0 --port 8000
```
