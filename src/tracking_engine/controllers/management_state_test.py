from tracking_engine.controllers.management_state import management_action_allowed, management_actions_for_status
from tracking_engine.models.tracking import (
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_DISABLED,
    TRACKING_STATUS_EXTERNAL_DELETED,
    TRACKING_STATUS_EXTERNAL_ONLY,
)


def test_frozen_management_state_matrix_has_no_implicit_actions() -> None:
    assert management_actions_for_status(TRACKING_STATUS_ACTIVE) == {
        "MODIFY", "SET_ENABLED", "REFRESH_RSS",
    }
    # Issue #224 A4 / ADR-0005: the retired read-only EXTERNAL_ONLY archive gets
    # no management action in the public projection or the normal write path, so
    # a client cannot manage a record this product never adopted. Only the
    # page-level 删除追番方案 / 复制并重新添加 remain.
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_ONLY) == set()
    assert not management_action_allowed(TRACKING_STATUS_EXTERNAL_ONLY, "MODIFY")
    assert not management_action_allowed(TRACKING_STATUS_EXTERNAL_ONLY, "DELETE_EXTERNAL")
    # Issue #218 exception (a): the internal plan-delete leg keeps exactly one
    # executable action, so deleting the plan cannot orphan an AB object.
    assert management_actions_for_status(
        TRACKING_STATUS_EXTERNAL_ONLY, include_internal=True
    ) == {"DELETE_EXTERNAL"}
    assert management_action_allowed(
        TRACKING_STATUS_EXTERNAL_ONLY, "DELETE_EXTERNAL", include_internal=True
    )
    for retired_action in ("MODIFY", "SET_ENABLED", "REFRESH_RSS"):
        assert not management_action_allowed(
            TRACKING_STATUS_EXTERNAL_ONLY, retired_action, include_internal=True
        )
    assert management_actions_for_status(TRACKING_STATUS_DISABLED) == {"SET_ENABLED"}
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_DELETED) == set()
    assert not management_action_allowed(TRACKING_STATUS_DISABLED, "MODIFY")


def test_standalone_external_delete_is_never_announced_but_stays_executable() -> None:
    """#228 E4: retire the public entry, keep the internal execution chain.

    ``tracking_plan_delete_service`` still runs ``DELETE_EXTERNAL`` for the
    composite "delete the plan + its controlled external subscription" flow
    (AGENTS.md exception (a)) from every mapped status, so the internal leg must
    keep permitting it while no public projection may announce it.
    """
    for status in (
        TRACKING_STATUS_ACTIVE,
        TRACKING_STATUS_DISABLED,
        TRACKING_STATUS_EXTERNAL_ONLY,
    ):
        assert "DELETE_EXTERNAL" not in management_actions_for_status(status)
        assert not management_action_allowed(status, "DELETE_EXTERNAL")
        assert management_actions_for_status(status, include_internal=True) >= {"DELETE_EXTERNAL"}
        assert management_action_allowed(status, "DELETE_EXTERNAL", include_internal=True) is True
    # The internal door widens nothing else: the public actions are unchanged.
    assert management_actions_for_status(
        TRACKING_STATUS_EXTERNAL_ONLY, include_internal=True
    ) == {"DELETE_EXTERNAL"}
    for retired_action in ("MODIFY", "SET_ENABLED", "REFRESH_RSS"):
        assert not management_action_allowed(
            TRACKING_STATUS_EXTERNAL_ONLY, retired_action, include_internal=True
        )
    assert management_actions_for_status(TRACKING_STATUS_EXTERNAL_DELETED, include_internal=True) == set()
