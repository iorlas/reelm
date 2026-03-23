#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28,<1.0", "websockets>=15"]
# ///
"""dokctl — thin CLI over the Dokploy API.

Encodes known API workarounds so AI agents (and humans) don't need to.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import ssl
import sys
import time
from pathlib import Path

import httpx
import websockets

CONFIG_DIR = Path.home() / ".config" / "dokploy"
TIMEOUT = 30.0


def load_config() -> tuple[str, str]:
    """Return (base_url, token). Exit with clear error if missing."""
    token_path = CONFIG_DIR / "token"
    url_path = CONFIG_DIR / "url"

    errors = []
    if not token_path.exists():
        errors.append(f"Missing token file: {token_path}")
    if not url_path.exists():
        errors.append(f"Missing URL file: {url_path}")
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"\nSetup:\n  mkdir -p {CONFIG_DIR}\n  echo 'YOUR_TOKEN' > {token_path}\n  echo 'https://your-dokploy-url' > {url_path}", file=sys.stderr)
        sys.exit(1)

    token = token_path.read_text().strip()
    url = url_path.read_text().strip().rstrip("/")
    return url, token


def api_call(client: httpx.Client, method: str, endpoint: str, data: dict | None = None) -> httpx.Response:
    """Make an API call. Endpoint is like 'compose.one' (no /api/ prefix needed)."""
    url = f"/api/{endpoint}"
    if method == "GET":
        resp = client.get(url, params=data)
    else:
        resp = client.post(url, json=data)
    return resp


def print_response(resp: httpx.Response) -> None:
    """Print response with status. Exit 1 on HTTP error."""
    try:
        body = resp.json()
        print(json.dumps(body, indent=2))
    except Exception:
        print(resp.text)

    if resp.is_error:
        print(f"\nerror: HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(1)


def make_client(url: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=url,
        headers={"x-api-key": token, "Content-Type": "application/json"},
        timeout=TIMEOUT,
    )


# ── Env helpers ──


def extract_env_vars(compose_content: str) -> list[str]:
    """Find all ${VAR} references in a compose file. Returns sorted unique names."""
    return sorted(set(re.findall(r'\$\{(\w+)\}', compose_content)))


def build_env_from_compose(compose_content: str) -> str:
    """Read ${VAR} refs from compose, resolve from os.environ, validate, return env string."""
    var_names = extract_env_vars(compose_content)
    if not var_names:
        return ""

    missing = [v for v in var_names if not os.environ.get(v)]
    if missing:
        print(f"error: Missing environment variables referenced in compose file:", file=sys.stderr)
        for v in missing:
            print(f"  ${{{v}}}", file=sys.stderr)
        print(f"\nSet them in the environment before running dokctl.", file=sys.stderr)
        sys.exit(1)

    lines = [f"{v}={os.environ[v]}" for v in var_names]
    print(f"Env: {len(var_names)} vars resolved from compose: {', '.join(var_names)}")
    return "\n".join(lines)


# ── WebSocket helpers ──


def _ws_url(base_url: str) -> str:
    """Convert https://host to wss://host."""
    return base_url.replace("https://", "wss://").replace("http://", "ws://")


def fetch_container_logs(
    base_url: str, token: str, container_id: str,
    tail: int = 50, since: str = "5m", recv_timeout: float = 5.0,
) -> list[str]:
    """Fetch container logs via Dokploy WebSocket. Returns list of log lines."""
    ws_base = _ws_url(base_url)
    url = f"{ws_base}/docker-container-logs?containerId={container_id}&tail={tail}&since={since}"

    async def _fetch() -> list[str]:
        lines: list[str] = []
        ssl_ctx = ssl.create_default_context()
        try:
            async with websockets.connect(
                url, ssl=ssl_ctx,
                additional_headers={"x-api-key": token},
                open_timeout=10, close_timeout=3,
            ) as ws:
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                        text = msg if isinstance(msg, str) else msg.decode("utf-8", errors="replace")
                        lines.append(text)
                    except asyncio.TimeoutError:
                        break
                    except websockets.exceptions.ConnectionClosed:
                        break
        except Exception as e:
            print(f"warning: WebSocket error: {e}", file=sys.stderr)
        return lines

    return asyncio.run(_fetch())


