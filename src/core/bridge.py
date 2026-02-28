"""
Python-JavaScript 브릿지 (QWebChannel)
"""
from PyQt6.QtCore import (
    QObject,
    pyqtSignal,
    pyqtSlot,
    QThread,
    QBuffer,
    QByteArray,
    QIODevice,
    QTimer,
    Qt,
)
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtWidgets import QApplication
from datetime import datetime
import json
import numpy as np

from ..ai.diary_service import DiaryService


class AIWorker(QThread):
    """AI 응답을 비동기로 처리하는 워커 스레드"""
    
    response_ready = pyqtSignal(str, str, str, list)  # (텍스트, 감정, 일본어, 이벤트)
    error_occurred = pyqtSignal(str)  # 오류 메시지
    
    def __init__(
        self,
        llm_client,
        message,
        use_memory=True,
        images=None,
        diary_request: str = "",
        diary_service: DiaryService | None = None,
    ):
        super().__init__()
        self.llm_client = llm_client
        self.message = message
        self.use_memory = use_memory
        self.images = images or []  # 이미지 데이터 리스트
        self.diary_request = (diary_request or "").strip()
        self.diary_service = diary_service
    
    def run(self):
        loop = None
        """스레드 실행"""
        try:
            print(f"[AI Worker] Processing message: {self.message[:50]}...")
            
            # 비동기 메서드이므로 asyncio로 실행
            import asyncio
            
            # 새 이벤트 루프 생성 (워커 스레드용)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            events = []

            if self.diary_request and self.diary_service:
                print("[AI Worker] /diary 모드")
                response_text, emotion, japanese_text, events = loop.run_until_complete(
                    self._run_diary_flow()
                )
            # 이미지가 있으면 멀티모달로 처리
            elif self.images:
                print(f"[AI Worker] 이미지 {len(self.images)}개 포함 - 멀티모달 모드")
                response_text, emotion, japanese_text, events = loop.run_until_complete(
                    self.llm_client.send_message_with_images(self.message, self.images)
                )
            elif self.use_memory and hasattr(self.llm_client, 'send_message_with_memory'):
                print(f"[AI Worker] 메모리 활용 모드")
                response_text, emotion, japanese_text, events = loop.run_until_complete(
                    self.llm_client.send_message_with_memory(self.message)
                )
            else:
                print(f"[AI Worker] 일반 모드 (메모리 없음)")
                # send_message는 4개 값 반환 (text, emotion, japanese, events)
                response_text, emotion, japanese_text, events = self.llm_client.send_message(self.message)
            
            
            print(f"[AI Worker] Response: {response_text[:50]}... [{emotion}]")
            if japanese_text:
                print(f"[AI Worker] Japanese: {japanese_text[:30]}...")
            if events:
                print(f"[AI Worker] {len(events)}개 일정 추출")
            
            # events도 함께 emit (signal에는 리스트로 전달 가능)
            self.response_ready.emit(response_text, emotion, japanese_text or "", events)
        except Exception as e:
            print(f"[AI Worker] Error: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))
        finally:
            if loop is not None:
                loop.close()

    async def _run_diary_flow(self):
        """일기/문서 생성 전용 플로우."""
        if not hasattr(self.llm_client, "generate_markdown_document"):
            raise RuntimeError("현재 LLM 클라이언트는 /diary를 지원하지 않습니다.")

        markdown_text = await self.llm_client.generate_markdown_document(self.message)
        result = self.diary_service.save_markdown(self.diary_request, markdown_text)

        completion_context = (
            "아래 정보를 바탕으로 마스터에게 파일 작성 완료를 알려주세요.\n"
            "- 문장 안에 반드시 다음 문구를 포함하세요: 성공적으로 파일 작성에 완료되었습니다.\n"
            f"- 작성된 md 파일: {result.relative_path}\n"
            "[작성된 md 파일 본문]\n"
            f"{result.content}"
        )

        if hasattr(self.llm_client, "generate_diary_completion_reply"):
            text, emotion, japanese_text, events = await self.llm_client.generate_diary_completion_reply(completion_context)
            required = "성공적으로 파일 작성에 완료되었습니다."
            if required not in text:
                text = f"{required}\n{text}".strip()
            return text, emotion, japanese_text, events

        # 하위 호환 폴백 (기존 클라이언트 경로)
        return self.llm_client.send_message(completion_context)


class TTSWorker(QThread):
    """TTS 생성 및 립싱크 분석을 비동기로 처리하는 워커 스레드"""
    
    tts_ready = pyqtSignal(bytes, list)  # (audio_data, lip_sync_data)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, tts_client, text):
        super().__init__()
        self.tts_client = tts_client
        self.text = text
    
    def run(self):
        loop = None
        """스레드 실행"""
        try:
            import asyncio
            import os
            import tempfile
            from pathlib import Path
            from src.ai.audio_analyzer import AudioAnalyzer
            
            print(f"[TTS Worker] Generating speech for: {self.text[:30]}...")
            
            # 새 이벤트 루프 생성
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # TTS API로 오디오 생성
            audio_data = loop.run_until_complete(
                self.tts_client.generate_speech(self.text)
            )
            
            
            print(f"[TTS Worker] Audio generated: {len(audio_data)} bytes")
            
            # 임시 WAV 파일로 저장 (분석용)
            temp_fd, temp_path = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(temp_fd, 'wb') as f:
                f.write(audio_data)
            
            # 오디오 분석하여 립싱크 데이터 생성
            try:
                analyzer = AudioAnalyzer(frame_duration_ms=50)
                lip_sync_data = analyzer.analyze(temp_path)
                print(f"[TTS Worker] Lip sync data: {len(lip_sync_data)} frames")
            except Exception as e:
                print(f"[TTS Worker] Lip sync analysis failed: {e}")
                lip_sync_data = []
            
            # 임시 파일 정리
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            
            # 결과 전송
            self.tts_ready.emit(audio_data, lip_sync_data)
            
        except Exception as e:
            print(f"[TTS Worker] Error: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))
        finally:
            if loop is not None:
                loop.close()


class WebBridge(QObject):
    """Python과 JavaScript 간 통신 브릿지"""
    
    # Python -> JavaScript 시그널
    message_received = pyqtSignal(str, str)  # (텍스트, 감정)
    expression_changed = pyqtSignal(str)     # 표정 변경
    lip_sync_update = pyqtSignal(float)      # 립싱크 업데이트 (mouth_value)
    reroll_state_changed = pyqtSignal(bool)  # 리롤 응답 교체 모드 on/off
    summary_notice = pyqtSignal(str, str)    # (메시지, 레벨)
    mood_changed = pyqtSignal(str, float, float, float, float)  # (라벨, valence, energy, bond, stress)
    
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.llm_client = None
        self.memory_manager = None
        self.worker = None
        self.settings = settings
        self.mood_manager = None
        self.diary_service = DiaryService("diary")
        
        # TTS 및 오디오 재생
        self.tts_client = None
        self.audio_player = None
        self.enable_tts = False  # TTS 활성화 여부
        self.tts_worker = None  # TTS 워커 스레드
        
        # 립싱크 데이터 및 타이머
        self.lip_sync_data = None
        self.lip_sync_timer = None
        self.lip_sync_start_time = None
        
        # 보류 중인 응답 (TTS 대기)
        self.pending_response = None  # (text, emotion)
        
        # 대화 추적
        self.conversation_buffer = []  # [(role, message, timestamp), ...]
        self._last_request_payload = None
        self._last_assistant_response = None
        self._is_rerolling = False

        # 자리 비움/유휴 감지 상태
        self.last_user_message_at = None
        self.user_message_count = 0
        self.away_check_in_progress = False
        self.away_already_triggered_since_last_user_msg = False
        self.away_trigger_count_since_last_user_msg = 0
        self.last_away_trigger_at = None
        self.away_first_capture_data_url = None
        self.away_first_capture_image = None
        self.away_idle_minutes = 60
        self.away_compare_delay_seconds = 30
        self.away_diff_threshold_percent = 3.0
        self.away_additional_retry_limit = 0
        self.enable_away_nudge = True

        # 유휴 감지 타이머
        self.away_timer = QTimer(self)
        self.away_timer.setInterval(10_000)
        self.away_timer.timeout.connect(self._check_away_nudge_condition)

        self.away_second_shot_timer = QTimer(self)
        self.away_second_shot_timer.setSingleShot(True)
        self.away_second_shot_timer.timeout.connect(self._complete_away_capture_pipeline)
        
        # 설정에서 임계값 로드 (기본값: 10)
        if settings and hasattr(settings, 'config'):
            self.summarize_threshold = settings.config.get('summarize_threshold', 10)
            self.enable_tts = settings.config.get('enable_tts', False)
        else:
            self.summarize_threshold = 10

        self.refresh_away_settings()
        
        print(f"[Bridge] 자동 요약 임계값: {self.summarize_threshold}개")
        print(f"[Bridge] TTS 활성화: {self.enable_tts}")
    
    def set_llm_client(self, client):
        """LLM 클라이언트 설정"""
        self.llm_client = client
        if self.llm_client and self.mood_manager:
            self.llm_client.mood_manager = self.mood_manager
        print(f"[Bridge] LLM client set: {client is not None}")

    def set_mood_manager(self, mood_manager):
        """기분 매니저 설정"""
        self.mood_manager = mood_manager
        if self.llm_client and self.mood_manager:
            self.llm_client.mood_manager = self.mood_manager
        if self.mood_manager:
            snapshot = self.mood_manager.get_snapshot()
            self._emit_mood_changed(snapshot)

    def _emit_mood_changed(self, snapshot: dict):
        """기분 상태 변경 시 UI로 전달"""
        try:
            self.mood_changed.emit(
                str(snapshot.get("current_mood", "calm")),
                float(snapshot.get("valence", 0.0)),
                float(snapshot.get("energy", 0.0)),
                float(snapshot.get("bond", 0.0)),
                float(snapshot.get("stress", 0.0)),
            )
        except Exception as e:
            print(f"[Bridge] mood_changed emit 실패: {e}")
    
    def set_memory_manager(self, memory_manager, _llm_client, user_profile=None):
        """메모리 매니저 및 사용자 프로필 설정"""
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        print(f"[Bridge] Memory manager set: {memory_manager is not None}")
        print(f"[Bridge] User profile set: {user_profile is not None}")
    
    def set_tts(self, tts_client, audio_player):
        """TTS 클라이언트 및 오디오 플레이어 설정"""
        self.tts_client = tts_client
        self.audio_player = audio_player
        print(f"[Bridge] TTS client set: {tts_client is not None}")
        print(f"[Bridge] Audio player set: {audio_player is not None}")

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

        idle_text = f"{self.away_idle_minutes}분"
        if use_feature_1:
            prompt = (
                f"상태 알림: 마스터가 현재 자리 비움 상태야. "
                f"참고로 최근 {idle_text} 동안 너에게 새 메시지를 보내지 않았고, "
                f"30초 간격 화면 비교에서 변화가 거의 없었어(차이율 {diff_percent:.2f}%). "
                f"방금 첨부한 최신 전체 화면 1장을 보고, 혼잣말처럼 자연스럽게 한 마디 하거나 "
                f"자리 비운 마스터에게 남길 말을 짧게 해줘."
            )
        else:
            if diff_percent is None:
                diff_note = "비교 실패로 보수적으로"
            else:
                diff_note = f"차이율 {diff_percent:.2f}%로"
            prompt = (
                f"상태 알림: 마스터가 최근 {idle_text} 동안 너에게 말을 걸지 않았어. "
                f"{diff_note} 화면 변화가 있는 상태로 판단했어. "
                f"방금 첨부한 최신 전체 화면 1장을 보고, 마스터가 너에게 말을 조금 걸어줬으면 좋겠다는 "
                f"티가 나는 짧은 한마디를 해줘."
            )

        timestamp = self._now_timestamp()
        message_with_time = f"[현재 시각: {timestamp}]\n{prompt}"
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

    def _now_timestamp(self) -> str:
        """Return current timestamp in a consistent format."""
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _append_conversation(self, role: str, message: str, timestamp: str | None = None):
        """Append a conversation tuple to the in-memory buffer."""
        self.conversation_buffer.append((role, message, timestamp or self._now_timestamp()))

    def _start_ai_worker(self, message_with_time: str, images_data: list | None = None):
        """Start AI worker with current payload."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()

        self.worker = AIWorker(
            self.llm_client,
            message_with_time,
            images=images_data or []
        )
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _start_diary_worker(self, diary_request: str, message_with_time: str):
        """Start /diary worker with isolated context."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()

        self.worker = AIWorker(
            self.llm_client,
            message_with_time,
            diary_request=diary_request,
            diary_service=self.diary_service,
        )
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _handle_diary_command(self, message: str) -> bool:
        """'/diary' 명령을 감지해 전용 처리한다."""
        is_diary, diary_body = self.diary_service.parse_diary_command(message)
        if not is_diary:
            return False

        self._mark_user_activity()
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        if not diary_body:
            self.message_received.emit("`/diary` 뒤에 작성할 내용을 함께 입력해 주세요.", "confused")
            return True

        timestamp = self._now_timestamp()
        message_with_time = f"[현재 시각: {timestamp}]\n{diary_body}"

        # /diary는 일반 리롤/수정 payload에서 제외해 원문/본문 누적을 막는다.
        self._last_request_payload = None
        self._is_rerolling = False

        self._start_diary_worker(diary_body, message_with_time)
        print("[Bridge] /diary worker thread started")
        return True
    @pyqtSlot(str)
    def send_to_ai(self, message: str):
        """JavaScript에서 호출: 사용자 텍스트 메시지를 AI로 전송."""
        print(f"[Bridge] Received message from JS: {message}")

        if hasattr(self, 'calendar_manager') and self.calendar_manager:
            self.calendar_manager.increment_conversation_count()
            print("[Bridge] 대화 횟수 증가")

        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad")
            return

        if self._handle_diary_command(message):
            return

        timestamp = self._now_timestamp()
        message_with_time = f"[현재 시각: {timestamp}]\n{message}"
        print(f"[Bridge] Message with timestamp: {message_with_time}")

        self._mark_user_activity()
        self._append_conversation("user", message, timestamp)
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        self._last_request_payload = {
            "type": "text",
            "message": message,
            "message_with_time": message_with_time,
            "images": [],
        }
        self._is_rerolling = False

        self._start_ai_worker(message_with_time)
        print("[Bridge] Worker thread started")

    @pyqtSlot(str, str)
    def send_to_ai_with_images(self, message: str, images_json: str):
        """JavaScript에서 호출: 이미지 포함 메시지를 AI로 전송."""
        import json

        print("[Bridge] Received message with images from JS")

        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad")
            return

        try:
            images_data = json.loads(images_json)
            print(f"[Bridge] Parsed {len(images_data)} images")
        except Exception as e:
            print(f"[Bridge] Failed to parse images: {e}")
            images_data = []

        timestamp = self._now_timestamp()
        message_with_time = f"[현재 시각: {timestamp}]\n{message}"

        self._mark_user_activity()
        img_note = f" [이미지 {len(images_data)}장]" if images_data else ""
        self._append_conversation("user", message + img_note, timestamp)
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=len(images_data))
            self._emit_mood_changed(snapshot)

        self._last_request_payload = {
            "type": "images",
            "message": message,
            "message_with_time": message_with_time,
            "images": images_data,
        }
        self._is_rerolling = False

        self._start_ai_worker(message_with_time, images_data)
        print(f"[Bridge] Worker thread started with {len(images_data)} images")

    @pyqtSlot()
    def reroll_last_response(self):
        """마지막 사용자 요청을 다시 실행해 최근 assistant 응답만 교체."""
        if not self.llm_client:
            print("[Bridge] Reroll ignored: LLM client not initialized")
            return

        if not self._last_request_payload:
            print("[Bridge] Reroll ignored: no previous request payload")
            return

        if self.worker and self.worker.isRunning():
            print("[Bridge] Reroll ignored: worker is still running")
            return

        if not self._rollback_last_turn_pair_for_retry():
            print("[Bridge] Reroll aborted: failed to rollback/rebuild LLM context")
            return

        # 교체 의미를 지키기 위해 최근 assistant 응답 하나를 버퍼에서 제거
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "assistant":
            self.conversation_buffer.pop()

        payload = self._last_request_payload
        self._is_rerolling = True
        self.reroll_state_changed.emit(True)
        self._start_ai_worker(payload["message_with_time"], payload.get("images") or [])
        print("[Bridge] Reroll started")

    def _rollback_last_turn_pair_for_retry(self) -> bool:
        """리롤/수정 재요청 전에 직전 user+assistant 턴을 되돌린다."""
        # 리롤 직전 기준 컨텍스트(..., user C, assistant D)에서
        # D와 C를 제외한 상태(..., B)를 폴백 재구성용으로 준비한다.
        fallback_context = list(self.conversation_buffer)
        if fallback_context and fallback_context[-1][0] == "assistant":
            fallback_context.pop()
        if fallback_context and fallback_context[-1][0] == "user":
            fallback_context.pop()

        # LLM 내부 chat 히스토리에서도 직전 user+assistant 턴을 롤백해야
        # 같은 user 입력이 누적되는 리롤 왜곡을 막을 수 있다.
        rolled_back = False
        if hasattr(self.llm_client, "rollback_last_assistant_turn"):
            rolled_back = bool(self.llm_client.rollback_last_assistant_turn())

        # 일부 SDK 환경에서는 history가 비어 rollback이 실패한다.
        # 이 경우 Bridge 버퍼 기반으로 컨텍스트를 재구성해 폴백한다.
        if not rolled_back and hasattr(self.llm_client, "rebuild_context_from_conversation"):
            rolled_back = bool(self.llm_client.rebuild_context_from_conversation(fallback_context))
            if rolled_back:
                print("[Bridge] Reroll fallback: rebuilt LLM context from conversation buffer")

        if not rolled_back:
            return False
        return True

    @pyqtSlot(str)
    def edit_last_user_message(self, edited_message: str):
        """최근 user 메시지를 수정하고 같은 턴을 다시 생성한다."""
        edited_message = (edited_message or "").strip()
        if not edited_message:
            print("[Bridge] Edit ignored: empty message")
            return

        if not self.llm_client:
            print("[Bridge] Edit ignored: LLM client not initialized")
            return

        if not self._last_request_payload:
            print("[Bridge] Edit ignored: no previous request payload")
            return

        if self.worker and self.worker.isRunning():
            print("[Bridge] Edit ignored: worker is still running")
            return

        # 최근 user/assistant 턴을 LLM 컨텍스트에서 롤백
        if not self._rollback_last_turn_pair_for_retry():
            print("[Bridge] Edit aborted: failed to rollback/rebuild LLM context")
            return

        # 대화 버퍼의 최근 assistant/user 턴 제거
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "assistant":
            self.conversation_buffer.pop()
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "user":
            self.conversation_buffer.pop()

        timestamp = self._now_timestamp()
        payload_type = self._last_request_payload.get("type", "text")
        images = self._last_request_payload.get("images") or []
        if payload_type == "images":
            img_note = f" [이미지 {len(images)}장]" if images else ""
            self._append_conversation("user", edited_message + img_note, timestamp)
        else:
            self._append_conversation("user", edited_message, timestamp)

        message_with_time = f"[현재 시각: {timestamp}]\n{edited_message}"
        self._last_request_payload = {
            "type": payload_type,
            "message": edited_message,
            "message_with_time": message_with_time,
            "images": images,
        }

        self._is_rerolling = True
        self.reroll_state_changed.emit(True)
        self._start_ai_worker(message_with_time, images)
        print("[Bridge] Edit last user message started")

    @pyqtSlot()
    def summarize_now(self):
        """UI에서 호출: 현재 대화를 즉시 요약해 메모리에 저장."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Manual summarize ignored: worker is still running")
            self.summary_notice.emit("응답 생성 중에는 요약할 수 없어요.", "error")
            return

        if not self.llm_client or not self.memory_manager:
            print("[Bridge] Manual summarize ignored: llm/memory not initialized")
            self.summary_notice.emit("요약 기능이 아직 준비되지 않았어요.", "error")
            return

        if not self.conversation_buffer:
            print("[Bridge] Manual summarize ignored: no conversation to summarize")
            self.summary_notice.emit("요약할 대화가 없어요.", "info")
            return

        import asyncio
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._auto_summarize())
            self.summary_notice.emit("대화 요약을 저장했어요.", "success")
        except Exception as e:
            print(f"[Bridge] Manual summarize failed: {e}")
            import traceback
            traceback.print_exc()
            self.summary_notice.emit("요약 중 오류가 발생했어요.", "error")
        finally:
            if loop is not None:
                loop.close()

    
    def _on_response_ready(self, text: str, emotion: str, japanese_text: str, events: list = None):
        """AI 응답 준비 완료"""
        print(f"[Bridge] Response ready: {text[:50]}... [{emotion}]")
        self._last_assistant_response = {"text": text, "emotion": emotion}
        if self.mood_manager:
            snapshot = self.mood_manager.on_assistant_emotion(emotion)
            self._emit_mood_changed(snapshot)
        
        # 대화 버퍼에 응답 추가 (+ 타임스탬프)
        self._append_conversation("assistant", text)
        
        # 일정 저장 (CalendarManager가 있으면)
        if events and hasattr(self, 'calendar_manager') and self.calendar_manager:
            for event_data in events:
                try:
                    event = self.calendar_manager.add_event(
                        date=event_data['date'],
                        title=event_data['title'],
                        description=event_data.get('description', ''),
                        source="ai_extracted"
                    )
                    print(f"[Bridge] 일정 추가: {event.date} - {event.title}")
                except Exception as e:
                    print(f"[Bridge] 일정 추가 실패: {e}")
        
        # TTS 재생 (일본어가 있고 TTS가 활성화되어 있으면)
        if japanese_text and self.enable_tts and self.tts_client and self.audio_player:
            print(f"[Bridge] TTS 활성화 - 텍스트 보류 중, TTS 생성 시작")
            # 텍스트를 보류하고 TTS 완료 대기
            self.pending_response = (text, emotion)
            self._play_tts(japanese_text)
        else:
            # TTS 비활성화 또는 일본어 없음 - 즉시 텍스트 전송
            print(f"[Bridge] TTS 비활성화 - 텍스트 즉시 전송")
            self.message_received.emit(text, emotion)
            if self._is_rerolling:
                self._is_rerolling = False
                self.reroll_state_changed.emit(False)
            if japanese_text:
                print(f"[Bridge] TTS 비활성화 또는 클라이언트 없음 (일본어: {japanese_text[:20]}...)")
        
        # 자동 요약 확인
        self._check_auto_summarize()
    
    def _play_tts(self, text: str):
        """립싱크를 포함한 TTS 재생 (비동기 스레드)"""
        # 기존 TTS 워커 종료
        if self.tts_worker and self.tts_worker.isRunning():
            self.tts_worker.quit()
            self.tts_worker.wait()
        
        # 새 TTS 워커 생성
        self.tts_worker = TTSWorker(self.tts_client, text)
        self.tts_worker.tts_ready.connect(self._on_tts_ready)
        self.tts_worker.error_occurred.connect(self._on_tts_error)
        self.tts_worker.start()
        
        print(f"[Bridge] TTS 워커 시작 (백그라운드)")
    
    def _on_tts_ready(self, audio_data: bytes, lip_sync_data: list):
        """비동기 TTS 완료 후 오디오 재생"""
        print(f"[Bridge] TTS 준비 완료: {len(audio_data)} bytes, {len(lip_sync_data)} 프레임")
        
        # 립싱크 데이터 저장
        self.lip_sync_data = lip_sync_data if lip_sync_data else None
        
        # 보류된 텍스트가 있으면 이제 전송 (텍스트 + 음성 동시 제공)
        if self.pending_response:
            text, emotion = self.pending_response
            print(f"[Bridge] 보류된 응답 전송: {text[:50]}... [{emotion}]")
            self.message_received.emit(text, emotion)
            if self._is_rerolling:
                self._is_rerolling = False
                self.reroll_state_changed.emit(False)
            self.pending_response = None
        
        # 오디오 재생
        self.audio_player.play(audio_data)
        
        # 립싱크 시작
        if self.lip_sync_data:
            self._start_lip_sync()
    
    def _on_tts_error(self, error_msg: str):
        """TTS 오류 처리"""
        print(f"[Bridge] TTS 오류: {error_msg}")
        # TTS 실패 시 보류 중이던 텍스트를 즉시 복구 전송한다.
        if self.pending_response:
            text, emotion = self.pending_response
            print(f"[Bridge] TTS 실패로 보류 응답 복구 전송: {text[:50]}... [{emotion}]")
            self.message_received.emit(text, emotion)
            self.pending_response = None
        if self._is_rerolling:
            self._is_rerolling = False
            self.reroll_state_changed.emit(False)
    
    def _start_lip_sync(self):
        """립싱크 타이머 시작"""
        from PyQt6.QtCore import QTimer, QTime
        
        if not self.lip_sync_data:
            return
        
        # 기존 타이머 정리
        if self.lip_sync_timer:
            self.lip_sync_timer.stop()
            self.lip_sync_timer = None
        
        # 시작 시간 기록
        self.lip_sync_start_time = QTime.currentTime()
        self.lip_sync_index = 0
        
        # 타이머 생성 (10ms 간격으로 체크)
        self.lip_sync_timer = QTimer(self)
        self.lip_sync_timer.timeout.connect(self._update_lip_sync)
        self.lip_sync_timer.start(10)
        
        print(f"[Bridge] 립싱크 타이머 시작")
    
    def _update_lip_sync(self):
        """립싱크 업데이트 (타이머 콜백)"""
        if not self.lip_sync_data or not self.lip_sync_start_time:
            return
        
        from PyQt6.QtCore import QTime
        
        # 경과 시간 계산 (초)
        elapsed_ms = self.lip_sync_start_time.msecsTo(QTime.currentTime())
        elapsed_sec = elapsed_ms / 1000.0
        
        # 현재 시간에 해당하는 립싱크 값 찾기
        mouth_value = 0.0
        found = False
        
        for i in range(self.lip_sync_index, len(self.lip_sync_data)):
            timestamp, value = self.lip_sync_data[i]
            
            if timestamp <= elapsed_sec:
                mouth_value = value
                self.lip_sync_index = i
                found = True
            else:
                break
        
        # 값 전송
        if found:
            self.lip_sync_update.emit(mouth_value)
        
        # 모든 데이터 처리 완료 시 타이머 종료
        if self.lip_sync_index >= len(self.lip_sync_data) - 1:
            self.lip_sync_timer.stop()
            self.lip_sync_update.emit(0.0)  # 입 닫기
            print(f"[Bridge] 립싱크 완료")
    
    def _check_auto_summarize(self):
        """자동 요약 확인"""
        if not self.memory_manager:
            return
        
        if len(self.conversation_buffer) >= self.summarize_threshold:
            print(f"[Bridge] 대화 {len(self.conversation_buffer)}개 - 자동 요약 트리거")
            
            # QThread에서 실행되므로 새 이벤트 루프 생성
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._auto_summarize())
                loop.close()
            except Exception as e:
                print(f"[Bridge] 자동 요약 실패: {e}")
                import traceback
                traceback.print_exc()
    
    async def _auto_summarize(self):
        """대화 자동 요약 및 사용자 정보 추출"""
        if not self.conversation_buffer or not self.memory_manager or not self.llm_client:
            return
        
        try:
            print(f"[Bridge] 대화 요약 시작 ({len(self.conversation_buffer)}개 메시지)")
            
            # 대화 내용
            messages = self.conversation_buffer.copy()
            
            # 원본 메시지 추출 (타임스탬프 제외)
            original_messages = []
            for item in messages:
                if len(item) == 3:
                    original_messages.append(item[1])  # (role, msg, time)
                else:
                    original_messages.append(item[1])  # (role, msg)
            
            # LLM으로 요약 + 사용자 정보 생성
            summary, user_facts = await self.llm_client.summarize_conversation(messages)
            
            # 메모리에 요약 저장
            await self.memory_manager.add_summary(
                summary=summary,
                original_messages=original_messages,
                is_important=False
            )
            
            # 사용자 정보 저장
            if user_facts and hasattr(self, 'user_profile') and self.user_profile:
                print(f"[Bridge] 마스터 정보 {len(user_facts)}개 저장")
                for fact in user_facts:
                    self.user_profile.add_fact(
                        content=fact,
                        category="fact",
                        source=f"대화 요약 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
                    )
            
            # 버퍼 클리어
            self.conversation_buffer = []
            
            print(f"[Bridge] 대화 요약 완료: {summary[:50]}...")
            if user_facts:
                print(f"[Bridge] 마스터 정보: {user_facts}")
            
        except Exception as e:
            print(f"[Bridge] 자동 요약 실패: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_error(self, error_msg: str):
        """오류 발생"""
        print(f"[Bridge] Error occurred: {error_msg}")
        if self._is_rerolling:
            self._is_rerolling = False
            self.reroll_state_changed.emit(False)
        self.message_received.emit("음... 무슨 일이 있었나봐요.", "confused")
    
    @pyqtSlot()
    def clear_conversation(self):
        """대화 내역 초기화"""
        # 남은 대화가 있으면 요약
        if self.memory_manager and len(self.conversation_buffer) >= 2:  # 최소 2개 이상
            print(f"[Bridge] 대화 클리어 전 남은 {len(self.conversation_buffer)}개 메시지 요약")
            
            # 비동기로 요약 실행
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._auto_summarize())
                loop.close()
            except Exception as e:
                print(f"[Bridge] 클리어 시 요약 실패: {e}")
        
        # 대화 버퍼 클리어
        self.conversation_buffer = []
        self._last_request_payload = None
        self._last_assistant_response = None
        self._is_rerolling = False
        self.away_already_triggered_since_last_user_msg = False
        self.away_trigger_count_since_last_user_msg = 0
        self.last_away_trigger_at = None
        self._cancel_away_pipeline()
        
        # LLM 컨텍스트 초기화
        if self.llm_client:
            self.llm_client.clear_context()
            print("[Bridge] Conversation cleared")
    
    @pyqtSlot(str)
    def log_from_js(self, message: str):
        """JavaScript에서 로그 받기"""
        print(f"[JS] {message}")

    @pyqtSlot()
    def increment_head_pat_count_from_js(self):
        """JavaScript에서 호출: 머리 쓰다듬기 횟수 증가."""
        if hasattr(self, "calendar_manager") and self.calendar_manager:
            self.calendar_manager.increment_head_pat_count()
            print("[Bridge] 쓰다듬기 횟수 증가")
        if self.mood_manager:
            snapshot = self.mood_manager.on_head_pat()
            self._emit_mood_changed(snapshot)

    @pyqtSlot(result=str)
    def get_mood_snapshot_json(self) -> str:
        """JavaScript에서 호출: 현재 기분 상태를 JSON 문자열로 반환."""
        if not self.mood_manager:
            return ""
        try:
            snapshot = self.mood_manager.get_snapshot()
            return json.dumps(snapshot, ensure_ascii=False)
        except Exception as e:
            print(f"[Bridge] 기분 스냅샷 반환 실패: {e}")
            return ""

