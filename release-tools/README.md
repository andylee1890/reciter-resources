# Release Tools

这里保存 GitHub Release 发布脚本。脚本使用 Python 标准库和 GitHub CLI，避免 PowerShell、CMD、Bash 等操作系统相关脚本。

## 前置条件

1. 已安装 GitHub CLI：`gh --version`
2. 已登录 GitHub CLI：`gh auth login`
3. 当前目录是本仓库根目录。

## 发布脚本

`publish_season_release.py` 会：

- 检查目标文件夹是否存在。
- 收集该文件夹内的 `.mp3`。
- 检查是否有同 basename 的 `.srt`、`.lrc`、`.rec` 或 `.recx`。
- 创建或复用指定 GitHub Release。
- 上传 `.mp3` 到该 Release。
- 在 `release-records/` 生成一份 Markdown 发布记录。

默认不会上传已存在的同名 asset。需要覆盖时使用 `--clobber`。

## 示例

```bash
python release-tools/publish_season_release.py \
  --folder resources/TheOfficeS02 \
  --tag the-office-us-s02-audio-v1 \
  --title "The Office US Season 02 Audio v1" \
  --dry-run
```