def get_containers(client: httpx.Client, app_name: str) -> list[dict]:
    """Get containers matching an app name from docker.getContainers."""
    resp = api_call(client, "GET", "docker.getContainers")
    if resp.is_error:
        return []
    containers = resp.json()
    if not isinstance(containers, list):
        return []
    return [c for c in containers if app_name in c.get("name", "")]


def get_problem_containers(containers: list[dict]) -> list[dict]:
    """Return containers sorted by severity: exited/dead first, unhealthy second, healthy last."""
    def severity(c: dict) -> int:
        state = c.get("state", "")
        status = c.get("status", "")
        if state in ("exited", "dead", "created"):
            return 0  # worst — show first
        if state == "running" and "(unhealthy)" in status:
            return 1
        if state == "running" and "(health: starting)" in status.lower():
            return 2
        return 3  # healthy — show last

    return sorted(containers, key=severity)


def show_problem_logs(base_url: str, token: str, containers: list[dict], app_name: str) -> None:
    """Show logs for unhealthy/failed containers only."""
    problem = [c for c in get_problem_containers(containers)
               if c.get("state") != "running" or "(healthy)" not in c.get("status", "")]
    if not problem:
        return

    print(f"\nLogs for problem containers:", file=sys.stderr)
    for c in problem:
        cid = c.get("containerId", "")
        cname = c.get("name", "?")
        short = cname.replace(f"{app_name}-", "").rstrip("-1234567890")
        state = c.get("state", "?")
        status = c.get("status", "")

        if not cid:
            continue

        print(f"\n--- {short} ({state}, {status}) ---", file=sys.stderr)
        lines = fetch_container_logs(base_url, token, cid, tail=50, since="5m", recv_timeout=3)
        for line in lines:
            print(f"  {line.rstrip()[:200]}", file=sys.stderr)


def verify_container_health(client: httpx.Client, app_name: str, timeout: int = 120) -> bool:
    """Poll containers until all are healthy or timeout. Returns True if healthy."""
    max_attempts = timeout // 5
    for i in range(1, max_attempts + 1):
        containers = get_containers(client, app_name)
        if not containers:
            print(f"  [health {i}/{max_attempts}] No containers found for {app_name}")
            time.sleep(5)
            continue

        all_healthy = True
        for c in containers:
            state = c.get("state", "unknown")
            status = c.get("status", "")

            if state != "running":
                all_healthy = False
            elif "(healthy)" not in status and "(health:" in status.lower():
                all_healthy = False

        states = ", ".join(
            f"{c.get('name','?').replace(app_name + '-', '').rstrip('-1234567890')}={c.get('state','?')}"
            for c in containers
        )
        print(f"  [health {i}/{max_attempts}] {states}")

        if all_healthy and containers:
            return True

        time.sleep(5)

    return False


# ── Commands ──


def cmd_api(client: httpx.Client, args: argparse.Namespace) -> None:
    """Raw API call: dokctl api compose.one --data '{"composeId":"xxx"}'"""
    data = json.loads(args.data) if args.data else None
    method = "POST" if data else "GET"
    resp = api_call(client, method, args.endpoint, data)
    print_response(resp)


