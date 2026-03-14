from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.routing import Router

from mcps.auth.provider import McpsOAuthProvider
from mcps.config import settings
from mcps.servers.jackett import mcp as jackett_mcp
from mcps.servers.tmdb import mcp as tmdb_mcp
from mcps.servers.transmission import mcp as transmission_mcp

# Create per-server OAuth providers with correct base_url per mount path.
# Each provider needs its own base_url so OAuth metadata advertises endpoints
# at the correct subpath (e.g., /jackett/authorize, not /authorize).
_auth_providers: dict[str, McpsOAuthProvider] = {}
if settings.auth_users:
    users = settings.get_users()
    issuer = settings.auth_issuer.rstrip("/")
    for mcp_instance, mount in [(jackett_mcp, "jackett"), (tmdb_mcp, "tmdb"), (transmission_mcp, "transmission")]:
        provider = McpsOAuthProvider(
            base_url=f"{issuer}/{mount}",
            users=users,
        )
        mcp_instance.auth = provider
        _auth_providers[mount] = provider

# Create HTTP apps (auth is read from mcp.auth internally)
jackett_app = jackett_mcp.http_app(path="/")
tmdb_app = tmdb_mcp.http_app(path="/")
transmission_app = transmission_mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with jackett_app.lifespan(jackett_app):
        async with tmdb_app.lifespan(tmdb_app):
            async with transmission_app.lifespan(transmission_app):
                yield


app = FastAPI(title="mcps", lifespan=lifespan)

# Add well-known discovery routes at root level (RFC 9728).
# MCP clients look for /.well-known/oauth-protected-resource/{path} and
# /.well-known/oauth-authorization-server/{path} at the domain root.
# These must be added directly to the router (not mounted) to preserve full paths.
for mount_name, provider in _auth_providers.items():
    for route in provider.get_well_known_routes(mcp_path="/"):
        app.router.routes.append(route)

app.mount("/jackett", jackett_app)
app.mount("/tmdb", tmdb_app)
app.mount("/transmission", transmission_app)


@app.get("/")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
