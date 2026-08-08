"""
WebBridge의 Obsidian 패널, 명령, 컨텍스트 연동을 담당한다.
"""
import json
import re

from PyQt6.QtCore import QTimer, pyqtSlot

from ...ai.chat_commands import parse_obs_command
from ..bridge_workers import ObsidianCheckedFilesWorker, ObsidianTreeWorker, build_obsidian_checked_context


_OBSIDIAN_TREE_ERROR_MESSAGE = "Obsidian 트리를 불러오지 못했어요."


def _safe_obsidian_result_path(value) -> str:
    """성공 안내에 표시해도 되는 정규 상대 Markdown 경로만 반환한다."""
    if type(value) is not str:
        return ""
    if (
        not value
        or len(value) > 512
        or value != value.strip()
        or not value.lower().endswith(".md")
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return ""
    parts = value.split("/")
    return value if all(part not in {"", ".", ".."} for part in parts) else ""


class ObsidianBridgeMixin:
    @staticmethod
    def _obsidian_bridge_is_shutting_down(bridge) -> bool:
        state = getattr(bridge, "life_record_state", None)
        return getattr(state, "phase", None) == "shutting_down"

    def set_obs_panel_window(self, panel_window):
        """Obsidian 플로팅 패널 참조를 등록한다."""
        self.obs_panel_window = panel_window

    def _build_obsidian_context_block(self, include_tree: bool = True, include_checked_files: bool = True) -> str:
        """Obsidian 트리/체크 파일 컨텍스트 블록을 생성한다."""
        language = self._prompt_language()
        labels = {
            "ko": {
                "tree": "[Obsidian 트리 구조]",
            },
            "en": {
                "tree": "[Obsidian Tree]",
            },
            "ja": {
                "tree": "[Obsidianツリー構造]",
            },
        }.get(language, {"tree": "[Obsidian 트리 구조]"})
        parts: list[str] = []
        if include_tree:
            parts.append(labels["tree"])
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
                parts.append(build_obsidian_checked_context(checked_contents, language))
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
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
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
            language=self._prompt_language(),
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

        if self._cached_checked_files_context and not self._validate_cached_checked_files_context(signature):
            return ""

        return self._cached_checked_files_context

    def _validate_cached_checked_files_context(self, signature: tuple[str, ...]) -> bool:
        """캐시된 체크 파일이 현재 Obsidian 트리에 여전히 존재하는지 확인한다."""
        try:
            tree = self.obsidian_manager.build_tree(allow_retry=False)
        except Exception:
            print("[Bridge] obsidian_cache category=obsidian_cache_validation_error")
            self._invalidate_checked_files_context_cache()
            return False

        if not isinstance(tree, dict) or not tree.get("ok"):
            self._invalidate_checked_files_context_cache()
            return False

        checked_files = tuple(str(path) for path in tree.get("checked_files", []) if str(path).strip())
        if checked_files == signature:
            return True

        setter = getattr(self.obs_settings, "set_checked_files", None)
        if callable(setter):
            try:
                setter(list(checked_files))
            except Exception:
                print("[Bridge] obsidian_cache category=obsidian_checked_files_cleanup_error")
        self._invalidate_checked_files_context_cache()
        try:
            self._cached_obs_tree_json = json.dumps(tree, ensure_ascii=False)
            self.obs_tree_updated.emit(self._cached_obs_tree_json)
        except Exception:
            print("[Bridge] obsidian_cache category=obsidian_tree_signal_error")
        if checked_files:
            self._schedule_checked_files_context_refresh(force=True)
        return False

    def _invalidate_checked_files_context_cache(self):
        """체크 파일 내용이 바뀐 뒤 기존 스냅샷을 무효화한다."""
        self._cached_checked_files_context = ""
        self._cached_checked_files_signature = tuple()

    def _on_checked_files_context_ready(self, context: str, signature_payload: str):
        """백그라운드에서 준비된 체크 파일 컨텍스트를 캐시에 반영한다."""
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
        signature = self._decode_checked_files_signature(signature_payload)
        current_signature = self._get_checked_files_signature()
        if signature != current_signature:
            self._schedule_checked_files_context_refresh(force=True)
            return
        self._cached_checked_files_context = context
        self._cached_checked_files_signature = signature

    def _on_checked_files_context_error(self, error_msg: str, signature_payload: str):
        """체크 파일 캐시 갱신 실패를 기록하고, 필요하면 다시 시도한다."""
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
        print("[Bridge] checked_files_context_failed category=obsidian_checked_files_error")
        if not signature_payload:
            return
        signature = self._decode_checked_files_signature(signature_payload)
        if signature != self._get_checked_files_signature():
            self._schedule_checked_files_context_refresh(force=True)

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
        is_obs, obs_body = parse_obs_command(message)
        if not is_obs:
            return False

        cancel_proactive = getattr(self, "_cancel_pending_proactive_conversations_for_user_message", None)
        if callable(cancel_proactive):
            cancel_proactive()
        self._mark_user_activity()
        if self.mood_manager:
            snapshot = self.mood_manager.on_user_message(message, image_count=0)
            self._emit_mood_changed(snapshot)

        if not obs_body:
            self.message_received.emit("`/obs` 뒤에 작성할 내용을 함께 입력해 주세요.", "confused", "")
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
                self.message_received.emit(preview, "normal", "")
            except Exception:
                self.message_received.emit("파일을 읽는 중 오류가 발생했어요.", "confused", "")
            return True

        if command == "append":
            result = self.obsidian_manager.append_file(payload["path"], payload["content"], create_if_missing=True)
            if result.ok:
                self._invalidate_checked_files_context_cache()
                try:
                    safe_path = _safe_obsidian_result_path(getattr(result, "path", ""))
                except Exception:
                    safe_path = ""
                message = f"추가 완료: {safe_path}" if safe_path else "추가 완료"
                self.message_received.emit(message, "smile", "")
            else:
                self.message_received.emit("추가 실패", "confused", "")
            return True

        if command == "replace":
            result = self.obsidian_manager.replace_in_file(payload["path"], payload["before"], payload["after"])
            if result.ok:
                self._invalidate_checked_files_context_cache()
                try:
                    safe_path = _safe_obsidian_result_path(getattr(result, "path", ""))
                except Exception:
                    safe_path = ""
                message = f"교체 완료: {safe_path}" if safe_path else "교체 완료"
                self.message_received.emit(message, "smile", "")
            else:
                self.message_received.emit("교체 실패", "confused", "")
            return True

        # summarize/ask: Obsidian 컨텍스트 포함하여 LLM 질의
        timestamp = self._now_timestamp()
        language = self._prompt_language()
        obs_context = self._build_obsidian_context_block(include_tree=True, include_checked_files=True)
        if command == "summarize":
            try:
                target = self.obsidian_manager.read_file(payload["path"])
            except Exception:
                self.message_received.emit("요약할 파일을 읽는 중 오류가 발생했어요.", "confused", "")
                return True
            if language == "en":
                prompt = (
                    f"{obs_context}\n\n"
                    f"[File To Summarize: {payload['path']}]\n{target}\n\n"
                    "Summarize the file above concisely, focusing only on the key points."
                )
            elif language == "ja":
                prompt = (
                    f"{obs_context}\n\n"
                    f"[要約対象ファイル: {payload['path']}]\n{target}\n\n"
                    "上のファイルを、要点だけに絞って簡潔に要約してください。"
                )
            else:
                prompt = (
                    f"{obs_context}\n\n"
                    f"[요약 대상 파일: {payload['path']}]\n{target}\n\n"
                    "위 파일을 핵심만 간결히 요약해 주세요."
                )
        else:
            instruction_label = {
                "ko": "[OBS 지시사항]",
                "en": "[OBS Instruction]",
                "ja": "[OBS指示]",
            }.get(language, "[OBS 지시사항]")
            prompt = f"{obs_context}\n\n{instruction_label}\n{payload.get('instruction', obs_body)}"

        message_with_time = self._with_prompt_time(timestamp, prompt)
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
        except Exception:
            return json.dumps({"checked_files": [], "error": "체크 파일 목록을 불러오지 못했어요."}, ensure_ascii=False)

    @pyqtSlot(str, bool)
    def set_obs_file_checked(self, rel_path: str, checked: bool):
        """JS에서 호출: 파일 체크 상태를 저장한다."""
        try:
            self.obs_settings.set_file_checked(rel_path, bool(checked))
            # 체크 상태 변경은 CLI 재호출 없이 캐시에 즉시 반영해 UI 지연을 줄인다.
            self._emit_obs_tree_with_updated_checked_files()
            self._schedule_checked_files_context_refresh(force=True)
        except Exception:
            print("[Bridge] obsidian_checked_state category=obsidian_checked_state_error")

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
        except Exception:
            print("[Bridge] obsidian_panel category=obsidian_panel_error")

    def _start_obs_tree_refresh(self, allow_retry: bool = False, retry_sequence: bool = False):
        """Obsidian 트리 갱신을 백그라운드 워커로 실행한다."""
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
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
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
        if self._obs_tree_retry_remaining <= 0:
            return
        panel = self.obs_panel_window
        if panel is None or not panel.isVisible():
            self._obs_tree_retry_remaining = 0
            return
        self._start_obs_tree_refresh(allow_retry=False, retry_sequence=False)

    def _schedule_obs_tree_retry_if_needed(self):
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
        panel = self.obs_panel_window
        if self._obs_tree_retry_remaining > 0 and panel is not None and panel.isVisible():
            self._obs_tree_retry_remaining -= 1
            self.obs_tree_retry_timer.start(30_000)

    def _on_obs_tree_ready(self, tree_json: str):
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
        try:
            parsed = json.loads(tree_json or "{}")
        except Exception:
            parsed = {}
        ok = isinstance(parsed, dict) and bool(parsed.get("ok"))
        if not ok:
            tree_json = json.dumps(
                {"ok": False, "error": _OBSIDIAN_TREE_ERROR_MESSAGE, "nodes": []},
                ensure_ascii=False,
            )
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
        if ObsidianBridgeMixin._obsidian_bridge_is_shutting_down(self):
            return
        payload = json.dumps(
            {"ok": False, "error": _OBSIDIAN_TREE_ERROR_MESSAGE, "nodes": []},
            ensure_ascii=False,
        )
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
        elif not parsed["ok"]:
            parsed["error"] = _OBSIDIAN_TREE_ERROR_MESSAGE
            parsed["nodes"] = []
        parsed["checked_files"] = checked
        if "nodes" not in parsed:
            parsed["nodes"] = []

        payload = json.dumps(parsed, ensure_ascii=False)
        self._cached_obs_tree_json = payload
        self.obs_tree_updated.emit(payload)
