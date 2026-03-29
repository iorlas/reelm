from unittest.mock import MagicMock

import pytest

from mcps.servers.storage import (
    FileEntry,
    _propfind,
    _walk,
    delete,
    get_dir_size,
    list_dir,
    move,
)


def _xml_multistatus(*responses: str) -> str:
    """Build a DAV:multistatus XML string from response fragments."""
    body = "\n".join(responses)
    return f'<?xml version="1.0" encoding="utf-8"?>\n<D:multistatus xmlns:D="DAV:">\n{body}\n</D:multistatus>'


def _xml_collection(href: str) -> str:
    """Build a DAV:response for a directory (collection)."""
    return (
        "<D:response>"
        f"<D:href>{href}</D:href>"
        "<D:propstat><D:prop>"
        "<D:resourcetype><D:collection/></D:resourcetype>"
        "</D:prop></D:propstat>"
        "</D:response>"
    )


def _xml_file(href: str, size: int) -> str:
    """Build a DAV:response for a file with a given size."""
    return (
        "<D:response>"
        f"<D:href>{href}</D:href>"
        "<D:propstat><D:prop>"
        f"<D:getcontentlength>{size}</D:getcontentlength>"
        "</D:prop></D:propstat>"
        "</D:response>"
    )


@pytest.fixture()
def mock_client(mocker):
    """Mock _client to return a controllable httpx.Client-like context manager."""
    client = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client)
    ctx.__exit__ = MagicMock(return_value=False)
    mocker.patch("mcps.servers.storage._client", return_value=ctx)
    mocker.patch("mcps.servers.storage.settings", webdav_url="http://localhost/webdav", webdav_user="u", webdav_pass="p")
    return client


def _set_propfind_response(client: MagicMock, xml: str):
    """Configure the mock client.request to return a response with given XML."""
    resp = MagicMock()
    resp.text = xml
    resp.raise_for_status = MagicMock()
    client.request.return_value = resp
    return resp


# ---------- _propfind ----------


@pytest.mark.unit
def test_propfind_parses_files_and_dirs(mock_client):
    xml = _xml_multistatus(
        _xml_collection("/webdav/media/"),  # parent — should be skipped
        _xml_collection("/webdav/media/movies/"),
        _xml_file("/webdav/media/readme.txt", 256),
    )
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/media/")

    assert len(entries) == 2
    dirs = [e for e in entries if e.is_dir]
    files = [e for e in entries if not e.is_dir]
    assert len(dirs) == 1
    assert dirs[0].name == "movies"
    assert dirs[0].path == "/media/movies/"
    assert dirs[0].size == 0
    assert len(files) == 1
    assert files[0].name == "readme.txt"
    assert files[0].size == 256


@pytest.mark.unit
def test_propfind_skips_dotfiles(mock_client):
    xml = _xml_multistatus(
        _xml_collection("/webdav/media/"),  # parent
        _xml_file("/webdav/media/.hidden", 100),
        _xml_file("/webdav/media/visible.txt", 200),
    )
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/media/")

    assert len(entries) == 1
    assert entries[0].name == "visible.txt"


@pytest.mark.unit
def test_propfind_skips_parent_directory(mock_client):
    xml = _xml_multistatus(
        _xml_collection("/webdav/media/"),  # parent itself
    )
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/media/")

    assert entries == []


@pytest.mark.unit
def test_propfind_empty_response(mock_client):
    xml = _xml_multistatus()  # no responses at all
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/media/")

    assert entries == []


@pytest.mark.unit
def test_propfind_root_path(mock_client):
    xml = _xml_multistatus(
        _xml_collection("/webdav/"),  # parent (root itself)
        _xml_collection("/webdav/media/"),
    )
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/")

    assert len(entries) == 1
    assert entries[0].name == "media"
    assert entries[0].path == "/media/"
    # Verify PROPFIND was called with "/" (root)
    mock_client.request.assert_called_once_with("PROPFIND", "/", headers={"Depth": "1"})


@pytest.mark.unit
def test_propfind_nested_path(mock_client):
    xml = _xml_multistatus(
        _xml_collection("/webdav/media/movies/"),  # parent
        _xml_file("/webdav/media/movies/avatar.mkv", 1073741824),
    )
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/media/movies/")

    assert len(entries) == 1
    assert entries[0].name == "avatar.mkv"
    assert entries[0].path == "/media/movies/avatar.mkv"
    assert entries[0].size == 1073741824
    assert entries[0].size_mb == round(1073741824 / (1024 * 1024), 1)


@pytest.mark.unit
def test_propfind_dir_size_is_zero(mock_client):
    """Directories should always report size=0, even if WebDAV returns a content length."""
    xml = _xml_multistatus(
        _xml_collection("/webdav/media/"),  # parent
        # A collection response that happens to have a getcontentlength
        "<D:response>"
        "<D:href>/webdav/media/subdir/</D:href>"
        "<D:propstat><D:prop>"
        "<D:resourcetype><D:collection/></D:resourcetype>"
        "<D:getcontentlength>4096</D:getcontentlength>"
        "</D:prop></D:propstat>"
        "</D:response>",
    )
    _set_propfind_response(mock_client, xml)

    entries = _propfind("/media/")

    assert len(entries) == 1
    assert entries[0].is_dir is True
    assert entries[0].size == 0
    assert entries[0].size_mb == 0.0


