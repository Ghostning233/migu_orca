# Issue tracker：GitHub

本仓库的 issue 与规格存放在 GitHub Issues 中。所有操作使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`。多行正文使用 heredoc。
- **读取 issue**：`gh issue view <number> --comments`，并按需使用 `jq` 筛选评论和获取标签。
- **列出 issue**：使用 `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，并按需增加 `--label` 和 `--state`。
- **评论 issue**：`gh issue comment <number> --body "..."`
- **添加或移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭 issue**：`gh issue close <number> --comment "..."`

在仓库 clone 内运行时，从 `git remote -v` 推断目标仓库；`gh` 会自动处理。

## 当技能要求“发布到 issue tracker”

创建一个 GitHub issue。

## 当技能要求“读取相关 ticket”

运行 `gh issue view <number> --comments`。
