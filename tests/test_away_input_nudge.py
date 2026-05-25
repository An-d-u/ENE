from src.core.bridge_mixins.away import AwayNudgeBridgeMixin


class _DummyAwayBridge(AwayNudgeBridgeMixin):
    def __init__(self):
        self.away_check_in_progress = False
        self.away_idle_minutes = 10
        self.away_input_grace_minutes = 3
        self.away_additional_retry_limit = 0
        self.away_trigger_count_since_last_user_msg = 0
        self.away_already_triggered_since_last_user_msg = False
        self.last_away_trigger_at = None
        self.worker = None
        self.settings = None
        self.started_worker = None
        self.capture_count = 0

    def parent(self):
        return None

    def _prompt_language(self):
        return "ko"

    def _now_timestamp(self):
        return "2026-05-25 12:00"

    def _with_prompt_time(self, timestamp, prompt):
        return f"[현재 시각: {timestamp}]\n{prompt}"

    def _capture_full_desktop_hidden_overlay(self):
        self.capture_count += 1
        return object(), "data:image/png;base64,latest"

    def _calculate_image_diff_percent(self, _image_a, _image_b):
        raise AssertionError("화면 차이율 비교는 더 이상 호출되면 안 됩니다.")

    def _start_ai_worker(self, message_with_time, images_data):
        self.started_worker = {
            "message_with_time": message_with_time,
            "images": images_data,
        }


def test_away_nudge_uses_no_recent_input_for_away_tone(monkeypatch):
    bridge = _DummyAwayBridge()
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: 3 * 60)

    bridge._start_away_capture_pipeline()

    assert bridge.capture_count == 1
    assert bridge.started_worker is not None
    assert "현재 자리 비움 상태야" in bridge.started_worker["message_with_time"]
    assert "최근 3분 동안 마우스/키보드 입력도 없었어" in bridge.started_worker["message_with_time"]


def test_away_nudge_uses_recent_input_for_active_tone(monkeypatch):
    bridge = _DummyAwayBridge()
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: (3 * 60) - 1)

    bridge._start_away_capture_pipeline()

    assert bridge.capture_count == 1
    assert bridge.started_worker is not None
    assert "최근 10분 동안 너에게 말을 걸지 않았어" in bridge.started_worker["message_with_time"]
    assert "마우스나 키보드 입력은 있었어" in bridge.started_worker["message_with_time"]


def test_away_nudge_uses_input_grace_instead_of_idle_minutes(monkeypatch):
    bridge = _DummyAwayBridge()
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: 4 * 60)

    bridge._start_away_capture_pipeline()

    assert bridge.started_worker is not None
    assert "현재 자리 비움 상태야" in bridge.started_worker["message_with_time"]


def test_refresh_away_settings_clamps_input_grace_to_idle_minutes():
    class _Settings:
        config = {
            "enable_away_nudge": True,
            "away_idle_minutes": 10,
            "away_input_grace_minutes": 30,
            "away_additional_retry_limit": 0,
        }

    bridge = _DummyAwayBridge()
    bridge.settings = _Settings()

    bridge.refresh_away_settings()

    assert bridge.away_idle_minutes == 10
    assert bridge.away_input_grace_minutes == 10
