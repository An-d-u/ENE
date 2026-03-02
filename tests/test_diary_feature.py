import asyncio
import builtins
from pathlib import Path
import sys

from PyQt6.QtCore import QCoreApplication

from src.ai.diary_service import DiaryService
from src.ai.prompt import get_system_prompt
from src.core.bridge import WebBridge


def _ensure_qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_prompt_includes_sub_prompt_by_default():
    prompt_with_sub = get_system_prompt()
    prompt_without_sub = get_system_prompt(include_sub_prompt=False)

    assert "[감정 표현 규칙]" in prompt_with_sub
    assert "[일본어 응답 규칙]" in prompt_with_sub
    assert "[감정 표현 규칙]" not in prompt_without_sub
    assert "[일본어 응답 규칙]" not in prompt_without_sub


def test_prompt_falls_back_when_sub_prompt_is_missing(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("sub_prompt"):
            raise ModuleNotFoundError("sub_prompt not found")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "src.ai.sub_prompt", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    prompt = get_system_prompt(include_sub_prompt=True)
    assert "[감정 표현 규칙]" not in prompt
    assert "[일본어 응답 규칙]" not in prompt


def test_diary_command_parse():
    is_diary, body = DiaryService.parse_diary_command("/diary 오늘 있었던 일을 일기로 써줘")
    assert is_diary is True
    assert body == "오늘 있었던 일을 일기로 써줘"

    is_diary2, body2 = DiaryService.parse_diary_command("/diary   ")
    assert is_diary2 is True
    assert body2 == ""

    is_diary3, body3 = DiaryService.parse_diary_command("일반 메시지")
    assert is_diary3 is False
    assert body3 == ""


def test_obs_command_parse():
    is_obs, body = DiaryService.parse_obs_command("/obs ENE/Projects/AI.md에 회의 요약 추가")
    assert is_obs is True
    assert body == "ENE/Projects/AI.md에 회의 요약 추가"

    is_obs2, body2 = DiaryService.parse_obs_command("/obs   ")
    assert is_obs2 is True
    assert body2 == ""

    is_obs3, body3 = DiaryService.parse_obs_command("일반 메시지")
    assert is_obs3 is False
    assert body3 == ""


def test_diary_save_markdown_creates_utf8_bom_file(tmp_path: Path):
    service = DiaryService(tmp_path / "diary")
    result = service.save_markdown("기획서 초안을 써줘", "# 제목\n\n본문")

    saved_path = Path(result.absolute_path)
    assert saved_path.exists()
    assert saved_path.parent.name == "diary"
    assert saved_path.suffix == ".md"

    data = saved_path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")


def test_diary_save_local_only_when_cli_disabled(tmp_path: Path):
    class DummySettings:
        def get(self, key: str, default=None):
            values = {
                "obsidian_cli_enabled": False,
                "obsidian_cli_command": "obsidian-cli --file \"{file_path}\"",
            }
            return values.get(key, default)

    service = DiaryService(tmp_path / "diary", settings=DummySettings())
    result = service.save_markdown_via_priority("연결 테스트", "# 문서")
    assert result.storage_target == "local_only"
    assert result.obsidian_cli_invoked is False
    assert result.obsidian_cli_error == ""


def test_diary_save_cli_primary_success(tmp_path: Path, monkeypatch):
    class DummySettings:
        def get(self, key: str, default=None):
            values = {
                "obsidian_cli_enabled": True,
                "obsidian_cli_primary_for_diary": True,
                "diary_keep_local_copy_on_cli_success": False,
                "obsidian_cli_command": "obsidian-cli --file \"{file_path}\" --name \"{file_name}\"",
                "obsidian_cli_timeout_sec": 5,
            }
            return values.get(key, default)

    captured = {}

    class DummyCompleted:
        returncode = 0
        stderr = ""

    def fake_run(command, shell, text, capture_output, timeout):
        captured["command"] = command
        captured["timeout"] = timeout
        return DummyCompleted()

    monkeypatch.setattr("src.ai.diary_service.subprocess.run", fake_run)

    service = DiaryService(tmp_path / "diary", settings=DummySettings())
    result = service.save_markdown_via_priority("연결 테스트", "# 문서")

    assert result.storage_target == "obsidian"
    assert result.obsidian_cli_invoked is True
    assert result.obsidian_cli_error == ""
    assert result.obsidian_output_path
    assert "obsidian-cli" in captured["command"]
    assert captured["timeout"] == 5
    assert list((tmp_path / "diary").glob("*.md")) == []


def test_diary_save_cli_primary_failure_fallback_local(tmp_path: Path, monkeypatch):
    class DummySettings:
        def get(self, key: str, default=None):
            values = {
                "obsidian_cli_enabled": True,
                "obsidian_cli_primary_for_diary": True,
                "diary_keep_local_copy_on_cli_success": False,
                "obsidian_cli_command": "obsidian-cli --file \"{file_path}\"",
                "obsidian_cli_timeout_sec": 5,
            }
            return values.get(key, default)

    class DummyCompleted:
        returncode = 1
        stderr = "mock fail"

    def fake_run(command, shell, text, capture_output, timeout):
        return DummyCompleted()

    monkeypatch.setattr("src.ai.diary_service.subprocess.run", fake_run)

    service = DiaryService(tmp_path / "diary", settings=DummySettings())
    result = service.save_markdown_via_priority("연결 테스트", "# 문서")

    assert result.storage_target == "local_fallback"
    assert result.obsidian_cli_invoked is True
    assert "mock fail" in result.obsidian_cli_error
    saved_files = list((tmp_path / "diary").glob("*.md"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes().startswith(b"\xef\xbb\xbf")


def test_bridge_handles_diary_without_conversation_buffer(monkeypatch):
    _ensure_qt_app()

    class DummyLLM:
        async def generate_markdown_document(self, message: str) -> str:
            return "# 테스트\n"

        async def generate_diary_completion_reply(self, context_message: str):
            return "성공적으로 파일 작성에 완료되었습니다.", "normal", "", []

    bridge = WebBridge()
    bridge.llm_client = DummyLLM()

    captured = {}

    def fake_start(body: str, message_with_time: str, use_obsidian_priority: bool = False):
        captured["body"] = body
        captured["message"] = message_with_time
        captured["use_obsidian_priority"] = use_obsidian_priority

    monkeypatch.setattr(bridge, "_start_diary_worker", fake_start)

    handled = bridge._handle_diary_command("/diary 오늘 있었던 일을 일기로 써줘")
    assert handled is True
    assert captured["body"] == "오늘 있었던 일을 일기로 써줘"
    assert "[현재 시각:" in captured["message"]
    assert captured["use_obsidian_priority"] is False
    assert bridge.conversation_buffer == []


def test_bridge_diary_empty_body_emits_error_message():
    _ensure_qt_app()

    class DummyLLM:
        pass

    bridge = WebBridge()
    bridge.llm_client = DummyLLM()

    received = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))

    handled = bridge._handle_diary_command("/diary")
    assert handled is True
    assert received
    assert "`/diary` 뒤에 작성할 내용을 함께 입력해 주세요." in received[-1][0]


def test_bridge_send_to_ai_routes_diary(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    called = {"diary": 0, "normal": 0}

    def fake_obs(message: str) -> bool:
        return False

    def fake_handle(message: str) -> bool:
        called["diary"] += 1
        return True

    def fake_start(*args, **kwargs):
        called["normal"] += 1

    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_handle)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("/diary 테스트")

    assert called["diary"] == 1
    assert called["normal"] == 0


def test_bridge_send_to_ai_routes_obs(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    called = {"obs": 0, "diary": 0}

    def fake_obs(message: str) -> bool:
        called["obs"] += 1
        return True

    def fake_diary(message: str) -> bool:
        called["diary"] += 1
        return False

    monkeypatch.setattr(bridge, "_handle_obs_command", fake_obs)
    monkeypatch.setattr(bridge, "_handle_diary_command", fake_diary)

    bridge.send_to_ai("/obs 테스트")

    assert called["obs"] == 1
    assert called["diary"] == 0


def test_bridge_obs_append_command_emits_success():
    _ensure_qt_app()

    class DummyResult:
        def __init__(self, ok=True, message="ok", path="C:/Vault/test.md"):
            self.ok = ok
            self.message = message
            self.path = path

    bridge = WebBridge()
    bridge.llm_client = object()

    class DummyObsManager:
        def append_file(self, rel_path, content, create_if_missing=True):
            return DummyResult(ok=True, message="ok", path=f"C:/Vault/{rel_path}")

        def get_tree_lines(self, max_lines=120):
            return []

        def get_checked_file_contents(self, **kwargs):
            return []

    bridge.obsidian_manager = DummyObsManager()

    received = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))

    handled = bridge._handle_obs_command("/obs append test.md :: 추가 텍스트")
    assert handled is True
    assert received
    assert "추가 완료" in received[-1][0]


