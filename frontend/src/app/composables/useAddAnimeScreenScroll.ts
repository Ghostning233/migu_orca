/**
 * 「添加番剧」两屏滚动所有权（父规格 #139；#140 切屏、#141 单轴长内容、#143 批量双栏）。
 *
 * 已确认的目标行为：
 * - 外层滚动属于文档：`#app-main` 内容、内边距与宽屏两侧留白都能驱动切屏；
 *   顶部一级导航保持可见；外层滚动条永久隐藏，但滚轮、触控板与键盘仍可滚动。
 *   该模式只由「添加番剧」页面挂载时启用（根元素类名），不改变其他一级页面。
 * - 搜索首屏与工作台屏像两页：一次向下手势完整、平滑地停到工作台顶部；工作台内容
 *   滚到顶部后，同一次手势必须停住，只有下一次向上手势才完整回到首屏；不中途停在
 *   两屏分界处（`resolveScreenRest` 会把落在两屏之间的停顿收敛到最近一屏）。
 * - 批量工作台的左右栏是内部滚动所有者（`data-screen-scroll="inner"`）：栏内滚到
 *   边界不切屏，只有模块外空白区或明确的返回按钮才切屏。
 *
 * 纯决策函数（`decideWheelIntent` / `resolveScreenRest`）与 DOM 绑定分离，便于在
 * Vitest 里覆盖手势边界，真实浏览器用例只验证可观察结果。
 */
import { onBeforeUnmount, onMounted, type Ref } from 'vue'

/** 根元素类名：由「添加番剧」页面挂载时开关文档级滚动模式。 */
export const ADD_ANIME_SCROLL_ROOT_CLASS = 'add-anime-scroll'

/** 内部滚动所有者标记：落在其中的滚轮只操作该容器，不参与切屏判定。 */
export const INNER_SCROLL_ATTRIBUTE = 'data-screen-scroll'

/** 判定「已在某屏顶部」的像素容差。 */
export const SCREEN_EDGE_EPSILON = 4

/** 连续滚轮事件之间的静默时长；超过它视为新手势。 */
export const WHEEL_GESTURE_IDLE_MS = 180

/** 滚轮/触控板手势结束后仍允许停靠收敛的时间窗。 */
export const WHEEL_SETTLE_WINDOW_MS = 600

/** 判定第二屏几何「连续两帧稳定」的像素容差。 */
export const SCREEN_GEOMETRY_EPSILON = 0.5

/** 切屏目标的几何：相对文档的 top 与渲染高度。 */
export interface ScreenGeometry {
  top: number
  height: number
}

/**
 * 连续两帧的几何是否在容差内稳定。
 *
 * 必须同时比较**文档 top 与高度**：只比高度会把「第一屏收尾导致第二屏整体位移」的
 * 中间态误判为稳定，从而用过期坐标切屏。
 */
export function screenGeometryIsStable(
  previous: ScreenGeometry | null,
  current: ScreenGeometry | null,
  epsilon: number = SCREEN_GEOMETRY_EPSILON,
): boolean {
  if (!previous || !current) return false
  return (
    Math.abs(current.top - previous.top) <= epsilon
    && Math.abs(current.height - previous.height) <= epsilon
  )
}

/** 等待切屏真正停到目标位置的有界兜底时长。 */
export const SCREEN_SWITCH_SETTLE_MS = 1500

/**
 * 等待第二屏「真实可见 + 文档位置连续两帧不变」的有界兜底时长。
 *
 * 用可观察条件收口而不是叠加任意 `nextTick()`/固定延时；后台标签页里
 * `requestAnimationFrame` 不触发，因此保留这个计时器兜底。
 */
export const SCREEN_READY_DEADLINE_MS = 1000

export type ScreenKey = 'first' | 'second'

export type WheelIntent = ScreenKey | 'hold' | 'native'

export interface WheelDecisionInput {
  scrollY: number
  firstTop: number
  secondTop: number | null
  deltaY: number
  /** 同一次手势里已经滚动过工作台内容（用于「刚到顶先停住」）。 */
  gestureConsumedContent: boolean
  /** 切屏动画进行中：吞掉滚轮事件，避免与动画争夺位置。 */
  locked: boolean
  insideInnerScroll: boolean
}

