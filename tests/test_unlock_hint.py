"""``can_unlock`` on the call status sensor: whether the caller has a door a dashboard may offer to open."""

import pytest

from custom_components.hikvision_intercom.sensor import unlock_hint

DOOR = {"devType": 1, "devNo": 0, "lockNum": 1}
GUARD = {"devType": -1, "devNo": 0, "lockNum": 0}


@pytest.mark.parametrize("status", ["ringing", "call in progress"])
def test_a_door_station_with_a_lock_can_be_unlocked_while_it_calls(status):
    assert unlock_hint(status, DOOR) == {"can_unlock": True}


@pytest.mark.parametrize("status", ["ringing", "call in progress"])
def test_a_caller_with_no_lock_cannot_be_unlocked(status):
    assert unlock_hint(status, GUARD) == {"can_unlock": False}
    assert unlock_hint(status, {}) == {"can_unlock": False}, (
        "a call that comes with no caller info"
    )
    assert unlock_hint(status, {"lockNum": "1"}) == {"can_unlock": False}, (
        "only a count counts"
    )
    assert unlock_hint(status, {"lockNum": 2}) == {"can_unlock": True}


@pytest.mark.parametrize("status", ["idle", "unknown", None, "unavailable"])
def test_nothing_is_published_when_no_call_is_going(status):
    assert unlock_hint(status, DOOR) == {}
