import urllib.request
import webbrowser
from typing import Any, Dict, List

import typer

from yema.clients.qbittorrent import (
    fetch_qb_torrent_piece_hashes,
    fetch_qb_torrent_properties,
    fetch_qb_torrent_trackers,
)
from yema.core.formatting import (
    format_bytes,
    format_duration,
    format_timestamp,
    get_terminal_width,
    pad_display,
    render_page,
    truncate_display,
)
from yema.core.terminal import clear_screen, read_key
from yema.domain.trackers import extract_domain_from_url, get_tracker_display_name, is_tracker_address
from yema.services.torrents import calc_pieces_hash

def show_torrent_details(opener: urllib.request.OpenerDirector, host: str, torrent: Dict[str, Any]) -> None:
    torrent_hash = torrent.get("hash")
    if not torrent_hash:
        typer.echo("无法获取种子 hash，无法查看详情。")
        return

    properties = fetch_qb_torrent_properties(opener, host, torrent_hash)
    trackers = fetch_qb_torrent_trackers(opener, host, torrent_hash)
    actual_trackers = [t.get("url", "") for t in trackers if is_tracker_address(str(t.get("url", "")))]
    piece_hashes = fetch_qb_torrent_piece_hashes(opener, host, torrent_hash)
    pieces_hash = calc_pieces_hash(piece_hashes)

    added_on = properties.get("added_on", torrent.get("added_on"))
    comment = properties.get("comment", "")
    info_hash = properties.get("hash", torrent_hash)
    seeds = properties.get("num_seeds", properties.get("num_complete", "-"))
    leeches = properties.get("num_leechs", properties.get("num_incomplete", "-"))
    save_path = properties.get("save_path", "")
    seeding_time = properties.get("seeding_time", properties.get("seeding_time_long", 0))
    uploaded = properties.get("total_uploaded", 0)
    downloaded = properties.get("total_downloaded", 0)
    ratio = properties.get("ratio", torrent.get("ratio", 0.0))
    progress = torrent.get("progress", 0.0) * 100

    view_detail = False
    while True:
        clear_screen()
        title = "种子详情 - 详细信息" if view_detail else "种子详情 - 简要信息"
        typer.echo(f"{title}\n")
        typer.echo(f"名称: {torrent.get('name', '<unknown>')}\n")
        
        if view_detail:
            typer.echo("=== 所有 Properties ===")
            for key in sorted(properties):
                value = properties[key]
                typer.echo(f"  {key}: {value}")
            typer.echo("")
            typer.echo("=== 所有 Trackers ===")
            if trackers:
                for idx, tracker in enumerate(trackers, start=1):
                    url = tracker.get("url", "")
                    status = tracker.get("status", "")
                    msg = tracker.get("msg", "")
                    typer.echo(f"  {idx:2d}. {url} [{status}] {msg}")
            else:
                typer.echo("  无 tracker 信息。")
        else:
            typer.echo(f"添加日期: {format_timestamp(added_on)}")
            typer.echo(f"Comment: {comment}")
            typer.echo(f"Hash: {info_hash}")
            typer.echo(f"Pieces Hash: {pieces_hash}")
            typer.echo(f"做种数: {seeds}  下载数: {leeches}")
            typer.echo(f"Save path: {save_path}")
            typer.echo(f"Seeding time: {format_duration(seeding_time)}")
            typer.echo(f"进度: {progress:.1f}%")
            typer.echo(f"上传: {format_bytes(uploaded)}  下载: {format_bytes(downloaded)}  比率: {ratio * 100:.2f}%")
            typer.echo("")
            typer.echo("Trackers:")
            if actual_trackers:
                for idx, tracker_url in enumerate(actual_trackers[:3], start=1):
                    typer.echo(f"  {idx:2d}. {tracker_url}")
                if len(actual_trackers) > 3:
                    typer.echo(f"  ...共 {len(actual_trackers)} 个 tracker")
            else:
                typer.echo("  无 tracker 地址。")

        typer.echo("")
        typer.echo("按 Enter 切换简要/详细，按 Esc 返回。")
        key = read_key()
        if key == "ENTER":
            view_detail = not view_detail
            continue
        if key == "ESC" or key == "q":
            break


