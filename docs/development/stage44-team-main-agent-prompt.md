# Stage 44 团队主 Agent 启动提示词

将以下文本发送给新会话即可启动开发；文件存在不代表已授权开发或发布。

```text
全程中文。启动团队进行 MiGuOrca Stage 44 开发；你是主规划、协调与独立审核 Agent。项目 /home/ghostning/github/migu_orca，分支 ralph/stage44-shared-draft-review，开始前核对 git status --short --branch、HEAD、origin/main、scripts/ralph/prd.json/progress；保留非本任务修改，不reset/覆盖/删旧分支。Stage43已由PR#72合并，merge 36ba540；本地准备提交9f51d41及后续D-03记录以git核对。

授权：按 Stage44 PRD 开发、定向验证、审核/红测/集中修复/复审闭环与本地逐story提交；不授权push、PR、合并、强推或删分支。主Agent读AGENTS.md、frontend/AGENTS.md、.agents/skills/ralph/SKILL.md、dev-browser skill、docs/MiGuOrca_stage44_shared_draft_review_PRD.md、总体PRD、handoff、prd/progress及当前包精确代码测试。

范围仅两包：US-353合集身份/资源/筛选审核层级，US-354修改状态与单番本地确认层级。D-03已确认：默认最多3条安全标题、完整列表按需展开、单番/批量同口径；D-02/D-04仍留Stage45，不改。A开发→独立审核→最小红测→同一B集中修复→复审，前包闭环才下一包；共享区仅一写入者。A优先Claude Fable，环境不可用如实用Luna替代；不运行ralph.sh。

保持服务端草案authority、draft_id/revision/CAS、scheduler/1.5秒防抖、flush、save-confirm、unknown恢复、safe-info与两次确认；不新增API/OpenAPI/generated字段/后端/持久化/外部写/未保存safe-info/单项重搜/实时进度，不重做Toast timer/store或Stage45。批量候选摘要只来自实际选中公开候选；直连/无封面/无总集数显示未知，不从Request/别名/其他候选推断。资源计数同源，不相减；敏感值不入DOM/URL/storage/trace。已保存模式的AnimeDraftEditor调用者、slot/event/props与人工保存必须回归。

普通story只跑受影响Vitest/typecheck/lint/build/api check、对应views/DTO/CAS契约和真实Chromium（route mock、held route、临时数据、三视口/200%/长标题/键盘/焦点/reduced-motion/canary）。Stage收尾一次完整后端/前端/Chromium门禁。每条实际AC通过才passes=true，记录实际命令/结果/风险，精确暂存提交`feat: [US-ID] - 标题`，不git add .。全部完成后报告审核HEAD、验证、工作区和Stage45交接，停止。
```
