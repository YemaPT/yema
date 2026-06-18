import typer
from typer import Context

from yema.filesystems.base import normalize_filesystems

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
    filesystems = normalize_filesystems(settings.get("filesystems"))
    clients = settings.get("clients", {})
    tr = clients.get("transmission", {}) if isinstance(clients, dict) else {}
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
    typer.echo(
        "  filesystems: "
        + (
            "local"
            + (", " + ", ".join(str(fs.get("id")) for fs in filesystems if fs.get("id")) if filesystems else "")
        )
    )
    typer.echo(f"  Transmission host: {tr.get('host', '(未配置)')}")
    typer.echo(f"  Transmission filesystem: {tr.get('filesystem', '(未配置)')}")
    mappings = tr.get("path_mappings", [])
    if isinstance(mappings, list) and mappings:
        mapping_text = ", ".join(f"{m.get('from')}->{m.get('to')}" for m in mappings if isinstance(m, dict))
        typer.echo(f"  Transmission path mappings: {mapping_text}")
    typer.echo(f"  debug: {'enabled' if settings.get('debug', False) else 'disabled'}")


from . import debug  # noqa: E402, F401
