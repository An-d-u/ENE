"""첫 일반 채팅 앞에서 생활 기록 생성을 한 번만 판정한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Literal, Mapping

from ...ai.life_record_prompt import LifeMoodSnapshot, snapshot_life_mood
from ...ai.prompt_config import load_life_world_prompt
from ...ai.prompt_language import resolve_prompt_language
from ..bridge_state import LifeRecordBridgeState
from ..life_session_tracker import InactiveStartCandidate


_LANGUAGES = frozenset({"ko", "en", "ja"})
_NEUTRAL_MOOD = {
    "current_mood": "calm",
    "temporary_state": "steady",
    "valence": 0.0,
    "energy": 0.0,
    "bond": 0.0,
    "stress": 0.0,
}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {_thaw(item) for item in value}
    return value


@dataclass(frozen=True, repr=False)
class PreparedChatRequest:
    """생활 기록 판정 동안 보류할 사용자 주도 일반 요청의 불변 사본."""

    received_at: datetime
    language: Literal["ko", "en", "ja"]
    mood_snapshot: LifeMoodSnapshot
    request_type: Literal["text", "attachments"]
    message: str
    attachments: tuple[Mapping[str, Any], ...] = ()
    head_pat_count_before_message: int = 0
    prior_token_usage: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at_must_be_aware")
        object.__setattr__(self, "received_at", self.received_at.replace(microsecond=0))
        if self.language not in _LANGUAGES:
            raise ValueError("invalid_language")
        if self.request_type not in {"text", "attachments"}:
            raise ValueError("invalid_request_type")
        if type(self.message) is not str:
            raise ValueError("invalid_message")
        object.__setattr__(self, "attachments", _freeze(tuple(self.attachments)))
        if self.prior_token_usage is not None:
            object.__setattr__(self, "prior_token_usage", _freeze(self.prior_token_usage))
        count = self.head_pat_count_before_message
        if type(count) is not int or count < 0:
            raise ValueError("invalid_head_pat_count")

    def __repr__(self) -> str:
        return (
            "PreparedChatRequest("
            f"request_type={self.request_type!r}, "
            f"received_at={self.received_at.isoformat()!r}, "
            f"language={self.language!r}, "
            f"message_chars={len(self.message)}, "
            f"attachment_count={len(self.attachments)})"
        )

    def attachment_copies(self) -> list[dict[str, Any]]:
        """기존 첨부 파이프라인에 넘길 새 가변 사본을 만든다."""
        return [_thaw(item) for item in self.attachments]


class LifeRecordBridgeMixin:
    """생활 기록 gate와 공통 생성 작업 arbiter를 제공한다."""

    def _get_life_record_state(self) -> LifeRecordBridgeState:
        state = getattr(self, "life_record_state", None)
        if not isinstance(state, LifeRecordBridgeState):
            state = LifeRecordBridgeState()
            self.life_record_state = state
        return state

    def _life_operation_accepts_input(self) -> bool:
        return self._get_life_record_state().phase == "idle"

    def _capture_life_received_at(self) -> datetime:
        """slot 진입 시 Task 1B clock에서 정수 초 수신 시각을 잡는다."""
        state = self._get_life_record_state()
        context = state.time_context
        if context is not None:
            return context.canonicalize_endpoint(context.now())
        return datetime.now().astimezone().replace(microsecond=0)

    def _resolve_life_prompt_language(self) -> str:
        language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
        return language if language in _LANGUAGES else "ko"

    def _snapshot_life_mood(self) -> LifeMoodSnapshot:
        manager = getattr(self, "mood_manager", None)
        getter = getattr(manager, "get_snapshot", None)
        raw = getter() if callable(getter) else _NEUTRAL_MOOD
        canonical = {
            key: raw[key]
            for key in _NEUTRAL_MOOD
            if isinstance(raw, Mapping) and key in raw
        }
        if set(canonical) != set(_NEUTRAL_MOOD):
            canonical = dict(_NEUTRAL_MOOD)
        return snapshot_life_mood(canonical)

    def _prepare_chat_request(
        self,
        *,
        received_at: datetime,
        request_type: Literal["text", "attachments"],
        message: str,
        attachments: list[dict] | tuple[dict, ...] = (),
        head_pat_count_before_message: int = 0,
        prior_token_usage: Mapping[str, Any] | None = None,
    ) -> PreparedChatRequest:
        language = self._resolve_life_prompt_language()
        return PreparedChatRequest(
            received_at=received_at,
            language=language,
            mood_snapshot=self._snapshot_life_mood(),
            request_type=request_type,
            message=str(message or ""),
            attachments=tuple(attachments),
            head_pat_count_before_message=head_pat_count_before_message,
            prior_token_usage=prior_token_usage,
        )

    def _life_setting(self, key: str, default: Any) -> Any:
        settings = getattr(self, "settings", None)
        if isinstance(settings, Mapping):
            return settings.get(key, default)
        getter = getattr(settings, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except Exception:
                return default
        config = getattr(settings, "config", None)
        return config.get(key, default) if isinstance(config, Mapping) else default

    def _normalized_life_inactive_minutes(self) -> int:
        value = self._life_setting("life_record_min_inactive_minutes", 60)
        return value if type(value) is int and value >= 1 else 60

    def _load_life_world_for_gate(self) -> str:
        return load_life_world_prompt()

    def _emit_life_record_notice(self, code: str) -> None:
        signal = getattr(self, "life_record_notice", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(code)

    def _emit_life_record_stage(self, stage: str) -> None:
        emitter = getattr(self, "_emit_request_pending_stage_changed", None)
        if callable(emitter):
            emitter(stage)
            return
        signal = getattr(self, "request_pending_stage_changed", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(stage)

    def _emit_life_record_pending(self, active: bool) -> None:
        emitter = getattr(self, "_emit_request_pending_changed", None)
        if callable(emitter):
            emitter(active)
            return
        signal = getattr(self, "request_pending_changed", None)
        if signal is not None and hasattr(signal, "emit"):
            signal.emit(active)

    def _dispatch_general_request(self, prepared_request: PreparedChatRequest) -> bool:
        """필요하면 생활 기록을 먼저 시작하고 아니면 일반 요청을 commit한다."""
        state = self._get_life_record_state()
        if state.phase != "idle":
            return False
        cancel_proactive = getattr(
            self,
            "_cancel_pending_proactive_conversations_for_user_message",
            None,
        )
        if callable(cancel_proactive):
            cancel_proactive()
        mark_activity = getattr(self, "_mark_user_activity", None)
        if callable(mark_activity):
            mark_activity()
        if state.auto_decision_completed:
            self._commit_prepared_chat_request(prepared_request)
            return True

        state.auto_decision_completed = True
        if not state.life_records_writable:
            self._commit_prepared_chat_request(prepared_request)
            return True
        if self._life_setting("enable_life_records", False) is not True:
            self._commit_prepared_chat_request(prepared_request)
            return True
        threshold = self._normalized_life_inactive_minutes()
        candidate = state.candidate
        if not isinstance(candidate, InactiveStartCandidate):
            self._commit_prepared_chat_request(prepared_request)
            return True
        try:
            world = self._load_life_world_for_gate()
        except Exception:
            self._commit_prepared_chat_request(prepared_request)
            return True
        if not isinstance(world, str) or not world.strip():
            self._emit_life_record_notice("world_empty")
            self._commit_prepared_chat_request(prepared_request)
            return True
        context = state.time_context
        try:
            elapsed = context.elapsed_between(candidate.started_at, prepared_request.received_at)
        except Exception:
            self._commit_prepared_chat_request(prepared_request)
            return True
        if elapsed <= timedelta(0) or elapsed < timedelta(minutes=threshold):
            self._commit_prepared_chat_request(prepared_request)
            return True

        operation_id = state.try_begin_operation(
            "auto_generating",
            pending_request=prepared_request,
        )
        if operation_id is None:
            return False
        state.pending_world_markdown = world
        state.prior_token_usage = prepared_request.prior_token_usage
        self._emit_life_record_stage("life_record")
        self._emit_life_record_pending(True)
        starter = getattr(self, "_start_auto_life_record_generation", None)
        if callable(starter):
            starter(operation_id)
        return True

    def _start_auto_life_record_generation(self, _operation_id: int) -> None:
        """Task 10B의 실제 worker 구현을 위한 진입 seam."""
