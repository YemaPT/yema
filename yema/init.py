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
from .clients.transmission import create_transmission_client
from .filesystems.base import (
    ensure_default_filesystems,
    get_filesystem_map,
    normalize_filesystems,
    validate_filesystem_config,
)


def prompt_secret(prompt_text: str, default: Optional[str] = None) -> str:
    if default is not None:
        return typer.prompt(prompt_text, default=default, hide_input=True)
    return typer.prompt(prompt_text, hide_input=True)


def prompt_field(prompt_text: str, default: Optional[str] = None) -> str:
    if default is not None:
        return typer.prompt(prompt_text, default=default)
    return typer.prompt(prompt_text)


def ensure_nested_settings(settings: Dict[str, object]) -> Dict[str, object]:
    settings.setdefault("yemapt", {})
    settings.setdefault("qb", {})
    settings.setdefault("clients", {})
    ensure_default_filesystems(settings)
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


def select_menu(title: str, options: list[tuple[str, str]]) -> Optional[str]:
    selected = 0
    while True:
        clear_screen()
        typer.echo(title)
        typer.echo("")
        for index, (_, label) in enumerate(options):
            prefix = "▶" if index == selected else "  "
            if index == selected:
                typer.secho(f"{prefix} {label}", fg="cyan")
            else:
                typer.echo(f"{prefix} {label}")
        typer.echo("")
        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(options)
        elif key == "DOWN":
            selected = (selected + 1) % len(options)
        elif key == "ENTER":
            return options[selected][0]
        elif key == "q" or key == "\x1b":
            return None


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
        "display": f"id={data.get('id')} username={data.get('name')}",
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
        return {"valid": True, "display": f"{host} 已联通"}
    except typer.Exit:
        return {"valid": False, "display": "配置无效"}


def filesystem_reference_label(settings: Dict[str, object], filesystem_id: str) -> str:
    if filesystem_id == "local":
        return "local"
    for index, fs in enumerate(normalize_filesystems(settings.get("filesystems"))):
        if str(fs.get("id") or "") == filesystem_id:
            name = str(fs.get("name") or f"文件系统 {index + 1}")
            return f"文件系统 {index + 1}: {name}"
    return "文件系统未配置"


def validate_filesystems_status(settings: Dict[str, object]) -> Dict[str, object]:
    ensure_default_filesystems(settings)
    filesystems = normalize_filesystems(settings.get("filesystems"))
    if not filesystems:
        return {"valid": True, "display": "仅本地文件系统"}
    ok = []
    failed = []
    for index, fs in enumerate(filesystems):
        label = f"文件系统 {index + 1}"
        try:
            validate_filesystem_config(fs)
            ok.append(label)
        except Exception:
            failed.append(label)
    if failed:
        return {
            "valid": False,
            "display": f"local 已联通; 远程已联通: {len(ok)}; 无效: {', '.join(failed)}",
        }
    return {"valid": True, "display": f"local 已联通; 远程已联通: {', '.join(ok)}"}


def validate_transmission_status(settings: Dict[str, object]) -> Dict[str, object]:
    clients = settings.get("clients", {})
    tr = clients.get("transmission", {}) if isinstance(clients, dict) else {}
    if not tr:
        tr = settings.get("transmission", {})
    if not isinstance(tr, dict):
        return {"valid": False, "display": "未配置"}
    host = tr.get("host")
    if not host:
        return {"valid": False, "display": "未配置"}
    filesystem = str(tr.get("filesystem") or "")
    filesystems = get_filesystem_map(settings)
    if not filesystem or filesystem not in filesystems:
        return {"valid": False, "display": "文件系统未配置"}
    try:
        create_transmission_client(str(host), str(tr.get("username") or ""), str(tr.get("password") or ""))
        return {"valid": True, "display": f"{host} fs={filesystem_reference_label(settings, filesystem)} 已联通"}
    except typer.Exit:
        return {"valid": False, "display": "配置无效"}


