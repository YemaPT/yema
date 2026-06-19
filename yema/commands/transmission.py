from __future__ import annotations

from typing import Any, Dict

import typer

from yema.clients.transmission import (
    create_transmission_client,
    fetch_transmission_torrent_tracker_urls,
    fetch_transmission_torrents,
    get_transmission_settings,
    resolve_transmission_pieces_hash,
)
from yema.config.utils import is_debug_enabled
from yema.core.formatting import render_page
from yema.core.terminal import clear_screen, read_key
from yema.services.torrents import collect_pt_check_results, get_check_result_sort_key
from yema.ui.screens import show_check_results


def _get_transmission_context() -> tuple[Dict[str, str], Any, list[Dict[str, Any]]]:
    debug = is_debug_enabled()
    tr = get_transmission_settings()
    if debug:
        typer.echo(f"[DEBUG] Transmission 配置读取完成: host={tr['host']}, filesystem={tr['filesystem']}")
        typer.echo("[DEBUG] Transmission 开始连接并校验 RPC")
    client = create_transmission_client(tr["host"], tr["username"], tr["password"])
    if debug:
        typer.echo("[DEBUG] Transmission RPC 校验通过，开始获取种子列表")
    torrents = fetch_transmission_torrents(client)
    if debug:
        typer.echo(f"[DEBUG] Transmission 种子列表获取完成: count={len(torrents)}")
    for torrent in torrents:
        torrent["source"] = "tr"
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)
    return tr, client, torrents


def list_torrents() -> None:
    _, _, torrents = _get_transmission_context()
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
        elif key == "ESC" or key == "q":
            break


def check_torrents() -> None:
    tr, _, torrents = _get_transmission_context()
    if not torrents:
        typer.echo("当前没有种子。")
        return

    clear_screen()
    typer.echo("正在检查 Transmission 种子信息...\n")
    debug = is_debug_enabled()
    if debug:
        typer.echo(f"[DEBUG] Transmission check 开始: host={tr['host']}, filesystem={tr['filesystem']}, count={len(torrents)}")
    results = collect_pt_check_results(
        None,
        tr["host"],
        torrents,
        debug,
        pieces_hash_resolver=lambda torrent: resolve_transmission_pieces_hash(
            torrent,
            tr["filesystem"],
            tr.get("path_mappings", []),
        ),
        tracker_url_fetcher=fetch_transmission_torrent_tracker_urls,
    )

    if debug:
        found_count = sum(1 for item in results if item["torrent_id"] is not None)
        typer.echo(f"[DEBUG] 最终统计 - 在 PT 站点找到: {found_count}/{len(results)}")

    show_check_results(sorted(results, key=get_check_result_sort_key))


def transmission_command() -> None:
    selected = 0
    items = {
        "list": "查看当前种子列表",
        "check": "检查种子是否已被 yemapt 收录",
        "exit": "退出 Transmission 菜单",
    }
    while True:
        clear_screen()
        typer.echo("Transmission 操作菜单：使用 ↑ ↓ 选择，按回车确认，按 Esc 退出。\n")
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
                check_torrents()
            else:
                return
