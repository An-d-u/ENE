"""
ENE 메인 애플리케이션
오버레이 윈도우와 트레이 아이콘을 관리
"""
import json

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, QTimer

from .i18n import configure_i18n, tr
from .settings import Settings
from .system_theme import get_theme_preset, get_windows_theme_mode
from .overlay_window import OverlayWindow
from .global_ptt import GlobalPTTController
from .tray_icon import TrayIcon
from ..ui.obsidian_panel_window import ObsidianPanelWindow
from ..ui.settings_dialog import SettingsDialog
from ..ai.llm_provider import LLMProviderConfig, create_llm_client
from ..ai.mood_manager import MoodManager


class ENEApplication(QObject):
    """ENE 메인 애플리케이션 클래스"""
    
    def __init__(self):
        super().__init__()
        
        # 설정 관리자
        self.settings = Settings()
        self.i18n = configure_i18n(language=str(self.settings.get("ui_language", "auto")))
        self._last_system_theme_mode = None
        self._apply_followed_system_theme(save=True)
        self.interrupt_tts_on_ptt = bool(self.settings.get("interrupt_tts_on_ptt", True))
        
        # LLM 클라이언트 초기화
        self._init_llm_client()
        
        # 캘린더 매니저 초기화
        self._init_calendar_manager()
        
        # 오버레이 윈도우 생성
        self.overlay_window = OverlayWindow(self.settings)
        self.overlay_window.set_llm_client(self.llm_client)  # LLM 클라이언트 연결
        
        # 캘린더 매니저 연결
        if hasattr(self, 'calendar_manager') and self.calendar_manager:
            self.overlay_window.bridge.calendar_manager = self.calendar_manager
            if self.overlay_window.bridge.llm_client:
                self.overlay_window.bridge.llm_client.calendar_manager = self.calendar_manager
            print("[App] Bridge에 캘린더 매니저 연결")

        # Obsidian 패널 창 생성 (ENE 외부 플로팅)
        self.obsidian_panel_window = ObsidianPanelWindow(
            bridge=self.overlay_window.bridge,
            obs_settings=self.overlay_window.bridge.obs_settings,
        )
        self.overlay_window.bridge.set_obs_panel_window(self.obsidian_panel_window)

        self.overlay_window.show()
        if bool(self.overlay_window.bridge.obs_settings.get("panel_visible", True)):
            self.obsidian_panel_window.show()
            self.obsidian_panel_window.refresh_tree()
        
        # 트레이 아이콘 생성
        self.tray_icon = TrayIcon()
        
        # 시그널 연결
        self._connect_signals()

        # 전역 PTT 초기화
        self._init_global_ptt()
        self._init_system_theme_sync()
    
    def _init_llm_client(self):
        """LLM 클라이언트 초기화"""
        from pathlib import Path

        try:
            llm_provider = str(self.settings.get("llm_provider", "gemini")).strip().lower()
            llm_models = self.settings.get("llm_models", {})
            if not isinstance(llm_models, dict):
                llm_models = {}
            llm_model = str(llm_models.get(llm_provider, "")).strip()
            if not llm_model:
                llm_model = str(self.settings.get("llm_model", "")).strip()
            generation_params = self._resolve_generation_params(llm_provider, llm_model)

            llm_api_keys = self.settings.get("llm_api_keys", {})
            if not isinstance(llm_api_keys, dict):
                llm_api_keys = {}

            api_key = str(llm_api_keys.get(llm_provider, "")).strip()
            if not api_key and llm_provider == "custom_api":
                api_key = str(self.settings.get("custom_api_key_or_password", "")).strip()

            # 기존 방식(api_key.txt)과의 호환: Gemini 선택 시에만 폴백
            if not api_key and llm_provider == "gemini":
                api_key_file = Path('api_key.txt')
                if api_key_file.exists():
                    api_key = api_key_file.read_text(encoding='utf-8').strip()

            if not api_key:
                print(f"WARNING: LLM API 키가 비어있습니다. provider={llm_provider}")
                self.llm_client = None
                self.memory_manager = None
                return
            
            # 메모리 매니저를 먼저 초기화
            self._init_memory_manager()
            
            # 사용자 프로필 초기화
            self._init_user_profile()
            self._init_mood_manager()
            
            # LLM 클라이언트 초기화 (공급자 추상화 + 메모리 매니저 + 프로필 전달)
            llm_config = LLMProviderConfig(
                provider=llm_provider,
                api_key=api_key,
                model_name=llm_model,
                generation_params=generation_params,
            )

            self.llm_client = create_llm_client(
                llm_config,
                memory_manager=self.memory_manager,
                user_profile=self.user_profile if hasattr(self, 'user_profile') else None,
                settings=self.settings,
                calendar_manager=self.calendar_manager if hasattr(self, 'calendar_manager') else None,
                mood_manager=self.mood_manager if hasattr(self, "mood_manager") else None,
            )
            print(f"OK: LLM 클라이언트 초기화 성공 (provider={llm_provider}, model={llm_model or 'default'})")
            
            # TTS 및 오디오 플레이어 초기화
            self._init_tts()
            
        except Exception as e:
            print(f"ERROR: LLM 클라이언트 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.llm_client = None
            self.memory_manager = None

    def _resolve_generation_params(self, provider: str, model_name: str) -> dict:
        defaults = {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048}
        raw = self.settings.get("llm_model_params", {})
        if not isinstance(raw, dict):
            return defaults

        provider_map = raw.get(provider, {})
        if not isinstance(provider_map, dict):
            return defaults

        model_key = str(model_name or "").strip()
        candidate = provider_map.get(model_key) if model_key else None
        if not isinstance(candidate, dict):
            candidate = provider_map.get("__default__")
        if not isinstance(candidate, dict):
            return defaults

        resolved = dict(defaults)
        try:
            resolved["temperature"] = max(0.0, min(2.0, float(candidate.get("temperature", defaults["temperature"]))))
        except (TypeError, ValueError):
            pass
        try:
            resolved["top_p"] = max(0.0, min(1.0, float(candidate.get("top_p", defaults["top_p"]))))
        except (TypeError, ValueError):
            pass
        try:
            resolved["max_tokens"] = max(0, int(candidate.get("max_tokens", defaults["max_tokens"])))
        except (TypeError, ValueError):
            pass
        return resolved

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

    def _init_user_profile(self):
        """사용자 프로필 초기화"""
        try:
            from src.ai.user_profile import UserProfile
            
            self.user_profile = UserProfile(profile_file="user_profile.json")
            print("OK: 사용자 프로필 초기화 성공")
            
        except Exception as e:
            print(f"ERROR: 사용자 프로필 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.user_profile = None
    
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
    
    def _init_memory_manager(self):
        """메모리 매니저 초기화"""
        from src.ai.memory import MemoryManager
        from src.ai.embedding import EmbeddingGenerator
        
        try:
            embedding_provider = str(self.settings.get("embedding_provider", "voyage")).strip().lower()
            embedding_model = str(self.settings.get("embedding_model", "voyage-3")).strip() or "voyage-3"
            embedding_api_keys = self.settings.get("embedding_api_keys", {})
            if not isinstance(embedding_api_keys, dict):
                embedding_api_keys = {}
            embedding_api_key = str(embedding_api_keys.get(embedding_provider, "")).strip()

            if embedding_provider != "voyage":
                print(f"WARNING: 지원하지 않는 임베딩 공급자입니다: {embedding_provider}")
                embedding_gen = None
            elif not embedding_api_key:
                print("WARNING: 임베딩 API 키가 없습니다.")
                print("장기기억 기능이 제한적으로 작동합니다 (임베딩 없음).")
                embedding_gen = None
            else:
                if embedding_api_key == "your-voyage-api-key-here" or not embedding_api_key:
                    print("WARNING: Voyage AI API 키를 설정해주세요.")
                    embedding_gen = None
                else:
                    embedding_gen = EmbeddingGenerator(api_key=embedding_api_key, model=embedding_model)
                    print(f"OK: Voyage AI 임베딩 생성기 초기화 성공 ({embedding_model})")
            
            # 메모리 매니저 생성
            self.memory_manager = MemoryManager(
                memory_file="memory.json",
                embedding_generator=embedding_gen
            )
            print("OK: 메모리 매니저 초기화 성공")
            
        except Exception as e:
            print(f"ERROR: 메모리 매니저 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self.memory_manager = None

    def _refresh_memory_runtime_bindings(self):
        """메모리 매니저 재초기화 후 LLM/Bridge에 다시 연결한다."""
        self._init_memory_manager()
        if hasattr(self, "llm_client") and self.llm_client:
            self.llm_client.memory_manager = self.memory_manager
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            user_profile = self.user_profile if hasattr(self, "user_profile") else None
            self.overlay_window.bridge.set_memory_manager(
                self.memory_manager,
                self.llm_client if hasattr(self, "llm_client") else None,
                user_profile,
            )
    
    def _init_tts(self):
        """TTS 및 오디오 플레이어 초기화"""
        try:
            from src.ai.tts_client import create_tts_client, get_tts_provider_defaults
            from src.core.audio_player import AudioPlayer

            if not bool(self.settings.get("enable_tts", True)):
                self.tts_client = None
                self.audio_player = None
                print("INFO: TTS 비활성화 상태로 초기화를 건너뜁니다.")
                return

            tts_provider = str(self.settings.get("tts_provider", "gpt_sovits_http")).strip().lower()
            tts_provider_configs = self.settings.get("tts_provider_configs", {})
            if not isinstance(tts_provider_configs, dict):
                tts_provider_configs = {}

            provider_config = get_tts_provider_defaults(tts_provider)
            raw_provider_config = tts_provider_configs.get(tts_provider, {})
            if isinstance(raw_provider_config, dict):
                provider_config.update(raw_provider_config)

            tts_api_keys = self.settings.get("tts_api_keys", {})
            if not isinstance(tts_api_keys, dict):
                tts_api_keys = {}

            try:
                self.tts_client = create_tts_client(
                    tts_provider,
                    provider_config,
                    api_key=str(tts_api_keys.get(tts_provider, "")).strip(),
                )
            except ValueError:
                self.tts_client = None
                self.audio_player = None
                print(f"WARNING: 아직 지원하지 않는 TTS 공급자입니다: {tts_provider}")
                return
            
            # 오디오 플레이어 초기화
            self.audio_player = AudioPlayer()
            
            # TTS 사용 가능 여부 확인
            if self.tts_client.is_available():
                print(f"OK: TTS 클라이언트 초기화 성공 ({tts_provider})")
            else:
                print(f"WARNING: TTS 공급자 설정이 충분하지 않습니다. provider={tts_provider}")
                self.tts_client = None
                self.audio_player = None
            
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
            self.overlay_window.bridge.enable_tts = bool(self.settings.get("enable_tts", False))
            self.overlay_window.bridge.set_tts(
                self.tts_client if hasattr(self, "tts_client") else None,
                self.audio_player if hasattr(self, "audio_player") else None,
            )
    
    def _connect_signals(self):
        """시그널 연결"""
        # WebBridge에 LLM 클라이언트 및 메모리 매니저 전달
        self.overlay_window.bridge.set_llm_client(self.llm_client)
        if hasattr(self, "mood_manager") and self.mood_manager:
            self.overlay_window.bridge.set_mood_manager(self.mood_manager)
        if hasattr(self, 'memory_manager'):
            user_profile = self.user_profile if hasattr(self, 'user_profile') else None
            self.overlay_window.bridge.set_memory_manager(
                self.memory_manager,
                self.llm_client,
                user_profile
            )
        
        # TTS 클라이언트 및 오디오 플레이어 연결
        if hasattr(self, 'tts_client') and self.tts_client:
            self.overlay_window.bridge.set_tts(self.tts_client, self.audio_player)

        # 유휴 감지 모니터 시작
        self.overlay_window.bridge.start_away_monitor()
        QTimer.singleShot(0, self.overlay_window.bridge._schedule_checked_files_context_refresh)
        
        # 트레이 아이콘 시그널
        self.tray_icon.settings_requested.connect(self._show_settings_dialog)
        self.tray_icon.calendar_requested.connect(self._show_calendar_dialog)
        self.tray_icon.toggle_drag_bar_requested.connect(self._toggle_drag_bar)
        self.tray_icon.toggle_mouse_tracking_requested.connect(self._toggle_mouse_tracking)
        self.tray_icon.quit_requested.connect(self._quit_application)

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
    
    def _show_settings_dialog(self):
        """설정 다이얼로그 표시 (비모달)"""
        # 이미 열려있으면 포커스
        if hasattr(self, '_settings_dialog') and self._settings_dialog and self._settings_dialog.isVisible():
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
        
        # 비모달로 표시
        dialog.show()
    
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
        bridge = self.overlay_window.bridge if hasattr(self.overlay_window, 'bridge') else None
        dialog = MemoryDialog(self.memory_manager, bridge)
        dialog.exec()
    
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
                "tts_provider": str(self.settings.get("tts_provider", "gpt_sovits_http")).strip(),
                "tts_provider_configs": self.settings.get("tts_provider_configs", {}),
                "tts_api_keys": self.settings.get("tts_api_keys", {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        self.overlay_window.apply_new_settings(new_settings)
        self.interrupt_tts_on_ptt = bool(new_settings.get("interrupt_tts_on_ptt", True))
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.apply_settings(new_settings)

        new_embedding_provider = str(new_settings.get("embedding_provider", old_embedding_provider)).strip().lower()
        new_embedding_model = str(new_settings.get("embedding_model", old_embedding_model)).strip() or "voyage-3"
        if (old_embedding_provider, old_embedding_model) != (new_embedding_provider, new_embedding_model):
            self._refresh_memory_runtime_bindings()

        new_tts_config = json.dumps(
            {
                "enable_tts": bool(new_settings.get("enable_tts", self.settings.get("enable_tts", False))),
                "tts_provider": str(new_settings.get("tts_provider", self.settings.get("tts_provider", "gpt_sovits_http"))).strip(),
                "tts_provider_configs": new_settings.get("tts_provider_configs", self.settings.get("tts_provider_configs", {})),
                "tts_api_keys": new_settings.get("tts_api_keys", self.settings.get("tts_api_keys", {})),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if old_tts_config != new_tts_config:
            self._refresh_tts_runtime_bindings()

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

    def _on_settings_preview(self, new_settings: dict):
        """설정 미리보기 (settings 객체 수정 없이 화면에만 적용)"""
        self.overlay_window.preview_settings(new_settings)
        self.interrupt_tts_on_ptt = bool(new_settings.get("interrupt_tts_on_ptt", True))
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.apply_settings(new_settings)
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            self.overlay_window.bridge.enable_tts = bool(new_settings.get("enable_tts", self.settings.get("enable_tts", False)))

    def _on_settings_cancelled(self):
        """설정 취소 - 저장된 값으로 복원"""
        self.overlay_window.restore_settings()
        self.interrupt_tts_on_ptt = bool(self.settings.get("interrupt_tts_on_ptt", True))
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.apply_settings(self.settings.config)
        if hasattr(self, "overlay_window") and self.overlay_window and hasattr(self.overlay_window, "bridge"):
            self.overlay_window.bridge.enable_tts = bool(self.settings.get("enable_tts", False))
    
    def _toggle_drag_bar(self):
        """드래그 바 토글"""
        is_visible = self.overlay_window.toggle_drag_bar()
        self.tray_icon.update_drag_bar_menu_text(is_visible)
    
    def _toggle_mouse_tracking(self):
        """마우스 트래킹 토글"""
        is_enabled = self.overlay_window.toggle_mouse_tracking()
        self.tray_icon.update_mouse_tracking_menu_text(is_enabled)
    
    def _quit_application(self):
        """애플리케이션 종료"""
        print("애플리케이션 종료 중...")

        if hasattr(self, "system_theme_timer") and self.system_theme_timer:
            self.system_theme_timer.stop()
        
        # 종료 전 남은 대화 요약
        if hasattr(self, 'overlay_window') and hasattr(self.overlay_window, 'bridge'):
            bridge = self.overlay_window.bridge
            bridge.stop_away_monitor()
            
            # 남은 대화가 있으면 요약
            if bridge.conversation_buffer:
                print(f"남은 대화 {len(bridge.conversation_buffer)}개 요약 중...")
                
                try:
                    # clear_conversation이 자동으로 남은 대화를 요약함
                    bridge.clear_conversation()
                    print("요약 완료")
                except Exception as e:
                    print(f"종료 전 요약 실패: {e}")

        if hasattr(self, "_settings_dialog") and self._settings_dialog and self._settings_dialog.isVisible():
            self._settings_dialog.close()

        self.overlay_window.shutdown()
        self.overlay_window.close()
        if hasattr(self, "obsidian_panel_window") and self.obsidian_panel_window:
            self.obsidian_panel_window.close()
        if hasattr(self, "global_ptt") and self.global_ptt:
            self.global_ptt.shutdown()
        QApplication.quit()