def cmd_status(client: httpx.Client, args: argparse.Namespace) -> None:
    """Show compose app status, optionally with live container health."""
    resp = api_call(client, "GET", "compose.one", {"composeId": args.compose_id})
    if resp.is_error:
        print_response(resp)
        return
    data = resp.json()
    app_name = data.get("appName", "?")
    print(f"Name:         {data.get('name', '?')}")
    print(f"App name:     {app_name}")
    print(f"Status:       {data.get('composeStatus', '?')}")
    print(f"Source type:   {data.get('sourceType', '?')}")
    print(f"Compose type:  {data.get('composeType', '?')}")
    compose_file = data.get("composeFile", "")
    print(f"Compose len:  {len(compose_file)} chars")
    env = data.get("env", "")
    env_keys = [line.split("=")[0] for line in env.strip().splitlines() if "=" in line]
    print(f"Env keys:     {', '.join(env_keys) if env_keys else '(none)'}")

    # Show latest deployment
    deployments = data.get("deployments", [])
    if deployments:
        latest = deployments[0]
        print(f"\nLast deploy:  {latest.get('title', '?')} ({latest.get('status', '?')})")
        print(f"  at:         {latest.get('createdAt', '?')}")
        if latest.get("errorMessage"):
            print(f"  error:      {latest['errorMessage']}")

    # Live container health
    if getattr(args, "live", False):
        print(f"\nContainers:")
        containers = get_containers(client, app_name)
        if not containers:
            print("  (none found)")
        for c in containers:
            name = c.get("name", "?")
            short = name.replace(f"{app_name}-", "").rstrip("-1234567890")
            print(f"  {short:30} {c.get('state', '?'):10} {c.get('status', '')}")


def _resolve_env(args: argparse.Namespace, compose_content: str) -> str | None:
    """Resolve env payload from --env-file or auto-detect from compose ${VAR} refs."""
    if getattr(args, "env_file", None):
        return Path(args.env_file).read_text()
    # Auto-detect: scan compose for ${VAR} and resolve from os.environ
    env_vars = extract_env_vars(compose_content)
    if env_vars:
        return build_env_from_compose(compose_content)
    return None


def cmd_sync(client: httpx.Client, args: argparse.Namespace) -> None:
    """Sync compose file + env to Dokploy. Verifies the update persisted."""
    compose_content = Path(args.compose_file).read_text()

    payload: dict = {
        "composeId": args.compose_id,
        "composeFile": compose_content,
        "sourceType": "raw",  # Always force raw — workaround for I0071
    }

    env_content = _resolve_env(args, compose_content)
    if env_content is not None:
        payload["env"] = env_content

    resp = api_call(client, "POST", "compose.update", payload)
    if resp.is_error:
        print_response(resp)
        sys.exit(1)

    # Verify — compose.update silently ignores wrong field names
    result = resp.json()
    stored_len = len(result.get("composeFile", ""))
    sent_len = len(compose_content)

    if stored_len < 10:
        print(f"error: compose.update did not persist composeFile (got {stored_len} chars, sent {sent_len})", file=sys.stderr)
        sys.exit(1)

    print(f"Synced: {stored_len} chars persisted, sourceType={result.get('sourceType', '?')}")

    if env_content is not None:
        stored_env = result.get("env", "")
        print(f"Env: {len(stored_env)} chars persisted")


