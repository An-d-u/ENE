"""
ENE 런타임 경로 유틸리티.

- 번들 내부 리소스 경로
- 사용자 데이터 저장 경로
- 상대 경로 저장/해석 규칙
을 한 곳에서 관리한다.
"""
from __future__ import annotations

import os
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
