import typer
from typer import Context

from .utils import format_secret, load_settings

config_app = typer.Typer(help="查看配置并管理 debug 开关")


@config_app.callback(invoke_without_command=True)
def config(ctx: Context):
    """显示当前配置。"""
    if ctx.invoked_subcommand is not None:
        return

    settings = load_settings()
    y = settings.get("yemapt", {})
    q = settings.get("qb", {})
    typer.echo("当前配置：")
    typer.echo(
        f"  yemapt auth: {format_secret(y.get('auth') or settings.get('yemapt_auth'))}"
    )
    typer.echo(
        f"  qBittorrent host: {q.get('host', settings.get('qb_host', '(未配置)'))}"
    )
    typer.echo(
        f"  qBittorrent username: {q.get('username', settings.get('qb_username', '(未配置)'))}"
    )
    typer.echo(
        f"  qBittorrent password: {format_secret(q.get('password') or settings.get('qb_password'))}"
    )
    typer.echo(f"  debug: {'enabled' if settings.get('debug', False) else 'disabled'}")


from . import debug  # noqa: E402, F401
