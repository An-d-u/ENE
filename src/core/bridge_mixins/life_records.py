"""첫 일반 채팅 앞에서 생활 기록 생성을 한 번만 판정한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping
from zoneinfo import ZoneInfo

from PyQt6.QtCore import QTimer, pyqtSlot

from ...ai.life_record_manager import LifeRecordManager, LifeRecordStoreError

from ...ai.life_record_prompt import (
    LifeMoodSnapshot,
    LifeRecordGenerationContext,
    build_life_record_prompt,
    snapshot_life_mood,
)
from ...ai.life_record_types import (
    LifeRecord,
    create_life_record,
    life_record_to_dict,
    stable_life_record_id,
)
from ...ai.persona_names import resolve_prompt_persona_names
from ...ai.prompt_config import load_life_world_prompt
from ...ai.prompt_language import resolve_prompt_language
from ..bridge_workers import (
    LifeRecordGenerationRequest,
    LifeRecordWorker,
    LifeRecordWorkerResult,
)
from ..bridge_state import LifeRecordBridgeState
from ..life_session_tracker import InactiveStartCandidate
from ..local_time import resolve_local_time_context


_LANGUAGES = frozenset({"ko", "en", "ja"})
_PUBLIC_READ_ONLY_REASONS = frozenset(
    {
        "session_lease_unavailable",
        "timezone_unavailable",
        "session_tracker_degraded",
    }
)
_NEUTRAL_MOOD = {
    "current_mood": "calm",
    "temporary_state": "steady",
    "valence": 0.0,
    "energy": 0.0,
    "bond": 0.0,
    "stress": 0.0,
}


def _public_read_only_reason(value: object) -> str | None:
    """외부 signal/payload에 노출 가능한 안정 사유 코드만 반환한다."""
    return value if type(value) is str and value in _PUBLIC_READ_ONLY_REASONS else None


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
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
            object.__setattr__(
                self, "prior_token_usage", _freeze(self.prior_token_usage)
            )
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


@dataclass(frozen=True, repr=False)
class ManualLifeRecordRegeneration:
    """수동 재생성 시작 시 고정한 대상과 실행 시점 정보."""

    record: LifeRecord
    language: Literal["ko", "en", "ja"]
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.record, LifeRecord):
            raise ValueError("invalid_regeneration_record")
        if self.language not in _LANGUAGES:
            raise ValueError("invalid_language")
        value = self.updated_at
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.microsecond != 0
        ):
            raise ValueError("invalid_updated_at")

    def __repr__(self) -> str:
        return (
            "ManualLifeRecordRegeneration("
            f"record_id={self.record.id!r}, "
            f"language={self.language!r}, "
            f"updated_at={self.updated_at.isoformat()!r})"
        )


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
        language = resolve_prompt_language(
            settings_source=getattr(self, "settings", None)
        )
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

        def accept_user_request() -> None:
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

        def commit_normal_reply() -> bool:
            operation_id = state.try_begin_operation(
                "normal_reply",
                pending_request=prepared_request,
            )
            if operation_id is None:
                return False
            accept_user_request()
            state.take_pending(operation_id)
            try:
                self._commit_prepared_chat_request(prepared_request)
            except Exception:
                state.finish_operation(operation_id)
                raise
            worker = getattr(self, "worker", None)
            is_running = getattr(worker, "isRunning", None)
            if state.matches_operation(operation_id, "normal_reply") and not (
                callable(is_running) and is_running()
            ):
                state.finish_operation(operation_id)
            return True

        if state.auto_decision_completed:
            return commit_normal_reply()

        state.auto_decision_completed = True
        if not state.life_records_writable:
            return commit_normal_reply()
        if self._life_setting("enable_life_records", False) is not True:
            return commit_normal_reply()
        threshold = self._normalized_life_inactive_minutes()
        candidate = state.candidate
        if not isinstance(candidate, InactiveStartCandidate):
            return commit_normal_reply()
        try:
            world = self._load_life_world_for_gate()
        except Exception:
            return commit_normal_reply()
        if not isinstance(world, str) or not world.strip():
            self._emit_life_record_notice("world_empty")
            return commit_normal_reply()
        context = state.time_context
        try:
            elapsed = context.elapsed_between(
                candidate.started_at, prepared_request.received_at
            )
        except Exception:
            return commit_normal_reply()
        if elapsed <= timedelta(0) or elapsed < timedelta(minutes=threshold):
            return commit_normal_reply()

        operation_id = state.try_begin_operation(
            "auto_generating",
            pending_request=prepared_request,
        )
        if operation_id is None:
            return False
        accept_user_request()
        state.pending_world_markdown = world
        state.prior_token_usage = prepared_request.prior_token_usage
        self._emit_life_record_stage("life_record")
        self._emit_life_record_pending(True)
        starter = getattr(self, "_start_auto_life_record_generation", None)
        if callable(starter):
            starter(operation_id)
        return True

    def _start_auto_life_record_generation(self, _operation_id: int) -> None:
        """확정된 snapshot만으로 자동 생활 기록 worker를 시작한다."""
        operation_id = _operation_id
        state = self._get_life_record_state()
        if not state.matches_operation(operation_id, "auto_generating"):
            return
        prepared = state.pending_request
        candidate = state.candidate
        if not isinstance(prepared, PreparedChatRequest) or not isinstance(
            candidate, InactiveStartCandidate
        ):
            self._fail_life_record_before_worker(operation_id)
            return

        try:
            manager = self._life_record_manager()
            previous = manager.latest() if manager is not None else None
            profile = self._life_profile_snapshot()
            names = resolve_prompt_persona_names(
                settings_source=getattr(self, "settings", None),
                language=prepared.language,
            )
            context = LifeRecordGenerationContext(
                inactive_started_at=candidate.started_at,
                returned_at=prepared.received_at,
                timezone=state.time_context.timezone_name,
                inactive_start_source=candidate.source,
                world_markdown=state.pending_world_markdown,
                ene_identity=profile["ene_identity"],
                relationship_tone=profile["relationship_tone"],
                profile_facts=profile["profile_facts"],
                display_names={"assistant": names.assistant, "user": names.user},
                previous_record=(
                    life_record_to_dict(previous) if previous is not None else None
                ),
                mood_snapshot=prepared.mood_snapshot,
                language=prepared.language,
            )
            request = LifeRecordGenerationRequest(
                operation_id=operation_id,
                prompt=build_life_record_prompt(context),
                inactive_started_at=candidate.started_at,
                returned_at=prepared.received_at,
                timezone=state.time_context.timezone_name,
                language=prepared.language,
            )
            worker = LifeRecordWorker(self.llm_client, request)
            state.worker = worker
            worker.result_ready.connect(self._stash_life_record_result)
            worker.error_occurred.connect(self._stash_life_record_error)
            worker.finished.connect(
                lambda op=operation_id, owned_worker=worker: (
                    self._on_life_record_worker_finished(op, owned_worker)
                )
            )
            worker.start()
        except Exception:
            self._fail_life_record_before_worker(operation_id)

    def _life_record_manager(self):
        manager = getattr(self, "life_record_manager", None)
        if manager is None:
            manager = getattr(
                getattr(self, "llm_client", None), "life_record_manager", None
            )
        return manager

    def _install_authoritative_life_record_manager(
        self,
        manager: LifeRecordManager,
    ) -> None:
        """권위 파일을 다시 읽은 manager를 모든 런타임 소비자에 연결한다."""
        self.life_record_manager = manager
        client = getattr(self, "llm_client", None)
        if client is not None:
            try:
                client.life_record_manager = manager
            except Exception:
                pass

    def _reload_authoritative_life_record_manager(self) -> LifeRecordManager:
        manager = self._life_record_manager()
        store_path = getattr(manager, "store_path", None)
        if store_path is None:
            raise LifeRecordStoreError("read_error")
        authoritative = LifeRecordManager(store_path)
        if authoritative.store_status == "read_error":
            raise LifeRecordStoreError("read_error")
        return authoritative

    @pyqtSlot(str, str)
    def request_life_records_for_date(
        self,
        iso_date: str,
        request_id: str,
    ) -> None:
        """현재 표시 timezone의 날짜와 겹치는 공개 기록만 전달한다."""
        try:
            if (
                type(iso_date) is not str
                or len(iso_date) != 10
                or date.fromisoformat(iso_date).isoformat() != iso_date
            ):
                raise ValueError("invalid_date")
            requested_date = date.fromisoformat(iso_date)
        except (TypeError, ValueError):
            self._emit_life_record_notice("invalid_date")
            return

        state = self._get_life_record_state()
        language = self._resolve_life_prompt_language()
        try:
            manager = self._reload_authoritative_life_record_manager()
            records = manager.records_overlapping_date(
                requested_date,
                state.view_timezone,
            )
            public_records = [
                manager.to_public_dict(record, state.view_timezone, language)
                for record in records
            ]
        except LifeRecordStoreError as failure:
            code = failure.code if failure.code in {"read_error", "invalid_view_timezone"} else "read_error"
            self._emit_life_record_notice(code)
            return
        except Exception:
            self._emit_life_record_notice("read_error")
            return

        self._install_authoritative_life_record_manager(manager)
        payload = json.dumps(
            {
                "status": "ready",
                "requested_date": iso_date,
                "request_id": request_id if type(request_id) is str else "",
                "view_timezone": state.view_timezone,
                "language": language,
                "records": public_records,
                "latest_id": manager.latest().id if manager.latest() is not None else None,
                "life_records_writable": state.life_records_writable is True,
                "read_only_reason": _public_read_only_reason(state.read_only_reason),
            },
            ensure_ascii=False,
        )
        signal = getattr(self, "life_record_items_updated", None)
        if signal is not None and hasattr(signal, "emit"):
            try:
                signal.emit(payload)
            except Exception:
                pass

    @pyqtSlot(str)
    def regenerate_latest_life_record(self, record_id: str) -> None:
        """현재 전역 최신 기록만 별도 호출로 다시 만들기 시작한다."""
        state = self._get_life_record_state()
        if state.phase != "idle":
            self._emit_life_record_notice("busy")
            return
        if not state.life_records_writable:
            self._emit_life_record_notice(
                _public_read_only_reason(state.read_only_reason) or "read_only"
            )
            return
        if state.time_context is None:
            self._emit_life_record_notice("timezone_unavailable")
            return
        try:
            manager = self._reload_authoritative_life_record_manager()
        except LifeRecordStoreError:
            self._emit_life_record_notice("read_error")
            return
        latest = manager.latest()
        if latest is None:
            self._emit_life_record_notice("not_found")
            return
        if type(record_id) is not str or record_id != latest.id:
            self._emit_life_record_notice("not_latest")
            return
        self._install_authoritative_life_record_manager(manager)
        try:
            world = self._load_life_world_for_gate()
        except Exception:
            self._emit_life_record_notice("world_unavailable")
            return
        if type(world) is not str or not world.strip():
            self._emit_life_record_notice("world_empty")
            return
        language = self._resolve_life_prompt_language()
        try:
            now = state.time_context.canonicalize_endpoint(state.time_context.now())
            record_zone = ZoneInfo(latest.timezone)
            updated_at = now.astimezone(record_zone)
            if updated_at.astimezone(timezone.utc) <= latest.updated_at.astimezone(timezone.utc):
                updated_at = (
                    latest.updated_at.astimezone(timezone.utc) + timedelta(seconds=1)
                ).astimezone(record_zone)
            pending = ManualLifeRecordRegeneration(
                record=latest,
                language=language,
                updated_at=updated_at,
            )
        except Exception:
            self._emit_life_record_notice("timezone_unavailable")
            return
        operation_id = state.try_begin_operation(
            "manual_regenerating",
            pending_request=pending,
        )
        if operation_id is None:
            self._emit_life_record_notice("busy")
            return
        state.pending_world_markdown = world
        try:
            self._emit_life_record_stage("life_record_regeneration")
            self._emit_life_record_pending(True)
            self._start_manual_life_record_regeneration(operation_id)
        except Exception:
            self._finish_life_record_without_reply(operation_id)
            try:
                self._emit_life_record_notice("generation_failed")
            except Exception:
                pass

    def _start_manual_life_record_regeneration(self, operation_id: int) -> None:
        state = self._get_life_record_state()
        if not state.matches_operation(operation_id, "manual_regenerating"):
            return
        pending = state.pending_request
        if not isinstance(pending, ManualLifeRecordRegeneration):
            self._fail_life_record_before_worker(operation_id)
            return
        target = pending.record
        try:
            profile = self._life_profile_snapshot()
            names = resolve_prompt_persona_names(
                settings_source=getattr(self, "settings", None),
                language=pending.language,
            )
            mood = target.mood_snapshot
            context = LifeRecordGenerationContext(
                inactive_started_at=target.inactive_started_at,
                returned_at=target.returned_at,
                timezone=target.timezone,
                inactive_start_source=target.inactive_start_source,
                world_markdown=state.pending_world_markdown,
                ene_identity=profile["ene_identity"],
                relationship_tone=profile["relationship_tone"],
                profile_facts=profile["profile_facts"],
                display_names={"assistant": names.assistant, "user": names.user},
                previous_record=None,
                mood_snapshot=LifeMoodSnapshot(
                    label=mood["label"],
                    valence=mood["valence"],
                    energy=mood["energy"],
                    bond=mood["bond"],
                    stress=mood["stress"],
                    short_term_mood=mood["short_term_mood"],
                ),
                language=pending.language,
            )
            request = LifeRecordGenerationRequest(
                operation_id=operation_id,
                prompt=build_life_record_prompt(context),
                inactive_started_at=target.inactive_started_at,
                returned_at=target.returned_at,
                timezone=target.timezone,
                language=pending.language,
            )
            worker = LifeRecordWorker(self.llm_client, request)
            state.worker = worker
            worker.result_ready.connect(self._stash_life_record_result)
            worker.error_occurred.connect(self._stash_life_record_error)
            worker.finished.connect(
                lambda op=operation_id, owned_worker=worker: (
                    self._on_life_record_worker_finished(op, owned_worker)
                )
            )
            worker.start()
        except Exception:
            self._fail_life_record_before_worker(operation_id)

    def _life_profile_snapshot(self) -> dict[str, object]:
        profile = getattr(self, "ene_profile", None)
        exporter = getattr(profile, "export_life_record_profile", None)
        if not callable(exporter):
            return {
                "ene_identity": {"identity": ()},
                "relationship_tone": (),
                "profile_facts": (),
            }
        raw_limit = self._life_setting("max_profile_facts_in_context", 10)
        try:
            limit = max(0, int(raw_limit))
        except (TypeError, ValueError, OverflowError):
            limit = 10
        exported = exporter(max_facts=limit)
        if not isinstance(exported, Mapping):
            raise ValueError("invalid_life_profile")
        return {
            "ene_identity": exported.get("ene_identity", {"identity": ()}),
            "relationship_tone": exported.get("relationship_tone", ()),
            "profile_facts": tuple(exported.get("profile_facts", ())),
        }

    def _fail_life_record_before_worker(self, operation_id: int) -> None:
        state = self._get_life_record_state()
        if not state.matches_operation(
            operation_id,
            "auto_generating",
            "manual_regenerating",
        ):
            return
        state.worker_error = "generation_failed"
        state.worker = None
        if state.phase == "manual_regenerating":
            self._finalize_manual_life_record_regeneration(operation_id)
        else:
            self._finalize_life_record_operation(operation_id)

    def _stash_life_record_result(self, operation_id: int, result: object) -> None:
        state = self._get_life_record_state()
        if not state.matches_operation(
            operation_id,
            "auto_generating",
            "manual_regenerating",
        ):
            return
        if state.worker_result is not None or state.worker_error is not None:
            return
        if (
            not isinstance(result, LifeRecordWorkerResult)
            or result.operation_id != operation_id
        ):
            state.worker_error = "generation_failed"
            return
        state.worker_result = result

    def _stash_life_record_error(self, operation_id: int, result: object) -> None:
        state = self._get_life_record_state()
        if not state.matches_operation(
            operation_id,
            "auto_generating",
            "manual_regenerating",
        ):
            return
        if (
            isinstance(result, LifeRecordWorkerResult)
            and result.operation_id != operation_id
        ):
            result = "generation_failed"
        if state.worker_result is None and state.worker_error is None:
            state.worker_error = result

    def _on_life_record_worker_finished(
        self, operation_id: int, worker: object
    ) -> None:
        state = self._get_life_record_state()
        if state.worker is not worker:
            return
        if not state.matches_operation(
            operation_id,
            "auto_generating",
            "manual_regenerating",
        ):
            if state.phase == "shutting_down":
                state.worker = None
            return
        self._defer_life_record_worker_finalization(
            lambda: self._finalize_deferred_life_record_worker(operation_id, worker)
        )

    def _defer_life_record_worker_finalization(self, callback) -> None:
        """같은 이벤트 큐에 대기 중인 결과 신호가 먼저 처리될 기회를 준다."""
        QTimer.singleShot(0, callback)

    def _finalize_deferred_life_record_worker(
        self,
        operation_id: int,
        worker: object,
    ) -> None:
        state = self._get_life_record_state()
        if state.worker is not worker:
            return
        if not state.matches_operation(
            operation_id,
            "auto_generating",
            "manual_regenerating",
        ):
            if state.phase == "shutting_down":
                state.worker = None
            return
        if state.worker_result is None and state.worker_error is None:
            interrupted = getattr(worker, "isInterruptionRequested", None)
            state.worker_error = (
                "cancelled"
                if callable(interrupted) and interrupted()
                else "generation_failed"
            )
        state.worker = None
        if state.phase == "manual_regenerating":
            self._finalize_manual_life_record_regeneration(operation_id)
        else:
            self._finalize_life_record_operation(operation_id)

    def _finalize_manual_life_record_regeneration(self, operation_id: int) -> None:
        state = self._get_life_record_state()
        if not state.matches_operation(operation_id, "manual_regenerating"):
            return
        pending = state.pending_request
        result = state.worker_result
        error = state.worker_error
        state.worker_result = None
        state.worker_error = None
        notice = "generation_failed"
        success = (
            isinstance(pending, ManualLifeRecordRegeneration)
            and isinstance(result, LifeRecordWorkerResult)
            and result.output is not None
            and error is None
        )
        if success:
            try:
                manager = self._reload_authoritative_life_record_manager()
                replacement = manager.replace_latest_if_unchanged(
                    pending.record,
                    result.output,
                    pending.updated_at,
                )
            except Exception:
                success = False
                notice = "save_failed"
            else:
                refresh_succeeded = True
                try:
                    self._install_authoritative_life_record_manager(manager)
                    refresh_succeeded = self._emit_saved_life_record(
                        replacement,
                        locale=pending.language,
                        manager=manager,
                    )
                except Exception:
                    refresh_succeeded = False
                if not refresh_succeeded:
                    try:
                        self._emit_life_record_notice("refresh_failed")
                    except Exception:
                        pass
        elif error == "cancelled":
            notice = "cancelled"
        if not success:
            try:
                self._emit_life_record_notice(notice)
            except Exception:
                pass
        self._finish_life_record_without_reply(operation_id)

    @staticmethod
    def _life_usage_dict(
        result: LifeRecordWorkerResult | None,
    ) -> dict[str, int | None]:
        usage = result.token_usage if result is not None else None
        return {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }

    def _finalize_life_record_operation(self, operation_id: int) -> None:
        state = self._get_life_record_state()
        if not state.matches_operation(operation_id, "auto_generating"):
            return
        result = state.worker_result
        error = state.worker_error
        state.worker_result = None
        state.worker_error = None
        success = (
            isinstance(result, LifeRecordWorkerResult)
            and result.output is not None
            and error is None
        )
        notice = "generation_failed"
        if success:
            try:
                saved = self._save_generated_life_record(result)
            except Exception:
                success = False
                notice = "save_failed"
            else:
                if not self._emit_saved_life_record(saved):
                    try:
                        self._emit_life_record_notice("refresh_failed")
                    except Exception:
                        pass
        if not success:
            try:
                self._emit_life_record_notice(notice)
            except Exception:
                pass

        if isinstance(result, LifeRecordWorkerResult):
            state.prior_token_usage = self._merge_life_token_usage(
                state.prior_token_usage,
                self._life_usage_dict(result),
            )
        pending = state.take_pending(operation_id)
        if not isinstance(pending, PreparedChatRequest):
            self._finish_life_record_without_reply(operation_id)
            return
        if not state.transition_operation(operation_id, "resuming_reply"):
            return
        try:
            self._emit_life_record_stage("thinking")
        except Exception:
            pass
        try:
            self._commit_prepared_chat_request(pending, emit_pending_state=False)
        except Exception:
            self._finish_life_record_without_reply(operation_id)

    @staticmethod
    def _merge_life_token_usage(*usages: object) -> dict[str, int | None] | None:
        from ...ai.response_protocol import TurnTokenUsageAccumulator

        accumulator = TurnTokenUsageAccumulator()
        recorded = False
        for usage in usages:
            if isinstance(usage, Mapping):
                accumulator.record(dict(usage))
                recorded = True
        return accumulator.snapshot() if recorded else None

    def _save_generated_life_record(self, result: LifeRecordWorkerResult):
        state = self._get_life_record_state()
        prepared = state.pending_request
        candidate = state.candidate
        manager = self._life_record_manager()
        if (
            manager is None
            or not isinstance(prepared, PreparedChatRequest)
            or not isinstance(candidate, InactiveStartCandidate)
        ):
            raise RuntimeError("save_unavailable")
        created_at = prepared.received_at
        output = result.output
        record = create_life_record(
            id=stable_life_record_id(candidate.started_at, prepared.received_at),
            inactive_started_at=candidate.started_at,
            returned_at=prepared.received_at,
            created_at=created_at,
            updated_at=created_at,
            revision=1,
            timezone=state.time_context.timezone_name,
            inactive_start_source=candidate.source,
            mood_snapshot={
                "label": prepared.mood_snapshot.label,
                "valence": prepared.mood_snapshot.valence,
                "energy": prepared.mood_snapshot.energy,
                "bond": prepared.mood_snapshot.bond,
                "stress": prepared.mood_snapshot.stress,
                "short_term_mood": prepared.mood_snapshot.short_term_mood,
            },
            entries=[
                {
                    "started_at": entry.started_at,
                    "ended_at": entry.ended_at,
                    "place": entry.place,
                    "activity": entry.activity,
                }
                for entry in output.entries
            ],
            ending_state={
                "place": output.ending_state.place,
                "summary": output.ending_state.summary,
            },
        )
        if manager.add(record) is not True:
            raise RuntimeError("save_rejected")
        authoritative = manager.latest()
        if authoritative is None or authoritative.id != record.id:
            raise RuntimeError("save_not_authoritative")
        return authoritative

    def _emit_saved_life_record(
        self,
        record: object,
        *,
        locale: str | None = None,
        manager: LifeRecordManager | None = None,
    ) -> bool:
        try:
            manager = manager or self._life_record_manager()
            state = self._get_life_record_state()
            locale = locale or self._resolve_life_prompt_language()
            public = manager.to_public_dict(record, state.view_timezone, locale)
            view_resolution = resolve_local_time_context(state.view_timezone)
            if view_resolution.context is None:
                return False
            zone = view_resolution.view_timezone
            local_start = record.inactive_started_at.astimezone(zone).date()
            local_last = (
                record.returned_at.astimezone(zone) - timedelta(microseconds=1)
            ).date()
            affected = []
            current = local_start
            while current <= local_last:
                affected.append(current.isoformat())
                current += timedelta(days=1)
            payload = json.dumps(
                {
                    "record": public,
                    "affected_dates": affected,
                    "latest_id": manager.latest().id
                    if manager.latest() is not None
                    else None,
                },
                ensure_ascii=False,
            )
            signal = getattr(self, "life_record_items_updated", None)
            if signal is not None and hasattr(signal, "emit"):
                signal.emit(payload)
                return True
        except Exception:
            return False
        return False

    def _finish_life_record_without_reply(self, operation_id: int) -> None:
        state = self._get_life_record_state()
        if state.finish_operation(operation_id):
            try:
                self._emit_life_record_pending(False)
            except Exception:
                pass
            drain = getattr(self, "_drain_queues_after_worker_finished", None)
            if callable(drain):
                drain()
