"""임시 등록 보관과 합성 응답만 사용하는 수동 LAN 연결 시험 화면."""

import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PyQt6.QtWidgets import QApplication

from src.core.companion.adapter import ConversationHead
from src.core.companion.controller import CompanionController
from src.core.companion.protocol import decode_message, encode_message
from src.core.companion.requests import RequestLedger, RequestStateError
from src.core.companion.session import SyncCapture
from src.core.companion.storage import RegistrationStore
from src.core.companion.transcript import CurrentConversationTranscript
from src.ui.companion_dialog import CompanionDialog


class SyntheticConversation:
    """AI·기억·설정·파일 명령을 호출하지 않는 개발 전용 대화 소유자."""

    def __init__(self):
        self.transcript = CurrentConversationTranscript()
        self.ledger = RequestLedger()
        self.response_count = 0
        self.publish = lambda event: None
        self.on_count = lambda count: None

    def head(self):
        return ConversationHead(
            self.transcript.server_epoch, self.transcript.conversation_id
        )

    def _status(self, generation, request_id, *, rejected=None, identity=None):
        epoch, conversation = identity or (
            self.transcript.server_epoch,
            self.transcript.conversation_id,
        )
        result = {
            "type": "request_status",
            "protocol_version": 1,
            "server_epoch": epoch,
            "conversation_id": conversation,
            "request_id": request_id,
        }
        record = self.ledger.lookup((generation, epoch, conversation, request_id))
        if rejected is not None:
            result.update(state="rejected", code=rejected)
        elif record is None:
            result["state"] = "unknown"
        else:
            result["state"] = record.state
            if record.message_id:
                result["message_id"] = record.message_id
            if record.code:
                result["code"] = record.code
        return decode_message(encode_message(result))

    def capture(self, generation, pending):
        return SyncCapture(
            self.transcript.capture(),
            tuple(self._status(generation, request_id) for request_id in pending),
        )

    def submit(self, context, message):
        fields = message.fields
        generation = context.registration_generation
        request_id = fields["request_id"]
        identity = (fields["server_epoch"], fields["conversation_id"])
        if identity != (self.transcript.server_epoch, self.transcript.conversation_id):
            return self._status(
                generation, request_id, rejected="stale_session", identity=identity
            )
        key = (generation, *identity, request_id)
        try:
            record = self.ledger.reserve(
                key, hashlib.sha256(fields["text"].encode("utf-8")).hexdigest()
            )
        except RequestStateError as error:
            return self._status(generation, request_id, rejected=error.code)
        if record.is_new:
            event = self.transcript.append_user(fields["text"], request_id=request_id)
            self.ledger.mark_accepted(key, event.message.id)
            self.publish(event)
            self.publish(
                self.transcript.publish_assistant(
                    "가상 응답: " + fields["text"], request_id=request_id
                )
            )
            self.ledger.finish(key, succeeded=True)
            self.response_count += 1
            self.on_count(self.response_count)
        return self._status(generation, request_id)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    with TemporaryDirectory(prefix="ene-companion-smoke-") as temporary:
        owner = SyntheticConversation()
        controller = CompanionController(
            owner,
            store_factory=lambda: RegistrationStore(
                Path(temporary) / "companion_registration.json"
            ),
        )
        owner.publish = controller.adapter.publish
        dialog = CompanionDialog()
        dialog.setWindowTitle("ENE 가상 대화 연결 시험 · 실제 AI 미사용")
        dialog.counter_label.setText(
            "가상 응답: 0회 · 실제 AI·기억과 연결되지 않습니다."
        )
        owner.on_count = lambda count: dialog.counter_label.setText(
            f"가상 응답: {count}회 · 종료하면 시험 대화와 등록이 삭제됩니다."
        )
        controller.state_changed.connect(dialog.set_state)
        controller.operation_failed.connect(dialog.show_error)
        dialog.enabled_requested.connect(
            lambda enabled, port: (
                controller.start(port) if enabled else controller.stop()
            )
        )
        dialog.qr_requested.connect(controller.request_qr)
        dialog.approve_requested.connect(controller.approve)
        dialog.reject_requested.connect(controller.reject)
        dialog.revoke_requested.connect(controller.revoke)
        closing = False

        def close_requested(result):
            nonlocal closing
            closing = True
            if controller.has_thread:
                controller.stop()
            else:
                app.quit()

        dialog.finished.connect(close_requested)
        controller.stopped.connect(lambda: app.quit() if closing else None)
        app.aboutToQuit.connect(controller.stop)
        dialog.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
