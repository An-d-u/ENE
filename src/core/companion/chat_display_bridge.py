"""대화·모델·음성과 독립적으로 PC의 유효 표시 설정을 공유한다."""


class CompanionChatDisplayBridge:
    capabilities = ("chat_display_v1",)

    def __init__(self, owner):
        self.owner = owner
        self._enabled = None
        self._revision = 0

    def snapshot(self):
        if self._enabled is None:
            settings = getattr(self.owner, "settings", None)
            self._enabled = bool(settings.get("message_split_enabled", False)) if settings is not None else False
        return {"display_revision": self._revision, "message_split_enabled": self._enabled}

    def settings_changed(self, enabled):
        self.snapshot()
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self._revision += 1
        adapter = getattr(self.owner, "_companion_adapter", None)
        if adapter is not None:
            try:
                adapter.publish_extension("chat_display_state", self.snapshot())
            except Exception:
                # 부가 알림 실패는 PC 적용을 막지 않으며 재조회로 회복한다.
                pass
