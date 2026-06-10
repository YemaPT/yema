import sys
import termios
import tty
from typing import Dict, Optional

import typer

from .config.utils import (
    fetch_qbittorrent_login,
    fetch_yemapt_basic_info,
    load_settings,
    save_settings,
)


def prompt_secret(prompt_text: str, default: Optional[str] = None) -> str:
    if default:
        return typer.prompt(prompt_text, default=default, hide_input=True)
    return typer.prompt(prompt_text, hide_input=True)


def prompt_field(prompt_text: str, default: Optional[str] = None) -> str:
    if default:
        return typer.prompt(prompt_text, default=default)
    return typer.prompt(prompt_text)


def ensure_nested_settings(settings: Dict[str, object]) -> Dict[str, object]:
    settings.setdefault("yemapt", {})
    settings.setdefault("qb", {})
    return settings


def read_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            second = sys.stdin.read(1)
            if second == "[":
                third = sys.stdin.read(1)
                if third == "A":
                    return "UP"
                if third == "B":
                    return "DOWN"
            return ch
        if ch == "\r":
            return "ENTER"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def clear_screen() -> None:
    print("\x1b[2J\x1b[H", end="")


def render_menu(selected: int, items: Dict[str, str]) -> None:
    clear_screen()
    typer.echo("使用 ↑ ↓ 选择，按回车确认。按 q 退出。\n")
    for index, (title, status) in enumerate(items.items()):
        prefix = "▶" if index == selected else "  "
        if index == selected:
            typer.secho(f"{prefix} {title} {status}", fg="cyan")
        else:
            typer.echo(f"{prefix} {title} {status}")
    typer.echo("")


def validate_yemapt_status(settings: Dict[str, object]) -> Dict[str, object]:
    yemapt = settings.get("yemapt", {})
    auth = yemapt.get("auth")
    if not auth:
        return {"valid": False, "display": "未配置"}
    try:
        result = fetch_yemapt_basic_info(auth)
    except typer.Exit:
        return {"valid": False, "display": "配置无效"}
    if not result.get("success"):
        return {"valid": False, "display": "配置无效"}
    data = result.get("data", {})
    return {
        "valid": True,
        "display": f"id={data.get('id')} username={data.get('name')} (已配置)",
    }


def validate_qb_status(settings: Dict[str, object]) -> Dict[str, object]:
    qb = settings.get("qb", {})
    host = qb.get("host")
    username = qb.get("username")
    password = qb.get("password")
    if not host or not username or not password:
        return {"valid": False, "display": "未配置"}
    try:
        fetch_qbittorrent_login(host, username, password)
        return {"valid": True, "display": f"{host} (已配置)"}
    except typer.Exit:
        return {"valid": False, "display": "配置无效"}


def prompt_yemapt_auth() -> Dict[str, object]:
    while True:
        auth = typer.prompt("请输入 yemapt auth")
        typer.echo("正在验证 yemapt auth...")
        try:
            result = fetch_yemapt_basic_info(auth)
        except typer.Exit as exc:
            typer.echo(exc.message, err=True)
            continue

        if not result.get("success"):
            typer.echo("yemapt auth 验证失败，success=false。请重新输入。", err=True)
            continue

        data = result.get("data", {})
        typer.secho(
            f"yemapt auth 验证通过，id={data.get('id')}，username={data.get('name')}",
            fg="green",
        )
        return {"auth": auth, "username": data.get("name")}


def confirm_or_edit_yemapt(settings: Dict[str, object]) -> Dict[str, object]:
    yemapt = settings.get("yemapt", {})
    auth = yemapt.get("auth")

    if auth:
        typer.echo("检测到已有 yemapt auth 配置，尝试验证当前 auth...")
        try:
            result = fetch_yemapt_basic_info(auth)
            if result.get("success"):
                data = result.get("data", {})
                typer.echo(f"当前 auth 对应用户：id={data.get('id')}，username={data.get('name')}")
                if typer.confirm("是否跳过修改 auth？", default=True):
                    return yemapt
                typer.echo("请重新输入新的 yemapt auth。")
            else:
                typer.echo("当前 auth 无效，需重新输入。")
        except typer.Exit as exc:
            typer.echo(str(exc), err=True)
            typer.echo("当前 auth 验证失败，需重新输入。")

    return prompt_yemapt_auth()


