"""가짜 시각과 색상만 이용해 공통 관찰 간격의 실제 적용을 확인한다."""
from unittest.mock import Mock

from src.core.screen_observation import ObservationSchedule
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_screen_observation_v1 import scene


def test_changed_scene_can_only_use_the_next_eligible_current_sample():
    schedule = ObservationSchedule()
    blue, white = scene("navy"), scene("white")
    assert not schedule.candidate(blue, 0)
    assert not schedule.candidate(white, 29)
    assert schedule.candidate(white, 30)
    schedule.mark_requested(30)
    assert not schedule.candidate(blue, 60)
    assert not schedule.candidate(blue, 300)
    assert schedule.candidate(blue, 330)


def test_live_changes_measure_from_last_sample_and_last_call_across_devices():
    schedule = ObservationSchedule()
    assert not schedule.candidate(scene("navy"), 100)
    schedule.mark_requested(105)
    schedule.configure(7, 10)
    assert schedule.next_sample == 107 and schedule.next_request == 115
    assert not schedule.candidate(scene("white"), 107)
    schedule.configure(1, 1000)
    assert schedule.next_sample == 108 and schedule.next_request == 1105
    schedule.reset_scene()
    assert schedule.next_request == 1105
    assert not schedule.candidate(scene("white"), 109)
    schedule.configure(1, 10)
    assert schedule.candidate(scene("navy"), 115)


def test_failed_sample_respects_its_interval():
    schedule = ObservationSchedule()
    assert not schedule.candidate(None, 10)
    assert schedule.next_sample == 40


def test_bridge_only_reports_persisted_values_and_does_not_start_sharing(bridge):
    bridge.settings = Mock()
    bridge.settings.config = {}
    bridge._companion_adapter = Mock()
    notifications = []
    bridge.observation_intervals_changed.connect(lambda *args: notifications.append(args))
    assert bridge.observation_intervals_state() == (30, 300)
    assert bridge.set_observation_intervals(7, 90)
    bridge.settings.commit_observation_intervals.assert_called_once_with(7, 90)
    assert bridge.observation_intervals_state() == (7, 90)
    assert bridge.away_timer.interval() <= 1000
    assert notifications == [(7, 90)]
    bridge.settings.commit_observation_intervals.side_effect = OSError()
    assert not bridge.set_observation_intervals(2, 20)
    assert notifications == [(7, 90)]
    assert bridge.observation_intervals_state() == (7, 90)
    assert not getattr(bridge, "_screen_share", None) and not getattr(bridge, "_mobile_camera", None)
