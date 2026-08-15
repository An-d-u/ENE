"""
브릿지에서 사용하는 백그라운드 워커 모음.
"""
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping

from PyQt6.QtCore import QThread, pyqtSignal

from ..ai.diary_service import DiaryService
from ..ai.life_record_types import (
    LifeRecordOutput,
    LifeRecordValidationError,
    parse_and_validate_life_record_output,
)
from ..ai.note_service import NoteCommand, NoteCommandResult, NotePlan, NoteService
from ..ai.response_protocol import (
    OneShotGenerationResult,
    OneShotTokenUsage,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
    TurnTokenUsageAccumulator,
    is_valid_token_count,
)
from ..ai.persona_names import resolve_prompt_persona_names
from ..ai.prompt_language import resolve_prompt_language
from .local_time import resolve_local_time_context

class _UnsupportedResponseFormatError(Exception):
    pass


class _UnsupportedImageInputError(Exception):
    pass


class _UnsupportedDiaryError(Exception):
    pass


class _UnsupportedNotePlanError(Exception):
    pass


class _UnsupportedNoteReportError(Exception):
    pass


def _local_validation_message(failure: BaseException) -> str | None:
    """예외 속성을 읽지 않고 신뢰 가능한 내부 타입만 공개 문구로 바꾼다."""
    failure_type = type(failure)
    if failure_type is _UnsupportedResponseFormatError:
        return "지원하지 않는 응답 형식입니다."
    if failure_type is _UnsupportedImageInputError:
        return "현재 LLM 공급자는 이미지 입력을 지원하지 않습니다. 이미지 지원 공급자나 모델로 변경해 주세요."
    if failure_type is _UnsupportedDiaryError:
        return "현재 LLM 클라이언트는 /diary를 지원하지 않습니다."
    if failure_type is _UnsupportedNotePlanError:
        return "현재 LLM 클라이언트는 /note 계획 생성을 지원하지 않습니다."
    if failure_type is _UnsupportedNoteReportError:
        return "현재 LLM 클라이언트는 /note 결과 보고 생성을 지원하지 않습니다."
    return None


def _safe_exception_class_name(failure: BaseException) -> str:
    """사용자 정의 예외 속성이나 메타클래스 훅 없이 안전한 분류명만 만든다."""
    failure_type = type(failure)
    if failure_type is RuntimeError:
        return "RuntimeError"
    if failure_type is ValueError:
        return "ValueError"
    if failure_type is TypeError:
        return "TypeError"
    if failure_type is AssertionError:
        return "AssertionError"
    if failure_type is OSError:
        return "OSError"
    if failure_type is asyncio.CancelledError:
        return "CancelledError"
    if _local_validation_message(failure) is not None:
        return "LocalValidationError"
    if isinstance(failure, Exception):
        return "Exception"
    return "BaseException"

_ALLOWED_RESPONSE_LOG_MODES = frozenset(mode.value for mode in ResponseMode)
_LIFE_RECORD_LANGUAGES = frozenset({"ko", "en", "ja"})
_LIFE_RECORD_REPAIR_SUFFIX = """

[생활 기록 출력 재검증]
이전 출력이 호스트 검증을 통과하지 못했다.
validation_error_code: {error_code}
원문을 복사하지 말고 전체 JSON 객체를 처음부터 다시 생성한다.
"""


@dataclass(frozen=True, repr=False)
class LifeRecordGenerationRequest:
    """GUI 스레드에서 확정해 worker에 넘기는 불변 생성 요청."""

    operation_id: int
    prompt: str
    inactive_started_at: datetime
    returned_at: datetime
    timezone: str
    language: Literal["ko", "en", "ja"]

    def __post_init__(self) -> None:
        if type(self.operation_id) is not int or self.operation_id < 0:
            raise ValueError("invalid_operation_id")
        if type(self.prompt) is not str or not self.prompt:
            raise ValueError("invalid_prompt")
        if self.language not in _LIFE_RECORD_LANGUAGES:
            raise ValueError("invalid_language")
        resolution = resolve_local_time_context(self.timezone)
        context = resolution.context
        if context is None:
            raise ValueError("invalid_timezone")
        start = self.inactive_started_at
        end = self.returned_at
        if (
            not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is None
            or end.tzinfo is None
            or start.utcoffset() is None
            or end.utcoffset() is None
            or start.microsecond != 0
            or end.microsecond != 0
        ):
            raise ValueError("invalid_interval")
        try:
            matches_zone = context.matches_zone_rules(start) and context.matches_zone_rules(end)
            ordered = start.astimezone(timezone.utc) < end.astimezone(timezone.utc)
        except (OverflowError, ValueError):
            raise ValueError("invalid_interval") from None
        if not matches_zone:
            raise ValueError("invalid_timezone_offset")
        if not ordered:
            raise ValueError("invalid_interval")

    def __repr__(self) -> str:
        return (
            "LifeRecordGenerationRequest("
            f"operation_id={self.operation_id}, "
            f"inactive_started_at={self.inactive_started_at.isoformat()!r}, "
            f"returned_at={self.returned_at.isoformat()!r}, "
            f"timezone={self.timezone!r}, "
            f"language={self.language!r}, "
            f"prompt_chars={len(self.prompt)})"
        )


