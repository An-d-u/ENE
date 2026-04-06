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
import re

from ..conversation_format import prepend_message_time, role_label_for_context
from ..ai.diary_service import DiaryService
from ..ai.note_service import NoteService, NoteCommand, NoteCommandResult, NotePlan
from ..ai.obsidian_manager import ObsidianManager
from .chat_attachments import (
    build_attachment_context_block,
    build_attachment_note,
    build_general_chat_prompt as compose_general_chat_prompt,
    prepare_attachments,
)
from .obs_settings import ObsSettings

VISIBLE_RESPONSE_ANALYSIS_KEYS = (
    "user_emotion",
    "user_intent",
    "interaction_effect",
    "bond_delta_hint",
    "stress_delta_hint",
    "energy_delta_hint",
    "valence_delta_hint",
    "confidence",
    "flags",
)


class AIWorker(QThread):
    """AI 응답을 비동기로 처리하는 워커 스레드"""
    
    response_ready = pyqtSignal(str, str, str, list, str, str)  # (텍스트, 감정, 일본어, 이벤트, analysis JSON, 토큰 JSON)
    error_occurred = pyqtSignal(str)  # 오류 메시지
    
    def __init__(
        self,
        llm_client,
        message,
        use_memory=True,
        images=None,
        memory_search_text: str = "",
        diary_request: str = "",
        note_request: str = "",
        note_recent_context: str = "",
        diary_service: DiaryService | None = None,
        note_service: NoteService | None = None,
        obsidian_manager=None,
        use_obsidian_priority: bool = False,
    ):
        super().__init__()
        self.llm_client = llm_client
        self.message = message
        self.use_memory = use_memory
        self.images = images or []  # 이미지 데이터 리스트
        self.memory_search_text = (memory_search_text or "").strip()
        self.diary_request = (diary_request or "").strip()
        self.note_request = (note_request or "").strip()
        self.note_recent_context = (note_recent_context or "").strip()
        self.diary_service = diary_service
        self.note_service = note_service
        self.obsidian_manager = obsidian_manager
        self.use_obsidian_priority = bool(use_obsidian_priority)

    def _normalize_response_payload(self, payload):
        """신구 응답 형식을 모두 5개 값으로 정규화한다."""
        if isinstance(payload, tuple):
            if len(payload) == 5:
                return payload
            if len(payload) == 4:
                text, emotion, japanese_text, events = payload
                return text, emotion, japanese_text, events, {}
        raise ValueError("지원하지 않는 응답 형식입니다.")
    
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
            analysis = {}

            if self.note_request and self.note_service and self.obsidian_manager:
                print("[AI Worker] /note 모드")
                response_text, emotion, japanese_text, events, analysis = self._normalize_response_payload(
                    loop.run_until_complete(self._run_note_flow())
                )
            elif self.diary_request and self.diary_service:
                print("[AI Worker] /diary 모드")
                response_text, emotion, japanese_text, events, analysis = self._normalize_response_payload(
                    loop.run_until_complete(self._run_diary_flow())
                )
            # 이미지가 있으면 멀티모달로 처리
            elif self.images:
                print(f"[AI Worker] 이미지 {len(self.images)}개 포함 - 멀티모달 모드")
                response_text, emotion, japanese_text, events, analysis = self._normalize_response_payload(
                    loop.run_until_complete(
                        self.llm_client.send_message_with_images(
                            self.message,
                            self.images,
                            self.memory_search_text,
                        )
                    )
                )
            elif self.use_memory and hasattr(self.llm_client, 'send_message_with_memory'):
                print(f"[AI Worker] 메모리 활용 모드")
                response_text, emotion, japanese_text, events, analysis = self._normalize_response_payload(
                    loop.run_until_complete(
                        self.llm_client.send_message_with_memory(
                            self.message,
                            self.memory_search_text,
                        )
                    )
                )
            else:
                print(f"[AI Worker] 일반 모드 (메모리 없음)")
                response_text, emotion, japanese_text, events, analysis = self._normalize_response_payload(
                    self.llm_client.send_message(self.message)
                )
            
            
            print(f"[AI Worker] Response: {response_text[:50]}... [{emotion}]")
            if japanese_text:
                print(f"[AI Worker] Japanese: {japanese_text[:30]}...")
            if events:
                print(f"[AI Worker] {len(events)}개 일정 추출")
            token_usage_payload = self._build_token_usage_payload()
            
            # events도 함께 emit (signal에는 리스트로 전달 가능)
            self.response_ready.emit(
                response_text,
                emotion,
                japanese_text or "",
                events,
                json.dumps(analysis, ensure_ascii=False),
                token_usage_payload,
            )
        except Exception as e:
            print(f"[AI Worker] Error: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))
        finally:
            if loop is not None:
                loop.close()

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
            if isinstance(raw, dict):
                usage = {
                    "input_tokens": raw.get("input_tokens") if isinstance(raw.get("input_tokens"), int) else None,
                    "output_tokens": raw.get("output_tokens") if isinstance(raw.get("output_tokens"), int) else None,
                    "total_tokens": raw.get("total_tokens") if isinstance(raw.get("total_tokens"), int) else None,
                }
        return json.dumps(usage, ensure_ascii=False)

    async def _run_diary_flow(self):
        """일기/문서 생성 전용 플로우."""
        if not hasattr(self.llm_client, "generate_markdown_document"):
            raise RuntimeError("현재 LLM 클라이언트는 /diary를 지원하지 않습니다.")

        markdown_text = await self.llm_client.generate_markdown_document(self.message)
        if self.use_obsidian_priority:
            result = self.diary_service.save_markdown_via_priority(self.diary_request, markdown_text)
        else:
            result = self.diary_service.save_markdown(self.diary_request, markdown_text)

        completion_context = (
            "아래 정보를 바탕으로 마스터에게 파일 작성 완료를 알려주세요.\n"
            "- 문장 안에 반드시 다음 문구를 포함하세요: 성공적으로 파일 작성에 완료되었습니다.\n"
            f"- 작성된 md 파일: {result.relative_path}\n"
            "[작성된 md 파일 본문]\n"
            f"{result.content}"
        )
        completion_context += (
            "\n[저장 결과]\n"
            f"- 대상: {result.storage_target}\n"
            f"- 경로: {result.absolute_path}"
        )
        if result.obsidian_output_path and result.obsidian_output_path != result.absolute_path:
            completion_context += f"\n- Obsidian 경로: {result.obsidian_output_path}"
        if result.obsidian_cli_error:
            completion_context += f"\n- 비고: {result.obsidian_cli_error}"

        if hasattr(self.llm_client, "generate_diary_completion_reply"):
            text, emotion, japanese_text, events, analysis = self._normalize_response_payload(
                await self.llm_client.generate_diary_completion_reply(completion_context)
            )
            required = "성공적으로 파일 작성에 완료되었습니다."
            if required not in text:
                text = f"{required}\n{text}".strip()
            return text, emotion, japanese_text, events, analysis

        # 하위 호환 폴백 (기존 클라이언트 경로)
        return self._normalize_response_payload(self.llm_client.send_message(completion_context))

    async def _run_note_flow(self):
        """Obsidian 계획 실행 전용 플로우."""
        if not hasattr(self.llm_client, "generate_note_command_plan"):
            raise RuntimeError("현재 LLM 클라이언트는 /note 계획 생성을 지원하지 않습니다.")
        if not hasattr(self.llm_client, "generate_note_execution_report"):
            raise RuntimeError("현재 LLM 클라이언트는 /note 결과 보고 생성을 지원하지 않습니다.")

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
        )
        plan_raw = await self.llm_client.generate_note_command_plan(plan_prompt)
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
        )
        return await self.llm_client.generate_note_execution_report(report_context)


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