def yemapt_status_from_config(settings: Dict[str, object]) -> Dict[str, object]:
    yemapt = settings.get("yemapt", {})
    if not isinstance(yemapt, dict) or not yemapt.get("auth"):
        return {"valid": False, "display": "未配置"}
    username = str(yemapt.get("username") or "")
    display = f"username={username}" if username else "已配置"
    return {"valid": True, "display": display}


def qb_status_from_config(settings: Dict[str, object]) -> Dict[str, object]:
    qb = settings.get("qb", {})
    if not isinstance(qb, dict) or not qb.get("host") or not qb.get("username") or not qb.get("password"):
        return {"valid": False, "display": "未配置"}
    return {"valid": True, "display": f"{qb.get('host')} 已联通"}


def filesystems_status_from_config(settings: Dict[str, object]) -> Dict[str, object]:
    ensure_default_filesystems(settings)
    filesystems = normalize_filesystems(settings.get("filesystems"))
    if not filesystems:
        return {"valid": True, "display": "仅本地文件系统"}
    labels = [f"文件系统 {index + 1}" for index, _ in enumerate(filesystems)]
    return {"valid": True, "display": f"local 已联通; 远程已联通: {', '.join(labels)}"}


def transmission_status_from_config(settings: Dict[str, object]) -> Dict[str, object]:
    clients = settings.get("clients", {})
    tr = clients.get("transmission", {}) if isinstance(clients, dict) else {}
    if not tr:
        tr = settings.get("transmission", {})
    if not isinstance(tr, dict) or not tr.get("host"):
        return {"valid": False, "display": "未配置"}
    filesystem = str(tr.get("filesystem") or "")
    filesystems = get_filesystem_map(settings)
    if not filesystem or filesystem not in filesystems:
        return {"valid": False, "display": "文件系统未配置"}
    return {"valid": True, "display": f"{tr.get('host')} fs={filesystem_reference_label(settings, filesystem)} 已联通"}


def prompt_yemapt_auth(existing_auth: Optional[str] = None) -> Dict[str, object]:
    while True:
        auth = prompt_secret("请输入 yemapt auth（留空复用当前值）", default=existing_auth) if existing_auth else prompt_secret("请输入 yemapt auth")
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


def has_config_value(config: object) -> bool:
    return isinstance(config, dict) and any(value not in (None, "", [], {}) for value in config.values())


def select_config_action(title: str) -> Optional[str]:
    return select_menu(
        f"{title}\n请选择操作。按 q 返回。",
        [("edit", "修改"), ("delete", "删除"), ("back", "返回")],
    )


def confirm_or_edit_yemapt(settings: Dict[str, object]) -> Dict[str, object]:
    yemapt = settings.get("yemapt", {})
    if not isinstance(yemapt, dict):
        yemapt = {}

    if has_config_value(yemapt):
        username = str(yemapt.get("username") or "")
        display = f"当前 yemapt auth 配置：username={username or '-'}"
        action = select_config_action(display)
        if action in {None, "back"}:
            return yemapt
        if action == "delete":
            if typer.confirm("确认删除 yemapt auth 配置？", default=False):
                return {}
            return yemapt
        typer.echo("请重新输入新的 yemapt auth。")

    return prompt_yemapt_auth(str(yemapt.get("auth") or "") or None)


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
                typer.echo("qBittorrent 初始化未完成。", err=True)
                raise typer.Exit(code=1)

            if typer.confirm("是否修改 host？", default=False):
                existing["host"] = prompt_field("请输入 qBittorrent host", default=existing.get("host"))
            if typer.confirm("是否修改 username？", default=False):
                existing["username"] = prompt_field("请输入 qBittorrent 用户名", default=existing.get("username"))
            if typer.confirm("是否修改 password？", default=False):
                existing["password"] = prompt_secret("请输入 qBittorrent 密码", default=existing.get("password"))

            typer.echo("请重新验证 qBittorrent 登录信息。")
            continue


