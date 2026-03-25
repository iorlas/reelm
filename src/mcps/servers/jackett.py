import hashlib
from typing import Annotated, Literal

import httpx
import xmltodict
from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from mcps.config import settings
from mcps.shared.pagination import DEFAULT_LIMIT, TsvList, paginate
from mcps.shared.query import apply_query, project, to_tsv
from mcps.shared.schema import optimize_tool_schemas
from mcps.shared.torrent import torrent_bytes_to_magnet

mcp = FastMCP("Jackett")

_client: httpx.Client | None = None
_cache: dict[str, "TorrentDetail"] = {}


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            base_url=settings.jackett_url,
            timeout=30.0,
        )
    return _client


ID_PREFIX = "jkt_"


def _make_id(guid: str) -> str:
    return ID_PREFIX + hashlib.md5(guid.encode(), usedforsecurity=False).hexdigest()[:8]


class TorrentSummary(BaseModel):
    id: str = Field(description="Internal reference ID")
    title: str
    size: int = Field(description="Size in bytes")
    seeders: int = 0
    leechers: int = 0
    indexer: str = ""


class TorrentDetail(BaseModel):
    id: str = Field(description="Internal reference ID")
    title: str
    size: int = Field(description="Size in bytes")
    seeders: int = 0
    leechers: int = 0
    indexer: str = ""
    link: str = Field(description="Download URL")
    magneturl: str | None = Field(default=None, description="Magnet link if available from indexer")
    infohash: str | None = None
    page_url: str = Field(default="", description="Torrent page URL")
    category: list[int] = []
    publish_date: str | None = None


# Keep for backwards compat during transition
TorrentResult = TorrentDetail


_INT_ATTRS = {"seeders", "size"}
_INT_REMAP = {"peers": "leechers"}
_STR_ATTRS = {"infohash", "magneturl", "tvdbid", "imdbid"}


def _extract_torznab_attrs(attrs: list | dict | None) -> dict:
    """Extract torznab:attr elements into a dict."""
    if attrs is None:
        return {}
    if isinstance(attrs, dict):
        attrs = [attrs]
    result: dict = {}
    for attr in attrs:
        name = attr.get("@name", "")
        value = attr.get("@value", "")
        if name in _INT_ATTRS:
            result[name] = int(value) if value else 0
        elif name in _INT_REMAP:
            result[_INT_REMAP[name]] = int(value) if value else 0
        elif name in _STR_ATTRS:
            result[name] = value
        elif name == "category":
            result.setdefault("category", []).append(int(value) if value else 0)
    return result


def _parse_torznab_response(xml_content: str) -> list[TorrentSummary]:
    """Parse Torznab XML response, cache details, return summaries."""
    data = xmltodict.parse(xml_content)
    channel = data.get("rss", {}).get("channel", {})
    items = channel.get("item", [])

    if isinstance(items, dict):
        items = [items]
    if items is None:
        items = []

    summaries = []
    for item in items:
        attrs = _extract_torznab_attrs(item.get("torznab:attr"))

        # Size can come from torznab:attr or enclosure
        size = attrs.get("size", 0)
        if not size:
            enclosure = item.get("enclosure", {})
            if isinstance(enclosure, dict):
                size = int(enclosure.get("@length", 0) or 0)

        # Get indexer from jackettindexer element or attr
        indexer = ""
        if "jackettindexer" in item:
            indexer_data = item["jackettindexer"]
            if isinstance(indexer_data, dict):
                indexer = indexer_data.get("#text", "")
            else:
                indexer = str(indexer_data) if indexer_data else ""

        guid = item.get("guid", "")
        if isinstance(guid, dict):
            guid = guid.get("#text", "")

        short_id = _make_id(guid)

        detail = TorrentDetail(
            id=short_id,
            title=item.get("title", ""),
            link=item.get("link", ""),
            size=size,
            seeders=attrs.get("seeders", 0),
            leechers=attrs.get("leechers", 0),
            infohash=attrs.get("infohash"),
            magneturl=attrs.get("magneturl"),
            category=attrs.get("category", []),
            indexer=indexer,
            page_url=guid,
            publish_date=item.get("pubDate"),
        )
        _cache[short_id] = detail

        summaries.append(
            TorrentSummary(
                id=short_id,
                title=detail.title,
                size=detail.size,
                seeders=detail.seeders,
                leechers=detail.leechers,
                indexer=detail.indexer,
            )
        )

    return summaries


