from __future__ import annotations

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
from yema.clients.transmission import (
    add_transmission_torrent,
    create_transmission_client,
    delete_transmission_torrents,
    fetch_transmission_torrent_tracker_urls,
    fetch_transmission_torrents,
    get_transmission_settings,
    resolve_transmission_pieces_hash,
)
from yema.clients.yemapt import download_torrent_from_pt, fetch_torrent_ids_from_pt
from yema.config.utils import is_debug_enabled, load_settings
from yema.core.debug import get_exception_message
from yema.core.formatting import render_page
from yema.core.terminal import clear_screen, read_key
from yema.domain.trackers import extract_domain_from_url, get_tracker_display_name
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
    save_pt_pieces_to_cache,
)
from yema.ui.screens import show_check_results, show_deduplicated_torrents, show_pub_results, show_torrent_details


def _has_qb_config(settings: Dict[str, Any]) -> bool:
    qb = settings.get("qb", {})
    return isinstance(qb, dict) and bool(qb.get("host") and qb.get("username") and qb.get("password"))


def _has_transmission_config(settings: Dict[str, Any]) -> bool:
    clients = settings.get("clients", {})
    tr = clients.get("transmission", {}) if isinstance(clients, dict) else {}
    if not tr:
        tr = settings.get("transmission", {})
    return isinstance(tr, dict) and bool(tr.get("host") and tr.get("filesystem"))


def _normalize_source_client(client: str | None) -> str | None:
    if client is None:
        return None
    value = client.strip().lower()
    if value in {"qb", "qbittorrent"}:
        return "qb"
    if value in {"tr", "transmission"}:
        return "tr"
    raise typer.Exit(code=1, message="--client 仅支持 qb 或 tr。")


def _matches_tracker(tracker_url: str, tracker: str) -> bool:
    target = tracker.strip().lower()
    if not target:
        return True
    url = tracker_url.lower()
    domain = extract_domain_from_url(tracker_url).lower()
    display_name = get_tracker_display_name(domain).lower()
    return target in url or target in domain or target in display_name


def _filter_torrents_by_tracker(
    torrents: List[Dict[str, Any]],
    tracker: str | None,
    tracker_url_fetcher: Any,
) -> List[Dict[str, Any]]:
    if not tracker or not tracker.strip():
        return torrents

    matched = []
    for torrent in torrents:
        try:
            tracker_urls = tracker_url_fetcher(torrent)
        except Exception:
            tracker_urls = []
        if any(_matches_tracker(url, tracker) for url in tracker_urls):
            matched.append(torrent)
    return matched


def _select_sources(command_name: str, client: str | None = None, auto_all: bool = False) -> List[str]:
    settings = load_settings()
    configured = []
    if _has_qb_config(settings):
        configured.append("qb")
    if _has_transmission_config(settings):
        configured.append("tr")

    if not configured:
        raise typer.Exit(code=1, message="未配置下载软件，请先运行 yema init 设置 qBittorrent 或 Transmission。")

    selected_client = _normalize_source_client(client)
    if selected_client:
        if selected_client not in configured:
            label = "qBittorrent" if selected_client == "qb" else "Transmission"
            raise typer.Exit(code=1, message=f"未配置 {label}，请先运行 yema init 设置。")
        return [selected_client]

    if len(configured) == 1:
        return configured
    if auto_all:
        return configured

    selected = 0
    items = [("all", "全部"), ("qb", "qBittorrent"), ("tr", "Transmission")]
    while True:
        clear_screen()
        typer.echo(f"{command_name} 来源选择：使用 ↑ ↓ 选择，按回车确认，按 Esc 取消。\n")
        for index, (_, label) in enumerate(items):
            prefix = "▶" if index == selected else "  "
            if index == selected:
                typer.secho(f"{prefix} {label}", fg="cyan")
            else:
                typer.echo(f"{prefix} {label}")
        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(items)
        elif key == "DOWN":
            selected = (selected + 1) % len(items)
        elif key == "ENTER":
            value = items[selected][0]
            return configured if value == "all" else [value]
        elif key == "ESC" or key == "q":
            typer.echo("已取消操作。")
            raise typer.Exit(code=0)


def _get_qb_context() -> Dict[str, Any]:
    qb = get_qb_settings()
    opener = create_qb_opener(qb["host"], qb["username"], qb["password"])
    torrents = fetch_qb_torrents(opener, qb["host"])
    for torrent in torrents:
        torrent["source"] = "qb"
    torrents.sort(key=lambda item: item.get("added_on", 0), reverse=True)
    return {
        "source": "qb",
        "host": qb["host"],
        "opener": opener,
        "torrents": torrents,
        "tracker_url_fetcher": lambda torrent: fetch_cached_qb_torrent_tracker_urls(opener, qb["host"], torrent.get("hash")),
        "get_save_path": lambda torrent: get_torrent_save_path(opener, qb["host"], torrent),
        "delete": lambda info_hashes: delete_qb_torrents(opener, qb["host"], info_hashes),
        "add": lambda torrent_data, save_path, category=None: add_qb_torrent(
            opener, qb["host"], torrent_data, save_path, category=category
        ),
    }