def cmd_deploy(client: httpx.Client, args: argparse.Namespace) -> None:
    """Sync + deploy + poll until done/error + verify container health."""
    url, token = load_config()

    # Step 1: sync (includes env resolution + validation)
    cmd_sync(client, args)

    # Step 2: snapshot current latest deployment ID (to detect the new one)
    pre_resp = api_call(client, "GET", "deployment.allByCompose", {
        "composeId": args.compose_id,
    })
    prev_deploy_id = None
    if not pre_resp.is_error:
        pre_deployments = pre_resp.json()
        if pre_deployments and isinstance(pre_deployments, list):
            prev_deploy_id = pre_deployments[0].get("deploymentId")

    # Step 3: trigger deploy
    print("\nTriggering deploy...")
    deploy_resp = api_call(client, "POST", "compose.deploy", {
        "composeId": args.compose_id,
    })
    if deploy_resp.is_error:
        print_response(deploy_resp)
        return

    print("Deploy triggered. Polling status...")

    # Step 4: poll Dokploy deploy status — wait for a NEW deployment (not the old one)
    max_attempts = args.timeout // 5
    app_name = ""
    for i in range(1, max_attempts + 1):
        time.sleep(5)
        status_resp = api_call(client, "GET", "deployment.allByCompose", {
            "composeId": args.compose_id,
        })
        if status_resp.is_error:
            status_resp = api_call(client, "GET", "deployment.all", {
                "composeId": args.compose_id,
            })

        if status_resp.is_error:
            print(f"  [{i}/{max_attempts}] Failed to fetch status (HTTP {status_resp.status_code})")
            continue

        deployments = status_resp.json()
        if not deployments:
            print(f"  [{i}/{max_attempts}] No deployments found")
            continue

        latest = deployments[0] if isinstance(deployments, list) else deployments

        # Skip stale deployment from before our trigger
        if prev_deploy_id and latest.get("deploymentId") == prev_deploy_id:
            print(f"  [{i}/{max_attempts}] Waiting for new deployment to appear...")
            continue

        status = latest.get("status", "unknown")
        print(f"  [{i}/{max_attempts}] status={status}")

        if status == "done":
            print("\nDokploy reports deploy done.")
            break
        if status == "error":
            print(f"\nerror: Deploy failed", file=sys.stderr)
            err_msg = latest.get("errorMessage", "")
            if err_msg:
                print(err_msg, file=sys.stderr)
            # Fetch logs for problem containers
            app_resp = api_call(client, "GET", "compose.one", {"composeId": args.compose_id})
            if not app_resp.is_error:
                app_name = app_resp.json().get("appName", "")
                containers = get_containers(client, app_name)
                if containers:
                    show_problem_logs(url, token, containers, app_name)
            sys.exit(1)
    else:
        print(f"\nerror: Deploy timed out after {args.timeout}s", file=sys.stderr)
        sys.exit(1)

    # Step 4: verify container health
    print("Verifying container health...")
    app_resp = api_call(client, "GET", "compose.one", {"composeId": args.compose_id})
    if app_resp.is_error:
        print("warning: could not fetch app info for health check", file=sys.stderr)
        return

    app_name = app_resp.json().get("appName", "")
    if not app_name:
        print("warning: no appName found, skipping health check", file=sys.stderr)
        return

    healthy = verify_container_health(client, app_name, timeout=120)
    if healthy:
        print("\nDeploy succeeded. All containers healthy.")
    else:
        print("\nwarning: Deploy done but not all containers healthy.", file=sys.stderr)
        containers = get_containers(client, app_name)
        show_problem_logs(url, token, containers, app_name)
        sys.exit(1)


def cmd_logs(client: httpx.Client, args: argparse.Namespace) -> None:
    """Show container runtime logs via WebSocket."""
    url, token = load_config()

    # Get app name to find containers
    resp = api_call(client, "GET", "compose.one", {"composeId": args.compose_id})
    if resp.is_error:
        print_response(resp)
        return

    data = resp.json()
    app_name = data.get("appName", "")

    containers = get_containers(client, app_name)
    if not containers:
        print("No running containers found.")
        return

    # Filter to a specific service if requested
    if args.service:
        containers = [c for c in containers if args.service in c.get("name", "")]
        if not containers:
            print(f"No container found matching service '{args.service}'")
            available = get_containers(client, app_name)
            if available:
                print("Available services:")
                for c in available:
                    name = c.get("name", "?").replace(f"{app_name}-", "").rstrip("-1234567890")
                    print(f"  {name}")
            return

    for c in containers:
        cid = c.get("containerId", "")
        cname = c.get("name", "?")
        short = cname.replace(f"{app_name}-", "").rstrip("-1234567890")

        if not cid:
            continue

        lines = fetch_container_logs(url, token, cid, tail=args.tail, since=args.since)
        if len(containers) > 1:
            print(f"--- {short} ---")
        for line in lines:
            print(line.rstrip())
        if len(containers) > 1:
            print()


