from __future__ import annotations

"""US-237 pure management operation contracts."""

import pytest

from tracking_engine.controllers.management_operation import (
    MANAGEMENT_OUTCOME_DEFINITE_FAILURE,
    MANAGEMENT_OUTCOME_RECOVERY_REQUIRED,
    MANAGEMENT_OUTCOME_SUCCESS,
    MANAGEMENT_OUTCOME_UNKNOWN,
    canonical_management_fingerprint,
    classify_management_action,
    classify_management_readback,
)


def test_fingerprint_is_deterministic_and_only_returns_a_sha256_summary() -> None:
    first = canonical_management_fingerprint(
        action="MODIFY",
        target_scope="SUBSCRIPTION",
        expected_projection={"title": "公开标题", "enabled": True},
    )
    second = canonical_management_fingerprint(
        action="MODIFY",
        target_scope="SUBSCRIPTION",
        expected_projection={"enabled": True, "title": "公开标题"},
    )

    assert first == second
    assert first.startswith("sha256:")
    assert "公开标题" not in first


def test_legacy_fingerprint_stays_frozen_while_saved_refs_are_isolated() -> None:
    legacy = canonical_management_fingerprint(
        action="MODIFY", target_scope="SUBSCRIPTION", expected_projection={"title": "公开标题"}
    )
    assert legacy == "sha256:dd2faf6548f935c3d6b26b686d53d746c5907688de082ae136f1b74ebc58bb53"
    first = canonical_management_fingerprint(
        action="MODIFY",
        target_scope="SUBSCRIPTION",
        expected_projection={"title": "公开标题"},
        connection_ref="11111111-1111-4111-8111-111111111111",
    )
    second = canonical_management_fingerprint(
        action="MODIFY",
        target_scope="SUBSCRIPTION",
        expected_projection={"title": "公开标题"},
        connection_ref="22222222-2222-4222-8222-222222222222",
    )
    assert first != second


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"status_code": 204}, MANAGEMENT_OUTCOME_SUCCESS),
        ({"status_code": 400}, MANAGEMENT_OUTCOME_DEFINITE_FAILURE),
        ({"status_code": 503}, MANAGEMENT_OUTCOME_UNKNOWN),
        ({"transport_error": "timeout"}, MANAGEMENT_OUTCOME_UNKNOWN),
        ({"status_code": 200, "response_valid": False}, MANAGEMENT_OUTCOME_UNKNOWN),
        ({"status_code": 204, "persisted": False}, MANAGEMENT_OUTCOME_RECOVERY_REQUIRED),
    ],
)
def test_action_classifier_covers_safe_outcomes(kwargs: dict[str, object], expected: str) -> None:
    assert classify_management_action(**kwargs) == expected


def test_readback_classifier_distinguishes_match_mismatch_and_unknown() -> None:
    digest = "sha256:" + "a" * 64
    assert (
        classify_management_readback(expected_fingerprint=digest, actual_fingerprint=digest, read_succeeded=True)
        == MANAGEMENT_OUTCOME_SUCCESS
    )
    assert (
        classify_management_readback(
            expected_fingerprint=digest, actual_fingerprint="sha256:" + "b" * 64, read_succeeded=True
        )
        == MANAGEMENT_OUTCOME_DEFINITE_FAILURE
    )
    assert (
        classify_management_readback(expected_fingerprint=digest, actual_fingerprint=None, read_succeeded=False)
        == MANAGEMENT_OUTCOME_UNKNOWN
    )