def test_bridge_obs_summarize_command_starts_ai_worker(monkeypatch):
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    class DummyObsManager:
        def read_file(self, rel_path):
            return "# 제목\n내용"

        def get_tree_lines(self, max_lines=120):
            return ["[FILE] test.md"]

        def get_checked_file_contents(self, **kwargs):
            return [("test.md", "체크 파일 내용")]

    bridge.obsidian_manager = DummyObsManager()

    captured = {}

    def fake_start(message_with_time: str, images_data=None):
        captured["message_with_time"] = message_with_time

    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)
    handled = bridge._handle_obs_command("/obs summarize test.md")
    assert handled is True
    assert "[Obsidian 트리 구조]" in captured["message_with_time"]
    assert "[Obsidian 체크된 파일 본문]" in captured["message_with_time"]
    assert "[요약 대상 파일: test.md]" in captured["message_with_time"]


def test_aiworker_diary_flow_uses_one_shot_and_does_not_need_history(tmp_path: Path):
    _ensure_qt_app()

    class DummyLLM:
        async def generate_markdown_document(self, message: str) -> str:
            return "# 문서\n\n내용"

        async def generate_diary_completion_reply(self, context_message: str):
            assert "성공적으로 파일 작성에 완료되었습니다." in context_message
            assert "[작성된 md 파일 본문]" in context_message
            assert "[저장 결과]" in context_message
            assert "- 대상:" in context_message
            assert "- 경로:" in context_message
            return "성공적으로 파일 작성에 완료되었습니다. 완료됐어요.", "smile", "", []

    from src.core.bridge import AIWorker

    service = DiaryService(tmp_path / "diary")
    worker = AIWorker(
        llm_client=DummyLLM(),
        message="[현재 시각: 2026-02-28 20:00]\n오늘 있었던 일을 일기로 써줘",
        diary_request="오늘 있었던 일을 일기로 써줘",
        diary_service=service,
    )

    result = asyncio.run(worker._run_diary_flow())
    assert result[0].startswith("성공적으로 파일 작성에 완료되었습니다.")
    saved_files = list((tmp_path / "diary").glob("*.md"))
    assert len(saved_files) == 1

