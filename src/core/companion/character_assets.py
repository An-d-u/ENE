"""선택된 모델 폴더의 허용 참조만 불변 바이트로 고정한다. moc 해석은 PC SDK의 책임이다."""

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading

from PIL import Image


class AssetError(ValueError):
    """로컬 경로·파일 내용 대신 고정 오류 코드만 전달한다."""


@dataclass(frozen=True)
class AssetLimits:
    files: int = 256
    total_bytes: int = 128 * 1024 * 1024
    file_bytes: int = 32 * 1024 * 1024
    texture_side: int = 8192


@dataclass(frozen=True)
class CharacterAsset:
    id: str
    sha256: str
    size: int
    mime: str
    body: bytes = field(repr=False)

    def descriptor(self):
        return {
            "id": self.id,
            "sha256": self.sha256,
            "size": self.size,
            "mime": self.mime,
        }


@dataclass(frozen=True)
class CharacterBundle:
    model_id: str
    model_version: str
    runtime_version: int
    entry_asset_id: str
    expression_ids: tuple[str, ...]
    assets: tuple[CharacterAsset, ...] = field(repr=False)

    def asset(self, asset_id):
        for asset in self.assets:
            if asset.id == asset_id:
                return asset
        raise AssetError("asset_not_found")

    def descriptors(self):
        return [asset.descriptor() for asset in self.assets]


def _cancelled(cancel):
    if cancel.is_set():
        raise AssetError("cancelled")


def _signature(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AssetError("invalid_asset")
    return _file_identity(info)


def _file_identity(info):
    # Windows Python 3.12의 stat/fstat ctime 의미가 다르므로 명시적 생성 시각을 쓴다.
    stamp = (
        getattr(info, "st_birthtime_ns", info.st_ctime_ns)
        if os.name == "nt"
        else info.st_ctime_ns
    )
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stamp)


