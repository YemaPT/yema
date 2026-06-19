from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List

import typer

from yema.clients.qbittorrent import (
    fetch_cached_qb_torrent_tracker_urls,
    fetch_qb_torrent_piece_hashes,
    fetch_qb_torrent_properties,
)
from yema.clients.yemapt import fetch_torrent_ids_from_pt, get_current_yemapt_user_id
from yema.config.utils import YEMAPT_HOST
from yema.domain.trackers import (
    _parse_hhanclub_detail_url,
    _parse_mteam_detail_url,
    extract_domain_from_url,
    extract_yemapt_tracker_user_id,
    normalize_user_id,
)
from yema.domain.torrent_files import bencode_bytes, calc_pieces_hash
from yema.storage.cache import (
    get_cached_pieces_hash,
    get_valid_pt_cache_entry,
    load_pt_pieces_cache,
    load_qb_torrent_cache,
    save_pieces_to_cache,
    save_pt_pieces_to_cache,
    save_qb_torrent_cache,
)

def get_torrent_detail_url(
    opener: urllib.request.OpenerDirector,
    host: str,
    info_hash: str,
    tracker_urls: List[str],
) -> str | None:
    """Get detail page URL for a torrent. Checks cache first, then attempts
    extraction from tracker URLs (m-team) or torrent properties (hhanclub)."""
    cache = load_qb_torrent_cache()
    entry = cache.get(info_hash)
    if entry:
        cached_url = entry.get("detailUrl")
        if isinstance(cached_url, str):
            return cached_url if cached_url else None

    url = _parse_mteam_detail_url(tracker_urls)
    if url:
        entry = cache.get(info_hash, {})
        entry["detailUrl"] = url
        cache[info_hash] = entry
        save_qb_torrent_cache(cache)
        return url

    try:
        properties = fetch_qb_torrent_properties(opener, host, info_hash)
        comment = properties.get("comment", "")
        url = _parse_hhanclub_detail_url(comment)
        if url:
            entry = cache.get(info_hash, {})
            entry["detailUrl"] = url
            cache[info_hash] = entry
            save_qb_torrent_cache(cache)
            return url
    except Exception:
        pass

    entry = cache.get(info_hash, {})
    entry["detailUrl"] = ""
    cache[info_hash] = entry
    save_qb_torrent_cache(cache)
    return None


def fetch_all_torrents_pieces_hashes(
    opener: urllib.request.OpenerDirector | None,
    host: str,
    torrents: List[Dict[str, Any]],
    pieces_hash_resolver: Callable[[Dict[str, Any]], str] | None = None,
    debug: bool = False,
) -> Dict[str, str]:
    """
    Fetch pieces hashes for all torrents, using cache when available.
    Returns dict: {info_hash: pieces_hash}
    """
    result = {}
    total = len(torrents)
    
    for idx, torrent in enumerate(torrents):
        print(f"\r处理中... {idx + 1}/{total}", end="", flush=True)
        info_hash = torrent.get("hash")
        if not info_hash:
            if debug:
                typer.echo(f"\n[DEBUG] 跳过缺少 infohash 的种子: name={torrent.get('name', '<unknown>')}")
            continue

        if debug:
            typer.echo(
                "\n[DEBUG] pieces hash 开始: "
                f"{idx + 1}/{total}, "
                f"source={torrent.get('source', '-')}, "
                f"name={torrent.get('name', '<unknown>')}, "
                f"info_hash={info_hash}"
            )
        
        # Check cache first
        pieces_hash = get_cached_pieces_hash(info_hash)
        if pieces_hash is not None:
            if debug:
                typer.echo(f"[DEBUG] pieces hash 缓存命中: info_hash={info_hash}, pieces_hash={pieces_hash}")
            result[info_hash] = pieces_hash
        else:
            try:
                if pieces_hash_resolver is not None:
                    if debug:
                        typer.echo(f"[DEBUG] pieces hash 使用自定义解析器: info_hash={info_hash}")
                    pieces_hash = pieces_hash_resolver(torrent)
                else:
                    if opener is None:
                        raise RuntimeError("缺少 qBittorrent opener，无法获取 pieces hash。")
                    if debug:
                        typer.echo(f"[DEBUG] qBittorrent 请求 piece hashes: host={host}, info_hash={info_hash}")
                    piece_hashes = fetch_qb_torrent_piece_hashes(opener, host, info_hash)
                    if debug:
                        typer.echo(f"[DEBUG] qBittorrent piece hashes 返回: info_hash={info_hash}, count={len(piece_hashes)}")
                    pieces_hash = calc_pieces_hash(piece_hashes)
                    save_pieces_to_cache(info_hash, pieces_hash)
            except Exception:
                if pieces_hash_resolver is not None:
                    if debug:
                        typer.echo(f"[DEBUG] pieces hash 解析失败并向上抛出: info_hash={info_hash}")
                    raise
                pieces_hash = "error"
                if debug:
                    typer.echo(f"[DEBUG] qBittorrent pieces hash 获取失败: info_hash={info_hash}")

            result[info_hash] = pieces_hash
            if debug:
                typer.echo(f"[DEBUG] pieces hash 完成: info_hash={info_hash}, pieces_hash={pieces_hash}")
    
    print()  # 完成后换行
    return result


