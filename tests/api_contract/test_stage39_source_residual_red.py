from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tracking_source_models_do_not_define_request_scoped_credentials() -> None:
    paths = [
        ROOT / "src/apps/migu_orca_web/schemas.py",
        ROOT / "src/apps/migu_orca_web/routes_tracking.py",
        ROOT / "src/apps/migu_orca_web/openapi_gen.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "_strip_retired_tracking_credentials" not in text
    assert "class TrackingSubmitPayload" not in text
    assert "request-scoped `ab_config`" not in text
    assert "legacy_credentials" not in text


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
