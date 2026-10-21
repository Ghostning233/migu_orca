> 来源：Codex 依 D0（#231）给出的 token 级规格，2026-10-20 修正版（取消复选框与选择列、行体点击随模式）。
> 本文件是 T2（#225）与后续 T3（#226）实现列表行、标题行与批量工具栏的唯一视觉权威；
> 正文与工作区 `.migu_orca/artifacts/codex_row_style_spec.md` 逐字一致，仅本说明为入库补充。

# 追番列表行与批量工具栏样式规格（修正版）

**2026-10-20 修正：行体点击模式相关；取消复选框与选择列。**

本文覆盖上一版规格，以用户本次决定为准。仅给结构、token与数值，不提供整段实现代码；不改仓库。全部颜色复用 `frontend/src/styles/tokens.css`，不新增调色板。

## 交互结构：两个兄弟按钮，不嵌套

每行使用中性容器，下设共享背景/色条装饰层，以及两个**兄弟原生按钮**：①行体按钮包含封面、标题、季度、状态药丸；②箭头按钮占固定末列。行体与箭头绝不互相嵌套；不在行容器注册会重复触发的点击处理。没有checkbox、选择列、勾号或其他选择图标。

| 元素 | 浏览态动作 | 多选态动作 |
| --- | --- | --- |
| 行体 | 切换右侧详情 | 切换该行是否参与批量选择；不切换详情 |
| 箭头区域 | 切换右侧详情 | 切换右侧详情；不修改批量选择 |

详情当前项与批量选择集合分别保存；箭头看详情不能把行自动加入批量集合。模式切换改变行体action，不更改其布局。多选勾选仅以共享行背景表达，不新增ARIA、role或aria-live；也不主动删除已有属性。原生button的既有键盘行为与focus-visible样式继续保留，不为装饰箭头新增语义属性。

## 元素 → 属性 → 值/token

数值是CSS逻辑像素；1586×992是设计图画布，不能把图片放大系数作为组件CSS尺寸。