def show_filesystem_config_example(fs_type: str) -> None:
    examples = {
        "webdav": [
            "WebDAV 配置示例：",
            "  远程地址: https://nas.example.com/dav",
            "  端口: 留空",
            "  用户名: user",
            "  远程种子文件根目录: /downloads/transmission/torrents",
        ],
        "sftp": [
            "SFTP 配置示例：",
            "  远程地址: 192.168.1.10",
            "  端口: 22",
            "  用户名: seedbox",
            "  远程种子文件根目录: /home/seedbox/.config/transmission/torrents",
        ],
        "ssh": [
            "SSH 配置示例：",
            "  远程地址: 192.168.1.10",
            "  端口: 22",
            "  用户名: seedbox",
            "  远程种子文件根目录: /vol1/@appdata/transmission/torrents",
        ],
        "ftp": [
            "FTP 配置示例：",
            "  远程地址: ftp.example.com",
            "  端口: 21",
            "  用户名: user",
            "  远程种子文件根目录: /transmission/torrents",
        ],
    }
    typer.echo("")
    for line in examples[fs_type]:
        typer.echo(line)
    typer.echo("")


def next_filesystem_id(filesystems: list[Dict[str, object]]) -> str:
    used = {str(fs.get("id")) for fs in filesystems if fs.get("id")}
    number = 1
    while f"fs{number}" in used:
        number += 1
    return f"fs{number}"


def filesystem_label(index: int, fs: Dict[str, object]) -> str:
    name = str(fs.get("name") or f"文件系统 {index + 1}")
    host = str(fs.get("host") or "-")
    port = str(fs.get("port") or "-")
    username = str(fs.get("username") or "-")
    root = str(fs.get("root") or "-")
    return (
        f"文件系统 {index + 1}: {name} ({fs.get('type', 'local')}) "
        f"host={host} port={port} username={username} root={root}"
    )


def prompt_filesystem_config(existing: Dict[str, object] | None = None) -> Dict[str, object]:
    existing = existing or {}
    while True:
        fs_id = str(existing.get("id") or "fs1")
        name = prompt_field("请输入文件系统名称", default=str(existing.get("name") or "远程文件系统"))
        while True:
            fs_type = prompt_field("请输入文件系统类型(webdav/sftp/ssh/ftp)", default=str(existing.get("type") or "webdav")).lower()
            if fs_type in {"webdav", "sftp", "ssh", "ftp"}:
                break
            typer.echo("文件系统类型无效，请输入 webdav、sftp、ssh 或 ftp。")
        show_filesystem_config_example(fs_type)
        config: Dict[str, object] = {"id": fs_id, "type": fs_type, "name": name}
        config["host"] = prompt_field("请输入远程地址", default=str(existing.get("host") or ""))
        default_port = "22" if fs_type in {"sftp", "ssh"} else "21" if fs_type == "ftp" else ""
        port = prompt_field("请输入端口（可留空使用默认端口）", default=str(existing.get("port") or default_port))
        if port:
            try:
                config["port"] = int(port)
            except ValueError:
                typer.echo("端口必须是数字，请重新配置。")
                continue
        config["username"] = prompt_field("请输入用户名（可留空）", default=str(existing.get("username") or ""))
        password = prompt_secret("请输入密码（可留空）", default=str(existing.get("password") or ""))
        config["password"] = password
        config["root"] = prompt_field("请输入远程种子文件根目录", default=str(existing.get("root") or ""))

        typer.echo("正在校验文件系统...")
        try:
            validate_filesystem_config(config)
            typer.secho("文件系统校验通过。", fg="green")
            return config
        except Exception as exc:
            typer.echo(f"文件系统校验失败: {exc}", err=True)
            if not typer.confirm("是否修改配置并重试？", default=True):
                typer.echo("文件系统初始化未完成。", err=True)
                raise typer.Exit(code=1)


