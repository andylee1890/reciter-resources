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

## RECX 波形生成

`generate_recx.py` 为音频生成兼容 EasyTyeReciter 的 `.recx` sidecar。它使用
FFmpeg 解码为 44.1kHz 双声道 PCM，再按 100ms 峰值波形、99.5% 分位归一化和
0.55 gamma 压缩生成 legacy Float64 little-endian wave data。生成文件只包含共享的
音频波形与同名字幕，不包含任何用户播放、复读或学习状态。

支持单个音频或整个目录，目录默认递归扫描 `.mp3`、`.wav`、`.m4a`、`.aac`、
`.ogg`、`.flac`、`.opus`、`.wma`、`.aiff` 和 `.aif`。输出始终是音频同目录下的
同 basename `.recx`，默认跳过已经存在的 `.recx`；加入 `--overwrite` 才会覆盖。
若存在同 basename `.srt`、`.vtt` 或 `.lrc`，会自动写入字幕 tag。

```bash
# 单个文件
python release-tools/generate_recx.py "resources/TheOfficeS01/example.mp3"

# 整个目录（默认递归）
python release-tools/generate_recx.py "resources/TheOfficeS01"

# 先查看将处理的文件，或只扫描目录顶层
python release-tools/generate_recx.py "resources/TheOfficeS01" --dry-run
python release-tools/generate_recx.py "resources/TheOfficeS01" --no-recursive
```

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
它只收录 `Published: True` 的记录。主索引只列资料包摘要和明细文件名；每个资料包 JSON 保留实际配置的音频投递方式、镜像数组、GitHub Raw sidecar 和 jsDelivr sidecar 链接。只有远端逐文件校验通过的 Internet Archive 条目才会进入 `platforms.mirrors` 和每首音频的 `audio.mirrors`。

```bash
python release-tools/generate_release_index.py
```

每次新增、撤回或修改发布记录后，都应重新生成并提交该索引。

## Internet Archive 逐文件镜像

`publish_to_internet_archive.py` 把一个 `release-plan.json` 资料包的 `.mp3`、`.srt`、`.lrc`、`.rec`、`.recx` 一起上传为一个 Internet Archive item。默认 identifier 是 `reciter-<tag>`；GitHub Raw 和 jsDelivr 链接继续保留为文本 sidecar 的备用入口。

Archive 条目只允许逐文件上传。每个 `.mp3`、`.srt`、`.lrc`、`.rec`、`.recx` 都必须有可引用的 Archive 直链；不使用压缩包作为发布或播放交付方式。

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

当本地资料目录不可用、但已发布的 GitHub Release 音频和 GitHub Raw sidecar 仍可访问时，`recover_and_publish_ia_package.py` 会把每个公开文件恢复到仓库外的临时目录，再逐文件上传并校验 Archive。恢复成功后默认删除临时文件。

```bash
python release-tools/recover_and_publish_ia_package.py \
  --tag new-concept-english-1-us-audio-v1 \
  --staging-dir /artifact/path \
  --credentials-file /private/path/ia-credentials.json
```

`recover_and_publish_all_ia_packages.py` 按发布计划顺序处理尚未完成逐文件 Archive 镜像的资料包。每套完成远端字节校验后可立即提交并推送该套记录与索引；网络中断后重跑同一命令会跳过已完成的 IA 文件和资料包。

```bash
python release-tools/recover_and_publish_all_ia_packages.py \
  --staging-dir /artifact/path \
  --credentials-file /private/path/ia-credentials.json \
  --push
```

中断后再次执行会按文件名和字节大小跳过已完成文件。默认使用 `pycurl` 直连 IA S3 并为每个文件重试 10 次；`--transport internetarchive` 使用 IA 官方客户端，`--transport stdlib` 可回退到内置分块 HTTPS 上传。`--direct` 仅作用于后两种 Python HTTP 传输。`--verify-only` 不需要凭据，只校验 item 是否完整。脚本默认等待最多 300 秒让 IA metadata 入库，上传和校验通过后才在发布记录写入 IA identifier、item URL，并重建 JSON 索引。

网络不稳定时可加 `--continue-on-error`，让单个文件重试耗尽后继续队列；命令仍会因最终逐文件校验不完整而返回失败，便于下一次只补传缺失文件。

## Internet Archive-only 资料包

当 `release-plan.json` 的资料包指定 `"audioDelivery": "internetArchive"` 时，先生成不包含 GitHub Release 的发布记录：

```bash
python release-tools/publish_archive_only_package.py \
  --tag american-accent-training-4e-audio-v1
```

然后使用 `publish_to_internet_archive.py` 上传。音频和所有配套字幕均逐文件上传、校验，并在索引中只提供 Internet Archive 音频直链；不会创建 GitHub Release。

## 批量发布

`publish_all_to_internet_archive.py` 顺序处理 `release-plan.json` 中尚未完成 IA 镜像的资料包。它只以发布计划为输入，不会扫描或处理计划外目录；已在发布记录中标记 `Internet Archive uploaded: True` 的资料包会自动跳过。

```bash
python release-tools/publish_all_to_internet_archive.py \
  --credentials-file /private/path/ia-credentials.json \
  --push
```

`--push` 会在每个资料包完成远端逐文件校验后，仅提交该资料包记录、明细 JSON 和主索引，再推送到当前 Git remote。网络中断后直接重跑同一命令即可继续；用 `--dry-run` 查看剩余队列，或用 `--tag <tag>` 只处理指定资料包。

## 资料包清单

`release-plan.json` 保存资料目录、Release tag 和标题，是整批发布及 AI 协作时使用的公开清单；它不包含本机账号、浏览器配置、SSH 别名或其他私有环境信息。
