from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_retired_batch_queue_write_runtime_has_no_live_wiring() -> None:
    """US335/336: queue/batch submit is migration-only, never a web runtime seam."""
    services = (ROOT / "src/apps/migu_orca_web/services.py").read_text(encoding="utf-8")
    submission = (ROOT / "src/apps/migu_orca_web/tracking_submission_service.py").read_text(encoding="utf-8")
    assert "batch_engine.controllers.batch_accept_controller" not in services
    assert "storage_engine.controllers.queue_repository" not in services
    assert "save_submission_queue" not in services
    assert "batch_engine.controllers.batch_submit_controller" not in submission
    assert "compose_ab_submit_one" not in submission

    accept = (ROOT / "src/batch_engine/controllers/batch_accept_controller.py").read_text(encoding="utf-8")
    submit = (ROOT / "src/batch_engine/controllers/batch_submit_controller.py").read_text(encoding="utf-8")
    queue_repo = (ROOT / "src/storage_engine/controllers/queue_repository.py").read_text(encoding="utf-8")
    assert "def accept_batch" not in accept
    assert "def submit_batch" not in submit
    assert "def retry_batch" not in submit
    assert "def recover_batch" not in submit
    assert "def save_submission_queue" not in queue_repo


def test_formal_frontend_does_not_project_retired_queue_dtos() -> None:
    sources = [
        ROOT / "frontend/src/features/workbench/BatchWorkbenchView.vue",
        ROOT / "frontend/src/features/tracking/TrackingView.vue",
        ROOT / "tests/browser/test_app_batch_workbench.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    assert "result as unknown as { queue?" not in text
    assert ").queue?.items" not in text
    assert "queue_status" not in text
    assert "/api/v1/batches/{batch_id}/queue" not in text
    assert '"queue": {' not in text
    assert "tracking_id" in text
    assert "tracking_ready" in text


def test_endpoint_inventory_has_no_retired_qb_contract() -> None:
    text = (ROOT / "docs/api/endpoint_inventory.md").read_text(encoding="utf-8").lower()
    assert "qbittorrent_auth_failed" not in text
    assert "qbittorrent_connection_failed" not in text
    assert "qbittorrent_timeout" not in text
    assert "### 3.5 连接测试" not in text
    assert "_sanitize_qbittorrent_connection_summary" not in text
    assert "qbittorrent_config" not in text


def test_tracking_source_models_do_not_define_request_scoped_credentials() -> None:
    paths = [
        ROOT / "src/apps/migu_orca_web/schemas.py",
        ROOT / "src/apps/migu_orca_web/routes_tracking.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "_strip_retired_tracking_credentials" not in text
    assert "class TrackingSubmitPayload" not in text
    assert "request-scoped `ab_config`" not in text
    for forbidden in ("legacy_config", "legacy_credentials", "saved_connection"):
        assert forbidden not in text


def test_tracking_tests_do_not_encode_retired_credential_flow() -> None:
    paths = [
        ROOT / "tests/browser/test_app_tracking.py",
        ROOT / "frontend/src/features/tracking/trackingManagement.test.ts",
        ROOT / "frontend/src/features/tracking/trackingProjection.test.ts",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "/api/v1/autobangumi/capabilities" not in text
    assert "#tracking-connect" not in text
    assert "CredentialSessionDialog" not in text
    assert "ab_config" not in text