def test_bridge_tts_error_restores_pending_response():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.pending_response = ("복구할 응답", "normal")
    bridge._is_rerolling = True

    received = []
    reroll_states = []
    bridge.message_received.connect(lambda text, emotion: received.append((text, emotion)))
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))

    bridge._on_tts_error("mock error")

    assert received == [("복구할 응답", "normal")]
    assert bridge.pending_response is None
    assert bridge._is_rerolling is False
    assert reroll_states and reroll_states[-1] is False


def test_bridge_edit_without_payload_resets_pending_ui_state():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    reroll_states = []
    notices = []
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))
    bridge.summary_notice.connect(lambda message, level: notices.append((message, level)))

    bridge.edit_last_user_message("수정 메시지")

    assert reroll_states and reroll_states[-1] is False
    assert notices
    assert "/diary 응답은 Edit로 다시 생성할 수 없어요." in notices[-1][0]
    assert notices[-1][1] == "info"


def test_bridge_reroll_without_payload_resets_pending_ui_state():
    _ensure_qt_app()

    bridge = WebBridge()
    bridge.llm_client = object()

    reroll_states = []
    notices = []
    bridge.reroll_state_changed.connect(lambda state: reroll_states.append(bool(state)))
    bridge.summary_notice.connect(lambda message, level: notices.append((message, level)))

    bridge.reroll_last_response()

    assert reroll_states and reroll_states[-1] is False
    assert notices
    assert notices[-1][1] == "info"
