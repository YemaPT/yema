import sys
import termios
import tty
from typing import Dict

import typer

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
