"""실행부 목록은 명시적이며 개인 모델이나 임의 경로를 내보내지 않는다."""

import copy
import json
from pathlib import Path
import shutil

import pytest

from tools.export_companion_character import (
    ExportError,
    export,
    load_manifest,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]


def test_repository_bundle_has_only_pinned_runtime_and_notices():
    manifest = load_manifest(ROOT)
    validate(ROOT, manifest)
    targets = {item["target"] for item in manifest["files"]}
    assert "index.html" in targets and "runtime_character_host.js" in targets
    assert "script.js" not in targets and "runtime_bootstrap.js" not in targets
    assert not any(
        "model" in name and name != "runtime_live2d_model.js" for name in targets
    )
    assert len(manifest["libraries"]) == 3


@pytest.mark.parametrize("change", ["hash", "missing", "extra", "escape", "duplicate"])
def test_tampered_or_unlisted_file_is_rejected(change):
    manifest = copy.deepcopy(load_manifest(ROOT))
    if change == "hash":
        manifest["files"][0]["sha256"] = "0" * 64
    elif change == "missing":
        manifest["files"].pop()
    elif change == "extra":
        manifest["files"].append(
            {"source": "config.json", "target": "config.json", "sha256": "0" * 64}
        )
    elif change == "escape":
        manifest["files"][0]["target"] = "../private.js"
    else:
        manifest["files"].append(manifest["files"][0])
    with pytest.raises(ExportError):
        validate(ROOT, manifest)


def test_export_is_standalone_repeatable_and_refuses_unowned_target(tmp_path):
    app = tmp_path / "ENE_APP"
    (app / "app/src/main/assets").mkdir(parents=True)
    (app / "settings.gradle.kts").write_text("// 합성 프로젝트\n", encoding="utf-8")
    (app / "app/build.gradle.kts").write_text("// 합성 모듈\n", encoding="utf-8")
    export(ROOT, app)
    target = app / "app/src/main/assets/character"
    imported = json.loads((target / "import-manifest.json").read_text(encoding="utf-8"))
    assert imported == load_manifest(ROOT)
    for item in imported["files"]:
        assert (target / item["target"]).read_bytes() == (
            ROOT / item["source"]
        ).read_bytes()
    export(ROOT, app)
    (target / "entry.js").write_text("// 별도 사용자 수정\n", encoding="utf-8")
    with pytest.raises(ExportError, match="대상 변경"):
        export(ROOT, app)
    assert (target / "entry.js").read_text(encoding="utf-8") == "// 별도 사용자 수정\n"


def test_unknown_file_is_not_removed_or_silently_included(tmp_path):
    app = tmp_path / "ENE_APP"
    (app / "app/src/main/assets/character").mkdir(parents=True)
    (app / "settings.gradle.kts").touch()
    (app / "app/build.gradle.kts").touch()
    unknown = app / "app/src/main/assets/character/unowned.txt"
    unknown.write_text("합성 파일", encoding="utf-8")
    with pytest.raises(ExportError):
        export(ROOT, app)
    assert unknown.exists()


def test_source_change_fails_before_any_destination_write(tmp_path):
    source = tmp_path / "PC"
    manifest = load_manifest(ROOT)
    for item in manifest["files"]:
        file = source / item["source"]
        file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / item["source"], file)
    contract = source / "contracts/companion/character-runtime.json"
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps(manifest), encoding="utf-8")
    (source / manifest["files"][0]["source"]).write_text(
        "변경된 합성 코드", encoding="utf-8"
    )
    with pytest.raises(ExportError):
        export(source, tmp_path / "ENE_APP")
    assert not (tmp_path / "ENE_APP").exists()


def test_import_manifest_link_is_refused_before_reading(tmp_path, monkeypatch):
    app = tmp_path / "ENE_APP"
    (app / "app/src/main/assets/character").mkdir(parents=True)
    (app / "settings.gradle.kts").touch()
    (app / "app/build.gradle.kts").touch()
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path.name == "import-manifest.json" or original(path),
    )
    with pytest.raises(ExportError, match="링크"):
        export(ROOT, app)