def prompt_qb_config(existing: Dict[str, str]) -> Dict[str, str]:
    while True:
        host = prompt_field("请输入 qBittorrent host", default=existing.get("host"))
        username = prompt_field("请输入 qBittorrent 用户名", default=existing.get("username"))
        password = prompt_secret("请输入 qBittorrent 密码", default=existing.get("password"))

        typer.echo("正在验证 qBittorrent 登录信息...")
        try:
            fetch_qbittorrent_login(host, username, password)
            typer.secho("qBittorrent 登录验证通过。", fg="green")
            return {"host": host, "username": username, "password": password}
        except typer.Exit as exc:
            typer.echo(str(exc), err=True)
            typer.echo("qBittorrent 登录失败。")

            if not typer.confirm("是否修改 host/用户名/密码 并重试？", default=True):
                raise typer.Exit(code=1, message="qBittorrent 初始化未完成。")

            if typer.confirm("是否修改 host？", default=False):
                existing["host"] = prompt_field("请输入 qBittorrent host", default=existing.get("host"))
            if typer.confirm("是否修改 username？", default=False):
                existing["username"] = prompt_field("请输入 qBittorrent 用户名", default=existing.get("username"))
            if typer.confirm("是否修改 password？", default=False):
                existing["password"] = prompt_secret("请输入 qBittorrent 密码", default=existing.get("password"))

            typer.echo("请重新验证 qBittorrent 登录信息。")
            continue


def confirm_or_edit_qb(settings: Dict[str, object]) -> Dict[str, str]:
    qb = settings.get("qb", {})
    if qb.get("host") and qb.get("username") and qb.get("password"):
        typer.echo("检测到已有 qBittorrent 配置，尝试验证当前配置...")
        try:
            fetch_qbittorrent_login(qb["host"], qb["username"], qb["password"])
            typer.echo(f"当前 qBittorrent 配置生效：host={qb['host']}，username={qb['username']}")
            if typer.confirm("是否跳过修改 qBittorrent 配置？", default=True):
                return qb
            typer.echo("请重新输入 qBittorrent 配置。")
        except typer.Exit as exc:
            typer.echo(str(exc), err=True)
            typer.echo("当前 qBittorrent 配置验证失败，需重新输入。")

    return prompt_qb_config({
        "host": qb.get("host", ""),
        "username": qb.get("username", ""),
        "password": qb.get("password", ""),
    })


def interactive_init(settings: Dict[str, object]) -> Dict[str, object]:
    selected = 0
    y_status = validate_yemapt_status(settings)
    q_status = validate_qb_status(settings)
    while True:
        menu_items = {
            "1 yemapt": f"{y_status['display']}",
            "2 qb": f"{q_status['display']}",
            "3 完成初始化": "",
        }
        render_menu(selected, menu_items)
        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(menu_items)
            continue
        if key == "DOWN":
            selected = (selected + 1) % len(menu_items)
            continue
        if key == "q":
            raise typer.Exit(code=1, message="已取消初始化。")
        if key == "ENTER":
            if selected == 0:
                settings["yemapt"] = confirm_or_edit_yemapt(settings)
                save_settings(settings)
                y_status = validate_yemapt_status(settings)
            elif selected == 1:
                settings["qb"] = confirm_or_edit_qb(settings)
                save_settings(settings)
                q_status = validate_qb_status(settings)
            elif selected == 2:
                if y_status["valid"] and q_status["valid"]:
                    return settings
                typer.echo("当前配置尚未完成或无效，请先修正。")
            continue


def init_command():
    settings = load_settings()
    ensure_nested_settings(settings)

    typer.echo("开始初始化 yema 配置。")
    settings = interactive_init(settings)
    save_settings(settings)
    typer.secho("初始化完成。", fg="green")
