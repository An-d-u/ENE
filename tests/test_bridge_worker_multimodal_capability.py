from PyQt6.QtCore import QCoreApplication

from src.core.bridge_workers import AIWorker


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
