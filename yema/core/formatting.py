import shutil
from datetime import datetime
from typing import Any, Dict, List

import typer
from wcwidth import wcwidth, wcswidth

from .terminal import clear_screen

STATE_TRANSLATION = {
    "allocating": "分配中",
    "downloading": "下载中",
    "metaDL": "获取元数据中",
    "forcedDL": "强制下载",
    "uploading": "上传中",
    "forcedUP": "强制上传",
    "queuedForChecking": "等待检查",
    "checkingUploadResume": "检查恢复",
    "checkingDL": "检查下载",
    "checkingResumeData": "检查恢复数据",
    "paused_DL": "暂停（下载中）",
    "paused_UP": "暂停（上传中）",
    "stalledUP": "卡住（上传）",
    "stalledDL": "卡住（下载）",
    "error": "错误",
    "missingFiles": "缺少文件",
    "unknown": "未知",
}

def translate_state(state: str) -> str:
    return STATE_TRANSLATION.get(state, state)


def get_terminal_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size(fallback=(default, 24)).columns
    except OSError:
        return default


def get_display_width(text: str) -> int:
    width = wcswidth(text)
    return width if width >= 0 else len(text)


def truncate_display(text: str, max_width: int) -> str:
    if get_display_width(text) <= max_width:
        return text
    ellipsis = "…"
    ellipsis_width = get_display_width(ellipsis)
    truncated = ""
    current_width = 0
    for ch in text:
        ch_width = wcwidth(ch)
        if ch_width < 0:
            ch_width = 0
        if current_width + ch_width + ellipsis_width > max_width:
            return truncated + ellipsis
        truncated += ch
        current_width += ch_width
    return truncated


def pad_display(text: str, width: int) -> str:
    current_width = get_display_width(text)
    if current_width >= width:
        return text
    return text + " " * (width - current_width)


def format_torrent(item: Dict[str, Any], name_width: int, show_added: bool) -> str:
    name = item.get("name", "<unknown>")
    name = truncate_display(name, name_width)
    name_field = pad_display(name, name_width)
    state = translate_state(item.get("state", "unknown"))
    state = truncate_display(state, 12)
    state_field = pad_display(state, 12)
    progress = item.get("progress", 0.0) * 100
    size = item.get("size", 0)
    size_str = f"{size / (1024**3):.2f}G" if size else "0B"
    ratio = item.get("ratio", 0.0)
    added_on = item.get("added_on")
    added_str = datetime.fromtimestamp(added_on).strftime("%Y-%m-%d %H:%M") if added_on else "-"
    if show_added:
        return f"{name_field} {state_field} {progress:6.1f}% {ratio:5.2f} {size_str:8} {added_str:16}"
    return f"{name_field} {state_field} {progress:6.1f}% {ratio:5.2f} {size_str:8}"


def render_torrent_line(index: int, item: Dict[str, Any], name_width: int, show_added: bool, selected: bool) -> str:
    line = format_torrent(item, name_width, show_added)
    row = f"{index:3d}. {line}"
    if selected:
        return f"\x1b[7m{row}\x1b[0m"
    return row


def render_page(items: List[Dict[str, Any]], page: int, page_size: int, selected: int) -> None:
    width = get_terminal_width()
    total_pages = (len(items) + page_size - 1) // page_size
    start = page * page_size
    end = min(start + page_size, len(items))
    page_items = items[start:end]
    show_added = width >= 95
    name_width = max(20, min(60, width - (55 if show_added else 41)))

    clear_screen()
    typer.echo("qBittorrent 种子列表\n")
    state_header = pad_display("State", 12)
    if show_added:
        typer.echo(f"{'Name':{name_width}} {state_header} {'Prog':>6} {'Ratio':>5} {'Size':>8} {'Added':>16}")
    else:
        typer.echo(f"{'Name':{name_width}} {state_header} {'Prog':>6} {'Ratio':>5} {'Size':>8}")
    typer.echo("-" * min(width, max(name_width + (55 if show_added else 41), 50)))
    for i, item in enumerate(page_items):
        absolute_index = start + i + 1
        typer.echo(render_torrent_line(absolute_index, item, name_width, show_added, i == selected))
    typer.echo("")
    typer.echo(f"当前 {page + 1}/{total_pages}  总数 {len(items)}  (↑ ↓ 选择，← → 翻页，Esc 退出，Enter 查看详情)")


def format_timestamp(value: Any) -> str:
    if value is None:
        return "-"
    try:
        timestamp = int(value)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def format_duration(seconds: Any) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def format_bytes(num: Any) -> str:
    try:
        num = int(num)
    except (TypeError, ValueError):
        return str(num)
    if num < 1024:
        return f"{num} B"
    for unit in ["KB", "MB", "GB", "TB"]:
        num /= 1024.0
        if num < 1024:
            return f"{num:.1f} {unit}"
    return f"{num:.1f} PB"
