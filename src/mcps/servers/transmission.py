from typing import Annotated, Any, Literal

import httpx
from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field
from transmission_rpc import Client

from mcps.config import settings
from mcps.shared.pagination import DEFAULT_LIMIT, TsvList, paginate
from mcps.shared.query import apply_query, project, to_tsv
from mcps.shared.schema import optimize_tool_schemas

mcp = FastMCP("Transmission")

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        protocol = "https" if settings.transmission_ssl else "http"
        _client = Client(
            protocol=protocol,
            host=settings.transmission_host,
            port=settings.transmission_port,
            path=settings.transmission_path,
            username=settings.transmission_user,
            password=settings.transmission_pass,
        )
    return _client


class TorrentFile(BaseModel):
    index: int
    name: str
    size: int
    completed: int
    priority: int


class FolderEntry(BaseModel):
    name: str
    file_count: int
    total_size: int
    completed_size: int
    is_folder: bool = True


TorrentStatus = Literal[
    "stopped",
    "check pending",
    "checking",
    "download pending",
    "downloading",
    "seed pending",
    "seeding",
]


class Torrent(BaseModel):
    id: int
    name: str
    status: Annotated[
        TorrentStatus,
        Field(description="stopped=completed/paused, downloading=in progress, seeding=uploading"),
    ]
    progress: Annotated[float, Field(description="0-100. 100=fully downloaded")]
    eta: int | None
    total_size: int
    comment: str
    error_string: str
    download_speed: int
    upload_speed: int
    file_count: int


class TorrentList(BaseModel):
    torrents: list[Torrent] | list[dict[str, Any]]
    total: int
    offset: int
    has_more: bool


class TorrentFileList(BaseModel):
    torrent_id: int
    files: list[TorrentFile | FolderEntry] | list[dict[str, Any]]
    total: int
    offset: int
    has_more: bool
    current_depth: int | None = None
    hint: str | None = None


def _resolve_url(url: str) -> str | bytes:
    """Resolve URL to magnet link or download .torrent file content.

    Jackett proxy URLs behave differently per indexer:
    - Some return 302 redirect to magnet: link -> extract magnet
    - Some return .torrent file directly -> download and return bytes

    Returns magnet string or .torrent file bytes. Transmission accepts both
    via add_torrent(). We must download .torrent files ourselves because
    Transmission (on the router) can't reach internal Docker hostnames.
    """
    if url.startswith("magnet:"):
        return url
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30.0)
        if resp.url and str(resp.url).startswith("magnet:"):
            return str(resp.url)
        # Check if redirect led to a magnet via Location header
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if location.startswith("magnet:"):
                return location
        if resp.status_code == 404:
            raise RuntimeError("Torrent download link expired (Jackett cache cleared). Please search again and retry with a fresh result.")
        # Got a .torrent file — return raw bytes for Transmission
        if resp.status_code == 200 and resp.content:
            return resp.content
    except (httpx.HTTPError, OSError) as e:
        raise RuntimeError(f"Failed to download torrent from {url}: {e}") from e
    raise RuntimeError(
        f"Unexpected response from {url}: status={resp.status_code}, content_type={resp.headers.get('content-type', 'unknown')}"
    )


def _torrent_to_model(t: Any) -> Torrent:
    file_count = 0
    if hasattr(t, "get_files") and callable(t.get_files):
        try:
            file_count = len(t.get_files())
        except KeyError:
            logger.debug(f"transmission.files_not_fetched torrent_id={t.id}")
    return Torrent(
        id=t.id,
        name=t.name,
        status=t.status.value if hasattr(t.status, "value") else str(t.status),  # type: ignore[invalid-argument-type]
        progress=t.progress,
        eta=int(t.eta.total_seconds()) if t.eta is not None and t.eta.total_seconds() >= 0 else None,
        total_size=t.total_size,
        comment=t.comment or "",
        error_string=t.error_string or "",
        download_speed=t.rate_download,
        upload_speed=t.rate_upload,
        file_count=file_count,
    )


def _aggregate_by_depth(files: list[TorrentFile], depth: int) -> list[BaseModel]:
    """Aggregate files into folders up to given depth."""
    if depth < 1:
        return list(files)

    folders: dict[str, FolderEntry] = {}
    result: list[BaseModel] = []

    for f in files:
        parts = f.name.split("/")
        if len(parts) <= depth:
            result.append(f)
        else:
            folder_path = "/".join(parts[:depth])
            if folder_path not in folders:
                folders[folder_path] = FolderEntry(
                    name=folder_path,
                    file_count=0,
                    total_size=0,
                    completed_size=0,
                )
            folders[folder_path].file_count += 1
            folders[folder_path].total_size += f.size
            folders[folder_path].completed_size += f.completed

    return result + list(folders.values())


class DiskUsage(BaseModel):
    download_dir: str
    free_bytes: int
    free_gb: float


@mcp.tool
def get_free_space() -> DiskUsage:
    """Get free disk space in the download directory."""
    client = get_client()
    session = client.get_session()
    free = session.download_dir_free_space
    return DiskUsage(
        download_dir=session.download_dir,
        free_bytes=free,
        free_gb=round(free / (1024**3), 2),
    )


