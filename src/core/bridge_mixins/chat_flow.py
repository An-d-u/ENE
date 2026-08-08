"""
WebBridge의 일반 채팅 요청, 재시도, 응답 완료 흐름.
"""
import json
from datetime import datetime
from functools import partial

from PyQt6.QtCore import pyqtSlot

from ...ai.chat_commands import parse_diary_command, parse_note_command
from ...ai.analysis_prompt import is_schedule_recognition_enabled
from ...ai.persona_names import role_label_for_prompt
from ...ai.prompt_language import resolve_prompt_language
from ...ai.response_protocol import (
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseDeliveryMetadata,
    ResponseMode,
)
from ..bridge_workers import AIWorker
from .life_records import LifeRecordBridgeMixin, PreparedChatRequest
from ..chat_attachments import (
    build_attachment_context_block,
    build_attachment_note,
    build_general_chat_prompt as compose_general_chat_prompt,
)
from ...conversation_format import prepend_message_time
from .goals import GoalBridgeMixin
from .thoughts import ThoughtBridgeMixin


def _prompt_time_header(timestamp: str, language: str) -> str:
    labels = {
        "ko": "현재 시각",
        "en": "Current Time",
        "ja": "現在時刻",
    }
    return f"[{labels.get(language, labels['ko'])}: {timestamp}]"


def _prompt_role_label(role: str, language: str, settings_source=None) -> str:
    return role_label_for_prompt(role, settings_source=settings_source, language=language)


_ALLOWED_RESPONSE_LOG_MODES = frozenset(mode.value for mode in ResponseMode)


def _safe_text_length(value: object) -> int:
    return len(value) if type(value) is str else 0


def _safe_list_count(value: object) -> int:
    return len(value) if type(value) is list else 0


def _response_log_metadata(metadata: object) -> tuple[str, str, str]:
    if type(metadata) is not ResponseDeliveryMetadata:
        return "unknown", "none", "false"
    response_mode = (
        metadata.response_mode
        if type(metadata.response_mode) is str
        and metadata.response_mode in _ALLOWED_RESPONSE_LOG_MODES
        else "unknown"
    )
    schema_version = (
        metadata.schema_version
        if type(metadata.schema_version) is str
        and metadata.schema_version == RESPONSE_ENVELOPE_SCHEMA_VERSION
        else "none"
    )
    repair_performed = "true" if metadata.repair_performed is True else "false"
    return response_mode, schema_version, repair_performed


