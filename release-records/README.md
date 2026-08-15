# 发布记录

这里保存每次 GitHub Release 发布时生成的记录。

记录文件应包含：

- release tag
- 发布标题
- 来源文件夹
- 音频文件数量和总大小
- GitHub Release 页面链接
- 每个音频的 GitHub Release 下载链接
- 每个文本 sidecar 的 GitHub Raw 链接
- 每个文本 sidecar 的 jsDelivr CDN 链接
- 每个音频对应的字幕/rec sidecar 情况
- 已上传时的 Internet Archive item 标识和页面链接
- 是否为 dry run

`index.json` 是从已发布记录生成的机器可读主索引，只包含 `Published: True` 的 Release。主索引同时包含 `releases`（课程摘要及其 `poster`）和 `posters`（完整海报清单），站点通常只需请求这一个文件；`posterIndex` 保留为独立海报索引的兼容引用。每个已发布资料包另有同 tag 的 JSON 明细文件；需要音频明细时再按 `detailFile` 读取。普通 GitHub Release 资料包在 `platforms.githubRelease.releaseUrl` 提供发布页；分段资料包则在 `platforms.githubRelease.releaseUrls` 提供多个发布页，而每个音频仍通过 `audio.githubRelease` 指向其所属 part 的直链。Internet Archive 等资料包页面镜像位于 `platforms.mirrors`，单个 MP3 的直接镜像位于 `audio.mirrors`；已镜像的字幕、LRC、REC、RECX 链接位于对应 `sidecars.internetArchive`。

如果某个资源因权利方要求撤下，也在这里追加处理说明，方便以后追踪替代策略。
