"""PC/폰의 활성 쓰다듬기 하나와 재전송 경계를 Qt 소유로 관리한다."""

from collections import OrderedDict
from dataclasses import dataclass, replace
import math
import re
from time import monotonic

from .protocol import integer_value, uuid_value


MAX_SEQUENCE = 2**53 - 1


@dataclass(frozen=True)
class ActiveHeadPat:
    source: str
    connection: str
    model_version: str
    interaction_id: str
    interaction_no: int
    seq: int
    intensity: float
    updated_at: float

    def fields(self):
        return {key: getattr(self, key) for key in (
            "model_version", "interaction_id", "interaction_no", "seq", "intensity",
        )}


class HeadPatCoordinator:
    """완료 기록은 256개, 번호 상한은 현재 PC/폰 연결별 하나씩만 유지한다."""

    def __init__(self, count, publish, *, now=monotonic):
        self.count, self.publish, self.now = count, publish, now
        self.active = None
        self.model_version = None
        self.enabled = False
        self.connections = {"pc": None, "phone": None}
        self.high_water = {"pc": 0, "phone": 0}
        self.history = OrderedDict()

    def bind(self, source, connection):
        if source not in self.connections:
            raise ValueError("invalid_source")
        if connection is not None:
            uuid_value(connection)
        if self.connections[source] == connection:
            return
        if self.active is not None and self.active.source == source:
            self.cancel("disconnected")
        self.connections[source] = connection
        self.high_water[source] = 0
        for key in tuple(self.history):
            if key[0] == source:
                del self.history[key]

    def configure(self, model_version, *, enabled):
        if model_version is not None and not re.fullmatch(r"[a-f0-9]{64}", model_version):
            raise ValueError("invalid_model")
        if type(enabled) is not bool:
            raise ValueError("invalid_enabled")
        if model_version != self.model_version:
            self.cancel("model_changed")
        elif not enabled:
            self.cancel("disabled")
        self.model_version, self.enabled = model_version, enabled

    @staticmethod
    def _validate(fields):
        if not isinstance(fields, dict):
            raise ValueError("invalid_input")
        model = fields.get("model_version")
        if not isinstance(model, str) or not re.fullmatch(r"[a-f0-9]{64}", model):
            raise ValueError("invalid_model")
        phase = fields.get("phase")
        if phase not in ("start", "update", "end", "cancel"):
            raise ValueError("invalid_phase")
        intensity = fields.get("intensity")
        try:
            valid = type(intensity) in (int, float) and math.isfinite(intensity) and 0 <= intensity <= 1
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("invalid_intensity")
        sequence = integer_value(fields.get("seq"), 0)
        if phase in ("start", "update") and sequence == MAX_SEQUENCE:
            raise ValueError("sequence_exhausted")
        return {"model_version": model, "interaction_id": uuid_value(fields.get("interaction_id")),
                "interaction_no": integer_value(fields.get("interaction_no"), 1), "seq": sequence,
                "phase": phase, "intensity": float(intensity)}

    @staticmethod
    def _answer(source, fields, phase, reason):
        return {**fields, "source": source, "phase": phase, "reason": reason}

    def _remember(self, source, fields, answer):
        key = (source, fields["interaction_no"])
        self.history[key] = (dict(fields), dict(answer))
        self.history.move_to_end(key)
        while len(self.history) > 256:
            self.history.popitem(last=False)

    def receive(self, source, connection, fields):
        if source not in self.connections:
            raise ValueError("invalid_source")
        fields = self._validate(fields)
        self.tick()
        if connection is None or self.connections[source] != connection:
            return self._answer(source, fields, "rejected", "stale_connection")
        number, phase = fields["interaction_no"], fields["phase"]
        previous = self.history.get((source, number))
        if previous is not None and previous[0] == fields:
            return dict(previous[1])
        fresh = number > self.high_water[source]
        self.high_water[source] = max(number, self.high_water[source])

        def reject(reason):
            answer = self._answer(source, fields, "rejected", reason)
            # 활성 세션의 마지막 유효 입력은 오래된/잘못된 입력으로 교체하지 않는다.
            if fresh:
                self._remember(source, fields, answer)
            return answer

        if fields["model_version"] != self.model_version:
            return reject("model_changed")
        if not self.enabled:
            return reject("disabled")
        if phase == "start":
            if not fresh:
                return reject("stale_interaction")
            if fields["seq"] != 0:
                return reject("invalid_sequence")
            if any(key[0] == source and record[0]["interaction_id"] == fields["interaction_id"]
                   for key, record in self.history.items()):
                return reject("reused_id")
            if self.active is not None:
                return reject("busy")
            self.active = ActiveHeadPat(source, connection, **{key: value for key, value in fields.items() if key != "phase"}, updated_at=self.now())
            answer = self._answer(source, fields, "accepted", "accepted")
        else:
            active = self.active
            if active is None or (active.source, active.connection, active.interaction_no, active.interaction_id) != (
                source, connection, number, fields["interaction_id"],
            ):
                return reject("no_active_interaction")
            if fields["seq"] <= active.seq:
                return reject("stale_sequence")
            if phase == "update":
                self.active = replace(active, seq=fields["seq"], intensity=fields["intensity"], updated_at=self.now())
                answer = self._answer(source, fields, "update", "updated")
            else:
                # 횟수 저장이 일부만 성공하거나 재진입하더라도 같은 세션은 다시 세지 않는다.
                self.active = None
                answer = self._answer(source, fields, "ended" if phase == "end" else "cancelled", "ended" if phase == "end" else "cancelled")
                if phase == "end":
                    try:
                        self.count()
                    except Exception:
                        answer = self._answer(source, fields, "cancelled", "count_failed")
        self._remember(source, fields, answer)
        self.publish(dict(answer))
        return answer

    def cancel(self, reason="cancelled"):
        active, self.active = self.active, None
        if active is None:
            return
        fields = {**active.fields(), "seq": min(MAX_SEQUENCE, active.seq + 1), "phase": "cancel"}
        answer = self._answer(active.source, fields, "cancelled", reason)
        self._remember(active.source, fields, answer)
        self.publish(dict(answer))

    def tick(self):
        if self.active is not None and self.now() - self.active.updated_at >= 2.0:
            self.cancel("lease_expired")
