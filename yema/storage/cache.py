from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

PT_CACHE_HIT_TTL = 30 * 24 * 60 * 60
PT_CACHE_MISS_TTL = 60
PT_CACHE_MISS_SENTINEL = -1
TRACKER_CACHE_TTL = 30 * 24 * 60 * 60

def get_qb_torrent_cache_file_path() -> str:
    """Get the path to the unified qB torrent cache file."""
    import os
    home = os.path.expanduser("~")
    cache_dir = os.path.join(home, ".yema")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "qb_torrent.cache")


def get_legacy_pieces_cache_file_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".yema", "infoPieces.cache")


def get_legacy_tracker_cache_file_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".yema", "qbTrackers.cache")


def load_legacy_qb_torrent_cache() -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}

    try:
        cache_file = get_legacy_pieces_cache_file_path()
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        info_hash, pieces_hash = line.split(":", 1)
                        cache.setdefault(info_hash, {})["piecesHash"] = pieces_hash
    except Exception:
        pass

    try:
        cache_file = get_legacy_tracker_cache_file_path()
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for info_hash, entry in raw.items():
                    if not isinstance(entry, dict):
                        continue
                    trackers = entry.get("trackers")
                    timestamp = entry.get("timestamp")
                    merged = cache.setdefault(info_hash, {})
                    if isinstance(trackers, list):
                        merged["tracker"] = trackers
                    if isinstance(timestamp, int):
                        merged["trackerTimestamp"] = timestamp
    except Exception:
        pass

    return cache


def load_qb_torrent_cache() -> Dict[str, Dict[str, Any]]:
    """Load unified qB torrent cache. Format: infoHash:{...json...} per line."""
    cache_file = get_qb_torrent_cache_file_path()
    cache: Dict[str, Dict[str, Any]] = {}
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        info_hash, raw_entry = line.split(":", 1)
                        entry = json.loads(raw_entry)
                        if isinstance(entry, dict):
                            cache[info_hash] = entry
    except Exception:
        pass
    legacy_cache = load_legacy_qb_torrent_cache()
    changed = False
    for info_hash, entry in legacy_cache.items():
        merged = cache.setdefault(info_hash, {})
        for key, value in entry.items():
            if key not in merged:
                merged[key] = value
                changed = True
    if changed:
        save_qb_torrent_cache(cache)
    return cache


def save_qb_torrent_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    cache_file = get_qb_torrent_cache_file_path()
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            for info_hash, entry in sorted(cache.items()):
                f.write(f"{info_hash}:{json.dumps(entry, ensure_ascii=False, separators=(',', ':'))}\n")
    except Exception:
        pass


def get_cached_pieces_hash(info_hash: str) -> str | None:
    entry = load_qb_torrent_cache().get(info_hash)
    if not entry:
        return None
    pieces_hash = entry.get("piecesHash")
    if isinstance(pieces_hash, str) and pieces_hash:
        return pieces_hash
    return None


def save_pieces_to_cache(info_hash: str, pieces_hash: str) -> None:
    """Save pieces hash to the unified qB torrent cache."""
    cache = load_qb_torrent_cache()
    entry = cache.get(info_hash, {})
    if entry.get("piecesHash") == pieces_hash:
        return
    entry["piecesHash"] = pieces_hash
    cache[info_hash] = entry
    save_qb_torrent_cache(cache)


def get_pt_cache_file_path() -> str:
    """Get the path to PT pieces cache file"""
    home = os.path.expanduser("~")
    cache_dir = os.path.join(home, ".yema")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "ptPiecesId.cache")


def load_pt_pieces_cache() -> Dict[str, tuple]:
    """Load PT pieces cache from file. Format: piecesHash:torrentId:timestamp"""
    cache_file = get_pt_cache_file_path()
    cache = {}
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        parts = line.rsplit(":", 2)
                        if len(parts) == 3:
                            pieces_hash, torrent_id, timestamp = parts
                            try:
                                cache[pieces_hash] = (int(torrent_id), int(timestamp))
                            except ValueError:
                                pass
    except Exception:
        pass
    return cache


def save_pt_pieces_to_cache(pieces_hash: str, torrent_id: int | None) -> None:
    """Save a PT pieces entry to cache file"""
    import time
    cache_file = get_pt_cache_file_path()
    cache = load_pt_pieces_cache()
    timestamp = int(time.time())
    cache[pieces_hash] = (PT_CACHE_MISS_SENTINEL if torrent_id is None else torrent_id, timestamp)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            for ph, (tid, ts) in sorted(cache.items()):
                f.write(f"{ph}:{tid}:{ts}\n")
    except Exception:
        pass


def get_valid_pt_cache_entry(pieces_hash: str) -> tuple[bool, int | None]:
    """Get valid PT cache entry and whether it exists."""
    import time
    cache = load_pt_pieces_cache()
    if pieces_hash in cache:
        torrent_id, timestamp = cache[pieces_hash]
        ttl = PT_CACHE_MISS_TTL if torrent_id == PT_CACHE_MISS_SENTINEL else PT_CACHE_HIT_TTL
        if time.time() - timestamp < ttl:
            return True, None if torrent_id == PT_CACHE_MISS_SENTINEL else torrent_id
        else:
            try:
                del cache[pieces_hash]
                cache_file = get_pt_cache_file_path()
                with open(cache_file, "w", encoding="utf-8") as f:
                    for ph, (tid, ts) in sorted(cache.items()):
                        f.write(f"{ph}:{tid}:{ts}\n")
            except Exception:
                pass
    return False, None


def get_valid_tracker_cache_entry(info_hash: str) -> tuple[bool, List[str]]:
    import time

    cache = load_qb_torrent_cache()
    entry = cache.get(info_hash)
    if entry:
        trackers = entry.get("tracker")
        timestamp = entry.get("trackerTimestamp")
        if isinstance(trackers, list) and isinstance(timestamp, int):
            if time.time() - timestamp < TRACKER_CACHE_TTL:
                return True, trackers
            try:
                del entry["tracker"]
                del entry["trackerTimestamp"]
                if not entry:
                    del cache[info_hash]
                else:
                    cache[info_hash] = entry
                save_qb_torrent_cache(cache)
            except Exception:
                pass
    return False, []


def delete_tracker_cache_entries(info_hashes: List[str]) -> None:
    cache = load_qb_torrent_cache()
    changed = False
    for info_hash in info_hashes:
        entry = cache.get(info_hash)
        if not entry:
            continue
        removed = False
        if "tracker" in entry:
            del entry["tracker"]
            removed = True
        if "trackerTimestamp" in entry:
            del entry["trackerTimestamp"]
            removed = True
        if removed:
            if entry:
                cache[info_hash] = entry
            else:
                del cache[info_hash]
            changed = True
    if changed:
        save_qb_torrent_cache(cache)