class ObsidianTreeWorker(QThread):
    """Obsidian 트리 조회를 백그라운드에서 처리하는 워커."""

    tree_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, obsidian_manager, allow_retry: bool = False):
        super().__init__()
        self.obsidian_manager = obsidian_manager
        self.allow_retry = bool(allow_retry)

    def run(self):
        try:
            payload = self.obsidian_manager.get_tree_json(allow_retry=self.allow_retry)
            self.tree_ready.emit(payload)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ObsidianCheckedFilesWorker(QThread):
    """체크된 Obsidian 파일 본문 컨텍스트를 백그라운드에서 준비하는 워커."""

    context_ready = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, obsidian_manager, checked_files: list[str]):
        super().__init__()
        self.obsidian_manager = obsidian_manager
        self.checked_files = [str(path) for path in (checked_files or []) if str(path).strip()]

    def _build_signature_payload(self) -> str:
        """현재 워커가 읽는 체크 파일 목록을 직렬화한다."""
        return json.dumps(self.checked_files, ensure_ascii=False)

    def run(self):
        signature_payload = self._build_signature_payload()
        if not self.checked_files:
            self.context_ready.emit("", signature_payload)
            return

        try:
            checked_contents = self.obsidian_manager.get_checked_file_contents(
                max_files=8,
                allow_retry=False,
            )
            parts: list[str] = []
            if checked_contents:
                parts.append("[Obsidian 체크된 파일 본문]")
                for rel, content in checked_contents:
                    parts.append(f"[파일:{rel}]")
                    parts.append(content)
            self.context_ready.emit("\n".join(parts), signature_payload)
        except Exception as e:
            self.error_occurred.emit(str(e), signature_payload)