def render_filesystem_menu(selected: int, filesystems: list[Dict[str, object]]) -> list[str]:
    options = ["local"] + [str(index) for index, _ in enumerate(filesystems)] + ["__new__"]
    labels = {"local": "local (本地文件系统，内置，无需配置)", "__new__": "新增文件系统"}
    for index, fs in enumerate(filesystems):
        labels[str(index)] = filesystem_label(index, fs)

    clear_screen()
    typer.echo("文件系统配置。使用 ↑ ↓ 选择，按回车确认。按 q 返回。\n")
    for index, option in enumerate(options):
        prefix = "▶" if index == selected else "  "
        line = f"{prefix} {labels[option]}"
        if index == selected:
            typer.secho(line, fg="cyan")
        else:
            typer.echo(line)
    typer.echo("")
    return options


def reset_transmission_filesystem_if_needed(settings: Dict[str, object], filesystem_id: str) -> None:
    clients = settings.get("clients")
    if not isinstance(clients, dict):
        return
    transmission = clients.get("transmission")
    if not isinstance(transmission, dict):
        return
    if str(transmission.get("filesystem") or "") == filesystem_id:
        transmission["filesystem"] = "local"
        typer.echo("该文件系统正在被 Transmission 使用，已将 Transmission 文件系统切换为 local。")


def confirm_or_edit_filesystems(settings: Dict[str, object]) -> list[Dict[str, object]]:
    ensure_default_filesystems(settings)
    filesystems = normalize_filesystems(settings.get("filesystems"))

    selected = 0
    while True:
        options = render_filesystem_menu(selected, filesystems)
        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(options)
            continue
        if key == "DOWN":
            selected = (selected + 1) % len(options)
            continue
        if key == "q":
            return filesystems
        if key != "ENTER":
            continue

        option = options[selected]
        if option == "local":
            continue

        if option == "__new__":
            next_number = len(filesystems) + 1
            fs_config = prompt_filesystem_config({
                "id": next_filesystem_id(filesystems),
                "name": f"文件系统 {next_number}",
            })
            filesystems.append(fs_config)
            selected = len(filesystems)
            continue

        fs_index = int(option)
        action = select_menu(
            f"{filesystem_label(fs_index, filesystems[fs_index])}\n请选择操作。按 q 返回。",
            [("edit", "修改"), ("delete", "删除"), ("back", "返回")],
        )
        if action in {None, "back"}:
            continue
        if action == "edit":
            if not typer.confirm("确认修改该文件系统？", default=True):
                continue
            filesystems[fs_index] = prompt_filesystem_config(filesystems[fs_index])
        elif action == "delete":
            if not typer.confirm("确认删除该文件系统？", default=False):
                continue
            removed = filesystems.pop(fs_index)
            reset_transmission_filesystem_if_needed(settings, str(removed.get("id") or ""))
            selected = min(selected, len(filesystems) + 1)


