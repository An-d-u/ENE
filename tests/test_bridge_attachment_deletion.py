from src.core.bridge import WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


def test_delete_message_attachment_updates_history_and_recent_payload():
    dummy = type("BridgeDummy", (), {})()
    dummy.conversation_buffer = [
        (
            "user",
            "사진 봐줘 [이미지:첫장.png | 이미지:둘째장.png]",
            "2026-04-07 14:10",
        ),
        ("assistant", "확인할게.", "2026-04-07 14:11"),
    ]
    dummy._message_attachment_records = {
        "msg-1": {
            "message": "사진 봐줘",
            "timestamp": "2026-04-07 14:10",
            "conversation_index": 0,
            "attachments": [
                {
                    "id": "img-1",
                    "name": "첫장.png",
                    "category": "image",
                    "type": "image/png",
                    "status": "ready",
                    "dataUrl": "data:image/png;base64,aaa",
                    "deleted": False,
                },
                {
                    "id": "img-2",
                    "name": "둘째장.png",
                    "category": "image",
                    "type": "image/png",
                    "status": "ready",
                    "dataUrl": "data:image/png;base64,bbb",
                    "deleted": False,
                },
            ],
        }
    }
    dummy._last_request_payload = {
        "type": "attachments",
        "message": "사진 봐줘",
        "message_id": "msg-1",
        "images": [
            {"id": "img-1", "dataUrl": "data:image/png;base64,aaa", "name": "첫장.png", "type": "image/png"},
            {"id": "img-2", "dataUrl": "data:image/png;base64,bbb", "name": "둘째장.png", "type": "image/png"},
        ],
        "attachment_note": " [이미지:첫장.png | 이미지:둘째장.png]",
        "attachment_context": "",
    }
    dummy._refresh_calls = 0
    dummy._compose_attachment_history_message = lambda message, attachments: WebBridge._compose_attachment_history_message(dummy, message, attachments)
    dummy._find_attachment_conversation_index = lambda record: WebBridge._find_attachment_conversation_index(dummy, record)
    dummy._build_active_image_payload = lambda attachments: WebBridge._build_active_image_payload(dummy, attachments)
    dummy._refresh_llm_history_from_visible_conversation = lambda: setattr(dummy, "_refresh_calls", dummy._refresh_calls + 1)

    WebBridge.delete_message_attachment(dummy, "msg-1", "img-2")

    assert dummy.conversation_buffer[0][1] == "사진 봐줘 [이미지:첫장.png | [사진이 삭제되었습니다.]]"
    assert dummy._last_request_payload["images"] == [
        {"id": "img-1", "dataUrl": "data:image/png;base64,aaa", "name": "첫장.png", "type": "image/png"},
    ]
    assert dummy._last_request_payload["attachment_note"] == " [이미지:첫장.png | [사진이 삭제되었습니다.]]"
    assert "[사진이 삭제되었습니다.]" in dummy._last_request_payload["attachment_context"]
    assert dummy._message_attachment_records["msg-1"]["attachments"][1]["deleted"] is True
    assert dummy._refresh_calls == 1
