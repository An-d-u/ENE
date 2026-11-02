"""PDF 종료와 WebSocket 수신 큐 제한을 실제 의존성으로 검증한다."""

import asyncio
from pathlib import Path
import subprocess
import sys

from aiohttp import WSMessage, WSMsgType
from aiohttp._websocket.reader import WebSocketDataQueue
import pytest


def test_incomplete_pdf_attachment_returns_an_error_without_hanging():
    # GHSA-5849-834g-hvw5의 작은 합성 입력만 자식 프로세스에 전달한다.
    script = """
import base64
from src.core.chat_attachments import prepare_attachments

payload = b"%PDF-1.4\\nstartxref\\n28\\n%%EOF\\nxref\\n1 0\\nzzz"
encoded = base64.b64encode(payload).decode("ascii")
result = prepare_attachments([{
    "name": "synthetic-incomplete.pdf",
    "type": "application/pdf",
    "dataUrl": f"data:application/pdf;base64,{encoded}",
}])
assert len(result) == 1
assert result[0]["status"] == "error"
assert result[0]["error"]
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("불완전한 PDF 첨부가 10초 안에 종료되지 않았습니다.")
    assert completed.returncode == 0, completed.stderr


class _ReceiveProtocol:
    def __init__(self):
        self._reading_paused = False

    def pause_reading(self):
        self._reading_paused = True

    def resume_reading(self):
        self._reading_paused = False


def test_empty_websocket_messages_trigger_receive_backpressure_and_resume():
    async def scenario():
        protocol = _ReceiveProtocol()
        queue = WebSocketDataQueue(protocol, 64, loop=asyncio.get_running_loop())
        message = WSMessage(WSMsgType.TEXT, "", "")
        # 페이로드가 비어 있어도 큐의 메시지 객체에는 메모리 비용이 있다.
        for _ in range(100):
            queue.feed_data(message, 0)
        assert protocol._reading_paused, "빈 메시지 누적에 수신 제한이 작동하지 않습니다."

        for _ in range(100):
            received = await queue.read()
            assert received.type == WSMsgType.TEXT
            assert received.data == ""
        assert not protocol._reading_paused

    asyncio.run(scenario())
