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
- 是否为 dry run

`index.json` 是从已发布记录生成的机器可读主索引，只包含 `Published: True` 的 Release。每个已发布资料包另有同 tag 的 JSON 明细文件；站点先读取主索引，再按 `detailFile` 读取资料包明细。音频的其他平台镜像保留在明细的 `audio.mirrors` 数组中。

如果某个资源因权利方要求撤下，也在这里追加处理说明，方便以后追踪替代策略。
