# yema

`yema` 是一个面向 yemapt 和 qBittorrent 的命令行辅助工具，用来管理保种、检查站点收录情况，并辅助半自动转种。

## 功能

- 配置 yemapt `auth` 和 qBittorrent Web API 登录信息。
- 查看 qBittorrent 中的种子列表和种子详情。
- 基于 Pieces Hash 查找 qBittorrent 中内容完全相同的重复种子。
- 检查 qBittorrent 中的种子是否已经被 yemapt 收录。
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

初始化会依次配置：

- yemapt auth
- qBittorrent Web API 地址、用户名和密码

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

辅助保种：

```bash
yema seed
```

`seed` 会分析 qBittorrent 中的种子，找出已被 yemapt 收录但当前用户未做种的项目。执行前会逐个确认，不会自动批量修改。

辅助转种：

```bash
yema pub
```

`pub` 会列出 qBittorrent 中尚未被 yemapt 收录的种子，并显示 tracker 来源。对于部分站点，工具会尝试解析并展示详情页 URL，方便手动转种。

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
  "debug": false
}
```
