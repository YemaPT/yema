from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import typer

from yema.clients.qbittorrent import (
    add_qb_torrent,
    create_qb_opener,
    delete_qb_torrents,
    fetch_cached_qb_torrent_tracker_urls,
    fetch_qb_torrents,
    get_qb_settings,
    get_torrent_save_path,
)
from yema.clients.yemapt import download_torrent_from_pt, fetch_torrent_ids_from_pt
from yema.config.utils import is_debug_enabled, load_settings
from yema.core.debug import get_exception_message
from yema.core.formatting import format_bytes, render_page
from yema.core.terminal import clear_screen, read_key
from yema.domain.trackers import extract_domain_from_url
from yema.services.torrents import (
    collect_pt_check_results,
    deduplicate_torrents_by_pieces_hash,
    fetch_all_torrents_pieces_hashes,
    get_check_result_sort_key,
    get_torrent_detail_url,
)
from yema.storage.cache import (
    delete_tracker_cache_entries,
    get_valid_pt_cache_entry,
    load_pt_pieces_cache,
    save_pt_pieces_to_cache,
)
from yema.ui.screens import show_check_results, show_deduplicated_torrents, show_pub_results, show_torrent_details

def deduplicate_torrents():
    """Main function for pieces deduplication"""
    qb = get_qb_settings()
    opener = create_qb_opener(qb["host"], qb["username"], qb["password"])
    torrents = fetch_qb_torrents(opener, qb["host"])
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)
    
    if not torrents:
        typer.echo("当前没有种子。")
        return
    
    clear_screen()
    typer.echo("正在处理所有种子的 Pieces Hash（这可能需要几分钟）...\n")
    dedup_dict = deduplicate_torrents_by_pieces_hash(opener, qb["host"], torrents)
    show_deduplicated_torrents(opener, qb["host"], dedup_dict)