@mcp.tool
def list_torrents(
    filter_expr: Annotated[
        str | None,
        Field(description="CEL filter. Examples: progress == 100, status == 'downloading', id == 42"),
    ] = None,
    search: Annotated[str | None, Field(description="Fuzzy text search across all fields (handles Cyrillic, transliteration)")] = None,
    fields: Annotated[
        list[str] | None,
        Field(
            description="Columns (id auto-incl.). Recommended: name,total_size."
            " Drop columns implied by filter (e.g. progress if progress==100)"
        ),
    ] = None,
    sort_by: Annotated[str | None, Field(description="Sort field, - prefix for desc")] = None,
    limit: Annotated[int, Field()] = DEFAULT_LIMIT,
    offset: Annotated[int, Field()] = 0,
) -> TsvList:
    """List torrents (TSV). No filter = all.
    Fields: name, status, progress, eta, total_size, error_string, download_speed, file_count.
    CRITICAL: downloaded/completed = progress==`100` ONLY.
    NEVER use status for downloaded. status=='downloading' = ACTIVELY in-progress."""
    torrents = get_client().get_torrents()
    items = [_torrent_to_model(t) for t in torrents]
    filtered = apply_query(items, filter_expr, search=search, sort_by=sort_by, limit=None)
    paginated, total, has_more = paginate(filtered, limit, offset)
    result = project(paginated, fields)
    return TsvList(data=to_tsv(result), total=total, offset=offset, has_more=has_more)


@mcp.tool
def add_torrent(
    url: Annotated[
        str,
        Field(description="Magnet link (strongly preferred). Get magneturl from get_torrent. Fallback: download URL."),
    ],
    category: Annotated[
        str | None,
        Field(description="Download subdirectory: tv, movies, music, other. Default: root download dir."),
    ] = None,
) -> Torrent:
    """Add torrent by magnet link. ALWAYS use magneturl from get_torrent — it's more reliable than download URLs.
    If download URL fails with 'expired', search again for fresh results."""
    client = get_client()
    download_dir = None
    if category:
        valid = settings.download_categories
        if category not in valid:
            msg = f"Invalid category '{category}'. Valid: {', '.join(sorted(valid))}"
            raise ValueError(msg)
        session = client.get_session()
        download_dir = f"{session.download_dir.rstrip('/')}/{category}"
    resolved_url = _resolve_url(url)
    t = client.add_torrent(resolved_url, download_dir=download_dir)
    full_torrent = client.get_torrent(t.id)
    return _torrent_to_model(full_torrent)


@mcp.tool
def remove_torrent(
    torrent_id: Annotated[int, Field()],
    delete_data: Annotated[bool, Field(description="Delete downloaded data")] = False,
) -> bool:
    """Remove torrent, optionally delete data."""
    get_client().remove_torrent(torrent_id, delete_data=delete_data)
    return True


@mcp.tool
def pause_torrent(
    torrent_id: Annotated[int, Field()],
) -> bool:
    """Pause torrent."""
    get_client().stop_torrent(torrent_id)
    return True


@mcp.tool
def resume_torrent(
    torrent_id: Annotated[int, Field()],
) -> bool:
    """Resume torrent."""
    get_client().start_torrent(torrent_id)
    return True


@mcp.tool
def list_files(
    torrent_id: Annotated[int, Field()],
    depth: Annotated[int | None, Field(description="Depth. 1=top, 2=sub, None=all")] = 1,
    filter_expr: Annotated[str | None, Field(description="CEL filter. Examples: size > 1000000, name.contains('.mkv')")] = None,
    search: Annotated[str | None, Field(description="Fuzzy text search across all fields (handles Cyrillic, transliteration)")] = None,
    fields: Annotated[list[str] | None, Field(description="Fields (index auto-incl.)")] = None,
    sort_by: Annotated[str | None, Field(description="Sort field, - prefix for desc")] = None,
    limit: Annotated[int, Field()] = DEFAULT_LIMIT,
    offset: Annotated[int, Field()] = 0,
) -> TorrentFileList:
    """List torrent files/folders. Fields: name, size, completed, priority | file_count, total_size, is_folder"""
    rpc_torrent = get_client().get_torrent(torrent_id)
    files = []
    for i, f in enumerate(rpc_torrent.get_files()):
        prio = f.priority.value if hasattr(f.priority, "value") else (f.priority or 1)
        files.append(TorrentFile(index=i, name=f.name, size=f.size, completed=f.completed, priority=prio))

    entries = _aggregate_by_depth(files, depth) if depth else files
    filtered = apply_query(entries, filter_expr, search=search, sort_by=sort_by, limit=None)
    paginated, total, has_more = paginate(filtered, limit, offset)
    result = project(paginated, fields)

    hint = None
    if depth is not None and not fields:
        has_folders = any(isinstance(e, FolderEntry) for e in paginated)
        if has_folders:
            hint = f"Folders found. To see their contents, increase depth (e.g., depth={depth + 1}) or use depth=None for all files."

    return TorrentFileList(
        torrent_id=torrent_id,
        files=result,
        total=total,
        offset=offset,
        has_more=has_more,
        current_depth=depth,
        hint=hint,
    )


@mcp.tool
def set_file_priorities(
    torrent_id: Annotated[int, Field()],
    file_indices: Annotated[list[int], Field(description="File indices from list_files")],
    priority: Annotated[int, Field(description="0=skip, 1=low, 2=normal, 3=high")],
) -> bool:
    """Set file download priority."""
    client = get_client()
    if priority == 0:
        client.change_torrent(torrent_id, files_unwanted=file_indices)
    else:
        client.change_torrent(torrent_id, files_wanted=file_indices)
        if priority == 1:
            client.change_torrent(torrent_id, priority_low=file_indices)
        elif priority == 2:
            client.change_torrent(torrent_id, priority_normal=file_indices)
        elif priority == 3:
            client.change_torrent(torrent_id, priority_high=file_indices)
    return True


optimize_tool_schemas(mcp)
