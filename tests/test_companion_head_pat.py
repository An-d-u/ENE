"""합성 입력과 단조 시계로 PC 권위의 쓰다듬기 수명을 검증한다."""

import pytest

from src.core.companion.head_pat import HeadPatCoordinator
from tests.companion_helpers import sample_id


MODEL = "a" * 64


@pytest.fixture
def pat():
    now, counted, events = [0.0], [], []
    value = HeadPatCoordinator(lambda: counted.append(1), events.append, now=lambda: now[0])
    value.bind("pc", sample_id(1))
    value.bind("phone", sample_id(2))
    value.configure(MODEL, enabled=True)
    return value, now, counted, events


def message(number=1, phase="start", seq=0, **changes):
    return {"model_version": MODEL, "interaction_id": sample_id(100 + number),
            "interaction_no": number, "seq": seq, "phase": phase, "intensity": .5, **changes}


def send(pat, number=1, phase="start", seq=0, *, source="phone", connection=None, **changes):
    return pat[0].receive(source, connection or sample_id(1 if source == "pc" else 2),
                          message(number, phase, seq, **changes))


def test_normal_end_counts_once_and_duplicate_does_not_extend_or_restart(pat):
    assert send(pat)["phase"] == "accepted"
    pat[1][0] = 1.0
    assert send(pat)["phase"] == "accepted"
    assert len(pat[3]) == 1
    assert send(pat, phase="update", seq=1)["phase"] == "update"
    assert send(pat, phase="end", seq=2)["phase"] == "ended"
    assert send(pat, phase="end", seq=2)["phase"] == "ended"
    assert pat[2] == [1] and pat[0].active is None
    assert [item["phase"] for item in pat[3]] == ["accepted", "update", "ended"]


def test_first_pc_or_phone_session_wins_and_busy_number_cannot_be_reused(pat):
    send(pat, source="pc")
    assert send(pat)["reason"] == "busy"
    send(pat, phase="end", seq=1, source="pc")
    assert send(pat)["phase"] == "rejected"
    assert pat[0].active is None and pat[2] == [1]
    assert send(pat, 2)["phase"] == "accepted"


def test_end_before_start_consumes_number_and_does_not_cancel_other_session(pat):
    send(pat, source="pc")
    assert send(pat, phase="end", seq=2)["phase"] == "rejected"
    assert send(pat)["phase"] == "rejected"
    assert pat[0].active.source == "pc" and not pat[2]


def test_duplicate_start_and_stale_update_do_not_renew_lease(pat):
    send(pat)
    pat[1][0] = 1.9
    send(pat)
    send(pat, phase="update", seq=0)
    pat[1][0] = 2.0
    pat[0].tick()
    assert pat[0].active is None and not pat[2]
    assert pat[3][-1]["phase"] == "cancelled" and pat[3][-1]["reason"] == "lease_expired"
    assert send(pat, phase="end", seq=3)["phase"] == "rejected"


@pytest.mark.parametrize("cause", ["model", "disabled", "disconnect", "cancel"])
def test_cancellation_never_counts_and_late_end_cannot_revive(pat, cause):
    send(pat)
    if cause == "model":
        pat[0].configure("b" * 64, enabled=True)
    elif cause == "disabled":
        pat[0].configure(MODEL, enabled=False)
    elif cause == "disconnect":
        pat[0].bind("phone", None)
    else:
        send(pat, phase="cancel", seq=1)
    assert pat[0].active is None and not pat[2]
    assert send(pat, phase="end", seq=2)["phase"] == "rejected"


def test_cache_eviction_does_not_allow_old_interaction_number(pat):
    old = message()
    for number in range(1, 270):
        send(pat, number)
        send(pat, number, "end", 1)
    assert len(pat[0].history) == 256 and len(pat[2]) == 269
    assert pat[0].receive("phone", sample_id(2), old)["phase"] == "rejected"
    assert pat[0].active is None
    assert send(pat, 270, interaction_id=sample_id(369))["reason"] == "reused_id"


def test_new_connection_resets_its_counter_but_old_connection_is_rejected(pat):
    send(pat)
    pat[0].bind("phone", sample_id(3))
    assert not pat[2] and pat[0].active is None
    assert send(pat)["reason"] == "stale_connection"
    assert send(pat, connection=sample_id(3))["phase"] == "accepted"


def test_invalid_number_sequence_or_intensity_never_reaches_count(pat):
    for changes in ({"interaction_no": True}, {"seq": -1}, {"intensity": float("nan")},
                    {"intensity": float("inf")}, {"intensity": True}, {"interaction_id": "invalid"}):
        with pytest.raises(ValueError):
            send(pat, **changes)
    assert not pat[2] and not pat[3]


def test_count_failure_is_terminal_without_retrying_partial_side_effect(pat):
    def fail():
        pat[2].append(1)
        raise OSError("합성 횟수 저장 실패")
    pat[0].count = fail
    send(pat)
    answer = send(pat, phase="end", seq=1)
    assert answer["phase"] == "cancelled" and answer["reason"] == "count_failed"
    assert send(pat, phase="end", seq=1) == answer
    assert pat[2] == [1]
