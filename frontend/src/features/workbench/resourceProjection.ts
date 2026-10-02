/**
 * 共享的安全资源投影（#151）。
 *
 * 资源标题来自服务端公开投影（`valid_seed_names` / `excluded_seed_names[].name`），
 * 通常就是种子文件名。即使如此，客户端仍要 fail closed：URL／magnet 形式的取值与
 * 绝对本地路径永远不能进入 DOM，排除原因也一样。规则集中在这里，资源摘要、批量
 * 草案资源概览与资源明细弹窗共用同一份判定，不各自复制安全措辞。
 *
 * 判定必须覆盖「地址嵌在说明文字里」的真实形态（例如「命中规则：https://…」、
 * 「资源位于 /srv/…」、「缓存 C:\…」）。只匹配字符串开头会把这些值原样放进 DOM，
 * 因此这里的规则在**任意位置**命中即整体替换为固定占位，绝不回显原值。
 *
 * 本模块不读取 Request、不发请求、不持久化任何值。
 */

/**
 * URL／magnet 形式：`magnet:` 或任意 `scheme://`。
 *
 * 不需要边界条件：正常番剧种子标题不会包含 `magnet:` 或 `://`，命中即代表泄漏。
 */
export const URL_LIKE_RESOURCE = /(?:magnet:|[a-z][a-z0-9+.-]*:\/\/)/i

/**
 * 明确表示「后面跟的是本地路径」的字段语义。
 *
 * CJK 字符**不再**一律当作路径边界：普通标题里的斜杠必须保留
 * （`孤独/摇滚！- 01.mkv`、`鬼滅の刃/遊郭編 - 01.mkv`）。只有「路径／目录／缓存／
 * 资源位于／存储位置」这类明确字段语义出现在 `/` 之前时，才按绝对路径 fail closed。
 *
 * 关键字与 `/` 之间只允许 0～2 个连接字符（见 `PATH_CONTEXT_CONNECTOR`），
 * 不接受任意自由文本，避免把普通标题重新误判成路径。
 */
const PATH_CONTEXT_KEYWORDS = [
  // 长词在前：`资源位于` 必须整体吃掉「位于」，否则连接词放不下。
  '资源位于',
  '资源位置',
  '存储位置',
  '文件位于',
  '文件路径',
  '根目录',
  '临时目录',
  '路径',
  '目录',
  '缓存',
  '文件夹',
  '资源',
  '文件',
  '位置',
].join('|')

/**
 * 字段语义与 `/` 之间允许的连接字符，最多 2 个：空白、为、是、在、冒号。
 *
 * 这是「缓存目录为/srv」「资源在/tmp」「文件路径是/home」这类自然写法，
 * 但范围被有意限制得很窄，避免变成「任意文本 + 斜杠即路径」。
 */
const PATH_CONTEXT_CONNECTOR = '[\\s为是在：:]{0,2}'

/**
 * 路径 token 之前允许出现的分隔字符：行首、空白、中英文标点、引号（含右引号）、
 * 开闭括号与书名/引号（`） ) 】 ] 」 』 》 〉 〕 }` 等，成对补全）、半角/全角连字符与
 * 破折号（`-`、`－`、`—`、`–`：`缓存目录-/srv`、`说明－/mnt/…`），以及
 * `=`、`?`、`&`、`#`、`%` 这类「说明 + 取值」形态（`foo=/srv/a.mkv`）。
 *
 * 要求边界是为了不误伤正常标题里的斜杠：`Fate/stay night - 01.mkv`、
 * `episode 01/24.mkv` 的斜杠都紧跟普通西文字符，不构成路径 token 的开头。
 * CJK 紧邻斜杠的情形由 `PATH_CONTEXT_KEYWORDS` 的字段语义决定，而不是「任意 CJK」。
 */
const PATH_SEPARATOR_CHARS =
  '\\s，,。.；;：:、/'
  + '（(）)【】\\[\\]「」『』《》〈〉〔〕｛｝{}'
  + '"\'`“”‘’'
  + '|=?&#%+~!@$^*<>\\-－—–'

/**
 * POSIX 绝对路径：合法分隔符之后，或字段语义（可带有限连接词）之后，
 * 紧跟一个非空 `/路径段`。
 *
 * UNC（`\\\\`）与 Windows 盘符（`C:\\`/`C:/`）不需要边界：正常番剧标题不会包含
 * 连续反斜杠或「盘符 + 分隔符」，因此对它们一律 fail closed。
 */
const POSIX_ABSOLUTE_PATH = '(?:'
  + '(?:^|[' + PATH_SEPARATOR_CHARS + '])'
  + '|(?:' + PATH_CONTEXT_KEYWORDS + ')' + PATH_CONTEXT_CONNECTOR
  + ')\\/[^\\s/]+'

/**
 * 绝对本地路径，出现在任意位置即整体隐藏：
 *
 * - POSIX：见 `POSIX_ABSOLUTE_PATH`（分隔符或字段语义之后紧跟非空 `/路径段`，
 *   不要求第二层目录或扩展名：`/srv`、`/tmp`、`/private`、`根目录=/home`、
 *   `说明）/private`、`路径】/srv`、`缓存目录为/srv` 都必须隐藏）；
 * - UNC：`\\\\server\\share\\…`（可被任意字符前缀，例如 `x=\\\\server\\share\\a.mkv`）；
 * - Windows 盘符：`C:\\…` / `C:/…`（同样不要求边界）。
 *
 * 只要命中敏感形状，`safeResourceTitle` 就整体返回固定占位，不做局部替换，
 * 因此路径片段、主机名或 canary 都不会随剩余文本泄漏出去。
 */
export const LOCAL_PATH_LIKE_RESOURCE = new RegExp(
  '(?:'
  + POSIX_ABSOLUTE_PATH
  + '|\\\\\\\\'
  + '|[A-Za-z]:[\\\\/]'
  + ')',
  'i',
)

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