def list_torrents():
    qb = get_qb_settings()
    opener = create_qb_opener(qb["host"], qb["username"], qb["password"])
    torrents = fetch_qb_torrents(opener, qb["host"])
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)
    if not torrents:
        typer.echo("当前没有种子。")
        return

    page = 0
    page_size = 20
    selected = 0
    total_pages = (len(torrents) + page_size - 1) // page_size
    while True:
        page_items = torrents[page * page_size : min((page + 1) * page_size, len(torrents))]
        selected = min(selected, len(page_items) - 1)
        render_page(torrents, page, page_size, selected)
        key = read_key()
        if key == "UP":
            if selected > 0:
                selected -= 1
            elif page > 0:
                page -= 1
                selected = min(page_size - 1, len(torrents[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "DOWN":
            if selected < len(page_items) - 1:
                selected += 1
            elif page < total_pages - 1:
                page += 1
                selected = 0
        elif key == "LEFT":
            if page > 0:
                page -= 1
                selected = min(selected, len(torrents[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "RIGHT":
            if page < total_pages - 1:
                page += 1
                selected = min(selected, len(torrents[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "ENTER":
            torrent = page_items[selected]
            show_torrent_details(opener, qb["host"], torrent)
        elif key == "ESC" or key == "q":
            break


def qb_command():
    selected = 0
    items = {
        "list": "查看当前种子列表",
        "pieces_dedup": "Pieces 去重 - 找到完全相同的内容",
        "exit": "退出 qBittorrent 菜单",
    }
    while True:
        clear_screen()
        typer.echo("qBittorrent 操作菜单：使用 ↑ ↓ 选择，按回车确认，按 Esc 退出。\n")
        for index, (name, desc) in enumerate(items.items()):
            prefix = "▶" if index == selected else "  "
            if index == selected:
                typer.secho(f"{prefix} {name} {desc}", fg="cyan")
            else:
                typer.echo(f"{prefix} {name} {desc}")
        typer.echo("")
        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(items)
            continue
        if key == "DOWN":
            selected = (selected + 1) % len(items)
            continue
        if key == "ESC" or key == "q":
            return
        if key == "ENTER":
            if selected == 0:
                list_torrents()
            elif selected == 1:
                deduplicate_torrents()
            else:
                return
            continue


def pub_torrents():
    """列出 qBittorrent 上不在 PT 站点的种子"""
    settings = load_settings()
    yemapt = settings.get("yemapt", {})
    auth = yemapt.get("auth")
    if not auth:
        typer.echo("未配置 yemapt auth，请先运行 yema init 设置。")
        return

    qb = get_qb_settings()
    opener = create_qb_opener(qb["host"], qb["username"], qb["password"])
    torrents = fetch_qb_torrents(opener, qb["host"])
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)

    if not torrents:
        typer.echo("当前没有种子。")
        return

    debug = is_debug_enabled()

    print("获取 pieces hash...")
    pieces_hashes = fetch_all_torrents_pieces_hashes(opener, qb["host"], torrents)

    pt_cache = load_pt_pieces_cache()
    to_query = []
    for pieces_hash in pieces_hashes.values():
        if pieces_hash == "error":
            continue
        is_cached, _ = get_valid_pt_cache_entry(pieces_hash)
        if not is_cached:
            to_query.append(pieces_hash)

    pt_results: Dict[str, int | None] = {}
    if to_query:
        batch_count = (len(to_query) + 99) // 100
        for batch_idx, i in enumerate(range(0, len(to_query), 100), 1):
            batch = to_query[i : i + 100]
            print(f"\r查询 PT 站点... {min(i + 100, len(to_query))}/{len(to_query)}", end="", flush=True)
            try:
                batch_result = fetch_torrent_ids_from_pt(batch, debug=debug)
                pt_results.update(batch_result)
                for ph in batch:
                    save_pt_pieces_to_cache(ph, batch_result.get(ph))
            except typer.Exit as e:
                typer.echo(f"\nPT 查询失败: {e.message or str(e)}", err=True)
            except Exception as e:
                if debug:
                    typer.echo(f"[DEBUG] 批次 {batch_idx} 查询失败: {e}")
        print()

    not_on_pt = []
    for torrent in torrents:
        info_hash = torrent.get("hash")
        pieces_hash = pieces_hashes.get(info_hash)
        if not pieces_hash or pieces_hash == "error":
            continue

        torrent_id = None
        if pieces_hash in pt_results:
            torrent_id = pt_results[pieces_hash]
        else:
            is_cached, cached_id = get_valid_pt_cache_entry(pieces_hash)
            if is_cached:
                torrent_id = cached_id

        if torrent_id is not None:
            continue

        tracker_domains: List[str] = []
        tracker_urls: List[str] = []
        try:
            tracker_urls = fetch_cached_qb_torrent_tracker_urls(opener, qb["host"], info_hash)
            seen = set()
            for url in tracker_urls:
                domain = extract_domain_from_url(url)
                if domain and domain not in seen:
                    seen.add(domain)
                    tracker_domains.append(domain)
        except Exception:
            pass

        detail_url = get_torrent_detail_url(opener, qb["host"], info_hash, tracker_urls)

        not_on_pt.append({
            "name": torrent.get("name", "<unknown>"),
            "size": torrent.get("size", 0),
            "tracker_domains": tracker_domains,
            "detail_url": detail_url,
        })

    if not not_on_pt:
        typer.echo("所有种子都在 PT 站点上。")
        return

    show_pub_results(not_on_pt)


def check_torrents():
    """Check torrents against PT site"""
    qb = get_qb_settings()
    opener = create_qb_opener(qb["host"], qb["username"], qb["password"])
    torrents = fetch_qb_torrents(opener, qb["host"])
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)
    
    if not torrents:
        typer.echo("当前没有种子。")
        return
    
    clear_screen()
    typer.echo("正在检查种子信息...\n")
    
    debug = is_debug_enabled()
    results = collect_pt_check_results(opener, qb["host"], torrents, debug)
    
    if debug:
        found_count = sum(1 for r in results if r["torrent_id"] is not None)
        typer.echo(f"[DEBUG] 最终统计 - 在 PT 站点找到: {found_count}/{len(results)}")

    show_check_results(sorted(results, key=get_check_result_sort_key))


def seed_torrents():
    qb = get_qb_settings()
    opener = create_qb_opener(qb["host"], qb["username"], qb["password"])
    torrents = fetch_qb_torrents(opener, qb["host"])
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)

    if not torrents:
        typer.echo("当前没有种子。")
        return

    clear_screen()
    typer.echo("正在分析可补种项目...\n")
    debug = is_debug_enabled()
    if debug:
        typer.echo("[DEBUG] seed 流程开始")
        typer.echo(f"[DEBUG] qB host: {qb['host']}")
        typer.echo(f"[DEBUG] 总种子数: {len(torrents)}")
    results = collect_pt_check_results(opener, qb["host"], torrents, debug)

    candidates = [
        item for item in results
        if item["torrent_id"] is not None and (not item["has_yemapt_tracker"] or item["needs_replacement"])
    ]
    if debug:
        typer.echo(f"[DEBUG] seed 候选数: {len(candidates)}")
        for item in candidates:
            typer.echo(
                "[DEBUG] seed 候选: "
                f"name={item['name']}, "
                f"torrent_id={item['torrent_id_display']}, "
                f"seed={item['seed_display']}, "
                f"current_user_seeding={item['current_user_seeding']}, "
                f"needs_replacement={item['needs_replacement']}, "
                f"replace_info_hashes={item['replace_info_hashes']}"
            )

    if not candidates:
        typer.echo("没有需要补种或替换的项目。")
        return

    for index, item in enumerate(candidates, 1):
        seed_action = "已有做种替换" if item["replace_info_hashes"] else "新下载"
        seed_user = "当前用户" if item["current_user_seeding"] else (
            ",".join(item["foreign_user_ids"]) if item["foreign_user_ids"] else "-"
        )
        save_path = get_torrent_save_path(opener, qb["host"], item["torrents"][0])
        if debug:
            typer.echo(
                "[DEBUG] 准备处理候选: "
                f"index={index}, "
                f"name={item['name']}, "
                f"action={seed_action}, "
                f"save_path={save_path}"
            )

        typer.echo("")
        typer.echo(f"[{index}/{len(candidates)}] {item['name']}")
        typer.echo(f"  操作: {seed_action}")
        typer.echo(f"  PT ID: {item['torrent_id_display']}")
        typer.echo(f"  当前做种: {item['seed_display']}")
        typer.echo(f"  做种用户: {seed_user}")
        typer.echo(f"  保存路径: {save_path}")
        if item["replace_info_hashes"]:
            typer.echo(f"  待删除 infohash: {', '.join(item['replace_info_hashes'])}")

        if not typer.confirm("是否执行该操作？", default=False):
            if debug:
                typer.echo(f"[DEBUG] 用户跳过候选: {item['name']}")
            typer.echo("已跳过。")
            continue

        try:
            if debug:
                typer.echo(f"[DEBUG] 开始执行候选: {item['name']}")
            torrent_data = download_torrent_from_pt(int(item["torrent_id"]))
            if debug:
                typer.echo(f"[DEBUG] 新种子下载成功: {item['name']}, bytes={len(torrent_data)}")
            if item["replace_info_hashes"]:
                if debug:
                    typer.echo(f"[DEBUG] 先删除旧做种: {item['replace_info_hashes']}")
                delete_qb_torrents(opener, qb["host"], item["replace_info_hashes"])
                delete_tracker_cache_entries(item["replace_info_hashes"])
                if debug:
                    typer.echo(f"[DEBUG] 已清理旧做种 tracker 缓存: {item['replace_info_hashes']}")
                typer.echo("已删除旧的做种条目（保留文件）。")
            if debug:
                typer.echo(f"[DEBUG] 开始向 qB 添加新种: {item['name']}")
            add_qb_torrent(opener, qb["host"], torrent_data, save_path)
            if debug:
                typer.echo(f"[DEBUG] qB 添加新种完成: {item['name']}")
            typer.echo(f"已完成: {seed_action}")
        except Exception as exc:
            msg = get_exception_message(exc)
            if len(msg) > 200:
                error_dir = Path.cwd() / "tmp"
                error_dir.mkdir(parents=True, exist_ok=True)
                error_file = error_dir / f"seed_error_{datetime.now().strftime('%H%M%S')}_{exc.__class__.__name__}.log"
                try:
                    with open(error_file, "w", encoding="utf-8") as f:
                        f.write(msg)
                except Exception:
                    pass
                typer.echo(f"操作失败: {exc.__class__.__name__}（详情已写入 {error_file}）", err=True)
                if debug:
                    typer.echo(f"[DEBUG] 候选执行失败类型: {exc.__class__.__name__}, 详情已写入 {error_file}")
            else:
                typer.echo(f"操作失败: {msg}", err=True)
                if debug:
                    typer.echo(f"[DEBUG] 候选执行失败类型: {exc.__class__.__name__}")
                    typer.echo(f"[DEBUG] 候选执行失败详情: {msg}")
            return