def show_dedup_details(
    opener: urllib.request.OpenerDirector, host: str, torrents_with_hash: List[Dict[str, Any]]
) -> None:
    """Show details for multiple torrents with the same pieces hash in table format"""
    while True:
        clear_screen()
        typer.echo("相同 Pieces Hash 的种子\n")
        
        width = get_terminal_width()
        hash_width = max(20, min(40, width - 60))
        tracker_width = max(30, width - hash_width - 10)
        
        typer.echo(f"{'InfoHash':{hash_width}} {'Tracker':{tracker_width}}")
        typer.echo("-" * min(width, hash_width + tracker_width + 5))
        
        for torrent in torrents_with_hash:
            torrent_hash = torrent.get("hash", "<unknown>")
            torrent_hash_display = torrent_hash[:hash_width] if torrent_hash else "<unknown>"
            
            try:
                trackers = fetch_qb_torrent_trackers(opener, host, torrent_hash)
                tracker_urls = [
                    t.get("url", "") for t in trackers if is_tracker_address(str(t.get("url", "")))
                ]
                domains = []
                seen = set()
                for url in tracker_urls:
                    domain = extract_domain_from_url(url)
                    if domain and domain not in seen:
                        domains.append(domain)
                        seen.add(domain)
                
                tracker_display = ", ".join(domains[:3]) if domains else "-"
                if len(domains) > 3:
                    tracker_display += f", ...({len(domains)} 个)"
            except Exception:
                tracker_display = "-"
            
            tracker_display = truncate_display(tracker_display, tracker_width)
            tracker_field = pad_display(tracker_display, tracker_width)
            
            typer.echo(f"{torrent_hash_display:{hash_width}} {tracker_field}")
        
        typer.echo("")
        typer.echo(f"共 {len(torrents_with_hash)} 个种子")
        typer.echo("")
        typer.echo("按 Esc 或 q 返回。")
        key = read_key()
        if key == "ESC" or key == "q":
            break


