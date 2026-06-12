"""
Python-JavaScript 브릿지 (QWebChannel)
"""
from PyQt6.QtCore import (
    QObject,
    pyqtSignal,
    pyqtSlot,
    QTimer,
)
from datetime import datetime

from ..ai.diary_service import DiaryService
from ..ai.note_service import NoteService
from ..ai.obsidian_manager import ObsidianManager
from ..ai.prompt_language import resolve_prompt_language
from .bridge_state import BridgeStateAliasMixin
from .bridge_workers import AIWorker  # 기존 import 경로 호환용 재노출
from .bridge_mixins.attachments import AttachmentBridgeMixin
from .bridge_mixins.away import AwayNudgeBridgeMixin
from .bridge_mixins.chat_flow import ChatFlowBridgeMixin
from .bridge_mixins.goals import GoalBridgeMixin
from .bridge_mixins.live2d_parameters import Live2DParameterBridgeMixin
from .bridge_mixins.memory_summary import MemorySummaryBridgeMixin
from .bridge_mixins.mood import MoodBridgeMixin
from .bridge_mixins.obsidian import ObsidianBridgeMixin
from .bridge_mixins.proactive import ProactiveBridgeMixin
from .bridge_mixins.promise import PromiseBridgeMixin
from .bridge_mixins.thoughts import ThoughtBridgeMixin
from .bridge_mixins.tts import TTSBridgeMixin
from .obs_settings import ObsSettings


def _prompt_time_header(timestamp: str, language: str) -> str:
    labels = {
        "ko": "현재 시각",
        "en": "Current Time",
        "ja": "現在時刻",
    }
    return f"[{labels.get(language, labels['ko'])}: {timestamp}]"


