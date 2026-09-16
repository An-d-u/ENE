"""Qt 소유의 발화별 출력 결정. 반환 명령은 호출자가 한 번만 실행한다."""


class AudioRoute:
    PREPARE_MS = 2000
    WATCHDOG_MS = 5000

    def __init__(self):
        self.state, self.target = "PC", "pc"
        self.deadline_ms = None
        self._begun = self._completed = False
        self._clock = -1
        self._received_ms = self._advanced_ms = 0
        self._played_frames = 0
        self._source_frames = self._finished_frames = None

    def _observe(self, now_ms):
        if type(now_ms) is not int or now_ms < self._clock:
            return False
        self._clock = now_ms
        return True

    def offer(self, *, now_ms, phone_eligible):
        if self._begun or self.state == "DONE" or not self._observe(now_ms):
            return "ignore"
        self._begun = True
        if not phone_eligible:
            return "play_pc"
        self.state = "OFFERED"
        self.deadline_ms = now_ms + self.PREPARE_MS
        return "offer_phone"

    def _fallback(self):
        if self.state != "OFFERED":
            return "ignore"
        self.state, self.target = "PC", "pc"
        return "play_pc"

    def prepared(self, *, now_ms):
        if self.state != "OFFERED" or not self._observe(now_ms):
            return "ignore"
        if now_ms >= self.deadline_ms:
            return self._fallback()
        # 송신 결과를 알 수 없어도 이 기록 이후에는 PC로 되돌리지 않는다.
        self.state, self.target = "PHONE_COMMITTED", "phone"
        self._received_ms = self._advanced_ms = now_ms
        return "send_start"

    def rejected(self):
        return self._fallback()

    def delivery_failed(self):
        if self.state == "OFFERED":
            return self._fallback()
        if self.state in {"PHONE_COMMITTED", "PLAYING"}:
            return self.cancel()
        return "ignore"

    def tick(self, *, now_ms):
        if not self._observe(now_ms):
            return "ignore"
        if self.state == "OFFERED" and now_ms >= self.deadline_ms:
            return self._fallback()
        if self.state in {"PHONE_COMMITTED", "PLAYING"} and (
            now_ms - self._received_ms >= self.WATCHDOG_MS
            or now_ms - self._advanced_ms >= self.WATCHDOG_MS
        ):
            return self.cancel()
        return "ignore"

    def started(self, *, now_ms):
        if self.state != "PHONE_COMMITTED" or now_ms < self._clock:
            return "ignore"
        action = self.tick(now_ms=now_ms)
        if action != "ignore":
            return action
        self.state = "PLAYING"
        self._received_ms = now_ms
        return "playing"

    def progress(self, *, now_ms, played_frames):
        if (
            self.state not in {"PHONE_COMMITTED", "PLAYING"}
            or type(played_frames) is not int
            or played_frames < self._played_frames
            or now_ms < self._clock
        ):
            return "ignore"
        action = self.tick(now_ms=now_ms)
        if action != "ignore":
            return action
        if self._source_frames is not None and played_frames > self._source_frames:
            return self.cancel()
        self.state = "PLAYING"
        self._received_ms = now_ms
        if played_frames > self._played_frames:
            self._advanced_ms = now_ms
        self._played_frames = played_frames
        return "ack_progress"

    def source_end(self, *, total_frames):
        if self.state == "DONE":
            return "ignore"
        if (
            type(total_frames) is not int
            or total_frames < self._played_frames
            or self._source_frames not in (None, total_frames)
        ):
            return self.cancel()
        self._source_frames = total_frames
        return self._drained()

    def phone_finished(self, *, played_frames):
        if self.state not in {"PHONE_COMMITTED", "PLAYING"}:
            return "ignore"
        if (
            type(played_frames) is not int
            or played_frames < self._played_frames
            or self._finished_frames not in (None, played_frames)
        ):
            return self.cancel()
        self._finished_frames = played_frames
        return self._drained()

    def _drained(self):
        if self._source_frames is None or self._finished_frames is None:
            return "ignore"
        if self._source_frames != self._finished_frames:
            return self.cancel()
        return self.finish()

    def cancel(self):
        if self.state == "DONE":
            return "ignore"
        self.state = "DONE"
        return "cancel"

    def finish(self):
        if self._completed:
            return "ignore"
        self.state, self._completed = "DONE", True
        return "complete_once"
