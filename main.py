from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap() -> None:
    src_dir = Path(__file__).resolve().parent / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def main() -> int:
    _bootstrap()
    from apps.migu_orca_entry.controllers.entry_controller import main as entry_main

    return entry_main()


if __name__ == "__main__":
    raise SystemExit(main())

