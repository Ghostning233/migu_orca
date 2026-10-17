# 下载现有资源采用至少一次提交语义

Auto Bangumi 3.1.18 无法返回逐个 torrent 的添加结果或提供幂等操作标识，且它的写响应体恒为 `{"msg_en": …, "msg_zh": …}`——结果只在 HTTP 状态码上，响应里没有 `status` 字段（#216）。因此 MiGuOrca 以**精确 HTTP 200 且响应体为该写信封**作为一次「已加入下载」的判据；201/204/3xx、非法 JSON、缺字段、超时和连接中断一律统一呈现为可再次提交的「提交失败」。

这一次接受的语义是**至少一次**：上游可能已经处理了本次提交，用户显式再次提交时，相同 info-hash 通常由 qBittorrent 去重，但不同 info-hash 或后来新增的资源仍可能产生新任务。所以产品不承诺「安全重试」，也不把这套宽松语义用于创建受控外部订阅的「持续追番」——后者先持久化写前意图，再以精确回查确认归属（#97/#182），结果待确认时只走恢复核验，不盲目重发。

## AB 侧副作用（#217）

这次接受调用的是 Auto Bangumi 3.1.18 的 `POST /api/v1/rss/collect`，请求体是**裸 `Bangumi` 模型**（不套 `data` 包装体，也不是 `{data, rss}` 订阅体），只在 **password 模式 ＋ 精确 3.1.18** 下发起，且 payload **不携带 `id`**。由此产生的上游副作用是明确的：

- **不创建 RSS 订阅**：该端点走 `SeasonCollector.collect_season`，与 `/rss/subscribe` 的 `add_rss` 无关。
- **可能写入一条 Bangumi 规则**：成功时上游执行 `eps_collect = True`，并 `if engine.bangumi.update(bangumi): engine.bangumi.add(bangumi)`（`module/manager/collector.py:27-30`）。payload 无 `id` 时 `update` 返回 False，随后 `add` 按 `title_raw` 去重且其返回值被忽略（`module/database/bangumi.py:16-24`），所以**既有同名规则不会被更新**，重复名称也不会新增第二条。
- **后台补收集不由 MiGuOrca 控制**：`eps_collect` 之后的资源收集沿用 Auto Bangumi 自身的既有配置；MiGuOrca 不接管、不追踪，也不据此宣称任何下载结果。
- **筛选规则不静默改写**：上游对整个 `filter` 执行 `.replace(",", "|")`，因此最终表达式含 ASCII 逗号时 MiGuOrca 直接拒绝提交并零外部写。

HTTP 200 只是「已加入下载」的本地判据，不代表逐个 torrent 的结果；406 等拒绝同样不被解读为「什么都没发生」。