def _search(params: dict) -> list[TorrentSummary]:
    """Execute search against Jackett API."""
    params["apikey"] = settings.jackett_api_key
    resp = _get_client().get("/api/v2.0/indexers/all/results/torznab/api", params=params)
    resp.raise_for_status()
    return _parse_torznab_response(resp.text)


@mcp.tool
def search_torrents(
    query: Annotated[str, Field()],
    alt_queries: Annotated[list[str] | None, Field(description="Alternative queries (OR, deduped)")] = None,
    search_type: Annotated[Literal["search", "movie", "tvsearch"], Field()] = "search",
    year: Annotated[int | None, Field()] = None,
    season: Annotated[int | None, Field()] = None,
    episode: Annotated[int | None, Field()] = None,
    categories: Annotated[list[int] | None, Field(description="Category IDs (2000=Movies, 5000=TV)")] = None,
    filter_expr: Annotated[str | None, Field(description="CEL filter. Examples: seeders > 10, size > 1000000000")] = None,
    search: Annotated[str | None, Field(description="Fuzzy text search across all fields (handles Cyrillic, transliteration)")] = None,
    fields: Annotated[list[str] | None, Field(description="Fields (id auto-incl.)")] = None,
    sort_by: Annotated[str | None, Field(description="Sort field, - prefix for desc")] = None,
    limit: Annotated[int, Field()] = DEFAULT_LIMIT,
    offset: Annotated[int, Field()] = 0,
) -> TsvList:
    """Search torrents (TSV). Fields: title, size, seeders, leechers, indexer"""
    base_params: dict[str, str] = {"t": search_type}
    if year:
        base_params["year"] = str(year)
    if season is not None and search_type == "tvsearch":
        base_params["season"] = str(season)
    if episode is not None and search_type == "tvsearch":
        base_params["ep"] = str(episode)
    if categories:
        base_params["cat"] = ",".join(str(c) for c in categories)

    all_queries = [query] + (alt_queries or [])
    seen_ids: set[str] = set()
    results: list[TorrentSummary] = []
    for q in all_queries:
        for item in _search({**base_params, "q": q}):
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                results.append(item)

    filtered = apply_query(results, filter_expr, search=search, sort_by=sort_by, limit=None)
    paginated, total, has_more = paginate(filtered, limit, offset)
    projected = project(paginated, fields)
    return TsvList(data=to_tsv(projected), total=total, offset=offset, has_more=has_more)


def _ensure_magnet(detail: TorrentDetail) -> TorrentDetail:
    """Best-effort resolve magnet link for a torrent detail.

    If magneturl is already set, return as-is. Otherwise, try to fetch the
    download link URL: if redirect leads to magnet: URL, use that; if response
    is 200 with content, convert torrent bytes to magnet via torrent_bytes_to_magnet.
    On any failure, return unchanged.
    """
    if detail.magneturl:
        return detail

    if not detail.link:
        return detail

    try:
        resp = httpx.get(detail.link, follow_redirects=True, timeout=30.0)
        if resp.url and str(resp.url).startswith("magnet:"):
            detail = detail.model_copy(update={"magneturl": str(resp.url)})
            _cache[detail.id] = detail
            return detail
        if resp.status_code == 200 and resp.content:
            magnet = torrent_bytes_to_magnet(resp.content)
            detail = detail.model_copy(update={"magneturl": magnet})
            _cache[detail.id] = detail
            return detail
    except (httpx.HTTPError, OSError, ValueError):
        logger.debug(f"jackett.ensure_magnet_failed id={detail.id} link={detail.link}")

    return detail


@mcp.tool
def get_torrent(
    torrent_id: Annotated[str, Field(description="Torrent ID (jkt_xxxxxxxx)")],
) -> TorrentDetail:
    """Get torrent details by ID. Resolves magnet link if not already available."""
    if not torrent_id.startswith(ID_PREFIX):
        raise ValueError(f"Invalid torrent ID format: {torrent_id}. Expected jkt_xxxxxxxx from search results.")
    if torrent_id not in _cache:
        raise ValueError(f"Unknown torrent ID: {torrent_id}. Search first with search_torrents, then use the ID from results.")
    return _ensure_magnet(_cache[torrent_id])


optimize_tool_schemas(mcp)