def _checked_path(root, relative):
    if (
        not isinstance(relative, str)
        or not relative
        or any(c in relative for c in ("%", "\\", ":", "\x00", "?", "#"))
    ):
        raise AssetError("invalid_asset_path")
    parts = PurePosixPath(relative).parts
    if relative != "/".join(parts) or any(part in ("/", ".", "..") for part in parts):
        raise AssetError("invalid_asset_path")
    if root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
        raise AssetError("invalid_asset_path")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise AssetError("invalid_asset_path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise AssetError("invalid_asset_path")
    return path


def _read_file(path, max_bytes, cancel):
    """경로 메타데이터와 열린 핸들이 같은 파일을 계속 가리키는지 검사한다."""
    _cancelled(cancel)
    before = _signature(path)
    if before[2] <= 0 or before[2] > max_bytes:
        raise AssetError("asset_size_limit")
    data = bytearray()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if _file_identity(opened) != before:
            raise AssetError("asset_changed")
        while True:
            _cancelled(cancel)
            chunk = handle.read(min(65536, max_bytes - len(data) + 1))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise AssetError("asset_size_limit")
        after = os.fstat(handle.fileno())
        if _file_identity(after) != before or after.st_ctime_ns != opened.st_ctime_ns:
            raise AssetError("asset_changed")
    if _signature(path) != before or len(data) != before[2]:
        raise AssetError("asset_changed")
    return bytes(data), before


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise AssetError("invalid_asset_json")
        result[key] = value
    return result


def _json(raw):
    try:

        def invalid(_):
            raise AssetError("invalid_asset_json")

        value = json.loads(
            raw.decode("utf-8-sig"), parse_constant=invalid, object_pairs_hook=_pairs
        )
        if not isinstance(value, dict):
            raise AssetError("invalid_asset_json")

        def inspect(item, depth=0):
            if depth > 32 or (isinstance(item, float) and not math.isfinite(item)):
                raise AssetError("invalid_asset_json")
            if isinstance(item, dict):
                if any(
                    key in ("__proto__", "constructor", "prototype") for key in item
                ):
                    raise AssetError("invalid_asset_json")
                for child in item.values():
                    inspect(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    inspect(child, depth + 1)

        inspect(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise AssetError("invalid_asset_json") from None


def _encode(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise AssetError("invalid_asset_json") from None


def _name(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 128
        or not re.fullmatch(r"[\w-]+", value)
    ):
        raise AssetError("invalid_asset_id")
    return value


def build_bundle(
    model_path: Path,
    *,
    emotions=(),
    runtime_version=1,
    limits=AssetLimits(),
    cancel=None,
):
    """파일 제공용 패커다. 사용 가능 상태는 별도의 PC 렌더러 카탈로그 확인 후에만 확정한다."""
    cancel = cancel or threading.Event()
    model_path = Path(model_path).absolute()
    root = model_path.parent
    source = {}
    signatures = {}
    assets = {}
    total = 0

    def read(relative):
        nonlocal total
        path = _checked_path(root, relative)
        if relative not in source:
            if len(source) >= limits.files:
                raise AssetError("asset_count_limit")
            data, signature = _read_file(
                path, min(limits.file_bytes, limits.total_bytes - total), cancel
            )
            source[relative] = data
            signatures[relative] = signature
            total += len(data)
        return source[relative]

    def add(raw, body, mime):
        _cancelled(cancel)
        key = sha256(raw).hexdigest()
        item = CharacterAsset(key, sha256(body).hexdigest(), len(body), mime, body)
        if key in assets and assets[key] != item:
            raise AssetError("ambiguous_asset_id")
        assets[key] = item
        if (
            len(body) > limits.file_bytes
            or sum(value.size for value in assets.values()) > limits.total_bytes
        ):
            raise AssetError("asset_size_limit")
        return key

    def binary(relative, kind):
        suffixes = {
            "moc": (".moc3",),
            "texture": (".png", ".jpg", ".jpeg"),
            "physics": (".physics3.json",),
            "pose": (".pose3.json",),
            "expression": (".exp3.json",),
            "motion": (".motion3.json",),
        }
        if not isinstance(relative, str) or not relative.lower().endswith(
            suffixes[kind]
        ):
            raise AssetError("unsupported_asset_type")
        raw = read(relative)
        mime = "application/octet-stream"
        if kind == "texture":
            try:
                with Image.open(BytesIO(raw)) as image:
                    if image.format not in ("PNG", "JPEG") or not (
                        0 < image.width <= limits.texture_side
                        and 0 < image.height <= limits.texture_side
                    ):
                        raise AssetError("invalid_texture")
                    mime = "image/png" if image.format == "PNG" else "image/jpeg"
                    image.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise AssetError("invalid_texture") from None
        elif kind not in ("moc", "texture"):
            _json(raw)
            mime = "application/json"
        return add(raw, raw, mime)

    try:
        if type(runtime_version) is not int or runtime_version < 1:
            raise AssetError("invalid_runtime_version")
        if not model_path.name.lower().endswith(".model3.json"):
            raise AssetError("unsupported_model")
        raw_model = read(model_path.name)
        model = _json(raw_model)
        refs = model.get("FileReferences")
        allowed = {
            "Moc",
            "Textures",
            "Physics",
            "Pose",
            "Expressions",
            "Motions",
            "DisplayInfo",
            "UserData",
        }
        if (
            type(model.get("Version")) is not int
            or model["Version"] != 3
            or not isinstance(refs, dict)
            or set(refs) - allowed
        ):
            raise AssetError("unsupported_model")
        textures = refs.get("Textures", [])
        if (
            not isinstance(textures, list)
            or not textures
            or len(textures) > limits.files
        ):
            raise AssetError("invalid_texture")
        converted = {
            "Moc": binary(refs.get("Moc"), "moc"),
            "Textures": [binary(path, "texture") for path in textures],
        }
        for key in ("Physics", "Pose"):
            if key in refs:
                converted[key] = binary(refs[key], key.lower())
        expressions = {}
        raw_expressions = refs.get("Expressions", [])
        if not isinstance(raw_expressions, list) or len(raw_expressions) > 256:
            raise AssetError("invalid_expression")
        for item in raw_expressions:
            if not isinstance(item, dict):
                raise AssetError("invalid_expression")
            name = _name(item.get("Name"))
            if name in expressions:
                raise AssetError("invalid_expression")
            expressions[name] = binary(item.get("File"), "expression")
        for name in emotions:
            name = _name(name)
            if name != "normal" and name not in expressions:
                expressions[name] = binary(f"emotions/{name}.exp3.json", "expression")
        converted["Expressions"] = [
            {"Name": name, "File": value} for name, value in sorted(expressions.items())
        ]
        motions = refs.get("Motions", {})
        if not isinstance(motions, dict) or len(motions) > 256:
            raise AssetError("invalid_motion")
        converted["Motions"] = {}
        for group, items in motions.items():
            _name(group)
            if not isinstance(items, list) or len(items) > 256:
                raise AssetError("invalid_motion")
            converted_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise AssetError("invalid_motion")
                # Sound는 선택적 PC 음향이므로 파일도 읽지 않고 참조도 제거한다.
                value = {
                    key: item[key]
                    for key in ("FadeInTime", "FadeOutTime")
                    if key in item
                }
                value["File"] = binary(item.get("File"), "motion")
                converted_items.append(value)
            converted["Motions"][group] = converted_items
        result = {
            key: model[key] for key in ("Groups", "HitAreas", "Layout") if key in model
        }
        result.update(Version=3, FileReferences=converted)
        entry = add(raw_model, _encode(result), "application/json")
        for relative, expected in signatures.items():
            _cancelled(cancel)
            if _signature(_checked_path(root, relative)) != expected:
                raise AssetError("asset_changed")
        ordered = tuple(assets[key] for key in sorted(assets))
        version = sha256(
            _encode(
                {
                    "runtime_version": runtime_version,
                    "entry_asset_id": entry,
                    "assets": [item.descriptor() for item in ordered],
                }
            )
        ).hexdigest()
        return CharacterBundle(
            entry,
            version,
            runtime_version,
            entry,
            tuple(sorted({"normal", *expressions})),
            ordered,
        )
    except AssetError:
        raise
    except (OSError, UnicodeError, TypeError, OverflowError, RecursionError):
        raise AssetError("invalid_asset") from None
