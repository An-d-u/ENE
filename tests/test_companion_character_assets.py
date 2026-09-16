"""합성 참조 그래프를 검사한다. moc 바이트의 SDK 렌더링 성공을 흉내 내지 않는다."""

from io import BytesIO
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

from PIL import Image
import pytest

from src.core.companion.character_assets import AssetError, AssetLimits, build_bundle


def test_python311_file_metadata_and_path_api_are_supported(tmp_path, monkeypatch):
    from src.core.companion.character_assets import _file_identity

    monkeypatch.delattr(Path, "is_junction", raising=False)
    assert build_bundle(synthetic_model(tmp_path)).assets
    info = SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
    assert _file_identity(info) == (1, 2, 3, 4, 5)


@pytest.mark.skipif(os.name != "nt", reason="Windows 정션 경계")
def test_real_junction_cannot_expand_selected_model_root(tmp_path):
    import _winapi

    root, outside = tmp_path / "root", tmp_path / "outside"
    outside.mkdir()
    path = synthetic_model(root)
    link = root / "linked"
    _winapi.CreateJunction(str(outside), str(link))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        value["FileReferences"]["Moc"] = "linked/outside.moc3"
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(AssetError, match="invalid_asset_path"):
            build_bundle(path)
        assert list(outside.iterdir()) == []
    finally:
        # 시험에서 만든 정션 자체만 제거한다. 대상 폴더를 순회하지 않는다.
        link.rmdir()


def test_hard_linked_model_asset_is_rejected(tmp_path):
    path = synthetic_model(tmp_path)
    os.link(tmp_path / "shape.moc3", tmp_path / "duplicate.moc3")
    with pytest.raises(AssetError, match="invalid_asset"):
        build_bundle(path)


def synthetic_model(root, references=None):
    root.mkdir(exist_ok=True)
    # 패커는 moc를 불투명 바이트로만 취급한다. 이 데이터는 유효한 Live2D 모델이 아니다.
    (root / "shape.moc3").write_bytes(b"MOC3" + bytes(32))
    stream = BytesIO()
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(stream, format="PNG")
    (root / "texture.png").write_bytes(stream.getvalue())
    (root / "motion.motion3.json").write_text(
        '{"Version":3,"Curves":[]}', encoding="utf-8"
    )
    (root / "face.exp3.json").write_text(
        '{"Type":"Live2D Expression","Parameters":[]}', encoding="utf-8"
    )
    refs = references or {
        "Moc": "shape.moc3",
        "Textures": ["texture.png"],
        "Expressions": [{"Name": "bright", "File": "face.exp3.json"}],
        "Motions": {
            "Idle": [{"File": "motion.motion3.json", "Sound": "not-transferred.wav"}]
        },
    }
    model = root / "shape.model3.json"
    model.write_text(
        json.dumps({"Version": 3, "FileReferences": refs}), encoding="utf-8"
    )
    return model


def test_bundle_rewrites_only_safe_references_and_drops_sound(tmp_path):
    bundle = build_bundle(synthetic_model(tmp_path))
    payload = json.loads(bundle.asset(bundle.entry_asset_id).body)
    refs = payload["FileReferences"]
    assert refs["Moc"] != "shape.moc3"
    assert refs["Textures"][0] != "texture.png"
    assert "Sound" not in refs["Motions"]["Idle"][0]
    assert len(bundle.assets) == 5
    assert bundle.expression_ids == ("bright", "normal")
    assert all(len(asset.id) == len(asset.sha256) == 64 for asset in bundle.assets)
    assert all(
        "shape" not in str(item) and "texture.png" not in str(item)
        for item in bundle.descriptors()
    )
    assert "MOC3" not in repr(bundle)


@pytest.mark.parametrize(
    "path",
    [
        "../outside.moc3",
        "/absolute.moc3",
        "C:/private.moc3",
        "https://invalid.test/a",
        "data:abc",
        "%2e%2e/a",
        "%252e%252e/a",
        "folder\\a.moc3",
    ],
)
def test_reference_escape_or_encoded_path_is_rejected(tmp_path, path):
    with pytest.raises(AssetError):
        build_bundle(
            synthetic_model(tmp_path, {"Moc": path, "Textures": ["texture.png"]})
        )


