"""
브릿지에서 사용하는 백그라운드 워커 모음.
"""
import json

from PyQt6.QtCore import QThread, pyqtSignal

from ..ai.diary_service import DiaryService
from ..ai.note_service import NoteCommand, NoteCommandResult, NotePlan, NoteService
from ..ai.persona_names import resolve_prompt_persona_names
from ..ai.prompt_language import resolve_prompt_language


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

    response_ready = pyqtSignal(str, str, str, list, str, str, list, str, str, list, str)  # (텍스트, 감정, TTS 텍스트, 이벤트, analysis JSON, 토큰 JSON, 약속 리스트, 생각, 목표 업데이트 JSON, 선제 대화 리스트, 제스처)
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
        self.diary_request = (diary_request or "").strip()
        self.note_request = (note_request or "").strip()
        self.note_recent_context = (note_recent_context or "").strip()
        self.diary_service = diary_service
        self.note_service = note_service
        self.obsidian_manager = obsidian_manager
        self.use_obsidian_priority = bool(use_obsidian_priority)
        self.progress_callback = progress_callback

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=getattr(self.llm_client, "settings", None))

    def _normalize_response_payload(self, payload):
        """신구 응답 형식을 모두 10개 값으로 정규화한다."""
        if isinstance(payload, tuple):
            if len(payload) == 10:
                return payload
            if len(payload) == 9:
                text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations = payload
                return text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, ""
            if len(payload) == 8:
                text, emotion, tts_text, events, analysis, promises, thought, goal_update = payload
                return text, emotion, tts_text, events, analysis, promises, thought, goal_update, [], ""
            if len(payload) == 7:
                text, emotion, tts_text, events, analysis, promises, thought = payload
                return text, emotion, tts_text, events, analysis, promises, thought, {}, [], ""
            if len(payload) == 6:
                text, emotion, tts_text, events, analysis, promises = payload
                return text, emotion, tts_text, events, analysis, promises, "", {}, [], ""
            if len(payload) == 5:
                text, emotion, tts_text, events, analysis = payload
                return text, emotion, tts_text, events, analysis, [], "", {}, [], ""
            if len(payload) == 4:
                text, emotion, tts_text, events = payload
                return text, emotion, tts_text, events, {}, [], "", {}, [], ""
        raise ValueError("지원하지 않는 응답 형식입니다.")

    def _ensure_image_input_supported(self):
        """이미지 입력 미지원 공급자에서 첨부 이미지를 조용히 버리지 않도록 막는다."""
        if getattr(self.llm_client, "supports_image_input", None) is False:
            raise RuntimeError("현재 LLM 공급자는 이미지 입력을 지원하지 않습니다. 이미지 지원 공급자나 모델로 변경해 주세요.")

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
            promises = []

            proactive_conversations = []
            gesture = ""

            if self.note_request and self.note_service and self.obsidian_manager:
                print("[AI Worker] /note 모드")
                response_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._normalize_response_payload(
                    loop.run_until_complete(self._run_note_flow())
                )
            elif self.diary_request and self.diary_service:
                print("[AI Worker] /diary 모드")
                response_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._normalize_response_payload(
                    loop.run_until_complete(self._run_diary_flow())
                )
            # 이미지가 있으면 멀티모달로 처리
            elif self.images:
                self._ensure_image_input_supported()
                print(f"[AI Worker] 이미지 {len(self.images)}개 포함 - 멀티모달 모드")
                response_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._normalize_response_payload(
                    loop.run_until_complete(
                        self.llm_client.send_message_with_images(
                            self.message,
                            self.images,
                            self.memory_search_text,
                            self.latest_user_message,
                            self.recent_memory_context,
                            self.head_pat_count_before_message,
                            progress_callback=self.progress_callback,
                        )
                    )
                )
            elif self.use_memory and hasattr(self.llm_client, 'send_message_with_memory'):
                print(f"[AI Worker] 메모리 활용 모드")
                response_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._normalize_response_payload(
                    loop.run_until_complete(
                        self.llm_client.send_message_with_memory(
                            self.message,
                            self.memory_search_text,
                            self.latest_user_message,
                            self.recent_memory_context,
                            self.head_pat_count_before_message,
                            progress_callback=self.progress_callback,
                        )
                    )
                )
            else:
                print(f"[AI Worker] 일반 모드 (메모리 없음)")
                response_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._normalize_response_payload(
                    self.llm_client.send_message(self.message)
                )

            print(f"[AI Worker] Response: {response_text[:50]}... [{emotion}]")
            if tts_text:
                print(f"[AI Worker] TTS text: {tts_text[:30]}...")
            if events:
                print(f"[AI Worker] {len(events)}개 일정 추출")
            token_usage_payload = self._build_token_usage_payload()

            # events도 함께 emit (signal에는 리스트로 전달 가능)
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
            text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._normalize_response_payload(
                await self.llm_client.generate_diary_completion_reply(completion_context)
            )
            if required not in text:
                text = f"{required}\n{text}".strip()
            return text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture

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
            language=self._prompt_language(),
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
            language=self._prompt_language(),
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

            print(f"[StreamingTTSWorker] Streaming speech for: {self.text[:30]}...")
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
            print(f"[StreamingTTSWorker] Error: {e}")
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

    def __init__(self, obsidian_manager, checked_files: list[str], language: str = "ko"):
        super().__init__()
        self.obsidian_manager = obsidian_manager
        self.checked_files = [str(path) for path in (checked_files or []) if str(path).strip()]
        self.language = resolve_prompt_language(language)

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
                checked_files=self.checked_files,
                allow_retry=False,
            )
            context = build_obsidian_checked_context(checked_contents, self.language)
            self.context_ready.emit(context, signature_payload)
        except Exception as e:
            self.error_occurred.emit(str(e), signature_payload)