def select_filesystem(settings: Dict[str, object], default: str = "local") -> str:
    ensure_default_filesystems(settings)
    filesystems = normalize_filesystems(settings.get("filesystems"))
    ids = [str(fs.get("id")) for fs in filesystems if fs.get("id")]
    labels = {str(fs.get("id")): filesystem_label(index, fs) for index, fs in enumerate(filesystems) if fs.get("id")}
    options = ["local"] + ids + ["__new__"]
    labels["local"] = "local (本地文件系统)"
    if default not in options:
        default = "local" if "local" in options else options[0]
    selected = options.index(default)
    while True:
        clear_screen()
        typer.echo("请选择 Transmission 使用的文件系统，按回车确认。\n")
        for index, option in enumerate(options):
            label = "新增文件系统" if option == "__new__" else labels[option]
            prefix = "▶" if index == selected else "  "
            if index == selected:
                typer.secho(f"{prefix} {label}", fg="cyan")
            else:
                typer.echo(f"{prefix} {label}")
        key = read_key()
        if key == "UP":
            selected = (selected - 1) % len(options)
        elif key == "DOWN":
            selected = (selected + 1) % len(options)
        elif key == "ENTER":
            option = options[selected]
            if option != "__new__":
                return option
            fs_config = prompt_filesystem_config({
                "id": next_filesystem_id(normalize_filesystems(settings.get("filesystems"))),
                "name": f"文件系统 {len(normalize_filesystems(settings.get('filesystems'))) + 1}",
            })
            fs_map = {str(fs.get("id")): fs for fs in normalize_filesystems(settings.get("filesystems")) if fs.get("id")}
            fs_map[str(fs_config["id"])] = fs_config
            settings["filesystems"] = list(fs_map.values())
            return str(fs_config["id"])
        elif key == "\x1b" or key == "q":
            typer.echo("已取消选择文件系统。")
            raise typer.Exit(code=0)


def prompt_path_mappings(existing: list[Dict[str, str]] | None = None) -> list[Dict[str, str]]:
    mappings = list(existing or [])
    if mappings:
        typer.echo("当前路径映射：")
        for mapping in mappings:
            typer.echo(f"  {mapping.get('from', '')} -> {mapping.get('to', '')}")
    typer.echo("如果 Transmission 运行在 Docker 中，Transmission 接口返回的是容器内路径，文件系统登录后看到的是宿主机路径。")
    typer.echo("这里应填写 Docker 文件夹映射关系，例如服务器 /xxx/transmission/config 映射到容器 /config。")
    typer.echo("当 Transmission 返回 /config/aaa.torrent 时，程序会映射回 /xxx/transmission/config/aaa.torrent 读取。")
    if not typer.confirm("是否配置 Transmission 到文件系统的路径映射？", default=not mappings):
        return mappings

    mappings = []
    typer.echo("请输入路径映射。")
    while True:
        source = prompt_field("Transmission/容器内路径前缀", default="/" if not mappings else "")
        target = prompt_field("文件系统/宿主机路径前缀", default="/" if source == "/" else "")
        mappings.append({"from": source.rstrip("/") or "/", "to": target.rstrip("/") or "/"})
        if not typer.confirm("是否继续添加路径映射？", default=False):
            return mappings


def prompt_transmission_config(settings: Dict[str, object], existing: Dict[str, object]) -> Dict[str, object] | None:
    while True:
        host = prompt_field("请输入 Transmission host", default=existing.get("host"))
        username = prompt_field("请输入 Transmission 用户名（可留空）", default=existing.get("username"))
        password = prompt_secret("请输入 Transmission 密码（可留空）", default=existing.get("password"))
        filesystem = select_filesystem(settings, default=existing.get("filesystem", "local"))
        mappings = prompt_path_mappings(existing.get("path_mappings") if isinstance(existing.get("path_mappings"), list) else None)

        typer.echo("正在验证 Transmission RPC...")
        try:
            create_transmission_client(host, username, password)
            typer.secho("Transmission RPC 验证通过。", fg="green")
            return {
                "host": host,
                "username": username,
                "password": password,
                "filesystem": filesystem,
                "path_mappings": mappings,
            }
        except typer.Exit as exc:
            typer.echo(str(exc), err=True)
            typer.echo("Transmission 验证失败。")
            if not typer.confirm("是否修改配置并重试？", default=True):
                typer.echo("本次 Transmission 修改未保存。")
                return None


