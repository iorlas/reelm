from datetime import timedelta
from enum import Enum
from unittest.mock import MagicMock

import httpx
import pytest

from mcps.servers.transmission import (
    FolderEntry,
    Torrent,
    TorrentFile,
    TorrentFileList,
    TorrentList,
    _aggregate_by_depth,
    _resolve_url,
    _torrent_to_model,
)


class FakeStatus(Enum):
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    STOPPED = "stopped"


class FakeFile:
    def __init__(self, name="test.txt", size=1024, completed=512, priority=1):
        self.name = name
        self.size = size
        self.completed = completed
        self.priority = priority


def make_fake_torrent(
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
        t.get_files = None
    return t


@pytest.mark.unit
class TestModels:
    def test_torrent_file_model(self):
        data = {"index": 0, "name": "movie.mkv", "size": 1073741824, "completed": 536870912, "priority": 1}
        f = TorrentFile.model_validate(data)
        assert f.index == 0
        assert f.name == "movie.mkv"
        assert f.size == 1073741824
        assert f.completed == 536870912
        assert f.priority == 1

    def test_folder_entry_model(self):
        data = {"name": "Season 1", "file_count": 10, "total_size": 10737418240, "completed_size": 5368709120}
        f = FolderEntry.model_validate(data)
        assert f.name == "Season 1"
        assert f.file_count == 10
        assert f.total_size == 10737418240
        assert f.completed_size == 5368709120
        assert f.is_folder is True

    def test_torrent_parses_full_response(self):
        data = {
            "id": 1,
            "name": "Ubuntu 24.04",
            "status": "downloading",
            "progress": 45.5,
            "download_speed": 1024000,
            "upload_speed": 512000,
            "eta": 3600,
            "total_size": 4294967296,
            "comment": "https://ubuntu.com",
            "error_string": "",
            "file_count": 1,
        }
        torrent = Torrent.model_validate(data)
        assert torrent.id == 1
        assert torrent.name == "Ubuntu 24.04"
        assert torrent.status == "downloading"
        assert torrent.progress == 45.5
        assert torrent.download_speed == 1024000
        assert torrent.upload_speed == 512000
        assert torrent.eta == 3600
        assert torrent.total_size == 4294967296
        assert torrent.comment == "https://ubuntu.com"
        assert torrent.error_string == ""
        assert torrent.file_count == 1

    def test_torrent_handles_none_eta(self):
        data = {
            "id": 2,
            "name": "Completed Torrent",
            "status": "seeding",
            "progress": 100.0,
            "download_speed": 0,
            "upload_speed": 256000,
            "eta": None,
            "total_size": 1073741824,
            "comment": "",
            "error_string": "",
            "file_count": 0,
        }
        torrent = Torrent.model_validate(data)
        assert torrent.eta is None

    def test_torrent_list_model_with_pagination(self):
        data = {
            "torrents": [
                {
                    "id": 1,
                    "name": "Torrent 1",
                    "status": "downloading",
                    "progress": 50.0,
                    "download_speed": 1024,
                    "upload_speed": 512,
                    "eta": 1800,
                    "total_size": 1073741824,
                    "comment": "",
                    "error_string": "",
                    "file_count": 0,
                },
            ],
            "total": 10,
            "offset": 0,
            "has_more": True,
        }
        tlist = TorrentList.model_validate(data)
        assert len(tlist.torrents) == 1
        assert tlist.total == 10
        assert tlist.offset == 0
        assert tlist.has_more is True

    def test_torrent_file_list_model_with_pagination(self):
        data = {
            "torrent_id": 42,
            "files": [
                {"index": 0, "name": "video.mkv", "size": 1000, "completed": 1000, "priority": 1},
            ],
            "total": 50,
            "offset": 0,
            "has_more": True,
        }
        flist = TorrentFileList.model_validate(data)
        assert flist.torrent_id == 42
        assert len(flist.files) == 1
        assert flist.total == 50
        assert flist.offset == 0
        assert flist.has_more is True

    def test_torrent_file_list_with_folder_entries(self):
        data = {
            "torrent_id": 42,
            "files": [
                {"name": "Season 1", "file_count": 10, "total_size": 1000, "completed_size": 500, "is_folder": True},
                {"index": 0, "name": "readme.txt", "size": 100, "completed": 100, "priority": 1},
            ],
            "total": 2,
            "offset": 0,
            "has_more": False,
        }
        flist = TorrentFileList.model_validate(data)
        assert len(flist.files) == 2
        assert isinstance(flist.files[0], FolderEntry)
        assert isinstance(flist.files[1], TorrentFile)

    def test_torrent_file_list_with_depth_and_hint(self):
        data = {
            "torrent_id": 42,
            "files": [
                {"name": "Show", "file_count": 20, "total_size": 5000, "completed_size": 2500, "is_folder": True},
            ],
            "total": 1,
            "offset": 0,
            "has_more": False,
            "current_depth": 1,
            "hint": "Folders found. To see their contents, increase depth (e.g., depth=2) or use depth=None for all files.",
        }
        flist = TorrentFileList.model_validate(data)
        assert flist.current_depth == 1
        assert flist.hint is not None
        assert "depth=2" in flist.hint

    def test_torrent_file_list_defaults_for_new_fields(self):
        data = {
            "torrent_id": 42,
            "files": [],
            "total": 0,
            "offset": 0,
            "has_more": False,
        }
        flist = TorrentFileList.model_validate(data)
        assert flist.current_depth is None
        assert flist.hint is None


@pytest.mark.unit
class TestAggregateByDepth:
    def test_depth_zero_returns_all_files(self):
        files = [
            TorrentFile(index=0, name="Show/S01/E01.mkv", size=100, completed=100, priority=1),
            TorrentFile(index=1, name="Show/S01/E02.mkv", size=100, completed=50, priority=1),
        ]
        result = _aggregate_by_depth(files, 0)
        assert len(result) == 2
        assert all(isinstance(f, TorrentFile) for f in result)

    def test_depth_one_aggregates_top_level(self):
        files = [
            TorrentFile(index=0, name="Show/S01/E01.mkv", size=100, completed=100, priority=1),
            TorrentFile(index=1, name="Show/S01/E02.mkv", size=200, completed=50, priority=1),
            TorrentFile(index=2, name="readme.txt", size=10, completed=10, priority=1),
        ]
        result = _aggregate_by_depth(files, 1)
        # readme.txt at depth 1 stays as file, Show folder gets aggregated
        assert len(result) == 2
        files_only = [f for f in result if isinstance(f, TorrentFile)]
        folders = [f for f in result if isinstance(f, FolderEntry)]
        assert len(files_only) == 1
        assert files_only[0].name == "readme.txt"
        assert len(folders) == 1
        assert folders[0].name == "Show"
        assert folders[0].file_count == 2
        assert folders[0].total_size == 300
        assert folders[0].completed_size == 150

    def test_depth_two_aggregates_two_levels(self):
        files = [
            TorrentFile(index=0, name="Show/S01/E01.mkv", size=100, completed=100, priority=1),
            TorrentFile(index=1, name="Show/S01/E02.mkv", size=200, completed=50, priority=1),
            TorrentFile(index=2, name="Show/S02/E01.mkv", size=150, completed=75, priority=1),
        ]
        result = _aggregate_by_depth(files, 2)
        # All files have 3 parts, so all get aggregated at depth 2
        folders = [f for f in result if isinstance(f, FolderEntry)]
        assert len(folders) == 2
        folder_names = {f.name for f in folders}
        assert folder_names == {"Show/S01", "Show/S02"}

    def test_mixed_depths(self):
        files = [
            TorrentFile(index=0, name="movie.mkv", size=1000, completed=1000, priority=1),
            TorrentFile(index=1, name="Extras/making.mkv", size=500, completed=500, priority=1),
            TorrentFile(index=2, name="Extras/deleted.mkv", size=300, completed=150, priority=1),
        ]
        result = _aggregate_by_depth(files, 1)
        files_only = [f for f in result if isinstance(f, TorrentFile)]
        folders = [f for f in result if isinstance(f, FolderEntry)]
        assert len(files_only) == 1
        assert files_only[0].name == "movie.mkv"
        assert len(folders) == 1
        assert folders[0].name == "Extras"
        assert folders[0].file_count == 2


@pytest.mark.unit
class TestTorrentToModel:
    def test_converts_status_enum_to_string(self):
        fake = make_fake_torrent(status=FakeStatus.DOWNLOADING)
        result = _torrent_to_model(fake)
        assert result.status == "downloading"

    def test_handles_status_without_value_attr(self):
        fake = make_fake_torrent()
        fake.status = "stopped"
        result = _torrent_to_model(fake)
        assert result.status == "stopped"

    def test_handles_negative_eta(self):
        fake = make_fake_torrent(eta=timedelta(seconds=-1))
        result = _torrent_to_model(fake)
        assert result.eta is None

    def test_handles_zero_eta(self):
        fake = make_fake_torrent(eta=timedelta(seconds=0))
        result = _torrent_to_model(fake)
        assert result.eta == 0

    def test_handles_none_eta(self):
        fake = make_fake_torrent(eta=None)
        result = _torrent_to_model(fake)
        assert result.eta is None

    def test_handles_positive_eta(self):
        fake = make_fake_torrent(eta=timedelta(seconds=3600))
        result = _torrent_to_model(fake)
        assert result.eta == 3600

    def test_maps_rate_fields_correctly(self):
        fake = make_fake_torrent(rate_download=5000, rate_upload=2500)
        result = _torrent_to_model(fake)
        assert result.download_speed == 5000
        assert result.upload_speed == 2500

    def test_maps_all_fields(self):
        fake = make_fake_torrent(
            id=42,
            name="Test.Movie.2024.1080p",
            status=FakeStatus.SEEDING,
            progress=100.0,
            rate_download=0,
            rate_upload=1024,
            eta=timedelta(seconds=-1),
            total_size=5368709120,
            comment="https://example.com",
            error_string="Tracker error",
            files=[FakeFile(name="movie.mkv", size=5368709120, completed=5368709120, priority=1)],
        )
        result = _torrent_to_model(fake)
        assert result.id == 42
        assert result.name == "Test.Movie.2024.1080p"
        assert result.status == "seeding"
        assert result.progress == 100.0
        assert result.download_speed == 0
        assert result.upload_speed == 1024
        assert result.eta is None
        assert result.total_size == 5368709120
        assert result.comment == "https://example.com"
        assert result.error_string == "Tracker error"
        assert result.file_count == 1

    def test_handles_none_comment_and_error(self):
        fake = make_fake_torrent(comment=None, error_string=None)
        result = _torrent_to_model(fake)
        assert result.comment == ""
        assert result.error_string == ""

    def test_handles_no_files(self):
        fake = make_fake_torrent(files=None)
        result = _torrent_to_model(fake)
        assert result.file_count == 0

    def test_handles_empty_files(self):
        fake = make_fake_torrent(files=[])
        result = _torrent_to_model(fake)
        assert result.file_count == 0

    def test_handles_multiple_files(self):
        files = [
            FakeFile(name="video.mkv", size=1000, completed=1000, priority=1),
            FakeFile(name="subs.srt", size=100, completed=50, priority=0),
        ]
        fake = make_fake_torrent(files=files)
        result = _torrent_to_model(fake)
        assert result.file_count == 2


@pytest.mark.unit
class TestResolveUrl:
    def test_returns_magnet_unchanged(self):
        magnet = "magnet:?xt=urn:btih:abc123"
        assert _resolve_url(magnet) == magnet

    def test_follows_302_redirect_to_magnet(self, mocker):
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"location": "magnet:?xt=urn:btih:xyz789"}
        mocker.patch("httpx.get", return_value=mock_resp)

        result = _resolve_url("http://jackett/dl/123")
        assert result == "magnet:?xt=urn:btih:xyz789"

    def test_follows_301_redirect_to_magnet(self, mocker):
        mock_resp = MagicMock()
        mock_resp.status_code = 301
        mock_resp.headers = {"location": "magnet:?xt=urn:btih:abc"}
        mocker.patch("httpx.get", return_value=mock_resp)

        result = _resolve_url("http://jackett/dl/456")
        assert result == "magnet:?xt=urn:btih:abc"

    def test_raises_if_redirect_not_magnet(self, mocker):
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"location": "http://example.com/file.torrent"}
        mock_resp.content = b""
        mocker.patch("httpx.get", return_value=mock_resp)

        with pytest.raises(RuntimeError, match="Unexpected response"):
            _resolve_url("http://jackett/dl/789")

    def test_returns_bytes_if_200_ok(self, mocker):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.content = b"torrent-file-bytes"
        mock_resp.url = "http://jackett/dl/torrent.torrent"
        mocker.patch("httpx.get", return_value=mock_resp)

        result = _resolve_url("http://jackett/dl/torrent.torrent")
        assert result == b"torrent-file-bytes"

    def test_raises_on_exception(self, mocker):
        mocker.patch("httpx.get", side_effect=httpx.ConnectError("Network error"))

        with pytest.raises(RuntimeError, match="magnet link"):
            _resolve_url("http://jackett/dl/fail")

    def test_raises_404_with_actionable_message(self, mocker):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.headers = {}
        mock_resp.url = None
        mocker.patch("httpx.get", return_value=mock_resp)

        with pytest.raises(RuntimeError, match="search again"):
            _resolve_url("http://jackett/dl/expired")

    def test_raises_unexpected_response_with_actionable_message(self, mocker):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.content = b""
        mock_resp.url = None
        mocker.patch("httpx.get", return_value=mock_resp)

        with pytest.raises(RuntimeError, match="magnet link"):
            _resolve_url("http://jackett/dl/bad")
