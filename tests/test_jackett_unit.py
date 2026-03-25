from unittest.mock import MagicMock, patch

import httpx
import pytest

from mcps.servers.jackett import (
    TorrentDetail,
    TorrentSummary,
    _cache,
    _ensure_magnet,
    _extract_torznab_attrs,
    _make_id,
    _parse_torznab_response,
    get_torrent,
    search_torrents,
)

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>Jackett</title>
    <item>
      <title>Ubuntu 24.04 LTS</title>
      <guid>https://example.com/torrent/123</guid>
      <link>https://example.com/download/123.torrent</link>
      <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
      <jackettindexer id="example">ExampleTracker</jackettindexer>
      <torznab:attr name="seeders" value="100"/>
      <torznab:attr name="peers" value="50"/>
      <torznab:attr name="size" value="4294967296"/>
      <torznab:attr name="infohash" value="abc123def456"/>
      <torznab:attr name="magneturl" value="magnet:?xt=urn:btih:abc123def456"/>
      <torznab:attr name="category" value="2000"/>
      <torznab:attr name="category" value="2010"/>
    </item>
  </channel>
</rss>"""

SINGLE_ITEM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Single Result</title>
      <guid>single-guid</guid>
      <link>https://example.com/single.torrent</link>
      <torznab:attr name="seeders" value="5"/>
    </item>
  </channel>
</rss>"""

EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>Jackett</title>
  </channel>
</rss>"""

ENCLOSURE_SIZE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Enclosure Size Test</title>
      <guid>enc-guid</guid>
      <link>https://example.com/enc.torrent</link>
      <enclosure url="https://example.com/enc.torrent" length="1073741824" type="application/x-bittorrent"/>
      <torznab:attr name="seeders" value="10"/>
    </item>
  </channel>
</rss>"""


@pytest.mark.unit
class TestModels:
    def test_torrent_summary_model(self):
        data = {
            "id": "a1b2c3d4",
            "title": "Test Torrent",
            "size": 1073741824,
            "seeders": 50,
            "leechers": 10,
            "indexer": "ExampleTracker",
        }
        result = TorrentSummary.model_validate(data)
        assert result.id == "a1b2c3d4"
        assert result.title == "Test Torrent"
        assert result.size == 1073741824
        assert result.seeders == 50
        assert result.leechers == 10
        assert result.indexer == "ExampleTracker"

    def test_torrent_summary_defaults(self):
        data = {"id": "abc", "title": "Minimal", "size": 0}
        result = TorrentSummary.model_validate(data)
        assert result.seeders == 0
        assert result.leechers == 0
        assert result.indexer == ""

    def test_torrent_detail_model(self):
        data = {
            "id": "a1b2c3d4",
            "title": "Test Torrent",
            "link": "https://example.com/download.torrent",
            "size": 1073741824,
            "seeders": 50,
            "leechers": 10,
            "infohash": "abc123",
            "magneturl": "magnet:?xt=urn:btih:abc123",
            "category": [2000, 2010],
            "indexer": "ExampleTracker",
            "page_url": "https://example.com/torrent/123",
            "publish_date": "2024-01-01T00:00:00Z",
        }
        result = TorrentDetail.model_validate(data)
        assert result.id == "a1b2c3d4"
        assert result.title == "Test Torrent"
        assert result.size == 1073741824
        assert result.link == "https://example.com/download.torrent"
        assert result.infohash == "abc123"
        assert result.category == [2000, 2010]
        assert result.page_url == "https://example.com/torrent/123"

    def test_torrent_detail_defaults(self):
        data = {"id": "abc", "title": "Minimal", "link": "https://example.com", "size": 0}
        result = TorrentDetail.model_validate(data)
        assert result.seeders == 0
        assert result.magneturl is None
        assert result.infohash is None
        assert result.category == []
        assert result.page_url == ""
        assert result.publish_date is None


