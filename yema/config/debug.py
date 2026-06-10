import typer

from . import config_app
from .utils import load_settings, save_settings


@config_app.command("debug")
def config_debug(
    action: str = typer.Argument(
        ..., 
        case_sensitive=False,
        help="enable: 启用 debug；disable: 禁用 debug。",
    ),
):
    """设置 debug 模式。"""
    normalized = action.lower()
    if normalized not in {"enable", "disable"}:
        raise typer.BadParameter("debug 子命令只支持 enable 或 disable")

    settings = load_settings()
    settings["debug"] = normalized == "enable"
    save_settings(settings)
    typer.secho(
        f"debug 已{'启用' if settings['debug'] else '禁用'}。",
        fg="green",
    )
