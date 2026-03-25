"""Unit tests for MCP tool functions in mcps.servers.transmission.

Covers: get_free_space, list_torrents, add_torrent, remove_torrent,
pause_torrent, resume_torrent, list_files, set_file_priorities,
_torrent_to_model (KeyError branch), get_client.
"""

from datetime import timedelta
from enum import Enum
from unittest.mock import MagicMock

import pytest

import mcps.servers.transmission as tm
from mcps.servers.transmission import (
    DiskUsage,
    TorrentFileList,
    _torrent_to_model,
    add_torrent,
    get_client,
    get_free_space,
    list_files,
    list_torrents,
    pause_torrent,
    remove_torrent,
    resume_torrent,
    set_file_priorities,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeStatus(Enum):
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    STOPPED = "stopped"


class FakePriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3


def _make_file(name="test.txt", size=1024, completed=512, priority=None):
    f = MagicMock()
    f.name = name
    f.size = size
    f.completed = completed
    f.priority = priority if priority is not None else FakePriority.NORMAL
    return f


def _make_torrent(
    id=1,
    name="Test Torrent",
    status=FakeStatus.DOWNLOADING,
    progress=50.0,
    rate_download=1024,
    rate_upload=512,
    eta=timedelta(seconds=3600),
    total_size=1073741824,
    comment="",
    error_string="",
    files=None,
):
    t = MagicMock()
    t.id = id
    t.name = name
    t.status = status
    t.progress = progress
    t.rate_download = rate_download
    t.rate_upload = rate_upload
    t.eta = eta
    t.total_size = total_size
    t.comment = comment
    t.error_string = error_string
    if files is not None:
        t.get_files = MagicMock(return_value=files)
    else:
        t.get_files = MagicMock(return_value=[])
    return t


def _mock_client():
    client = MagicMock()
    session = MagicMock()
    session.download_dir = "/downloads"
    session.download_dir_free_space = 50 * (1024**3)  # 50 GB
    client.get_session.return_value = session
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetClient:
    def test_creates_client_with_ssl_settings(self, mocker):
        mocker.patch.object(tm.settings, "transmission_ssl", True)
        mocker.patch.object(tm.settings, "transmission_host", "router.local")
        mocker.patch.object(tm.settings, "transmission_port", 9091)
        mocker.patch.object(tm.settings, "transmission_path", "/transmission/rpc")
        mocker.patch.object(tm.settings, "transmission_user", "admin")
        mocker.patch.object(tm.settings, "transmission_pass", "secret")

        mock_cls = mocker.patch("mcps.servers.transmission.Client")
        result = get_client()

        mock_cls.assert_called_once_with(
            protocol="https",
            host="router.local",
            port=9091,
            path="/transmission/rpc",
            username="admin",
            password="secret",
        )
        assert result == mock_cls.return_value


@pytest.mark.unit
class TestGetFreeSpace:
    def test_returns_disk_usage(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = get_free_space()

        assert isinstance(result, DiskUsage)
        assert result.download_dir == "/downloads"
        assert result.free_bytes == 50 * (1024**3)
        assert result.free_gb == 50.0


@pytest.mark.unit
class TestListTorrents:
    def test_returns_tsv_list(self, mocker):
        t1 = _make_torrent(id=1, name="Torrent A", progress=100.0, status=FakeStatus.SEEDING)
        t2 = _make_torrent(id=2, name="Torrent B", progress=50.0, status=FakeStatus.DOWNLOADING)
        client = _mock_client()
        client.get_torrents.return_value = [t1, t2]
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = list_torrents()

        assert result.total == 2
        assert result.offset == 0
        assert result.has_more is False
        assert "Torrent A" in result.data
        assert "Torrent B" in result.data


@pytest.mark.unit
class TestAddTorrent:
    def test_add_magnet_url(self, mocker):
        magnet = "magnet:?xt=urn:btih:abc123"
        added = _make_torrent(id=10, name="Added Torrent")
        full = _make_torrent(id=10, name="Added Torrent", files=[_make_file()])

        client = _mock_client()
        client.add_torrent.return_value = added
        client.get_torrent.return_value = full
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)
        mock_resolve = mocker.patch("mcps.servers.transmission._resolve_url", return_value=magnet)

        result = add_torrent(url=magnet)

        mock_resolve.assert_called_once_with(magnet)
        client.add_torrent.assert_called_once_with(magnet, download_dir=None)
        client.get_torrent.assert_called_once_with(10)
        assert result.id == 10
        assert result.name == "Added Torrent"

    def test_add_torrent_url_with_category(self, mocker):
        url = "http://jackett/dl/123.torrent"
        torrent_bytes = b"torrent-file-content"
        added = _make_torrent(id=11, name="File Torrent")
        full = _make_torrent(id=11, name="File Torrent", files=[_make_file()])

        client = _mock_client()
        client.add_torrent.return_value = added
        client.get_torrent.return_value = full
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)
        mocker.patch("mcps.servers.transmission._resolve_url", return_value=torrent_bytes)

        result = add_torrent(url=url, category="tv")

        client.add_torrent.assert_called_once_with(torrent_bytes, download_dir="/downloads/tv")
        assert result.id == 11

    def test_invalid_category_raises(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)
        mocker.patch("mcps.servers.transmission._resolve_url", return_value="magnet:?xt=urn:btih:abc")

        with pytest.raises(ValueError, match="Invalid category 'badcat'"):
            add_torrent(url="magnet:?xt=urn:btih:abc", category="badcat")


