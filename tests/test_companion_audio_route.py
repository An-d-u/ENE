"""가상 단조 시계로 한 발화의 출력 대상과 완료 횟수를 검증한다."""

import pytest

from src.core.companion.audio_route import AudioRoute


def offered():
    route = AudioRoute()
    assert route.offer(now_ms=0, phone_eligible=True) == "offer_phone"
    return route


def committed():
    route = offered()
    assert route.prepared(now_ms=100) == "send_start"
    return route


def test_start_delivery_uncertainty_never_falls_back_to_pc():
    route = committed()
    assert route.target == "phone"
    assert route.delivery_failed() == "cancel"
    assert route.target == "phone"
    assert route.finish() == "complete_once"
    assert route.finish() == "ignore"


def test_pc_utterance_does_not_move_when_phone_becomes_available():
    route = AudioRoute()
    assert route.offer(now_ms=0, phone_eligible=False) == "play_pc"
    assert route.offer(now_ms=500, phone_eligible=True) == "ignore"
    assert route.target == "pc"


@pytest.mark.parametrize("method", ["rejected", "delivery_failed"])
def test_before_start_failure_falls_back_only_once(method):
    route = offered()
    assert getattr(route, method)() == "play_pc"
    assert getattr(route, method)() == "ignore"
    assert route.prepared(now_ms=100) == "ignore"


@pytest.mark.parametrize("method", ["tick", "prepared"])
def test_prepare_deadline_is_exact_and_irreversible(method):
    route = offered()
    assert route.tick(now_ms=1999) == "ignore"
    assert getattr(route, method)(now_ms=2000) == "play_pc"
    assert route.prepared(now_ms=2001) == "ignore"


def test_duplicate_prepared_or_started_never_starts_twice():
    route = committed()
    assert route.prepared(now_ms=200) == "ignore"
    assert route.started(now_ms=210) == "playing"
    assert route.started(now_ms=220) == "ignore"
    assert route.target == "phone"


def test_lost_started_ack_can_be_followed_by_real_progress():
    route = committed()
    assert route.progress(now_ms=200, played_frames=24) == "ack_progress"
    assert route.state == "PLAYING"
    assert route.started(now_ms=210) == "ignore"


@pytest.mark.parametrize("with_static_reports", [False, True])
def test_five_seconds_without_real_progress_cancels(with_static_reports):
    route = committed()
    if with_static_reports:
        for now in range(200, 5000, 100):
            assert route.progress(now_ms=now, played_frames=0) == "ack_progress"
    assert route.tick(now_ms=5099) == "ignore"
    assert route.tick(now_ms=5100) == "cancel"
    assert route.target == "phone"
    assert route.finish() == "complete_once"


def test_cancel_is_not_a_request_to_fallback():
    route = offered()
    assert route.cancel() == "cancel"
    assert route.prepared(now_ms=100) == "ignore"
    assert route.offer(now_ms=200, phone_eligible=False) == "ignore"
    assert route.finish() == "complete_once"


def test_source_and_phone_completion_are_both_required():
    route = committed()
    assert route.phone_finished(played_frames=9600) == "ignore"
    assert route.source_end(total_frames=9600) == "complete_once"
    assert route.phone_finished(played_frames=9600) == "ignore"
    assert route.finish() == "ignore"


def test_mismatched_source_count_cancels_without_pc_replay():
    route = committed()
    assert route.source_end(total_frames=100) == "ignore"
    assert route.phone_finished(played_frames=99) == "cancel"
    assert route.target == "phone"


def test_old_progress_or_clock_does_not_extend_watchdog():
    route = committed()
    route.progress(now_ms=200, played_frames=100)
    assert route.progress(now_ms=300, played_frames=99) == "ignore"
    assert route.progress(now_ms=199, played_frames=101) == "ignore"
    assert route.tick(now_ms=5200) == "cancel"


def test_late_progress_cannot_revive_an_expired_route():
    route = committed()
    assert route.progress(now_ms=5100, played_frames=100) == "cancel"
    assert route.prepared(now_ms=5200) == "ignore"
    assert route.target == "phone"