@pytest.mark.unit
class TestMakeId:
    def test_returns_prefixed_hash(self):
        result = _make_id("https://example.com/torrent/123")
        assert result.startswith("jkt_")
        assert len(result) == 12  # "jkt_" + 8 hex chars

    def test_deterministic(self):
        guid = "https://example.com/torrent/456"
        assert _make_id(guid) == _make_id(guid)

    def test_different_guids_different_ids(self):
        id1 = _make_id("https://example.com/torrent/1")
        id2 = _make_id("https://example.com/torrent/2")
        assert id1 != id2


@pytest.mark.unit
class TestExtractTorznabAttrs:
    def test_extracts_single_attr_as_dict(self):
        attrs = {"@name": "seeders", "@value": "100"}
        result = _extract_torznab_attrs(attrs)
        assert result["seeders"] == 100

    def test_extracts_multiple_attrs(self):
        attrs = [
            {"@name": "seeders", "@value": "100"},
            {"@name": "peers", "@value": "50"},
            {"@name": "size", "@value": "1024"},
        ]
        result = _extract_torznab_attrs(attrs)
        assert result["seeders"] == 100
        assert result["leechers"] == 50
        assert result["size"] == 1024

    def test_handles_multiple_categories(self):
        attrs = [
            {"@name": "category", "@value": "2000"},
            {"@name": "category", "@value": "2010"},
        ]
        result = _extract_torznab_attrs(attrs)
        assert result["category"] == [2000, 2010]

    def test_handles_none_attrs(self):
        result = _extract_torznab_attrs(None)
        assert result == {}

    def test_handles_empty_values(self):
        attrs = [{"@name": "seeders", "@value": ""}]
        result = _extract_torznab_attrs(attrs)
        assert result["seeders"] == 0


@pytest.mark.unit
class TestParseTorznabResponse:
    def test_parses_full_response(self):
        _cache.clear()
        summaries = _parse_torznab_response(SAMPLE_XML)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.title == "Ubuntu 24.04 LTS"
        assert s.id.startswith("jkt_")
        assert len(s.id) == 12
        assert s.seeders == 100
        assert s.leechers == 50
        assert s.size == 4294967296
        assert s.indexer == "ExampleTracker"
        # Check cache has full details
        detail = _cache[s.id]
        assert detail.link == "https://example.com/download/123.torrent"
        assert detail.infohash == "abc123def456"
        assert detail.magneturl is not None
        assert "magnet:" in detail.magneturl
        assert detail.category == [2000, 2010]
        assert detail.page_url == "https://example.com/torrent/123"

    def test_handles_single_item(self):
        _cache.clear()
        summaries = _parse_torznab_response(SINGLE_ITEM_XML)
        assert len(summaries) == 1
        assert summaries[0].title == "Single Result"
        assert summaries[0].seeders == 5
        assert summaries[0].id in _cache

    def test_handles_empty_response(self):
        _cache.clear()
        summaries = _parse_torznab_response(EMPTY_XML)
        assert summaries == []

    def test_uses_enclosure_size_as_fallback(self):
        _cache.clear()
        summaries = _parse_torznab_response(ENCLOSURE_SIZE_XML)
        assert len(summaries) == 1
        assert summaries[0].size == 1073741824


@pytest.mark.unit
class TestGetTorrent:
    def test_returns_cached_detail(self):
        _cache.clear()
        _parse_torznab_response(SAMPLE_XML)
        # Get the ID from cache
        torrent_id = list(_cache.keys())[0]
        detail = get_torrent(torrent_id)
        assert detail.title == "Ubuntu 24.04 LTS"
        assert detail.link == "https://example.com/download/123.torrent"

    def test_raises_for_unknown_id(self):
        _cache.clear()
        with pytest.raises(ValueError, match="Invalid torrent ID format"):
            get_torrent("nonexistent")

    def test_raises_for_missing_cached_id_mentions_search_torrents(self):
        _cache.clear()
        with pytest.raises(ValueError, match="search_torrents"):
            get_torrent("jkt_00000000")


