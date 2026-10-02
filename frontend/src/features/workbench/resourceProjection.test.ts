import { describe, expect, it } from 'vitest'

import {
  resourcePreview,
  safeResourceReason,
  safeResourceTitle,
} from '@/features/workbench/resourceProjection'

/** #151：默认层与明细弹窗共用的资源安全投影。 */
describe('resource projection (#151)', () => {
  it('keeps ordinary seed titles and reasons readable', () => {
    expect(safeResourceTitle('星海旅途 S01E01 1080p WEB-DL x264.mkv')).toBe('星海旅途 S01E01 1080p WEB-DL x264.mkv')
    expect(safeResourceReason('命中排除规则：[v2]')).toBe('命中排除规则：[v2]')
  })

  it('hides URL-like values, magnets and absolute local paths without echoing them', () => {
    expect(safeResourceTitle('magnet:?xt=urn:btih:deadbeef')).toBe('[已隐藏资源地址]')
    expect(safeResourceTitle('https://mikan.example/rss/1')).toBe('[已隐藏资源地址]')
    expect(safeResourceTitle('/data/media/anime/01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('C:\\media\\01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('\\\\server\\share\\01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('magnet:?xt=urn:btih:deadbeef')).toBe('[已隐藏资源地址]')
    expect(safeResourceReason('/srv/library/01.mkv')).toBe('[已隐藏本地路径]')
  })

  // 已确认缺陷：投影只匹配字符串开头，因此把地址嵌在中文说明里的真实形态会原样
  // 进入 DOM（「命中规则：https://…」「资源位于 /srv/…」「缓存 C:\\…」）。
  it('hides values whose address or path is embedded anywhere in the string', () => {
    expect(safeResourceReason('命中规则：https://example.invalid/private.xml')).toBe('[已隐藏资源地址]')
    expect(safeResourceReason('排除原因：magnet:?xt=urn:btih:deadbeef')).toBe('[已隐藏资源地址]')
    expect(safeResourceReason('资源位于 /srv/private/file.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('缓存 C:\\private\\file.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('备份到 \\\\server\\share\\01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('资源位于/srv/private/file.mkv')).toBe('[已隐藏本地路径]')
  })

  // 已确认缺陷：PATH_BOUNDARY 过窄，`=`/`?`/`&` 等普通字符之后接绝对路径时不会命中。
  it('hides absolute paths that follow an ordinary character such as = ? &', () => {
    expect(safeResourceTitle('foo=/srv/private/a.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('path=C:\\secret\\a.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('x=\\\\server\\share\\file.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('/srv/private/a.mkv?token=abc')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('来源?/data/media/01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('缓存&/mnt/private/01.mkv')).toBe('[已隐藏本地路径]')
    // 原断言为「说明文字/mnt/private/01.mkv」，它依赖「任意 CJK 字符 + / 即路径」，
    // 而那条规则会把 `孤独/摇滚！- 01.mkv`、`鬼滅の刃/遊郭編 - 01.mkv` 这类正常
    // 标题整体隐藏（误伤）。这里改为等价或更强的**明确路径上下文**用例：
    // 同样的嵌入形态在「存储位置/说明：/说明-」等字段语义或标点分隔下仍必须隐藏，
    // 消除误伤的原因与正常标题回归见 keeps CJK slashes … 用例。
    expect(safeResourceReason('存储位置/mnt/private/01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('说明：/mnt/private/01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('说明-/mnt/private/01.mkv')).toBe('[已隐藏本地路径]')
  })

  // 已确认缺陷：单段 POSIX 绝对路径（没有第二层目录、没有扩展名）此前会原样放行。
  it('hides a single-segment absolute path even without a second level or extension', () => {
    expect(safeResourceTitle('/private')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('缓存目录：/srv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('临时目录 /tmp')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('根目录=/home')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('/data')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('临时目录 /tmp 下的资源')).toBe('[已隐藏本地路径]')
  })

  it('never echoes a canary carried in a single-segment path', () => {
    const canary = 'CANARY-single-segment-9d2f'
    const projected = safeResourceReason(`缓存目录：/${canary}`)
    expect(projected).toBe('[已隐藏本地路径]')
    expect(projected).not.toContain(canary)
    expect(projected).not.toContain('/')
    expect(safeResourceTitle(`根目录=/${canary}/a.mkv`)).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle(`根目录=/${canary}/a.mkv`)).not.toContain(canary)
  })

  // 已确认缺陷：半角/全角连字符是常见的「说明 + 取值」分隔符，此前不在安全边界里。
  it('hides paths after half-width or full-width hyphen separators', () => {
    const canary = 'CANARY-hyphen-7a4d'
    expect(safeResourceTitle(`缓存目录-/srv/${canary}`)).toBe('[已隐藏本地路径]')
    expect(safeResourceReason(`说明-/tmp/${canary}`)).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle(`说明－/mnt/${canary}`)).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle(`说明—/var/${canary}`)).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle(`说明–/opt/${canary}`)).toBe('[已隐藏本地路径]')
    for (const value of [
      `缓存目录-/srv/${canary}`,
      `说明-/tmp/${canary}`,
      `说明－/mnt/${canary}`,
      `说明—/var/${canary}`,
    ]) {
      const projected = safeResourceTitle(value)
      expect(projected).toBe('[已隐藏本地路径]')
      expect(projected).not.toContain(canary)
      expect(projected).not.toContain('/')
    }
    // 既有 fail-closed 行为保持不变。
    expect(safeResourceTitle('缓存目录-/srv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('/private')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('缓存目录：/srv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('根目录=/home')).toBe('[已隐藏本地路径]')
  })

  // 已确认缺陷：右括号/右方括号/右引号等**闭合分隔符**不在边界集里，
  // `说明）/private/…`、`路径】/srv/…` 会整体绕过投影。
  it('hides paths after closing brackets and quotes', () => {
    const canary = 'CANARY-closing-2b9f'
    const values = [
      `说明）/private/${canary}`,
      `路径】/srv/${canary}`,
      `说明]/var/${canary}`,
      `说明」/mnt/${canary}`,
      `说明』/opt/${canary}`,
      `说明”/home/${canary}`,
      `说明’/data/${canary}`,
      `说明》/usr/${canary}`,
      `说明〕/media/${canary}`,
      `说明}/root/${canary}`,
    ]
    for (const value of values) {
      const projected = safeResourceTitle(value)
      expect(projected).toBe('[已隐藏本地路径]')
      expect(projected).not.toContain('/')
      expect(projected).not.toContain(canary)
    }
  })

  // 已确认缺陷：字段语义与 `/` 之间允许出现有限连接词（为/是/在/冒号/空白），
  // 但绝不能放宽成「任意自由文本」，否则会重新误伤普通标题。
  it('hides paths introduced by a path-context keyword with a short connector', () => {
    const canary = 'CANARY-connector-4e12'
    const values = [
      `缓存目录为/srv/${canary}`,
      `资源在/tmp/${canary}`,
      `文件路径是/home/${canary}`,
      `存储位置为/var/${canary}`,
      `路径：/mnt/${canary}`,
      `目录 /data/${canary}`,
      `资源位于/srv/${canary}`,
    ]
    for (const value of values) {
      const projected = safeResourceReason(value)
      expect(projected).toBe('[已隐藏本地路径]')
      expect(projected).not.toContain('/')
      expect(projected).not.toContain(canary)
    }
    // 连接词仍然有限：普通说明文字后紧跟 `/` 不是路径上下文。
    expect(safeResourceTitle(`说明文字/srv/${canary}`)).toBe(`说明文字/srv/${canary}`)
    expect(safeResourceTitle(`孤独/摇滚！- 01.mkv`)).toBe('孤独/摇滚！- 01.mkv')
  })

  // 已确认缺陷：把任意 CJK 字符当路径边界会把普通标题里的斜杠整体隐藏。
  it('keeps CJK slashes in ordinary titles unless the field context says it is a path', () => {
    const readable = [
      '孤独/摇滚！- 01.mkv',
      '鬼滅の刃/遊郭編 - 01 [1080p].mkv',
      '名侦探柯南/特别篇 - 01 [1080p][CHS].mkv',
    ]
    for (const title of readable) {
      expect(safeResourceTitle(title)).toBe(title)
    }
    // 明确的路径字段语义 + CJK 紧邻斜杠，仍然 fail closed。
    expect(safeResourceTitle('缓存目录/private')).toBe('[已隐藏本地路径]')
    expect(safeResourceReason('资源位于/srv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('存储位置/var/log')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('文件夹/media/anime')).toBe('[已隐藏本地路径]')
  })

  it('hides a Windows drive or UNC path even with a plain letter prefix', () => {
    expect(safeResourceTitle('diskC:\\private\\a.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('share\\\\server\\share\\a.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('C:/private/a.mkv')).toBe('[已隐藏本地路径]')
  })

  it('hides a leading-whitespace address instead of echoing it after trimming', () => {
    expect(safeResourceTitle('  https://example.invalid/private.xml')).toBe('[已隐藏资源地址]')
    expect(safeResourceTitle('\n /srv/private/01.mkv')).toBe('[已隐藏本地路径]')
    expect(safeResourceTitle('  magnet:?xt=urn:btih:deadbeef')).toBe('[已隐藏资源地址]')
  })

  it('never echoes a canary or host carried inside a mixed resource line', () => {
    const canary = 'CANARY-7f3a9c'
    const value = `命中规则：https://example.invalid/private.xml?token=${canary}`
    const projected = safeResourceReason(value)
    expect(projected).toBe('[已隐藏资源地址]')
    expect(projected).not.toContain(canary)
    expect(projected).not.toContain('example.invalid')
    expect(projected).not.toContain('private.xml')

    const pathProjection = safeResourceTitle(`资源位于 /srv/${canary}/01.mkv`)
    expect(pathProjection).toBe('[已隐藏本地路径]')
    expect(pathProjection).not.toContain(canary)
  })

  it('keeps ordinary anime seed titles readable (no false positives)', () => {
    const readable = [
      '星海旅途 S01E01 1080p WEB-DL x264.mkv',
      '[喵萌奶茶屋] 葬送的芙莉莲 - 01 [1080p][CHS].mkv',
      'Fate/stay night - 01 [1080p].mkv',
      '孤独摇滚！ 第01话 1080p WEB-DL AAC H.264.mp4',
      'SP01 (特典) 「夏日重现」.mkv',
      'episode 01/24 1080p.mkv',
      '[Loli] 咒术回战 第三季 - 01 V2 [1080p][CHS].mkv',
      '01/24 1080p.mkv',
      '命中排除规则：[v2]',
      '未命中包含规则：1080p',
    ]
    for (const title of readable) {
      expect(safeResourceTitle(title)).toBe(title)
    }
  })

  it('previews only a few safe samples and never invents extra values', () => {
    const seeds = ['01.mkv', '02.mkv', '03.mkv']
    expect(resourcePreview(seeds)).toEqual(['01.mkv', '02.mkv'])
    expect(resourcePreview(seeds, 1)).toEqual(['01.mkv'])
    expect(resourcePreview([])).toEqual([])
    expect(resourcePreview(['magnet:?xt=urn:btih:deadbeef', '02.mkv'])).toEqual(['[已隐藏资源地址]', '02.mkv'])
    expect(resourcePreview(['01.mkv'], -3)).toEqual([])
  })
})
