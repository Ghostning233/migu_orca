"""Shared helpers for the two-screen add-anime journeys (Issues 110/113)."""

from __future__ import annotations

from playwright.sync_api import Page

SCREENS = ".add-anime-screens"


def wait_for_screen_scroll(page: Page, *, minimum: int = 100) -> None:
    """Wait until the two-screen container has scrolled onto a screen and settled.

    ``scrollTop > minimum`` alone can already be true mid smooth-scroll
    animation, so geometry measured right after it races the animation on
    slower runners. This waits until the position is unchanged across two
    animation frames after the container has moved past ``minimum``.
    """
    page.wait_for_function(
        """(minimum) => {
          const container = document.querySelector('.add-anime-screens')
          if (!container || container.scrollTop <= minimum) return false
          const top = container.scrollTop
          return new Promise((resolve) => {
            requestAnimationFrame(() =>
              requestAnimationFrame(() => resolve(container.scrollTop === top)),
            )
          })
        }""",
        arg=minimum,
    )