@dataclass(frozen=True, repr=False)
class LifeRecordWorkerResult:
    """생활 기록 worker가 bridge에 전달하는 개인정보 비노출 결과."""

    operation_id: int
    output: LifeRecordOutput | None
    status: ResponseStatus | None
    token_usage: OneShotTokenUsage
    attempt_count: int
    error_code: str | None = None

    def __repr__(self) -> str:
        entry_count = len(self.output.entries) if self.output is not None else 0
        status = self.status.value if self.status is not None else "error"
        return (
            "LifeRecordWorkerResult("
            f"operation_id={self.operation_id}, "
            f"status={status!r}, "
            f"attempt_count={self.attempt_count}, "
            f"entry_count={entry_count}, "
            f"error_code={self.error_code!r})"
        )


class LifeRecordWorker(QThread):
    """히스토리 없는 생활 기록 호출과 host 검증 재시도를 소유한다."""

    result_ready = pyqtSignal(int, object)
    error_occurred = pyqtSignal(int, object)

    def __init__(self, llm_client, request: LifeRecordGenerationRequest):
        super().__init__()
        if not isinstance(request, LifeRecordGenerationRequest):
            raise ValueError("invalid_life_record_request")
        self.llm_client = llm_client
        self.request = request

    @staticmethod
    def _usage_dict(result: OneShotGenerationResult) -> dict[str, int | None]:
        usage = result.token_usage
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }

    @staticmethod
    def _usage_snapshot(accumulator: TurnTokenUsageAccumulator) -> OneShotTokenUsage:
        usage = accumulator.snapshot()
        return OneShotTokenUsage(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
        )

    def _result(
        self,
        *,
        accumulator: TurnTokenUsageAccumulator,
        output: LifeRecordOutput | None,
        status: ResponseStatus | None,
        error_code: str | None,
    ) -> LifeRecordWorkerResult:
        return LifeRecordWorkerResult(
            operation_id=self.request.operation_id,
            output=output,
            status=status,
            token_usage=self._usage_snapshot(accumulator),
            attempt_count=accumulator.attempt_count,
            error_code=error_code,
        )

    async def _generate(self) -> LifeRecordWorkerResult | None:
        accumulator = TurnTokenUsageAccumulator()
        prompt = self.request.prompt
        for attempt_index in range(2):
            if self.isInterruptionRequested():
                return None
            try:
                response = await self.llm_client.generate_life_record_once(prompt)
            except BaseException:
                if self.isInterruptionRequested():
                    return None
                accumulator.record(None)
                return self._result(
                    accumulator=accumulator,
                    output=None,
                    status=None,
                    error_code="generation_failed",
                )
            if self.isInterruptionRequested():
                return None
            if not isinstance(response, OneShotGenerationResult):
                accumulator.record(None)
                return self._result(
                    accumulator=accumulator,
                    output=None,
                    status=None,
                    error_code="generation_failed",
                )
            accumulator.record(self._usage_dict(response))
            if response.status is not ResponseStatus.COMPLETE:
                error_code = {
                    ResponseStatus.REFUSAL: "provider_refusal",
                    ResponseStatus.INCOMPLETE: "provider_incomplete",
                    ResponseStatus.EMPTY: "provider_empty",
                }.get(response.status, "generation_failed")
                return self._result(
                    accumulator=accumulator,
                    output=None,
                    status=response.status,
                    error_code=error_code,
                )
            try:
                output = parse_and_validate_life_record_output(
                    response.text,
                    inactive_started_at=self.request.inactive_started_at,
                    returned_at=self.request.returned_at,
                    timezone_name=self.request.timezone,
                )
            except LifeRecordValidationError as failure:
                if attempt_index == 0:
                    prompt = self.request.prompt + _LIFE_RECORD_REPAIR_SUFFIX.format(
                        error_code=failure.code
                    )
                    continue
                return self._result(
                    accumulator=accumulator,
                    output=None,
                    status=response.status,
                    error_code=failure.code,
                )
            return self._result(
                accumulator=accumulator,
                output=output,
                status=response.status,
                error_code=None,
            )
        return self._result(
            accumulator=accumulator,
            output=None,
            status=None,
            error_code="generation_failed",
        )

    def run(self) -> None:
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._generate())
            if result is None or self.isInterruptionRequested():
                return
            token_usage = result.token_usage
            entry_count = len(result.output.entries) if result.output is not None else 0
            status = result.status.value if result.status is not None else "error"
            print(
                "[Life Record Worker] request_finished "
                f"status={status} "
                f"attempt_count={result.attempt_count} "
                f"entry_count={entry_count} "
                f"input_tokens={token_usage.input_tokens} "
                f"output_tokens={token_usage.output_tokens} "
                f"total_tokens={token_usage.total_tokens} "
                f"error_code={result.error_code or 'none'}"
            )
            if result.output is not None and result.error_code is None:
                if self.isInterruptionRequested():
                    return
                self.result_ready.emit(result.operation_id, result)
            else:
                if self.isInterruptionRequested():
                    return
                self.error_occurred.emit(result.operation_id, result)
        except BaseException:
            if not self.isInterruptionRequested():
                result = LifeRecordWorkerResult(
                    operation_id=self.request.operation_id,
                    output=None,
                    status=None,
                    token_usage=OneShotTokenUsage(None, None, None),
                    attempt_count=0,
                    error_code="generation_failed",
                )
                print(
                    "[Life Record Worker] request_finished status=error "
                    "attempt_count=0 entry_count=0 input_tokens=None "
                    "output_tokens=None total_tokens=None error_code=generation_failed"
                )
                if self.isInterruptionRequested():
                    return
                self.error_occurred.emit(result.operation_id, result)
        finally:
            if loop is not None:
                loop.close()


