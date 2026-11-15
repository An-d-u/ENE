"""
WebBridge의 자리 비움 감지와 채팅 안부.
"""
from datetime import datetime

from ..system_idle import get_system_idle_seconds
from ..away_nudge import away_greeting


class AwayNudgeBridgeMixin:
    def refresh_away_settings(self):
        """설정 파일에서 유휴 감지 관련 값을 다시 읽는다."""
        if self.settings and hasattr(self.settings, "config"):
            config = self.settings.config
            self.enable_away_nudge = bool(config.get("enable_away_nudge", True))
            self.away_idle_minutes = int(config.get("away_idle_minutes", 60))
            self.away_input_grace_minutes = int(config.get("away_input_grace_minutes", 5))
            self.away_additional_retry_limit = int(config.get("away_additional_retry_limit", 0))
        else:
            self.enable_away_nudge = True
            self.away_idle_minutes = 60
            self.away_input_grace_minutes = 5
            self.away_additional_retry_limit = 0

        self.away_idle_minutes = max(1, min(self.away_idle_minutes, 1440))
        self.away_input_grace_minutes = max(1, min(self.away_input_grace_minutes, self.away_idle_minutes))
        self.away_additional_retry_limit = max(0, min(self.away_additional_retry_limit, 20))

    def start_away_monitor(self):
        """유휴 감지 타이머를 시작한다."""
        if not self.away_timer.isActive():
            self.away_timer.start()

    def stop_away_monitor(self):
        """유휴 감지 타이머와 진행 중 파이프라인을 정리한다."""
        if self.away_timer.isActive():
            self.away_timer.stop()
        self._cancel_away_pipeline()

    def _mark_user_activity(self):
        """사용자 발화를 기준으로 유휴 감지 상태를 재무장한다."""
        self.last_user_message_at = datetime.now()
        self.user_message_count += 1
        self.away_already_triggered_since_last_user_msg = False
        self.away_trigger_count_since_last_user_msg = 0
        self.last_away_trigger_at = None
        self._cancel_away_pipeline()

    def _cancel_away_pipeline(self):
        """진행 중인 유휴 감지 임시 상태를 정리한다."""
        self.away_check_in_progress = False

    def _check_away_nudge_condition(self):
        """주기적으로 유휴 조건과 실행 가능 상태를 확인한다."""
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            return
        if not self.enable_away_nudge:
            return
        if self.away_check_in_progress:
            return
        if self.user_message_count <= 0 or self.last_user_message_at is None:
            return
        if self.worker and self.worker.isRunning():
            return

        max_total_runs = 1 + self.away_additional_retry_limit
        if self.away_trigger_count_since_last_user_msg >= max_total_runs:
            self.away_already_triggered_since_last_user_msg = True
            return

        # 첫 실행은 마지막 사용자 발화 기준, 이후 재실행은 마지막 유휴 실행 시점 기준
        if self.away_trigger_count_since_last_user_msg == 0 or self.last_away_trigger_at is None:
            idle_base_time = self.last_user_message_at
        else:
            idle_base_time = self.last_away_trigger_at

        idle_minutes = (datetime.now() - idle_base_time).total_seconds() / 60.0
        if idle_minutes < self.away_idle_minutes:
            return

        system_idle = get_system_idle_seconds()
        if system_idle is None or system_idle < self.away_input_grace_minutes * 60:
            return

        text = away_greeting(self._prompt_language())
        self._display_away_greeting(text)
        self.away_trigger_count_since_last_user_msg += 1
        self.last_away_trigger_at = datetime.now()
        self.away_already_triggered_since_last_user_msg = (
            self.away_trigger_count_since_last_user_msg >= max_total_runs
        )