def show_deduplicated_torrents(
    opener: urllib.request.OpenerDirector, host: str, dedup_dict: Dict[str, Dict[str, Any]]
) -> None:
    """Show deduplicated torrents list with selection"""
    dedup_list = list(dedup_dict.items())
    dedup_list.sort(key=lambda x: x[1]["count"], reverse=True)
    
    page = 0
    page_size = 20
    selected = 0
    total_pages = (len(dedup_list) + page_size - 1) // page_size
    
    while True:
        page_items = dedup_list[page * page_size : min((page + 1) * page_size, len(dedup_list))]
        selected = min(selected, len(page_items) - 1)
        
        width = get_terminal_width()
        name_width = max(20, min(60, width - 30))
        
        clear_screen()
        typer.echo("Pieces 去重结果\n")
        typer.echo(f"{'Name':{name_width}} {'Count':>5} {'PiecesHash':>35}")
        typer.echo("-" * min(width, max(name_width + 42, 50)))
        
        for i, (pieces_hash, data) in enumerate(page_items):
            name = data["name"]
            name = truncate_display(name, name_width)
            name_field = pad_display(name, name_width)
            count = data["count"]
            hash_display = pieces_hash[:35] if pieces_hash != "error" else "ERROR"
            row = f"{name_field} {count:5d} {hash_display:>35}"
            
            if i == selected:
                typer.echo(f"\x1b[7m{row}\x1b[0m")
            else:
                typer.echo(row)
        
        typer.echo("")
        typer.echo(f"当前 {page + 1}/{total_pages}  总数 {len(dedup_list)}  (↑ ↓ 选择，← → 翻页，Esc 退出，Enter 查看详情)")
        
        key = read_key()
        if key == "UP":
            if selected > 0:
                selected -= 1
            elif page > 0:
                page -= 1
                selected = min(page_size - 1, len(dedup_list[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "DOWN":
            if selected < len(page_items) - 1:
                selected += 1
            elif page < total_pages - 1:
                page += 1
                selected = 0
        elif key == "LEFT":
            if page > 0:
                page -= 1
                selected = min(selected, len(dedup_list[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "RIGHT":
            if page < total_pages - 1:
                page += 1
                selected = min(selected, len(dedup_list[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "ENTER":
            _, data = page_items[selected]
            show_dedup_details(opener, host, data["torrents"])
        elif key == "ESC" or key == "q":
            break


def show_check_results(results: List[Dict[str, Any]]) -> None:
    """Show check results with pagination"""
    page = 0
    page_size = 20
    selected = 0
    total_pages = (len(results) + page_size - 1) // page_size
    
    while True:
        page_items = results[page * page_size : min((page + 1) * page_size, len(results))]
        selected = min(selected, len(page_items) - 1)
        
        width = get_terminal_width()
        name_width = max(20, min(60, width - 42))
        
        clear_screen()
        typer.echo("PT 站点查询结果\n")
        typer.echo(f"{'Name':{name_width}} {'Seed':>10} {'ID':>15}")
        typer.echo("-" * min(width, max(name_width + 27, 42)))
        
        for i, item in enumerate(page_items):
            name = truncate_display(item["name"], name_width)
            name_field = pad_display(name, name_width)
            seeding = item["seed_display"]
            torrent_id = item["torrent_id_display"]
            row = f"{name_field} {seeding:>10} {str(torrent_id):>15}"
            
            if i == selected:
                typer.echo(f"\x1b[7m{row}\x1b[0m")
            else:
                typer.echo(row)
        
        typer.echo("")
        typer.echo(f"当前 {page + 1}/{total_pages}  总数 {len(results)}  (↑ ↓ 选择，← → 翻页，Esc 退出)")
        
        key = read_key()
        if key == "UP":
            if selected > 0:
                selected -= 1
            elif page > 0:
                page -= 1
                selected = min(page_size - 1, len(results[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "DOWN":
            if selected < len(page_items) - 1:
                selected += 1
            elif page < total_pages - 1:
                page += 1
                selected = 0
        elif key == "LEFT":
            if page > 0:
                page -= 1
                selected = min(selected, len(results[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "RIGHT":
            if page < total_pages - 1:
                page += 1
                selected = min(selected, len(results[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "ESC" or key == "q":
            break


def _format_tracker_domains(domains: list[str]) -> str:
    return ", ".join(get_tracker_display_name(d) for d in domains) if domains else "-"


def show_pub_results(results: List[Dict[str, Any]]) -> None:
    """Show pub results with pagination"""
    page = 0
    page_size = 20
    selected = 0
    total_pages = (len(results) + page_size - 1) // page_size

    while True:
        page_items = results[page * page_size : min((page + 1) * page_size, len(results))]
        selected = min(selected, len(page_items) - 1)

        width = get_terminal_width()
        name_width = max(20, min(60, width - 42))
        size_width = 12
        tracker_width = max(15, width - name_width - size_width - 4)

        clear_screen()
        typer.echo("不在 PT 站点的种子\n")
        header = (
            pad_display("名称", name_width) + " "
            + pad_display("大小", size_width) + " "
            + "Tracker"
        )
        typer.echo(header)
        typer.echo("-" * min(width, name_width + size_width + tracker_width + 4))

        for i, item in enumerate(page_items):
            name = truncate_display(item["name"], name_width)
            name_field = pad_display(name, name_width)
            size = format_bytes(item["size"])
            size_field = pad_display(size, size_width)
            trackers = _format_tracker_domains(item["tracker_domains"])
            trackers = truncate_display(trackers, tracker_width)
            row = f"{name_field} {size_field} {trackers}"

            if i == selected:
                typer.echo(f"\x1b[7m{row}\x1b[0m")
            else:
                typer.echo(row)

        typer.echo("")
        has_detail = bool(results[page * page_size + selected].get("detail_url")) if results else False
        hint = "Enter 打开详情, " if has_detail else ""
        typer.echo(f"当前 {page + 1}/{total_pages}  总数 {len(results)}  ({hint}↑ ↓ 选择，← → 翻页，Esc 退出)")

        key = read_key()
        if key == "UP":
            if selected > 0:
                selected -= 1
            elif page > 0:
                page -= 1
                selected = min(page_size - 1, len(results[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "DOWN":
            if selected < len(page_items) - 1:
                selected += 1
            elif page < total_pages - 1:
                page += 1
                selected = 0
        elif key == "LEFT":
            if page > 0:
                page -= 1
                selected = min(selected, len(results[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "RIGHT":
            if page < total_pages - 1:
                page += 1
                selected = min(selected, len(results[page * page_size : (page + 1) * page_size]) - 1)
        elif key == "ENTER":
            detail_url = results[page * page_size + selected].get("detail_url")
            if detail_url:
                clear_screen()
                typer.echo("种子详情页 URL（可鼠标选中复制）:\n")
                typer.echo(f"  {detail_url}\n")
                try:
                    webbrowser.open(detail_url)
                except Exception:
                    pass
                typer.echo("按任意键返回列表...")
                read_key()
        elif key == "ESC" or key == "q":
            break
