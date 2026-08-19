from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.config import PROJECT_ROOT
from shared.errors import Stage1Error


DEFAULT_STORAGE_DIR = PROJECT_ROOT / ".migu_orca" / "storage"


@dataclass(frozen=True)
class StorageConfig:
    storage_dir: Path
    requests_dir: Path
    history_dir: Path
    ab_results_dir: Path
    queue_dir: Path
    preferences_dir: Path
    corrections_dir: Path


def load_storage_config(storage_dir: Path | None = None) -> StorageConfig:
    root = (storage_dir or DEFAULT_STORAGE_DIR).expanduser()
    return StorageConfig(
        storage_dir=root,
        requests_dir=root / "requests",
        history_dir=root / "history",
        ab_results_dir=root / "ab_results",
        queue_dir=root / "queue",
        preferences_dir=root / "preferences",
        corrections_dir=root / "corrections",
    )


def ensure_storage_layout(config: StorageConfig) -> StorageConfig:
    for directory in (
        config.storage_dir,
        config.requests_dir,
        config.history_dir,
        config.ab_results_dir,
        config.queue_dir,
        config.preferences_dir,
        config.corrections_dir,
    ):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Stage1Error(
                "storage_error",
                "无法创建本地存储目录",
                "ensure_storage_layout",
                {"reason": str(exc), "directory": directory.name},
            ) from exc
        if not directory.is_dir():
            raise Stage1Error(
                "storage_error",
                "本地存储路径不是目录",
                "ensure_storage_layout",
                {"directory": directory.name},
            )
    return config
