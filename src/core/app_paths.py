"""
ENE 런타임 경로 유틸리티.

- 번들 내부 리소스 경로
- 사용자 데이터 저장 경로
- 상대 경로 저장/해석 규칙
을 한 곳에서 관리한다.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path


APP_NAME = "ENE"
USER_DATA_DIR_ENV = "ENE_USER_DATA_DIR"
BUNDLE_ROOT_ENV = "ENE_BUNDLE_DIR"


def _normalize_path(path_like: str | Path) -> Path:
    return Path(str(path_like)).expanduser()


def get_bundle_root() -> Path:
    """실행 중인 앱이 읽어야 하는 번들 루트를 반환한다."""
    override = str(os.environ.get(BUNDLE_ROOT_ENV, "") or "").strip()
    if override:
        return _normalize_path(override)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[2]


def is_windows_store_python_runtime() -> bool:
    """Microsoft Store Python 런타임 여부를 반환한다."""
    executable = str(getattr(sys, "executable", "") or "").lower()
    return os.name == "nt" and "\\windowsapps\\pythonsoftwarefoundation.python." in executable


def get_visible_user_data_dir(app_name: str = APP_NAME) -> Path:
    """사용자가 탐색기에서 보는 실제 Roaming 사용자 데이터 루트를 반환한다."""
    if os.name == "nt":
        return Path.home() / "AppData" / "Roaming" / app_name
    return get_user_data_dir(app_name=app_name)


def get_user_data_dir(app_name: str = APP_NAME) -> Path:
    """사용자별 ENE 데이터 저장 루트를 반환한다."""
    override = str(os.environ.get(USER_DATA_DIR_ENV, "") or "").strip()
    if override:
        return _normalize_path(override)

    if os.name == "nt":
        appdata = str(os.environ.get("APPDATA", "") or "").strip()
        if appdata:
            return _normalize_path(appdata) / app_name
        return Path.home() / "AppData" / "Roaming" / app_name

    xdg_data_home = str(os.environ.get("XDG_DATA_HOME", "") or "").strip()
    if xdg_data_home:
        return _normalize_path(xdg_data_home) / app_name
    return Path.home() / ".local" / "share" / app_name


def ensure_directory(path: str | Path) -> Path:
    """디렉터리를 보장하고 절대 경로를 반환한다."""
    resolved = _normalize_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved.resolve()


def ensure_parent_dir(path: str | Path) -> Path:
    """파일의 부모 디렉터리를 보장하고 절대 경로를 반환한다."""
    resolved = _normalize_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved.resolve()


def get_user_file(filename: str) -> Path:
    """사용자 데이터 루트 아래 파일 경로를 반환한다."""
    return get_user_data_dir() / str(filename or "").strip()


def get_user_prompts_dir() -> Path:
    """사용자 프롬프트 디렉터리를 반환한다."""
    return get_user_data_dir() / "prompts"


def _should_bridge_store_python_user_data(path_like: str | Path, *, user_root: Path | None = None) -> bool:
    if not is_windows_store_python_runtime():
        return False
    if str(os.environ.get(USER_DATA_DIR_ENV, "") or "").strip():
        return False

    path_obj = _normalize_path(path_like)
    runtime_root = Path(user_root) if user_root is not None else get_user_data_dir()
    visible_root = get_visible_user_data_dir()

    if not path_obj.is_absolute():
        return True

    path_candidates = [path_obj]
    try:
        resolved_path = path_obj.resolve()
        if resolved_path not in path_candidates:
            path_candidates.append(resolved_path)
    except Exception:
        pass

    root_candidates: list[Path] = []
    for root in (runtime_root, visible_root):
        if root not in root_candidates:
            root_candidates.append(root)
        try:
            resolved_root = root.resolve()
            if resolved_root not in root_candidates:
                root_candidates.append(resolved_root)
        except Exception:
            continue

    for candidate in path_candidates:
        for root in root_candidates:
            try:
                candidate.relative_to(root)
                return True
            except Exception:
                continue
    return False


def _get_visible_store_python_path(path_like: str | Path, *, user_root: Path | None = None) -> Path | None:
    if not _should_bridge_store_python_user_data(path_like, user_root=user_root):
        return None

    path_obj = _normalize_path(path_like)
    visible_root = get_visible_user_data_dir()
    if not path_obj.is_absolute():
        return visible_root / path_obj

    runtime_root = Path(user_root) if user_root is not None else get_user_data_dir()
    path_candidates = [path_obj]
    try:
        resolved_path = path_obj.resolve()
        if resolved_path not in path_candidates:
            path_candidates.append(resolved_path)
    except Exception:
        pass

    root_candidates: list[Path] = []
    for root in (runtime_root, visible_root):
        if root not in root_candidates:
            root_candidates.append(root)
        try:
            resolved_root = root.resolve()
            if resolved_root not in root_candidates:
                root_candidates.append(resolved_root)
        except Exception:
            continue

    for candidate in path_candidates:
        for root in root_candidates:
            try:
                relative = candidate.relative_to(root)
                return visible_root / relative
            except Exception:
                continue
    return None


def _run_powershell_command(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )


def _read_file_bytes_via_powershell(path: Path) -> bytes | None:
    file_text = str(path).replace("'", "''")
    result = _run_powershell_command(
        "\n".join(
            [
                f"$path = '{file_text}'",
                "if (-not (Test-Path -LiteralPath $path)) { exit 0 }",
                "[Console]::Write([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)))",
            ]
        )
    )
    payload = str(result.stdout or "").strip()
    if not payload:
        return None
    return base64.b64decode(payload)


def _write_file_bytes_via_powershell(path: Path, payload: bytes) -> None:
    file_text = str(path).replace("'", "''")
    encoded = base64.b64encode(payload).decode("ascii")
    _run_powershell_command(
        "\n".join(
            [
                f"$path = '{file_text}'",
                f"$payload = '{encoded}'",
                "$parent = Split-Path -Parent $path",
                "New-Item -ItemType Directory -Path $parent -Force | Out-Null",
                "[IO.File]::WriteAllBytes($path, [Convert]::FromBase64String($payload))",
            ]
        )
    )


def sync_visible_store_python_file_to_runtime(
    path_like: str | Path,
    *,
    user_root: Path | None = None,
) -> Path:
    """
    Store Python 환경에서 실제 Roaming 파일을 런타임 가상화 경로로 복사한다.
    """
    runtime_path = _normalize_path(path_like)
    visible_path = _get_visible_store_python_path(runtime_path, user_root=user_root)
    if visible_path is None:
        return runtime_path

    try:
        payload = _read_file_bytes_via_powershell(visible_path)
        if payload is None:
            return runtime_path
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_bytes(payload)
    except Exception:
        pass
    return runtime_path


def sync_runtime_store_python_file_to_visible(
    path_like: str | Path,
    *,
    user_root: Path | None = None,
) -> Path:
    """
    Store Python 환경에서 런타임 가상화 파일을 실제 Roaming 위치로 복사한다.
    """
    runtime_path = _normalize_path(path_like)
    visible_path = _get_visible_store_python_path(runtime_path, user_root=user_root)
    if visible_path is None or not runtime_path.exists():
        return runtime_path

    try:
        _write_file_bytes_via_powershell(visible_path, runtime_path.read_bytes())
    except Exception:
        pass
    return runtime_path


def load_json_data(
    path_like: str | Path,
    *,
    encoding: str = "utf-8-sig",
    user_root: Path | None = None,
):
    """Store Python 경로 가상화를 고려해 JSON 파일을 읽는다."""
    target = sync_visible_store_python_file_to_runtime(path_like, user_root=user_root)
    with open(target, "r", encoding=encoding) as handle:
        return json.load(handle)


def read_text_data(
    path_like: str | Path,
    *,
    encoding: str = "utf-8-sig",
    user_root: Path | None = None,
) -> str:
    """Store Python 경로 가상화를 고려해 텍스트 파일을 읽는다."""
    target = sync_visible_store_python_file_to_runtime(path_like, user_root=user_root)
    return Path(target).read_text(encoding=encoding)


def save_json_data(
    path_like: str | Path,
    payload,
    *,
    encoding: str = "utf-8-sig",
    indent: int = 2,
    ensure_ascii: bool = False,
    trailing_newline: bool = False,
    user_root: Path | None = None,
) -> Path:
    """Store Python 경로 가상화를 고려해 JSON 파일을 저장한다."""
    target = _normalize_path(path_like)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding=encoding) as handle:
        json.dump(payload, handle, indent=indent, ensure_ascii=ensure_ascii)
        if trailing_newline:
            handle.write("\n")
    sync_runtime_store_python_file_to_visible(target, user_root=user_root)
    return target


def write_text_data(
    path_like: str | Path,
    text: str,
    *,
    encoding: str = "utf-8-sig",
    user_root: Path | None = None,
) -> Path:
    """Store Python 경로 가상화를 고려해 텍스트 파일을 저장한다."""
    target = _normalize_path(path_like)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(text), encoding=encoding)
    sync_runtime_store_python_file_to_visible(target, user_root=user_root)
    return target


def get_bundle_prompts_defaults_dir() -> Path:
    """번들 내부 기본 프롬프트 디렉터리를 반환한다."""
    return get_bundle_root() / "prompts" / "defaults"


def resolve_user_storage_path(
    path_like: str | Path | None,
    *,
    user_root: Path | None = None,
) -> Path:
    """
    쓰기 대상 파일 경로를 사용자 데이터 루트 기준 절대 경로로 해석한다.
    """
    if path_like is None:
        raise ValueError("path_like cannot be None")

    path_obj = _normalize_path(path_like)
    if path_obj.is_absolute():
        return path_obj.resolve()

    resolved_user_root = Path(user_root) if user_root is not None else get_user_data_dir()
    return (resolved_user_root / path_obj).resolve()


def resolve_runtime_resource_path(
    path_like: str | Path | None,
    *,
    user_root: Path | None = None,
    bundle_root: Path | None = None,
) -> Path:
    """
    읽기 전용 런타임 리소스를 사용자 데이터 -> 번들 순서로 해석한다.
    """
    if path_like is None:
        raise ValueError("path_like cannot be None")

    path_obj = _normalize_path(path_like)
    if path_obj.is_absolute():
        return path_obj.resolve()

    resolved_user_root = Path(user_root) if user_root is not None else get_user_data_dir()
    resolved_bundle_root = Path(bundle_root) if bundle_root is not None else get_bundle_root()

    candidates = [
        resolved_user_root / path_obj,
        resolved_bundle_root / path_obj,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def relativize_for_storage(
    path_like: str | Path | None,
    *,
    user_root: Path | None = None,
    bundle_root: Path | None = None,
) -> str:
    """
    저장 시 알려진 루트 아래 경로는 상대 경로로 축약한다.
    외부 파일은 절대 경로를 유지한다.
    """
    raw_path = str(path_like or "").strip()
    if not raw_path:
        return ""

    path_obj = _normalize_path(raw_path)
    if not path_obj.is_absolute():
        return raw_path.replace("\\", "/")

    resolved_path = path_obj.resolve()
    roots = [
        Path(user_root) if user_root is not None else get_user_data_dir(),
        Path(bundle_root) if bundle_root is not None else get_bundle_root(),
    ]
    for root in roots:
        try:
            relative = resolved_path.relative_to(root.resolve())
            return str(relative).replace("\\", "/")
        except Exception:
            continue
    return str(resolved_path).replace("\\", "/")
