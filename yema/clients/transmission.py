from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

import typer

from yema.config.utils import is_debug_enabled, load_settings
from yema.domain.trackers import is_tracker_address
from yema.domain.torrent_files import calc_pieces_hash_from_torrent_data
from yema.filesystems.base import create_filesystem, get_filesystem_settings
from yema.storage.cache import get_cached_pieces_hash, save_pieces_to_cache

TRANSMISSION_RPC_PATH = "/transmission/rpc"


def get_transmission_settings() -> Dict[str, Any]:
    settings = load_settings()
    clients = settings.get("clients", {})
    tr = {}
    if isinstance(clients, dict):
        tr = clients.get("transmission", {}) or clients.get("tr", {})
    if not tr:
        tr = settings.get("transmission", {})
    host = tr.get("host")
    if not host:
        raise typer.Exit(code=1, message="未配置 Transmission，请先运行 yema init 设置 host。")
    filesystem = tr.get("filesystem")
    if not filesystem:
        raise typer.Exit(code=1, message="Transmission 未选择文件系统，请先运行 yema init 设置。")
    return {
        "host": str(host),
        "username": str(tr.get("username") or ""),
        "password": str(tr.get("password") or ""),
        "filesystem": str(filesystem),
        "path_mappings": tr.get("path_mappings") if isinstance(tr.get("path_mappings"), list) else [],
    }


class TransmissionClient:
    def __init__(self, host: str, username: str = "", password: str = "") -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.session_id = ""

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "yema",
        }
        if self.session_id:
            headers["X-Transmission-Session-Id"] = self.session_id
        if self.username or self.password:
            token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def call(self, method: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.host}{TRANSMISSION_RPC_PATH}"
        body = json.dumps({"method": method, "arguments": arguments or {}}, ensure_ascii=False).encode("utf-8")
        for _ in range(2):
            request = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                session_id = exc.headers.get("X-Transmission-Session-Id")
                if exc.code == 409 and session_id:
                    self.session_id = session_id
                    continue
                raise typer.Exit(code=1, message=f"请求 Transmission 失败: {exc.code} {exc.reason}")
            except urllib.error.URLError as exc:
                raise typer.Exit(code=1, message=f"无法连接到 Transmission: {exc.reason}")
        raise typer.Exit(code=1, message="请求 Transmission 失败: session id negotiation failed")


def create_transmission_client(host: str, username: str = "", password: str = "") -> TransmissionClient:
    client = TransmissionClient(host, username, password)
    result = client.call("session-get")
    if result.get("result") != "success":
        raise typer.Exit(code=1, message=f"Transmission 登录验证失败: {result.get('result')}")
    return client


def fetch_transmission_torrents(client: TransmissionClient) -> List[Dict[str, Any]]:
    fields = [
        "id",
        "name",
        "hashString",
        "totalSize",
        "addedDate",
        "percentDone",
        "uploadRatio",
        "uploadedEver",
        "downloadDir",
        "trackerStats",
        "torrentFile",
    ]
    result = client.call("torrent-get", {"fields": fields})
    if result.get("result") != "success":
        raise typer.Exit(code=1, message=f"获取 Transmission 种子失败: {result.get('result')}")
    torrents = result.get("arguments", {}).get("torrents", [])
    normalized = []
    for torrent in torrents:
        normalized.append({
            "id": torrent.get("id"),
            "hash": str(torrent.get("hashString", "")).lower(),
            "name": torrent.get("name", "<unknown>"),
            "size": torrent.get("totalSize", 0),
            "added_on": torrent.get("addedDate", 0),
            "progress": torrent.get("percentDone", 0.0),
            "ratio": torrent.get("uploadRatio", 0.0),
            "uploaded": torrent.get("uploadedEver", 0),
            "save_path": torrent.get("downloadDir", ""),
            "trackerStats": torrent.get("trackerStats", []),
            "torrent_file": torrent.get("torrentFile", ""),
        })
    return normalized


def fetch_transmission_torrent_tracker_urls(torrent: Dict[str, Any]) -> List[str]:
    urls = []
    for tracker in torrent.get("trackerStats", []) or []:
        announce = str(tracker.get("announce") or "")
        if is_tracker_address(announce):
            urls.append(announce)
    return urls


def delete_transmission_torrents(client: TransmissionClient, info_hashes: List[str]) -> None:
    if not info_hashes:
        return
    result = client.call("torrent-remove", {"ids": info_hashes, "delete-local-data": False})
    if result.get("result") != "success":
        raise RuntimeError(f"删除 Transmission 种子失败: {result.get('result')}")


