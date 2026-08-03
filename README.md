# Reciter Resources

这个仓库用于保存复读工作台可公开引用的文本类学习资源。

仓库名：`reciter-resources`  
远程 SSH：`git@github-andylee1890:andylee1890/reciter-resources.git`

## 目录结构

```text
resources/          # 字幕、LRC、REC、RECX 以及本地忽略的音频源文件
release-tools/      # 跨平台 Python 发布脚本
release-records/    # 每次发布或撤回的记录
```

## 资源边界

- `.srt`、`.lrc`、`.rec`、`.recx` 属于可版本化的文本资产，直接提交到 Git。
- `.mp3` 等音频文件不进入 Git 历史，按每一季或每个资料包上传到 GitHub Releases。
- 音频与文本文件需要保持同一个 basename，例如：

```text
The Office US S02E01 The Dundies.mp3
The Office US S02E01 The Dundies.srt
The Office US S02E01 The Dundies.rec
```

这样前端或复读机可以按文件名自动配对。

## 发布策略

每个季文件夹对应一个 Release tag，例如：

```text
the-office-s02-audio-v1
friends-s01-audio-v1
nce4-audio-v1
```

发布时只上传 `resources/` 下对应文件夹内的 `.mp3`。字幕、LRC、REC、RECX 保留在 Git 仓库中，通过提交版本固定。

发布脚本放在 `release-tools/`，发布记录放在 `release-records/`。

## 版权与撤回

本站资源按非盈利学习用途整理，早期发布状态可视为 `provisional`。不声称官方授权、正版合作或替代原始发行渠道。

如收到明确权利方要求，应按资源粒度撤下对应 Release asset、Release 或仓库文件，并在 `release-records/` 中记录处理结果。不要通过换仓库、换 tag 或换代理链接反复规避同一撤回请求。

## 常用命令

查看待提交的文本资产：

```powershell
git status --short
```

发布某一季音频：

```powershell
python release-tools/publish_season_release.py --folder resources/TheOfficeS02 --tag the-office-us-s02-audio-v1 --title "The Office US Season 02 Audio v1"
```

只预览不上传：

```powershell
python release-tools/publish_season_release.py --folder resources/TheOfficeS02 --tag the-office-us-s02-audio-v1 --title "The Office US Season 02 Audio v1" --dry-run
```
