from pathlib import Path


README_PATH = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_mentions_forui_icon_license_notice():
    readme = README_PATH.read_text(encoding="utf-8-sig")
    assert "Forui" in readme
    assert "Lucide" in readme
    assert "ISC License" in readme
