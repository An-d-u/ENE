"""실제 Qt 요청 gate에서 모바일 사진의 수락·중복·공개 경계를 검사한다."""

from hashlib import sha256
import json

import pytest

from src.core.companion.extension_protocol import ExtensionContext
from src.core.companion.input_uploads import UploadStore
from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_input_uploads import picture


def images_request(admission, *, count=1, request=30, command=50, text="가상 색상표를 확인합니다."):
    owner, _, context, _ = admission
    head = owner.head()
    scope = ExtensionContext(context.registration_generation, head.server_epoch, context.connection_generation, head.conversation_id)
    store = UploadStore(scope)
    images = []
    for index in range(count):
        data = picture((16 + index, 12))
        digest = sha256(data).hexdigest()
        key = store.reserve(scope, sample_id(command + index), "image", len(data), digest)
        store.begin(scope, key, len(data))
        store.append(scope, key, data)
        store.finish(scope, key)
        images.append(dict(upload_id=key, sha256=digest, byte_length=len(data), mime="image/png"))
    message = decode_message(encode_message(dict(type="chat_images_send", protocol_version=1,
        registration_generation=scope.registration_generation, server_epoch=scope.server_epoch,
        connection_generation=scope.connection_generation, conversation_id=scope.conversation_id,
        request_id=sample_id(request), text=text, images=images)))
    return message, store


def submit(admission, message, store):
    owner, _, context, _ = admission
    assert callable(getattr(owner, "submit_mobile_images", None)), "사진은 기존 Qt 수락 경계에 연결되어야 한다"
    return owner.submit_mobile_images(context, message, store)


def test_images_are_accepted_once_with_pc_display_and_image_payload(admission):
    owner, _, _, counts = admission
    displayed = []
    owner.chat_display_event.connect(lambda raw: displayed.append(json.loads(raw)))
    message, store = images_request(admission, count=2)
    result = submit(admission, message, store)
    assert result.state == "accepted"
    assert counts["worker"] == 1 and store.reserved_bytes == 0
    assert len(owner._last_request_payload["images"]) == 2
    user, = [item["message"] for item in displayed if item["op"] == "append" and item["message"]["role"] == "user"]
    assert user["id"] == result.message_id and len(user["attachments"]) == 2
    assert user["attachment_unsupported"] is True
    again, retry_store = images_request(admission, count=2, command=60)
    assert submit(admission, again, retry_store) == result
    assert counts["worker"] == 1


def test_photo_only_uses_existing_default_and_known_nonvision_blocks(admission):
    owner, _, _, counts = admission
    owner.llm_client.supports_image_input = False
    message, store = images_request(admission, text="")
    result = submit(admission, message, store)
    assert result.state == "rejected" and result.code == "image_input_unsupported"
    assert counts["worker"] == 0
    owner.llm_client.supports_image_input = True
    result = submit(admission, message, store)
    assert result.state == "accepted"
    assert owner._last_request_payload["message"] == "첨부한 자료를 확인해 줘."


def test_partial_upload_failure_never_publishes_text_only_message(admission):
    owner, _, _, counts = admission
    message, store = images_request(admission, count=2)
    store.cancel(store.context, message.fields["images"][1]["upload_id"])
    result = submit(admission, message, store)
    assert result.state == "rejected"
    assert owner.chat_state.public_transcript.capture().messages == ()
    assert not any(counts.values())


def test_changed_image_content_conflicts_before_busy(admission):
    message, store = images_request(admission)
    assert submit(admission, message, store).state == "accepted"
    changed, second = images_request(admission, count=2)
    assert submit(admission, changed, second).code == "request_conflict"


def test_metadata_contains_only_registered_mobile_images_and_deletion_invalidates(admission):
    owner, _, context, _ = admission
    message, store = images_request(admission)
    result = submit(admission, message, store)
    owner.worker.reply()
    query = dict(conversation_id=owner.head().conversation_id,
                 conversation_revision=owner.chat_state.public_transcript.capture().conversation_revision,
                 query_id=sample_id(80), message_id=result.message_id)
    images = owner._companion_images.metadata(context.registration_generation, query)
    assert len(images["images"]) == 1
    assert owner._companion_images.metadata(context.registration_generation + 1, query)["images"] == []
    image_id = images["images"][0]["id"]
    owner.delete_message_attachment(result.message_id, image_id)
    deleted = owner._companion_images.metadata(context.registration_generation, query)
    assert deleted["images"] == []
    assert deleted["attachment_revision"] > images["attachment_revision"]


def test_untrusted_mobile_attachment_dict_is_still_rejected(admission):
    owner, _, context, _ = admission
    from src.core.companion.requests import RequestRef
    head = owner.head()
    ref = RequestRef(context.registration_generation, head.server_epoch, head.conversation_id, sample_id(90), "mobile")
    assert owner.submit_chat_request("가상 첨부", request_ref=ref, context=context,
                                    request_type="attachments", attachments=[{}]).code == "unsupported_command"


def test_queued_adapter_transfers_only_current_uploads(admission):
    from PyQt6.QtWidgets import QApplication
    from tests.test_companion_adapter import run_adapter

    owner, adapter, context, counts = admission
    message, store = images_request(admission)

    async def scenario():
        result = await adapter.call("send_images", context, message=message, input_store=store)
        assert result.fields["state"] == "accepted"
        capture = await adapter.call("capture", context)
        user = capture.transcript.messages[0]
        query = decode_message(encode_message({**message.to_dict(), "type": "chat_images_request",
            "query_id": sample_id(81), "message_id": user.id, "conversation_revision": capture.transcript.conversation_revision}))
        metadata = await adapter.call("extension", context, message=query)
        image = metadata.fields["images"][0]
        revision, data = await adapter.call("image_capture", context, pending=(user.id, image["id"]))
        assert revision == metadata.fields["attachment_revision"] and data.startswith("data:image/png;base64,")

    run_adapter(QApplication.instance(), adapter, scenario)
    assert counts["worker"] == 1


def test_thumbnail_is_bounded_and_contains_no_original_metadata():
    import importlib
    import base64
    from io import BytesIO
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    module = "src.core.companion.image_thumbnail"
    assert importlib.util.find_spec(module) is not None, "원본과 분리된 제한된 썸네일 생성기가 필요하다"
    metadata = PngInfo()
    metadata.add_text("synthetic-note", "synthetic metadata")
    output = BytesIO()
    Image.new("RGBA", (2048, 1024), (30, 60, 90, 100)).save(output, "PNG", pnginfo=metadata)
    body, mime = importlib.import_module(module).thumbnail("data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii"))
    assert len(body) <= 128 * 1024 and mime == "image/png"
    with Image.open(BytesIO(body)) as image:
        assert image.size == (320, 160)
        assert "synthetic-note" not in image.info
        assert image.getpixel((0, 0))[3] == 100
