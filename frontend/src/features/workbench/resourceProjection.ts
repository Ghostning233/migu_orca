/**
 * 共享的安全资源投影（#151）。
 *
 * 资源标题来自服务端公开投影（`valid_seed_names` / `excluded_seed_names[].name`），
 * 通常就是种子文件名。即使如此，客户端仍要 fail closed：URL／magnet 形式的取值与
 * 绝对本地路径永远不能进入 DOM，排除原因也一样。规则集中在这里，资源摘要、批量
 * 草案资源概览与资源明细弹窗共用同一份判定，不各自复制安全措辞。
 *
 * 本模块不读取 Request、不发请求、不持久化任何值。
 */

/** URL／magnet 形式：`magnet:?…`、`http(s)://…` 等任意 scheme。 */
export const URL_LIKE_RESOURCE = /^(?:magnet:|[a-z][a-z0-9+.-]*:\/\/)/i

/** 绝对本地路径：POSIX（`/…`）、UNC（`\\…`）、Windows 盘符（`C:\…` / `C:/…`）。 */
export const LOCAL_PATH_LIKE_RESOURCE = /^(?:\/|\\\\|[a-z]:[\\/])/i

/** 资源标题的安全显示值；命中敏感形状时只给固定占位，不回显原值。 */
export function safeResourceTitle(value: string): string {
  if (URL_LIKE_RESOURCE.test(value)) return '[已隐藏资源地址]'
  if (LOCAL_PATH_LIKE_RESOURCE.test(value)) return '[已隐藏本地路径]'
  return value
}

/** 排除原因与资源标题走同一套判定（原因同样不得回显地址或路径）。 */
export function safeResourceReason(value: string): string {
  return safeResourceTitle(value)
}

/**
 * 资源概览里的少量安全示例。
 *
 * #145 要求默认层只放「少量安全示例资源」，完整清单按需在明细弹窗中浏览，因此这里
 * 固定取前 `limit` 条；它不改变资源数，也不推断集数。
 */
export function resourcePreview(seeds: readonly string[], limit = 2): string[] {
  return seeds.slice(0, Math.max(0, limit)).map(safeResourceTitle)
}