def cmd_init(client: httpx.Client, args: argparse.Namespace) -> None:
    """Create a new compose app with sourceType=raw (two-step workaround for I0071)."""
    # Step 1: create
    resp = api_call(client, "POST", "compose.create", {
        "name": args.app_name,
        "projectId": args.project_id,
    })
    if resp.is_error:
        print_response(resp)
        return

    result = resp.json()
    compose_id = result.get("composeId")
    if not compose_id:
        print("error: compose.create returned no composeId", file=sys.stderr)
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(f"Created compose app: {compose_id}")

    # Step 2: fix sourceType (I0071 workaround)
    fix_resp = api_call(client, "POST", "compose.update", {
        "composeId": compose_id,
        "sourceType": "raw",
    })
    if fix_resp.is_error:
        print(f"warning: failed to fix sourceType (HTTP {fix_resp.status_code})", file=sys.stderr)
    else:
        print(f"Fixed sourceType to 'raw'")

    print(f"\nCompose ID: {compose_id}")
    print(f"Use this in CI: dokctl deploy {compose_id} docker-compose.prod.yml")


# ── Main ──


def main() -> None:
    parser = argparse.ArgumentParser(prog="dokctl", description="Thin CLI over Dokploy API")
    sub = parser.add_subparsers(dest="command", required=True)

    # api
    p_api = sub.add_parser("api", help="Raw API call (like gh api)")
    p_api.add_argument("endpoint", help="API endpoint, e.g. compose.one")
    p_api.add_argument("--data", "-d", help="JSON body (POST if provided, GET otherwise)")

    # status
    p_status = sub.add_parser("status", help="Show compose app status")
    p_status.add_argument("compose_id", help="Dokploy compose ID")
    p_status.add_argument("--live", "-l", action="store_true", help="Show live container health")

    # sync
    p_sync = sub.add_parser("sync", help="Sync compose file + env to Dokploy")
    p_sync.add_argument("compose_id", help="Dokploy compose ID")
    p_sync.add_argument("compose_file", help="Path to docker-compose.prod.yml")
    p_sync.add_argument("--env-file", "-e", help="Path to .env file (if omitted, auto-resolves from compose ${VAR} refs)")

    # deploy
    p_deploy = sub.add_parser("deploy", help="Sync + deploy + poll + verify health")
    p_deploy.add_argument("compose_id", help="Dokploy compose ID")
    p_deploy.add_argument("compose_file", help="Path to docker-compose.prod.yml")
    p_deploy.add_argument("--env-file", "-e", help="Path to .env file (if omitted, auto-resolves from compose ${VAR} refs)")
    p_deploy.add_argument("--timeout", "-t", type=int, default=300, help="Timeout in seconds (default: 300)")

    # logs
    p_logs = sub.add_parser("logs", help="Show container runtime logs")
    p_logs.add_argument("compose_id", help="Dokploy compose ID")
    p_logs.add_argument("--service", "-s", help="Filter to a specific service name")
    p_logs.add_argument("--tail", "-n", type=int, default=100, help="Number of lines (default: 100)")
    p_logs.add_argument("--since", default="all", help="Time filter: 30s, 5m, 1h, all (default: all)")

    # init
    p_init = sub.add_parser("init", help="Create new compose app (with sourceType fix)")
    p_init.add_argument("project_id", help="Dokploy project ID")
    p_init.add_argument("app_name", help="Name for the compose app")

    args = parser.parse_args()
    url, token = load_config()
    client = make_client(url, token)

    cmd = {
        "api": cmd_api,
        "status": cmd_status,
        "sync": cmd_sync,
        "deploy": cmd_deploy,
        "logs": cmd_logs,
        "init": cmd_init,
    }[args.command]

    cmd(client, args)


if __name__ == "__main__":
    main()
