"""
Windows portable release 빌드 스크립트.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


APP_NAME = "ENE"
PLATFORM_SUFFIX = "win64"
PYINSTALLER_COLLECT_ALL = (
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "tiktoken",
    "tiktoken_ext",
)


def normalize_version_label(version: str | None) -> str:
    normalized = str(version or "").strip()
    return normalized or "dev"


def build_archive_name(version: str | None) -> str:
    return f"{APP_NAME}-{normalize_version_label(version)}-{PLATFORM_SUFFIX}.zip"


def collect_data_mappings(project_root: Path) -> list[tuple[Path, str]]:
    return [
        (project_root / "assets" / "icons", "assets/icons"),
        (project_root / "assets" / "web", "assets/web"),
        (project_root / "assets" / "live2d_models" / "hiyori", "assets/live2d_models/hiyori"),
        (project_root / "src" / "locales", "src/locales"),
        (project_root / "prompts" / "defaults", "prompts/defaults"),
    ]


def _format_add_data_arg(source: Path, target: str) -> str:
    return f"{source}{os.pathsep}{target}"


def build_pyinstaller_command(project_root: Path) -> list[str]:
    dist_root = project_root / "dist"
    build_root = project_root / "build" / "pyinstaller"
    spec_root = project_root / "build" / "spec"
    icon_path = project_root / "assets" / "icons" / "ene_app.ico"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist_root),
        "--workpath",
        str(build_root),
        "--specpath",
        str(spec_root),
    ]

    if icon_path.exists():
        command.extend(["--icon", str(icon_path)])

    for source, target in collect_data_mappings(project_root):
        command.extend(["--add-data", _format_add_data_arg(source, target)])

    for package_name in PYINSTALLER_COLLECT_ALL:
        command.extend(["--collect-all", package_name])

    command.append(str(project_root / "main.py"))
    return command


def _clean_previous_outputs(project_root: Path) -> None:
    shutil.rmtree(project_root / "dist" / APP_NAME, ignore_errors=True)
    shutil.rmtree(project_root / "build" / "pyinstaller", ignore_errors=True)
    shutil.rmtree(project_root / "build" / "spec", ignore_errors=True)


def create_portable_archive(dist_dir: Path, release_dir: Path, archive_name: str) -> Path:
    release_dir.mkdir(parents=True, exist_ok=True)
    archive_path = release_dir / archive_name
    if archive_path.exists():
        archive_path.unlink()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in dist_dir.rglob("*"):
            if path.is_dir():
                continue
            archive_path_in_zip = Path(dist_dir.name) / path.relative_to(dist_dir)
            zip_file.write(path, archive_path_in_zip)

    return archive_path


def build_release(project_root: Path, version: str | None) -> Path:
    _clean_previous_outputs(project_root)
    command = build_pyinstaller_command(project_root)
    subprocess.run(command, check=True, cwd=project_root)

    dist_dir = project_root / "dist" / APP_NAME
    if not dist_dir.exists():
        raise FileNotFoundError(f"PyInstaller output not found: {dist_dir}")

    archive_name = build_archive_name(version)
    return create_portable_archive(dist_dir, project_root / "release", archive_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ENE Windows portable release.")
    parser.add_argument("--version", default="", help="릴리스 버전 또는 태그 이름")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="프로젝트 루트 경로",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    archive_path = build_release(project_root, args.version)
    print(f"[Release] Portable archive created: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
