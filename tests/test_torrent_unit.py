import bencodepy
import pytest

from mcps.shared.torrent import torrent_bytes_to_magnet


def _make_torrent_bytes(name="test"):
    info = {b"name": name.encode(), b"piece length": 262144, b"length": 1024, b"pieces": b"\x00" * 20}
    return bencodepy.encode({b"info": info})


@pytest.mark.unit
class TestTorrentBytesToMagnet:
    def test_returns_valid_magnet_link(self):
        data = _make_torrent_bytes("test")
        result = torrent_bytes_to_magnet(data)
        assert result.startswith("magnet:?xt=urn:btih:")

    def test_correct_infohash(self):
        import hashlib

        info = {b"name": b"test", b"piece length": 262144, b"length": 1024, b"pieces": b"\x00" * 20}
        info_encoded = bencodepy.encode(info)
        expected_hash = hashlib.sha1(info_encoded).hexdigest()  # noqa: S324

        data = _make_torrent_bytes("test")
        result = torrent_bytes_to_magnet(data)
        assert expected_hash in result

    def test_includes_display_name(self):
        data = _make_torrent_bytes("My Cool Torrent")
        result = torrent_bytes_to_magnet(data)
        assert "&dn=My%20Cool%20Torrent" in result

    def test_raises_value_error_for_invalid_bytes(self):
        with pytest.raises(ValueError, match=r"Invalid \.torrent file data"):
            torrent_bytes_to_magnet(b"not a torrent")

    def test_raises_value_error_for_missing_info(self):
        data = bencodepy.encode({b"other": b"stuff"})
        with pytest.raises(ValueError, match=r"Invalid \.torrent file data"):
            torrent_bytes_to_magnet(data)

    def test_includes_tracker(self):
        info = {b"name": b"test", b"piece length": 262144, b"length": 1024, b"pieces": b"\x00" * 20}
        torrent = {b"info": info, b"announce": b"udp://tracker.example.com:80"}
        data = bencodepy.encode(torrent)
        result = torrent_bytes_to_magnet(data)
        assert "tr=" in result
        assert "tracker.example.com" in result
