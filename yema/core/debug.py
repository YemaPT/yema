from __future__ import annotations

import http.client
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import typer

def get_exception_message(exc: BaseException) -> str:
    message = getattr(exc, "message", None)
    if message:
        return str(message)
    if exc.args:
        return " ".join(str(arg) for arg in exc.args if arg is not None)
    return str(exc) or exc.__class__.__name__


def preview_bytes(data: bytes, limit: int = 80) -> str:
    preview = data[:limit]
    try:
        return preview.decode("utf-8", errors="replace")
    except Exception:
        return repr(preview)


def get_debug_output_path() -> Path:
    tmp_dir = Path.cwd() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"{secrets.token_hex(8)}.tmp"


def format_debug_body(data: bytes | str | None, full_text_threshold: int = 150, preview_limit: int = 200) -> str:
    if data is None:
        return "<empty>"
    if isinstance(data, bytes) and len(data) > full_text_threshold:
        output_path = get_debug_output_path()
        output_path.write_bytes(data)
        typer.echo(f"[DEBUG] 响应内容较长，已保存到: {output_path}，请查看该文件")
        return f"<saved to {output_path}>"
    if isinstance(data, str):
        text = data
    else:
        text = data.decode("utf-8", errors="replace")
    if len(text) < full_text_threshold:
        return text
    output_path = get_debug_output_path()
    output_path.write_text(text, encoding="utf-8")
    typer.echo(f"[DEBUG] 响应内容较长，已保存到: {output_path}，请查看该文件")
    return f"<saved to {output_path}>"


def debug_http_dump(
    prefix: str,
    *,
    method: str,
    url: str,
    headers: Dict[str, Any],
    body: bytes | str | None = None,
    response: Any = None,
    response_body: bytes | str | None = None,
    error: BaseException | None = None,
) -> None:
    typer.echo(f"[DEBUG] {prefix} 请求 Method: {method}")
    typer.echo(f"[DEBUG] {prefix} 请求 URL: {url}")
    typer.echo(f"[DEBUG] {prefix} 请求 Headers: {headers}")
    typer.echo(f"[DEBUG] {prefix} 请求 Body: {format_debug_body(body)}")
    if response is not None:
        status = getattr(response, "code", getattr(response, "status", "<unknown>"))
        reason = getattr(response, "reason", "")
        typer.echo(f"[DEBUG] {prefix} 响应 Status: {status} {reason}".rstrip())
        try:
            response_headers = dict(response.headers.items())
        except Exception:
            response_headers = str(getattr(response, "headers", "<unknown>"))
        typer.echo(f"[DEBUG] {prefix} 响应 Headers: {response_headers}")
        typer.echo(f"[DEBUG] {prefix} 响应 Body: {format_debug_body(response_body)}")
    if error is not None:
        typer.echo(f"[DEBUG] {prefix} 异常类型: {error.__class__.__name__}")
        typer.echo(f"[DEBUG] {prefix} 异常详情: {get_exception_message(error)}")


def is_retryable_remote_disconnect(error: BaseException) -> bool:
    if isinstance(error, http.client.RemoteDisconnected):
        return True
    return "Remote end closed connection without response" in get_exception_message(error)


def fetch_with_remote_disconnect_retry(
    request: urllib.request.Request,
    *,
    timeout: int,
    debug_prefix: str,
    debug: bool,
    request_url: str,
    request_headers: Dict[str, Any],
    request_body: bytes | str | None = None,
) -> tuple[Any, bytes]:
    last_error: BaseException | None = None
    for attempt in range(1, 5):
        response = None
        try:
            if debug and attempt > 1:
                typer.echo(f"[DEBUG] {debug_prefix} 重试 {attempt - 1}/3")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read()
                return response, response_body
        except urllib.error.URLError as exc:
            last_error = exc
            if debug:
                debug_http_dump(
                    debug_prefix,
                    method=request.get_method(),
                    url=request_url,
                    headers=request_headers,
                    body=request_body,
                    error=exc,
                )
            if attempt < 4 and is_retryable_remote_disconnect(exc):
                continue
            raise
        except http.client.RemoteDisconnected as exc:
            last_error = exc
            if debug:
                debug_http_dump(
                    debug_prefix,
                    method=request.get_method(),
                    url=request_url,
                    headers=request_headers,
                    body=request_body,
                    error=exc,
                )
            if attempt < 4:
                continue
            raise
        except http.client.IncompleteRead as exc:
            last_error = exc
            partial = exc.partial or b""
            if debug:
                typer.echo(f"[DEBUG] {debug_prefix} IncompleteRead: 已读取 {len(partial)}B，期望 {exc.expected}")
            if partial:
                if debug:
                    typer.echo(f"[DEBUG] {debug_prefix} 连接提前关闭，但已获得响应内容，交由上层解析。")
                return response, partial
            if attempt < 4:
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{debug_prefix} 请求失败: 未知错误")
