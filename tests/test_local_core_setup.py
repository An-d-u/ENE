"""SDK를 재배포하거나 자동 다운로드하지 않는 로컬 준비 경계."""

from pathlib import Path

import pytest

from scripts import setup_web_libs


def test_setup_never_downloads_or_overwrites_core(tmp_path, monkeypatch):
    core = tmp_path / "assets/web/lib/live2dcubismcore.min.js"
    core.parent.mkdir(parents=True)
    core.write_bytes(b"synthetic user-owned core")
    downloads = []
    monkeypatch.setattr(setup_web_libs, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(setup_web_libs, "download_file", lambda url, path: downloads.append((url, path)) or True)
    setup_web_libs.setup_libraries()
    assert len(downloads) == 2
    assert all("cubismcore" not in url.lower() for url, _ in downloads)
    assert core.read_bytes() == b"synthetic user-owned core"


def test_missing_core_reports_official_manual_installation(tmp_path, capsys):
    assert hasattr(setup_web_libs, "check_local_core"), "수동 Core 설치 검사 필요"
    assert setup_web_libs.check_local_core(tmp_path) is False
    output = capsys.readouterr().out
    assert "https://www.live2d.com/en/sdk/download/web/" in output
    assert "직접" in output


def test_wrong_core_is_preserved_and_rejected(tmp_path):
    assert hasattr(setup_web_libs, "check_local_core"), "수동 Core 해시 검사 필요"
    core = tmp_path / "assets/web/lib/live2dcubismcore.min.js"
    core.parent.mkdir(parents=True)
    core.write_bytes(b"synthetic invalid core")
    assert setup_web_libs.check_local_core(tmp_path) is False
    assert core.read_bytes() == b"synthetic invalid core"


def test_pinned_local_core_is_accepted_without_network():
    assert hasattr(setup_web_libs, "check_local_core"), "수동 Core 해시 검사 필요"
    root = Path(__file__).resolve().parents[1]
    core = root / "assets/web/lib/live2dcubismcore.min.js"
    if not core.exists():
        pytest.skip("선택적 로컬 SDK 통합 검사: Core 미설치")
    assert setup_web_libs.check_local_core(root) is True