class WebBridge(
    AwayNudgeBridgeMixin,
    AttachmentBridgeMixin,
    Live2DParameterBridgeMixin,
    ChatFlowBridgeMixin,
    GoalBridgeMixin,
    MoodBridgeMixin,
    ObsidianBridgeMixin,
    MemorySummaryBridgeMixin,
    PromiseBridgeMixin,
    ProactiveBridgeMixin,
    ThoughtBridgeMixin,
    TTSBridgeMixin,
    BridgeStateAliasMixin,
    QObject,
):
    """Python과 JavaScript 간 통신 브릿지"""
    
    # Python -> JavaScript 시그널
    message_received = pyqtSignal(str, str, str)  # (텍스트, 감정, 생각)
    request_pending_changed = pyqtSignal(bool)  # LLM 응답 생성 진행 상태
    expression_changed = pyqtSignal(str)     # 표정 변경
    lip_sync_update = pyqtSignal(float)      # 립싱크 업데이트 (mouth_value)
    mouth_pose_update = pyqtSignal(str)      # 모델 적응형 입모양 JSON
    reroll_state_changed = pyqtSignal(bool)  # 리롤 응답 교체 모드 on/off
    summary_notice = pyqtSignal(str, str)    # (메시지, 레벨)
    summary_review_ready = pyqtSignal(str)   # 요약 검토 payload JSON
    summary_review_saved = pyqtSignal()      # 요약 검토 저장 완료
    mood_changed = pyqtSignal(str, float, float, float, float, str)  # (라벨, valence, energy, bond, stress, 단기 분위기)
    obs_tree_updated = pyqtSignal(str)       # Obsidian 트리 JSON
    attachment_preview_ready = pyqtSignal(str)  # 첨부 프리뷰 메타데이터 JSON
    token_usage_ready = pyqtSignal(str)  # 토큰 사용량 JSON
    promise_notice = pyqtSignal(str, str)  # (메시지, 레벨)
    promise_items_updated = pyqtSignal(str)  # 예정 목록 JSON
    proactive_items_updated = pyqtSignal(str)  # 선제 대화 예약 목록 JSON
    goal_items_updated = pyqtSignal(str)  # 목표 목록 JSON
    goal_notice = pyqtSignal(str, str)  # (메시지, 레벨)
    
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.llm_client = None
        self.memory_manager = None
        self.worker = None
        self.settings = settings
        self.mood_manager = None
        self.goal_manager = None
        self.diary_service = DiaryService("diary", settings=settings)
        self.note_service = NoteService("note_runs", settings=self.settings)
        self.obs_settings = ObsSettings("obs_config.json")
        self.obsidian_manager = ObsidianManager(settings=self.settings, obs_settings=self.obs_settings)
        self._settings_dialog_opener = None
        self._init_bridge_states(checked_files=self.obs_settings.get_checked_files())
        self.obs_tree_retry_timer = QTimer(self)
        self.obs_tree_retry_timer.setSingleShot(True)
        self.obs_tree_retry_timer.timeout.connect(self._retry_obs_tree_refresh)
        self._sync_attachment_session_aliases()
        
        self.promise_timer = QTimer(self)
        self.promise_timer.setInterval(10_000)
        self.promise_timer.timeout.connect(self._poll_promise_reminders)
        self.promise_timer.start()

        self.proactive_timer = QTimer(self)
        self.proactive_timer.setInterval(10_000)
        self.proactive_timer.timeout.connect(self._poll_proactive_conversations)
        self.proactive_timer.start()

        self.away_timer = QTimer(self)
        self.away_timer.setInterval(10_000)
        self.away_timer.timeout.connect(self._check_away_nudge_condition)
        
        # 설정에서 임계값 로드 (기본값: 10)
        if settings and hasattr(settings, 'config'):
            self.summarize_threshold = max(0, int(settings.config.get('summarize_threshold', 10) or 0))
            self.enable_tts = settings.config.get('enable_tts', False)
            self.tts_streaming_enabled = bool(settings.config.get("tts_streaming_enabled", False))
            self.tts_streaming_emit_message_on_first_chunk = bool(
                settings.config.get("tts_streaming_emit_message_on_first_chunk", True)
            )
        else:
            self.summarize_threshold = 10

        self.refresh_away_settings()
        
        threshold_label = "무제한" if self.summarize_threshold == 0 else f"{self.summarize_threshold}개"
        print(f"[Bridge] 자동 요약 임계값: {threshold_label}")
        print(f"[Bridge] TTS 활성화: {self.enable_tts}")

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=self.settings)

    def _with_prompt_time(self, timestamp: str, prompt: str) -> str:
        return f"{_prompt_time_header(timestamp, self._prompt_language())}\n{prompt}"
    
    def set_llm_client(self, client):
        """LLM 클라이언트 설정"""
        self.llm_client = client
        if self.llm_client and self.mood_manager:
            self.llm_client.mood_manager = self.mood_manager
        if self.llm_client and self.goal_manager:
            self.llm_client.goal_manager = self.goal_manager
        print(f"[Bridge] LLM client set: {client is not None}")


    def _reset_pending_ui_state(self, notice: str | None = None):
        """
        프런트가 로딩 상태로 고정되지 않도록 pending UI 상태를 강제로 해제한다.
        주로 reroll/edit 조기 종료 경로에서 사용한다.
        """
        self._is_rerolling = False
        signal = getattr(self, "request_pending_changed", None)
        if signal and hasattr(signal, "emit"):
            signal.emit(False)
        self.reroll_state_changed.emit(False)
        if notice:
            self.summary_notice.emit(notice, "info")
    
    def set_memory_manager(self, memory_manager, _llm_client, user_profile=None, ene_profile=None):
        """메모리 매니저 및 사용자/에네 프로필 설정"""
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        print(f"[Bridge] Memory manager set: {memory_manager is not None}")
        print(f"[Bridge] User profile set: {user_profile is not None}")
        print(f"[Bridge] ENE profile set: {ene_profile is not None}")
    
    def set_tts(self, tts_client, audio_player):
        """TTS 클라이언트 및 오디오 플레이어 설정"""
        self.tts_client = tts_client
        self.audio_player = audio_player
        print(f"[Bridge] TTS client set: {tts_client is not None}")
        print(f"[Bridge] Audio player set: {audio_player is not None}")


    def set_settings_dialog_opener(self, opener):
        """설정창을 여는 콜백을 등록한다."""
        self._settings_dialog_opener = opener if callable(opener) else None


    def _now_timestamp(self) -> str:
        """일관된 형식의 현재 시각 문자열을 반환한다."""
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _append_conversation(self, role: str, message: str, timestamp: str | None = None):
        """인메모리 대화 버퍼에 한 턴을 추가한다."""
        self.conversation_buffer.append((role, message, timestamp or self._now_timestamp()))


    @pyqtSlot()
    def open_settings_dialog(self):
        """JS에서 호출: 기존 설정창을 연다."""
        if callable(self._settings_dialog_opener):
            self._settings_dialog_opener()

    @pyqtSlot(str)
    def save_chat_panel_height(self, height: str):
        """JS에서 호출: 채팅 패널 높이를 설정에 저장한다."""
        if not self.settings:
            return

        try:
            numeric_height = int(float(str(height or "0").strip()))
        except Exception:
            numeric_height = 0

        numeric_height = max(0, min(numeric_height, 4096))

        try:
            self.settings.set("chat_panel_height", numeric_height)
            self.settings.save()
        except Exception as e:
            print(f"[Bridge] chat panel height save failed: {e}")

    @pyqtSlot(str)
    def log_from_js(self, message: str):
        """JavaScript에서 로그 받기"""
        print(f"[JS] {message}")
