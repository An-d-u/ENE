"""
WebBridge의 런타임 상태를 도메인별 객체로 묶는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

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
    "_last_request_payload": ("chat_state", "last_request_payload"),
    "_last_assistant_response": ("chat_state", "last_assistant_response"),
    "_is_rerolling": ("chat_state", "is_rerolling"),
    "promise_manager": ("promise_state", "manager"),
    "promise_run_queue": ("promise_state", "run_queue"),
    "_active_promise_id": ("promise_state", "active_id"),
    "_active_promise_signature": ("promise_state", "active_signature"),
    "_recent_promise_fire_signatures": ("promise_state", "recent_fire_signatures"),
    "promise_timer": ("promise_state", "timer"),
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
        self.away_state = AwayBridgeState()
        self.attachment_state = AttachmentBridgeState()


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
