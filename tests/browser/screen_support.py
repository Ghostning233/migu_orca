"""Shared helpers for the two-screen add-anime journeys (Issues #140/#141/#143).

「添加番剧」的两屏由文档滚动承载：外层滚动属于 `html`，因此内容、内边距与宽屏
两侧留白都能驱动切屏。这里的 helper 统一等待切屏滚动稳定，避免把平滑动画的
中间态当成布局结果。
"""

from __future__ import annotations

from playwright.sync_api import Page

SCREENS = ".add-anime-screens"

SCREEN_TOPS_SCRIPT = """
() => {
  const padding = Number.parseFloat(
    getComputedStyle(document.documentElement).scrollPaddingTop) || 0
  const topOf = (selector) => {
    const element = document.querySelector(selector)
    if (!element) return null
    return element.getBoundingClientRect().top + window.scrollY - padding
  }
  return {
    hero: topOf('.single-home-hero') ?? topOf('.batch-search-screen'),
    workbench: topOf('.candidate-workbench-screen') ?? topOf('.batch-workbench-screen'),
    scrollY: window.scrollY,
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    scrollbarHidden: getComputedStyle(document.documentElement).scrollbarWidth === 'none',
    scrollbarGutter: window.innerWidth - document.documentElement.clientWidth,
  }
}
"""


def screen_metrics(page: Page) -> dict[str, float | bool | None]:
    """读取两屏的顶位（相对文档，已扣除 scroll-padding）与当前滚动位置。"""
    return page.evaluate(SCREEN_TOPS_SCRIPT)


def wait_for_screen_scroll(page: Page, *, minimum: int = 100, timeout: float = 8000) -> None:
    """等待文档完整停在第二屏顶部（平滑动画结束）。

    只检查「已经离开首屏」会在动画中途提前成立，因此这里同时要求文档位置已经落在
    工作台顶部 0.5px 内，并在连续两帧内不再变化。
    """
    page.wait_for_function(
        """(minimum) => {
          const workbench = document.querySelector('.candidate-workbench-screen')
            ?? document.querySelector('.batch-workbench-screen')
          if (!workbench) return false
          if (window.scrollY <= minimum) return false
          const padding = Number.parseFloat(
            getComputedStyle(document.documentElement).scrollPaddingTop) || 0
          const top = workbench.getBoundingClientRect().top + window.scrollY - padding
          if (Math.abs(window.scrollY - top) > 0.5) return false
          const at = window.scrollY
          return new Promise((resolve) => {
            requestAnimationFrame(() =>
              requestAnimationFrame(() => resolve(Math.abs(window.scrollY - at) <= 0.01)),
            )
          })
        }""",
        arg=minimum,
        timeout=timeout,
    )


def wait_for_hero_top(page: Page) -> None:
    """等待文档回到搜索首屏顶部并停稳。"""
    page.wait_for_function(
        """() => {
          if (window.scrollY > 2) return false
          const top = window.scrollY
          return new Promise((resolve) => {
            requestAnimationFrame(() =>
              requestAnimationFrame(() => resolve(window.scrollY === top)),
            )
          })
        }"""
    )


def wait_for_scroll_idle(page: Page, *, quiet_ms: int = 250, timeout: float = 8000) -> None:
    """等待滚动真正停下来（按真实时间采样，而不是按帧）。

    平滑滚动与滚轮动量都会让位置连续变化；「两帧不变」可能在动画中途提前成立，
    因此这里要求位置在 ``quiet_ms`` 真实时间内不再变化。
    """
    page.wait_for_function(
        """(quiet) => {
          const now = performance.now()
          const position = window.scrollY
          if (window.__scrollIdlePosition !== position) {
            window.__scrollIdlePosition = position
            window.__scrollIdleSince = now
            return false
          }
          return now - window.__scrollIdleSince >= quiet
        }""",
        arg=quiet_ms,
        timeout=timeout,
    )


def wheel_at(page: Page, x: float, y: float, delta_y: int) -> None:
    """在指定视口坐标派发一次真实滚轮手势。"""
    page.mouse.move(x, y)
    page.mouse.wheel(0, delta_y)
