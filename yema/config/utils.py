import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import typer

SETTINGS_DIR = Path.home() / ".yema"
SETTINGS_FILE = SETTINGS_DIR / "setting.json"
YEMAPT_HOST = "https://www.yemapt.org"
YEMAPT_USER_INFO_URL = "https://www.yemapt.org/openApi/user/fetchBasicInfo.json"


def load_settings() -> Dict[str, Any]:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise typer.Exit(code=1, message="配置文件已损坏，请删除 ~/.yema/setting.json 后重试。")
    return {}


def save_settings(settings: Dict[str, Any]) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(SETTINGS_FILE, 0o600)


def is_debug_enabled() -> bool:
    return bool(load_settings().get("debug", False))


def format_secret(value: Optional[str]) -> str:
    if not value:
        return "(未配置)"
    return value if len(value) <= 8 else value[:4] + "..." + value[-4:]


def fetch_yemapt_basic_info(auth_token: str) -> Dict[str, Any]:
    debug = is_debug_enabled()
    masked_auth = auth_token if len(auth_token) <= 16 else auth_token[:8] + "..." + auth_token[-8:]
    if debug:
        typer.echo(f"[DEBUG] 请求 URL: {YEMAPT_USER_INFO_URL}")
        typer.echo(f"[DEBUG] 请求 Header Authorization: {masked_auth}")

    request = urllib.request.Request(
        YEMAPT_USER_INFO_URL,
        headers={
            "Authorization": auth_token,
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "curl/8.0.1",
            "Connection": "close",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            if debug:
                typer.echo(f"[DEBUG] 响应状态: {response.status} {response.reason}")
                typer.echo(f"[DEBUG] 响应体: {response_body}")
            return json.loads(response_body)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = "<无法读取响应体>"
        if debug:
            typer.echo(f"[DEBUG] HTTPError 响应状态: {exc.code} {exc.reason}")
            typer.echo(f"[DEBUG] HTTPError 响应体: {body}")
        raise typer.Exit(code=1, message=f"请求 yemapt 站点失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        if debug:
            typer.echo(f"[DEBUG] URLError: {exc.reason}")
        raise typer.Exit(code=1, message=f"无法连接到 yemapt 站点: {exc.reason}")


def fetch_qbittorrent_login(host: str, username: str, password: str) -> None:
    debug = is_debug_enabled()
    host = host.rstrip("/")
    login_url = f"{host}/api/v2/auth/login"
    data = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        login_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    if debug:
        typer.echo(f"[DEBUG] qBittorrent 登录 URL: {login_url}")
        typer.echo(f"[DEBUG] qBittorrent 请求数据: username={username}&password=***")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            if debug:
                typer.echo(f"[DEBUG] qBittorrent 响应状态: {response.status} {response.reason}")
                typer.echo(f"[DEBUG] qBittorrent 响应体: {body}")
            if body.strip() != "Ok.":
                raise typer.Exit(code=1, message=f"qBittorrent 登录失败，响应：{body}")
    except urllib.error.HTTPError as exc:
        if debug:
            typer.echo(f"[DEBUG] qBittorrent HTTPError: {exc.code} {exc.reason}")
        raise typer.Exit(code=1, message=f"请求 qBittorrent 失败: {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        if debug:
            typer.echo(f"[DEBUG] qBittorrent URLError: {exc.reason}")
        raise typer.Exit(code=1, message=f"无法连接到 qBittorrent: {exc.reason}")
