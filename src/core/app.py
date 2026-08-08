"""
ENE 메인 애플리케이션
오버레이 윈도우와 트레이 아이콘을 관리
"""
import asyncio
import json
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QObject, QTimer

from ..ai.embedding_rebuild import (
    count_saved_embeddings,
    has_embedding_regenerator,
    regenerate_saved_embeddings,
)
from ..ai.life_record_manager import LifeRecordManager
from .app_paths import get_user_data_dir
from .i18n import configure_i18n, tr
from .life_session_tracker import (
    AppSessionTracker,
    SESSION_LEASE_UNAVAILABLE,
    SESSION_TRACKER_DEGRADED,
)
from .local_time import TIMEZONE_UNAVAILABLE, resolve_local_time_context
from .settings import Settings
from .system_theme import get_theme_preset, get_windows_theme_mode
from .overlay_window import OverlayWindow
from .global_ptt import GlobalPTTController
from .tray_icon import TrayIcon
from ..ui.obsidian_panel_window import ObsidianPanelWindow
from ..ui.settings_dialog import SettingsDialog
from ..ai.mood_manager import MoodManager
from ..ai.ene_goal_manager import EneGoalManager
from ..ai.proactive_conversation_manager import ProactiveConversationManager
from .app_llm_bootstrap import (
    LLMRuntimeDependencies,
    create_llm_runtime_client,
    resolve_llm_bootstrap_config,
)
from .app_memory_bootstrap import build_memory_knowledge_runtime, build_profile_runtime
from .app_tts_bootstrap import (
    TTSRuntime,
    apply_tts_runtime_to_bridge,
    build_tts_runtime,
)


def _embedding_setting_map(settings_source, key: str) -> dict:
    value = settings_source.get(key, {}) if settings_source else {}
    return value if isinstance(value, dict) else {}


def _embedding_api_key_for(settings_source, provider: str) -> str:
    values = _embedding_setting_map(settings_source, "embedding_api_keys")
    return str(values.get(provider, "")).strip()


def _embedding_api_url_for(settings_source, provider: str) -> str:
    default_api_urls = {
        "openai": "https://api.openai.com/v1",
        "openai_compatible": "http://127.0.0.1:8000/v1",
    }
    configs = _embedding_setting_map(settings_source, "embedding_provider_configs")
    provider_config = configs.get(provider, {})
    if not isinstance(provider_config, dict):
        provider_config = {}
    return str(provider_config.get("api_url", default_api_urls.get(provider, ""))).strip()