class WebBridge(QObject):
    """Python과 JavaScript 간 통신 브릿지"""
    
    # Python -> JavaScript 시그널
    message_received = pyqtSignal(str, str)  # (텍스트, 감정)
    expression_changed = pyqtSignal(str)     # 표정 변경
    lip_sync_update = pyqtSignal(float)      # 립싱크 업데이트 (mouth_value)
    speech_state_changed = pyqtSignal(str, float)  # (speech state, intensity)
    performance_state_changed = pyqtSignal(str)  # performance state
    reroll_state_changed = pyqtSignal(bool)  # 리롤 응답 교체 모드 on/off
    summary_notice = pyqtSignal(str, str)    # (메시지, 레벨)
    mood_changed = pyqtSignal(str, float, float, float, float, str)  # (라벨, valence, energy, bond, stress, 단기 분위기)
    obs_tree_updated = pyqtSignal(str)       # Obsidian 트리 JSON
    attachment_preview_ready = pyqtSignal(str)  # 첨부 프리뷰 메타데이터 JSON
    token_usage_ready = pyqtSignal(str)  # 토큰 사용량 JSON
    
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.llm_client = None
        self.memory_manager = None
        self.worker = None
        self.settings = settings
        self.mood_manager = None
        self.diary_service = DiaryService("diary", settings=settings)
        self.note_service = NoteService("note_runs")
        self.obs_settings = ObsSettings("obs_config.json")
        self.obsidian_manager = ObsidianManager(settings=self.settings, obs_settings=self.obs_settings)
        self.obs_panel_window = None
        self._settings_dialog_opener = None
        self.obs_tree_worker = None
        self.obs_tree_retry_timer = QTimer(self)
        self.obs_tree_retry_timer.setSingleShot(True)
        self.obs_tree_retry_timer.timeout.connect(self._retry_obs_tree_refresh)
        self._obs_tree_retry_remaining = 0
        self._cached_obs_tree_json = json.dumps(
            {"ok": True, "nodes": [], "checked_files": self.obs_settings.get_checked_files()},
            ensure_ascii=False
        )
        self._cached_checked_files_context = ""
        self._cached_checked_files_signature: tuple[str, ...] = tuple()
        self.obs_checked_files_worker = None
        self._obsidian_integration_activated = False
        self._pending_attachment_cache: dict[str, dict] = {}
        self._session_attachment_documents: list[dict] = []
        
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
        self.pending_token_usage_payload = ""
        self._tts_interrupted_for_ptt = False
        
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
                str(snapshot.get("temporary_state", "steady")),
            )
        except Exception as e:
            print(f"[Bridge] mood_changed emit 실패: {e}")

    def _reset_pending_ui_state(self, notice: str | None = None):
        """
        프런트가 로딩 상태로 고정되지 않도록 pending UI 상태를 강제로 해제한다.
        주로 reroll/edit 조기 종료 경로에서 사용한다.
        """
        self._is_rerolling = False
        self.reroll_state_changed.emit(False)
        if notice:
            self.summary_notice.emit(notice, "info")
    
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

    def set_obs_panel_window(self, panel_window):
        """Obsidian 플로팅 패널 참조를 등록한다."""
        self.obs_panel_window = panel_window

    def set_settings_dialog_opener(self, opener):
        """설정창을 여는 콜백을 등록한다."""
        self._settings_dialog_opener = opener if callable(opener) else None

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

    def _emit_performance_state(self, state: str):
        """연기 엔진용 상태 신호를 JS로 보낸다."""
        try:
            self.performance_state_changed.emit(str(state or "idle"))
        except Exception as e:
            print(f"[Bridge] performance_state_changed emit 실패: {e}")

    def _emit_speech_state(self, state: str, intensity: float = 0.0):
        """연기 엔진용 음성 상태 신호를 JS로 보낸다."""
        try:
            self.speech_state_changed.emit(str(state or "idle"), float(intensity))
        except Exception as e:
            print(f"[Bridge] speech_state_changed emit 실패: {e}")

    def _start_ai_worker(
        self,
        message_with_time: str,
        images_data: list | None = None,
        memory_search_text: str = "",
    ):
        """Start AI worker with current payload."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()

        self.worker = AIWorker(
            self.llm_client,
            message_with_time,
            images=images_data or [],
            memory_search_text=memory_search_text,
        )
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _start_diary_worker(self, diary_request: str, message_with_time: str, use_obsidian_priority: bool = False):
        """Start /diary worker with isolated context."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()

        self.worker = AIWorker(
            self.llm_client,
            message_with_time,
            diary_request=diary_request,
            diary_service=self.diary_service,
            use_obsidian_priority=use_obsidian_priority,
        )
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    def _start_note_worker(self, note_request: str, message_with_time: str, note_recent_context: str = ""):
        """Start /note worker."""
        if self.worker and self.worker.isRunning():
            print("[Bridge] Worker still running, waiting...")
            self.worker.wait()

        self.worker = AIWorker(
            self.llm_client,
            message_with_time,
            note_request=note_request,
            note_recent_context=note_recent_context,
            note_service=self.note_service,
            obsidian_manager=self.obsidian_manager,
        )
        self.worker.response_ready.connect(self._on_response_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

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
            role_label = "마스터" if role == "user" else "에네" if role == "assistant" else role
            prefix = f"[{ts}][{role_label}]" if ts else f"[{role_label}]"
            lines.append(f"{prefix} {text}")
        return "\n".join(lines).strip()

    def _handle_diary_command(self, message: str) -> bool:
        """'/diary' 명령을 감지해 로컬 저장 전용 처리한다."""
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

        self._start_diary_worker(diary_body, message_with_time, use_obsidian_priority=False)
        print("[Bridge] /diary worker thread started")
        return True

    def _handle_note_command(self, message: str) -> bool:
        """/note 명령을 감지해 계획-실행-보고 플로우를 처리한다."""
        is_note, note_body = self.diary_service.parse_note_command(message)
        if not is_note:
            return False

        self._mark_user_activity()
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        if not note_body:
            self.message_received.emit("`/note` 뒤에 실행할 내용을 함께 입력해 주세요.", "confused")
            return True

        self._activate_obsidian_integration()
        timestamp = self._now_timestamp()
        message_with_time = f"[현재 시각: {timestamp}]\n{note_body}"
        self._last_request_payload = None
        self._is_rerolling = False

        use_recent_context, recent_turns = self._resolve_note_context_settings()
        note_recent_context = self._build_note_recent_context(recent_turns) if use_recent_context else ""

        self._start_note_worker(note_body, message_with_time, note_recent_context)
        print("[Bridge] /note worker thread started")
        return True

    def _build_obsidian_context_block(self, include_tree: bool = True, include_checked_files: bool = True) -> str:
        """Obsidian 트리/체크 파일 컨텍스트 블록을 생성한다."""
        parts: list[str] = []
        if include_tree:
            parts.append("[Obsidian 트리 구조]")
            for line in self.obsidian_manager.get_tree_lines(max_lines=120):
                parts.append(f"- {line}")

        if include_checked_files:
            checked_limits = self._resolve_obsidian_checked_file_limits()
            checked_contents = self.obsidian_manager.get_checked_file_contents(
                max_files=8,
                max_chars_per_file=checked_limits["max_chars_per_file"],
                total_max_chars=checked_limits["total_max_chars"],
                allow_retry=False,
            )
            if checked_contents:
                parts.append("[Obsidian 체크된 파일 본문]")
                for rel, content in checked_contents:
                    parts.append(f"[파일:{rel}]")
                    parts.append(content)
        return "\n".join(parts)

    def _resolve_obsidian_checked_file_limits(self) -> dict[str, int]:
        """체크된 Obsidian 파일 컨텍스트 길이 제한을 설정값에서 읽는다."""
        max_chars_per_file = 3000
        total_max_chars = 12000

        if self.settings:
            try:
                max_chars_per_file = int(self.settings.get("obsidian_checked_max_chars_per_file", 3000) or 3000)
            except Exception:
                max_chars_per_file = 3000
            try:
                total_max_chars = int(self.settings.get("obsidian_checked_total_max_chars", 12000) or 12000)
            except Exception:
                total_max_chars = 12000

        return {
            "max_chars_per_file": max(100, min(max_chars_per_file, 200000)),
            "total_max_chars": max(100, min(total_max_chars, 1000000)),
        }

    def _get_checked_files_signature(self) -> tuple[str, ...]:
        """현재 체크된 Obsidian 파일 목록 시그니처를 반환한다."""
        return tuple(self.obs_settings.get_checked_files())

    def _decode_checked_files_signature(self, signature_payload: str) -> tuple[str, ...]:
        """직렬화된 체크 파일 시그니처를 튜플로 복원한다."""
        try:
            parsed = json.loads(signature_payload or "[]")
        except Exception:
            return tuple()
        if not isinstance(parsed, list):
            return tuple()
        return tuple(str(path) for path in parsed if str(path).strip())

    def _schedule_checked_files_context_refresh(self, force: bool = False):
        """일반 채팅용 체크 파일 컨텍스트를 백그라운드에서 갱신한다."""
        if not self._obsidian_integration_activated:
            return

        signature = self._get_checked_files_signature()
        if not signature:
            self._cached_checked_files_context = ""
            self._cached_checked_files_signature = tuple()
            return

        if self.obs_checked_files_worker and self.obs_checked_files_worker.isRunning():
            return

        if not force and signature == self._cached_checked_files_signature and self._cached_checked_files_context:
            return

        self.obs_checked_files_worker = ObsidianCheckedFilesWorker(
            self.obsidian_manager,
            list(signature),
        )
        self.obs_checked_files_worker.context_ready.connect(self._on_checked_files_context_ready)
        self.obs_checked_files_worker.error_occurred.connect(self._on_checked_files_context_error)
        self.obs_checked_files_worker.start()

    def _get_cached_checked_files_context(self) -> str:
        """전송 경로에서 사용할 체크 파일 컨텍스트 스냅샷을 반환한다."""
        if not self._obsidian_integration_activated:
            return ""

        signature = self._get_checked_files_signature()
        if not signature:
            self._cached_checked_files_context = ""
            self._cached_checked_files_signature = tuple()
            return ""

        if signature != self._cached_checked_files_signature:
            self._schedule_checked_files_context_refresh(force=True)
            return ""

        return self._cached_checked_files_context

    def _invalidate_checked_files_context_cache(self):
        """체크 파일 내용이 바뀐 뒤 기존 스냅샷을 무효화한다."""
        self._cached_checked_files_context = ""
        self._cached_checked_files_signature = tuple()

    def _on_checked_files_context_ready(self, context: str, signature_payload: str):
        """백그라운드에서 준비된 체크 파일 컨텍스트를 캐시에 반영한다."""
        signature = self._decode_checked_files_signature(signature_payload)
        current_signature = self._get_checked_files_signature()
        if signature != current_signature:
            self._schedule_checked_files_context_refresh(force=True)
            return
        self._cached_checked_files_context = context
        self._cached_checked_files_signature = signature

    def _on_checked_files_context_error(self, error_msg: str, signature_payload: str):
        """체크 파일 캐시 갱신 실패를 기록하고, 필요하면 다시 시도한다."""
        print(f"[Bridge] 체크 파일 컨텍스트 갱신 실패: {error_msg}")
        signature = self._decode_checked_files_signature(signature_payload)
        if signature != self._get_checked_files_signature():
            self._schedule_checked_files_context_refresh(force=True)

    def _build_general_chat_prompt(self, message: str, attachment_context: str = "") -> str:
        """
        일반 채팅 프롬프트를 구성한다.
        체크된 파일 본문과 이번 턴 첨부 자료만 현재 요청에 포함한다.
        """
        obs_context = self._get_cached_checked_files_context().strip()
        return compose_general_chat_prompt(
            message,
            obsidian_context=obs_context,
            attachment_context=str(attachment_context or "").strip(),
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
        current = str(current_message or "").strip()
        turns = self._resolve_memory_search_turns()
        entries = list(self.conversation_buffer or [])
        if turns > 0:
            entries = entries[-(turns * 2):]

        lines: list[str] = []
        for item in entries:
            if not item or len(item) < 2:
                continue
            role = str(item[0]).strip().lower()
            text = str(item[1] or "").strip()
            if not text:
                continue
            timestamp = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
            role_label = role_label_for_context(role)
            lines.append(prepend_message_time(f"[{role_label}] {text}", timestamp))

        if current:
            lines.append(prepend_message_time(f"[현재 사용자 메시지] {current}", current_timestamp))

        return "\n".join(lines).strip()

    def _attachment_model_name(self) -> str:
        """첨부 토큰 추정에 사용할 현재 모델명을 가져온다."""
        if not self.llm_client:
            return ""
        return str(getattr(self.llm_client, "model_name", "") or "")

    def _prepare_attachment_payload(self, attachments_data: list[dict]) -> list[dict]:
        """첨부 원본 페이로드를 분석 가능한 메타데이터로 변환한다."""
        return prepare_attachments(attachments_data, model_name=self._attachment_model_name())

    def _cache_prepared_attachments(self, prepared_attachments: list[dict]):
        """프리뷰 단계에서 준비한 첨부 메타데이터를 임시 캐시에 저장한다."""
        for item in prepared_attachments or []:
            attachment_id = str((item or {}).get("id", "")).strip()
            if attachment_id:
                self._pending_attachment_cache[attachment_id] = item

    def _resolve_prepared_attachments(self, attachments_data: list[dict]) -> list[dict]:
        """캐시가 있으면 재사용하고, 없으면 즉시 분석한다."""
        items = list(attachments_data or [])
        if not items:
            return []

        if any(not str((item or {}).get("id", "")).strip() for item in items):
            prepared = self._prepare_attachment_payload(items)
            self._cache_prepared_attachments(prepared)
            return prepared

        missing: list[dict] = []
        prepared_by_id: dict[str, dict] = {}

        for raw in items:
            attachment_id = str((raw or {}).get("id", "")).strip()
            cached = self._pending_attachment_cache.get(attachment_id)
            if cached and cached.get("dataUrl") == raw.get("dataUrl"):
                prepared_by_id[attachment_id] = cached
            else:
                missing.append(raw)

        if missing:
            fresh = self._prepare_attachment_payload(missing)
            self._cache_prepared_attachments(fresh)
            for item in fresh:
                attachment_id = str((item or {}).get("id", "")).strip()
                if attachment_id:
                    prepared_by_id[attachment_id] = item

        resolved: list[dict] = []
        for raw in items:
            attachment_id = str((raw or {}).get("id", "")).strip()
            item = prepared_by_id.get(attachment_id)
            if item:
                resolved.append(item)
        return resolved

    def _build_attachment_preview_payload(self, prepared_attachments: list[dict]) -> str:
        """프런트 프리뷰 갱신용 최소 메타데이터만 JSON으로 직렬화한다."""
        payload = []
        for item in prepared_attachments or []:
            payload.append(
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                    "category": item.get("category", ""),
                    "tokenEstimate": int(item.get("tokenEstimate", 0) or 0),
                    "width": int(item.get("width", 0) or 0),
                    "height": int(item.get("height", 0) or 0),
                    "status": item.get("status", "ready"),
                    "error": item.get("error", ""),
                }
            )
        return json.dumps(payload, ensure_ascii=False)

    def _upsert_session_documents(self, prepared_attachments: list[dict]):
        """전송이 완료된 문서 첨부를 현재 세션 참고 자료로 유지한다."""
        for item in prepared_attachments or []:
            if str(item.get("category", "")) != "document":
                continue
            if str(item.get("status", "ready")) != "ready":
                continue

            normalized_name = str(item.get("name", "")).strip().casefold()
            if not normalized_name:
                continue

            document_entry = {
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "category": "document",
                "tokenEstimate": int(item.get("tokenEstimate", 0) or 0),
                "extractedText": item.get("extractedText", ""),
                "_name_key": normalized_name,
            }

            replaced = False
            for index, existing in enumerate(self._session_attachment_documents):
                if str(existing.get("_name_key", "")) == normalized_name:
                    self._session_attachment_documents[index] = document_entry
                    replaced = True
                    break
            if not replaced:
                self._session_attachment_documents.append(document_entry)

    def _parse_obs_subcommand(self, body: str) -> tuple[str, dict]:
        """
        /obs 하위 명령 파싱.
        지원 형식:
        - summarize <path.md>
        - read <path.md>
        - append <path.md> :: <text>
        - replace <path.md> :: <before> => <after>
        """
        raw = (body or "").strip()
        low = raw.lower()

        m = re.match(r"^summarize\s+(.+\.md)\s*$", raw, re.IGNORECASE)
        if m:
            return "summarize", {"path": m.group(1).strip()}

        m = re.match(r"^read\s+(.+\.md)\s*$", raw, re.IGNORECASE)
        if m:
            return "read", {"path": m.group(1).strip()}

        m = re.match(r"^append\s+(.+\.md)\s*::\s*([\s\S]+)$", raw, re.IGNORECASE)
        if m:
            return "append", {"path": m.group(1).strip(), "content": m.group(2).strip()}

        m = re.match(r"^replace\s+(.+\.md)\s*::\s*([\s\S]+?)\s*=>\s*([\s\S]+)$", raw, re.IGNORECASE)
        if m:
            return "replace", {"path": m.group(1).strip(), "before": m.group(2), "after": m.group(3)}

        # 한국어 요약 자연어 최소 지원: "test.md 파일 요약좀"
        m = re.search(r"([^\s]+\.md).*(요약|정리)", raw, re.IGNORECASE)
        if m:
            return "summarize", {"path": m.group(1).strip()}

        return "ask", {"instruction": raw, "low": low}

    def _handle_obs_command(self, message: str) -> bool:
        """'/obs' 명령을 감지해 Obsidian 명령/질의를 처리한다."""
        is_obs, obs_body = self.diary_service.parse_obs_command(message)
        if not is_obs:
            return False

        self._mark_user_activity()
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        if not obs_body:
            self.message_received.emit("`/obs` 뒤에 작성할 내용을 함께 입력해 주세요.", "confused")
            return True

        self._activate_obsidian_integration()
        command, payload = self._parse_obs_subcommand(obs_body)
        self._last_request_payload = None
        self._is_rerolling = False

        # 명령형: read/append/replace는 로컬에서 즉시 처리
        if command == "read":
            try:
                text = self.obsidian_manager.read_file(payload["path"])
                preview = text[:4000]
                if len(text) > len(preview):
                    preview += "\n...(생략)"
                self.message_received.emit(preview, "normal")
            except Exception as e:
                self.message_received.emit(f"파일 읽기 실패: {e}", "confused")
            return True

        if command == "append":
            result = self.obsidian_manager.append_file(payload["path"], payload["content"], create_if_missing=True)
            if result.ok:
                self._invalidate_checked_files_context_cache()
                self.message_received.emit(f"추가 완료: {result.path}", "smile")
            else:
                self.message_received.emit(f"추가 실패: {result.message}", "confused")
            return True

        if command == "replace":
            result = self.obsidian_manager.replace_in_file(payload["path"], payload["before"], payload["after"])
            if result.ok:
                self._invalidate_checked_files_context_cache()
                self.message_received.emit(f"교체 완료: {result.path}", "smile")
            else:
                self.message_received.emit(f"교체 실패: {result.message}", "confused")
            return True

        # summarize/ask: Obsidian 컨텍스트 포함하여 LLM 질의
        timestamp = self._now_timestamp()
        obs_context = self._build_obsidian_context_block(include_tree=True, include_checked_files=True)
        if command == "summarize":
            try:
                target = self.obsidian_manager.read_file(payload["path"])
            except Exception as e:
                self.message_received.emit(f"요약 대상 파일 읽기 실패: {e}", "confused")
                return True
            prompt = (
                f"{obs_context}\n\n"
                f"[요약 대상 파일: {payload['path']}]\n{target}\n\n"
                "위 파일을 핵심만 간결히 요약해 주세요."
            )
        else:
            prompt = f"{obs_context}\n\n[OBS 지시사항]\n{payload.get('instruction', obs_body)}"

        message_with_time = f"[현재 시각: {timestamp}]\n{prompt}"
        self._start_ai_worker(message_with_time)
        print("[Bridge] /obs AI worker thread started")
        return True

    @pyqtSlot(result=str)
    def get_obs_tree_json(self) -> str:
        """JS에서 호출: Obsidian 트리 구조를 JSON으로 반환."""
        # UI 블로킹을 피하기 위해 캐시를 즉시 반환하고 백그라운드 갱신을 시작한다.
        self._start_obs_tree_refresh()
        return self._cached_obs_tree_json

    @pyqtSlot(result=str)
    def get_obs_checked_files_json(self) -> str:
        """JS에서 호출: 체크된 파일 목록 반환."""
        try:
            files = self.obs_settings.get_checked_files()
            return json.dumps({"checked_files": files}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"checked_files": [], "error": str(e)}, ensure_ascii=False)

    @pyqtSlot(str, bool)
    def set_obs_file_checked(self, rel_path: str, checked: bool):
        """JS에서 호출: 파일 체크 상태를 저장한다."""
        try:
            self.obs_settings.set_file_checked(rel_path, bool(checked))
            # 체크 상태 변경은 CLI 재호출 없이 캐시에 즉시 반영해 UI 지연을 줄인다.
            self._emit_obs_tree_with_updated_checked_files()
            self._schedule_checked_files_context_refresh(force=True)
        except Exception as e:
            print(f"[Bridge] set_obs_file_checked failed: {e}")

    @pyqtSlot()
    def refresh_obs_tree(self):
        """JS에서 호출: 트리를 새로고침한다."""
        self._activate_obsidian_integration()
        self._start_obs_tree_refresh(allow_retry=False, retry_sequence=False)

    @pyqtSlot()
    def toggle_obs_panel(self):
        """JS에서 호출: Obsidian 플로팅 패널 표시를 토글한다."""
        panel = self.obs_panel_window
        if panel is None:
            print("[Bridge] toggle_obs_panel ignored: panel window not attached")
            return

        try:
            if panel.isVisible():
                panel.hide()
                self.obs_tree_retry_timer.stop()
                self._obs_tree_retry_remaining = 0
                self.obs_settings.set("panel_visible", False)
                self.obs_settings.save()
            else:
                self._activate_obsidian_integration()
                if hasattr(panel, "_ensure_visible_on_screen"):
                    panel._ensure_visible_on_screen()
                panel.show()
                panel.raise_()
                panel.activateWindow()
                self.obs_settings.set("panel_visible", True)
                self.obs_settings.save()
                # 표시를 먼저 완료하고 트리는 백그라운드에서 갱신한다.
                QTimer.singleShot(0, lambda: self._start_obs_tree_refresh(allow_retry=False, retry_sequence=True))
        except Exception as e:
            print(f"[Bridge] toggle_obs_panel failed: {e}")

    @pyqtSlot()
    def open_settings_dialog(self):
        """JS에서 호출: 기존 설정창을 연다."""
        if callable(self._settings_dialog_opener):
            self._settings_dialog_opener()

    def _start_obs_tree_refresh(self, allow_retry: bool = False, retry_sequence: bool = False):
        """Obsidian 트리 갱신을 백그라운드 워커로 실행한다."""
        if self.obs_tree_worker and self.obs_tree_worker.isRunning():
            return
        if retry_sequence:
            self._obs_tree_retry_remaining = 3
        elif not self.obs_tree_retry_timer.isActive():
            self._obs_tree_retry_remaining = 0

        self.obs_tree_worker = ObsidianTreeWorker(self.obsidian_manager, allow_retry=allow_retry)
        self.obs_tree_worker.tree_ready.connect(self._on_obs_tree_ready)
        self.obs_tree_worker.error_occurred.connect(self._on_obs_tree_error)
        self.obs_tree_worker.start()

    def _activate_obsidian_integration(self):
        """사용자가 Obsidian 기능을 처음 요청한 뒤부터만 연동을 활성화한다."""
        if self._obsidian_integration_activated:
            return
        self._obsidian_integration_activated = True

    def _retry_obs_tree_refresh(self):
        if self._obs_tree_retry_remaining <= 0:
            return
        panel = self.obs_panel_window
        if panel is None or not panel.isVisible():
            self._obs_tree_retry_remaining = 0
            return
        self._start_obs_tree_refresh(allow_retry=False, retry_sequence=False)

    def _schedule_obs_tree_retry_if_needed(self):
        panel = self.obs_panel_window
        if self._obs_tree_retry_remaining > 0 and panel is not None and panel.isVisible():
            self._obs_tree_retry_remaining -= 1
            self.obs_tree_retry_timer.start(30_000)

    def _on_obs_tree_ready(self, tree_json: str):
        try:
            parsed = json.loads(tree_json or "{}")
        except Exception:
            parsed = {}
        ok = isinstance(parsed, dict) and bool(parsed.get("ok"))
        if ok:
            self.obs_tree_retry_timer.stop()
            self._obs_tree_retry_remaining = 0
        self._cached_obs_tree_json = tree_json
        self.obs_tree_updated.emit(tree_json)
        if ok:
            self._schedule_checked_files_context_refresh()
        if not ok:
            self._schedule_obs_tree_retry_if_needed()

    def _on_obs_tree_error(self, error_msg: str):
        payload = json.dumps({"ok": False, "error": f"Obsidian 트리 갱신 실패: {error_msg}", "nodes": []}, ensure_ascii=False)
        self._cached_obs_tree_json = payload
        self.obs_tree_updated.emit(payload)
        self._schedule_obs_tree_retry_if_needed()

    def _emit_obs_tree_with_updated_checked_files(self):
        checked = self.obs_settings.get_checked_files()
        try:
            parsed = json.loads(self._cached_obs_tree_json or "{}")
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception:
            parsed = {}

        if "ok" not in parsed:
            parsed["ok"] = True
        parsed["checked_files"] = checked
        if "nodes" not in parsed:
            parsed["nodes"] = []

        payload = json.dumps(parsed, ensure_ascii=False)
        self._cached_obs_tree_json = payload
        self.obs_tree_updated.emit(payload)
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

        if self._handle_note_command(message):
            return

        if self._handle_obs_command(message):
            return

        if self._handle_diary_command(message):
            return

        timestamp = self._now_timestamp()
        prompt = self._build_general_chat_prompt(message)
        message_with_time = f"[현재 시각: {timestamp}]\n{prompt}"
        memory_search_text = self._build_memory_search_text(message, timestamp)
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
            "attachment_context": "",
            "memory_search_text": memory_search_text,
        }
        self._is_rerolling = False

        self._emit_performance_state("thinking")
        self._start_ai_worker(message_with_time, memory_search_text=memory_search_text)
        print("[Bridge] Worker thread started")

    @pyqtSlot(str, str)
    def send_to_ai_with_images(self, message: str, images_json: str):
        """기존 이미지 전송 진입점을 일반 첨부 전송 경로로 연결한다."""
        try:
            images_data = json.loads(images_json)
        except Exception:
            images_data = []

        attachments = []
        for index, image in enumerate(images_data):
            attachments.append(
                {
                    "id": str((image or {}).get("id", "")).strip() or f"legacy-image-{index}",
                    "name": str((image or {}).get("name", "")).strip() or f"image-{index + 1}.png",
                    "type": str((image or {}).get("type", "")).strip() or "image/png",
                    "dataUrl": str((image or {}).get("dataUrl", "")).strip(),
                }
            )
        self.send_to_ai_with_attachments(message, json.dumps(attachments, ensure_ascii=False))

    @pyqtSlot(str)
    def preview_attachments(self, attachments_json: str):
        """프런트가 첨부 미리보기 옆에 표시할 메타데이터를 계산한다."""
        try:
            attachments_data = json.loads(attachments_json) if attachments_json else []
        except Exception as e:
            print(f"[Bridge] Failed to parse preview attachments: {e}")
            self.attachment_preview_ready.emit("[]")
            return

        prepared = self._prepare_attachment_payload(attachments_data)
        self._cache_prepared_attachments(prepared)
        self.attachment_preview_ready.emit(self._build_attachment_preview_payload(prepared))

    @pyqtSlot(str, str)
    def send_to_ai_with_attachments(self, message: str, attachments_json: str):
        """JavaScript에서 호출: 이미지/문서 첨부를 포함한 메시지를 AI로 전송."""
        print("[Bridge] Received message with attachments from JS")

        if not self.llm_client:
            print("[Bridge] LLM client not initialized")
            self.message_received.emit("AI가 초기화되지 않았어요.", "sad")
            return

        try:
            attachments_data = json.loads(attachments_json) if attachments_json else []
            print(f"[Bridge] Parsed {len(attachments_data)} attachments")
        except Exception as e:
            print(f"[Bridge] Failed to parse attachments: {e}")
            attachments_data = []

        prepared_attachments = self._resolve_prepared_attachments(attachments_data)
        ready_attachments = [
            item for item in prepared_attachments
            if str(item.get("status", "ready")) == "ready"
        ]
        image_attachments = [
            {
                "id": item.get("id", ""),
                "dataUrl": item.get("dataUrl", ""),
                "name": item.get("name", ""),
                "type": item.get("type", "image/png"),
            }
            for item in ready_attachments
            if str(item.get("category", "")) == "image"
        ]
        effective_message = (message or "").strip() or "첨부한 자료를 확인해 줘."
        timestamp = self._now_timestamp()
        attachment_context = build_attachment_context_block(ready_attachments)
        prompt = self._build_general_chat_prompt(effective_message, attachment_context=attachment_context)
        message_with_time = f"[현재 시각: {timestamp}]\n{prompt}"
        memory_search_text = self._build_memory_search_text(effective_message, timestamp)

        self._mark_user_activity()
        attachment_note = build_attachment_note(ready_attachments)
        history_message = ((message or "").strip() or "(첨부)") + attachment_note
        self._append_conversation("user", history_message, timestamp)
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(effective_message, image_count=len(image_attachments))
            self._emit_mood_changed(snapshot)

        self._last_request_payload = {
            "type": "attachments" if ready_attachments else "text",
            "message": effective_message,
            "message_with_time": message_with_time,
            "images": image_attachments,
            "attachment_note": attachment_note,
            "attachment_context": attachment_context,
            "memory_search_text": memory_search_text,
        }
        self._is_rerolling = False

        self._emit_performance_state("thinking")
        self._start_ai_worker(
            message_with_time,
            image_attachments,
            memory_search_text=memory_search_text,
        )
        print(
            f"[Bridge] Worker thread started with "
            f"{len(image_attachments)} images and "
            f"{len([item for item in ready_attachments if item.get('category') == 'document'])} documents"
        )

    @pyqtSlot()
    def reroll_last_response(self):
        """마지막 사용자 요청을 다시 실행해 최근 assistant 응답만 교체."""
        if not self.llm_client:
            print("[Bridge] Reroll ignored: LLM client not initialized")
            self._reset_pending_ui_state("리롤할 수 있는 최근 요청이 없어요.")
            return

        if not self._last_request_payload:
            print("[Bridge] Reroll ignored: no previous request payload")
            self._reset_pending_ui_state("리롤할 수 있는 최근 요청이 없어요.")
            return

        if self.worker and self.worker.isRunning():
            print("[Bridge] Reroll ignored: worker is still running")
            self._reset_pending_ui_state("이미 응답 생성 중이에요.")
            return

        if not self._rollback_last_turn_pair_for_retry():
            print("[Bridge] Reroll aborted: failed to rollback/rebuild LLM context")
            self._reset_pending_ui_state("리롤 준비 중 문제가 생겼어요.")
            return

        # 교체 의미를 지키기 위해 최근 assistant 응답 하나를 버퍼에서 제거
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "assistant":
            self.conversation_buffer.pop()

        payload = self._last_request_payload
        self._is_rerolling = True
        self.reroll_state_changed.emit(True)
        self._emit_performance_state("thinking")
        self._start_ai_worker(
            payload["message_with_time"],
            payload.get("images") or [],
            memory_search_text=str(payload.get("memory_search_text", "") or ""),
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

        if self.worker and self.worker.isRunning():
            print("[Bridge] Edit ignored: worker is still running")
            self._reset_pending_ui_state("이미 응답 생성 중이에요.")
            return

        # 최근 user/assistant 턴을 LLM 컨텍스트에서 롤백
        if not self._rollback_last_turn_pair_for_retry():
            print("[Bridge] Edit aborted: failed to rollback/rebuild LLM context")
            self._reset_pending_ui_state("수정 재요청 준비 중 문제가 생겼어요.")
            return

        # 대화 버퍼의 최근 assistant/user 턴 제거
        if self.conversation_buffer and self.conversation_buffer[-1][0] == "assistant":
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
        if payload_type in {"images", "attachments"}:
            self._append_conversation("user", edited_message + attachment_note, timestamp)
        else:
            self._append_conversation("user", edited_message, timestamp)

        prompt = self._build_general_chat_prompt(edited_message, attachment_context=attachment_context)
        message_with_time = f"[현재 시각: {timestamp}]\n{prompt}"
        memory_search_text = self._build_memory_search_text(edited_message, timestamp)
        self._last_request_payload = {
            "type": payload_type,
            "message": edited_message,
            "message_with_time": message_with_time,
            "images": images,
            "attachment_note": attachment_note,
            "attachment_context": attachment_context,
            "memory_search_text": memory_search_text,
        }

        self._is_rerolling = True
        self.reroll_state_changed.emit(True)
        self._start_ai_worker(message_with_time, images, memory_search_text=memory_search_text)
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

    
    def _on_response_ready(
        self,
        text: str,
        emotion: str,
        japanese_text: str,
        events: list = None,
        analysis_payload: str = "",
        token_usage_payload: str = "",
    ):
        """AI 응답 준비 완료"""
        text = self._sanitize_visible_response_text(text)
        print(f"[Bridge] Response ready: {text[:50]}... [{emotion}]")
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
        
        # 대화 버퍼에 응답 추가 (+ 타임스탬프)
        self._append_conversation("assistant", text)
        self._refresh_llm_history_from_visible_conversation()
        
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
        emit_performance_state = getattr(self, "_emit_performance_state", None)
        if japanese_text and self.enable_tts and self.tts_client and self.audio_player:
            print(f"[Bridge] TTS 활성화 - 텍스트 보류 중, TTS 생성 시작")
            # 텍스트를 보류하고 TTS 완료 대기
            self.pending_response = (text, emotion)
            self.pending_token_usage_payload = resolved_token_usage_payload
            if callable(emit_performance_state):
                emit_performance_state("preSpeech")
            self._play_tts(japanese_text)
        else:
            # TTS 비활성화 또는 일본어 없음 - 즉시 텍스트 전송
            print(f"[Bridge] TTS 비활성화 - 텍스트 즉시 전송")
            self.message_received.emit(text, emotion)
            if callable(emit_performance_state):
                emit_performance_state("listening")
            self.token_usage_ready.emit(resolved_token_usage_payload)
            if self._is_rerolling:
                self._is_rerolling = False
                self.reroll_state_changed.emit(False)
            if japanese_text:
                print(f"[Bridge] TTS 비활성화 또는 클라이언트 없음 (일본어: {japanese_text[:20]}...)")
        
        # 자동 요약 확인
        self._check_auto_summarize()

    def _sanitize_visible_response_text(self, text: str) -> str:
        """표시 직전 응답에서 내부 메타데이터와 잔여 감정 태그를 제거한다."""
        sanitized = str(text or "")
        sanitized = re.sub(r"\[analysis\]\s*.*?\s*\[/analysis\]\s*", "", sanitized, flags=re.IGNORECASE | re.DOTALL)

        key_pattern = "|".join(re.escape(key) for key in VISIBLE_RESPONSE_ANALYSIS_KEYS)
        leading_meta_pattern = rf"^\s*(?:(?:{key_pattern})\s*=\s*.*(?:\r?\n|$))+"
        sanitized = re.sub(leading_meta_pattern, "", sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r"^\s*\n+", "", sanitized)

        sanitized = re.sub(r"\[(\w+)\]", "", sanitized)
        return sanitized.strip()

    def _refresh_llm_history_from_visible_conversation(self):
        """현재 보이는 대화 버퍼만 남도록 LLM 히스토리를 재구성한다."""
        if not self.llm_client:
            return
        rebuild = getattr(self.llm_client, "rebuild_context_from_conversation", None)
        if not callable(rebuild):
            return
        try:
            ok = bool(rebuild(self.conversation_buffer))
            if not ok:
                print("[Bridge] LLM 히스토리 재구성 실패")
        except Exception as e:
            print(f"[Bridge] LLM 히스토리 재구성 중 오류: {e}")
    
    def _play_tts(self, text: str):
        """립싱크를 포함한 TTS 재생 (비동기 스레드)"""
        self._tts_interrupted_for_ptt = False
        if getattr(self.tts_client, "uses_browser_playback", False):
            self._flush_pending_response_if_any()
            self._play_browser_tts(text)
            return

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

    def _run_parent_javascript(self, script: str):
        """부모 오버레이의 웹뷰에 자바스크립트를 실행한다."""
        parent = self.parent()
        if not parent or not hasattr(parent, "web_view"):
            return
        try:
            parent.web_view.page().runJavaScript(script)
        except Exception as e:
            print(f"[Bridge] JS 실행 실패: {e}")

    def _play_browser_tts(self, text: str):
        """브라우저 기본 speechSynthesis로 음성을 재생한다."""
        if not self.tts_client:
            return
        try:
            payload = self.tts_client.build_request(text)
        except Exception as e:
            self._on_tts_error(str(e))
            return

        self.lip_sync_data = None
        self.lip_sync_start_time = None
        self.lip_sync_update.emit(0.0)
        self._emit_speech_state("ended", 0.0)
        self._run_parent_javascript(
            "(function(){"
            "if (typeof window.playBrowserTTS === 'function') {"
            f"window.playBrowserTTS({json.dumps(payload, ensure_ascii=False)});"
            "}"
            "})();"
        )
        print("[Bridge] 브라우저 TTS 재생 요청 완료")

    def _flush_pending_response_if_any(self):
        """TTS 대기 중 응답이 있으면 즉시 채팅으로 복구 전송한다."""
        if not self.pending_response:
            return
        text, emotion = self.pending_response
        print(f"[Bridge] 보류된 응답 즉시 전송: {text[:50]}... [{emotion}]")
        self.message_received.emit(text, emotion)
        self._emit_performance_state("listening")
        self.token_usage_ready.emit(self._resolve_token_usage_payload(self.pending_token_usage_payload))
        if self._is_rerolling:
            self._is_rerolling = False
            self.reroll_state_changed.emit(False)
        self.pending_response = None
        self.pending_token_usage_payload = ""

    def _resolve_token_usage_payload(self, token_usage_payload: str = "") -> str:
        """브리지에서 사용할 토큰 사용량 JSON을 정규화한다."""
        usage = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

        if token_usage_payload:
            try:
                parsed = json.loads(token_usage_payload)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                usage = {
                    "input_tokens": parsed.get("input_tokens") if isinstance(parsed.get("input_tokens"), int) else None,
                    "output_tokens": parsed.get("output_tokens") if isinstance(parsed.get("output_tokens"), int) else None,
                    "total_tokens": parsed.get("total_tokens") if isinstance(parsed.get("total_tokens"), int) else None,
                }
                return json.dumps(usage, ensure_ascii=False)

        getter = getattr(self.llm_client, "get_last_token_usage", None)
        if callable(getter):
            try:
                latest_usage = getter()
            except Exception:
                latest_usage = None
            if isinstance(latest_usage, dict):
                usage = {
                    "input_tokens": latest_usage.get("input_tokens") if isinstance(latest_usage.get("input_tokens"), int) else None,
                    "output_tokens": latest_usage.get("output_tokens") if isinstance(latest_usage.get("output_tokens"), int) else None,
                    "total_tokens": latest_usage.get("total_tokens") if isinstance(latest_usage.get("total_tokens"), int) else None,
                }

        return json.dumps(usage, ensure_ascii=False)

    def interrupt_tts_for_ptt(self):
        """PTT 시작 시 현재 음성 출력/립싱크를 즉시 중단한다."""
        # 생성 중인 TTS 결과가 곧 도착할 수 있으면 다음 오디오 재생을 1회 스킵한다.
        self._tts_interrupted_for_ptt = bool(self.pending_response) or bool(
            self.tts_worker and self.tts_worker.isRunning()
        )

        # 재생 중 오디오 중단
        if self.audio_player:
            try:
                self.audio_player.stop()
            except Exception as e:
                print(f"[Bridge] PTT TTS 중단 실패(audio): {e}")

        # 립싱크 중단 및 입 닫기
        if self.lip_sync_timer:
            try:
                self.lip_sync_timer.stop()
            except Exception:
                pass
            self.lip_sync_timer = None
        self.lip_sync_data = None
        self.lip_sync_start_time = None
        self.lip_sync_update.emit(0.0)
        self._emit_speech_state("ended", 0.0)
        self._emit_performance_state("listening")
        self._run_parent_javascript(
            "(function(){"
            "if (typeof window.stopBrowserTTS === 'function') {"
            "window.stopBrowserTTS();"
            "}"
            "})();"
        )

        # 보류 중 텍스트가 있으면 즉시 표시
        self._flush_pending_response_if_any()
        print(f"[Bridge] PTT로 TTS 중단 처리 완료 (skip_next={self._tts_interrupted_for_ptt})")

    def _on_tts_ready(self, audio_data: bytes, lip_sync_data: list):
        """비동기 TTS 완료 후 오디오 재생"""
        print(f"[Bridge] TTS 준비 완료: {len(audio_data)} bytes, {len(lip_sync_data)} 프레임")
        
        # 립싱크 데이터 저장
        self.lip_sync_data = lip_sync_data if lip_sync_data else None
        
        # 보류된 텍스트가 있으면 이제 전송 (텍스트 + 음성 동시 제공)
        self._flush_pending_response_if_any()
        
        # PTT로 끊긴 경우, 이번 오디오는 재생하지 않는다.
        if self._tts_interrupted_for_ptt:
            self._tts_interrupted_for_ptt = False
            self.lip_sync_data = None
            self.lip_sync_update.emit(0.0)
            print("[Bridge] PTT 중단 플래그로 오디오 재생 생략")
            return
        
        # 오디오 재생
        self.audio_player.play(audio_data)
        
        # 립싱크 시작
        if self.lip_sync_data:
            self._start_lip_sync()
    
    def _on_tts_error(self, error_msg: str):
        """TTS 오류 처리"""
        print(f"[Bridge] TTS 오류: {error_msg}")
        # TTS 실패 시 보류 중이던 텍스트를 즉시 복구 전송한다.
        self._flush_pending_response_if_any()
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
        self._emit_speech_state("started", 0.0)
        self._emit_performance_state("preSpeech")
        
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
            self._emit_speech_state("speaking", mouth_value)
        
        # 모든 데이터 처리 완료 시 타이머 종료
        if self.lip_sync_index >= len(self.lip_sync_data) - 1:
            self.lip_sync_timer.stop()
            self.lip_sync_update.emit(0.0)  # 입 닫기
            self._emit_speech_state("ended", 0.0)
            self._emit_performance_state("settling")
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

            clear_context = getattr(self.llm_client, "clear_context", None)
            if callable(clear_context):
                clear_context()
                print("[Bridge] 대화 요약 후 LLM 세션 컨텍스트 초기화")
            
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
        self._emit_performance_state("listening")
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
        self._pending_attachment_cache = {}
        self._session_attachment_documents = []
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