def _safe_text_length(value: object) -> int:
    """로그에서 사용자 정의 문자열 훅을 호출하지 않고 길이를 센다."""
    return len(value) if type(value) is str else 0


def _safe_list_count(value: object) -> int:
    """로그에서 사용자 정의 컬렉션 훅을 호출하지 않고 항목 수를 센다."""
    return len(value) if type(value) is list else 0


def _obsidian_checked_context_labels(language: str) -> dict[str, str]:
    return {
        "ko": {
            "checked": "[Obsidian 체크된 파일 본문]",
            "file": "파일",
        },
        "en": {
            "checked": "[Checked Obsidian File Contents]",
            "file": "File",
        },
        "ja": {
            "checked": "[Obsidianのチェック済みファイル本文]",
            "file": "ファイル",
        },
    }.get(language, {
        "checked": "[Obsidian 체크된 파일 본문]",
        "file": "파일",
    })


def build_obsidian_checked_context(checked_contents: list[tuple[str, str]], language: str) -> str:
    labels = _obsidian_checked_context_labels(language)
    parts: list[str] = []
    if checked_contents:
        parts.append(labels["checked"])
        for rel, content in checked_contents:
            parts.append(f"[{labels['file']}:{rel}]")
            parts.append(content)
    return "\n".join(parts)