class ENEApplication(QObject):
    """ENE 메인 애플리케이션 클래스"""
    
    def __init__(
        self,
        *,
        life_time_resolver=None,
        life_session_tracker_factory=None,
        life_record_manager_factory=None,
        life_timer_factory=None,
        life_data_root=None,
        shutdown_drain_scheduler_factory=None,
        shutdown_drain_poll_interval_ms: int = 25,
        shutdown_drain_timeout_ms: int = 2_000,
    ):
        super().__init__()
        self._life_time_resolver = life_time_resolver or resolve_local_time_context
        self._life_session_tracker_factory = life_session_tracker_factory or AppSessionTracker
        self._life_record_manager_factory = life_record_manager_factory or LifeRecordManager
        self._life_timer_factory = life_timer_factory or QTimer
        self._life_data_root = Path(life_data_root or get_user_data_dir())
        self._shutdown_drain_scheduler_factory = (
            shutdown_drain_scheduler_factory
            or (lambda _parent: _QtShutdownDrainScheduler())
        )
        self._shutdown_drain_poll_interval_ms = max(
            1,
            int(shutdown_drain_poll_interval_ms),
        )
        self._shutdown_drain_poll_limit = max(
            1,
            int(shutdown_drain_timeout_ms)
            // self._shutdown_drain_poll_interval_ms,
        )
        
        # 설정 관리자
        self.settings = Settings()
        self.i18n = configure_i18n(language=str(self.settings.get("ui_language", "auto")))
        self._last_system_theme_mode = None
        self._apply_followed_system_theme(save=True)
        self.interrupt_tts_on_ptt = bool(self.settings.get("interrupt_tts_on_ptt", True))
        self._init_goal_manager()
        self._init_memory_manager()
        self._init_profiles()
        self._init_mood_manager()
        self._init_life_record_runtime()
        
        # LLM 클라이언트 초기화
        self._init_llm_client()
        
        # 캘린더 매니저 초기화
        self._init_calendar_manager()
        self._init_promise_manager()
        self._init_proactive_manager()
        
        # 오버레이 윈도우 생성
        self.overlay_window = OverlayWindow(
            self.settings,
            life_time_context=self.life_time_context,
            life_view_timezone=self.life_view_timezone,
        )
        self.overlay_window.set_llm_client(self.llm_client)  # LLM 클라이언트 연결
        self._bind_life_record_runtime_to_bridge()
        if hasattr(self, "goal_manager") and self.goal_manager and hasattr(self.overlay_window.bridge, "set_goal_manager"):
            self.overlay_window.bridge.set_goal_manager(self.goal_manager)
        
        # 캘린더 매니저 연결
        if hasattr(self, 'calendar_manager') and self.calendar_manager:
            self.overlay_window.bridge.calendar_manager = self.calendar_manager
            if self.overlay_window.bridge.llm_client:
                self.overlay_window.bridge.llm_client.calendar_manager = self.calendar_manager
            print("[App] Bridge에 캘린더 매니저 연결")
        if hasattr(self, 'promise_manager') and self.promise_manager:
            self.overlay_window.bridge.promise_manager = self.promise_manager
            self.overlay_window.bridge.request_promise_items()
            print("[App] Bridge에 대화 약속 매니저 연결")
        if hasattr(self, "proactive_manager") and self.proactive_manager:
            self.overlay_window.bridge.proactive_manager = self.proactive_manager
            print("[App] Bridge에 선제 대화 매니저 연결")

        # Obsidian 패널 창 생성 (ENE 외부 플로팅)
        self.obsidian_panel_window = ObsidianPanelWindow(
            bridge=self.overlay_window.bridge,
            obs_settings=self.overlay_window.bridge.obs_settings,
        )
        self.overlay_window.bridge.set_obs_panel_window(self.obsidian_panel_window)

        self.overlay_window.show()
        
        # 트레이 아이콘 생성
        self.tray_icon = TrayIcon(
            drag_bar_visible=bool(self.settings.get("show_drag_bar", True)),
            mouse_tracking_enabled=bool(self.settings.get("mouse_tracking_enabled", True)),
        )
        self._quit_after_summary_review = False
        self._quit_in_progress = False
        self._quit_summary_review_connected = False
        self._shutdown_completed = False
        self._shutdown_worker_refs = []
        
        # 시그널 연결
        self._connect_signals()

        # 전역 PTT 초기화
        self._init_global_ptt()
        self._init_system_theme_sync()
        self._start_life_session_heartbeat()

    def _init_life_record_runtime(self) -> None:
        """생활 기록 시작 상태를 실패 폐쇄 방식으로 준비한다."""
        self.life_time_context = None
        self.life_view_timezone = "UTC"
        self.life_session_tracker = None
        self.life_record_manager = None
        self.life_record_candidate = None
        self.life_records_writable = False
        self.life_record_read_only_reason = SESSION_TRACKER_DEGRADED
        self.life_heartbeat_timer = None
        self._life_session_id = None

        try:
            resolution = self._life_time_resolver()
            view_zone = getattr(resolution, "view_timezone", None)
            self.life_view_timezone = str(getattr(view_zone, "key", "UTC") or "UTC")
            self.life_time_context = getattr(resolution, "context", None)
            records_path = self._life_data_root / "life_records.json"
            self.life_record_manager = self._life_record_manager_factory(
                records_path,
                time_context=self.life_time_context,
            )
            if self.life_time_context is None:
                self.life_view_timezone = "UTC"
                self.life_record_read_only_reason = TIMEZONE_UNAVAILABLE
                return

            session_path = self._life_data_root / "life_session_state.json"
            tracker = self._life_session_tracker_factory(
                session_path,
                time_context=self.life_time_context,
            )
            self.life_session_tracker = tracker
            candidate = tracker.start_session()
            session_id = getattr(tracker, "session_id", None)
            writable = (
                getattr(tracker, "life_records_writable", False) is True
                and isinstance(session_id, str)
                and bool(session_id)
            )
            if not writable:
                reason = getattr(tracker, "reason", None)
                self.life_record_read_only_reason = (
                    reason
                    if reason in {
                        SESSION_LEASE_UNAVAILABLE,
                        SESSION_TRACKER_DEGRADED,
                        TIMEZONE_UNAVAILABLE,
                    }
                    else SESSION_TRACKER_DEGRADED
                )
                return

            self.life_record_candidate = candidate
            self.life_records_writable = True
            self.life_record_read_only_reason = None
            self._life_session_id = session_id
        except Exception:
            self.life_record_candidate = None
            self.life_records_writable = False
            self.life_record_read_only_reason = SESSION_TRACKER_DEGRADED
            print("WARNING: life_record_startup_failed code=session_tracker_degraded")

    def _bind_life_record_runtime_to_bridge(self) -> None:
        """동일한 관리자와 시간 문맥을 bridge와 실제 LLM client에 연결한다."""
        client = getattr(self, "llm_client", None)
        manager = getattr(self, "life_record_manager", None)
        if client is not None:
            client.life_record_manager = manager

        overlay = getattr(self, "overlay_window", None)
        bridge = getattr(overlay, "bridge", None)
        if bridge is None:
            return
        bridge.life_record_manager = manager
        bridge.life_session_tracker = getattr(self, "life_session_tracker", None)
        bridge.settings = getattr(self, "settings", getattr(bridge, "settings", None))
        bridge.ene_profile = getattr(self, "ene_profile", getattr(bridge, "ene_profile", None))
        bridge.mood_manager = getattr(self, "mood_manager", getattr(bridge, "mood_manager", None))
        if client is not None:
            bridge.llm_client = client

        state = bridge._get_life_record_state()
        state.candidate = self.life_record_candidate if self.life_records_writable else None
        state.life_records_writable = self.life_records_writable is True
        state.read_only_reason = self.life_record_read_only_reason
        state.time_context = self.life_time_context
        state.view_timezone = self.life_view_timezone

    def _start_life_session_heartbeat(self) -> None:
        """권위 running 세션이 열린 경우에만 60초 heartbeat를 시작한다."""
        if not self.life_records_writable or not self._life_session_id:
            return
        try:
            timer = self._life_timer_factory(self)
            timer.setInterval(60_000)
            timer.timeout.connect(self._heartbeat_life_session)
            timer.start()
            self.life_heartbeat_timer = timer
        except Exception:
            self._set_life_records_read_only(SESSION_TRACKER_DEGRADED)

    def _heartbeat_life_session(self) -> None:
        """현재 소유 세션만 갱신하고 실패하면 즉시 쓰기를 막는다."""
        tracker = self.life_session_tracker
        if tracker is None or getattr(tracker, "session_id", None) != self._life_session_id:
            self._set_life_records_read_only(SESSION_TRACKER_DEGRADED)
            return
        try:
            succeeded = tracker.heartbeat()
        except Exception:
            succeeded = False
        if succeeded is True:
            return
        reason = getattr(tracker, "reason", None)
        if reason not in {
            SESSION_LEASE_UNAVAILABLE,
            SESSION_TRACKER_DEGRADED,
            TIMEZONE_UNAVAILABLE,
        }:
            reason = SESSION_TRACKER_DEGRADED
        self._set_life_records_read_only(reason)

    def _set_life_records_read_only(self, reason: str) -> None:
        self.life_records_writable = False
        self.life_record_candidate = None
        self.life_record_read_only_reason = reason
        timer = getattr(self, "life_heartbeat_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        overlay = getattr(self, "overlay_window", None)
        bridge = getattr(overlay, "bridge", None)
        if bridge is not None:
            state = bridge._get_life_record_state()
            state.candidate = None
            state.life_records_writable = False
            state.read_only_reason = reason
    
    def _init_llm_client(self):
        """LLM 클라이언트 초기화"""
        try:
            llm_config = resolve_llm_bootstrap_config(self.settings)

            if not llm_config.api_key:
                print(f"WARNING: LLM API 키가 비어있습니다. provider={llm_config.provider}")
                self.llm_client = None
                return
            
            self.llm_client = create_llm_runtime_client(
                llm_config,
                LLMRuntimeDependencies(
                    memory_manager=self.memory_manager,
                    knowledge_map_manager=self.knowledge_map_manager if hasattr(self, "knowledge_map_manager") else None,
                    user_profile=self.user_profile if hasattr(self, "user_profile") else None,
                    ene_profile=self.ene_profile if hasattr(self, "ene_profile") else None,
                    settings=self.settings,
                    calendar_manager=self.calendar_manager if hasattr(self, "calendar_manager") else None,
                    mood_manager=self.mood_manager if hasattr(self, "mood_manager") else None,
                    goal_manager=self.goal_manager if hasattr(self, "goal_manager") else None,
                ),
            )
            self.llm_client.life_record_manager = self.life_record_manager
            if hasattr(self, "promise_manager") and self.promise_manager:
                self.llm_client.promise_manager = self.promise_manager
            print(f"OK: LLM 클라이언트 초기화 성공 (provider={llm_config.provider}, model={llm_config.model_name or 'default'})")
            
            # TTS 및 오디오 플레이어 초기화
            self._init_tts()
            
        except Exception as e:
            print(f"ERROR: LLM 클라이언트 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.llm_client = None

    def _init_mood_manager(self):
        """기분 매니저 초기화"""
        try:
            state_file = "mood_state.json"
            if self.settings and hasattr(self.settings, "config"):
                state_file = str(self.settings.config.get("mood_state_file", state_file))
            self.mood_manager = MoodManager(state_file=state_file, settings=self.settings)
            print("OK: 기분 매니저 초기화 성공")
        except Exception as e:
            print(f"ERROR: 기분 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.mood_manager = None

    def _init_goal_manager(self):
        """에네 목표 매니저 초기화"""
        try:
            state_file = "ene_goals.json"
            if self.settings and hasattr(self.settings, "config"):
                state_file = str(self.settings.config.get("ene_goal_state_file", state_file))
            self.goal_manager = EneGoalManager(state_file=state_file, settings=self.settings)
            print("OK: 에네 목표 매니저 초기화 성공")
        except Exception as e:
            print(f"ERROR: 에네 목표 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.goal_manager = None

    def _init_profiles(self):
        """사용자/에네 프로필 초기화"""
        runtime = build_profile_runtime()
        self.user_profile = runtime.user_profile
        self.ene_profile = runtime.ene_profile
    
    def _init_calendar_manager(self):
        """캘린더 매니저 초기화"""
        from src.ai.calendar_manager import CalendarManager
        
        try:
            self.calendar_manager = CalendarManager()
            print("OK: 캘린더 매니저 초기화 성공")
        except Exception as e:
            print(f"ERROR: 캘린더 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.calendar_manager = None

    def _init_promise_manager(self):
        """대화 약속 매니저 초기화"""
        from src.ai.promise_reminder_manager import PromiseReminderManager

        try:
            self.promise_manager = PromiseReminderManager()
            if hasattr(self, "llm_client") and self.llm_client:
                self.llm_client.promise_manager = self.promise_manager
            print("OK: 대화 약속 매니저 초기화 성공")
        except Exception as e:
            print(f"ERROR: 대화 약속 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.promise_manager = None

    def _init_proactive_manager(self):
        """선제 대화 매니저 초기화"""
        try:
            self.proactive_manager = ProactiveConversationManager()
            if hasattr(self, "llm_client") and self.llm_client:
                self.llm_client.proactive_manager = self.proactive_manager
            print("OK: 선제 대화 매니저 초기화 성공")
        except Exception as e:
            print(f"ERROR: 선제 대화 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.proactive_manager = None
    
    def _init_memory_manager(self):
        """메모리 매니저 초기화"""
        try:
            runtime = build_memory_knowledge_runtime(self.settings)
            self.memory_manager = runtime.memory_manager
            self.knowledge_map_manager = runtime.knowledge_map_manager
        except Exception as e:
            print(f"ERROR: 메모리 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.memory_manager = None
            self.knowledge_map_manager = None

    def _refresh_memory_runtime_bindings(self):
        """메모리 매니저 재초기화 후 LLM/Bridge에 다시 연결한다."""
        self._init_memory_manager()
        if hasattr(self, "llm_client") and self.llm_client:
            self.llm_client.memory_manager = self.memory_manager
            self.llm_client.knowledge_map_manager = self.knowledge_map_manager
            self.llm_client.ene_profile = self.ene_profile if hasattr(self, "ene_profile") else None
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            user_profile = self.user_profile if hasattr(self, "user_profile") else None
            ene_profile = self.ene_profile if hasattr(self, "ene_profile") else None
            self.overlay_window.bridge.set_memory_manager(
                self.memory_manager,
                self.llm_client if hasattr(self, "llm_client") else None,
                user_profile,
                ene_profile,
                self.knowledge_map_manager if hasattr(self, "knowledge_map_manager") else None,
            )
    
    def _init_tts(self):
        """TTS 및 오디오 플레이어 초기화"""
        try:
            runtime = build_tts_runtime(self.settings)
            self.tts_client = runtime.tts_client
            self.audio_player = runtime.audio_player
        except Exception as e:
            print(f"WARNING: TTS 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.tts_client = None
            self.audio_player = None

    def _refresh_tts_runtime_bindings(self):
        """TTS 설정 변경 후 클라이언트/브리지 상태를 다시 연결한다."""
        self._init_tts()
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            apply_tts_runtime_to_bridge(
                self.overlay_window.bridge,
                self.settings,
                TTSRuntime(
                    tts_client=self.tts_client if hasattr(self, "tts_client") else None,
                    audio_player=self.audio_player if hasattr(self, "audio_player") else None,
                ),
            )
    
    def _connect_signals(self):
        """시그널 연결"""
        # WebBridge에 LLM 클라이언트 및 메모리 매니저 전달
        self.overlay_window.bridge.set_llm_client(self.llm_client)
        self.overlay_window.bridge.set_settings_dialog_opener(self._show_settings_dialog)
        if hasattr(self, "mood_manager") and self.mood_manager:
            self.overlay_window.bridge.set_mood_manager(self.mood_manager)
        if hasattr(self, "goal_manager") and self.goal_manager and hasattr(self.overlay_window.bridge, "set_goal_manager"):
            self.overlay_window.bridge.set_goal_manager(self.goal_manager)
        if hasattr(self, 'memory_manager'):
            user_profile = self.user_profile if hasattr(self, 'user_profile') else None
            ene_profile = self.ene_profile if hasattr(self, 'ene_profile') else None
            self.overlay_window.bridge.set_memory_manager(
                self.memory_manager,
                self.llm_client,
                user_profile,
                ene_profile,
                self.knowledge_map_manager if hasattr(self, "knowledge_map_manager") else None,
            )
        
        # TTS 클라이언트 및 오디오 플레이어 연결
        if hasattr(self, 'tts_client') and self.tts_client:
            self.overlay_window.bridge.set_tts(self.tts_client, self.audio_player)

        # 유휴 감지 모니터 시작
        self.overlay_window.bridge.start_away_monitor()
        
        # 트레이 아이콘 시그널
        self.tray_icon.settings_requested.connect(self._show_settings_dialog)
        self.tray_icon.ene_profile_requested.connect(self._show_ene_profile_dialog)
        self.tray_icon.calendar_requested.connect(self._show_calendar_dialog)
        self.tray_icon.toggle_drag_bar_requested.connect(self._toggle_drag_bar)
        self.tray_icon.toggle_mouse_tracking_requested.connect(self._toggle_mouse_tracking)
        self.tray_icon.quit_requested.connect(self._quit_application)

        self._connect_application_quit_fallback()

    def _connect_application_quit_fallback(self) -> None:
        """Qt 자체 종료도 동일한 멱등 finalizer로 한 번만 연결한다."""
        if getattr(self, "_application_quit_fallback_connected", False):
            return
        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.aboutToQuit.connect(
                lambda: self._finish_quit_application(_about_to_quit=True)
            )
            self._application_quit_fallback_connected = True

    def _init_global_ptt(self):
        """전역 PTT 컨트롤러 초기화"""
        try:
            self.global_ptt = GlobalPTTController(self.settings.config)
            self.global_ptt.transcription_ready.connect(self._on_ptt_transcription_ready)
            self.global_ptt.recording_started.connect(self._on_ptt_recording_started)
            self.global_ptt.notice.connect(self._on_ptt_notice)
            self.global_ptt.start()
            print("OK: 전역 PTT 초기화 성공")
        except Exception as e:
            print(f"WARNING: 전역 PTT 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.global_ptt = None

    def _apply_followed_system_theme(self, save: bool = False) -> bool:
        """
        윈도우 테마 따라가기가 켜져 있으면 현재 시스템 테마 프리셋을 설정에 반영한다.
        실제 반영이 일어났는지 여부를 반환한다.
        """
        if not bool(self.settings.get("follow_system_theme", False)):
            return False

        mode = get_windows_theme_mode()
        preset = get_theme_preset(mode)
        changed = False
        for key, value in preset.items():
            if self.settings.get(key) != value:
                self.settings.set(key, value)
                changed = True
        if self.settings.get("theme_mode", "light") != mode:
            self.settings.set("theme_mode", mode)
            changed = True
        self._last_system_theme_mode = mode
        if changed and save:
            self.settings.save()
        return changed

    def _init_system_theme_sync(self):
        """윈도우 테마 추적 타이머를 시작한다."""
        self.system_theme_timer = QTimer(self)
        self.system_theme_timer.setInterval(3000)
        self.system_theme_timer.timeout.connect(self._sync_system_theme_if_needed)
        self.system_theme_timer.start()

    def _sync_system_theme_if_needed(self):
        """윈도우 테마 변경을 감지해 ENE 테마를 동기화한다."""
        if not bool(self.settings.get("follow_system_theme", False)):
            self._last_system_theme_mode = None
            return

        current_mode = get_windows_theme_mode()
        if current_mode == self._last_system_theme_mode:
            return

        changed = self._apply_followed_system_theme(save=True)
        if changed and hasattr(self, "overlay_window") and self.overlay_window:
            self.overlay_window.apply_new_settings(dict(self.settings.config))
        if hasattr(self, "_settings_dialog") and self._settings_dialog and self._settings_dialog.isVisible():
            current_settings = dict(self.settings.config)
            if hasattr(self.settings, "secret_config") and isinstance(self.settings.secret_config, dict):
                current_settings.update(self.settings.secret_config)
            self._settings_dialog._original_settings = current_settings
            self._settings_dialog._load_values()

    def _on_ptt_transcription_ready(self, text: str):
        """STT 결과 텍스트를 기존 채팅 경로로 전달"""
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        if hasattr(self, "overlay_window") and self.overlay_window:
            self.overlay_window.send_voice_text(cleaned)

    def _on_ptt_notice(self, message: str, level: str = "info"):
        """PTT 상태를 토스트/로그로 전달"""
        print(f"[PTT][{level}] {message}")
        if hasattr(self, "overlay_window") and self.overlay_window:
            self.overlay_window.show_toast(message, level)

    def _on_ptt_recording_started(self):
        """PTT 녹음 시작 시 설정에 따라 TTS 출력을 중단한다."""
        if not bool(self.interrupt_tts_on_ptt):
            return
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            self.overlay_window.bridge.interrupt_tts_for_ptt()
    
    def _show_settings_dialog(self, section_id: str | None = None):
        """설정 다이얼로그 표시 (비모달)"""
        # 이미 열려있으면 포커스
        if hasattr(self, '_settings_dialog') and self._settings_dialog and self._settings_dialog.isVisible():
            if section_id and hasattr(self._settings_dialog, "focus_section"):
                self._settings_dialog.focus_section(section_id)
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        
        # 설정창은 "현재 화면 상태"를 기준으로 열어야 체크/토글 시 위치가 튀지 않는다.
        current_settings = dict(self.settings.config)
        if hasattr(self.settings, "secret_config") and isinstance(self.settings.secret_config, dict):
            current_settings.update(self.settings.secret_config)
        if hasattr(self, 'overlay_window') and self.overlay_window:
            current_settings['window_x'] = self.overlay_window.x()
            current_settings['window_y'] = self.overlay_window.y()
            current_settings['window_width'] = self.overlay_window.width()
            current_settings['window_height'] = self.overlay_window.height()

        memory_manager = self.memory_manager if hasattr(self, "memory_manager") else None
        bridge = self.overlay_window.bridge if hasattr(self.overlay_window, "bridge") else None
        dialog = SettingsDialog(current_settings, memory_manager=memory_manager, bridge=bridge)
        self._settings_dialog = dialog
        
        # 시그널 연결
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.settings_preview.connect(self._on_settings_preview)
        dialog.settings_cancelled.connect(self._on_settings_cancelled)
        
        # 드래그 바의 위치 변경 시그널을 설정창에 연결
        self.overlay_window.drag_bar.position_changed.connect(dialog.update_position)
        self._connect_overlay_drag_persistence()
        
        # 비모달로 표시
        dialog.show()
        if section_id and hasattr(dialog, "focus_section"):
            dialog.focus_section(section_id)

    def _connect_overlay_drag_persistence(self):
        drag_bar = getattr(getattr(self, "overlay_window", None), "drag_bar", None)
        try:
            already_connected = getattr(self, "_overlay_drag_persistence_connected", False)
        except RuntimeError:
            already_connected = False
        if drag_bar is None or already_connected:
            return
        signal = getattr(drag_bar, "drag_finished", None) or getattr(drag_bar, "position_changed", None)
        if signal is None or not hasattr(signal, "connect"):
            return
        signal.connect(self._persist_overlay_position)
        self._overlay_drag_persistence_connected = True

    def _persist_overlay_position(self, x: int, y: int):
        settings = getattr(self, "settings", None)
        if settings is None:
            return
        try:
            next_x = int(x)
            next_y = int(y)
        except (TypeError, ValueError):
            return

        setter = getattr(settings, "set", None)
        if callable(setter):
            setter("window_x", next_x)
            setter("window_y", next_y)
        elif isinstance(getattr(settings, "config", None), dict):
            settings.config["window_x"] = next_x
            settings.config["window_y"] = next_y
        else:
            return

        saver = getattr(settings, "save", None)
        if callable(saver):
            saver()
    
    def _show_memory_dialog(self):
        """기억 관리 다이얼로그 표시"""
        if not hasattr(self, 'memory_manager') or not self.memory_manager:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                None,
                tr("memory.warning.title"),
                tr("memory.warning.body")
            )
            return
        
        from src.ui.memory_dialog import MemoryDialog
        
        # WebBridge 참조 전달
        try:
            overlay_window = getattr(self, "overlay_window", None)
        except RuntimeError:
            overlay_window = None
        try:
            knowledge_map_manager = getattr(self, "knowledge_map_manager", None)
        except RuntimeError:
            knowledge_map_manager = None
        bridge = getattr(overlay_window, "bridge", None)
        dialog = MemoryDialog(
            self.memory_manager,
            bridge,
            knowledge_map_manager=knowledge_map_manager,
        )
        dialog.exec()

    def _show_ene_profile_dialog(self):
        """에네 기억 관리 탭으로 이동한다."""
        self._show_settings_dialog("ene_profile")
    
    def _show_calendar_dialog(self):
        """캘린더 다이얼로그 표시"""
        from src.ui.calendar_dialog import CalendarDialog
        
        if not hasattr(self, 'calendar_manager') or not self.calendar_manager:
            print("[App] Calendar manager가 없습니다")
            return
        
        dialog = CalendarDialog(self.calendar_manager)
        dialog.exec()
    
    def _on_settings_changed(self, new_settings: dict):
        """설정 변경 시 (저장)"""
        old_ui_language = str(self.settings.get("ui_language", "auto")).strip() or "auto"
        old_embedding_provider = str(self.settings.get("embedding_provider", "voyage")).strip().lower()
        old_embedding_model = str(self.settings.get("embedding_model", "voyage-3")).strip() or "voyage-3"
        old_tts_config = json.dumps(
            {
                "enable_tts": bool(self.settings.get("enable_tts", False)),
                "tts_streaming_enabled": bool(self.settings.get("tts_streaming_enabled", False)),
                "tts_streaming_emit_message_on_first_chunk": bool(
                    self.settings.get("tts_streaming_emit_message_on_first_chunk", True)
                ),
                "tts_output_device_id": str(self.settings.get("tts_output_device_id", "")).strip(),
                "tts_output_volume": float(self.settings.get("tts_output_volume", 0.8) or 0.8),
                "tts_provider": str(self.settings.get("tts_provider", "gpt_sovits_http")).strip(),
                "tts_provider_configs": self.settings.get("tts_provider_configs", {}),
                "tts_api_keys": self.settings.get("tts_api_keys", {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        self.overlay_window.apply_new_settings(new_settings)
        if hasattr(self.overlay_window, "bridge") and self.overlay_window.bridge:
            refresh_proactive_settings = getattr(self.overlay_window.bridge, "refresh_proactive_settings", None)
            if callable(refresh_proactive_settings):
                refresh_proactive_settings()
        self.interrupt_tts_on_ptt = bool(new_settings.get("interrupt_tts_on_ptt", True))
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.apply_settings(new_settings)

        new_ui_language = str(new_settings.get("ui_language", old_ui_language)).strip() or "auto"
        if old_ui_language != new_ui_language:
            self.i18n = configure_i18n(language=new_ui_language)
            if hasattr(self, "tray_icon") and self.tray_icon:
                self.tray_icon.retranslate_ui()
            if hasattr(self, "obsidian_panel_window") and self.obsidian_panel_window:
                self.obsidian_panel_window.retranslate_ui()
            if (
                hasattr(self, "_settings_dialog")
                and self._settings_dialog
                and self._settings_dialog.isVisible()
                and hasattr(self._settings_dialog, "_retranslate_ui")
            ):
                self._settings_dialog._retranslate_ui()

        new_embedding_provider = str(new_settings.get("embedding_provider", old_embedding_provider)).strip().lower()
        new_embedding_model = str(new_settings.get("embedding_model", old_embedding_model)).strip() or "voyage-3"
        old_embedding_key = _embedding_api_key_for(self.settings, new_embedding_provider)
        new_embedding_key_source = (
            new_settings
            if "embedding_api_keys" in new_settings
            else self.settings
        )
        new_embedding_key = _embedding_api_key_for(new_embedding_key_source, new_embedding_provider)
        old_embedding_api_url = _embedding_api_url_for(self.settings, new_embedding_provider)
        new_embedding_api_url_source = (
            new_settings
            if "embedding_provider_configs" in new_settings
            else self.settings
        )
        new_embedding_api_url = _embedding_api_url_for(new_embedding_api_url_source, new_embedding_provider)
        embedding_source_changed = (
            old_embedding_provider,
            old_embedding_model,
        ) != (
            new_embedding_provider,
            new_embedding_model,
        )
        embedding_runtime_config_changed = (
            old_embedding_key,
            old_embedding_api_url,
        ) != (
            new_embedding_key,
            new_embedding_api_url,
        )
        if embedding_source_changed or embedding_runtime_config_changed:
            if hasattr(self, "memory_manager") and self.memory_manager:
                marker = getattr(self.memory_manager, "mark_unknown_embeddings_source", None)
                if embedding_source_changed and callable(marker):
                    marker(old_embedding_provider, old_embedding_model)
            self._refresh_memory_runtime_bindings()
            if embedding_source_changed:
                self._show_embedding_rebuild_prompt(new_embedding_provider, new_embedding_model)

        new_tts_config = json.dumps(
            {
                "enable_tts": bool(new_settings.get("enable_tts", self.settings.get("enable_tts", False))),
                "tts_streaming_enabled": bool(
                    new_settings.get("tts_streaming_enabled", self.settings.get("tts_streaming_enabled", False))
                ),
                "tts_streaming_emit_message_on_first_chunk": bool(
                    new_settings.get(
                        "tts_streaming_emit_message_on_first_chunk",
                        self.settings.get("tts_streaming_emit_message_on_first_chunk", True),
                    )
                ),
                "tts_output_device_id": str(new_settings.get("tts_output_device_id", self.settings.get("tts_output_device_id", ""))).strip(),
                "tts_output_volume": float(new_settings.get("tts_output_volume", self.settings.get("tts_output_volume", 0.8)) or 0.8),
                "tts_provider": str(new_settings.get("tts_provider", self.settings.get("tts_provider", "gpt_sovits_http"))).strip(),
                "tts_provider_configs": new_settings.get("tts_provider_configs", self.settings.get("tts_provider_configs", {})),
                "tts_api_keys": new_settings.get("tts_api_keys", self.settings.get("tts_api_keys", {})),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if old_tts_config != new_tts_config:
            self._refresh_tts_runtime_bindings()

    def _show_embedding_rebuild_prompt(self, provider: str, model: str) -> None:
        """임베딩 설정 변경 후 기존 메모리 재생성을 안내한다."""
        if not hasattr(self, "memory_manager") or not self.memory_manager:
            return
        knowledge_map_manager = getattr(self, "knowledge_map_manager", None)
        embedding_count = count_saved_embeddings(self.memory_manager, knowledge_map_manager)
        if embedding_count == 0:
            return

        reply = QMessageBox.question(
            self.overlay_window if hasattr(self, "overlay_window") else None,
            tr("memory.embedding.rebuild.prompt.title"),
            tr("memory.embedding.rebuild.prompt.body", provider=provider, model=model, count=embedding_count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._regenerate_memory_embeddings_with_feedback(
                self.overlay_window if hasattr(self, "overlay_window") else None
            )

    def _regenerate_memory_embeddings_with_feedback(self, parent=None) -> dict[str, int] | None:
        """현재 메모리 매니저의 임베딩을 재생성하고 결과를 사용자에게 알린다."""
        if not hasattr(self, "memory_manager") or not self.memory_manager:
            QMessageBox.warning(
                parent,
                tr("memory.warning.title"),
                tr("memory.warning.body"),
            )
            return None

        knowledge_map_manager = getattr(self, "knowledge_map_manager", None)
        if not (
            has_embedding_regenerator(self.memory_manager)
            or has_embedding_regenerator(knowledge_map_manager)
        ):
            QMessageBox.warning(
                parent,
                tr("memory.embedding.rebuild.unavailable.title"),
                tr("memory.embedding.rebuild.unavailable.body"),
            )
            return None

        try:
            QApplication.processEvents()
            result = asyncio.run(regenerate_saved_embeddings(self.memory_manager, knowledge_map_manager))
        except Exception as error:
            QMessageBox.warning(
                parent,
                tr("memory.embedding.rebuild.failed.title"),
                tr("memory.embedding.rebuild.failed.body", error=str(error)),
            )
            return None
        QMessageBox.information(
            parent,
            tr("memory.embedding.rebuild.complete.title"),
            tr(
                "memory.embedding.rebuild.complete.body",
                updated=result.get("updated", 0),
                failed=result.get("failed", 0),
                skipped=result.get("skipped", 0),
            ),
        )
        return result

    def _on_settings_preview(self, new_settings: dict):
        """설정 미리보기 (settings 객체 수정 없이 화면에만 적용)"""
        self.overlay_window.preview_settings(new_settings)
        self.interrupt_tts_on_ptt = bool(new_settings.get("interrupt_tts_on_ptt", True))
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.apply_settings(new_settings)
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            self.overlay_window.bridge.enable_tts = bool(new_settings.get("enable_tts", self.settings.get("enable_tts", False)))
            self.overlay_window.bridge.tts_streaming_enabled = bool(
                new_settings.get("tts_streaming_enabled", self.settings.get("tts_streaming_enabled", False))
            )
            self.overlay_window.bridge.tts_streaming_emit_message_on_first_chunk = bool(
                new_settings.get(
                    "tts_streaming_emit_message_on_first_chunk",
                    self.settings.get("tts_streaming_emit_message_on_first_chunk", True),
                )
            )

    def _on_settings_cancelled(self):
        """설정 취소 - 저장된 값으로 복원"""
        self.overlay_window.restore_settings()
        self.interrupt_tts_on_ptt = bool(self.settings.get("interrupt_tts_on_ptt", True))
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.apply_settings(self.settings.config)
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            self.overlay_window.bridge.enable_tts = bool(self.settings.get("enable_tts", False))
            self.overlay_window.bridge.tts_streaming_enabled = bool(
                self.settings.get("tts_streaming_enabled", False)
            )
            self.overlay_window.bridge.tts_streaming_emit_message_on_first_chunk = bool(
                self.settings.get("tts_streaming_emit_message_on_first_chunk", True)
            )
    
    def _toggle_drag_bar(self):
        """드래그 바 토글"""
        is_visible = self.overlay_window.toggle_drag_bar()
        self.tray_icon.update_drag_bar_menu_text(is_visible)
    
    def _toggle_mouse_tracking(self):
        """마우스 트래킹 토글"""
        is_enabled = self.overlay_window.toggle_mouse_tracking()
        self.tray_icon.update_mouse_tracking_menu_text(is_enabled)

    def _bridge_has_unsummarized_messages(self) -> bool:
        """종료 전에 확인해야 할 미요약 대화가 있는지 확인한다."""
        if not hasattr(self, "overlay_window") or not hasattr(self.overlay_window, "bridge"):
            return False
        bridge = self.overlay_window.bridge
        return bool(getattr(bridge, "conversation_buffer", None))

    def _ask_quit_summary_confirmation(self) -> bool:
        """종료 전 미요약 대화를 저장할지 사용자에게 묻는다."""
        reply = QMessageBox.question(
            self.overlay_window if hasattr(self, "overlay_window") else None,
            tr("app.quit.summary.title"),
            tr("app.quit.summary.body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _start_quit_summary_review(self):
        """수동 요약 검토를 시작하고 저장 완료 후 종료되도록 연결한다."""
        if not hasattr(self, "overlay_window") or not hasattr(self.overlay_window, "bridge"):
            self._finish_quit_application()
            return

        bridge = self.overlay_window.bridge
        self._quit_after_summary_review = True
        if not getattr(self, "_quit_summary_review_connected", False):
            saved_signal = getattr(bridge, "summary_review_saved", None)
            if saved_signal is not None:
                saved_signal.connect(self._on_quit_summary_review_saved)
                self._quit_summary_review_connected = True

        if hasattr(self.overlay_window, "show"):
            self.overlay_window.show()
        if hasattr(self.overlay_window, "raise_"):
            self.overlay_window.raise_()
        if hasattr(self.overlay_window, "activateWindow"):
            self.overlay_window.activateWindow()

        bridge.summarize_now()

    def _on_quit_summary_review_saved(self):
        """종료 대기 중인 요약 검토 저장이 끝나면 실제 종료한다."""
        if not getattr(self, "_quit_after_summary_review", False):
            return
        self._finish_quit_application()
    
    def _quit_application(self):
        """애플리케이션 종료"""
        print("애플리케이션 종료 중...")

        if getattr(self, "_quit_in_progress", False):
            return

        if self._bridge_has_unsummarized_messages():
            if self._ask_quit_summary_confirmation():
                self._start_quit_summary_review()
                return
            print("종료 전 요약을 건너뜁니다.")

        self._finish_quit_application()

    @staticmethod
    def _shutdown_qt_object_is_deleted(value) -> bool:
        try:
            return sip.isdeleted(value) is True
        except (TypeError, RuntimeError):
            return False

    @staticmethod
    def _shutdown_safe_getattr(owner, name: str, default=None):
        """삭제된 Qt wrapper를 포함한 종료 객체의 속성을 안전하게 읽는다."""
        if owner is None:
            return default
        try:
            return getattr(owner, name, default)
        except Exception:
            return default

    @staticmethod
    def _shutdown_worker_is_running(worker) -> bool:
        try:
            checker = getattr(worker, "isRunning", None)
        except Exception:
            return not ENEApplication._shutdown_qt_object_is_deleted(worker)
        if not callable(checker):
            return False
        try:
            return checker() is True
        except Exception:
            return not ENEApplication._shutdown_qt_object_is_deleted(worker)

    def _collect_shutdown_workers(self, bridge) -> list:
        """종료 barrier가 소유해야 할 실행 중 worker를 중복 없이 모은다."""
        candidates = [
            self._shutdown_safe_getattr(bridge, "worker"),
            self._shutdown_safe_getattr(bridge, "tts_worker"),
            self._shutdown_safe_getattr(bridge, "_summary_review_worker"),
            self._shutdown_safe_getattr(bridge, "obs_tree_worker"),
            self._shutdown_safe_getattr(bridge, "obs_checked_files_worker"),
        ]
        state = self._shutdown_safe_getattr(bridge, "life_record_state")
        candidates.append(self._shutdown_safe_getattr(state, "worker"))
        workers = []
        seen = set()
        for worker in candidates:
            identity = id(worker)
            if worker is None or identity in seen:
                continue
            seen.add(identity)
            if self._shutdown_worker_is_running(worker):
                workers.append(worker)
        return workers

    def _prepare_shutdown_worker(
        self,
        worker,
        *,
        interruption_already_requested: bool = False,
    ) -> None:
        """새로 발견한 worker를 취소하고 종료 신호를 drain 확인에 연결한다."""
        if not interruption_already_requested:
            interrupt = self._shutdown_safe_getattr(worker, "requestInterruption")
            if callable(interrupt):
                try:
                    interrupt()
                except Exception:
                    pass
        request_stop = self._shutdown_safe_getattr(worker, "request_stop")
        if callable(request_stop):
            try:
                request_stop()
            except Exception:
                pass
        finished = self._shutdown_safe_getattr(worker, "finished")
        connect = self._shutdown_safe_getattr(finished, "connect")
        if callable(connect):
            try:
                connect(self._schedule_shutdown_drain_check)
            except Exception:
                pass

    def _refresh_shutdown_workers(
        self,
        bridge,
        *,
        state_interrupted_worker=None,
    ) -> list:
        """매 poll의 worker 스냅샷을 기존 강한 참조와 합친다."""
        workers = list(getattr(self, "_shutdown_worker_refs", []))
        seen = {id(worker) for worker in workers}
        for worker in self._collect_shutdown_workers(bridge):
            identity = id(worker)
            if identity in seen:
                continue
            seen.add(identity)
            workers.append(worker)
            self._prepare_shutdown_worker(
                worker,
                interruption_already_requested=worker is state_interrupted_worker,
            )
        self._shutdown_worker_refs = workers
        return workers

    def _schedule_shutdown_drain_check(self) -> None:
        if getattr(self, "_shutdown_completed", False):
            return
        if getattr(self, "_shutdown_drain_check_scheduled", False):
            return
        scheduler = getattr(self, "_shutdown_drain_scheduler", None)
        try:
            if scheduler is None:
                factory = getattr(
                    self,
                    "_shutdown_drain_scheduler_factory",
                    lambda _parent: _QtShutdownDrainScheduler(),
                )
                scheduler = factory(self)
                self._shutdown_drain_scheduler = scheduler
            self._shutdown_drain_check_scheduled = True
            scheduler.schedule(
                int(getattr(self, "_shutdown_drain_poll_interval_ms", 25)),
                self._check_shutdown_workers,
            )
        except Exception:
            self._shutdown_drain_check_scheduled = False
            self._complete_shutdown(workers_drained=False)

    def _check_shutdown_workers(self) -> None:
        self._shutdown_drain_check_scheduled = False
        if getattr(self, "_shutdown_completed", False):
            return
        overlay = self._shutdown_safe_getattr(self, "overlay_window")
        bridge = self._shutdown_safe_getattr(overlay, "bridge")
        workers = self._refresh_shutdown_workers(bridge)
        if not any(self._shutdown_worker_is_running(worker) for worker in workers):
            self._complete_shutdown(workers_drained=True)
            return
        remaining = int(getattr(self, "_shutdown_drain_polls_remaining", 0)) - 1
        self._shutdown_drain_polls_remaining = remaining
        if remaining <= 0:
            self._complete_shutdown(workers_drained=False)
            return
        self._schedule_shutdown_drain_check()

    @staticmethod
    def _stop_timer_safely(timer) -> None:
        stop = ENEApplication._shutdown_safe_getattr(timer, "stop")
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    def _stop_shutdown_worker_producers(self, bridge) -> None:
        """첫 worker 스냅샷 전에 새 작업을 만들 수 있는 타이머를 멈춘다."""
        if getattr(self, "_shutdown_worker_producers_stopped", False):
            return
        self._shutdown_worker_producers_stopped = True
        stop_away = self._shutdown_safe_getattr(bridge, "stop_away_monitor")
        if callable(stop_away):
            try:
                stop_away()
            except Exception:
                pass
        for name in ("promise_timer", "proactive_timer", "obs_tree_retry_timer"):
            self._stop_timer_safely(self._shutdown_safe_getattr(bridge, name))

    def _stop_shutdown_timers(self, bridge) -> None:
        self._stop_shutdown_worker_producers(bridge)
        self._stop_timer_safely(self._shutdown_safe_getattr(self, "system_theme_timer"))
        self._stop_timer_safely(self._shutdown_safe_getattr(self, "life_heartbeat_timer"))

    def _complete_shutdown(self, *, workers_drained: bool) -> None:
        """drain 결과에 맞춰 세션 commit과 UI teardown을 한 번만 수행한다."""
        if getattr(self, "_shutdown_completed", False):
            return
        self._shutdown_completed = True
        overlay = getattr(self, "overlay_window", None)
        bridge = getattr(overlay, "bridge", None)
        self._stop_shutdown_timers(bridge)

        tracker = getattr(self, "life_session_tracker", None)
        if workers_drained and tracker is not None:
            stop_session = getattr(tracker, "stop_session", None)
            if callable(stop_session):
                try:
                    if stop_session() is not True:
                        print(
                            "WARNING: life_record_shutdown_failed "
                            "code=session_stop_failed"
                        )
                except Exception:
                    print(
                        "WARNING: life_record_shutdown_failed "
                        "code=session_stop_failed"
                    )

        dialog = getattr(self, "_settings_dialog", None)
        if dialog is not None:
            try:
                if dialog.isVisible():
                    dialog.close()
            except Exception:
                pass
        if overlay is not None:
            for method_name in ("shutdown", "close"):
                method = getattr(overlay, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
        panel = getattr(self, "obsidian_panel_window", None)
        close_panel = getattr(panel, "close", None)
        if callable(close_panel):
            try:
                close_panel()
            except Exception:
                pass
        global_ptt = getattr(self, "global_ptt", None)
        shutdown_ptt = getattr(global_ptt, "shutdown", None)
        if callable(shutdown_ptt):
            try:
                shutdown_ptt()
            except Exception:
                pass
        tray = getattr(getattr(self, "tray_icon", None), "tray_icon", None)
        hide_tray = getattr(tray, "hide", None)
        if callable(hide_tray):
            try:
                hide_tray()
            except Exception:
                pass

        release_lease = getattr(tracker, "release_lease", None)
        if callable(release_lease):
            try:
                release_lease()
            except Exception:
                print(
                    "WARNING: life_record_shutdown_failed "
                    "code=session_lease_release_failed"
                )
        if not getattr(self, "_shutdown_from_about_to_quit", False):
            QApplication.quit()

    def _finish_quit_application(self, *, _about_to_quit: bool = False):
        """모든 종료 진입점이 공유하는 비차단 멱등 finalizer다."""
        if getattr(self, "_shutdown_completed", False):
            return
        if getattr(self, "_quit_in_progress", False):
            if _about_to_quit:
                overlay = self._shutdown_safe_getattr(self, "overlay_window")
                bridge = self._shutdown_safe_getattr(overlay, "bridge")
                workers = self._refresh_shutdown_workers(bridge)
                drained = not any(
                    self._shutdown_worker_is_running(worker) for worker in workers
                )
                self._shutdown_from_about_to_quit = True
                self._complete_shutdown(workers_drained=drained)
            return

        self._quit_in_progress = True
        self._quit_after_summary_review = False
        self._shutdown_from_about_to_quit = _about_to_quit is True

        overlay = getattr(self, "overlay_window", None)
        bridge = getattr(overlay, "bridge", None)
        life_state = getattr(bridge, "life_record_state", None)
        life_worker = getattr(life_state, "worker", None)
        begin_shutdown = getattr(bridge, "begin_shutdown", None)
        if callable(begin_shutdown):
            try:
                begin_shutdown()
            except Exception:
                pass
        elif life_state is not None:
            begin_state_shutdown = getattr(life_state, "begin_shutdown", None)
            if callable(begin_state_shutdown):
                try:
                    begin_state_shutdown()
                except Exception:
                    pass

        self._stop_shutdown_worker_producers(bridge)
        self._shutdown_worker_refs = []
        workers = self._refresh_shutdown_workers(
            bridge,
            state_interrupted_worker=life_worker,
        )

        if not any(self._shutdown_worker_is_running(worker) for worker in workers):
            self._complete_shutdown(workers_drained=True)
            return
        if _about_to_quit:
            self._complete_shutdown(workers_drained=False)
            return
        self._shutdown_drain_polls_remaining = int(
            getattr(self, "_shutdown_drain_poll_limit", 80)
        )
        self._schedule_shutdown_drain_check()


class _QtShutdownDrainScheduler:
    """GUI 스레드를 막지 않는 기본 종료 drain 스케줄러."""

    @staticmethod
    def schedule(delay_ms: int, callback) -> None:
        QTimer.singleShot(delay_ms, callback)