/** 一次滚轮事件的切屏意图。 */
export function decideWheelIntent(input: WheelDecisionInput): WheelIntent {
  const { scrollY, firstTop, secondTop, deltaY, gestureConsumedContent, locked, insideInnerScroll } = input
  if (locked) return 'hold'
  if (insideInnerScroll) return 'native'
  if (!Number.isFinite(deltaY) || Math.abs(deltaY) < 1) return 'native'
  if (deltaY > 0) {
    if (secondTop === null) return 'native'
    return scrollY <= firstTop + SCREEN_EDGE_EPSILON ? 'second' : 'native'
  }
  // 向上滚动：已经在首屏顶部就无事可做，交给原生滚动。
  if (scrollY <= firstTop + SCREEN_EDGE_EPSILON) return 'native'
  if (secondTop === null) return 'native'
  // 还在工作台内容中间：原生滚动（先滚到工作台顶部）。
  if (scrollY > secondTop + SCREEN_EDGE_EPSILON) return 'native'
  // 已在工作台顶部：同一次手势先停住，下一次手势才回首屏。
  return gestureConsumedContent ? 'hold' : 'first'
}

/** 停止滚动后，落在两屏之间的位置该收敛到哪一屏；已经在某一屏上则返回 null。 */
export function resolveScreenRest(
  scrollY: number,
  firstTop: number,
  secondTop: number | null,
  epsilon: number = SCREEN_EDGE_EPSILON,
): ScreenKey | null {
  if (secondTop === null) return null
  if (scrollY <= firstTop + epsilon) return null
  if (scrollY >= secondTop - epsilon) return null
  return scrollY < (firstTop + secondTop) / 2 ? 'first' : 'second'
}

export interface AddAnimeScreenScrollOptions {
  /** 上方搜索首屏元素。 */
  firstScreen: Ref<HTMLElement | null>
  /** 下方工作台屏元素；未挂载时返回 null（加载/失败/无候选仍留在首屏）。 */
  secondScreen: Ref<HTMLElement | null>
}

export interface AddAnimeScreenScrollController {
  /** 完整、平滑地回到搜索首屏；动画结束后 resolve（减少动态效果时立即返回）。 */
  goToFirstScreen: () => Promise<void>
  /** 完整、平滑地进入工作台顶部。 */
  goToSecondScreen: (options?: GoToSecondScreenOptions) => Promise<void>
}

