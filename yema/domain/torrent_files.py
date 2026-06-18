from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple


class BencodeError(ValueError):
    pass


def _decode_next(data: bytes, index: int) -> Tuple[Any, int]:
    if index >= len(data):
        raise BencodeError("unexpected end of bencode data")

    token = data[index : index + 1]
    if token == b"i":
        end = data.find(b"e", index)
        if end == -1:
            raise BencodeError("unterminated integer")
        return int(data[index + 1 : end]), end + 1

    if token == b"l":
        values = []
        index += 1
        while data[index : index + 1] != b"e":
            value, index = _decode_next(data, index)
            values.append(value)
        return values, index + 1

    if token == b"d":
        values: Dict[bytes, Any] = {}
        index += 1
        while data[index : index + 1] != b"e":
            key, index = _decode_next(data, index)
            if not isinstance(key, bytes):
                raise BencodeError("dictionary key must be bytes")
            value, index = _decode_next(data, index)
            values[key] = value
        return values, index + 1

    if b"0" <= token <= b"9":
        colon = data.find(b":", index)
        if colon == -1:
            raise BencodeError("invalid byte string")
        size = int(data[index:colon])
        start = colon + 1
        end = start + size
        if end > len(data):
            raise BencodeError("byte string exceeds input length")
        return data[start:end], end

    raise BencodeError(f"invalid bencode token: {token!r}")


def bdecode(data: bytes) -> Any:
    value, index = _decode_next(data, 0)
    if index != len(data):
        raise BencodeError("trailing bencode data")
    return value


def bencode_bytes(data: bytes) -> bytes:
    return str(len(data)).encode("ascii") + b":" + data


def calc_pieces_hash(piece_hashes: List[str]) -> str:
    if not piece_hashes:
        return "-"
    pieces_raw = b"".join(bytes.fromhex(piece_hash) for piece_hash in piece_hashes)
    return hashlib.sha1(bencode_bytes(pieces_raw)).hexdigest()


def piece_hashes_from_torrent_data(torrent_data: bytes) -> List[str]:
    root = bdecode(torrent_data)
    if not isinstance(root, dict):
        raise BencodeError("torrent root must be a dictionary")
    info = root.get(b"info")
    if not isinstance(info, dict):
        raise BencodeError("torrent info must be a dictionary")
    pieces = info.get(b"pieces")
    if not isinstance(pieces, bytes):
        raise BencodeError("torrent info.pieces must be bytes")
    if len(pieces) % 20 != 0:
        raise BencodeError("torrent info.pieces length is not divisible by 20")
    return [pieces[index : index + 20].hex() for index in range(0, len(pieces), 20)]


def calc_pieces_hash_from_torrent_data(torrent_data: bytes) -> str:
    return calc_pieces_hash(piece_hashes_from_torrent_data(torrent_data))
