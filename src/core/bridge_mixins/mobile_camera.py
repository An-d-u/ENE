"""페어링된 휴대폰의 카메라 동의와 요청 한 건에서만 쓰는 이미지를 관리한다."""
from dataclasses import dataclass, replace
from time import monotonic
from weakref import WeakSet

from ..companion.adapter import AdapterError
from ..companion.extension_protocol import ExtensionContext
from ..companion.input_uploads import InputError
from ..companion.protocol import WireMessage
from ..companion.requests import AdmissionResult, RequestRef
from ..screen_frame import ScreenFrame
from .screen import _remote_endpoint


@dataclass(frozen=True)
class MobileCameraShare:
    scope: ExtensionContext
    generation: int
    lens: str
    question: bool
    observe: bool


class MobileCameraBridgeMixin:
    def _camera_scope(self, context, message):
        self._companion_adapter.validate_admission(context)
        head = self.head()
        scope = ExtensionContext(context.registration_generation, head.server_epoch,
                                 context.connection_generation, head.conversation_id)
        if any(message.fields[name] != value for name, value in vars(scope).items()):
            raise AdapterError("stale_session")
        return scope

    def _mobile_camera_state(self):
        share = self._mobile_camera
        client = self.llm_client
        model = str(getattr(client, "model_name", "") or "")
        return {
            "conversation_id": share.scope.conversation_id, "generation": share.generation,
            "available": bool(self._vision_available()),
            "observe_allowed": self._observation_device() == "mobile" and bool(self._vision_available()),
            "model": model.encode("utf-8", "replace")[:256].decode("utf-8", "ignore"),
            "remote": _remote_endpoint(client),
        }

    def _publish_mobile_camera_state(self):
        if getattr(self, "_mobile_camera", None) is None:
            return
        state = self._mobile_camera_state()
        if state != getattr(self, "_published_camera_state", None):
            self._published_camera_state = state
            self._companion_adapter.publish_extension("camera_state", state)

    def _set_mobile_camera(self, share):
        previous = getattr(self, "_mobile_camera", None)
        if share == previous:
            return
        old_context = self._ambient_context()
        self._mobile_camera = share
        self._sync_pc_observation_capture()
        for frame in tuple(getattr(self, "_mobile_camera_frames", ())):
            frame.revalidate()
        if self._ambient_context() != old_context:
            self._invalidate_automatic_reply()
            self._observation_schedule.reset_scene()

    def _revoke_mobile_camera(self, *, disconnect=False):
        share = getattr(self, "_mobile_camera", None)
        if share is not None:
            self._set_mobile_camera(None if disconnect else replace(share, question=False, observe=False))
            self._published_camera_state = None
            if not disconnect and (share.question or share.observe):
                # 서로 다른 제공자가 같은 모델 이름을 표시해도 기기에서 기존 동의를 해제한다.
                state = {**self._mobile_camera_state(), "available": False, "observe_allowed": False}
                self._companion_adapter.publish_extension("camera_state", state)
                self._published_camera_state = state

    def mobile_camera_share(self, context, message):
        scope = self._camera_scope(context, message)
        fields = message.fields
        previous = getattr(self, "_mobile_camera", None)
        if previous is None or previous.scope != scope or fields["generation"] > previous.generation:
            allowed = self._vision_available()
            self._set_mobile_camera(MobileCameraShare(scope, fields["generation"], fields["lens"],
                                                      bool(allowed and fields["question"]),
                                                      bool(allowed and fields["observe"])))
        state = self._mobile_camera_state()
        self._published_camera_state = state
        return WireMessage("camera_state", {**vars(scope), **state})

    def _camera_frame(self, share, mode, store, descriptor):
        observation = self._ambient_context() if mode == "observe" else None
        def authorized():
            return (self._mobile_camera is share and getattr(share, mode)
                    and (mode != "observe" or observation == self._ambient_context())
                    and store.camera_current(share.scope, share.generation, mode))

        if not authorized():
            return ScreenFrame(None, authorized)
        verified, = store.claim(share.scope, [descriptor], "camera", generation=share.generation, mode=mode)
        frame = ScreenFrame(verified.body, authorized)
        if not hasattr(self, "_mobile_camera_frames"):
            self._mobile_camera_frames = WeakSet()
        self._mobile_camera_frames.add(frame)
        return frame

    def submit_mobile_camera_question(self, context, message, store):
        fields = message.fields
        ref = RequestRef(context.registration_generation, fields["server_epoch"], fields["conversation_id"],
                         fields["request_id"], "mobile")
        try:
            scope = self._camera_scope(context, message)
        except AdapterError as error:
            return AdmissionResult(ref, "rejected", code=error.code)

        def take_frame():
            share = getattr(self, "_mobile_camera", None)
            if (share is not None and share.scope == scope and share.generation == fields["generation"]
                    and share.question and self._vision_available()):
                try:
                    return self._camera_frame(share, "question", store, fields["frame"])
                except InputError:
                    pass
            return ScreenFrame(None, lambda: False)

        return self.submit_chat_request(fields["text"], request_ref=ref, context=context,
                                        _mobile_camera_frame=take_frame)

    def submit_mobile_camera_observation(self, context, message, store):
        scope = self._camera_scope(context, message)
        share = getattr(self, "_mobile_camera", None)
        if (share is None or share.scope != scope or share.generation != message.fields["generation"]
                or self._observation_device() != "mobile" or not self._vision_available()):
            return
        now = monotonic()
        schedule = self._observation_schedule
        if (self._ambient_busy() or getattr(self, "_observation_pending", None) is not None
                or now < max(getattr(self, "_ambient_quiet_until", 0), schedule.next_request)):
            return
        try:
            frame = self._camera_frame(share, "observe", store, message.fields["frame"])
        except InputError:
            return
        observation = self._ambient_context()
        if not frame.read() or observation is None:
            frame.close()
            return
        self._mobile_observation_current = lambda: store.camera_current(share.scope, share.generation, "observe")
        self._launch_screen_observation(observation, frame, now=now, mobile=True)
