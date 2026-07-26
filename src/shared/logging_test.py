from __future__ import annotations

import logging
from pathlib import Path

from shared.logging import configure_logging


def test_file_logging_is_opt_in(tmp_path: Path) -> None:
    log_file = tmp_path / "run.log"

    configure_logging(log_file)
    logging.getLogger("migu_orca_test").info("测试日志")
    logging.shutdown()

    assert "测试日志" in log_file.read_text(encoding="utf-8")
