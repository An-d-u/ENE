"""
WebBridge의 자리 비움 감지와 화면 캡처 로직.
"""
from datetime import datetime

import numpy as np
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from ...ai.persona_names import resolve_prompt_persona_names
from ..away_nudge import build_away_nudge_prompt


class AwayNudgeBridgeMixin:
    def refresh_away_settings(self):
        """설정 파일에서 유휴 감지 관련 값을 다시 읽는다."""
        if self.settings and hasattr(self.settings, "config"):
            config = self.settings.config
            self.enable_away_nudge = bool(config.get("enable_away_nudge", True))
            self.away_idle_minutes = int(config.get("away_idle_minutes", 60))
            self.away_compare_delay_seconds = int(config.get("away_compare_delay_seconds", 30))
            self.away_diff_threshold_percent = float(config.get("away_diff_threshold_percent", 3.0))
            self.away_additional_retry_limit = int(config.get("away_additional_retry_limit", 0))
        else:
            self.enable_away_nudge = True
            self.away_idle_minutes = 60
            self.away_compare_delay_seconds = 30
            self.away_diff_threshold_percent = 3.0
            self.away_additional_retry_limit = 0

        self.away_idle_minutes = max(1, min(self.away_idle_minutes, 1440))
        self.away_compare_delay_seconds = max(1, min(self.away_compare_delay_seconds, 600))
        self.away_diff_threshold_percent = max(0.1, min(self.away_diff_threshold_percent, 100.0))
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
        """진행 중인 2차 캡처 대기/임시 상태를 정리한다."""
        if self.away_second_shot_timer.isActive():
            self.away_second_shot_timer.stop()
        self.away_check_in_progress = False
        self.away_first_capture_data_url = None
        self.away_first_capture_image = None

    def _check_away_nudge_condition(self):
        """주기적으로 유휴 조건과 실행 가능 상태를 확인한다."""
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

        self._start_away_capture_pipeline()

    def _start_away_capture_pipeline(self):
        """1차 캡처 후 2차 캡처 타이머를 시작한다."""
        if self.away_check_in_progress:
            return

        self.away_check_in_progress = True
        first_result = self._capture_full_desktop_hidden_overlay()
        if first_result is None:
            print("[Bridge] Away capture(1차) 실패")
            self._cancel_away_pipeline()
            return

        first_image, first_data_url = first_result
        self.away_first_capture_image = first_image
        self.away_first_capture_data_url = first_data_url
        self.away_second_shot_timer.start(self.away_compare_delay_seconds * 1000)

    def _complete_away_capture_pipeline(self):
        """2차 캡처 후 차이율을 계산하고 기능 1/2로 분기한다."""
        if self.worker and self.worker.isRunning():
            self.away_second_shot_timer.start(10_000)
            return

        first_image = self.away_first_capture_image
        if first_image is None:
            self._cancel_away_pipeline()
            return

        second_result = self._capture_full_desktop_hidden_overlay()
        if second_result is None:
            print("[Bridge] Away capture(2차) 실패")
            self._cancel_away_pipeline()
            return

        second_image, second_data_url = second_result

        use_feature_1 = False
        diff_percent = None
        try:
            diff_percent = self._calculate_image_diff_percent(first_image, second_image)
            use_feature_1 = diff_percent <= self.away_diff_threshold_percent
        except Exception as e:
            print(f"[Bridge] 화면 비교 실패, 기능2로 폴백: {e}")
            use_feature_1 = False

        prompt = build_away_nudge_prompt(
            language=self._prompt_language(),
            idle_minutes=self.away_idle_minutes,
            use_stable_screen=use_feature_1,
            diff_percent=diff_percent,
            user_name=resolve_prompt_persona_names(
                settings_source=getattr(self, "settings", None),
                language=self._prompt_language(),
            ).user,
        )

        timestamp = self._now_timestamp()
        message_with_time = self._with_prompt_time(timestamp, prompt)
        images_data = [{
            "dataUrl": second_data_url,
            "name": "away_latest_screen.png",
            "type": "image/png",
        }]

        self._last_request_payload = {
            "type": "images",
            "message": prompt,
            "message_with_time": message_with_time,
            "images": images_data,
        }
        self._is_rerolling = False
        self.away_trigger_count_since_last_user_msg += 1
        self.last_away_trigger_at = datetime.now()
        max_total_runs = 1 + self.away_additional_retry_limit
        self.away_already_triggered_since_last_user_msg = (
            self.away_trigger_count_since_last_user_msg >= max_total_runs
        )
        self._start_ai_worker(message_with_time, images_data)

        self.away_check_in_progress = False
        self.away_first_capture_data_url = None
        self.away_first_capture_image = None

    def _capture_full_desktop_hidden_overlay(self):
        """ENE 창을 잠시 숨긴 뒤 전체 모니터를 합성 캡처한다."""
        overlay = self.parent() if self.parent() else None
        was_visible = False
        if overlay and hasattr(overlay, "isVisible"):
            try:
                was_visible = bool(overlay.isVisible())
                if was_visible:
                    overlay.hide()
                    QApplication.processEvents()
            except Exception:
                was_visible = False

        try:
            image = self._capture_full_desktop_image()
            if image is None:
                return None
            data_url = self._qimage_to_data_url(image)
            return image, data_url
        finally:
            if overlay and was_visible:
                try:
                    overlay.show()
                    QApplication.processEvents()
                except Exception:
                    pass

    def _capture_full_desktop_image(self):
        """모든 모니터를 하나의 이미지로 합성한다."""
        screens = QGuiApplication.screens()
        if not screens:
            return None

        virtual_rect = screens[0].geometry()
        for screen in screens[1:]:
            virtual_rect = virtual_rect.united(screen.geometry())

        canvas = QImage(virtual_rect.size(), QImage.Format.Format_RGBA8888)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        try:
            for screen in screens:
                geo = screen.geometry()
                pixmap = screen.grabWindow(0)
                x = geo.x() - virtual_rect.x()
                y = geo.y() - virtual_rect.y()
                painter.drawPixmap(x, y, pixmap)
        finally:
            painter.end()

        return canvas

    def _qimage_to_data_url(self, image: QImage) -> str:
        """QImage를 data:image/png;base64 형태로 변환한다."""
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        encoded = bytes(byte_array.toBase64()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _calculate_image_diff_percent(self, image_a: QImage, image_b: QImage) -> float:
        """RGBA 절대차 평균 기반 변화율(%) 계산."""
        if image_a.size() != image_b.size():
            raise ValueError("캡처 해상도가 서로 다릅니다.")

        img_a = image_a.convertToFormat(QImage.Format.Format_RGBA8888)
        img_b = image_b.convertToFormat(QImage.Format.Format_RGBA8888)

        width = img_a.width()
        height = img_a.height()
        total_bytes = width * height * 4

        ptr_a = img_a.bits()
        ptr_b = img_b.bits()
        ptr_a.setsize(total_bytes)
        ptr_b.setsize(total_bytes)

        arr_a = np.frombuffer(ptr_a, dtype=np.uint8).reshape((height, width, 4))
        arr_b = np.frombuffer(ptr_b, dtype=np.uint8).reshape((height, width, 4))
        diff = np.abs(arr_a.astype(np.int16) - arr_b.astype(np.int16))
        return float((diff.mean() / 255.0) * 100.0)
