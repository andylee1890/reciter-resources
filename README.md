# Reciter Resources

这个仓库保存复读、跟读、字幕对齐等学习场景可直接引用的公开文本资源。

仓库地址：[https://github.com/andylee1890/reciter-resources](https://github.com/andylee1890/reciter-resources)

## 如何引用

文本资源位于 `resources/`，可以通过 GitHub Raw 或 jsDelivr 引用。

GitHub Raw:

`https://raw.githubusercontent.com/andylee1890/reciter-resources/main/resources/...`

jsDelivr:

`https://cdn.jsdelivr.net/gh/andylee1890/reciter-resources@main/resources/...`

音频资源不提交到 Git 历史，按资料包或季发布到 GitHub Releases，并可同步到 Internet Archive 作为独立镜像。每次发布的可用链接记录在 [release-records](https://github.com/andylee1890/reciter-resources/tree/main/release-records)。

## 机器可读索引

已发布的资料包、音频下载地址和配套文本链接汇总在 JSON 索引中；未实际发布的 dry run 记录不会进入索引。

- GitHub Raw：`https://raw.githubusercontent.com/andylee1890/reciter-resources/main/release-records/index.json`
- jsDelivr：`https://cdn.jsdelivr.net/gh/andylee1890/reciter-resources@main/release-records/index.json`

## 资源边界

- `.srt`、`.lrc`、`.rec`、`.recx` 属于可版本化的文本资产，直接提交到 Git。
- `.mp3` 等音频文件不进入 Git 历史，按每一季或每个资料包上传到 GitHub Releases；已同步的资料包会在索引中提供 Internet Archive 镜像。
- 音频与文本文件保持同一个 basename，方便前端自动配对，例如：

```text
The Office US S02E01 The Dundies.mp3
The Office US S02E01 The Dundies.srt
The Office US S02E01 The Dundies.rec
```

## 目录

- [resources](https://github.com/andylee1890/reciter-resources/tree/main/resources)：字幕、LRC、REC、RECX 等文本资源。
- [release-records](https://github.com/andylee1890/reciter-resources/tree/main/release-records)：音频发布、链接索引和撤回记录。

## 使用说明

本仓库面向非盈利学习用途整理资源，不声称官方授权、正版合作或替代原始发行渠道。

如果明确权利方要求撤下某项资源，会按资源粒度处理对应文件或 Release，并在发布记录中留下处理说明。