def deduplicate_torrents_by_pieces_hash(
    opener: urllib.request.OpenerDirector | None,
    host: str,
    torrents: List[Dict[str, Any]],
    pieces_hash_resolver: Callable[[Dict[str, Any]], str] | None = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Group torrents by pieces hash.
    Returns dict: {pieces_hash: {name, count, torrents: [list of torrents]}}
    Uses cache to avoid recalculating pieces hashes.
    """
    result = {}
    pieces_hashes = fetch_all_torrents_pieces_hashes(opener, host, torrents, pieces_hash_resolver, debug)
    
    for torrent in torrents:
        info_hash = torrent.get("hash")
        if not info_hash:
            continue
        
        pieces_hash = pieces_hashes.get(info_hash, "error")
        
        if pieces_hash not in result:
            result[pieces_hash] = {
                "name": torrent.get("name", "<unknown>"),
                "count": 0,
                "torrents": [],
            }
        
        result[pieces_hash]["count"] += 1
        result[pieces_hash]["torrents"].append(torrent)
    
    return result


def collect_pt_check_results(
    opener: urllib.request.OpenerDirector | None,
    host: str,
    torrents: List[Dict[str, Any]],
    debug: bool,
    pieces_hash_resolver: Callable[[Dict[str, Any]], str] | None = None,
    tracker_url_fetcher: Callable[[Dict[str, Any]], List[str]] | None = None,
) -> List[Dict[str, Any]]:
    if debug:
        typer.echo("[DEBUG] 检查过程开始")
        typer.echo(f"[DEBUG] 总种子数: {len(torrents)}")

    print("准备数据中...")
    pieces_hashes = fetch_all_torrents_pieces_hashes(opener, host, torrents, pieces_hash_resolver)

    if debug:
        valid_hashes = sum(1 for h in pieces_hashes.values() if h != "error")
        typer.echo(f"[DEBUG] 成功获取 pieces hash: {valid_hashes}/{len(torrents)}")

    pt_cache = load_pt_pieces_cache()
    if debug:
        typer.echo(f"[DEBUG] PT 缓存中条目数: {len(pt_cache)}")

    to_query = []
    for pieces_hash in pieces_hashes.values():
        if pieces_hash == "error":
            continue
        is_cached, _ = get_valid_pt_cache_entry(pieces_hash)
        if not is_cached:
            to_query.append(pieces_hash)

    if debug:
        typer.echo(f"[DEBUG] 需要查询 PT 的 pieces hash: {len(to_query)}")

    pt_results = {}
    batch_count = (len(to_query) + 99) // 100
    for batch_idx, i in enumerate(range(0, len(to_query), 100), 1):
        batch = to_query[i : i + 100]
        print(f"\r查询 PT 站点... {min(i + 100, len(to_query))}/{len(to_query)}", end="", flush=True)

        if debug:
            typer.echo(f"\n[DEBUG] PT 批次查询 {batch_idx}/{batch_count}: {len(batch)} 个 pieces hash")

        try:
            batch_result = fetch_torrent_ids_from_pt(batch, debug=debug)
            pt_results.update(batch_result)

            if debug:
                typer.echo(f"[DEBUG] 批次 {batch_idx} 返回结果数: {len(batch_result)}")

            for ph in batch:
                save_pt_pieces_to_cache(ph, batch_result.get(ph))
        except typer.Exit as e:
            typer.echo(f"\nPT 查询失败: {e.message or str(e)}", err=True)
            if debug:
                typer.echo(f"[DEBUG] 批次 {batch_idx} 查询失败: {e}")
        except Exception as e:
            if debug:
                typer.echo(f"[DEBUG] 批次 {batch_idx} 查询失败: {e}")
                raise

    print()

    if debug:
        typer.echo(f"[DEBUG] 总共从 PT 站点获取: {len(pt_results)} 个结果")

    current_user_id = normalize_user_id(get_current_yemapt_user_id())
    if debug:
        typer.echo(f"[DEBUG] 当前 yemapt 用户 ID: {current_user_id!r}")
    grouped_torrents = []
    group_map = {}
    for torrent in torrents:
        info_hash = torrent.get("hash")
        pieces_hash = pieces_hashes.get(info_hash)
        if pieces_hash and pieces_hash != "error":
            if pieces_hash in group_map:
                group_map[pieces_hash]["torrents"].append(torrent)
                continue
            group = {"pieces_hash": pieces_hash, "torrents": [torrent]}
            group_map[pieces_hash] = group
            grouped_torrents.append(group)
            continue
        grouped_torrents.append({"pieces_hash": pieces_hash, "torrents": [torrent]})

    results = []
    for group in grouped_torrents:
        torrent = group["torrents"][0]
        pieces_hash = group["pieces_hash"] or pieces_hashes.get(torrent.get("hash"))
        torrent_id = None
        if pieces_hash and pieces_hash != "error":
            if pieces_hash in pt_results:
                torrent_id = pt_results[pieces_hash]
            else:
                is_cached, cached_id = get_valid_pt_cache_entry(pieces_hash)
                if is_cached and cached_id is not None:
                    torrent_id = cached_id

        tracker_user_ids = set()
        current_user_seeding = False
        has_yemapt_tracker = False
        replace_info_hashes = []
        for grouped_torrent in group["torrents"]:
            grouped_hash = grouped_torrent.get("hash")
            if not grouped_hash:
                continue
            try:
                if debug:
                    typer.echo(
                        "[DEBUG] tracker 获取开始: "
                        f"name={grouped_torrent.get('name', '<unknown>')}, "
                        f"info_hash={grouped_hash}"
                    )
                if tracker_url_fetcher is not None:
                    tracker_urls = tracker_url_fetcher(grouped_torrent)
                else:
                    if opener is None:
                        raise RuntimeError("缺少 qBittorrent opener，无法获取 tracker。")
                    tracker_urls = fetch_cached_qb_torrent_tracker_urls(opener, host, grouped_hash)
                if debug:
                    typer.echo(f"[DEBUG] tracker 获取完成: info_hash={grouped_hash}, count={len(tracker_urls)}")
            except Exception as exc:
                if debug:
                    typer.echo(f"[DEBUG] tracker 获取失败: info_hash={grouped_hash}, error={exc}")
                tracker_urls = []

            torrent_has_foreign_seed = False
            torrent_has_current_seed = False
            torrent_has_yemapt = False
            for tracker_url in tracker_urls:
                if "yemapt.org" not in extract_domain_from_url(tracker_url).lower():
                    continue
                torrent_has_yemapt = True
                has_yemapt_tracker = True
                tracker_user_id = normalize_user_id(extract_yemapt_tracker_user_id(tracker_url))
                if tracker_user_id:
                    tracker_user_ids.add(tracker_user_id)
                    if current_user_id is not None and tracker_user_id == current_user_id:
                        torrent_has_current_seed = True
                    elif current_user_id is not None:
                        torrent_has_foreign_seed = True
                elif current_user_id is not None:
                    torrent_has_foreign_seed = True

            if torrent_has_current_seed:
                current_user_seeding = True
            if (
                current_user_id is not None
                and torrent_has_yemapt
                and not torrent_has_current_seed
                and torrent_has_foreign_seed
            ):
                replace_info_hashes.append(grouped_hash)

        if current_user_seeding:
            replace_info_hashes = []

        foreign_user_ids = sorted(
            [uid for uid in tracker_user_ids if current_user_id is not None and uid != current_user_id],
            key=lambda value: int(value) if value.isdigit() else value,
        )
        if current_user_id is not None and has_yemapt_tracker and not tracker_user_ids:
            foreign_user_ids = ["?"]

        torrent_id_display = "-" if torrent_id is None else str(torrent_id)
        if current_user_seeding:
            seed_display = "✓"
        elif not has_yemapt_tracker:
            seed_display = "-"
        elif current_user_id is None:
            seed_display = "?"
        else:
            seed_display = ",".join(foreign_user_ids) if foreign_user_ids else "?"

        if debug:
            typer.echo(
                "[DEBUG] 分组结果: "
                f"name={torrent.get('name', '<unknown>')}, "
                f"pieces_hash={pieces_hash}, "
                f"qb_count={len(group['torrents'])}, "
                f"torrent_id={torrent_id_display}, "
                f"seed_display={seed_display}, "
                f"current_user_id={current_user_id!r}, "
                f"tracker_user_ids={sorted(tracker_user_ids)!r}, "
                f"has_yemapt_tracker={has_yemapt_tracker}, "
                f"current_user_seeding={current_user_seeding}, "
                f"replace_info_hashes={replace_info_hashes}"
            )

        results.append({
            "source": torrent.get("source", "-"),
            "name": torrent.get("name", "<unknown>"),
            "pieces_hash": pieces_hash,
            "torrents": group["torrents"],
            "torrent_id": torrent_id,
            "torrent_id_display": torrent_id_display,
            "seed_display": seed_display,
            "has_yemapt_tracker": has_yemapt_tracker,
            "current_user_seeding": current_user_seeding,
            "needs_replacement": bool(replace_info_hashes),
            "foreign_user_ids": foreign_user_ids,
            "replace_info_hashes": replace_info_hashes,
        })

    return results


def get_check_result_sort_key(item: Dict[str, Any]) -> tuple:
    has_id_rank = 0 if item["torrent_id"] is not None else 1
    if item["torrent_id"] is None:
        seed_rank = 3
    elif not item["has_yemapt_tracker"]:
        seed_rank = 0
    elif item["current_user_seeding"]:
        seed_rank = 2
    else:
        seed_rank = 1
    return (has_id_rank, seed_rank)
