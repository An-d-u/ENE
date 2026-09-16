"""명시된 공유 실행부만 검증·복사한다. 모델/설정 검색이나 자동 다운로드는 하지 않는다."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/companion/character-runtime.json"
RUNTIME = (
    "runtime_character_state.js",
    "runtime_live2d_model.js",
    "runtime_motion_state.js",
    "runtime_gesture_engine.js",
    "runtime_head_pat.js",
    "runtime_auto_blink_tracking.js",
    "runtime_expression.js",
    "runtime_lipsync.js",
    "runtime_live2d_parameter_core.js",
    "runtime_character_host.js",
)
LIBRARIES = ("pixi.min.js", "live2dcubismcore.min.js", "pixi-live2d-display.min.js")
NOTICES = (
    "Pixi-MIT.txt",
    "pixi-live2d-display-MIT.txt",
    "CubismWebFramework-LICENSE.md",
    "THIRD-PARTY.md",
)
ALLOWED = {f"assets/web/{name}": name for name in RUNTIME}
ALLOWED.update({f"assets/web/lib/{name}": f"lib/{name}" for name in LIBRARIES})
ALLOWED.update(
    {
        f"assets/web/character/{name}": name
        for name in ("index.html", "entry.js", "style.css")
    }
)
ALLOWED.update(
    {f"assets/web/character/notices/{name}": f"notices/{name}" for name in NOTICES}
)


class ExportError(ValueError):
    """민감한 경로 원문을 포함하지 않는 내보내기 오류."""


def unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    # Python 3.11에서도 정션·기타 재분석 지점을 우회하지 못하게 한다.
    return bool(getattr(info, "st_file_attributes", 0) & 0x400) or (
        path.is_file() and info.st_nlink != 1
    )


def safe_path(root: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or "\\" in relative
        or "%" in relative
        or ":" in relative
    ):
        raise ExportError("허용되지 않은 파일 경로")
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or relative != "/".join(parts)
        or any(part in (".", "..", "") for part in parts)
    ):
        raise ExportError("허용되지 않은 파일 경로")
    path = root
    for part in parts:
        path = path / part
        if unsafe_link(path):
            raise ExportError("링크 경로는 내보낼 수 없음")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ExportError("기준 디렉터리 이탈")
    return path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(root: Path) -> dict:
    try:
        return json.loads(safe_path(root, CONTRACT).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ExportError("실행부 계약을 읽지 못함") from error


def validate(root: Path, manifest: dict) -> dict[str, bytes]:
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or manifest.get("runtime_version") != 1
    ):
        raise ExportError("실행부 계약 버전 불일치")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != len(ALLOWED):
        raise ExportError("실행부 목록 누락 또는 초과")
    content = {}
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"source", "target", "sha256"}:
            raise ExportError("실행부 목록 형식 불일치")
        source, target, expected = entry["source"], entry["target"], entry["sha256"]
        if (
            not isinstance(source, str)
            or source in seen
            or ALLOWED.get(source) != target
        ):
            raise ExportError("허용되지 않은 실행부 파일")
        seen.add(source)
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ExportError("실행부 해시 형식 불일치")
        try:
            data = safe_path(root, source).read_bytes()
        except OSError as error:
            raise ExportError("실행부 파일 누락") from error
        if len(data) > 2 * 1024 * 1024 or digest(data) != expected:
            raise ExportError("실행부 해시 또는 크기 불일치")
        content[target] = data
    libraries = manifest.get("libraries", [])
    if len(libraries) != 3 or {item.get("file") for item in libraries} != {
        f"lib/{name}" for name in LIBRARIES
    }:
        raise ExportError("라이브러리 고정 정보 누락")
    for item in libraries:
        if not item.get("version") or not str(item.get("source", "")).startswith(
            "https://"
        ):
            raise ExportError("라이브러리 출처 누락")
        if item.get("sha256") != digest(content[item["file"]]) or not item.get(
            "notices"
        ):
            raise ExportError("라이브러리 해시 또는 고지 누락")
        if any(
            name not in content or not name.startswith("notices/")
            for name in item["notices"]
        ):
            raise ExportError("라이브러리 고지 파일 누락")
    return content


def export(root: Path, android_root: Path) -> None:
    manifest = load_manifest(root)
    content = validate(root, manifest)
    if (
        not android_root.is_absolute()
        or not android_root.is_dir()
        or unsafe_link(android_root)
    ):
        raise ExportError("기존 Android 프로젝트의 절대 경로가 필요함")
    if android_root.resolve().is_relative_to(root.resolve()):
        raise ExportError("PC 작업 트리 내부로 내보낼 수 없음")
    for required in ("settings.gradle.kts", "app/build.gradle.kts"):
        if not safe_path(android_root, required).is_file():
            raise ExportError("Android 프로젝트 확인 실패")
    target = safe_path(android_root, "app/src/main/assets/character")
    imported = safe_path(target, "import-manifest.json")
    previous = {}
    if imported.exists():
        try:
            previous = {
                item["target"]: item["sha256"]
                for item in json.loads(imported.read_text(encoding="utf-8"))["files"]
            }
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ExportError("이전 가져오기 계약 확인 실패") from error
    if target.exists():
        allowed = set(content) | {"import-manifest.json"}
        for path in target.rglob("*"):
            relative = path.relative_to(target).as_posix()
            safe_path(target, relative)
            if path.is_file() and relative not in allowed:
                raise ExportError("알 수 없는 대상 파일을 보존하기 위해 중단")
        for relative, data in content.items():
            path = safe_path(target, relative)
            if path.exists() and digest(path.read_bytes()) not in (
                digest(data),
                previous.get(relative),
            ):
                raise ExportError("대상 변경 감지: 사용자 수정을 보존하기 위해 중단")
    # 모든 검증 뒤에만 쓰며 계약을 마지막에 기록한다. 파일 삭제는 하지 않는다.
    for relative, data in content.items():
        path = safe_path(target, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    imported.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="실행부 목록·고지·해시만 검사"
    )
    parser.add_argument(
        "--android-root", type=Path, help="독립 Android 프로젝트의 절대 경로"
    )
    args = parser.parse_args()
    try:
        if args.android_root is not None:
            export(ROOT, args.android_root)
            print("캐릭터 실행부 복사 완료. 공개 배포·실기기 호환성 검증은 별도입니다.")
        else:
            validate(ROOT, load_manifest(ROOT))
            print("캐릭터 실행부 목록·고지·해시 검사 통과")
    except ExportError as error:
        print(f"캐릭터 실행부 검사 실패: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