# ---------- list_dir ----------


@pytest.mark.unit
def test_list_dir_returns_tsv_list(mock_client):
    xml = _xml_multistatus(
        _xml_collection("/webdav/media/"),  # parent
        _xml_file("/webdav/media/a.txt", 100),
        _xml_file("/webdav/media/b.txt", 200),
    )
    _set_propfind_response(mock_client, xml)

    result = list_dir("/media/")

    assert result.total == 2
    assert result.offset == 0
    assert result.has_more is False
    assert "a.txt" in result.data
    assert "b.txt" in result.data


# ---------- _walk ----------


@pytest.mark.unit
def test_walk_recursively_visits_subdirectories(mocker):
    """_walk should recurse into subdirectories discovered via _propfind."""
    mocker.patch("mcps.servers.storage.settings", webdav_url="http://localhost/webdav", webdav_user="u", webdav_pass="p")

    call_count = 0

    def fake_propfind(path, depth=1):
        nonlocal call_count
        call_count += 1
        if path == "/media/":
            return [
                FileEntry(name="movies", path="/media/movies/", is_dir=True, size=0, size_mb=0.0),
                FileEntry(name="file1.txt", path="/media/file1.txt", is_dir=False, size=100, size_mb=0.0),
            ]
        if path == "/media/movies/":
            return [
                FileEntry(name="avatar.mkv", path="/media/movies/avatar.mkv", is_dir=False, size=5000, size_mb=4.8),
            ]
        return []

    mocker.patch("mcps.servers.storage._propfind", side_effect=fake_propfind)

    entries = _walk("/media/")

    assert call_count == 2
    names = {e.name for e in entries}
    assert names == {"movies", "file1.txt", "avatar.mkv"}


@pytest.mark.unit
def test_walk_respects_max_depth(mocker):
    """_walk with max_depth=1 should not recurse deeper than one level of subdirectories."""
    mocker.patch("mcps.servers.storage.settings", webdav_url="http://localhost/webdav", webdav_user="u", webdav_pass="p")

    paths_visited = []

    def fake_propfind(path, depth=1):
        paths_visited.append(path)
        if path == "/":
            return [
                FileEntry(name="media", path="/media/", is_dir=True, size=0, size_mb=0.0),
            ]
        if path == "/media/":
            return [
                FileEntry(name="movies", path="/media/movies/", is_dir=True, size=0, size_mb=0.0),
                FileEntry(name="file.txt", path="/media/file.txt", is_dir=False, size=50, size_mb=0.0),
            ]
        if path == "/media/movies/":
            # Should NOT be reached with max_depth=1
            return [
                FileEntry(name="deep.mkv", path="/media/movies/deep.mkv", is_dir=False, size=9999, size_mb=9.5),
            ]
        return []

    mocker.patch("mcps.servers.storage._propfind", side_effect=fake_propfind)

    entries = _walk("/", max_depth=1)

    # depth=0 visits "/", depth=1 visits "/media/", depth=2 ("/media/movies/") should be skipped
    assert "/media/movies/" not in paths_visited
    names = {e.name for e in entries}
    assert "deep.mkv" not in names
    assert "movies" in names
    assert "file.txt" in names


# ---------- get_dir_size ----------


@pytest.mark.unit
def test_get_dir_size_sums_file_sizes(mocker):
    mocker.patch("mcps.servers.storage.settings", webdav_url="http://localhost/webdav", webdav_user="u", webdav_pass="p")
    mocker.patch(
        "mcps.servers.storage._walk",
        return_value=[
            FileEntry(name="a.mkv", path="/media/a.mkv", is_dir=False, size=1000, size_mb=0.0),
            FileEntry(name="b.mkv", path="/media/b.mkv", is_dir=False, size=2000, size_mb=0.0),
            FileEntry(name="subdir", path="/media/subdir/", is_dir=True, size=0, size_mb=0.0),
        ],
    )

    result = get_dir_size("/media/")

    assert result["total_bytes"] == 3000
    assert result["file_count"] == 2
    assert result["dir_count"] == 1
    assert result["path"] == "/media/"
    assert result["total_gb"] == round(3000 / (1024**3), 2)


# ---------- delete ----------


@pytest.mark.unit
def test_delete_sends_delete_request(mock_client):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    mock_client.request.return_value = resp

    result = delete("/media/old_movie.mkv")

    assert result is True
    mock_client.request.assert_called_once_with("DELETE", "/media/old_movie.mkv")
    resp.raise_for_status.assert_called_once()


# ---------- move ----------


@pytest.mark.unit
def test_move_sends_move_request_with_destination(mock_client):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    mock_client.request.return_value = resp

    result = move("/media/old.mkv", "/media/new.mkv")

    assert result is True
    mock_client.request.assert_called_once_with(
        "MOVE",
        "/media/old.mkv",
        headers={"Destination": "http://localhost/webdav/media/new.mkv"},
        follow_redirects=True,
    )
    resp.raise_for_status.assert_called_once()
