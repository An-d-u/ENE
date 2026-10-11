"""Qt의 사진 수락과 모바일로 공개 가능한 첨부 ID만 관리한다."""

import base64
from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import uuid4

from .extension_protocol import ExtensionContext
from .input_uploads import InputError, UploadStore


@dataclass(frozen=True, repr=False)
class MobileImageAdmission:
    store: UploadStore
    context: ExtensionContext
    descriptors: tuple

    def fingerprint(self, text):
        content = [[item["sha256"], item["mime"], item["byte_length"]] for item in self.descriptors]
        return sha256(json.dumps(["mobile_images_v1", text, content], ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")).hexdigest()

    def materialize(self):
        images = self.store.claim(self.context, self.descriptors, "image")
        return tuple({"id": str(uuid4()), "name": f"image-{index + 1}." + ("png" if item.mime == "image/png" else "jpg"),
                      "type": item.mime, "dataUrl": "data:" + item.mime + ";base64," + base64.b64encode(item.body).decode("ascii")}
                     for index, item in enumerate(images))


class CompanionChatImagesBridge:
    capabilities = ("chat_images_v1",)

    def __init__(self, owner):
        self.owner = owner
        self._records = {}
        self._revision = 0

    def limits(self, query_id):
        owner = self.owner
        reason = "ready"
        if not owner.llm_client:
            reason = "ai_unavailable"
        elif getattr(owner.llm_client, "supports_image_input", None) is False:
            reason = "image_input_unsupported"
        elif owner.life_record_state.phase != "idle" or (owner.worker and owner.worker.isRunning()):
            reason = "busy"
        return dict(conversation_id=owner.head().conversation_id, query_id=query_id,
                    allowed=reason == "ready", reason=reason, max_count=4)

    def register(self, ref, message_id, attachments):
        if ref is None or ref.source != "mobile":
            return
        self._revision += 1
        ids = tuple(item["id"] for item in attachments)
        self._records[message_id] = (ref.registration_generation, ref.conversation_id, ids, self._revision, ids)

    def _visible(self, registration, message_id):
        record = self._records.get(message_id)
        captured = self.owner.chat_state.public_transcript.capture()
        if (record is None or record[:2] != (registration, captured.conversation_id)
                or not any(item.id == message_id and item.role == "user" for item in captured.messages)):
            return None, ()
        current = getattr(self.owner, "_message_attachment_records", {}).get(message_id, {})
        items = tuple(item for item in current.get("attachments", ()) if item.get("id") in record[2]
                      and item.get("category") == "image" and item.get("status") == "ready"
                      and not item.get("deleted") and item.get("dataUrl"))
        ids = tuple(item["id"] for item in items)
        if ids != record[4]:
            self._revision += 1
            record = (*record[:3], self._revision, ids)
            self._records[message_id] = record
        return record, items

    def metadata(self, registration, fields):
        captured = self.owner.chat_state.public_transcript.capture()
        record, items = self._visible(registration, fields["message_id"])
        current = (fields["conversation_id"], fields["conversation_revision"]) == (
            captured.conversation_id, captured.conversation_revision)
        return dict(conversation_id=captured.conversation_id, query_id=fields["query_id"], message_id=fields["message_id"],
                    conversation_revision=captured.conversation_revision, attachment_revision=record[3] if record else 0,
                    images=[dict(id=item["id"], width=item["width"], height=item["height"], mime=item["type"])
                            for item in items] if current else [])

    def capture(self, registration, message_id, image_id):
        record, items = self._visible(registration, message_id)
        for item in items:
            if item["id"] == image_id:
                return record[3], item["dataUrl"]
        raise InputError("image_unavailable", 404)

    def changed(self, message_id):
        record = self._records.get(message_id)
        if record is None:
            return
        record, _ = self._visible(record[0], message_id)
        adapter = getattr(self.owner, "_companion_adapter", None)
        if record is not None and adapter is not None:
            adapter.publish_extension("chat_images_invalidated", dict(conversation_id=self.owner.head().conversation_id,
                message_id=message_id, attachment_revision=record[3]))

    def reset(self):
        self._records.clear()
        self._revision = 0