def confirm_or_edit_transmission(settings: Dict[str, object]) -> Dict[str, object] | None:
    clients = settings.setdefault("clients", {})
    if not isinstance(clients, dict):
        clients = {}
        settings["clients"] = clients
    existing = clients.get("transmission", {})
    if not isinstance(existing, dict):
        existing = {}

    if has_config_value(existing):
        filesystem = str(existing.get("filesystem") or "-")
        display = f"当前 Transmission 配置：host={existing.get('host') or '-'}，filesystem={filesystem}"
        action = select_config_action(display)
        if action in {None, "back"}:
            return existing
        if action == "delete":
            if typer.confirm("确认删除 Transmission 配置？", default=False):
                return {}
            return existing
        typer.echo("请重新输入 Transmission 配置。")

    updated = prompt_transmission_config(settings, {
        "host": str(existing.get("host") or ""),
        "username": str(existing.get("username") or ""),
        "password": str(existing.get("password") or ""),
        "filesystem": str(existing.get("filesystem") or "local"),
        "path_mappings": existing.get("path_mappings") if isinstance(existing.get("path_mappings"), list) else [],
    })
    if updated is None:
        return existing if existing else None
    return updated


def confirm_or_edit_qb(settings: Dict[str, object]) -> Dict[str, str]:
    qb = settings.get("qb", {})
    if not isinstance(qb, dict):
        qb = {}

    if has_config_value(qb):
        display = f"当前 qBittorrent 配置：host={qb.get('host') or '-'}，username={qb.get('username') or '-'}"
        action = select_config_action(display)
        if action in {None, "back"}:
            return qb
        if action == "delete":
            if typer.confirm("确认删除 qBittorrent 配置？", default=False):
                return {}
            return qb
        typer.echo("请重新输入 qBittorrent 配置。")

    return prompt_qb_config({
        "host": qb.get("host", ""),
        "username": qb.get("username", ""),
        "password": qb.get("password", ""),
    })


def interactive_init(settings: Dict[str, object]) -> Dict[str, object]:
    selected = 0
    y_status = validate_yemapt_status(settings)
    q_status = validate_qb_status(settings)
    fs_status = validate_filesystems_status(settings)
    tr_status = validate_transmission_status(settings)
    while True:
        menu_items = {
            "1 yemapt": f"{y_status['display']}",
            "2 qb": f"{q_status['display']}",
            "3 transmission": f"{tr_status['display']}",
            "4 filesystems": f"{fs_status['display']}",
            "5 完成初始化": "",
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
            typer.echo("已取消初始化。")
            raise typer.Exit(code=0)
        if key == "ENTER":
            if selected == 0:
                previous = settings.get("yemapt", {})
                updated = confirm_or_edit_yemapt(settings)
                settings["yemapt"] = updated
                save_settings(settings)
                if updated != previous:
                    y_status = yemapt_status_from_config(settings)
            elif selected == 1:
                previous = settings.get("qb", {})
                updated = confirm_or_edit_qb(settings)
                settings["qb"] = updated
                save_settings(settings)
                if updated != previous:
                    q_status = qb_status_from_config(settings)
            elif selected == 2:
                clients = settings.setdefault("clients", {})
                if not isinstance(clients, dict):
                    clients = {}
                    settings["clients"] = clients
                previous = clients.get("transmission")
                transmission_config = confirm_or_edit_transmission(settings)
                if transmission_config == {}:
                    clients.pop("transmission", None)
                    save_settings(settings)
                elif transmission_config is not None:
                    clients["transmission"] = transmission_config
                    save_settings(settings)
                if transmission_config is not None and transmission_config != previous:
                    tr_status = transmission_status_from_config(settings)
            elif selected == 3:
                previous = normalize_filesystems(settings.get("filesystems"))
                updated = confirm_or_edit_filesystems(settings)
                settings["filesystems"] = updated
                save_settings(settings)
                if updated != previous:
                    fs_status = filesystems_status_from_config(settings)
                    tr_status = transmission_status_from_config(settings)
            elif selected == 4:
                return settings
            continue


def init_command():
    settings = load_settings()
    ensure_nested_settings(settings)

    typer.echo("开始初始化 yema 配置。")
    settings = interactive_init(settings)
    save_settings(settings)
    typer.secho("初始化完成。", fg="green")