| 元素 | 属性 | 冻结值／token |
| --- | --- | --- |
| 列表正文 | 排列、间距 | 单列，gap=0；无卡片网格间隔 |
| 行容器 | 常态外观 | 无四边框、无阴影；底色沿用`--color-surface`；不做独立卡片 |
| 行容器 | 最小高度 | 新增`--tracking-row-min-height`，定义为海报高＋2×`--space-3`＋`--control-border-width`，解析115px；不是固定height，字体放大可增高 |
| 行容器 | 结构列 | 外层两列：`minmax(0,1fr)`行体＋`--control-target-min`箭头44px；左/右统一padding=`--space-4`=16px。行体与箭头间gap=`--space-3`=12px |
| 行容器 | 垂直padding | 上/下`--space-3`=12px；底部另留`--control-border-width`=1px线槽；不叠加子按钮默认padding |
| 行体按钮 | 内部排列 | 海报固定60px、标题列`minmax(0,1fr)`、状态药丸auto；列gap=`--space-3`=12px，垂直居中，min-width:0；自身padding/border/shadow为0 |
| 行体按钮 | action、鼠标 | 浏览态看详情，多选态切换选择；cursor:pointer；不继承共享按钮hover的上移transform |
| 封面 | 宽、高、比例 | 新增`--tracking-poster-width`=60px（40px＋20px间距token）；`--tracking-poster-height`=90px（宽×1.5）；固定2:3、object-fit:cover；缺图同框 |
| 封面 | 圆角 | `--radius-sm`=6px；不随是否详情选中或批量选中改尺寸 |
| 标题 | 字体、溢出 | `--type-card-title`=17px、`--font-weight-semibold`=650、`--line-height-tight`=1.3、`--color-text`；单行省略 |
| 季度 | 字体、间距 | `--type-label`=14px、regular、`--color-text-muted`；与标题gap=`--space-1`=4px；不显示提交方式或时间 |
| 状态药丸 | 字体、padding、圆角 | 14px/medium；上下`--space-1`=4px、左右`--space-3`=12px；`--radius-pill`；不换行，不截断现行精确状态 |
| 状态药丸 | 语义颜色 | 追番中：`--color-info`/`--color-info-surface`；待提交、已停用、已加入下载：`--color-unknown`/`--color-unknown-surface`；待重新确认、需要恢复、外部已删除：`--color-warning`/`--color-warning-surface`；提交失败：`--color-danger`/`--color-danger-surface`。不得用珊瑚橙作追番中药丸 |
| 分隔线 | 颜色、厚度、横向范围 | `--color-border-subtle`、`--control-border-width`=1px；距行左/右边各`--space-4`=16px，处于最底线槽，不因行状态加粗 |
| 最后一行 | 分隔线 | 最后可见数据行不画线；仍保留1px槽，避免高度跳变；异步提示不算数据行 |
| 背景装饰层 | 范围、圆角 | 贴行左/右/上边，底距1px线槽；`--radius-md`=10px；仅装饰层overflow:hidden，pointer-events:none |
| 详情当前项 | 底色、色条 | `--color-info-surface`=淡蓝、100%不透明；常驻`--color-primary`左条；不随鼠标移出取消 |
| 批量已选项 | 底色、色条 | 仅`--color-info-surface`、100%；不新增色条或其他选择符号 |
| 鼠标悬停 | 底色、色条 | 临时`--color-info-surface`、100%；仅悬停不生成色条；移出恢复当前详情/批量状态对应样式 |
| 状态重叠 | 优先级、混合 | 底色只绘一次，不叠透明层：detail-selected∨batch-selected∨hover均取同一淡蓝。**左条只由detail-selected决定**；一行同时详情当前＋批量选中时仍是单底色＋单左条 |
| 已详情选中行hover | 响应 | 生效但不加深颜色、不改变条宽、无闪烁；移出仍保留详情选中效果 |
| 背景过渡 | 时长、缓动 | `--motion-duration-fast`=120ms＋`--motion-easing-standard`；只过渡background-color，不平移/缩放、不动画整行opacity；reduced-motion沿现有token自动0ms |
| 左条 | 宽、高、偏移 | 宽`--space-1`=4px、left/top/bottom=0（相对背景层）；铺满行背景高度而非海报高度；不占grid列、不增加选择列 |
| 左条 | 颜色、圆角、线槽 | `--color-primary`；自身radius=0，由背景层10px圆角整体裁切；止于底部线槽上缘，不覆盖分隔线 |
| 箭头按钮 | 热区 | 宽`--control-target-min`=44px，高撑满行内容区（标准90px），至少44px；整个矩形可点，不只是图形本身 |
| 箭头按钮 | 定位、padding | 固定末列，外侧距行右边16px；内padding=0；hover/焦点不扩大列宽、不补大padding、不覆盖标题 |
| 箭头图形 | 大小、颜色 | `--icon-md`=20px，`--color-text-muted`，热区居中；沿用现有chevron，不新增图形标签或ARIA属性 |
| 箭头按钮 | action、鼠标、背景 | 两种模式恒为看详情；cursor:pointer；自身透明、无独立矩形描边/阴影；共享行背景负责hover预览，不单独再铺一层蓝色 |
| 两按钮focus-visible | 保留样式、边界 | 复用`--focus-ring-width`=3px、`--color-focus-ring`，内侧offset=-3px；不改行尺寸；装饰层不裁按钮焦点。不是常态边框，也不是选择符号 |
| 禁用行体 | 资格限制 | 多选态不适用项按现有业务规则禁用行体，cursor:not-allowed；箭头仍可独立查看详情。不得因样式任务扩张提交资格 |
| 标题行 | 布局 | flex、center、gap=`--space-3`=12px；左“追番列表”，右操作组按“多选/完成 → 搜索框”排列；搜索靠右 |
| 标题 | 字体 | `--type-section-title`=20px、semibold、`--color-text` |
| 多选/完成按钮 | 层级、文案、尺寸 | `BaseButton secondary`；普通态“多选”，多选态原位变“完成”；高`--control-height-md`=44px、左右padding12px、14px/medium、radius10px；局部禁止hover上移 |
| 搜索框 | 宽度、顺序 | 最小新增`--tracking-search-min-width`=160px，优选新增`--tracking-search-width`=240px，可收缩；位于多选/完成右侧 |
| 标题行移除项 | 范围 | 无“全部”“清除筛选”“刷新列表”，也不换成隐蔽图标；再次点击已选状态卡取消状态筛选 |
| 批量工具栏 | 出现位置 | 仅多选态：**标题行下方另起一行**；不把选择计数与操作塞进标题/搜索所在行 |
| 批量工具栏 | 外观、高度 | 无独立边框、阴影或卡片底；上下padding8px（`--space-2`），距标题行8px；44px控件使标准高60px，计入列表面板内部预算 |
| 批量工具栏 | 布局 | flex可换行；左组“已选N部 · 全选当前N部 · 清除选择”；右动作组margin-inline-start:auto；组间16px，左组内部12px |
| 已选N部 | 字体、颜色 | 14px/medium、`--color-text-secondary`；数字semibold但不放大；完整短语不换行；不新增aria-live |
| 全选当前N部、清除选择 | 按钮层级 | 原生文字按钮，14px/medium、`--color-primary`，无常态描边/实心底；最小高44px、左右padding8px；hover=`--color-primary-subtle`；不增加ARIA/role |
| 文本分隔点 | 间距、颜色 | “·”，`--color-text-disabled`，左右8px；与左组gap不重复累加。随相邻操作一起换行，不能孤立落下一行 |
| 提交选中 | 层级、外观 | 本轮唯一批量主动作，`BaseButton primary`，深海蓝底白字，44px高、14px/medium、radius10px，左右padding12px；不增加删除/启停 |
| 提交选中 | 禁用与进行中 | N=0禁用；其它disabled、loading沿既有session/组件行为，不能在本任务新增ARIA属性。共享禁用视觉0.55透明度、not-allowed，loading不改变按钮宽度 |
| ≤760px | 标题/搜索换行 | 标题和多选/完成在第一行，搜索独占下一行width100%；只使用壳层760px断点，不新建800px断点 |
| ≤760px | 批量栏换行 | 左选择信息组先排，允许自然换行；提交选中独占下一行width100%、高44px；无横向滚动 |
| >760px受压 | 自然换行 | flex-wrap；搜索达160px仍放不下则操作组换行；批量右动作整体另行右对齐，不缩窄按钮或截操作文案 |

