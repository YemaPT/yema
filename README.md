# yema

`yema` 是一个面向 yemapt、qBittorrent 和 Transmission 的命令行辅助工具，用来管理保种、检查站点收录情况，并辅助半自动转种。

## 功能

- 配置 yemapt `auth`、下载软件 Web API 登录信息，以及用于读取 `.torrent` 元数据的文件系统。
- 查看 qBittorrent 中的种子列表和种子详情。
- 基于 Pieces Hash 查找 qBittorrent 中内容完全相同的重复种子。
- 检查 qBittorrent 中的种子是否已经被 yemapt 收录。
- 检查 Transmission 中的种子是否已经被 yemapt 收录；Transmission 的 pieces hash 会从配置的文件系统读取 `.torrent` 文件计算。
- 显示已收录种子的 yemapt 种子 ID 和当前做种状态。
- 辅助补种：对已被 yemapt 收录但当前用户未做种的项目，下载新种并添加到 qBittorrent。
- 辅助转种：列出 qBittorrent 中尚未被 yemapt 收录的种子，并尽量展示来源站点详情页。

## 安装

使用安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/YemaPT/yema/main/install.sh | sh
```

如果已经下载源码，也可以在项目目录执行：

```bash
./install.sh
```

脚本会使用当前 Python 的用户目录安装，并在 `yema` 不在 `PATH` 时自动写入当前 shell 的 profile。

从 PyPI 安装：

```bash
pip install yema
```

如果使用 `uv`：

```bash
uv tool install yema
```

源码运行：

```bash
git clone https://github.com/YemaPT/yema.git
cd yema
uv sync
uv run yema --help
```

## 初始化

首次使用建议运行交互式初始化：

```bash
yema init
```

初始化可配置：

- yemapt auth
- qBittorrent Web API 地址、用户名和密码
- Transmission RPC 地址、用户名、密码，选择一个文件系统，并配置可选路径映射。Docker 场景下，路径映射应填写 Docker 文件夹映射关系：Transmission/容器内路径映射到文件系统/宿主机路径。
- 文件系统：`local` 内置可用、不需要保存到配置；也支持配置多个 WebDAV、FTP、SFTP 和 SSH；远程文件系统保存前会校验可访问

已有配置项在初始化主菜单中选中后，按回车可选择修改或删除；删除前会二次确认。文件系统列表中，远程文件系统按顺序显示为“文件系统 1/2/3”。

这些配置项都是可选的；只有在运行相关命令时才要求对应配置存在。交互式初始化中如果选择配置某一项，工具会先验证连接或 auth 有效，验证通过后才保存。

配置会保存到：

```text
~/.yema/setting.json
```

查看当前配置：

```bash
yema config
```

## 常用命令

进入 qBittorrent 操作菜单：

```bash
yema qb
```

菜单中支持：

- `list`：查看 qBittorrent 当前种子列表。
- `pieces_dedup`：按 Pieces Hash 查找重复内容。

检查 qBittorrent 种子是否已被 yemapt 收录：

```bash
yema check
```

如果同时配置了 qBittorrent 和 Transmission，`check`、`pub` 会先让你选择来源，默认是全部。`seed -y` 会自动处理全部来源；如需限制 `seed` 来源，可使用 `--client qb` 或 `--client tr`。

辅助保种：

```bash
yema seed
```

`seed` 会分析 qBittorrent 中的种子，找出已被 yemapt 收录但当前用户未做种的项目。默认执行前会逐个确认，不会自动批量修改。如需自动确认所有候选项，可使用：

```bash
yema seed -y
```

只处理指定下载软件：

```bash
yema seed --client qb
yema seed --client tr
yema seed --client qb --tracker mteam
```

辅助转种：

```bash
yema pub
yema pub --client qb
yema pub --client tr
yema pub --urls --client qb
yema pub --urls --client qb --tracker mteam
```

`pub` 会列出下载软件中尚未被 yemapt 收录的种子，并显示 tracker 来源。对于部分站点，工具会尝试解析并展示详情页 URL，方便手动转种。

加上 `--urls` 后，`pub` 只处理已下载完成的种子，并直接输出可解析出的详情页 URL，每行一个，方便交给下一个程序处理。可用 `--client qb` 或 `--client tr` 限制来源。交互式列表会显示下载状态，未完成的种子不会生成详情页 URL。

`seed` 和 `pub` 都支持 `--tracker` 筛选。筛选值会匹配 tracker URL、tracker 域名和内置显示名，例如 `--tracker mteam` 或 `--tracker tracker.m-team.cc`。

Transmission：

```bash
yema tr
yema tr-check
```

`tr-check` 会通过 Transmission RPC 获取种子列表和 tracker，再通过配置的文件系统读取 `.torrent` 文件计算 Pieces Hash。当前支持本地、WebDAV、FTP；SFTP 使用可选的 `paramiko` adapter。若 Transmission 运行在 Docker 中，Transmission 接口返回的通常是容器内路径，而文件系统登录后看到的是宿主机路径，因此需要配置路径映射。映射内容就是 Docker 文件夹映射关系，例如服务器的 `/xxx/transmission/config` 映射到容器的 `/config`，则应配置 `from=/config`、`to=/xxx/transmission/config`。后续 Transmission 返回 `/config/aaa.torrent` 时，程序会映射回 `/xxx/transmission/config/aaa.torrent` 读取。

如果按候选路径找不到 `.torrent` 文件，程序不会递归扫描目录，而是列出当前文件系统登录目录下的前 20 个文件，方便核对实际可见路径。

## Debug

启用 debug：

```bash
yema config debug enable
```

关闭 debug：

```bash
yema config debug disable
```

debug 模式会输出 qBittorrent 和 yemapt 请求过程，适合排查登录失败、接口失败、下载种子失败等问题。较长的响应内容会写入当前目录的 `tmp/` 下。

## 缓存

工具会在 `~/.yema/` 下保存本地缓存，用于减少重复请求：

- qBittorrent 种子的 Pieces Hash
- tracker 信息
- yemapt Pieces Hash 查询结果

如果发现结果明显不符合预期，可以删除 `~/.yema/` 下对应缓存文件后重试。

## 注意事项

- 需要先启用 qBittorrent Web UI，并确保当前机器可以访问 Web API。
- `seed` 添加新种时会使用原 qBittorrent 种子的保存路径，并开启跳过校验添加。
- 替换已有非当前用户 yemapt 做种时，工具只删除 qBittorrent 中的旧任务，不删除本地文件。
- `pub` 只是辅助列出未收录种子，不会自动发布到 yemapt。

## 配置示例

```json
{
  "yemapt": {
    "auth": "YOUR_YEMAPT_AUTH"
  },
  "qb": {
    "host": "http://127.0.0.1:8080",
    "username": "qbuser",
    "password": "qbpass"
  },
  "filesystems": [],
  "clients": {
    "transmission": {
      "host": "http://127.0.0.1:9091",
      "username": "",
      "password": "",
      "filesystem": "local",
      "path_mappings": [
        {
          "from": "/config",
          "to": "/xxx/transmission/config"
        }
      ]
    }
  },
  "debug": false
}
```

远程文件系统配置示例：

```json
{
  "filesystems": [
    {
      "id": "nas-webdav",
      "type": "webdav",
      "host": "https://nas.example.com/dav",
      "username": "user",
      "password": "pass",
      "root": "/downloads/transmission/torrents"
    },
    {
      "id": "seedbox-sftp",
      "type": "sftp",
      "host": "192.168.1.10",
      "port": 22,
      "username": "seedbox",
      "password": "pass",
      "root": "/home/seedbox/.config/transmission/torrents"
    },
    {
      "id": "nas-ssh",
      "type": "ssh",
      "host": "192.168.1.10",
      "port": 22,
      "username": "seedbox",
      "password": "pass",
      "root": "/vol1/@appdata/transmission/torrents"
    },
    {
      "id": "seedbox-ftp",
      "type": "ftp",
      "host": "ftp.example.com",
      "port": 21,
      "username": "user",
      "password": "pass",
      "root": "/transmission/torrents"
    }
  ]
}
```
