import hashlib
from urllib.parse import quote

import bencodepy


def torrent_bytes_to_magnet(data: bytes) -> str:
    """Convert .torrent file bytes to a magnet link."""
    try:
        torrent: dict = bencodepy.decode(data)  # type: ignore[assignment]
        info = torrent[b"info"]
    except (bencodepy.DecodingError, KeyError) as e:
        msg = "Invalid .torrent file data"
        raise ValueError(msg) from e

    info_encoded = bencodepy.encode(info)
    info_hash = hashlib.sha1(info_encoded).hexdigest()  # noqa: S324

    magnet = f"magnet:?xt=urn:btih:{info_hash}"

    name = info.get(b"name")
    if name:
        magnet += f"&dn={quote(name.decode(errors='replace'))}"

    # Include trackers for private tracker support
    if b"announce" in torrent:
        magnet += f"&tr={quote(torrent[b'announce'].decode(errors='replace'))}"

    return magnet
