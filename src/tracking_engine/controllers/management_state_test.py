from tracking_engine.controllers.management_state import management_action_allowed, management_actions_for_status
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_EXTERNAL_ONLY,
)


def test_frozen_management_state_matrix_has_no_implicit_actions() -> None:
    assert management_actions_for_status(TRACKING_STATUS_ACTIVE) == {
        "MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS",
    }
    # Issue #224 A4 / ADR-0005: the retired read-only EXTERNAL_ONLY archive gets
    # no management action at all — not in the read projection and not here in
    # the write policy, so a client cannot manage a record this product never
    # adopted. Only the page-level 删除追番方案 / 复制并重新添加 remain.
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_ONLY) == set()
    assert not management_action_allowed(TRACKING_STATUS_EXTERNAL_ONLY, "MODIFY")
    assert not management_action_allowed(TRACKING_STATUS_EXTERNAL_ONLY, "DELETE_EXTERNAL")
    assert management_actions_for_status(TRACKING_STATUS_DISABLED) == {"SET_ENABLED", "DELETE_EXTERNAL"}
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_DELETED) == set()
    assert not management_action_allowed(TRACKING_STATUS_DISABLED, "MODIFY")
