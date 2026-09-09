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
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_ONLY) == {
        "MODIFY", "SET_ENABLED", "DELETE_EXTERNAL", "REFRESH_RSS",
    }
    assert management_actions_for_status(TRACKING_STATUS_DISABLED) == {"SET_ENABLED", "DELETE_EXTERNAL"}
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_DELETED) == set()
    assert not management_action_allowed(TRACKING_STATUS_DISABLED, "MODIFY")