## 新token提议（实施时集中登记，本文不改tokens.css）

只新增组件几何别名，不新增颜色或交互状态变量：

- `--tracking-poster-width`：`calc(var(--space-10) + var(--space-5))`，60px。
- `--tracking-poster-height`：`calc(var(--tracking-poster-width) * 1.5)`，90px。
- `--tracking-row-min-height`：`calc(var(--tracking-poster-height) + 2 * var(--space-3) + var(--control-border-width))`，115px。
- `--tracking-search-min-width`：`calc(4 * var(--space-10))`，160px。
- `--tracking-search-width`：`calc(6 * var(--space-10))`，240px。

外层行统一16px横向padding，行体与箭头按钮不再叠同一padding。两个按钮为独立可点区域，箭头热区不通过覆盖行体或让事件冒泡实现。**不要复用上一版“行体恒为详情”的action，也不要恢复checkbox列。**

## 后续母版摘要同步项

母版摘要删除“提交方式”，删除“最近更新”；“创建时间”必须取created_at。字段顺序固定：季度／字幕组／有效资源数／总集数／已更新集数／创建时间。总集数与已更新集数缺可信数据仍“未开发”。这不是把updated_at标签改名，也不在摘要补“本地状态”行。

## 肉眼与操作验收要点

1. 行不是卡片：没有四边框/阴影/行间gap，仅相邻一条1px细线，末行无线；115px最低行高、60×90封面。
2. 全列表无复选框、选择列、勾号；进入多选也不改变海报与行左侧的对齐。
3. 详情当前项有满行内嵌左条＋淡蓝；另一批量选中项只有淡蓝；两种身份重叠不叠色，左条只追随右侧详情。
4. 浏览态点行体看详情；多选态点同一位置切换选择、详情不变；任意模式点箭头都看详情、批量选择不变。每次点击只触发一个动作。
5. 箭头上/下的末列空白也可点击；热区固定44px，移入后标题不会被挤窄，行不会上浮。
6. 悬停仅临时淡蓝；移出批量已选行不取消底色，移出详情当前项不消失左条；hover已选项不加深。
7. 标题右侧“多选/完成”紧靠搜索左边；无全部、清除筛选、刷新。批量工具栏明确另起一行，计数/全选/清除靠左，唯一主动作提交选中靠右。
8. ≤760px搜索独立成行，批量动作下一行占满宽度；文案不重叠、页面不横向溢出，工具栏出现只占面板内部预算。
9. 不为本次多选新增ARIA、role或aria-live；也不清理已有属性。保留原生按钮及现有组件行为，不把本任务变成无障碍改造。
10. 母版只绘浏览态，不为展示多选逻辑额外出局部补图；本规格不代表其他状态图已授权生成。
