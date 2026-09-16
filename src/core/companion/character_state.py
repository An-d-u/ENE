"""Qt 소유의 공개 캐릭터 상태. 파일·SDK·연결 객체는 상태 기계에 넣지 않는다."""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import math

from .character_assets import CharacterBundle
from .extension_protocol import (
    BOOL_SETTINGS,
    EXPRESSION_SETTINGS,
    INT_SETTINGS,
    NUMBER_SETTINGS,
    normalize_settings,
)
from .protocol import ProtocolError, uuid_value
from ..settings import Settings


SETTING_KEYS = (
    BOOL_SETTINGS
    | EXPRESSION_SETTINGS
    | INT_SETTINGS.keys()
    | NUMBER_SETTINGS.keys()
    | {"idle_synthetic_gesture_frequency"}
)


class CharacterStateError(ValueError):
    """공개 경계에는 고정 코드만 전달한다."""


@dataclass(frozen=True)
class CharacterCapture:
    body: bytes = field(repr=False)
    bundle: CharacterBundle | None = field(repr=False)


def _identifier(value):
    try:
        valid = (
            isinstance(value, str)
            and bool(value.strip())
            and len(value.encode("utf-8")) <= 128
            and value not in {"__proto__", "constructor", "prototype"}
            and not any(ord(c) < 32 for c in value)
        )
    except UnicodeError:
        valid = False
    if not valid:
        raise CharacterStateError("invalid_catalog")
    return value


def _ids(values):
    if not isinstance(values, list) or len(values) > 256:
        raise CharacterStateError("invalid_catalog")
    result = [_identifier(value) for value in values]
    if len(set(result)) != len(result):
        raise CharacterStateError("invalid_catalog")
    return sorted(result)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _settings(values):
    result = {}
    for key in sorted(SETTING_KEYS):
        fallback = Settings.DEFAULT_CONFIG[key]
        try:
            result.update(normalize_settings({key: values.get(key, fallback)}))
        except ProtocolError:
            result[key] = fallback
    return result


class CharacterState:
    def __init__(self):
        self.state_revision = self.settings_revision = 1
        self.action_seq = 0
        self.generation = None
        self.bundle = None
        self.status = "unavailable"
        self.settings = _settings({})
        self.parameters = {}
        self.catalog = []
        self.expressions = []
        self.gestures = []
        self.default_expression = "normal"
        self._head_pat_defaults = {"active": "normal", "end": "normal"}

    def set_head_pat_defaults(self, values):
        """PC의 기존 우선순위는 유지하되 실제 공개 카탈로그 ID만 내보낸다."""
        before = self.head_pat_defaults()
        for phase in ("active", "end"):
            resolved = values.get(f"head_pat_{phase}_emotion", "")
            default = values.get(f"head_pat_{phase}_emotion_default", "normal")
            self._head_pat_defaults[phase] = next(
                (value.strip() for value in (resolved, default) if isinstance(value, str) and value.strip()), "normal"
            )
        changed = before != self.head_pat_defaults()
        if changed:
            self.settings_revision += 1
            self.state_revision += 1
        return changed

    def head_pat_defaults(self):
        if self.status != "ready":
            return {}
        return {key: value if value in self.expressions else "normal" for key, value in self._head_pat_defaults.items()}

    def unavailable(self, status="unavailable"):
        if status not in {"unavailable", "unsupported", "loading"}:
            raise CharacterStateError("invalid_status")
        self.generation = self.bundle = None
        self.status = status
        self.catalog, self.expressions, self.gestures = [], [], []
        self.parameters = {}
        self.default_expression = "normal"
        self.state_revision += 1

    def select(self, generation, bundle, settings, parameters):
        uuid_value(generation)
        self.unavailable("loading")
        self.generation, self.bundle = generation, bundle
        self.settings = _settings(settings)
        self.parameters = dict(parameters)
        self.set_head_pat_defaults(settings)
        self.settings_revision += 1

    def accept_catalog(self, generation, version, catalog, expressions, gestures):
        if self.bundle is None or (generation, version) != (
            self.generation,
            self.bundle.model_version,
        ):
            return False
        if not isinstance(catalog, list) or len(catalog) > 256:
            raise CharacterStateError("invalid_catalog")
        clean = []
        for item in catalog:
            if not isinstance(item, dict) or set(item) != {
                "id",
                "min",
                "max",
                "default",
            }:
                raise CharacterStateError("invalid_catalog")
            key = _identifier(item["id"])
            if (
                not all(_number(item[k]) for k in ("min", "max", "default"))
                or not item["min"] <= item["default"] <= item["max"]
            ):
                raise CharacterStateError("invalid_catalog")
            clean.append(dict(item, id=key))
        if len({item["id"] for item in clean}) != len(clean):
            raise CharacterStateError("invalid_catalog")
        clean.sort(key=lambda item: item["id"])
        expression_ids, gesture_ids = _ids(expressions), _ids(gestures)
        expression_ids = sorted(set(expression_ids) & set(self.bundle.expression_ids))
        parameters = {
            item["id"]: self.parameters[item["id"]]
            for item in clean
            if _number(self.parameters.get(item["id"]))
            and item["min"] <= self.parameters[item["id"]] <= item["max"]
        }
        self.catalog, self.expressions, self.gestures = (
            clean,
            expression_ids,
            gesture_ids,
        )
        self.parameters = parameters
        for key in EXPRESSION_SETTINGS:
            if self.settings[key] not in self.expressions:
                self.settings[key] = ""
        self.status = "ready"
        self.state_revision += 1
        return True

    def snapshot(self):
        ready = self.status == "ready" and self.bundle is not None
        bundle = self.bundle if ready else None
        return deepcopy(
            {
                "model_id": bundle.model_id if bundle else None,
                "model_version": bundle.model_version if bundle else None,
                "runtime_version": bundle.runtime_version if bundle else 1,
                "state_revision": self.state_revision,
                "settings_revision": self.settings_revision,
                "action_seq": self.action_seq,
                "settings": self.settings,
                "head_pat_defaults": self.head_pat_defaults(),
                "parameters": self.parameters if ready else {},
                "parameter_catalog": self.catalog if ready else [],
                "expression_ids": self.expressions if ready else [],
                "gesture_ids": self.gestures if ready else [],
                "default_expression": self.default_expression,
                "assets": bundle.descriptors() if bundle else [],
                "entry_asset_id": bundle.entry_asset_id if bundle else None,
                "status": self.status,
            }
        )

    def commit_settings(self, settings, parameters):
        """검증·영속 저장이 끝난 사본만 적용한다. Qt 조정기 외부에서 호출하지 않는다."""
        self.settings, self.parameters = settings, parameters
        self.settings_revision += 1
        self.state_revision += 1

    def capture(self):
        body = json.dumps(
            self.snapshot(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > 256 * 1024:
            raise CharacterStateError("manifest_size_limit")
        return CharacterCapture(body, self.bundle if self.status == "ready" else None)

    def action(self, kind, action_id, duration_ms):
        allowed = (
            self.expressions
            if kind == "expression"
            else self.gestures
            if kind == "gesture"
            else ()
        )
        if (
            self.status != "ready"
            or action_id not in allowed
            or type(duration_ms) is not int
            or not 0 <= duration_ms <= 30000
        ):
            return None
        self.action_seq += 1
        if kind == "expression":
            self.default_expression = action_id
        return {
            "action_seq": self.action_seq,
            "model_version": self.bundle.model_version,
            "kind": kind,
            "action_id": action_id,
            "duration_ms": duration_ms,
        }
