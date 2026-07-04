from __future__ import annotations

from typing import Optional

import typer

from .config import config_app
from .commands.qb import qb_command, check_torrents, seed_torrents, pub_torrents
from .commands.transmission import (
    check_torrents as transmission_check_torrents,
    transmission_command,
)
from .init import init_command

app = typer.Typer(help="yemapt 下载软件辅助保种与转种工具", invoke_without_command=True)
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def app_callback(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def init():
    """交互式初始化配置。"""
    init_command()


@app.command()
def qb():
    """进入 qBittorrent 操作菜单。"""
    qb_command()


@app.command()
def tr():
    """进入 Transmission 操作菜单。"""
    transmission_command()


@app.command()
def pub(
    client: Optional[str] = typer.Option(None, "--client", help="只处理指定客户端：qb 或 tr。"),
    tracker: Optional[str] = typer.Option(None, "--tracker", help="只处理匹配指定 tracker 的种子。"),
    urls: bool = typer.Option(False, "--urls", help="直接输出可解析出的详情页 URL，每行一个。"),
):
    """列出下载软件上不在 PT 站点的种子。"""
    pub_torrents(client=client, urls=urls, tracker=tracker)


@app.command()
def check():
    """检查下载软件种子在 PT 站点上是否存在。"""
    check_torrents()


@app.command("tr-check")
def tr_check():
    """检查 Transmission 种子在 PT 站点上是否存在。"""
    transmission_check_torrents()


@app.command()
def seed(
    yes: bool = typer.Option(False, "--yes", "-y", help="自动确认并执行所有补种操作。"),
    client: Optional[str] = typer.Option(None, "--client", help="只处理指定客户端：qb 或 tr。"),
    tracker: Optional[str] = typer.Option(None, "--tracker", help="只处理匹配指定 tracker 的种子。"),
):
    """补种未做种或非当前用户做种的 PT 种子。"""
    seed_torrents(yes=yes, client=client, tracker=tracker)


def main() -> int:
    try:
        app()
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"错误: {exc}", err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
