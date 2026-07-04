# AGENTS.MD

本文档为代码代理和维护者提供本仓库的项目约定。

## 项目概览

`yema` 是一个 Python CLI 工具，用于 yemapt 保种、种子检查，以及半自动转种/补种流程。项目代码位于 `yema/` 目录，CLI 入口通过 `pyproject.toml` 中的 `project.scripts` 暴露：

```bash
uv run yema --help
```

本项目使用 `uv` 管理依赖和运行环境。不要假设依赖已经全局安装，也不要手动维护虚拟环境。

## 环境与依赖管理

- 使用 `uv sync` 根据 `pyproject.toml` 和 `uv.lock` 安装或更新开发环境。
- 使用 `uv run ...` 运行项目命令。
- 依赖变更应写入 `pyproject.toml`，并用 `uv` 刷新 `uv.lock`。
- 除非任务明确要求发布产物，否则不要修改 `dist/` 下的生成文件。

常用命令：

```bash
uv sync
uv run yema --help
uv run python -m yema.main --help
```

如果需要在受限沙箱中做字节码编译，避免 Python 写入用户缓存目录：

```bash
PYTHONPYCACHEPREFIX=/tmp/yema_pycache uv run python -m compileall yema
```

## 目录结构

- `yema/main.py`：Typer CLI 入口和顶层命令注册。
- `yema/init.py`：交互式初始化和配置校验。
- `yema/config/`：配置展示和 debug 开关命令。
- `yema/commands/`：下载软件相关命令流程。
- `yema/clients/`：qBittorrent、Transmission、yemapt 以及未来客户端的 HTTP/RPC 对接代码。
- `yema/services/`：种子检查、分组、PT 查询等共享业务流程。
- `yema/domain/`：tracker 解析、种子元数据解析等纯领域逻辑。
- `yema/filesystems/`：用于读取 `.torrent` 元数据的本地和远程文件系统 adapter。
- `yema/storage/`：`~/.yema` 下的本地缓存读写。
- `yema/ui/`：终端 UI、分页和详情展示。

## 配置与敏感信息

运行时配置存储在 `~/.yema/setting.json`，不应放入仓库。

禁止提交：

- 真实 yemapt auth token
- qBittorrent 或 Transmission 密码
- 包含 passkey 的 tracker URL
- `.torrent` 文件
- debug 日志或缓存文件

如果修改了用户可见配置，需要同步更新 `README.md`，并尽量保持向后兼容。现有 qBittorrent 配置使用 `qb` key；新的多客户端配置可以使用 `clients`。

## 开发约定

- 优先使用标准库和项目已有模式，再考虑新增依赖。
- 客户端协议代码放在 `yema/clients/`。
- 可复用的种子业务逻辑放在 `yema/services/` 或 `yema/domain/`。
- 文件系统访问必须通过 `yema/filesystems/` adapter。
- 新客户端不要直接耦合 qBittorrent 专用 helper。
- 除非任务明确要求，否则保持现有 CLI 行为不变。
- 面向终端用户的错误信息使用简洁中文，风格与现有代码保持一致。
- 项目支持 Python 3.9；新增或修改包含 `X | Y`、`str | None` 等 PEP 604 类型注解的模块时，必须添加 `from __future__ import annotations`，否则请使用 `typing.Optional` / `typing.Union`。

下载软件集成约定：

- 将不同客户端返回的种子信息规范化为共享服务期望的字段，尤其是 `hash`、`name`、`size`、`added_on`、`progress`、`ratio`、`save_path`。
- 如果客户端 API 不能提供 pieces hash，应通过配置的文件系统读取 `.torrent` 元数据，并从 `info.pieces` 计算。
- tracker 提取逻辑保留在客户端侧，再把规范化后的 tracker URL 传入共享服务。

文件系统约定：

- `local` 应该无需额外配置即可工作。
- WebDAV 和 FTP 在标准库足够时不要引入额外依赖。
- SFTP 可以使用可选依赖；依赖缺失时必须给出清晰错误。

## 验证

至少运行：

```bash
PYTHONPYCACHEPREFIX=/tmp/yema_pycache uv run python -m compileall yema
uv run yema --help
```

如果修改了 CLI 行为，还应运行相关命令的 help 或安全路径：

```bash
uv run yema config
uv run yema qb --help
uv run yema tr --help
```

如条件允许，网络集成应使用非生产的 qBittorrent、Transmission 和 yemapt 环境手动验证。不要在日志、fixture 或文档中暴露真实凭据。

## 文档维护

新增或修改以下内容时，需要更新 `README.md`：

- 命令
- 必需配置
- 支持的下载软件
- 支持的文件系统类型
- 用户可见行为

只有贡献流程本身发生变化时，才更新 `CONTRIBUTING.md`。

## Git 约定

- 保持改动聚焦。
- 不要回滚与当前任务无关的用户改动。
- 不要提交本地缓存、debug 输出、构建产物或凭据。
- 完成前检查 `git status --short`，并说明哪些未跟踪文件属于本次改动。
