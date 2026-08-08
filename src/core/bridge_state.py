"""
WebBridge의 런타임 상태를 도메인별 객체로 묶는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Literal

from .attachment_session import AttachmentSession
from .tts_sync_controller import TTSSyncController


@dataclass
class ObsidianBridgeState:
    """Obsidian 패널, 트리 워커, 체크 파일 캐시 상태."""

    panel_window: Any = None
    tree_worker: Any = None
    tree_retry_timer: Any = None
    tree_retry_remaining: int = 0
    cached_obs_tree_json: str = ""
    cached_checked_files_context: str = ""
    cached_checked_files_signature: tuple[str, ...] = field(default_factory=tuple)
    checked_files_worker: Any = None
    integration_activated: bool = False

    @classmethod
    def initial(cls, checked_files: list[str] | tuple[str, ...] | None = None) -> "ObsidianBridgeState":
        """체크된 파일 목록을 포함한 기본 트리 페이로드로 상태를 만든다."""
        normalized_checked = list(checked_files or [])
        return cls(
            cached_obs_tree_json=json.dumps(
                {"ok": True, "nodes": [], "checked_files": normalized_checked},
                ensure_ascii=False,
            )
        )


@dataclass
class TTSBridgeState:
    """TTS, 립싱크, 스트리밍 오디오 상태."""

    client: Any = None
    audio_player: Any = None
    enabled: bool = False
    worker: Any = None
    streaming_enabled: bool = False
    streaming_emit_message_on_first_chunk: bool = True
    streaming_started: bool = False
    stream_lip_sync_next_timestamp: float = 0.0
    stream_lip_sync_values: list[float] = field(default_factory=list)
    stream_lip_sync_timer: Any = None
    stream_lip_sync_finished: bool = False
    stream_audio_format: Any = None
    stream_audio_output_started: bool = False
    stream_sync_started_at: Any = None
    stream_pending_pcm_chunks: list[bytes] = field(default_factory=list)
    stream_pending_lip_sync_data: list[Any] = field(default_factory=list)
    stream_viseme_analyzer: Any = None
    sync_controller: TTSSyncController = field(default_factory=TTSSyncController)
    sync_started: bool = False
    sync_using_rms_fallback: bool = False
    stream_future_viseme_frames: list[Any] = field(default_factory=list)
    model_lip_sync_profile: Any = None
    model_lip_sync_profile_key: Any = None
    lip_sync_data: Any = None
    lip_sync_timer: Any = None
    lip_sync_start_time: Any = None
    lip_sync_index: int = 0
    pending_response: Any = None
    pending_token_usage_payload: str = ""
    interrupted_for_ptt: bool = False


@dataclass
class ChatBridgeState:
    """대화 버퍼와 최근 요청/응답 추적 상태."""

    conversation_buffer: list[tuple] = field(default_factory=list)
    ene_thought_context_buffer: list[dict] = field(default_factory=list)
    loaded_topic_memory_context_buffer: list[dict] = field(default_factory=list)
    last_request_payload: dict[str, Any] | None = None
    last_assistant_response: dict[str, Any] | None = None
    is_rerolling: bool = False


@dataclass
class PromiseBridgeState:
    """대화 약속 실행 큐와 현재 실행 중인 약속 상태."""

    manager: Any = None
    run_queue: list[dict[str, Any]] = field(default_factory=list)
    active_id: str | None = None
    active_signature: str | None = None
    recent_fire_signatures: dict[str, Any] = field(default_factory=dict)
    timer: Any = None


@dataclass
class ProactiveBridgeState:
    """선제 대화 실행 큐와 현재 실행 중인 예약 상태."""

    manager: Any = None
    run_queue: list[dict[str, Any]] = field(default_factory=list)
    active_id: str | None = None
    active_signature: str | None = None
    recent_fire_signatures: dict[str, Any] = field(default_factory=dict)
    timer: Any = None


@dataclass
class AwayBridgeState:
    """자리 비움 감지와 입력 유휴 상태."""

    last_user_message_at: Any = None
    user_message_count: int = 0
    check_in_progress: bool = False
    already_triggered_since_last_user_msg: bool = False
    trigger_count_since_last_user_msg: int = 0
    last_trigger_at: Any = None
    idle_minutes: int = 60
    input_grace_minutes: int = 5
    additional_retry_limit: int = 0
    enabled: bool = True
    timer: Any = None


@dataclass
class AttachmentBridgeState:
    """첨부 세션 상태 객체."""

    session: AttachmentSession = field(default_factory=AttachmentSession)


LifeRecordPhase = Literal[
    "idle",
    "auto_generating",
    "resuming_reply",
    "normal_reply",
    "manual_regenerating",
    "shutting_down",
]

_LIFE_RECORD_PHASES = frozenset(
    {
        "idle",
        "auto_generating",
        "resuming_reply",
        "normal_reply",
        "manual_regenerating",
        "shutting_down",
    }
)
_LIFE_RECORD_READ_ONLY_REASONS = frozenset(
    {
        "session_lease_unavailable",
        "timezone_unavailable",
        "session_tracker_degraded",
    }
)


@dataclass
class LifeRecordBridgeState:
    """생활 기록 생성과 일반 답변 사이의 단일 작업 상태."""

    candidate: Any = None
    auto_decision_completed: bool = False
    life_records_writable: bool = False
    read_only_reason: str | None = None
    time_context: Any = None
    view_timezone: str = "UTC"
    phase: LifeRecordPhase = "idle"
    operation_id: int = 0
    pending_request: Any = None
    pending_world_markdown: str = ""
    worker: Any = None
    worker_result: Any = None
    worker_error: Any = None
    prior_token_usage: Any = None

    def __post_init__(self) -> None:
        if (
            self.read_only_reason is not None
            and self.read_only_reason not in _LIFE_RECORD_READ_ONLY_REASONS
        ):
            raise ValueError("invalid_life_record_read_only_reason")
        if self.phase not in _LIFE_RECORD_PHASES:
            raise ValueError("invalid_life_record_phase")

    def try_begin_operation(
        self,
        phase: LifeRecordPhase,
        *,
        pending_request: Any = None,
    ) -> int | None:
        """idle에서만 새 작업을 시작하고 단조 증가 식별자를 돌려준다."""
        if phase not in _LIFE_RECORD_PHASES or phase in {"idle", "shutting_down"}:
            raise ValueError("invalid_life_record_phase")
        if self.phase != "idle":
            return None
        self.operation_id += 1
        self.phase = phase
        self.pending_request = pending_request
        return self.operation_id

    def matches_operation(self, operation_id: int, *phases: LifeRecordPhase) -> bool:
        """늦게 도착한 콜백이 현재 작업에 속하는지 확인한다."""
        return (
            type(operation_id) is int
            and operation_id == self.operation_id
            and self.phase != "idle"
            and self.phase != "shutting_down"
            and (not phases or self.phase in phases)
        )

    def take_pending(self, operation_id: int) -> Any:
        """현재 작업의 보류 요청을 정확히 한 번 꺼낸다."""
        if not self.matches_operation(operation_id):
            return None
        request = self.pending_request
        self.pending_request = None
        return request

    def transition_operation(
        self,
        operation_id: int,
        phase: LifeRecordPhase,
    ) -> bool:
        """현재 작업 식별자를 유지한 채 허용된 다음 phase로 전이한다."""
        if phase not in _LIFE_RECORD_PHASES or phase in {"idle", "shutting_down"}:
            raise ValueError("invalid_life_record_phase")
        if not self.matches_operation(operation_id):
            return False
        self.phase = phase
        return True

    def finish_operation(self, operation_id: int) -> bool:
        """현재 작업만 idle로 되돌리고 stale 종료는 무시한다."""
        if not self.matches_operation(operation_id):
            return False
        self.phase = "idle"
        self.pending_request = None
        self.pending_world_markdown = ""
        self.prior_token_usage = None
        self.worker = None
        self.worker_result = None
        self.worker_error = None
        return True

    def begin_shutdown(self) -> int:
        """작업 식별자를 무효화하고 terminal 종료 상태로 전이한다."""
        self.operation_id += 1
        self.phase = "shutting_down"
        self.pending_request = None
        self.pending_world_markdown = ""
        worker = self.worker
        request_interruption = getattr(worker, "requestInterruption", None)
        if callable(request_interruption):
            try:
                request_interruption()
            except Exception:
                pass
        self.worker_result = None
        self.worker_error = None
        return self.operation_id


BRIDGE_STATE_ALIASES = {
    "obs_panel_window": ("obsidian_state", "panel_window"),
    "obs_tree_worker": ("obsidian_state", "tree_worker"),
    "obs_tree_retry_timer": ("obsidian_state", "tree_retry_timer"),
    "_obs_tree_retry_remaining": ("obsidian_state", "tree_retry_remaining"),
    "_cached_obs_tree_json": ("obsidian_state", "cached_obs_tree_json"),
    "_cached_checked_files_context": ("obsidian_state", "cached_checked_files_context"),
    "_cached_checked_files_signature": ("obsidian_state", "cached_checked_files_signature"),
    "obs_checked_files_worker": ("obsidian_state", "checked_files_worker"),
    "_obsidian_integration_activated": ("obsidian_state", "integration_activated"),
    "tts_client": ("tts_state", "client"),
    "audio_player": ("tts_state", "audio_player"),
    "enable_tts": ("tts_state", "enabled"),
    "tts_worker": ("tts_state", "worker"),
    "tts_streaming_enabled": ("tts_state", "streaming_enabled"),
    "tts_streaming_emit_message_on_first_chunk": ("tts_state", "streaming_emit_message_on_first_chunk"),
    "_streaming_tts_started": ("tts_state", "streaming_started"),
    "_stream_lip_sync_next_timestamp": ("tts_state", "stream_lip_sync_next_timestamp"),
    "_stream_lip_sync_values": ("tts_state", "stream_lip_sync_values"),
    "_stream_lip_sync_timer": ("tts_state", "stream_lip_sync_timer"),
    "_stream_lip_sync_finished": ("tts_state", "stream_lip_sync_finished"),
    "_stream_audio_format": ("tts_state", "stream_audio_format"),
    "_stream_audio_output_started": ("tts_state", "stream_audio_output_started"),
    "_stream_sync_started_at": ("tts_state", "stream_sync_started_at"),
    "_stream_pending_pcm_chunks": ("tts_state", "stream_pending_pcm_chunks"),
    "_stream_pending_lip_sync_data": ("tts_state", "stream_pending_lip_sync_data"),
    "_stream_viseme_analyzer": ("tts_state", "stream_viseme_analyzer"),
    "_sync_controller": ("tts_state", "sync_controller"),
    "_sync_started": ("tts_state", "sync_started"),
    "_sync_using_rms_fallback": ("tts_state", "sync_using_rms_fallback"),
    "_stream_future_viseme_frames": ("tts_state", "stream_future_viseme_frames"),
    "_model_lip_sync_profile": ("tts_state", "model_lip_sync_profile"),
    "_model_lip_sync_profile_key": ("tts_state", "model_lip_sync_profile_key"),
    "lip_sync_data": ("tts_state", "lip_sync_data"),
    "lip_sync_timer": ("tts_state", "lip_sync_timer"),
    "lip_sync_start_time": ("tts_state", "lip_sync_start_time"),
    "lip_sync_index": ("tts_state", "lip_sync_index"),
    "pending_response": ("tts_state", "pending_response"),
    "pending_token_usage_payload": ("tts_state", "pending_token_usage_payload"),
    "_tts_interrupted_for_ptt": ("tts_state", "interrupted_for_ptt"),
    "conversation_buffer": ("chat_state", "conversation_buffer"),
    "_ene_thought_context_buffer": ("chat_state", "ene_thought_context_buffer"),
    "_loaded_topic_memory_context_buffer": ("chat_state", "loaded_topic_memory_context_buffer"),
    "_last_request_payload": ("chat_state", "last_request_payload"),
    "_last_assistant_response": ("chat_state", "last_assistant_response"),
    "_is_rerolling": ("chat_state", "is_rerolling"),
    "promise_manager": ("promise_state", "manager"),
    "promise_run_queue": ("promise_state", "run_queue"),
    "_active_promise_id": ("promise_state", "active_id"),
    "_active_promise_signature": ("promise_state", "active_signature"),
    "_recent_promise_fire_signatures": ("promise_state", "recent_fire_signatures"),
    "promise_timer": ("promise_state", "timer"),
    "proactive_manager": ("proactive_state", "manager"),
    "proactive_run_queue": ("proactive_state", "run_queue"),
    "_active_proactive_id": ("proactive_state", "active_id"),
    "_active_proactive_signature": ("proactive_state", "active_signature"),
    "_recent_proactive_fire_signatures": ("proactive_state", "recent_fire_signatures"),
    "proactive_timer": ("proactive_state", "timer"),
    "last_user_message_at": ("away_state", "last_user_message_at"),
    "user_message_count": ("away_state", "user_message_count"),
    "away_check_in_progress": ("away_state", "check_in_progress"),
    "away_already_triggered_since_last_user_msg": ("away_state", "already_triggered_since_last_user_msg"),
    "away_trigger_count_since_last_user_msg": ("away_state", "trigger_count_since_last_user_msg"),
    "last_away_trigger_at": ("away_state", "last_trigger_at"),
    "away_idle_minutes": ("away_state", "idle_minutes"),
    "away_input_grace_minutes": ("away_state", "input_grace_minutes"),
    "away_additional_retry_limit": ("away_state", "additional_retry_limit"),
    "enable_away_nudge": ("away_state", "enabled"),
    "away_timer": ("away_state", "timer"),
    "_attachment_session": ("attachment_state", "session"),
}


class BridgeStateAliasMixin:
    """기존 속성 접근을 도메인별 State 객체로 연결한다."""

    def _init_bridge_states(self, checked_files: list[str] | tuple[str, ...] | None = None) -> None:
        """WebBridge 초기화 초기에 모든 도메인 상태 객체를 만든다."""
        self.obsidian_state = ObsidianBridgeState.initial(checked_files)
        self.tts_state = TTSBridgeState()
        self.chat_state = ChatBridgeState()
        self.promise_state = PromiseBridgeState()
        self.proactive_state = ProactiveBridgeState()
        self.away_state = AwayBridgeState()
        self.attachment_state = AttachmentBridgeState()
        self.life_record_state = LifeRecordBridgeState()


def _make_state_alias(legacy_name: str, state_name: str, field_name: str) -> property:
    def _get(self):
        state = self.__dict__.get(state_name)
        if state is None:
            if legacy_name in self.__dict__:
                return self.__dict__[legacy_name]
            raise AttributeError(legacy_name)
        return getattr(state, field_name)

    def _set(self, value):
        state = self.__dict__.get(state_name)
        if state is None:
            self.__dict__[legacy_name] = value
            return
        setattr(state, field_name, value)

    return property(_get, _set)


for _legacy_name, (_state_name, _field_name) in BRIDGE_STATE_ALIASES.items():
    setattr(BridgeStateAliasMixin, _legacy_name, _make_state_alias(_legacy_name, _state_name, _field_name))
