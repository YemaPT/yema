import sys
from typing import Dict

import typer

def read_key() -> str:
    # Windows: read directly from the console input buffer via msvcrt.
    # This avoids the POSIX-only termios/tty modules entirely.
    if sys.platform.startswith("win"):
        import msvcrt

        ch = msvcrt.getwch()
        if ch == "\x1b":
            return "ESC"
        if ch == "\r":
            return "ENTER"
        if ch in ("\x00", "\xe0"):
            second = msvcrt.getwch()
            if second == "H":
                return "UP"
            if second == "P":
                return "DOWN"
            if second == "M":
                return "RIGHT"
            if second == "K":
                return "LEFT"
            return second
        return ch

    # POSIX: raw terminal mode via termios/tty.
    import termios
    import tty

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
                if third == "C":
                    return "RIGHT"
                if third == "D":
                    return "LEFT"
            return "ESC"
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
    for index, (title, desc) in enumerate(items.items()):
        prefix = "▶" if index == selected else "  "
        if index == selected:
            typer.secho(f"{prefix} {title} {desc}", fg="cyan")
        else:
            typer.echo(f"{prefix} {title} {desc}")
    typer.echo("")