def add_transmission_torrent(client: TransmissionClient, torrent_data: bytes, save_path: str) -> None:
    metainfo = base64.b64encode(torrent_data).decode("ascii")
    result = client.call(
        "torrent-add",
        {
            "metainfo": metainfo,
            "download-dir": save_path,
            "paused": False,
        },
    )
    if result.get("result") not in {"success", "duplicate torrent"}:
        raise RuntimeError(f"添加 Transmission 种子失败: {result.get('result')}")


def apply_path_mappings(path: str, mappings: List[Dict[str, str]]) -> str:
    if not path:
        return path
    for mapping in mappings:
        source = str(mapping.get("from") or "").rstrip("/") or "/"
        target = str(mapping.get("to") or "").rstrip("/") or "/"
        if source == "/":
            if path.startswith("/"):
                return target.rstrip("/") + path
            return path
        if path == source or path.startswith(source + "/"):
            suffix = path[len(source) :]
            return target + suffix
    return path


def exit_with_filesystem_directory_preview(filesystem_id: str, fs: Any, errors: List[str]) -> None:
    typer.echo("无法按 Transmission 返回路径读取种子文件。")
    typer.echo(f"文件系统: {filesystem_id}")
    if errors:
        typer.echo("读取失败路径:")
        for error in errors:
            typer.echo(f"  {error}")

    typer.echo("用户配置目录下的前 20 个目录:")
    try:
        directories = fs.list_directories(20)
    except Exception as exc:
        typer.echo(f"  目录列表读取失败: {exc}")
        raise typer.Exit(code=1)

    if not directories:
        typer.echo("  (未找到目录)")
    else:
        for path in directories:
            typer.echo(f"  {path}")
    raise typer.Exit(code=1)


def resolve_transmission_pieces_hash(
    torrent: Dict[str, Any],
    filesystem_id: str,
    path_mappings: List[Dict[str, str]] | None = None,
) -> str:
    info_hash = str(torrent.get("hash") or "").lower()
    debug = is_debug_enabled()
    torrent_name = str(torrent.get("name") or "<unknown>")
    if not info_hash:
        if debug:
            typer.echo(f"[DEBUG] Transmission pieces hash 跳过：缺少 infohash, name={torrent_name}")
        return "error"

    cached = get_cached_pieces_hash(info_hash)
    if cached is not None:
        if debug:
            typer.echo(f"[DEBUG] Transmission pieces hash 缓存命中: name={torrent_name}, info_hash={info_hash}")
        return cached

    if debug:
        typer.echo(
            "[DEBUG] Transmission pieces hash 准备读取 .torrent: "
            f"name={torrent_name}, "
            f"info_hash={info_hash}, "
            f"filesystem={filesystem_id}, "
            f"torrent_file={torrent.get('torrent_file') or '-'}"
        )
    fs = create_filesystem(get_filesystem_settings(filesystem_id))
    torrent_file = str(torrent.get("torrent_file") or "")
    candidates = []
    if torrent_file:
        mapped = apply_path_mappings(torrent_file, path_mappings or [])
        candidates.append(mapped)
        if mapped != torrent_file:
            candidates.append(torrent_file)
    if debug:
        typer.echo(f"[DEBUG] Transmission .torrent 候选路径数: {len(candidates)}")
        for index, path in enumerate(candidates, 1):
            typer.echo(f"[DEBUG] Transmission .torrent 候选 {index}: {path}")

    errors = []
    for path in candidates:
        try:
            if debug:
                typer.echo(f"[DEBUG] Transmission 开始读取 .torrent: {path}")
            torrent_data = fs.read_file(path)
            if debug:
                typer.echo(f"[DEBUG] Transmission .torrent 读取完成: {path}, bytes={len(torrent_data)}")
            pieces_hash = calc_pieces_hash_from_torrent_data(torrent_data)
            if debug:
                typer.echo(f"[DEBUG] Transmission pieces hash 计算完成: info_hash={info_hash}, pieces_hash={pieces_hash}")
            save_pieces_to_cache(info_hash, pieces_hash)
            return pieces_hash
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            if debug:
                typer.echo(f"[DEBUG] 读取 Transmission 种子文件失败: {path}: {exc}")
            continue
    if debug:
        typer.echo(f"[DEBUG] Transmission 按候选路径读取失败，展示文件系统目录并退出: {info_hash}")
    if not candidates:
        errors.append("Transmission 未返回 torrentFile，无法生成候选路径。")
    exit_with_filesystem_directory_preview(filesystem_id, fs, errors)
