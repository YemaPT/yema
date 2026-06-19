from __future__ import annotations

import os
import posixpath
import shlex
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from ftplib import FTP
from pathlib import Path
from typing import Any, Dict, Iterable, List

import typer

from yema.config.utils import is_debug_enabled, load_settings


class UnsupportedFileSystemError(RuntimeError):
    pass


class FileSystem:
    def read_file(self, path: str) -> bytes:
        raise NotImplementedError

    def list_files(self, limit: int = 20) -> List[str]:
        return []

    def list_directories(self, limit: int = 20) -> List[str]:
        return []

    def iter_torrent_files(self) -> Iterable[str]:
        return []

    def validate(self) -> None:
        return None


class LocalFileSystem(FileSystem):
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root).expanduser() if root else None

    def _resolve(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if candidate.is_absolute() or self.root is None:
            return candidate
        return self.root / candidate

    def read_file(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def validate(self) -> None:
        if self.root and not self.root.exists():
            raise UnsupportedFileSystemError(f"本地路径不存在: {self.root}")

    def list_files(self, limit: int = 20) -> List[str]:
        roots = [self.root] if self.root else _default_torrent_roots()
        result = []
        for root in roots:
            if root is None:
                continue
            root = root.expanduser()
            if not root.exists():
                continue
            for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if path.is_file():
                    result.append(str(path))
                    if len(result) >= limit:
                        return result
        return result

    def list_directories(self, limit: int = 20) -> List[str]:
        roots = [self.root] if self.root else _default_torrent_roots()
        result = []
        for root in roots:
            if root is None:
                continue
            root = root.expanduser()
            if not root.exists():
                continue
            for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if path.is_dir():
                    result.append(str(path))
                    if len(result) >= limit:
                        return result
        return result

    def iter_torrent_files(self) -> Iterable[str]:
        roots = []
        if self.root:
            roots.append(self.root)
        roots.extend(_default_torrent_roots())
        seen = set()
        for root in roots:
            root = root.expanduser()
            if not root.exists() or root in seen:
                continue
            seen.add(root)
            for path in root.rglob("*.torrent"):
                if path.is_file():
                    yield str(path)


class PlaceholderRemoteFileSystem(FileSystem):
    def __init__(self, fs_type: str) -> None:
        self.fs_type = fs_type

    def read_file(self, path: str) -> bytes:
        raise UnsupportedFileSystemError(f"{self.fs_type} 文件系统读取尚未实现。")

    def list_directories(self, limit: int = 20) -> List[str]:
        raise UnsupportedFileSystemError(f"{self.fs_type} 文件系统目录列表尚未实现。")

    def list_files(self, limit: int = 20) -> List[str]:
        raise UnsupportedFileSystemError(f"{self.fs_type} 文件系统文件列表尚未实现。")

    def iter_torrent_files(self) -> Iterable[str]:
        raise UnsupportedFileSystemError(f"{self.fs_type} 文件系统遍历尚未实现。")


class FTPFileSystem(FileSystem):
    def __init__(self, host: str, username: str = "", password: str = "", root: str = "", port: int = 21) -> None:
        self.host = host
        self.username = username or "anonymous"
        self.password = password or ""
        self.root = root or "/"
        self.port = port

    def _connect(self) -> FTP:
        ftp = FTP()
        ftp.connect(self.host, self.port, timeout=15)
        ftp.login(self.username, self.password)
        return ftp

    def _remote_path(self, path: str) -> str:
        if path.startswith("/"):
            return path
        return posixpath.join(self.root, path)

    def read_file(self, path: str) -> bytes:
        chunks = []
        remote_path = self._remote_path(path)
        with self._connect() as ftp:
            debug = is_debug_enabled()
            if debug:
                try:
                    pwd = ftp.pwd()
                except Exception as exc:
                    pwd = f"<获取失败: {exc}>"
                typer.echo(
                    "[DEBUG] FTP 读取文件: "
                    f"host={self.host}, "
                    f"port={self.port}, "
                    f"username={self.username}, "
                    f"pwd={pwd}, "
                    f"root={self.root}, "
                    f"input_path={path}, "
                    f"retr_path={remote_path}"
                )
            try:
                ftp.retrbinary(f"RETR {remote_path}", chunks.append)
            except Exception:
                if debug:
                    self._debug_list_paths(ftp, remote_path)
                raise
        return b"".join(chunks)

    def _debug_list_paths(self, ftp: FTP, remote_path: str) -> None:
        paths = ["/"]
        parent = posixpath.dirname(remote_path) or "/"
        if parent not in paths:
            paths.append(parent)
        for path in paths:
            try:
                entries = ftp.nlst(path)
            except Exception as exc:
                typer.echo(f"[DEBUG] FTP 目录列表失败: path={path}, error={exc}")
                continue
            preview = entries[:20]
            suffix = "" if len(entries) <= 20 else f" ... 共 {len(entries)} 项"
            typer.echo(f"[DEBUG] FTP 目录列表: path={path}, entries={preview}{suffix}")

    def validate(self) -> None:
        with self._connect() as ftp:
            ftp.nlst(self.root)

    def list_files(self, limit: int = 20) -> List[str]:
        with self._connect() as ftp:
            try:
                entries = list(ftp.mlsd(self.root))
            except Exception:
                return self._list_files_with_nlst(ftp, limit)
            result = []
            for name, facts in entries:
                if name in {".", ".."}:
                    continue
                if facts.get("type") == "file":
                    result.append(posixpath.join(self.root, name))
                    if len(result) >= limit:
                        break
            return result

    def _list_files_with_nlst(self, ftp: FTP, limit: int) -> List[str]:
        result = []
        for name in ftp.nlst(self.root):
            path = name if name.startswith("/") else posixpath.join(self.root, name)
            current = ftp.pwd()
            try:
                ftp.cwd(path)
            except Exception:
                result.append(path)
                if len(result) >= limit:
                    break
            finally:
                try:
                    ftp.cwd(current)
                except Exception:
                    pass
        return result

    def list_directories(self, limit: int = 20) -> List[str]:
        with self._connect() as ftp:
            try:
                entries = list(ftp.mlsd(self.root))
            except Exception:
                return self._list_directories_with_nlst(ftp, limit)
            result = []
            for name, facts in entries:
                if name in {".", ".."}:
                    continue
                if facts.get("type") == "dir":
                    result.append(posixpath.join(self.root, name))
                    if len(result) >= limit:
                        break
            return result

    def _list_directories_with_nlst(self, ftp: FTP, limit: int) -> List[str]:
        result = []
        for name in ftp.nlst(self.root):
            path = name if name.startswith("/") else posixpath.join(self.root, name)
            current = ftp.pwd()
            try:
                ftp.cwd(path)
            except Exception:
                continue
            finally:
                ftp.cwd(current)
            result.append(path)
            if len(result) >= limit:
                break
        return result

    def iter_torrent_files(self) -> Iterable[str]:
        with self._connect() as ftp:
            yield from self._walk(ftp, self.root, seen=set(), depth=0)

    def _walk(self, ftp: FTP, root: str, seen: set[str], depth: int) -> Iterable[str]:
        if depth > 64:
            raise UnsupportedFileSystemError(f"FTP 目录层级过深，已停止遍历: {root}")
        if root in seen:
            return
        seen.add(root)
        try:
            entries = list(ftp.mlsd(root))
        except Exception:
            for name in ftp.nlst(root):
                if name.lower().endswith(".torrent"):
                    yield name
            return
        for name, facts in entries:
            if name in {".", ".."}:
                continue
            path = posixpath.join(root, name)
            if facts.get("type") == "dir":
                yield from self._walk(ftp, path, seen, depth + 1)
            elif path.lower().endswith(".torrent"):
                yield path


class WebDAVFileSystem(FileSystem):
    def __init__(self, host: str, username: str = "", password: str = "", root: str = "") -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.root = "/" + root.strip("/") if root else ""

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        path = "/" + path.strip("/") if path else self.root
        if self.root and not path.startswith(self.root):
            path = self.root + path
        return f"{self.host}{urllib.parse.quote(path, safe='/:')}"

    def _headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "yema"}
        if self.username or self.password:
            import base64

            token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def read_file(self, path: str) -> bytes:
        request = urllib.request.Request(self._url(path), headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read()
        except urllib.error.URLError as exc:
            raise UnsupportedFileSystemError(f"读取 WebDAV 文件失败: {exc}") from exc

    def validate(self) -> None:
        headers = self._headers()
        headers["Depth"] = "0"
        request = urllib.request.Request(self._url(self.root), headers=headers, method="PROPFIND")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except urllib.error.URLError as exc:
            raise UnsupportedFileSystemError(f"连接 WebDAV 失败: {exc}") from exc

    def list_files(self, limit: int = 20) -> List[str]:
        headers = self._headers()
        headers["Depth"] = "1"
        request = urllib.request.Request(self._url(self.root), headers=headers, method="PROPFIND")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except urllib.error.URLError as exc:
            raise UnsupportedFileSystemError(f"列出 WebDAV 文件失败: {exc}") from exc

        root = ET.fromstring(body)
        result = []
        for response in root.findall("{DAV:}response"):
            href = response.find("{DAV:}href")
            resource_type = response.find(".//{DAV:}resourcetype")
            if href is None or not href.text:
                continue
            path = urllib.parse.unquote(href.text)
            if path.rstrip("/") == (self.root or "/").rstrip("/"):
                continue
            if resource_type is not None and resource_type.find("{DAV:}collection") is not None:
                continue
            result.append(path)
            if len(result) >= limit:
                break
        return result

    def list_directories(self, limit: int = 20) -> List[str]:
        headers = self._headers()
        headers["Depth"] = "1"
        request = urllib.request.Request(self._url(self.root), headers=headers, method="PROPFIND")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except urllib.error.URLError as exc:
            raise UnsupportedFileSystemError(f"列出 WebDAV 目录失败: {exc}") from exc

        root = ET.fromstring(body)
        result = []
        for response in root.findall("{DAV:}response"):
            href = response.find("{DAV:}href")
            resource_type = response.find(".//{DAV:}resourcetype")
            if href is None or not href.text or resource_type is None:
                continue
            if resource_type.find("{DAV:}collection") is None:
                continue
            path = urllib.parse.unquote(href.text)
            if path.rstrip("/") == (self.root or "/").rstrip("/"):
                continue
            result.append(path)
            if len(result) >= limit:
                break
        return result

    def iter_torrent_files(self) -> Iterable[str]:
        headers = self._headers()
        headers["Depth"] = "infinity"
        request = urllib.request.Request(self._url(self.root), headers=headers, method="PROPFIND")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except urllib.error.URLError as exc:
            raise UnsupportedFileSystemError(f"遍历 WebDAV 文件失败: {exc}") from exc

        root = ET.fromstring(body)
        for href in root.findall(".//{DAV:}href"):
            if href.text and href.text.lower().endswith(".torrent"):
                yield urllib.parse.unquote(href.text)


class SFTPFileSystem(FileSystem):
    def __init__(
        self,
        host: str,
        username: str = "",
        password: str = "",
        root: str = "",
        port: int = 22,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.root = root or "."
        self.port = port

    def _connect(self):
        try:
            import paramiko
        except ImportError as exc:
            raise UnsupportedFileSystemError("SFTP 读取需要安装 paramiko。") from exc
        transport = paramiko.Transport((self.host, self.port))
        transport.connect(username=self.username or None, password=self.password or None)
        return transport, paramiko.SFTPClient.from_transport(transport)

    def _remote_path(self, path: str) -> str:
        if path.startswith("/"):
            return path
        return posixpath.join(self.root, path)

    def read_file(self, path: str) -> bytes:
        transport, sftp = self._connect()
        try:
            with sftp.open(self._remote_path(path), "rb") as file:
                return file.read()
        finally:
            sftp.close()
            transport.close()

    def validate(self) -> None:
        transport, sftp = self._connect()
        try:
            sftp.stat(self.root)
        finally:
            sftp.close()
            transport.close()

    def list_files(self, limit: int = 20) -> List[str]:
        import stat

        transport, sftp = self._connect()
        try:
            result = []
            for entry in sftp.listdir_attr(self.root):
                if stat.S_ISREG(entry.st_mode):
                    result.append(posixpath.join(self.root, entry.filename))
                    if len(result) >= limit:
                        break
            return result
        finally:
            sftp.close()
            transport.close()

    def list_directories(self, limit: int = 20) -> List[str]:
        import stat

        transport, sftp = self._connect()
        try:
            result = []
            for entry in sftp.listdir_attr(self.root):
                if stat.S_ISDIR(entry.st_mode):
                    result.append(posixpath.join(self.root, entry.filename))
                    if len(result) >= limit:
                        break
            return result
        finally:
            sftp.close()
            transport.close()

    def iter_torrent_files(self) -> Iterable[str]:
        transport, sftp = self._connect()
        try:
            yield from self._walk(sftp, self.root, seen=set(), depth=0)
        finally:
            sftp.close()
            transport.close()

    def _walk(self, sftp, root: str, seen: set[str], depth: int) -> Iterable[str]:
        import stat

        if depth > 64:
            raise UnsupportedFileSystemError(f"SFTP 目录层级过深，已停止遍历: {root}")
        if root in seen:
            return
        seen.add(root)
        for entry in sftp.listdir_attr(root):
            path = posixpath.join(root, entry.filename)
            if stat.S_ISDIR(entry.st_mode):
                yield from self._walk(sftp, path, seen, depth + 1)
            elif path.lower().endswith(".torrent"):
                yield path


class SSHFileSystem(FileSystem):
    def __init__(
        self,
        host: str,
        username: str = "",
        password: str = "",
        root: str = "",
        port: int = 22,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.root = root or "/"
        self.port = port

    def _connect(self):
        try:
            import paramiko
        except ImportError as exc:
            raise UnsupportedFileSystemError("SSH 文件系统需要安装 paramiko。") from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.username or None,
            password=self.password or None,
            timeout=15,
        )
        return client

    def _remote_path(self, path: str) -> str:
        if path.startswith("/"):
            return path
        return posixpath.join(self.root, path)

    def _exec_bytes(self, command: str) -> bytes:
        client = self._connect()
        try:
            if is_debug_enabled():
                typer.echo(f"[DEBUG] SSH 执行命令: host={self.host}, port={self.port}, command={command}")
            _, stdout, stderr = client.exec_command(command, timeout=30)
            data = stdout.read()
            error = stderr.read().decode("utf-8", errors="replace").strip()
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                raise UnsupportedFileSystemError(f"SSH 命令失败: exit={exit_status}, stderr={error}")
            return data
        finally:
            client.close()

    def read_file(self, path: str) -> bytes:
        remote_path = self._remote_path(path)
        if is_debug_enabled():
            typer.echo(
                "[DEBUG] SSH 读取文件: "
                f"host={self.host}, "
                f"port={self.port}, "
                f"username={self.username}, "
                f"root={self.root}, "
                f"input_path={path}, "
                f"remote_path={remote_path}"
            )
        return self._exec_bytes(f"cat -- {shlex.quote(remote_path)}")

    def validate(self) -> None:
        self._exec_bytes(f"test -d {shlex.quote(self.root)}")

    def list_directories(self, limit: int = 20) -> List[str]:
        command = (
            f"find {shlex.quote(self.root)} -mindepth 1 -maxdepth 1 "
            f"-type d -print | head -n {int(limit)}"
        )
        output = self._exec_bytes(command).decode("utf-8", errors="replace")
        return [line.strip() for line in output.splitlines() if line.strip()]

    def list_files(self, limit: int = 20) -> List[str]:
        command = (
            f"find {shlex.quote(self.root)} -mindepth 1 -maxdepth 1 "
            f"-type f -print | head -n {int(limit)}"
        )
        output = self._exec_bytes(command).decode("utf-8", errors="replace")
        return [line.strip() for line in output.splitlines() if line.strip()]

    def iter_torrent_files(self) -> Iterable[str]:
        command = f"find {shlex.quote(self.root)} -type f -name '*.torrent' -print"
        output = self._exec_bytes(command).decode("utf-8", errors="replace")
        for line in output.splitlines():
            path = line.strip()
            if path:
                yield path


def _default_torrent_roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".config" / "transmission" / "torrents",
        home / "Library" / "Application Support" / "Transmission" / "Torrents",
        Path("/var/lib/transmission-daemon/info/torrents"),
    ]


def normalize_filesystems(filesystems: Any) -> list[Dict[str, Any]]:
    if isinstance(filesystems, list):
        normalized = []
        for index, fs in enumerate(filesystems):
            if not isinstance(fs, dict):
                continue
            fs_id = str(fs.get("id") or fs.get("name") or f"fs{index + 1}")
            if fs_id == "local":
                continue
            normalized.append({"id": fs_id, **fs})
        return normalized
    return []


def ensure_default_filesystems(settings: Dict[str, Any]) -> None:
    settings["filesystems"] = normalize_filesystems(settings.get("filesystems"))


def get_filesystem_map(settings: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    ensure_default_filesystems(settings)
    filesystems = {"local": {"id": "local", "type": "local", "name": "本地文件系统", "root": ""}}
    filesystems.update({
        str(fs.get("id")): fs for fs in normalize_filesystems(settings.get("filesystems")) if fs.get("id")
    })
    return filesystems


def get_filesystem_settings(filesystem_id: str | None) -> Dict[str, Any]:
    settings = load_settings()
    fs_id = filesystem_id or "local"
    filesystems = get_filesystem_map(settings)
    if fs_id not in filesystems:
        raise typer.Exit(code=1, message=f"文件系统 {fs_id} 未配置，请先运行 yema init。")
    fs = filesystems[fs_id]
    return fs


def create_filesystem(config: Dict[str, Any]) -> FileSystem:
    fs_type = str(config.get("type", "local")).lower()
    if fs_type == "local":
        root = str(config.get("root") or "").strip()
        return LocalFileSystem(root or None)
    if fs_type == "ftp":
        return FTPFileSystem(
            str(config.get("host") or ""),
            str(config.get("username") or ""),
            str(config.get("password") or ""),
            str(config.get("root") or ""),
            int(config.get("port") or 21),
        )
    if fs_type == "webdav":
        return WebDAVFileSystem(
            str(config.get("host") or ""),
            str(config.get("username") or ""),
            str(config.get("password") or ""),
            str(config.get("root") or ""),
        )
    if fs_type == "sftp":
        return SFTPFileSystem(
            str(config.get("host") or ""),
            str(config.get("username") or ""),
            str(config.get("password") or ""),
            str(config.get("root") or ""),
            int(config.get("port") or 22),
        )
    if fs_type == "ssh":
        return SSHFileSystem(
            str(config.get("host") or ""),
            str(config.get("username") or ""),
            str(config.get("password") or ""),
            str(config.get("root") or ""),
            int(config.get("port") or 22),
        )
    raise UnsupportedFileSystemError(f"未知文件系统类型: {fs_type}")


def validate_filesystem_config(config: Dict[str, Any]) -> None:
    create_filesystem(config).validate()


def find_torrent_file_by_hash(filesystem: FileSystem, info_hash: str) -> str | None:
    info_hash = info_hash.lower()
    for path in filesystem.iter_torrent_files():
        name = os.path.basename(path).lower()
        if info_hash in name:
            return path
    return None