def test_version_depends_on_bytes_and_runtime_not_local_path(tmp_path):
    first = build_bundle(synthetic_model(tmp_path / "one"))
    other_path = synthetic_model(tmp_path / "two")
    second = build_bundle(other_path)
    assert first.model_version == second.model_version
    assert first.model_id == second.model_id
    assert (
        first.model_version != build_bundle(other_path, runtime_version=2).model_version
    )
    texture = other_path.parent / "texture.png"
    stream = BytesIO()
    Image.new("RGBA", (4, 4), (0, 20, 0, 255)).save(stream, format="PNG")
    texture.write_bytes(stream.getvalue())
    assert first.model_version != build_bundle(other_path).model_version


@pytest.mark.parametrize(
    "limits",
    [
        AssetLimits(files=2),
        AssetLimits(total_bytes=40),
        AssetLimits(file_bytes=16),
        AssetLimits(texture_side=2),
    ],
)
def test_allocation_and_texture_limits_are_enforced(tmp_path, limits):
    with pytest.raises(AssetError):
        build_bundle(synthetic_model(tmp_path), limits=limits)


def test_links_and_changes_during_read_are_rejected(tmp_path, monkeypatch):
    path = synthetic_model(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda value: value.name == "shape.moc3" or original(value)
    )
    with pytest.raises(AssetError):
        build_bundle(path)
    monkeypatch.undo()
    from src.core.companion import character_assets

    original_read = character_assets._read_file

    def changed(*args, **kwargs):
        value = original_read(*args, **kwargs)
        if args[0].name == "shape.moc3":
            args[0].write_bytes(b"MOC3-changed")
        return value

    monkeypatch.setattr(character_assets, "_read_file", changed)
    with pytest.raises(AssetError, match="asset_changed"):
        build_bundle(path)


def test_extra_emotions_stay_inside_selected_root_and_unknown_fields_do_not_leave(
    tmp_path,
):
    path = synthetic_model(tmp_path)
    (tmp_path / "emotions").mkdir()
    (tmp_path / "emotions/soft.exp3.json").write_text(
        '{"Parameters":[]}', encoding="utf-8"
    )
    model = json.loads(path.read_text(encoding="utf-8"))
    model["private_note"] = "합성 제외 필드"
    model["FileReferences"]["UserData"] = "not-transferred.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    bundle = build_bundle(path, emotions=("soft",))
    result = json.loads(bundle.asset(bundle.entry_asset_id).body)
    assert "private_note" not in result
    assert "UserData" not in result["FileReferences"]
    assert "soft" in bundle.expression_ids
    with pytest.raises(AssetError):
        build_bundle(path, emotions=("../escape",))


def test_cancellation_invalid_json_and_unknown_reference_fail_closed(tmp_path):
    path = synthetic_model(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AssetError, match="cancelled"):
        build_bundle(path, cancel=cancel)
    path.write_text(
        '{"Version":3,"FileReferences":{"Moc":"shape.moc3","NewExternalFile":"outside"}}',
        encoding="utf-8",
    )
    with pytest.raises(AssetError):
        build_bundle(path)


def test_non_model_file_extension_and_nonfinite_json_are_not_transferred(tmp_path):
    path = synthetic_model(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["FileReferences"]["Physics"] = "settings.json"
    (tmp_path / "settings.json").write_text(
        '{"synthetic_setting":true}', encoding="utf-8"
    )
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AssetError):
        build_bundle(path)
    value["FileReferences"].pop("Physics")
    path.write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "motion.motion3.json").write_text(
        '{"Version":3,"Curves":[],"Meta":{"Duration":1e999}}', encoding="utf-8"
    )
    with pytest.raises(AssetError):
        build_bundle(path)
    path.write_text('{"Version":NaN}', encoding="utf-8")
    with pytest.raises(AssetError):
        build_bundle(path)