class AIWorker(QThread):
    """AI 응답을 비동기로 처리하는 워커 스레드"""

    response_ready = pyqtSignal(str, str, str, list, str, str, list, str, str, list, str, str)  # (텍스트, 감정, TTS 텍스트, 이벤트, 분석 JSON, 토큰 JSON, 약속 리스트, 생각, 목표 업데이트 JSON, 선제 대화 리스트, 제스처, 무드 분석 JSON)
    error_occurred = pyqtSignal(str)  # 오류 메시지

    def __init__(
        self,
        llm_client,
        message,
        use_memory=True,
        images=None,
        memory_search_text: str = "",
        latest_user_message: str = "",
        recent_memory_context: str = "",
        head_pat_count_before_message: int = 0,
        diary_request: str = "",
        note_request: str = "",
        note_recent_context: str = "",
        diary_service: DiaryService | None = None,
        note_service: NoteService | None = None,
        obsidian_manager=None,
        use_obsidian_priority: bool = False,
        progress_callback=None,
        include_life_record_context: bool = False,
        prior_token_usage: Mapping[str, object] | None = None,
        mood_event_context: Mapping[str, str] | None = None,
    ):
        super().__init__()
        self.llm_client = llm_client
        self.message = message
        self.use_memory = use_memory
        self.images = images or []  # 이미지 데이터 리스트
        self.memory_search_text = (memory_search_text or "").strip()
        self.latest_user_message = (latest_user_message or "").strip()
        self.recent_memory_context = (recent_memory_context or "").strip()
        self.head_pat_count_before_message = max(0, int(head_pat_count_before_message or 0))
        self.include_life_record_context = include_life_record_context is True
        self.prior_token_usage = (
            dict(prior_token_usage) if isinstance(prior_token_usage, Mapping) else None
        )
        copied_mood_context = {}
        if isinstance(mood_event_context, Mapping):
            for key in ("event_id", "occurred_at_utc"):
                value = mood_event_context.get(key)
                if type(value) is str and value.strip():
                    copied_mood_context[key] = value
        self.mood_event_context = (
            copied_mood_context
            if set(copied_mood_context) == {"event_id", "occurred_at_utc"}
            else {}
        )
        self.diary_request = (diary_request or "").strip()
        self.note_request = (note_request or "").strip()
        self.note_recent_context = (note_recent_context or "").strip()
        self.diary_service = diary_service
        self.note_service = note_service
        self.obsidian_manager = obsidian_manager
        self.use_obsidian_priority = bool(use_obsidian_priority)
        self.progress_callback = progress_callback
        self.response_metadata = ResponseDeliveryMetadata.empty()
        self._cancellation_requested = False

    def requestInterruption(self) -> None:
        """시작 직전 요청도 잃지 않도록 Python 측 취소 상태를 함께 보관한다."""
        self._cancellation_requested = True
        super().requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancellation_requested or self.isInterruptionRequested()

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=getattr(self.llm_client, "settings", None))

    def _normalize_response_payload(self, payload):
        """신구 응답 형식을 기존 위치를 유지한 11개 값으로 정규화한다."""
        if isinstance(payload, tuple):
            if len(payload) == 11:
                return payload
            if len(payload) == 10:
                return (*payload, None)
            if len(payload) == 9:
                text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations = payload
                return text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, "", None
            if len(payload) == 8:
                text, emotion, tts_text, events, analysis, promises, thought, goal_update = payload
                return text, emotion, tts_text, events, analysis, promises, thought, goal_update, [], "", None
            if len(payload) == 7:
                text, emotion, tts_text, events, analysis, promises, thought = payload
                return text, emotion, tts_text, events, analysis, promises, thought, {}, [], "", None
            if len(payload) == 6:
                text, emotion, tts_text, events, analysis, promises = payload
                return text, emotion, tts_text, events, analysis, promises, "", {}, [], "", None
            if len(payload) == 5:
                text, emotion, tts_text, events, analysis = payload
                return text, emotion, tts_text, events, analysis, [], "", {}, [], "", None
            if len(payload) == 4:
                text, emotion, tts_text, events = payload
                return text, emotion, tts_text, events, {}, [], "", {}, [], "", None
        raise _UnsupportedResponseFormatError()

    def _ensure_image_input_supported(self):
        """이미지 입력 미지원 공급자에서 첨부 이미지를 조용히 버리지 않도록 막는다."""
        if getattr(self.llm_client, "supports_image_input", None) is False:
            raise _UnsupportedImageInputError()

    def run(self):
        self.response_metadata = ResponseDeliveryMetadata.empty()
        loop = None
        """스레드 실행"""
        try:
            if self._is_cancelled():
                return
            print(f"[AI Worker] request_started message_chars={_safe_text_length(self.message)}")

            # 비동기 메서드이므로 asyncio로 실행
            import asyncio

            # 새 이벤트 루프 생성 (워커 스레드용)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            events = []
            analysis = {}
            promises = []

            proactive_conversations = []
            gesture = ""

            if self.note_request and self.note_service and self.obsidian_manager:
                print("[AI Worker] /note 모드")
                response_payload = loop.run_until_complete(self._run_note_flow())
            elif self.diary_request and self.diary_service:
                print("[AI Worker] /diary 모드")
                response_payload = loop.run_until_complete(self._run_diary_flow())
            # 이미지가 있으면 멀티모달로 처리
            elif self.images:
                self._ensure_image_input_supported()
                print(f"[AI Worker] 이미지 {len(self.images)}개 포함 - 멀티모달 모드")
                response_payload = loop.run_until_complete(
                    self.llm_client.send_message_with_images(
                        self.message,
                        self.images,
                        self.memory_search_text,
                        self.latest_user_message,
                        self.recent_memory_context,
                        self.head_pat_count_before_message,
                        progress_callback=self.progress_callback,
                        mood_event_context=self.mood_event_context or None,
                        **(
                            {"include_life_record_context": True}
                            if self.include_life_record_context
                            else {}
                        ),
                    )
                )
                if self._is_cancelled():
                    return
                self._capture_response_delivery_metadata()
            elif self.use_memory and hasattr(self.llm_client, 'send_message_with_memory'):
                print("[AI Worker] 메모리 활용 모드")
                response_payload = loop.run_until_complete(
                    self.llm_client.send_message_with_memory(
                        self.message,
                        self.memory_search_text,
                        self.latest_user_message,
                        self.recent_memory_context,
                        self.head_pat_count_before_message,
                        progress_callback=self.progress_callback,
                        mood_event_context=self.mood_event_context or None,
                        **(
                            {"include_life_record_context": True}
                            if self.include_life_record_context
                            else {}
                        ),
                    )
                )
                if self._is_cancelled():
                    return
                self._capture_response_delivery_metadata()
            else:
                print("[AI Worker] 일반 모드 (메모리 없음)")
                response_payload = self.llm_client.send_message(
                    self.message,
                    mood_event_context=self.mood_event_context or None,
                )
                self._capture_response_delivery_metadata()

            if self._is_cancelled():
                return
            response_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture, mood_analysis = self._normalize_response_payload(
                response_payload
            )

            token_usage_payload = self._build_token_usage_payload()
            token_usage = json.loads(token_usage_payload)
            metadata = self.response_metadata
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
            print(
                "[AI Worker] response_completed "
                f"response_mode={response_mode} "
                f"schema_version={schema_version} "
                f"repair_performed={'true' if metadata.repair_performed is True else 'false'} "
                f"reply_chars={_safe_text_length(response_text)} "
                f"tts_chars={_safe_text_length(tts_text)} "
                f"thought_chars={_safe_text_length(thought)} "
                f"event_count={_safe_list_count(events)} "
                f"analysis_item_count={len(analysis) if type(analysis) is dict else 0} "
                f"promise_count={_safe_list_count(promises)} "
                f"goal_item_count={1 if type(goal_update) is dict and goal_update else 0} "
                f"proactive_count={_safe_list_count(proactive_conversations)} "
                f"input_tokens={token_usage.get('input_tokens')} "
                f"output_tokens={token_usage.get('output_tokens')} "
                f"total_tokens={token_usage.get('total_tokens')}"
            )

            # events도 함께 emit (signal에는 리스트로 전달 가능)
            if self._is_cancelled():
                return
            mood_analysis_payload = ""
            if mood_analysis is not None:
                try:
                    mood_analysis_payload = json.dumps(
                        mood_analysis,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                except Exception:
                    mood_analysis_payload = ""
            self.response_ready.emit(
                response_text,
                emotion,
                tts_text or "",
                events,
                json.dumps(analysis, ensure_ascii=False),
                token_usage_payload,
                promises,
                thought,
                json.dumps(goal_update or {}, ensure_ascii=False),
                proactive_conversations,
                gesture,
                mood_analysis_payload,
            )
        except BaseException as failure:
            if self._is_cancelled():
                return
            self.response_metadata = ResponseDeliveryMetadata.empty()
            exception_class = _safe_exception_class_name(failure)
            local_message = _local_validation_message(failure)
            category = "validation_error" if local_message is not None else "provider_error"
            public_error = local_message if local_message is not None else category
            print(f"[AI Worker] request_failed category={category} exception_class={exception_class}")
            if self._is_cancelled():
                return
            self.error_occurred.emit(public_error)
        finally:
            if loop is not None:
                loop.close()

    def _capture_response_delivery_metadata(self) -> None:
        """성공한 일반 응답의 요청 범위 메타데이터만 보관한다."""
        getter = getattr(self.llm_client, "get_last_response_delivery_metadata", None)
        if not callable(getter):
            return
        try:
            metadata = getter()
        except Exception:
            return
        if type(metadata) is ResponseDeliveryMetadata:
            self.response_metadata = metadata

    def _build_token_usage_payload(self) -> str:
        """최근 토큰 사용량을 JSON 문자열로 직렬화한다."""
        usage = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        getter = getattr(self.llm_client, "get_last_token_usage", None)
        if callable(getter):
            try:
                raw = getter()
            except Exception:
                raw = None
            if type(raw) is dict:
                usage = {
                    "input_tokens": raw.get("input_tokens") if is_valid_token_count(raw.get("input_tokens")) else None,
                    "output_tokens": raw.get("output_tokens") if is_valid_token_count(raw.get("output_tokens")) else None,
                    "total_tokens": raw.get("total_tokens") if is_valid_token_count(raw.get("total_tokens")) else None,
                }
        if self.prior_token_usage is not None:
            accumulator = TurnTokenUsageAccumulator()
            accumulator.record(self.prior_token_usage)
            accumulator.record(usage)
            usage = accumulator.snapshot()
        return json.dumps(usage, ensure_ascii=False)

    async def _run_diary_flow(self):
        """일기/문서 생성 전용 플로우."""
        if not hasattr(self.llm_client, "generate_markdown_document"):
            raise _UnsupportedDiaryError()

        markdown_text = await self.llm_client.generate_markdown_document(self.message)
        if self._is_cancelled():
            return None
        if self.use_obsidian_priority:
            result = self.diary_service.save_markdown_via_priority(self.diary_request, markdown_text)
        else:
            result = self.diary_service.save_markdown(self.diary_request, markdown_text)

        language = self._prompt_language()
        user_name = resolve_prompt_persona_names(
            settings_source=getattr(self.llm_client, "settings", None),
            language=language,
        ).user
        required = {
            "ko": "성공적으로 파일 작성에 완료되었습니다.",
            "en": "The file has been written successfully.",
            "ja": "ファイルの作成が正常に完了しました。",
        }.get(language, "성공적으로 파일 작성에 완료되었습니다.")
        if language == "en":
            completion_context = (
                f"Use the information below to tell {user_name} that the file has been written.\n"
                f"- The sentence must include this exact phrase: {required}\n"
                f"- Written Markdown file: {result.relative_path}\n"
                "[Written Markdown Body]\n"
                f"{result.content}"
            )
            completion_context += (
                "\n[Save Result]\n"
                f"- Target: {result.storage_target}\n"
                f"- Path: {result.absolute_path}"
            )
            obsidian_path_label = "Obsidian Path"
            note_label = "Note"
        elif language == "ja":
            completion_context = (
                f"次の情報をもとに、{user_name}へファイル作成完了を伝えてください。\n"
                f"- 文中に必ず次の文言を含めてください: {required}\n"
                f"- 作成されたmdファイル: {result.relative_path}\n"
                "[作成されたmdファイル本文]\n"
                f"{result.content}"
            )
            completion_context += (
                "\n[保存結果]\n"
                f"- 対象: {result.storage_target}\n"
                f"- パス: {result.absolute_path}"
            )
            obsidian_path_label = "Obsidianパス"
            note_label = "備考"
        else:
            completion_context = (
                f"아래 정보를 바탕으로 {user_name}에게 파일 작성 완료를 알려주세요.\n"
                f"- 문장 안에 반드시 다음 문구를 포함하세요: {required}\n"
                f"- 작성된 md 파일: {result.relative_path}\n"
                "[작성된 md 파일 본문]\n"
                f"{result.content}"
            )
            completion_context += (
                "\n[저장 결과]\n"
                f"- 대상: {result.storage_target}\n"
                f"- 경로: {result.absolute_path}"
            )
            obsidian_path_label = "Obsidian 경로"
            note_label = "비고"
        if result.obsidian_output_path and result.obsidian_output_path != result.absolute_path:
            completion_context += f"\n- {obsidian_path_label}: {result.obsidian_output_path}"
        if result.obsidian_cli_error:
            completion_context += f"\n- {note_label}: {result.obsidian_cli_error}"

        if hasattr(self.llm_client, "generate_diary_completion_reply"):
            completion_payload = await self.llm_client.generate_diary_completion_reply(
                completion_context
            )
            if self._is_cancelled():
                return None
            text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture, mood_analysis = self._normalize_response_payload(
                completion_payload
            )
            if required not in text:
                text = f"{required}\n{text}".strip()
            return text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture, mood_analysis

        # 하위 호환 폴백 (기존 클라이언트 경로)
        return self._normalize_response_payload(self.llm_client.send_message(completion_context))

    async def _run_note_flow(self):
        """Obsidian 계획 실행 전용 플로우."""
        if not hasattr(self.llm_client, "generate_note_command_plan"):
            raise _UnsupportedNotePlanError()
        if not hasattr(self.llm_client, "generate_note_execution_report"):
            raise _UnsupportedNoteReportError()

        obs_tree_lines = self.obsidian_manager.get_tree_lines(max_lines=120, allow_retry=False)
        checked_files = self.obsidian_manager.get_checked_file_contents(
            max_files=8,
            allow_retry=False,
        )
        plan_prompt = self.note_service.build_plan_prompt(
            user_instruction=self.note_request,
            obs_tree_lines=obs_tree_lines,
            checked_files=checked_files,
            recent_context=self.note_recent_context,
            language=self._prompt_language(),
        )
        plan_raw = await self.llm_client.generate_note_command_plan(plan_prompt)
        if self._is_cancelled():
            return None
        planner_error = ""
        plan = NotePlan(summary="요청 기반 실행", commands=[], stop_on_error=True)
        results: list[NoteCommandResult] = []
        try:
            plan = self.note_service.parse_plan(plan_raw)
            self.note_service.validate_plan(plan)
            results = self.note_service.execute_plan(self.obsidian_manager, plan)
        except Exception as e:
            planner_error = str(e)
            plan = NotePlan(summary=f"계획 오류 폴백: {planner_error[:120]}", commands=[], stop_on_error=True)

        # 문서 작성 요청이면 "실제 본문 쓰기 성공"이 확인될 때까지 보강한다.
        needs_document = self.note_service.is_document_generation_request(self.note_request)
        wrote_content = self.note_service.has_successful_content_writing_result(plan, results)
        if needs_document and not wrote_content:
            target = (
                self.note_service.extract_target_markdown_path(self.note_request)
                or self.note_service.extract_target_markdown_path_from_plan(plan)
                or self.note_service.build_generated_markdown_path(self.note_request)
            )
            if target:
                generated_markdown = await self.llm_client.generate_markdown_document(self.note_request)
                if self._is_cancelled():
                    return None
                if not (generated_markdown or "").strip():
                    generated_markdown = self.note_service.build_default_markdown(self.note_request, target)
                fallback_cmd = NoteCommand(
                    args=["create", f"path={target}", f"content={generated_markdown}", "overwrite"],
                    reason="문서 작성 보강: 본문이 없거나 쓰기 실패하여 create(content) 재시도",
                )
                completed = self.obsidian_manager.execute_cli_args(fallback_cmd.args)
                fallback_stdout = (completed.stdout or "").strip()
                fallback_stderr = (completed.stderr or "").strip()
                fallback_ok = completed.returncode == 0 and not self.note_service.has_cli_error_output(
                    fallback_stdout,
                    fallback_stderr,
                )
                fallback_result = NoteCommandResult(
                    args=fallback_cmd.args,
                    returncode=int(completed.returncode),
                    stdout=fallback_stdout[:5000],
                    stderr=fallback_stderr[:3000],
                    ok=fallback_ok,
                )
                plan = NotePlan(
                    summary=plan.summary + " + content-write-fallback",
                    commands=[*plan.commands, fallback_cmd],
                    stop_on_error=plan.stop_on_error,
                )
                results = [*results, fallback_result]
            elif not planner_error:
                if self.note_service.has_content_writing_command(plan):
                    planner_error = "본문 작성 명령이 실행됐지만 저장에 실패했고, 대체 저장 경로도 결정하지 못했습니다."
                else:
                    planner_error = "문서 작성 요청으로 감지됐지만 대상 .md 경로를 찾지 못했습니다."

        self.note_service.save_run_log(
            user_instruction=self.note_request,
            plan=plan,
            results=results,
            plan_raw=plan_raw,
            planner_error=planner_error,
        )
        report_context = self.note_service.build_report_context(
            user_instruction=self.note_request,
            plan=plan,
            results=results,
            planner_error=planner_error,
            language=self._prompt_language(),
        )
        report = await self.llm_client.generate_note_execution_report(report_context)
        if self._is_cancelled():
            return None
        return report


class TTSWorker(QThread):
    """TTS 생성 및 립싱크 분석을 비동기로 처리하는 워커 스레드"""

    tts_ready = pyqtSignal(bytes, list)  # (audio_data, lip_sync_data)
    error_occurred = pyqtSignal(str)

    def __init__(self, tts_client, text):
        super().__init__()
        self.tts_client = tts_client
        self.text = text
        self._cancellation_requested = False

    def requestInterruption(self) -> None:
        """스레드 시작 전 취소 요청도 잃지 않도록 함께 기록한다."""
        self._cancellation_requested = True
        super().requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancellation_requested or self.isInterruptionRequested()

    def run(self):
        loop = None
        """스레드 실행"""
        try:
            if self._is_cancelled():
                return
            import asyncio
            import os
            import tempfile
            from pathlib import Path
            from src.ai.audio_analyzer import AudioAnalyzer

            print(f"[TTS Worker] generation_started text_chars={_safe_text_length(self.text)}")

            # 새 이벤트 루프 생성
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # TTS API로 오디오 생성
            audio_data = loop.run_until_complete(
                self.tts_client.generate_speech(self.text)
            )
            if self._is_cancelled():
                return

            print(f"[TTS Worker] Audio generated: {len(audio_data) if type(audio_data) is bytes else 0} bytes")
            if self._is_cancelled():
                return

            temp_fd = None
            temp_path = None
            try:
                if self._is_cancelled():
                    return
                temp_fd, temp_path = tempfile.mkstemp(suffix=".wav")
                if self._is_cancelled():
                    return
                file_object = os.fdopen(temp_fd, "wb")
                temp_fd = None
                with file_object as file_handle:
                    file_handle.write(audio_data)

                if self._is_cancelled():
                    return
                try:
                    analyzer = AudioAnalyzer(frame_duration_ms=50)
                    lip_sync_data = analyzer.analyze(temp_path)
                    if self._is_cancelled():
                        return
                    print(f"[TTS Worker] Lip sync data: {_safe_list_count(lip_sync_data)} frames")
                except Exception as failure:
                    if self._is_cancelled():
                        return
                    print(
                        "[TTS Worker] lip_sync_failed "
                        "category=analysis_error "
                        f"exception_class={_safe_exception_class_name(failure)}"
                    )
                    lip_sync_data = []
            finally:
                if temp_fd is not None:
                    try:
                        os.close(temp_fd)
                    except Exception:
                        pass
                if temp_path is not None:
                    try:
                        Path(temp_path).unlink(missing_ok=True)
                    except Exception:
                        pass

            # 결과 전송
            if self._is_cancelled():
                return
            self.tts_ready.emit(audio_data, lip_sync_data)

        except BaseException as failure:
            if self._is_cancelled():
                return
            print(
                "[TTS Worker] generation_failed category=tts_error "
                f"exception_class={_safe_exception_class_name(failure)}"
            )
            if self._is_cancelled():
                return
            self.error_occurred.emit("tts_error")
        finally:
            if loop is not None:
                loop.close()


class StreamingTTSWorker(QThread):
    """HTTP chunked TTS를 PCM 청크 단위로 전달하는 워커 스레드."""

    stream_format_ready = pyqtSignal(int, int, int)  # (sample_rate, channels, sample_width)
    stream_chunk_ready = pyqtSignal(bytes, list)  # (pcm_bytes, mouth_values)
    stream_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, tts_client, text: str):
        super().__init__()
        self.tts_client = tts_client
        self.text = text
        self._stop_requested = False

    def request_stop(self):
        """다음 청크 경계에서 안전하게 스트림 처리를 중단한다."""
        self._stop_requested = True

    def run(self):
        loop = None
        try:
            import asyncio
            from src.ai.audio_analyzer import RealtimeLipSyncAnalyzer, StreamingWavDecoder

            print(f"[StreamingTTSWorker] stream_started text_chars={_safe_text_length(self.text)}")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _consume_stream():
                decoder = StreamingWavDecoder()
                analyzer = None
                format_emitted = False

                async for chunk in self.tts_client.stream_speech(self.text):
                    if self._stop_requested:
                        print("[StreamingTTSWorker] Stop requested before consuming next chunk")
                        break

                    audio_format, pcm_bytes = decoder.push(chunk)
                    if audio_format is not None and not format_emitted:
                        self.stream_format_ready.emit(
                            audio_format.sample_rate,
                            audio_format.channels,
                            audio_format.sample_width,
                        )
                        analyzer = RealtimeLipSyncAnalyzer(
                            sample_rate=audio_format.sample_rate,
                            channels=audio_format.channels,
                            sample_width=audio_format.sample_width,
                            frame_duration_ms=50,
                        )
                        format_emitted = True

                    if pcm_bytes and analyzer is not None:
                        mouth_values = analyzer.push_pcm(pcm_bytes)
                        self.stream_chunk_ready.emit(pcm_bytes, mouth_values)

                if analyzer is not None and not self._stop_requested:
                    tail_values = analyzer.finalize()
                    if tail_values:
                        self.stream_chunk_ready.emit(b"", tail_values)

            loop.run_until_complete(_consume_stream())
            self.stream_finished.emit()
        except Exception as e:
            print(
                f"[StreamingTTSWorker] stream_failed category=tts_stream_error exception_class={type(e).__name__}"
            )
            self.error_occurred.emit("tts_stream_error")
        finally:
            if loop is not None:
                loop.close()