export interface GoToSecondScreenOptions {
  /**
   * 第二屏已经真实可见、文档位置也稳定之后、计算切屏目标之前执行一次。
   *
   * 这是「把焦点移到结果标题」这类一次性准备的入口：它必须发生在最终布局上，
   * 因此在同一个等待条件里执行，而不是由调用方再叠一层 `nextTick()`。
   */
  onReady?: () => void
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

function scrollPaddingTop(): number {
  if (typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') return 0
  const parsed = Number.parseFloat(window.getComputedStyle(document.documentElement).scrollPaddingTop)
  return Number.isFinite(parsed) ? parsed : 0
}

function isInsideInnerScroll(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  // `inner`：永远是内部滚动所有者（批量双栏：栏内滚到边界也不切屏）。
  if (target.closest(`[${INNER_SCROLL_ATTRIBUTE}="inner"]`)) return true
  // `overflow`：只有真的溢出、能滚动时才接管滚轮（批量工作台屏在极窄视口或
  // 200% 缩放下装不下时退化为自身滚动；正常桌面没有溢出，滚轮仍用于切屏）。
  const owner = target.closest(`[${INNER_SCROLL_ATTRIBUTE}="overflow"]`)
  if (!(owner instanceof HTMLElement)) return false
  return owner.scrollHeight > owner.clientHeight + 1
}

function isInsideModal(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  return target.closest('[aria-modal="true"]') !== null
}

/**
 * 绑定文档级滚动、滚轮切屏与停靠收敛；返回可被按钮和搜索流程复用的控制器。
 *
 * 调用方负责在页面卸载时停止使用（组合式函数自行注销监听并移除根类名）。
 */
export function useAddAnimeScreenScroll(
  options: AddAnimeScreenScrollOptions,
): AddAnimeScreenScrollController {
  const supportsScrollEnd = typeof window !== 'undefined' && 'onscrollend' in window
  let gestureConsumedContent = false
  let gestureTimer: ReturnType<typeof setTimeout> | undefined
  let locked = false
  let switchToken = 0
  let lastWheelAt = 0
  let scrollIdleTimer: ReturnType<typeof setTimeout> | undefined

  /** 第二屏当前的文档几何；未挂载或没有渲染高度时返回 null。 */
  function secondScreenGeometry(): ScreenGeometry | null {
    const element = options.secondScreen.value
    if (!element) return null
    const rect = element.getBoundingClientRect()
    if (rect.height <= 0) return null
    return { top: rect.top + window.scrollY, height: rect.height }
  }

  function screenTop(key: ScreenKey): number | null {
    const element = key === 'first' ? options.firstScreen.value : options.secondScreen.value
    // 未挂载或 `v-show` 隐藏（`display: none`）的屏不是切屏目标：它的盒模型为零，
    // 直接用 rect 会算出一个虚假的顶位（例如 -scrollPaddingTop）并骗过切屏判断。
    if (!element || element.getBoundingClientRect().height <= 0) return null
    return element.getBoundingClientRect().top + window.scrollY - scrollPaddingTop()
  }

  /**
   * 等到文档真的停到目标位置。`scrollend` 在平滑滚动中可能提前到达，因此这里以
   * 可观察结果为准（进入 1px 并稳住一帧），并保留一个有界兜底，避免被中断时永久锁定。
   */
  function waitUntilAtTarget(target: number, deadline = SCREEN_SWITCH_SETTLE_MS): Promise<void> {
    return new Promise((resolve) => {
      const startedAt = performance.now()
      let previous: number | null = null
      // 计时器兜底：后台标签页里 rAF 不触发，await 也必须能结束。
      const timer = setTimeout(finish, deadline)
      function finish(): void {
        clearTimeout(timer)
        resolve()
      }
      const check = (): void => {
        const position = window.scrollY
        const atTarget = Math.abs(position - target) <= 1
        if (atTarget && previous === position) {
          finish()
          return
        }
        if (performance.now() - startedAt >= deadline) {
          finish()
          return
        }
        previous = position
        requestAnimationFrame(check)
      }
      requestAnimationFrame(check)
    })
  }

  /**
   * 等第二屏进入「可切屏」的稳定布局。
   *
   * 切屏目标必须取自最终稳定布局，因此等待条件同时覆盖：第二屏存在并渲染出高度、
   * 它的**文档坐标 top** 与高度连续两帧在合理误差内不变。只看高度不足以证明稳定——
   * 第一屏的进度条/loading 收尾时第二屏高度可能不变，但它的文档 top 仍会变化，
   * 提前取目标就会用过期坐标造成错误切屏或回跳。
   *
   * 这里用可观察几何收口，不做 sleep、也不叠加任意 `nextTick()`；后台标签页里
   * `requestAnimationFrame` 不触发，因此保留 `SCREEN_READY_DEADLINE_MS` 计时器兜底，
   * 超时后安全返回（找不到目标就不滚动），绝不永久锁定滚动。
   */
  function waitForSecondScreenReady(deadline = SCREEN_READY_DEADLINE_MS): Promise<void> {
    // 没有真实布局信息（jsdom 等测试环境）时几何稳定性不可观测：直接返回，
    // 既不误判成「已稳定」，也不无意义地等满兜底时长。
    if (document.documentElement.clientHeight <= 0) return Promise.resolve()
    return new Promise((resolve) => {
      const startedAt = performance.now()
      let finished = false
      let previous: ScreenGeometry | null = null
      const finish = (): void => {
        if (finished) return
        finished = true
        clearTimeout(timer)
        resolve()
      }
      const timer = setTimeout(finish, deadline)
      const check = (): void => {
        if (finished) return
        const geometry = secondScreenGeometry()
        if (screenGeometryIsStable(previous, geometry)) {
          finish()
          return
        }
        previous = geometry
        if (performance.now() - startedAt >= deadline) {
          finish()
          return
        }
        requestAnimationFrame(check)
      }
      requestAnimationFrame(check)
    })
  }

  async function goToScreen(key: ScreenKey): Promise<void> {
    const top = screenTop(key)
    if (top === null) return
    const target = Math.max(0, top)
    // 只有最新一次切屏可以解锁：两次切屏重叠时旧的完成回调不能放开滚轮。
    const token = ++switchToken
    locked = true
    if (prefersReducedMotion()) {
      // 减少动态效果：即时定位，但焦点与内容仍然正确。
      window.scrollTo({ top: target, behavior: 'auto' })
      if (token === switchToken) locked = false
      return
    }
    window.scrollTo({ top: target, behavior: 'smooth' })
    await waitUntilAtTarget(target)
    if (token === switchToken) locked = false
  }

  function noteGesture(deltaY: number): void {
    // 只有真正让工作台内容滚动的向上手势才算「本次手势已消费内容」。
    if (!locked && deltaY < 0) gestureConsumedContent = true
    lastWheelAt = performance.now()
    if (gestureTimer !== undefined) clearTimeout(gestureTimer)
    gestureTimer = setTimeout(() => {
      gestureConsumedContent = false
    }, WHEEL_GESTURE_IDLE_MS)
  }

  function onWheel(event: WheelEvent): void {
    if (event.ctrlKey || event.defaultPrevented) return
    if (isInsideModal(event.target)) return
    const decision = decideWheelIntent({
      scrollY: window.scrollY,
      firstTop: screenTop('first') ?? 0,
      secondTop: screenTop('second'),
      deltaY: event.deltaY,
      gestureConsumedContent,
      locked,
      insideInnerScroll: isInsideInnerScroll(event.target),
    })
    noteGesture(event.deltaY)
    if (decision === 'native') return
    event.preventDefault()
    if (decision === 'hold') return
    void goToScreen(decision)
  }

  /**
   * 手势滚动结束后的停靠收敛：只处理滚轮/触控板造成的停靠，键盘与程序化滚动
   * 保持原生语义（键盘用户需要能自由到达两屏之间的任意位置）。
   *
   * 手势把长工作台滚过顶部时，先回到工作台顶部（本次手势「先停住」）；只有下一次
   * 独立手势才会完整回到首屏。
   */
  function settleScreenPosition(): void {
    // 切屏动画进行中：由 goToScreen 自己收口，这里不重复干预。
    if (locked) return
    if (performance.now() - lastWheelAt > WHEEL_SETTLE_WINDOW_MS) return
    const first = screenTop('first')
    const second = screenTop('second')
    if (first === null || second === null) return
    const rest = resolveScreenRest(window.scrollY, first, second)
    if (rest === null) return
    void goToScreen(gestureConsumedContent ? 'second' : rest)
  }

  function onScrollEnd(): void {
    settleScreenPosition()
  }

  function onScroll(): void {
    if (supportsScrollEnd) return
    if (scrollIdleTimer !== undefined) clearTimeout(scrollIdleTimer)
    scrollIdleTimer = setTimeout(settleScreenPosition, 120)
  }

  onMounted(() => {
    document.documentElement.classList.add(ADD_ANIME_SCROLL_ROOT_CLASS)
    window.addEventListener('wheel', onWheel, { passive: false })
    if (supportsScrollEnd) {
      document.addEventListener('scrollend', onScrollEnd)
    } else {
      document.addEventListener('scroll', onScroll, { passive: true })
    }
  })

  onBeforeUnmount(() => {
    document.documentElement.classList.remove(ADD_ANIME_SCROLL_ROOT_CLASS)
    window.removeEventListener('wheel', onWheel)
    document.removeEventListener('scrollend', onScrollEnd)
    document.removeEventListener('scroll', onScroll)
    if (gestureTimer !== undefined) clearTimeout(gestureTimer)
    if (scrollIdleTimer !== undefined) clearTimeout(scrollIdleTimer)
  })

  return {
    goToFirstScreen: () => goToScreen('first'),
    /**
     * 程序化进入工作台：第二屏真的可见之后再按最终布局取目标切屏。
     *
     * 滚轮驱动的切屏不走这条等待（第二屏本来就已渲染稳定），保持手势响应即时。
     */
    goToSecondScreen: async (readyOptions?: GoToSecondScreenOptions) => {
      await waitForSecondScreenReady()
      readyOptions?.onReady?.()
      await goToScreen('second')
    },
  }
}
