from __future__ import annotations

from pathlib import Path

from apps.base import create_app

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

    accept_path = ROOT / "src/batch_engine/controllers/batch_accept_controller.py"
    submit_path = ROOT / "src/batch_engine/controllers/batch_submit_controller.py"
    queue_repo = (ROOT / "src/storage_engine/controllers/queue_repository.py").read_text(encoding="utf-8")
    assert not accept_path.exists()
    assert not submit_path.exists()
    assert "def save_submission_queue" not in queue_repo
    assert "def write_legacy_queue_fixture" not in queue_repo
    assert "queue_path.write_text" not in queue_repo
    for forbidden in (
        "def create_submission_queue",
        "def enqueue_item",
        "def start_queue_item_submit",
        "def complete_queue_item_submit",
        "def mark_queue_item_failed",
        "def mark_queue_item_retry_failed",
    ):
        assert forbidden not in (ROOT / "src/batch_engine/controllers/batch_queue_controller.py").read_text(encoding="utf-8")


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


def test_batch_parse_contract_has_tracking_fields_only() -> None:
    dto = (ROOT / "src/apps/migu_orca_web/api_contract.py").read_text(encoding="utf-8")
    openapi = (ROOT / "docs/api/openapi.json").read_text(encoding="utf-8")
    generated = (ROOT / "frontend/src/api/generated/api.ts").read_text(encoding="utf-8")
    assert "class BatchParseItemDTO" in dto
    assert "queue_status" not in dto
    assert '"queue_status"' not in openapi
    assert "queue_status:" not in generated
    assert "tracking_id" in dto and "tracking_ready" in dto


def test_production_queue_controller_has_no_runtime_state_machine() -> None:
    source = (ROOT / "src/batch_engine/controllers/batch_queue_controller.py").read_text(encoding="utf-8")
    forbidden = (
        "legacy_create_queue", "legacy_enqueue_item", "legacy_start_queue_item_submit",
        "legacy_complete_queue_item_submit", "legacy_mark_queue_item_failed",
        "legacy_mark_queue_item_retry_failed", "serialize_queue", "serialize_queue_item",
        "queue_to_storage_dict", "queue_item_to_storage_dict",
    )
    for symbol in forbidden:
        assert f"def {symbol}(" not in source
    assert "def queue_from_storage_dict(" in source
    assert "def queue_item_from_storage_dict(" in source


def test_preview_save_is_not_a_public_endpoint() -> None:
    client = create_app("testing").test_client()
    for method in ("get", "post"):
        response = getattr(client, method)("/api/v1/requests/preview-save")
        assert response.status_code == 404, (method, response.status_code, response.get_data(as_text=True))


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