class ChatFlowBridgeMixin:
    def _emit_request_pending_stage_changed(self, stage: str):
        normalized = str(stage or "").strip().lower()
        if normalized not in {
            "life_record",
            "life_record_regeneration",
            "thinking",
            "searching",
        }:
            normalized = "thinking"
        signal = getattr(self, "request_pending_stage_changed", None)
        if signal and hasattr(signal, "emit"):
            signal.emit(normalized)

    def _emit_request_pending_changed(self, active: bool):
        """LLM 응답 생성 진행 상태를 프런트에 알린다."""
        if not active:
            emit_stage = getattr(self, "_emit_request_pending_stage_changed", None)
            if callable(emit_stage):
                emit_stage("thinking")
            else:
                stage_signal = getattr(self, "request_pending_stage_changed", None)
                if stage_signal and hasattr(stage_signal, "emit"):
                    stage_signal.emit("thinking")
        signal = getattr(self, "request_pending_changed", None)
        if signal and hasattr(signal, "emit"):
            signal.emit(bool(active))

    def _drain_queues_after_worker_finished(self):
        """워커 종료 뒤 대기 중인 약속/선제 대화 큐를 다시 확인한다."""
        drain_promise_queue = getattr(self, "_drain_promise_queue_if_idle", None)
        if callable(drain_promise_queue):
            drain_promise_queue()
        drain_proactive_queue = getattr(self, "_drain_proactive_queue_if_idle", None)
        if callable(drain_proactive_queue):
            drain_proactive_queue()

    def _connect_worker_finished_drain(self, operation_id: int | None = None):
        """worker 종료 시 현재 normal_reply 소유권을 해제한 뒤 큐를 확인한다."""
        response_worker = getattr(self, "worker", None)
        finished = getattr(response_worker, "finished", None)
        connector = getattr(finished, "connect", None)
        if callable(connector):
            if operation_id is None:
                connector(self._drain_queues_after_worker_finished)
            else:
                connector(
                    partial(
                        self._finish_normal_reply_operation,
                        operation_id,
                        response_worker,
                    )
                )

    def _begin_normal_reply_operation(self) -> int | None:
        """일반·도구·자동 답변 worker가 사용할 공통 phase를 확보한다."""
        state = getattr(self, "life_record_state", None)
        if state is None:
            return 0
        phase = getattr(state, "phase", "idle")
        if phase == "idle":
            return state.try_begin_operation("normal_reply")
        if phase == "resuming_reply":
            operation_id = state.operation_id
            return operation_id if state.transition_operation(operation_id, "normal_reply") else None
        if phase == "normal_reply" and not (
            getattr(self, "worker", None) and self.worker.isRunning()
        ):
            return state.operation_id
        return None

    def _finish_normal_reply_operation(self, operation_id: int, response_worker) -> None:
        """stale worker 종료는 무시하고 현재 답변 작업만 idle로 되돌린다."""
        state = getattr(self, "life_record_state", None)
        if state is not None and getattr(self, "worker", None) is response_worker:
            state.finish_operation(operation_id)
        self._drain_queues_after_worker_finished()

    def _restore_failed_worker_start(self, operation_id: int) -> None:
        """worker 시작 실패가 phase와 프런트 pending 상태를 남기지 않게 한다."""
        state = getattr(self, "life_record_state", None)
        if state is not None:
            state.finish_operation(operation_id)
        self.worker = None
        reset_pending = getattr(self, "_reset_pending_ui_state", None)
        if callable(reset_pending):
            reset_pending()
            return
        self._is_rerolling = False
        stage_signal = getattr(self, "request_pending_stage_changed", None)
        if stage_signal is not None and hasattr(stage_signal, "emit"):
            stage_signal.emit("thinking")
        pending_signal = getattr(self, "request_pending_changed", None)
        if pending_signal is not None and hasattr(pending_signal, "emit"):
            pending_signal.emit(False)
        reroll_signal = getattr(self, "reroll_state_changed", None)
        if reroll_signal is not None and hasattr(reroll_signal, "emit"):
            reroll_signal.emit(False)

    def _start_ai_worker(
        self,
        message_with_time: str,
        images_data: list | None = None,
        memory_search_text: str = "",
        latest_user_message: str = "",
        recent_memory_context: str = "",
        head_pat_count_before_message: int = 0,
        include_life_record_context: bool = False,
    ):
        """현재 요청 페이로드로 AI 워커를 시작한다."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] request_rejected category=busy request_type=worker")
            return False
        begin_operation = getattr(self, "_begin_normal_reply_operation", None)
        operation_id = (
            begin_operation()
            if callable(begin_operation)
            else ChatFlowBridgeMixin._begin_normal_reply_operation(self)
        )
        if operation_id is None:
            print("[Bridge] request_rejected category=busy request_type=worker")
            return False

        try:
            message_with_context = self._with_ene_thought_context(message_with_time)
            message_with_context = self._with_tts_output_reminder(message_with_context)
            self.worker = AIWorker(
                self.llm_client,
                message_with_context,
                images=images_data or [],
                memory_search_text=memory_search_text,
                latest_user_message=latest_user_message,
                recent_memory_context=recent_memory_context,
                head_pat_count_before_message=head_pat_count_before_message,
                include_life_record_context=include_life_record_context,
                progress_callback=self._emit_request_pending_stage_changed,
            )
            self.worker.response_ready.connect(
                partial(self._on_response_ready, response_worker=self.worker)
            )
            self.worker.error_occurred.connect(self._on_error)
            connect_finished = getattr(self, "_connect_worker_finished_drain", None)
            if callable(connect_finished):
                connect_finished(operation_id) if operation_id else connect_finished()
            self._emit_request_pending_stage_changed("thinking")
            self._emit_request_pending_changed(True)
            self.worker.start()
            return True
        except Exception:
            restore = getattr(self, "_restore_failed_worker_start", None)
            if callable(restore):
                restore(operation_id)
            else:
                ChatFlowBridgeMixin._restore_failed_worker_start(self, operation_id)
            raise

    def _start_diary_worker(self, diary_request: str, message_with_time: str, use_obsidian_priority: bool = False):
        """/diary 전용 독립 컨텍스트 워커를 시작한다."""
        if self.worker and self.worker.isRunning():
            return False
        begin_operation = getattr(self, "_begin_normal_reply_operation", None)
        operation_id = (
            begin_operation()
            if callable(begin_operation)
            else ChatFlowBridgeMixin._begin_normal_reply_operation(self)
        )
        if operation_id is None:
            return False

        try:
            self.worker = AIWorker(
                self.llm_client,
                message_with_time,
                diary_request=diary_request,
                diary_service=self.diary_service,
                use_obsidian_priority=use_obsidian_priority,
            )
            self.worker.response_ready.connect(
                partial(self._on_response_ready, response_worker=self.worker)
            )
            self.worker.error_occurred.connect(self._on_error)
            connect_finished = getattr(self, "_connect_worker_finished_drain", None)
            if callable(connect_finished):
                connect_finished(operation_id) if operation_id else connect_finished()
            self._emit_request_pending_stage_changed("thinking")
            self._emit_request_pending_changed(True)
            self.worker.start()
            return True
        except Exception:
            restore = getattr(self, "_restore_failed_worker_start", None)
            if callable(restore):
                restore(operation_id)
            else:
                ChatFlowBridgeMixin._restore_failed_worker_start(self, operation_id)
            raise

    def _start_note_worker(self, note_request: str, message_with_time: str, note_recent_context: str = ""):
        """/note 계획-실행 워커를 시작한다."""
        if self.worker and self.worker.isRunning():
            return False
        begin_operation = getattr(self, "_begin_normal_reply_operation", None)
        operation_id = (
            begin_operation()
            if callable(begin_operation)
            else ChatFlowBridgeMixin._begin_normal_reply_operation(self)
        )
        if operation_id is None:
            return False

        try:
            self.worker = AIWorker(
                self.llm_client,
                message_with_time,
                note_request=note_request,
                note_recent_context=note_recent_context,
                note_service=self.note_service,
                obsidian_manager=self.obsidian_manager,
            )
            self.worker.response_ready.connect(
                partial(self._on_response_ready, response_worker=self.worker)
            )
            self.worker.error_occurred.connect(self._on_error)
            connect_finished = getattr(self, "_connect_worker_finished_drain", None)
            if callable(connect_finished):
                connect_finished(operation_id) if operation_id else connect_finished()
            self._emit_request_pending_stage_changed("thinking")
            self._emit_request_pending_changed(True)
            self.worker.start()
            return True
        except Exception:
            restore = getattr(self, "_restore_failed_worker_start", None)
            if callable(restore):
                restore(operation_id)
            else:
                ChatFlowBridgeMixin._restore_failed_worker_start(self, operation_id)
            raise

    def _resolve_note_context_settings(self) -> tuple[bool, int]:
        """노트 최근 대화 주입 설정을 읽어 정규화한다."""
        if not self.settings:
            return False, 0
        try:
            enabled = bool(self.settings.get("note_include_recent_context", False))
            turns = int(self.settings.get("note_recent_context_turns", 4) or 0)
        except Exception:
            return False, 0
        turns = max(0, min(turns, 200))
        return enabled, turns

    def _build_note_recent_context(self, max_turns: int) -> str:
        """
        /note 계획 프롬프트에 넣을 최근 대화 맥락을 생성한다.
        - max_turns == 0: 현재 세션 전체
        - max_turns > 0: 최근 N턴(사용자+에네 페어 단위)
        """
        if not self.conversation_buffer:
            return ""

        entries = list(self.conversation_buffer)
        if max_turns > 0:
            entries = entries[-(max_turns * 2):]

        lines: list[str] = []
        for item in entries:
            if not item or len(item) < 2:
                continue
            role = str(item[0]).strip().lower()
            text = str(item[1] or "").strip()
            if not text:
                continue
            ts = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
            language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
            role_label = _prompt_role_label(role, language, settings_source=getattr(self, "settings", None))
            prefix = f"[{ts}][{role_label}]" if ts else f"[{role_label}]"
            lines.append(f"{prefix} {text}")
        return "\n".join(lines).strip()

    def _handle_diary_command(self, message: str) -> bool:
        """'/diary' 명령을 감지해 로컬 저장 전용 처리한다."""
        is_diary, diary_body = parse_diary_command(message)
        if not is_diary:
            return False

        cancel_proactive = getattr(self, "_cancel_pending_proactive_conversations_for_user_message", None)
        if callable(cancel_proactive):
            cancel_proactive()
        self._mark_user_activity()
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        if not diary_body:
            self.message_received.emit("`/diary` 뒤에 작성할 내용을 함께 입력해 주세요.", "confused", "")
            return True

        timestamp = self._now_timestamp()
        message_with_time = self._with_prompt_time(timestamp, diary_body)

        # /diary는 일반 리롤/수정 payload에서 제외해 원문/본문 누적을 막는다.
        self._last_request_payload = None
        self._is_rerolling = False

        self._start_diary_worker(diary_body, message_with_time, use_obsidian_priority=False)
        print("[Bridge] /diary worker thread started")
        return True

    def _handle_note_command(self, message: str) -> bool:
        """/note 명령을 감지해 계획-실행-보고 플로우를 처리한다."""
        is_note, note_body = parse_note_command(message)
        if not is_note:
            return False

        cancel_proactive = getattr(self, "_cancel_pending_proactive_conversations_for_user_message", None)
        if callable(cancel_proactive):
            cancel_proactive()
        self._mark_user_activity()
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        if not note_body:
            self.message_received.emit("`/note` 뒤에 실행할 내용을 함께 입력해 주세요.", "confused", "")
            return True

        self._activate_obsidian_integration()
        timestamp = self._now_timestamp()
        message_with_time = self._with_prompt_time(timestamp, note_body)
        self._last_request_payload = None
        self._is_rerolling = False

        use_recent_context, recent_turns = self._resolve_note_context_settings()
        note_recent_context = self._build_note_recent_context(recent_turns) if use_recent_context else ""

        self._start_note_worker(note_body, message_with_time, note_recent_context)
        print("[Bridge] /note worker thread started")
        return True

    def _build_general_chat_prompt(
        self,
        message: str,
        attachment_context: str = "",
        *,
        language: str | None = None,
    ) -> str:
        """
        일반 채팅 프롬프트를 구성한다.
        체크된 파일 본문과 이번 턴 첨부 자료만 현재 요청에 포함한다.
        """
        obs_context = self._get_cached_checked_files_context().strip()
        return compose_general_chat_prompt(
            message,
            obsidian_context=obs_context,
            attachment_context=str(attachment_context or "").strip(),
            language=(
                language
                if language in {"ko", "en", "ja"}
                else self._prompt_language()
            ),
        )

    def _resolve_memory_search_turns(self) -> int:
        """장기기억 검색에 참고할 최근 보이는 대화 턴 수를 반환한다."""
        if not self.settings:
            return 2
        try:
            turns = int(self.settings.get("memory_search_recent_turns", 2) or 0)
        except Exception:
            turns = 2
        return max(0, min(turns, 50))

    def _build_memory_search_text(self, current_message: str, current_timestamp: str | None = None) -> str:
        """최신 메시지와 최근 보이는 대화 N턴으로 검색용 문자열을 만든다."""
        return ChatFlowBridgeMixin._build_memory_search_inputs(self, current_message, current_timestamp)["memory_search_text"]

    def _build_memory_search_inputs(
        self,
        current_message: str,
        current_timestamp: str | None = None,
        *,
        language: str | None = None,
    ) -> dict[str, str]:
        """장기기억 검색용 최신 메시지/보조 문맥/전체 텍스트를 각각 구성한다."""
        current = str(current_message or "").strip()
        turns = self._resolve_memory_search_turns()
        entries = list(self.conversation_buffer or [])
        if turns > 0:
            entries = entries[-(turns * 2):]

        resolved_language = (
            language
            if language in {"ko", "en", "ja"}
            else resolve_prompt_language(settings_source=getattr(self, "settings", None))
        )
        recent_lines: list[str] = []
        for item in entries:
            if not item or len(item) < 2:
                continue
            role = str(item[0]).strip().lower()
            text = str(item[1] or "").strip()
            if not text:
                continue
            timestamp = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
            role_label = _prompt_role_label(
                role,
                resolved_language,
                settings_source=getattr(self, "settings", None),
            )
            recent_lines.append(prepend_message_time(f"[{role_label}] {text}", timestamp))

        memory_search_lines = list(recent_lines)
        if current:
            current_label = {
                "ko": "현재 사용자 메시지",
                "en": "Current User Message",
                "ja": "現在のユーザーメッセージ",
            }.get(resolved_language, "현재 사용자 메시지")
            memory_search_lines.append(prepend_message_time(f"[{current_label}] {current}", current_timestamp))

        return {
            "latest_user_message": current,
            "recent_context_text": "\n".join(recent_lines).strip(),
            "memory_search_text": "\n".join(memory_search_lines).strip(),
        }

    @pyqtSlot(str)
    def send_to_ai(self, message: str):
        """JavaScript에서 호출: 사용자 텍스트 메시지를 AI로 전송."""
        capture_received_at = getattr(self, "_capture_life_received_at", None)
        received_at = (
            capture_received_at()
            if callable(capture_received_at)
            else datetime.now().astimezone().replace(microsecond=0)
        )
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=text")
            return
        print(f"[Bridge] message_received message_chars={_safe_text_length(message)}")

        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad", "")
            return

        if self._handle_note_command(message):
            return

        if self._handle_obs_command(message):
            return

        if self._handle_diary_command(message):
            return

        head_pat_count_before_message = 0
        if hasattr(self, 'calendar_manager') and self.calendar_manager:
            getter = getattr(self.calendar_manager, "get_pending_head_pat_count", None)
            if callable(getter):
                head_pat_count_before_message = int(getter())
        prepare_request = getattr(self, "_prepare_chat_request", None)
        if callable(prepare_request):
            prepared = prepare_request(
                received_at=received_at,
                request_type="text",
                message=message,
                head_pat_count_before_message=head_pat_count_before_message,
            )
        else:
            prepared = PreparedChatRequest(
                received_at=received_at,
                language=resolve_prompt_language(
                    settings_source=getattr(self, "settings", None)
                ),
                mood_snapshot=LifeRecordBridgeMixin._snapshot_life_mood(self),
                request_type="text",
                message=message,
                head_pat_count_before_message=head_pat_count_before_message,
            )
        dispatch = getattr(self, "_dispatch_general_request", None)
        if callable(dispatch):
            dispatch(prepared)
        else:
            self._mark_user_activity()
            ChatFlowBridgeMixin._commit_prepared_chat_request(self, prepared)

    def _commit_prepared_chat_request(self, request: PreparedChatRequest) -> None:
        """보류 가능 요청의 일반 대화 부수효과를 정확히 한 번 적용한다."""
        if request.request_type == "attachments":
            commit_attachments = getattr(self, "_commit_prepared_attachment_request", None)
            if not callable(commit_attachments):
                raise RuntimeError("attachment_commit_unavailable")
            commit_attachments(request)
            return

        legacy_direct_mixin = not hasattr(self, "life_record_state")
        timestamp = (
            self._now_timestamp()
            if legacy_direct_mixin
            else request.received_at.strftime("%Y-%m-%d %H:%M")
        )
        if legacy_direct_mixin:
            prompt = self._build_general_chat_prompt(request.message)
        else:
            prompt = self._build_general_chat_prompt(
                request.message,
                language=request.language,
            )
        with_prompt_time = getattr(self, "_with_prompt_time", None)
        if legacy_direct_mixin and callable(with_prompt_time):
            message_with_time = with_prompt_time(timestamp, prompt)
        else:
            message_with_time = f"{_prompt_time_header(timestamp, request.language)}\n{prompt}"
        if legacy_direct_mixin:
            memory_search_inputs = self._build_memory_search_inputs(
                request.message,
                timestamp,
            )
        else:
            memory_search_inputs = self._build_memory_search_inputs(
                request.message,
                timestamp,
                language=request.language,
            )
        memory_search_text = memory_search_inputs["memory_search_text"]
        committed_head_pat_count = request.head_pat_count_before_message
        if hasattr(self, "calendar_manager") and self.calendar_manager:
            self.calendar_manager.increment_conversation_count()
            drain = getattr(self.calendar_manager, "drain_pending_head_pat_count", None)
            if callable(drain):
                drained = drain()
                if legacy_direct_mixin:
                    committed_head_pat_count = int(drained or 0)
            print("[Bridge] 대화 횟수 증가")
        print(f"[Bridge] prompt_built prompt_chars={_safe_text_length(message_with_time)}")

        self._append_conversation("user", request.message, timestamp)
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(request.message, image_count=0)
            self._emit_mood_changed(snapshot)

        self._last_request_payload = {
            "type": "text",
            "message": request.message,
            "message_with_time": message_with_time,
            "images": [],
            "attachment_context": "",
            "memory_search_text": memory_search_text,
            "latest_user_message": memory_search_inputs["latest_user_message"],
            "recent_memory_context": memory_search_inputs["recent_context_text"],
            "head_pat_count_before_message": committed_head_pat_count,
            "include_life_record_context": True,
        }
        self._is_rerolling = False

        self._start_ai_worker(
            message_with_time,
            memory_search_text=memory_search_text,
            latest_user_message=memory_search_inputs["latest_user_message"],
            recent_memory_context=memory_search_inputs["recent_context_text"],
            head_pat_count_before_message=committed_head_pat_count,
            include_life_record_context=True,
        )
        print("[Bridge] Worker thread started")

    @pyqtSlot()
    def reroll_last_response(self):
        """마지막 사용자 요청을 다시 실행해 최근 assistant 응답만 교체."""
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=reroll")
            return
        if not self.llm_client:
            print("[Bridge] Reroll ignored: LLM client not initialized")
            self._reset_pending_ui_state("리롤할 수 있는 최근 요청이 없어요.")
            return

        if not self._last_request_payload:
            print("[Bridge] Reroll ignored: no previous request payload")
            self._reset_pending_ui_state("리롤할 수 있는 최근 요청이 없어요.")
            return
        if self._last_request_payload.get("type") == "proactive":
            print("[Bridge] Reroll ignored: proactive reply has no user request turn")
            self._reset_pending_ui_state("선제 대화 응답은 리롤할 수 없어요.")
            return

        if self.worker and self.worker.isRunning():
            print("[Bridge] Reroll ignored: worker is still running")
            self._reset_pending_ui_state("이미 응답 생성 중이에요.")
            return

        if not self._rollback_last_turn_pair_for_retry():
            print("[Bridge] Reroll aborted: failed to rollback/rebuild LLM context")
            self._reset_pending_ui_state("리롤 준비 중 문제가 생겼어요.")
            return

        self._delete_tracked_promises_for_retry()
        delete_proactive = getattr(self, "_delete_tracked_proactive_for_retry", None)
        if callable(delete_proactive):
            delete_proactive()

        # 교체 의미를 지키기 위해 최근 assistant 응답 하나를 버퍼에서 제거
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "assistant":
            assistant_index = len(self.conversation_buffer) - 1
            discard_loaded_topic = getattr(self, "_discard_loaded_topic_memory_context_from_index", None)
            if not callable(discard_loaded_topic):
                discard_loaded_topic = lambda index: ChatFlowBridgeMixin._discard_loaded_topic_memory_context_from_index(
                    self,
                    index,
                )
            discard_loaded_topic(max(0, assistant_index - 1))
            discard_thoughts = getattr(self, "_discard_ene_thought_context_from_index", None)
            if not callable(discard_thoughts):
                discard_thoughts = lambda index: ThoughtBridgeMixin._discard_ene_thought_context_from_index(self, index)
            discard_thoughts(assistant_index)
            self.conversation_buffer.pop()

        payload = self._last_request_payload
        self._is_rerolling = True
        self.reroll_state_changed.emit(True)
        self._start_ai_worker(
            payload["message_with_time"],
            payload.get("images") or [],
            memory_search_text=str(payload.get("memory_search_text", "") or ""),
            latest_user_message=str(payload.get("latest_user_message", "") or ""),
            recent_memory_context=str(payload.get("recent_memory_context", "") or ""),
            head_pat_count_before_message=int(payload.get("head_pat_count_before_message", 0) or 0),
            include_life_record_context=(
                payload.get("include_life_record_context") is True
            ),
        )
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
        accepts_input = getattr(self, "_life_operation_accepts_input", None)
        if callable(accepts_input) and not accepts_input():
            print("[Bridge] request_rejected category=busy request_type=edit")
            return
        edited_message = (edited_message or "").strip()
        if not edited_message:
            print("[Bridge] Edit ignored: empty message")
            self._reset_pending_ui_state("빈 메시지는 수정 저장할 수 없어요.")
            return

        if not self.llm_client:
            print("[Bridge] Edit ignored: LLM client not initialized")
            self._reset_pending_ui_state("수정 재요청을 처리할 수 없어요.")
            return

        if not self._last_request_payload:
            print("[Bridge] Edit ignored: no previous request payload")
            self._reset_pending_ui_state("/diary 응답은 Edit로 다시 생성할 수 없어요.")
            return
        if self._last_request_payload.get("type") == "proactive":
            print("[Bridge] Edit ignored: proactive reply has no user request turn")
            self._reset_pending_ui_state("선제 대화 응답은 수정할 사용자 메시지가 없어요.")
            return

        if self.worker and self.worker.isRunning():
            print("[Bridge] Edit ignored: worker is still running")
            self._reset_pending_ui_state("이미 응답 생성 중이에요.")
            return

        # 최근 user/assistant 턴을 LLM 컨텍스트에서 롤백
        if not self._rollback_last_turn_pair_for_retry():
            print("[Bridge] Edit aborted: failed to rollback/rebuild LLM context")
            self._reset_pending_ui_state("수정 재요청 준비 중 문제가 생겼어요.")
            return

        self._delete_tracked_promises_for_retry()
        delete_proactive = getattr(self, "_delete_tracked_proactive_for_retry", None)
        if callable(delete_proactive):
            delete_proactive()

        # 대화 버퍼의 최근 assistant/user 턴 제거
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "assistant":
            assistant_index = len(self.conversation_buffer) - 1
            discard_loaded_topic = getattr(self, "_discard_loaded_topic_memory_context_from_index", None)
            if not callable(discard_loaded_topic):
                discard_loaded_topic = lambda index: ChatFlowBridgeMixin._discard_loaded_topic_memory_context_from_index(
                    self,
                    index,
                )
            discard_loaded_topic(max(0, assistant_index - 1))
            discard_thoughts = getattr(self, "_discard_ene_thought_context_from_index", None)
            if not callable(discard_thoughts):
                discard_thoughts = lambda index: ThoughtBridgeMixin._discard_ene_thought_context_from_index(self, index)
            discard_thoughts(assistant_index)
            self.conversation_buffer.pop()
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "user":
            self.conversation_buffer.pop()

        # 수정 결과가 슬래시 명령이면 일반 채팅이 아니라 원래 명령 경로로 다시 보낸다.
        if self._handle_note_command(edited_message):
            print("[Bridge] Edit rerouted to /note command flow")
            return
        if self._handle_obs_command(edited_message):
            print("[Bridge] Edit rerouted to /obs command flow")
            return
        if self._handle_diary_command(edited_message):
            print("[Bridge] Edit rerouted to /diary command flow")
            return

        timestamp = self._now_timestamp()
        payload_type = self._last_request_payload.get("type", "text")
        images = self._last_request_payload.get("images") or []
        attachment_note = str(self._last_request_payload.get("attachment_note", "") or "")
        attachment_context = str(self._last_request_payload.get("attachment_context", "") or "")
        message_id = str(self._last_request_payload.get("message_id", "") or "")
        if payload_type in {"images", "attachments"}:
            self._append_conversation("user", edited_message + attachment_note, timestamp)
        else:
            self._append_conversation("user", edited_message, timestamp)

        record = self._message_attachment_records.get(message_id) if message_id else None
        if isinstance(record, dict):
            record["message"] = edited_message
            record["timestamp"] = timestamp
            record["conversation_index"] = len(self.conversation_buffer) - 1
            attachment_note = build_attachment_note(record.get("attachments") or [], language=self._prompt_language())
            attachment_context = build_attachment_context_block(
                record.get("attachments") or [],
                language=self._prompt_language(),
            )
            self.conversation_buffer[-1] = (
                self.conversation_buffer[-1][0],
                self._compose_attachment_history_message(edited_message, record.get("attachments") or []),
                self.conversation_buffer[-1][2],
            )
            record["attachment_note"] = attachment_note
            record["attachment_context"] = attachment_context

        prompt = self._build_general_chat_prompt(edited_message, attachment_context=attachment_context)
        message_with_time = self._with_prompt_time(timestamp, prompt)
        memory_search_inputs = self._build_memory_search_inputs(edited_message, timestamp)
        memory_search_text = memory_search_inputs["memory_search_text"]
        include_life_record_context = (
            self._last_request_payload.get("include_life_record_context") is True
        )
        self._last_request_payload = {
            "type": payload_type,
            "message": edited_message,
            "message_id": message_id,
            "message_with_time": message_with_time,
            "images": images,
            "attachment_note": attachment_note,
            "attachment_context": attachment_context,
            "memory_search_text": memory_search_text,
            "latest_user_message": memory_search_inputs["latest_user_message"],
            "recent_memory_context": memory_search_inputs["recent_context_text"],
            "head_pat_count_before_message": int(self._last_request_payload.get("head_pat_count_before_message", 0) or 0),
            "include_life_record_context": include_life_record_context,
        }

        self._is_rerolling = True
        self.reroll_state_changed.emit(True)
        self._start_ai_worker(
            message_with_time,
            images,
            memory_search_text=memory_search_text,
            latest_user_message=memory_search_inputs["latest_user_message"],
            recent_memory_context=memory_search_inputs["recent_context_text"],
            head_pat_count_before_message=int(self._last_request_payload.get("head_pat_count_before_message", 0) or 0),
            include_life_record_context=include_life_record_context,
        )
        print("[Bridge] Edit last user message started")

    def _on_response_ready(self, *args, response_worker=None, **kwargs):
        worker = (
            response_worker if response_worker is not None else getattr(self, "worker", None)
        )
        response_metadata = getattr(worker, "response_metadata", None)
        if type(response_metadata) is not ResponseDeliveryMetadata:
            response_metadata = ResponseDeliveryMetadata.empty()
        try:
            return ChatFlowBridgeMixin._handle_response_ready(
                self,
                *args,
                response_metadata=response_metadata,
                **kwargs,
            )
        except Exception:
            ChatFlowBridgeMixin._emit_request_pending_changed(self, False)
            raise
        finally:
            if worker is not None:
                worker.response_metadata = ResponseDeliveryMetadata.empty()

    def _remember_loaded_topic_memory_context_for_summary(self) -> None:
        """이번 응답 생성에 실제 주입된 주제 기억을 요약 비교용 side-buffer에 남긴다."""
        llm_client = getattr(self, "llm_client", None)
        context = str(getattr(llm_client, "_last_loaded_topic_memory_context", "") or "").strip()
        if not context:
            return

        conversation = list(getattr(self, "conversation_buffer", []) or [])
        conversation_index = len(conversation) - 2
        if conversation_index < 0:
            return

        buffer = getattr(self, "_loaded_topic_memory_context_buffer", None)
        if not isinstance(buffer, list):
            buffer = []
            self._loaded_topic_memory_context_buffer = buffer
        buffer.append(
            {
                "conversation_index": conversation_index,
                "context": context,
            }
        )
        setattr(llm_client, "_last_loaded_topic_memory_context", "")

    def _discard_loaded_topic_memory_context_from_index(self, start_index: int) -> None:
        """리롤/수정으로 사라진 대화 범위의 loaded topic context를 버린다."""
        entries = getattr(self, "_loaded_topic_memory_context_buffer", None)
        if not isinstance(entries, list):
            return

        try:
            threshold = int(start_index)
        except Exception:
            threshold = 0
        kept = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                conversation_index = int(entry.get("conversation_index", -1))
            except Exception:
                conversation_index = -1
            if conversation_index < threshold:
                kept.append(entry)
        self._loaded_topic_memory_context_buffer = kept

    def _handle_response_ready(
        self,
        text: str,
        emotion: str,
        tts_text: str,
        events: list = None,
        analysis_payload: str = "",
        token_usage_payload: str = "",
        scheduled_promises: list | None = None,
        thought: str = "",
        goal_update_payload: str = "",
        proactive_conversations: list | None = None,
        gesture: str = "",
        *,
        response_metadata: ResponseDeliveryMetadata | None = None,
    ):
        """AI 응답 준비 완료"""
        completed_promise_id = str(getattr(self, "_active_promise_id", "") or "").strip()
        completed_proactive_id = str(getattr(self, "_active_proactive_id", "") or "").strip()
        proactive_enabled = getattr(self, "_is_proactive_conversation_enabled", None)
        if completed_proactive_id and callable(proactive_enabled) and not proactive_enabled():
            print("[Bridge] 선제 대화 설정이 꺼져 활성 선제 응답을 폐기합니다.")
            ChatFlowBridgeMixin._emit_request_pending_changed(self, False)
            proactive_manager = getattr(self, "proactive_manager", None)
            if proactive_manager:
                proactive_manager.delete_item(completed_proactive_id)
            self._active_proactive_id = None
            self._active_proactive_signature = None
            refresh_history = getattr(self, "_refresh_llm_history_from_visible_conversation", None)
            if callable(refresh_history):
                refresh_history()
            drain_proactive_queue = getattr(self, "_drain_proactive_queue_if_idle", None)
            if callable(drain_proactive_queue):
                drain_proactive_queue()
            return
        text = self._sanitize_visible_response_text(text)
        gesture = ChatFlowBridgeMixin._normalize_response_gesture(self, gesture)
        sanitize_thought = getattr(self, "_sanitize_visible_thought_text", None)
        thought = sanitize_thought(thought) if callable(sanitize_thought) else str(thought or "").strip()
        thoughts_enabled = getattr(self, "_are_ene_thoughts_enabled", None)
        if not callable(thoughts_enabled):
            thoughts_enabled = lambda: ThoughtBridgeMixin._are_ene_thoughts_enabled(self)
        if not thoughts_enabled():
            thought = ""
        response_mode, schema_version, repair_performed = _response_log_metadata(
            response_metadata
        )
        print(
            "[Bridge] response_ready "
            f"response_mode={response_mode} "
            f"schema_version={schema_version} "
            f"repair_performed={repair_performed} "
            f"reply_chars={_safe_text_length(text)} "
            f"tts_chars={_safe_text_length(tts_text)} "
            f"thought_chars={_safe_text_length(thought)} "
            f"event_count={_safe_list_count(events)} "
            f"promise_count={_safe_list_count(scheduled_promises)} "
            f"proactive_count={_safe_list_count(proactive_conversations)}"
        )
        self._last_assistant_response = {"text": text, "emotion": emotion}
        analysis = {}
        if analysis_payload:
            try:
                parsed = json.loads(analysis_payload)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                analysis = {str(key): str(value) for key, value in parsed.items()}

        if self.mood_manager and analysis:
            snapshot = self.mood_manager.on_user_analysis(analysis)
            self._emit_mood_changed(snapshot)
        resolved_token_usage_payload = self._resolve_token_usage_payload(token_usage_payload)
        if self.mood_manager:
            snapshot = self.mood_manager.on_assistant_emotion(emotion)
            self._emit_mood_changed(snapshot)

        GoalBridgeMixin._apply_goal_update_payload(self, goal_update_payload)
        
        # 대화 버퍼에 응답 추가 (+ 타임스탬프)
        self._append_conversation("assistant", text)
        remember_loaded_topic = getattr(self, "_remember_loaded_topic_memory_context_for_summary", None)
        if not callable(remember_loaded_topic):
            remember_loaded_topic = lambda: ChatFlowBridgeMixin._remember_loaded_topic_memory_context_for_summary(self)
        remember_loaded_topic()
        remember_thought = getattr(self, "_remember_ene_thought_for_context", None)
        if not callable(remember_thought):
            remember_thought = lambda value: ThoughtBridgeMixin._remember_ene_thought_for_context(self, value)
        remember_thought(thought)
        self._refresh_llm_history_from_visible_conversation()
        
        # 일정 저장 (CalendarManager가 있으면)
        if (
            events
            and is_schedule_recognition_enabled(getattr(self, "settings", None))
            and hasattr(self, 'calendar_manager')
            and self.calendar_manager
        ):
            for event_data in events:
                try:
                    self.calendar_manager.add_event(
                        date=event_data['date'],
                        title=event_data['title'],
                        description=event_data.get('description', ''),
                        source="ai_extracted"
                    )
                    print("[Bridge] schedule_event category=schedule_add_success")
                except Exception as e:
                    print(
                        "[Bridge] schedule_event category=schedule_add_failed "
                        f"exception_class={type(e).__name__}"
                    )

        stored_promise_ids: list[str] = []
        llm_promises = list(scheduled_promises or [])
        promises_authoritative = (
            type(response_metadata) is ResponseDeliveryMetadata
            and response_metadata.promises_authoritative is True
        )
        use_fallback = not llm_promises and not promises_authoritative
        store_promises = getattr(self, "_store_scheduled_promises", None)
        if callable(store_promises):
            stored = store_promises(llm_promises)
            stored_promise_ids.extend(self._collect_promise_ids(stored))
        maybe_store_user_promises = getattr(self, "_maybe_store_user_promise_candidates", None)
        if callable(maybe_store_user_promises) and use_fallback:
            stored = maybe_store_user_promises(llm_promises)
            stored_promise_ids.extend(self._collect_promise_ids(stored))
        maybe_store_assistant_promises = getattr(self, "_maybe_store_assistant_promise_candidates", None)
        if callable(maybe_store_assistant_promises) and use_fallback:
            stored = maybe_store_assistant_promises(text)
            stored_promise_ids.extend(self._collect_promise_ids(stored))
        self._remember_tracked_promise_ids(stored_promise_ids)

        stored_proactive_ids: list[str] = []
        store_proactive = getattr(self, "_store_proactive_conversations", None)
        if callable(store_proactive):
            stored_proactive = store_proactive(
                list(proactive_conversations or []),
                suppress=bool(llm_promises) or bool(completed_proactive_id),
            )
            collect_proactive_ids = getattr(self, "_collect_proactive_ids", None)
            if callable(collect_proactive_ids):
                stored_proactive_ids.extend(collect_proactive_ids(stored_proactive))
        remember_proactive = getattr(self, "_remember_tracked_proactive_ids", None)
        if callable(remember_proactive):
            remember_proactive(stored_proactive_ids)
        
        # TTS 재생 (읽어줄 텍스트가 있고 TTS가 활성화되어 있으면)
        deferred_completion = False
        if tts_text and self.enable_tts and self.tts_client and self.audio_player:
            print(f"[Bridge] TTS 활성화 - 텍스트 보류 중, TTS 생성 시작")
            # 텍스트를 보류하고 TTS 완료 대기
            self.pending_response = (text, emotion, thought, gesture)
            self.pending_token_usage_payload = resolved_token_usage_payload
            self._pending_response_completion = {
                "promise_id": completed_promise_id,
                "proactive_id": completed_proactive_id,
            }
            deferred_completion = True
            self._play_tts(tts_text)
        else:
            # TTS 비활성화 또는 읽어줄 텍스트 없음 - 즉시 텍스트 전송
            print(f"[Bridge] TTS 비활성화 - 텍스트 즉시 전송")
            ChatFlowBridgeMixin._emit_request_pending_changed(self, False)
            self.message_received.emit(text, emotion, thought)
            ChatFlowBridgeMixin._emit_gesture_requested(self, gesture)
            self.token_usage_ready.emit(resolved_token_usage_payload)
            if self._is_rerolling:
                self._is_rerolling = False
                self.reroll_state_changed.emit(False)
            if tts_text:
                print(f"[Bridge] tts_skipped tts_chars={_safe_text_length(tts_text)}")
        
        # 자동 요약 확인
        self._check_auto_summarize()
        if deferred_completion:
            if self.pending_response:
                return
            ChatFlowBridgeMixin._finalize_pending_response_completion_if_any(self)
            return
        ChatFlowBridgeMixin._finalize_completed_runtime_items(self, completed_promise_id, completed_proactive_id)

    def _normalize_response_gesture(self, gesture: str) -> str:
        """LLM 응답에서 온 제스처 키를 런타임 허용 목록으로 제한한다."""
        normalized = str(gesture or "").strip().lower().replace("_", "-")
        allowed = {"nod", "bow", "shake", "surprise", "tilt", "sway"}
        return normalized if normalized in allowed else ""

    def _emit_gesture_requested(self, gesture: str) -> None:
        """제스처가 있을 때만 프론트엔드에 요청한다."""
        if not ChatFlowBridgeMixin._is_synthetic_gesture_enabled(self):
            return
        normalized = ChatFlowBridgeMixin._normalize_response_gesture(self, gesture)
        if normalized:
            self.gesture_requested.emit(normalized)

    def _is_synthetic_gesture_enabled(self) -> bool:
        """설정에서 합성 제스처 재생 허용 여부를 읽는다."""
        settings = getattr(self, "settings", None)
        if isinstance(settings, dict):
            return bool(settings.get("enable_synthetic_gestures", True))
        getter = getattr(settings, "get", None)
        if callable(getter):
            try:
                return bool(getter("enable_synthetic_gestures", True))
            except Exception:
                return True
        config = getattr(settings, "config", None)
        if isinstance(config, dict):
            return bool(config.get("enable_synthetic_gestures", True))
        return True

    def _finalize_completed_runtime_items(self, completed_promise_id: str = "", completed_proactive_id: str = ""):
        """사용자에게 응답을 보낸 뒤 예약/큐 상태를 마무리한다."""
        promise_manager = getattr(self, "promise_manager", None)
        if promise_manager and completed_promise_id:
            promise_manager.delete_promise(completed_promise_id)
            emit_items = getattr(self, "_emit_promise_items_updated", None)
            if callable(emit_items):
                emit_items()
        self._active_promise_id = None
        self._active_promise_signature = None
        drain_queue = getattr(self, "_drain_promise_queue_if_idle", None)
        if callable(drain_queue):
            drain_queue()
        proactive_manager = getattr(self, "proactive_manager", None)
        if proactive_manager and completed_proactive_id:
            proactive_manager.set_status(completed_proactive_id, "completed")
            emit_proactive_items = getattr(self, "_emit_proactive_items_updated", None)
            if callable(emit_proactive_items):
                emit_proactive_items()
        self._active_proactive_id = None
        self._active_proactive_signature = None
        drain_proactive_queue = getattr(self, "_drain_proactive_queue_if_idle", None)
        if callable(drain_proactive_queue):
            drain_proactive_queue()

    def _finalize_pending_response_completion_if_any(self):
        """TTS 보류 응답이 실제로 표시된 뒤 예약 완료 처리를 수행한다."""
        payload = getattr(self, "_pending_response_completion", None)
        self._pending_response_completion = None
        if not isinstance(payload, dict):
            return
        ChatFlowBridgeMixin._finalize_completed_runtime_items(
            self,
            str(payload.get("promise_id", "") or "").strip(),
            str(payload.get("proactive_id", "") or "").strip(),
        )

    def _on_error(self, error_msg: str):
        """오류 발생"""
        print("[Bridge] request_failed category=provider_error")
        ChatFlowBridgeMixin._emit_request_pending_changed(self, False)
        reminder_id = str(getattr(self, "_active_promise_id", "") or "").strip()
        promise_manager = getattr(self, "promise_manager", None)
        if promise_manager and reminder_id:
            promise_manager.set_status(reminder_id, "missed")
            emit_items = getattr(self, "_emit_promise_items_updated", None)
            if callable(emit_items):
                emit_items()
            self._active_promise_id = None
            self._active_promise_signature = None
        proactive_id = str(getattr(self, "_active_proactive_id", "") or "").strip()
        proactive_manager = getattr(self, "proactive_manager", None)
        if proactive_manager and proactive_id:
            proactive_manager.set_status(proactive_id, "expired")
            self._active_proactive_id = None
            self._active_proactive_signature = None
        self.message_received.emit("음... 무슨 일이 있었나봐요.", "confused", "")
        if self._is_rerolling:
            self._is_rerolling = False
            self.reroll_state_changed.emit(False)
        drain_queue = getattr(self, "_drain_promise_queue_if_idle", None)
        if callable(drain_queue):
            drain_queue()
        drain_proactive_queue = getattr(self, "_drain_proactive_queue_if_idle", None)
        if callable(drain_proactive_queue):
            drain_proactive_queue()
