# Release Tools

这里保存维护者使用的发布脚本。根目录 `README.md` 面向外部使用者，本目录只记录脚本、依赖和发布流程。

脚本使用 Python、`pycurl`、Internet Archive 官方 `internetarchive` 库和 GitHub CLI，避免 PowerShell、CMD、Bash 等操作系统相关发布脚本。

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
| `--record-only` | 只生成发布记录，不创建 Release、不上传音频。 |
| `--published` | 配合 `--record-only`，标记已通过其他方式实际发布的 Release。 |
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

`generate_release_index.py` 从 `release-records/*.md` 生成站点可直接消费的 `release-records/index.json`，以及每个已发布资料包的 `release-records/<tag>.json`。
它只收录 `Published: True` 的记录。主索引只列资料包摘要和明细文件名；每个资料包 JSON 保留音频的 GitHub Release 地址、镜像数组、GitHub Raw sidecar 和 jsDelivr sidecar 链接。只有远端逐文件校验通过的 Internet Archive 条目才会进入 `platforms.mirrors` 和每首音频的 `audio.mirrors`。ZIP 归档不会进入播放镜像字段，避免前端把 ZIP 误当作 MP3 直链。

```bash
python release-tools/generate_release_index.py
```

每次新增、撤回或修改发布记录后，都应重新生成并提交该索引。

## Internet Archive 完整资料包镜像

`publish_to_internet_archive.py` 把一个 `release-plan.json` 资料包的 `.mp3`、`.srt`、`.lrc`、`.rec`、`.recx` 一起上传为一个 Internet Archive item。默认 identifier 是 `reciter-<tag>`；GitHub Raw 和 jsDelivr 链接继续保留为文本 sidecar 的备用入口。

对于大资料包，`publish_ia_bundle.py` 可在同一个 IA item 上传 ZIP 作为归档备份。ZIP 不属于网页逐条播放资源，也不会被索引生成器写入播放镜像；网页播放应使用 `publish_to_internet_archive.py` 上传并校验每个 MP3 文件后生成的逐文件直链。临时 ZIP 只能保存在仓库外的 artifact 目录。

```bash
python release-tools/publish_ia_bundle.py \
  --tag friends-s09-audio-v1 \
  --credentials-file /private/path/ia-credentials.json \
  --artifact-dir /artifact/path
```

元数据入库延迟时，使用 `--verify-only` 只检查已上传 ZIP，绝不重传也不重建已有 ZIP：

```bash
python release-tools/publish_ia_bundle.py \
  --tag friends-s09-audio-v1 \
  --artifact-dir /artifact/path \
  --verify-only
```

安装官方 Python 客户端：

```bash
python -m pip install pycurl internetarchive
```

凭据不进入仓库。通过环境变量 `IA_ACCESS_KEY`、`IA_SECRET_KEY`，或仓库外的 JSON 文件提供：

```json
{"access_key":"...","secret_key":"..."}
```

先检查一个资料包：

```bash
python release-tools/publish_to_internet_archive.py \
  --tag new-concept-english-1-us-audio-v1 \
  --dry-run
```

实际上传并在远端逐文件校验：

```bash
python release-tools/publish_to_internet_archive.py \
  --tag new-concept-english-1-us-audio-v1 \
  --credentials-file /private/path/ia-credentials.json
```

中断后再次执行会按文件名和字节大小跳过已完成文件。默认使用 `pycurl` 直连 IA S3 并为每个文件重试 10 次；`--transport internetarchive` 使用 IA 官方客户端，`--transport stdlib` 可回退到内置分块 HTTPS 上传。`--direct` 仅作用于后两种 Python HTTP 传输。`--verify-only` 不需要凭据，只校验 item 是否完整。脚本默认等待最多 300 秒让 IA metadata 入库，上传和校验通过后才在发布记录写入 IA identifier、item URL，并重建 JSON 索引。

## 批量发布

`publish_all_to_internet_archive.py` 顺序处理 `release-plan.json` 中尚未完成 IA 镜像的资料包。它只以发布计划为输入，不会扫描或处理计划外目录；已在发布记录中标记 `Internet Archive uploaded: True` 的资料包会自动跳过。

```bash
python release-tools/publish_all_to_internet_archive.py \
  --credentials-file /private/path/ia-credentials.json \
  --push
```

`--push` 会在每个资料包完成远端逐文件校验后，仅提交该资料包记录、明细 JSON 和主索引，再推送到当前 Git remote。网络中断后直接重跑同一命令即可继续；用 `--dry-run` 查看剩余队列，或用 `--tag <tag>` 只处理指定资料包。

`publish_all_ia_bundles.py` 是完整 ZIP 镜像的顺序队列。它只处理发布记录中尚未有 `Internet Archive bundle` 的计划项；每个 ZIP 都含音频和对应 `.srt`、`.lrc`、`.rec`、`.recx`，远端字节校验成功后才更新索引。以 `--push` 运行时，每包完成后都会提交并推送，网络中断后直接重跑即可跳过已完成的包。

```bash
python release-tools/publish_all_ia_bundles.py \
  --credentials-file /private/path/ia-credentials.json \
  --artifact-dir /artifact/path \
  --push
```

## 资料包清单

`release-plan.json` 保存资料目录、Release tag 和标题，是整批发布及 AI 协作时使用的公开清单；它不包含本机账号、浏览器配置、SSH 别名或其他私有环境信息。
