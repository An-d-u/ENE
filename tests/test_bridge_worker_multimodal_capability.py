from PyQt6.QtCore import QCoreApplication

from src.ai.response_protocol import ResponseDeliveryMetadata
from src.core.bridge_workers import AIWorker


STRUCTURED_METADATA = ResponseDeliveryMetadata(
    response_mode="json_schema",
    schema_version="1",
    promises_authoritative=True,
    repair_performed=False,
)


def _ensure_qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_ai_worker_rejects_images_when_client_declares_no_image_support():
    _ensure_qt_app()

    class DummyLLM:
        supports_image_input = False

        async def send_message_with_images(self, *_args, **_kwargs):
            raise AssertionError("이미지 미지원 공급자에서는 멀티모달 호출을 하면 안 됩니다.")

    errors = []
    worker = AIWorker(
        llm_client=DummyLLM(),
        message="이미지 설명해줘",
        images=[{"dataUrl": "data:image/png;base64,QUJD"}],
    )
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "이미지 입력을 지원하지 않습니다" in errors[0]


def test_ai_worker_sends_images_when_client_declares_image_support():
    _ensure_qt_app()

    class DummyLLM:
        supports_image_input = True

        def __init__(self):
            self.calls = []

        def get_last_response_delivery_metadata(self):
            return STRUCTURED_METADATA

        async def send_message_with_images(self, message, images, *_args, **_kwargs):
            self.calls.append((message, images))
            return "이미지 응답", "normal", "", [], {}, [], "", {}

    client = DummyLLM()
    responses = []
    worker = AIWorker(
        llm_client=client,
        message="이미지 설명해줘",
        images=[{"dataUrl": "data:image/png;base64,QUJD"}],
    )
    worker.response_ready.connect(lambda text, *_args: responses.append(text))

    worker.run()

    assert client.calls == [("이미지 설명해줘", [{"dataUrl": "data:image/png;base64,QUJD"}])]
    assert responses == ["이미지 응답"]
    assert worker.response_metadata == STRUCTURED_METADATA


def test_ai_worker_forwards_progress_callback_to_memory_client():
    _ensure_qt_app()

    stages = []

    class DummyLLM:
        def get_last_response_delivery_metadata(self):
            return STRUCTURED_METADATA

        async def send_message_with_memory(self, *args, progress_callback=None):
            if progress_callback:
                progress_callback("searching")
            self.call_args = args
            self.progress_callback = progress_callback
            return "Synthetic response.", "normal", "", [], {}, [], "", {}, [], ""

    client = DummyLLM()
    responses = []
    progress_callback = stages.append
    worker = AIWorker(
        llm_client=client,
        message="Synthetic prompt.",
        progress_callback=progress_callback,
    )
    worker.response_ready.connect(lambda text, *_args: responses.append(text))

    worker.run()

    assert client.progress_callback is progress_callback
    assert stages == ["searching"]
    assert responses == ["Synthetic response."]
    assert worker.response_metadata == STRUCTURED_METADATA


def test_ai_worker_logs_chat_content(capsys):
    _ensure_qt_app()

    user_text = "Synthetic user text visible in logs"
    response_text = "Synthetic response text visible in logs"
    tts_text = "Synthetic TTS text visible in logs"

    class DummyLLM:
        async def send_message_with_memory(self, *_args, **_kwargs):
            return response_text, "normal", tts_text, [], {}, [], "", {}, [], ""

    worker = AIWorker(
        llm_client=DummyLLM(),
        message=user_text,
    )

    worker.run()

    captured = capsys.readouterr().out
    assert user_text in captured
    assert response_text in captured
    assert tts_text in captured
    assert "emotion=normal" in captured
