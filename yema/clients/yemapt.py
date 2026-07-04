from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

import typer

from yema.config.utils import YEMAPT_HOST, fetch_yemapt_basic_info, is_debug_enabled, load_settings
from yema.core.debug import (
    debug_http_dump,
    fetch_with_remote_disconnect_retry,
    get_exception_message,
    preview_bytes,
)
from yema.domain.torrent_files import BencodeError, piece_hashes_from_torrent_data
from yema.domain.trackers import normalize_user_id

def fetch_torrent_ids_from_pt(pieces_hash_list: List[str], debug: bool = False) -> Dict[str, int | None]:
    """Fetch torrent IDs from PT site for given pieces hashes"""
    settings = load_settings()
    yemapt = settings.get("yemapt", {})
    host = yemapt.get("host") or YEMAPT_HOST
    auth = yemapt.get("auth")
    
    if not auth:
        raise typer.Exit(code=1, message="未配置 yemapt 站点，请先运行 yema init 设置。")
    
    host = host.rstrip("/")
    url = f"{host}/openApi/torrent/fetchTorrentIdWithPiecesHash.json"
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "python-urllib/3",
        "Authorization": auth,
    }
    data = json.dumps({"piecesHashList": pieces_hash_list})
    request = urllib.request.Request(
        url,
        data=data.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    
    if debug:
        typer.echo(f"[DEBUG] 查询 Pieces Hash 数量: {len(pieces_hash_list)}")
        typer.echo(f"[DEBUG] PT 请求 Body 长度: {len(data)} 字节")
        debug_http_dump("PT", method="POST", url=url, headers=headers, body=data)
    
    try:
        response, response_bytes = fetch_with_remote_disconnect_retry(
            request,
            timeout=10,
            debug_prefix="PT",
            debug=debug,
            request_url=url,
            request_headers=headers,
            request_body=data,
        )
        body = response_bytes.decode("utf-8")
        if debug:
            typer.echo(f"[DEBUG] PT 响应 Body 长度: {len(body)} 字节")
            debug_http_dump(
                "PT",
                method="POST",
                url=url,
                headers=headers,
                body=data,
                response=response,
                response_body=response_bytes,
            )
        resp_data = json.loads(body)
        if debug:
            typer.echo(f"[DEBUG] PT 响应 JSON - success: {resp_data.get('success')}, data 条数: {len(resp_data.get('data', {}))}")
        if resp_data.get("success"):
            return resp_data.get("data", {})
        raise typer.Exit(code=1, message="PT 站点返回 success=false")
    except json.JSONDecodeError as exc:
        if debug:
            typer.echo(f"[DEBUG] PT 响应不是 JSON: {get_exception_message(exc)}")
        raise typer.Exit(code=1, message="PT 站点返回内容不是 JSON")
    except urllib.error.HTTPError as exc:
        if debug:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = "<无法读取响应体>"
            debug_http_dump(
                "PT",
                method="POST",
                url=url,
                headers=headers,
                body=data,
                response=exc,
                response_body=error_body,
                error=exc,
            )
        raise typer.Exit(code=1, message=f"请求 PT 站点失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise typer.Exit(code=1, message=f"无法连接到 PT 站点: {exc.reason}")
    except http.client.RemoteDisconnected as exc:
        raise typer.Exit(code=1, message=get_exception_message(exc))
    
    return {}


def is_probable_torrent_file(data: bytes) -> bool:
    if not data or not data.startswith(b"d"):
        return False
    return b"4:info" in data


def validate_torrent_data(torrent_id: int, data: bytes) -> None:
    if not data:
        raise BencodeError(f"种子内容为空，torrent_id={torrent_id}")
    if not is_probable_torrent_file(data):
        raise BencodeError(
            f"返回内容不像 torrent 文件, torrent_id={torrent_id}, "
            f"size={len(data)}, preview={preview_bytes(data)}"
        )
    piece_hashes_from_torrent_data(data)


def get_yemapt_auth() -> str:
    settings = load_settings()
    yemapt = settings.get("yemapt", {})
    auth = yemapt.get("auth") or settings.get("yemapt_auth")
    if not auth:
        raise RuntimeError("未配置 yemapt auth，请先运行 yema init 设置。")
    return str(auth)


def get_pt_download_url_from_key(torrent_id: int, auth: str, debug: bool) -> str:
    url = f"{YEMAPT_HOST.rstrip('/')}/openApi/torrent/generateDownloadKey?id={torrent_id}"
    headers = {
        "Authorization": auth,
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "curl/8.0.1",
        "Connection": "close",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    if debug:
        debug_http_dump("PT 下载 Key", method="GET", url=url, headers=headers)
    try:
        response, response_body = fetch_with_remote_disconnect_retry(
            request,
            timeout=20,
            debug_prefix="PT 下载 Key",
            debug=debug,
            request_url=url,
            request_headers=headers,
        )
        if debug:
            debug_http_dump(
                "PT 下载 Key",
                method="GET",
                url=url,
                headers=headers,
                response=response,
                response_body=response_body,
            )
        payload = json.loads(response_body.decode("utf-8", errors="replace"))
        if not payload.get("success"):
            raise RuntimeError(f"generateDownloadKey 返回 success=false: {payload}")
        data = payload.get("data")
        if isinstance(data, str) and data:
            if data.startswith("http"):
                return data
            return f"{YEMAPT_HOST.rstrip('/')}/api/torrent/download1?token={urllib.parse.quote(data)}"
        if isinstance(data, dict):
            for key in ("url", "downloadUrl", "download_url"):
                value = data.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return value
            for key in ("downloadKey", "key"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return f"{YEMAPT_HOST.rstrip('/')}/api/torrent/download1?token={urllib.parse.quote(value)}"
        raise RuntimeError(f"generateDownloadKey 未返回可用下载地址: {payload}")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if debug:
            debug_http_dump(
                "PT 下载 Key",
                method="GET",
                url=url,
                headers=headers,
                response=exc,
                response_body=body,
                error=exc,
            )
        raise RuntimeError(f"generateDownloadKey 失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接到 PT 站点: {exc.reason}")


def download_torrent_bytes(
    url: str,
    headers: Dict[str, Any],
    debug: bool,
    debug_prefix: str,
) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    if debug:
        debug_http_dump(debug_prefix, method="GET", url=url, headers=headers)
    try:
        response, data = fetch_with_remote_disconnect_retry(
            request,
            timeout=20,
            debug_prefix=debug_prefix,
            debug=debug,
            request_url=url,
            request_headers=headers,
        )
        if debug:
            typer.echo(f"[DEBUG] {debug_prefix} 字节数: {len(data)}")
            debug_http_dump(
                debug_prefix,
                method="GET",
                url=url,
                headers=headers,
                response=response,
                response_body=data,
            )
        return data
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if debug:
            debug_http_dump(
                debug_prefix,
                method="GET",
                url=url,
                headers=headers,
                response=exc,
                response_body=body,
                error=exc,
            )
        raise RuntimeError(f"下载 PT 种子失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接到 PT 站点: {exc.reason}")


def download_torrent_from_pt(torrent_id: int) -> bytes:
    debug = is_debug_enabled()
    auth = get_yemapt_auth()
    if debug:
        typer.echo(f"[DEBUG] 开始下载 PT 种子: torrent_id={torrent_id}")
    last_error: BencodeError | None = None
    max_retries = 10
    for attempt in range(1, max_retries + 2):
        if debug and attempt > 1:
            delay = (attempt - 1) * 2
            typer.echo(
                f"[DEBUG] PT 种子解析失败后等待 {delay}s 重新下载: "
                f"torrent_id={torrent_id}, retry={attempt - 1}/{max_retries}"
            )
            time.sleep(delay)
        download_url = get_pt_download_url_from_key(torrent_id, auth, debug)
        if debug:
            typer.echo(f"[DEBUG] PT 下载 Key 返回地址: {download_url}")
        data = download_torrent_bytes(
            download_url,
            {"User-Agent": "curl/8.0.1", "Connection": "close"},
            debug,
            "PT 下载免登录",
        )
        try:
            validate_torrent_data(torrent_id, data)
            if debug:
                typer.echo(f"[DEBUG] PT 种子 bencode 校验通过: torrent_id={torrent_id}")
            return data
        except BencodeError as exc:
            last_error = exc
            if debug:
                typer.echo(f"[DEBUG] PT 种子 bencode 校验失败: {get_exception_message(exc)}")
            if attempt > max_retries:
                break
    raise RuntimeError(f"下载 PT 种子失败: 返回内容不是有效的 torrent 文件: {get_exception_message(last_error)}")


def get_current_yemapt_user_id() -> str | None:
    settings = load_settings()
    yemapt = settings.get("yemapt", {})
    auth = yemapt.get("auth") or settings.get("yemapt_auth")
    if not auth:
        return None

    try:
        result = fetch_yemapt_basic_info(auth)
    except Exception:
        return None

    if not result.get("success"):
        return None

    data = result.get("data", {})
    for key in ("id", "userId", "uid"):
        fetched_user_id = data.get(key)
        normalized = normalize_user_id(fetched_user_id)
        if normalized is not None:
            return normalized
    return None