class ObsidianTreeWorker(QThread):
    """Obsidian 트리 조회를 백그라운드에서 처리하는 워커."""

    tree_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, obsidian_manager, allow_retry: bool = False):
        super().__init__()
        self.obsidian_manager = obsidian_manager
        self.allow_retry = bool(allow_retry)
        self._cancellation_requested = False

    def requestInterruption(self) -> None:
        """스레드 시작 전 취소 요청도 잃지 않도록 함께 기록한다."""
        self._cancellation_requested = True
        super().requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancellation_requested or self.isInterruptionRequested()

    def run(self):
        if self._is_cancelled():
            return
        try:
            payload = self.obsidian_manager.get_tree_json(allow_retry=self.allow_retry)
            if self._is_cancelled():
                return
            self.tree_ready.emit(payload)
        except BaseException:
            if self._is_cancelled():
                return
            self.error_occurred.emit("obsidian_tree_error")


class ObsidianCheckedFilesWorker(QThread):
    """체크된 Obsidian 파일 본문 컨텍스트를 백그라운드에서 준비하는 워커."""

    context_ready = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, obsidian_manager, checked_files: list[str], language: str = "ko"):
        super().__init__()
        self.obsidian_manager = obsidian_manager
        self.checked_files = [str(path) for path in (checked_files or []) if str(path).strip()]
        self.language = resolve_prompt_language(language)
        self._cancellation_requested = False

    def requestInterruption(self) -> None:
        """스레드 시작 전 취소 요청도 잃지 않도록 함께 기록한다."""
        self._cancellation_requested = True
        super().requestInterruption()

    def _is_cancelled(self) -> bool:
        return self._cancellation_requested or self.isInterruptionRequested()

    def _build_signature_payload(self) -> str:
        """현재 워커가 읽는 체크 파일 목록을 직렬화한다."""
        return json.dumps(self.checked_files, ensure_ascii=False)

    def run(self):
        if self._is_cancelled():
            return
        signature_payload = self._build_signature_payload()
        if not self.checked_files:
            if self._is_cancelled():
                return
            self.context_ready.emit("", signature_payload)
            return

        try:
            checked_contents = self.obsidian_manager.get_checked_file_contents(
                max_files=8,
                checked_files=self.checked_files,
                allow_retry=False,
            )
            if self._is_cancelled():
                return
            context = build_obsidian_checked_context(checked_contents, self.language)
            if self._is_cancelled():
                return
            self.context_ready.emit(context, signature_payload)
        except BaseException:
            if self._is_cancelled():
                return
            self.error_occurred.emit("obsidian_checked_files_error", "")
