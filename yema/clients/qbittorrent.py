from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List

import typer

from yema.config.utils import is_debug_enabled, load_settings
from yema.core.debug import debug_http_dump
from yema.domain.trackers import is_tracker_address
from yema.storage.cache import get_valid_tracker_cache_entry, load_qb_torrent_cache, save_qb_torrent_cache

QB_TORRENTS_INFO_PATH = "/api/v2/torrents/info"

def get_qb_settings() -> Dict[str, str]:
    settings = load_settings()
    qb = settings.get("qb", {})
    host = qb.get("host")
    username = qb.get("username")
    password = qb.get("password")
    if not host or not username or not password:
        raise typer.Exit(code=1, message="未配置 qBittorrent，请先运行 yema init 设置 host/username/password。")
    return {"host": host, "username": username, "password": password}


def create_qb_opener(host: str, username: str, password: str) -> urllib.request.OpenerDirector:
    host = host.rstrip("/")
    login_url = f"{host}/api/v2/auth/login"
    data = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
    cookiejar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    request = urllib.request.Request(
        login_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    debug = is_debug_enabled()
    if debug:
        typer.echo(f"[DEBUG] qBittorrent 登录 URL: {login_url}")
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            if debug:
                typer.echo(f"[DEBUG] qBittorrent 登录响应: {body}")
            if body.strip() != "Ok.":
                raise typer.Exit(code=1, message=f"qBittorrent 登录失败，响应：{body}")
    except urllib.error.HTTPError as exc:
        if debug:
            typer.echo(f"[DEBUG] qBittorrent 登录 HTTPError: {exc.code} {exc.reason}")
        raise typer.Exit(code=1, message=f"请求 qBittorrent 失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        if debug:
            typer.echo(f"[DEBUG] qBittorrent 登录 URLError: {exc.reason}")
        raise typer.Exit(code=1, message=f"无法连接到 qBittorrent: {exc.reason}")
    return opener


def fetch_qb_torrents(opener: urllib.request.OpenerDirector, host: str) -> List[Dict[str, Any]]:
    host = host.rstrip("/")
    url = f"{host}{QB_TORRENTS_INFO_PATH}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "python-urllib/3"},
    )
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        raise typer.Exit(code=1, message=f"请求 qBittorrent 列表失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise typer.Exit(code=1, message=f"无法连接到 qBittorrent: {exc.reason}")


def fetch_qb_torrent_properties(opener: urllib.request.OpenerDirector, host: str, torrent_hash: str) -> Dict[str, Any]:
    host = host.rstrip("/")
    url = f"{host}/api/v2/torrents/properties?hash={urllib.parse.quote(torrent_hash)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "python-urllib/3"})
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        raise typer.Exit(code=1, message=f"请求 qBittorrent properties 失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise typer.Exit(code=1, message=f"无法连接到 qBittorrent: {exc.reason}")


def fetch_qb_torrent_trackers(opener: urllib.request.OpenerDirector, host: str, torrent_hash: str) -> List[Dict[str, Any]]:
    host = host.rstrip("/")
    url = f"{host}/api/v2/torrents/trackers?hash={urllib.parse.quote(torrent_hash)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "python-urllib/3"})
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        raise typer.Exit(code=1, message=f"请求 qBittorrent trackers 失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise typer.Exit(code=1, message=f"无法连接到 qBittorrent: {exc.reason}")


def fetch_cached_qb_torrent_tracker_urls(
    opener: urllib.request.OpenerDirector, host: str, info_hash: str
) -> List[str]:
    import time

    is_cached, tracker_urls = get_valid_tracker_cache_entry(info_hash)
    if is_cached:
        return tracker_urls

    trackers = fetch_qb_torrent_trackers(opener, host, info_hash)
    tracker_urls = [str(t.get("url", "")) for t in trackers if is_tracker_address(str(t.get("url", "")))]

    cache = load_qb_torrent_cache()
    entry = cache.get(info_hash, {})
    entry["tracker"] = tracker_urls
    entry["trackerTimestamp"] = int(time.time())
    cache[info_hash] = entry
    save_qb_torrent_cache(cache)
    return tracker_urls


def fetch_qb_torrent_piece_hashes(opener: urllib.request.OpenerDirector, host: str, torrent_hash: str) -> List[str]:
    host = host.rstrip("/")
    url = f"{host}/api/v2/torrents/pieceHashes?hash={urllib.parse.quote(torrent_hash)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "python-urllib/3"})
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        raise typer.Exit(code=1, message=f"请求 qBittorrent pieceHashes 失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise typer.Exit(code=1, message=f"无法连接到 qBittorrent: {exc.reason}")


def delete_qb_torrents(opener: urllib.request.OpenerDirector, host: str, info_hashes: List[str]) -> None:
    if not info_hashes:
        return
    debug = is_debug_enabled()
    host = host.rstrip("/")
    url = f"{host}/api/v2/torrents/delete"
    data = urllib.parse.urlencode({
        "hashes": "|".join(info_hashes),
        "deleteFiles": "false",
    }).encode("utf-8")
    request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if debug:
        typer.echo(f"[DEBUG] 删除 qB 种子 infohash 数量: {len(info_hashes)}")
        typer.echo(f"[DEBUG] 删除 qB 种子 infohash 列表: {', '.join(info_hashes)}")
        debug_http_dump("qB 删除", method="POST", url=url, headers=request_headers, body=data)
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST",
    )
    try:
        with opener.open(request, timeout=20) as response:
            response_body = response.read().decode("utf-8", errors="ignore")
            if debug:
                debug_http_dump(
                    "qB 删除",
                    method="POST",
                    url=url,
                    headers=request_headers,
                    body=data,
                    response=response,
                    response_body=response_body,
                )
    except urllib.error.HTTPError as exc:
        if debug:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            debug_http_dump(
                "qB 删除",
                method="POST",
                url=url,
                headers=request_headers,
                body=data,
                response=exc,
                response_body=error_body,
                error=exc,
            )
        raise RuntimeError(f"删除 qB 种子失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        if debug:
            debug_http_dump("qB 删除", method="POST", url=url, headers=request_headers, body=data, error=exc)
        raise RuntimeError(f"无法连接到 qBittorrent: {exc.reason}")


def add_qb_torrent(
    opener: urllib.request.OpenerDirector,
    host: str,
    torrent_data: bytes,
    save_path: str,
    category: str | None = None,
) -> None:
    debug = is_debug_enabled()
    host = host.rstrip("/")
    url = f"{host}/api/v2/torrents/add"
    boundary = f"----yema-{uuid.uuid4().hex}"
    body = bytearray()

    def add_text_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="torrents"; filename="seed.torrent"\r\n')
    body.extend(b"Content-Type: application/x-bittorrent\r\n\r\n")
    body.extend(torrent_data)
    body.extend(b"\r\n")
    add_text_field("savepath", save_path)
    add_text_field("skip_checking", "true")
    if category:
        add_text_field("category", category)
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "text/plain, */*",
        "User-Agent": "python-urllib/3",
    }
    if debug:
        typer.echo(f"[DEBUG] 添加 qB 种子保存路径: {save_path}")
        typer.echo(f"[DEBUG] 添加 qB 种子 skip_checking: true")
        if category:
            typer.echo(f"[DEBUG] 添加 qB 种子类目: {category}")
        typer.echo(f"[DEBUG] 添加 qB 种子文件字节数: {len(torrent_data)}")
        typer.echo(f"[DEBUG] 添加 qB 请求体字节数: {len(body)}")
        debug_http_dump("qB 添加", method="POST", url=url, headers=request_headers, body=bytes(body))

    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers=request_headers,
        method="POST",
    )
    try:
        with opener.open(request, timeout=30) as response:
            response_body = response.read().decode("utf-8", errors="ignore")
            if debug:
                debug_http_dump(
                    "qB 添加",
                    method="POST",
                    url=url,
                    headers=request_headers,
                    body=bytes(body),
                    response=response,
                    response_body=response_body,
                )
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        if debug:
            debug_http_dump(
                "qB 添加",
                method="POST",
                url=url,
                headers=request_headers,
                body=bytes(body),
                response=exc,
                response_body=error_body,
                error=exc,
            )
        detail = error_body.strip()
        if detail:
            raise RuntimeError(f"添加 qB 种子失败: {exc.code} {exc.reason}: {detail}")
        raise RuntimeError(f"添加 qB 种子失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        if debug:
            debug_http_dump("qB 添加", method="POST", url=url, headers=request_headers, body=bytes(body), error=exc)
        raise RuntimeError(f"无法连接到 qBittorrent: {exc.reason}")


def get_torrent_save_path(
    opener: urllib.request.OpenerDirector,
    host: str,
    torrent: Dict[str, Any],
) -> str:
    debug = is_debug_enabled()
    save_path = torrent.get("save_path")
    if save_path:
        if debug:
            typer.echo(f"[DEBUG] 直接使用列表中的 save_path: {save_path}")
        return str(save_path)
    torrent_hash = torrent.get("hash")
    if not torrent_hash:
        raise RuntimeError("无法获取 qB 种子 hash，无法确定保存路径。")
    if debug:
        typer.echo(f"[DEBUG] 列表未提供 save_path，改查 properties: infohash={torrent_hash}")
    properties = fetch_qb_torrent_properties(opener, host, torrent_hash)
    save_path = properties.get("save_path")
    if not save_path:
        raise RuntimeError(f"无法获取种子保存路径: {torrent.get('name', '<unknown>')}")
    if debug:
        typer.echo(f"[DEBUG] properties 返回 save_path: {save_path}")
    return str(save_path)