def _get_transmission_context() -> Dict[str, Any]:
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
    return {
        "source": "tr",
        "host": tr["host"],
        "filesystem": tr["filesystem"],
        "opener": None,
        "client": client,
        "torrents": torrents,
        "pieces_hash_resolver": lambda torrent: resolve_transmission_pieces_hash(
            torrent,
            tr["filesystem"],
            tr.get("path_mappings", []),
        ),
        "tracker_url_fetcher": fetch_transmission_torrent_tracker_urls,
        "get_save_path": lambda torrent: str(torrent.get("save_path") or ""),
        "delete": lambda info_hashes: delete_transmission_torrents(client, info_hashes),
        "add": lambda torrent_data, save_path, category=None: add_transmission_torrent(client, torrent_data, save_path),
    }


def _get_source_contexts(command_name: str, client: str | None = None, auto_all: bool = False) -> List[Dict[str, Any]]:
    contexts = []
    for source in _select_sources(command_name, client=client, auto_all=auto_all):
        if source == "qb":
            contexts.append(_get_qb_context())
        elif source == "tr":
            contexts.append(_get_transmission_context())
    return contexts


def _ensure_yemapt_auth() -> None:
    settings = load_settings()
    yemapt = settings.get("yemapt", {})
    auth = yemapt.get("auth") if isinstance(yemapt, dict) else None
    if not auth:
        auth = settings.get("yemapt_auth")
    if not auth:
        raise typer.Exit(code=1, message="未配置 yemapt auth，请先运行 yema init 设置。")

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


def _is_torrent_completed(torrent: Dict[str, Any]) -> bool:
    try:
        return float(torrent.get("progress", 0)) >= 1
    except (TypeError, ValueError):
        return False


def _collect_pub_torrents(
    client: str | None = None,
    tracker: str | None = None,
    progress_to_stderr: bool = False,
    completed_only: bool = False,
) -> List[Dict[str, Any]]:
    _ensure_yemapt_auth()
    contexts = _get_source_contexts("pub", client=client)
    debug = is_debug_enabled()
    not_on_pt = []

    for context in contexts:
        torrents = context["torrents"]
        torrents = _filter_torrents_by_tracker(torrents, tracker, context["tracker_url_fetcher"])
        if completed_only:
            torrents = [torrent for torrent in torrents if _is_torrent_completed(torrent)]
        if not torrents:
            if tracker and tracker.strip():
                empty_text = f"当前没有匹配 tracker={tracker} 的种子"
            elif completed_only:
                empty_text = "当前没有已下载完成的种子"
            else:
                empty_text = "当前没有种子"
            typer.echo(f"{context['source']} {empty_text}。", err=progress_to_stderr)
            continue

        typer.echo(f"获取 {context['source']} pieces hash...", err=progress_to_stderr)
        pieces_hashes = fetch_all_torrents_pieces_hashes(
            context["opener"],
            context["host"],
            torrents,
            context.get("pieces_hash_resolver"),
            debug,
            progress_to_stderr,
        )

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
                typer.echo(
                    f"\r查询 PT 站点... {min(i + 100, len(to_query))}/{len(to_query)}",
                    nl=False,
                    err=progress_to_stderr,
                )
                try:
                    batch_result = fetch_torrent_ids_from_pt(batch, debug=debug)
                    pt_results.update(batch_result)
                    for ph in batch:
                        save_pt_pieces_to_cache(ph, batch_result.get(ph))
                except typer.Exit as e:
                    typer.echo(f"\nPT 查询失败: {e.message or str(e)}", err=True)
                except Exception as e:
                    if debug:
                        typer.echo(f"[DEBUG] 批次 {batch_idx}/{batch_count} 查询失败: {e}")
            typer.echo("", err=progress_to_stderr)

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
                tracker_urls = context["tracker_url_fetcher"](torrent)
                seen = set()
                for url in tracker_urls:
                    domain = extract_domain_from_url(url)
                    if domain and domain not in seen:
                        seen.add(domain)
                        tracker_domains.append(domain)
            except Exception:
                pass

            is_completed = _is_torrent_completed(torrent)
            detail_url = None
            if is_completed:
                detail_url = get_torrent_detail_url(context["opener"], context["host"], info_hash, tracker_urls)

            not_on_pt.append({
                "source": context["source"],
                "name": torrent.get("name", "<unknown>"),
                "size": torrent.get("size", 0),
                "progress": torrent.get("progress", 0),
                "is_completed": is_completed,
                "tracker_domains": tracker_domains,
                "detail_url": detail_url,
            })

    return not_on_pt