SECOND_ITEM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Interstellar RUS</title>
      <guid>https://example.com/torrent/rus</guid>
      <link>https://example.com/download/rus.torrent</link>
      <torznab:attr name="seeders" value="20"/>
      <torznab:attr name="size" value="5000000000"/>
    </item>
  </channel>
</rss>"""


@pytest.mark.unit
class TestAltQueriesDedup:
    def test_dedup_by_id(self, monkeypatch):
        _cache.clear()
        call_count = 0

        def fake_search(params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _parse_torznab_response(SAMPLE_XML)
            return _parse_torznab_response(SAMPLE_XML)  # same results

        monkeypatch.setattr("mcps.servers.jackett._search", fake_search)
        result = search_torrents(query="Ubuntu", alt_queries=["Убунту"])
        assert call_count == 2
        # Deduplicated: same GUID -> same ID -> kept once
        lines = result.data.strip().split("\n")
        assert len(lines) == 2  # header + 1 row

    def test_alt_queries_merges_different_results(self, monkeypatch):
        _cache.clear()
        call_count = 0

        def fake_search(params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _parse_torznab_response(SAMPLE_XML)
            return _parse_torznab_response(SECOND_ITEM_XML)

        monkeypatch.setattr("mcps.servers.jackett._search", fake_search)
        result = search_torrents(query="Interstellar", alt_queries=["Интерстеллар"])
        lines = result.data.strip().split("\n")
        assert len(lines) == 3  # header + 2 distinct rows

    def test_returns_tsv_format(self, monkeypatch):
        _cache.clear()
        monkeypatch.setattr("mcps.servers.jackett._search", lambda p: _parse_torznab_response(SAMPLE_XML))
        result = search_torrents(query="Ubuntu")
        assert "\t" in result.data
        header = result.data.split("\n")[0]
        assert "title" in header
        assert "seeders" in header


def _make_detail(magneturl=None, link="https://example.com/dl/123.torrent"):
    return TorrentDetail(
        id="jkt_test1234",
        title="Test",
        link=link,
        size=1024,
        magneturl=magneturl,
    )


@pytest.mark.unit
class TestEnsureMagnet:
    def test_already_has_magnet_returns_unchanged(self):
        detail = _make_detail(magneturl="magnet:?xt=urn:btih:abc123")
        result = _ensure_magnet(detail)
        assert result.magneturl == "magnet:?xt=urn:btih:abc123"

    def test_redirect_to_magnet_url(self):
        detail = _make_detail()
        magnet_url = "magnet:?xt=urn:btih:redirected"

        mock_resp = MagicMock()
        mock_resp.url = httpx.URL(magnet_url)
        mock_resp.status_code = 200
        mock_resp.content = b""

        with patch("mcps.servers.jackett.httpx.get", return_value=mock_resp):
            result = _ensure_magnet(detail)

        assert result.magneturl == magnet_url

    def test_torrent_bytes_response_converts_to_magnet(self):
        import bencodepy

        detail = _make_detail()
        info = {b"name": b"test", b"piece length": 262144, b"length": 1024, b"pieces": b"\x00" * 20}
        torrent_bytes = bencodepy.encode({b"info": info})

        mock_resp = MagicMock()
        mock_resp.url = httpx.URL("https://example.com/dl/123.torrent")
        mock_resp.status_code = 200
        mock_resp.content = torrent_bytes

        with patch("mcps.servers.jackett.httpx.get", return_value=mock_resp):
            result = _ensure_magnet(detail)

        assert result.magneturl is not None
        assert result.magneturl.startswith("magnet:?xt=urn:btih:")

    def test_network_failure_returns_unchanged(self):
        detail = _make_detail()

        with patch("mcps.servers.jackett.httpx.get", side_effect=httpx.ConnectError("fail")):
            result = _ensure_magnet(detail)

        assert result.magneturl is None

    def test_empty_link_returns_unchanged(self):
        detail = TorrentDetail(
            id="jkt_test1234",
            title="Test",
            link="",
            size=1000,
        )
        from mcps.servers.jackett import _ensure_magnet

        result = _ensure_magnet(detail)
        assert result.magneturl is None
