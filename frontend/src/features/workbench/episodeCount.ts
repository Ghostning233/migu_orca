/**
 * 集数占位投影（#165）——单一来源。
 *
 * 只做「判定 + 格式化」：输入由来源侧保证可信，输出 `N 集` 或「未开发」。
 *
 *   - 判定统一为 `Number.isInteger(total) && total > 0`；`0`、负数、小数、字符串、
 *     `null`/`undefined` 一律视为不可得。
 *   - 「未开发」是**能力尚未实现的固定占位**，不是「数据缺失」，也不因来源是否公开
 *     而改写（`CONTEXT.md`「界面占位表述」）。
 *   - 这里不判定可信度，更不从资源标题、种子数量或有效资源数推算集数——可信度由
 *     来源侧保证，函数内无法断言（`CONTEXT.md` 的负向约束）。
 */

/** 能力尚未实现时的固定占位；本模块是它在界面上的唯一来源。 */
export const EPISODE_PLACEHOLDER = '未开发'

/**
 * 判定：这个值能不能当可信总集数用。
 *
 * 单独导出是给「数值本身就要原样显示」的表面用（追番详情的主字段），
 * 让它们共用同一套判定而不被格式化改写有值路径。
 */
export function hasTrustedEpisodeCount(total: number | null | undefined): total is number {
  return typeof total === 'number' && Number.isInteger(total) && total > 0
}

/** 可信总集数 → `N 集`；缺可信数值时给固定占位。 */
export function episodeCountText(total: number | null | undefined): string {
  return hasTrustedEpisodeCount(total) ? `${total} 集` : EPISODE_PLACEHOLDER
}

/** 候选卡「总集数」行的带标签文本（`总集数：N 集` / `总集数：未开发`）。 */
export function episodeProgressText(total: number | null | undefined): string {
  return `总集数：${episodeCountText(total)}`
}
