"""Qt 직렬 호출의 모델별 설정 검증과 연결별 유한 중복 명령 경계."""

from collections import OrderedDict
import hashlib
import json
import math

from .extension_protocol import EXPRESSION_SETTINGS, normalize_settings
from .protocol import MAX_SAFE_INTEGER, ProtocolError, text_value, uuid_value


# 기존 PC 장식 파라미터 창과 같은 읽기 전용 경계다.
READ_ONLY_PARAMETER_PREFIXES = (
    "ParamEye", "ParamMouth", "ParamJaw", "ParamTongue", "ParamBrow", "ParamAngle",
    "ParamBody", "ParamBreath", "ParamArm", "ParamHand", "ParamShoulder", "ParamLeg",
)


def normalize_parameters(values, catalog=None):
    """저장 경계에서도 형태를 검사하고 원격 경계에서는 SDK 카탈로그 범위를 검사한다."""
    if not isinstance(values, dict) or len(values) > 256:
        raise ValueError("invalid_parameters")
    bounds = {item["id"]: item for item in catalog} if catalog is not None else None
    result = {}
    for key, value in values.items():
        text_value(key, max_bytes=128, nonblank=True)
        if key in {"__proto__", "constructor", "prototype"} or any(ord(c) < 32 for c in key):
            raise ValueError("invalid_parameters")
        if bounds is not None and (key not in bounds or key.startswith(READ_ONLY_PARAMETER_PREFIXES)):
            raise ValueError("invalid_parameters")
        if value is not None:
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("invalid_parameters")
            if bounds is not None and not bounds[key]["min"] <= value <= bounds[key]["max"]:
                raise ValueError("invalid_parameters")
        result[key] = value
    return result


class CharacterControls:
    def __init__(self, state, commit):
        self.state, self.commit = state, commit
        self._connection = None
        self._commands = OrderedDict()

    @property
    def cached_commands(self):
        return len(self._commands)

    def disconnected(self):
        self._connection = None
        self._commands.clear()

    def patch(self, connection, *, command_id, model_version, expected_revision, changes, parameters):
        """호출자는 먼저 현재 등록/연결의 admission을 검사해야 한다."""
        uuid_value(command_id)
        if connection != self._connection:
            self.disconnected()
            self._connection = connection

        def result(status, reason):
            return {"command_id": command_id, "status": status, "reason": reason,
                    "settings_revision": self.state.settings_revision}

        try:
            body = json.dumps([model_version, expected_revision, changes, parameters],
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if len(body) > 65536:
                return result("rejected", "invalid_settings")
            fingerprint = hashlib.sha256(body).digest()
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            return result("rejected", "invalid_settings")
        previous = self._commands.get(command_id)
        if previous is not None:
            return dict(previous[1]) if previous[0] == fingerprint else result("conflict", "command_mismatch")

        if self.state.status != "ready" or self.state.bundle is None:
            answer = result("rejected", "character_unavailable")
        elif model_version != self.state.bundle.model_version:
            answer = result("conflict", "model_changed")
        elif type(expected_revision) is not int or not 0 <= expected_revision < MAX_SAFE_INTEGER:
            answer = result("rejected", "invalid_revision")
        elif expected_revision != self.state.settings_revision:
            answer = result("conflict", "revision_conflict")
        else:
            try:
                clean = normalize_settings(changes)
                for key in EXPRESSION_SETTINGS & clean.keys():
                    if clean[key] and clean[key] not in self.state.expressions:
                        raise ValueError("invalid_expression")
                clean_parameters = normalize_parameters(parameters, self.state.catalog)
                next_settings = {**self.state.settings, **clean}
                next_parameters = dict(self.state.parameters)
                for key, value in clean_parameters.items():
                    if value is None:
                        next_parameters.pop(key, None)
                    else:
                        next_parameters[key] = value
            except (ProtocolError, ValueError, TypeError, OverflowError):
                answer = result("rejected", "invalid_settings")
            else:
                try:
                    self.commit(clean, clean_parameters)
                except Exception:
                    answer = result("rejected", "storage_failed")
                else:
                    # 빈 변경도 revision을 전진시켜 캐시 축출 뒤 재적용을 막는다.
                    self.state.commit_settings(next_settings, next_parameters)
                    answer = result("accepted", "saved")
        self._commands[command_id] = (fingerprint, dict(answer))
        if len(self._commands) > 256:
            self._commands.popitem(last=False)
        return answer
