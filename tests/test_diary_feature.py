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


def test_diary_save_markdown_creates_utf8_bom_file(tmp_path: Path):
    service = DiaryService(tmp_path / "diary")
    result = service.save_markdown("기획서 초안을 써줘", "# 제목\n\n본문")

    saved_path = Path(result.absolute_path)
    assert saved_path.exists()
    assert saved_path.parent.name == "diary"
    assert saved_path.suffix == ".md"

    data = saved_path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")


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

    def fake_start(body: str, message_with_time: str):
        captured["body"] = body
        captured["message"] = message_with_time

    monkeypatch.setattr(bridge, "_start_diary_worker", fake_start)

    handled = bridge._handle_diary_command("/diary 오늘 있었던 일을 일기로 써줘")
    assert handled is True
    assert captured["body"] == "오늘 있었던 일을 일기로 써줘"
    assert "[현재 시각:" in captured["message"]
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

    def fake_handle(message: str) -> bool:
        called["diary"] += 1
        return True

    def fake_start(*args, **kwargs):
        called["normal"] += 1

    monkeypatch.setattr(bridge, "_handle_diary_command", fake_handle)
    monkeypatch.setattr(bridge, "_start_ai_worker", fake_start)

    bridge.send_to_ai("/diary 테스트")

    assert called["diary"] == 1
    assert called["normal"] == 0


def test_aiworker_diary_flow_uses_one_shot_and_does_not_need_history(tmp_path: Path):
    _ensure_qt_app()

    class DummyLLM:
        async def generate_markdown_document(self, message: str) -> str:
            return "# 문서\n\n내용"

        async def generate_diary_completion_reply(self, context_message: str):
            assert "성공적으로 파일 작성에 완료되었습니다." in context_message
            assert "[작성된 md 파일 본문]" in context_message
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