def pub_torrents(client: str | None = None, urls: bool = False, tracker: str | None = None):
    """列出下载软件上不在 PT 站点的种子"""
    not_on_pt = _collect_pub_torrents(
        client=client,
        tracker=tracker,
        progress_to_stderr=urls,
        completed_only=urls,
    )
    if urls:
        seen = set()
        for item in not_on_pt:
            detail_url = item.get("detail_url")
            if not detail_url or detail_url in seen:
                continue
            seen.add(detail_url)
            typer.echo(detail_url)
        return

    if not not_on_pt:
        typer.echo("所有种子都在 PT 站点上。")
        return

    show_pub_results(not_on_pt)


def check_torrents():
    """Check torrents against PT site"""
    _ensure_yemapt_auth()
    contexts = _get_source_contexts("check")
    
    clear_screen()
    typer.echo("正在检查种子信息...\n")
    
    debug = is_debug_enabled()
    results = []
    for context in contexts:
        torrents = context["torrents"]
        if not torrents:
            typer.echo(f"{context['source']} 当前没有种子。")
            continue
        if debug:
            typer.echo(
                "[DEBUG] check 来源开始: "
                f"source={context['source']}, "
                f"host={context['host']}, "
                f"filesystem={context.get('filesystem', '-')}, "
                f"count={len(torrents)}"
            )
        results.extend(collect_pt_check_results(
            context["opener"],
            context["host"],
            torrents,
            debug,
            pieces_hash_resolver=context.get("pieces_hash_resolver"),
            tracker_url_fetcher=context.get("tracker_url_fetcher"),
        ))

    if not results:
        typer.echo("当前没有可检查的种子。")
        return
    
    if debug:
        found_count = sum(1 for r in results if r["torrent_id"] is not None)
        typer.echo(f"[DEBUG] 最终统计 - 在 PT 站点找到: {found_count}/{len(results)}")

    show_check_results(sorted(results, key=get_check_result_sort_key))


def seed_torrents(
    yes: bool = False,
    client: str | None = None,
    tracker: str | None = None,
    category: str | None = None,
):
    _ensure_yemapt_auth()
    contexts = _get_source_contexts("seed", client=client, auto_all=yes)

    clear_screen()
    typer.echo("正在分析可补种项目...\n")
    debug = is_debug_enabled()
    results = []
    context_by_source = {context["source"]: context for context in contexts}
    for context in contexts:
        torrents = context["torrents"]
        torrents = _filter_torrents_by_tracker(torrents, tracker, context["tracker_url_fetcher"])
        if not torrents:
            if tracker and tracker.strip():
                typer.echo(f"{context['source']} 当前没有匹配 tracker={tracker} 的种子。")
            else:
                typer.echo(f"{context['source']} 当前没有种子。")
            continue
        if debug:
            typer.echo("[DEBUG] seed 流程开始")
            typer.echo(f"[DEBUG] source: {context['source']}")
            typer.echo(f"[DEBUG] host: {context['host']}")
            typer.echo(f"[DEBUG] 总种子数: {len(torrents)}")
        results.extend(collect_pt_check_results(
            context["opener"],
            context["host"],
            torrents,
            debug,
            pieces_hash_resolver=context.get("pieces_hash_resolver"),
            tracker_url_fetcher=context.get("tracker_url_fetcher"),
        ))

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
        context = context_by_source[item["source"]]
        seed_action = "已有做种替换" if item["replace_info_hashes"] else "新下载"
        seed_user = "当前用户" if item["current_user_seeding"] else (
            ",".join(item["foreign_user_ids"]) if item["foreign_user_ids"] else "-"
        )
        save_path = context["get_save_path"](item["torrents"][0])
        if debug:
            typer.echo(
                "[DEBUG] 准备处理候选: "
                f"index={index}, "
                f"name={item['name']}, "
                f"action={seed_action}, "
                f"save_path={save_path}"
            )

        typer.echo("")
        typer.echo(f"[{index}/{len(candidates)}] [{item['source']}] {item['name']}")
        typer.echo(f"  操作: {seed_action}")
        typer.echo(f"  PT ID: {item['torrent_id_display']}")
        typer.echo(f"  当前做种: {item['seed_display']}")
        typer.echo(f"  做种用户: {seed_user}")
        typer.echo(f"  保存路径: {save_path}")
        if category and item["source"] == "qb":
            typer.echo(f"  类目: {category}")
        if item["replace_info_hashes"]:
            typer.echo(f"  待删除 infohash: {', '.join(item['replace_info_hashes'])}")

        if yes:
            typer.echo("  自动确认: 是")
        elif not typer.confirm("是否执行该操作？", default=False):
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
                context["delete"](item["replace_info_hashes"])
                delete_tracker_cache_entries(item["replace_info_hashes"])
                if debug:
                    typer.echo(f"[DEBUG] 已清理旧做种 tracker 缓存: {item['replace_info_hashes']}")
                typer.echo("已删除旧的做种条目（保留文件）。")
            if debug:
                typer.echo(f"[DEBUG] 开始向 {item['source']} 添加新种: {item['name']}")
            context["add"](torrent_data, save_path, category)
            if debug:
                typer.echo(f"[DEBUG] {item['source']} 添加新种完成: {item['name']}")
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
