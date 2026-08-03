# Release Tools

这里保存维护者使用的发布脚本。根目录 `README.md` 面向外部使用者，本目录只记录脚本、依赖和发布流程。

脚本使用 Python 标准库和 GitHub CLI，避免 PowerShell、CMD、Bash 等操作系统相关发布脚本。

## 前置条件

1. 已安装 GitHub CLI：`gh --version`
2. 已登录 GitHub CLI：`gh auth login`
3. 当前目录是本仓库根目录。

## 发布脚本

`publish_season_release.py` 会：

- 检查目标文件夹是否存在。
- 收集该文件夹内的 `.mp3`。
- 检查是否有同 basename 的 `.srt`、`.lrc`、`.rec` 或 `.recx`。
- 为文本 sidecar 生成 GitHub Raw 和 jsDelivr 链接。
- 为音频生成 GitHub Release 下载链接。
- 创建或复用指定 GitHub Release。
- 上传 `.mp3` 到该 Release。
- 在 `release-records/` 生成一份 Markdown 发布记录，可直接给产品配置或人工核对使用。

默认不会上传已存在的同名 asset。需要覆盖时使用 `--clobber`。

## 示例

```bash
python release-tools/publish_season_release.py \
  --folder resources/TheOfficeS02 \
  --tag the-office-us-s02-audio-v1 \
  --title "The Office US Season 02 Audio v1" \
  --dry-run
```

实际上传时去掉 `--dry-run`：

```bash
python release-tools/publish_season_release.py \
  --folder resources/TheOfficeS02 \
  --tag the-office-us-s02-audio-v1 \
  --title "The Office US Season 02 Audio v1"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--folder` | 要发布音频的资源目录，通常位于 `resources/` 下。 |
| `--tag` | GitHub Release tag，例如 `the-office-us-s02-audio-v1`。 |
| `--title` | GitHub Release 标题。 |
| `--repo` | GitHub 仓库，默认 `andylee1890/reciter-resources`。 |
| `--branch` | 文本资源引用分支，默认 `main`。 |
| `--dry-run` | 只生成发布记录，不创建 Release、不上传音频。 |
| `--clobber` | 上传时覆盖 Release 中已有的同名 asset。 |

## 发布记录

脚本会把记录写入 `release-records/<tag>.md`。记录内包含：

- GitHub Release 页面。
- 音频 Release asset 下载链接。
- 文本资源 GitHub Raw 链接。
- 文本资源 jsDelivr CDN 链接。
- 每个音频的大小和 sidecar 状态。

如果收到权利方要求撤回资源，不要复用旧 tag 绕过，应撤下对应 asset 或 Release，并在同一条发布记录中追加处理说明。

## 索引生成

`generate_release_index.py` 从 `release-records/*.md` 生成站点可直接消费的 `release-records/index.json`。
它只收录 `Dry run: False` 的记录，并为每条音频保留 Release 下载、GitHub Raw sidecar 和 jsDelivr sidecar 链接。

```bash
python release-tools/generate_release_index.py
```

每次新增、撤回或修改发布记录后，都应重新生成并提交该索引。
