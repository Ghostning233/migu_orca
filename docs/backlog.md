# MiGuOrca Backlog

本文件记录已发现但不阻塞当前阶段推进的后续优化事项。进入新 Stage 或编写 Ralph PRD 时，应先检查本文件，决定是否纳入当前阶段范围。

## 搜索与真实 MiKan 兼容性

### BL-001: 优化真实 MiKan 番剧搜索和 RSS 源解析

- 状态：待办
- 来源：Stage 5 验收后的真实 MiKan 试用
- 优先级：中
- 不阻塞：Stage 6 启动

观察结果：

- 使用真实 MiKan endpoint 搜索 `无职转生`、`無職転生`、`Mushoku Tensei` 可以返回候选番剧。
- 搜索 `无职转生 第四季`、`無職転生 第4期` 未返回候选；当前 MiKan 结果中最新可见相关候选为 `无职转生 第三季 ～到了异世界就拿出真本事～`。
- 对多个真实 MiKan 番剧页执行 `list_rss_sources(...)` 时返回 `mikan_parse_failed: MiKan 番剧页未找到 RSS 源`。
- 手动抽样页面片段可见类似 `/RSS/Bangumi?bangumiId=...` 的 RSS 链接，说明现有解析规则未完全覆盖实站 HTML 结构。

后续建议：

- 增加针对 MiKan 实站当前 HTML 结构的离线 fixture，覆盖番剧页顶部 `.mikan-rss` 链接。
- 区分番剧级 RSS 和字幕组级 RSS：若页面只有番剧级 RSS，应明确产出可用 `RssSource` 或给出更准确的错误。
- 增强搜索关键词策略，例如中日文标题、数字季/第 N 季/第 N 期、罗马字别名的 fallback 查询。
- 为真实搜索和 RSS 源解析增加手动验收脚本，输出候选和安全脱敏后的解析摘要。
- 保持错误输出不包含原始 HTML、RSS XML、完整 URL、cookie 或 token。
