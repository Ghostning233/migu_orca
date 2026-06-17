from __future__ import annotations

from apps.migu_orca_entry.controllers.entry_controller import main


def test_main_returns_success() -> None:
    assert main() == 0