@pytest.mark.unit
class TestRemoveTorrent:
    def test_remove_without_delete(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = remove_torrent(torrent_id=5, delete_data=False)

        client.remove_torrent.assert_called_once_with(5, delete_data=False)
        assert result is True

    def test_remove_with_delete(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = remove_torrent(torrent_id=5, delete_data=True)

        client.remove_torrent.assert_called_once_with(5, delete_data=True)
        assert result is True


@pytest.mark.unit
class TestPauseTorrent:
    def test_pause(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = pause_torrent(torrent_id=7)

        client.stop_torrent.assert_called_once_with(7)
        assert result is True


@pytest.mark.unit
class TestResumeTorrent:
    def test_resume(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = resume_torrent(torrent_id=7)

        client.start_torrent.assert_called_once_with(7)
        assert result is True


@pytest.mark.unit
class TestListFiles:
    def test_depth_one_with_folder_aggregation(self, mocker):
        files = [
            _make_file(name="Show/S01/E01.mkv", size=1000, completed=1000),
            _make_file(name="Show/S01/E02.mkv", size=2000, completed=500),
            _make_file(name="Extras/making.mkv", size=100, completed=100),
        ]
        torrent = _make_torrent(id=42, files=files)

        client = _mock_client()
        client.get_torrent.return_value = torrent
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = list_files(torrent_id=42, depth=1)

        assert isinstance(result, TorrentFileList)
        assert result.torrent_id == 42
        assert result.current_depth == 1
        # All files nested deeper than depth=1, so all become folders
        assert result.total == 2
        assert result.hint is not None
        assert "depth=2" in result.hint

    def test_depth_none_returns_all_files(self, mocker):
        files = [
            _make_file(name="Show/S01/E01.mkv", size=1000, completed=1000),
            _make_file(name="Show/S01/E02.mkv", size=2000, completed=500),
        ]
        torrent = _make_torrent(id=42, files=files)

        client = _mock_client()
        client.get_torrent.return_value = torrent
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = list_files(torrent_id=42, depth=None)

        assert result.torrent_id == 42
        assert result.total == 2
        assert result.current_depth is None
        assert result.hint is None


@pytest.mark.unit
class TestSetFilePriorities:
    def test_priority_zero_skips_files(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = set_file_priorities(torrent_id=3, file_indices=[0, 1], priority=0)

        client.change_torrent.assert_called_once_with(3, files_unwanted=[0, 1])
        assert result is True

    def test_priority_one_low(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = set_file_priorities(torrent_id=3, file_indices=[0], priority=1)

        assert client.change_torrent.call_count == 2
        client.change_torrent.assert_any_call(3, files_wanted=[0])
        client.change_torrent.assert_any_call(3, priority_low=[0])
        assert result is True

    def test_priority_two_normal(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = set_file_priorities(torrent_id=3, file_indices=[2, 3], priority=2)

        assert client.change_torrent.call_count == 2
        client.change_torrent.assert_any_call(3, files_wanted=[2, 3])
        client.change_torrent.assert_any_call(3, priority_normal=[2, 3])
        assert result is True

    def test_priority_three_high(self, mocker):
        client = _mock_client()
        mocker.patch("mcps.servers.transmission.get_client", return_value=client)

        result = set_file_priorities(torrent_id=3, file_indices=[5], priority=3)

        assert client.change_torrent.call_count == 2
        client.change_torrent.assert_any_call(3, files_wanted=[5])
        client.change_torrent.assert_any_call(3, priority_high=[5])
        assert result is True


@pytest.mark.unit
class TestTorrentToModelKeyError:
    def test_get_files_raises_key_error(self):
        """Covers lines 130-131: KeyError in get_files sets file_count=0."""
        t = _make_torrent(id=99, name="Broken Files")
        t.get_files.side_effect = KeyError("files")

        result = _torrent_to_model(t)

        assert result.file_count == 0
        assert result.id == 99
