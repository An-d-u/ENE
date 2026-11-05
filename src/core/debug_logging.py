"""사용자가 켠 동안에만 생성 요청과 원본 오류를 로컬 파일에 기록한다."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
import re
import sys
import threading
import time
import traceback
from uuid import uuid4

from .app_paths import get_bundle_root


_lock = threading.RLock()
_enabled = False
_log_dir: Path | None = None
_generation = 0
_secrets: tuple[str, ...] = ()
_warned = False
_active_request = ContextVar("ene_debug_request", default=None)


def get_debug_log_dir() -> Path:
    """패키지 임시 해제 폴더 대신 실행 파일이 놓인 폴더를 사용한다."""
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else get_bundle_root()
    return root / "log"


def _warn() -> None:
    global _warned
    if not _warned:
        _warned = True
        try:
            print("[디버그] 로그를 기록하지 못했습니다. log 폴더의 쓰기 권한과 디스크 공간을 확인하세요.")
        except Exception:
            pass


def configure_debug_logging(settings, *, root: Path | None = None) -> None:
    """저장한 설정을 적용한다. 비활성화하면 진행 중 요청의 후속 기록도 멈춘다."""
    global _enabled, _log_dir, _generation, _secrets, _warned
    enabled = settings.get("debug_mode", False) is True
    directory = Path(root) / "log" if root is not None else get_debug_log_dir()
    secrets = []
    for key in ("llm_api_keys", "tts_api_keys", "embedding_api_keys", "web_search_api_keys",
                "custom_api_key_or_password", "gemini_api_key"):
        value = settings.get(key, {})
        values = value.values() if isinstance(value, dict) else (value,)
        secrets.extend(item.strip() for item in values if isinstance(item, str) and item.strip())
    with _lock:
        if _enabled != enabled or _log_dir != directory:
            _generation += 1
        _enabled, _log_dir = enabled, directory
        _secrets = tuple(sorted(set(secrets), key=len, reverse=True))
        _warned = False
        if enabled:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError:
                _warn()


def debug_logging_enabled() -> bool:
    return _enabled


def _clean(value):
    """텍스트 전문은 유지하고 인증 정보와 바이너리만 제외한다."""
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value:
            return "[바이너리 첨부 생략]"
        for secret in _secrets:
            value = value.replace(secret, "[인증 정보 삭제]")
        value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[인증 정보 삭제]", value)
        return re.sub(r"\bsk-[A-Za-z0-9_-]{16,}", "[인증 정보 삭제]", value)
    if isinstance(value, bytes):
        return {"binary_omitted": True, "byte_count": len(value)}
    if isinstance(value, Enum):
        return _clean(value.value)
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            name = str(key)
            if name.lower() in {"authorization", "api_key", "x-api-key", "password", "cookie"}:
                result[name] = "[인증 정보 삭제]"
            elif name in {"inline_data", "inlineData"} or (name == "data" and value.get("type") == "base64"):
                result[name] = "[바이너리 첨부 생략]"
            elif name == "images":
                result[name] = {"binary_omitted": True, "count": len(item) if isinstance(item, list) else None}
            else:
                result[name] = _clean(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _clean(dump(exclude_none=True))
    return {"type": type(value).__name__}


def _write(event: dict, generation: int) -> None:
    with _lock:
        if not _enabled or _generation != generation or _log_dir is None:
            return
        try:
            now = datetime.now().astimezone()
            line = json.dumps(_clean({"timestamp": now.isoformat(), **event}), ensure_ascii=False)
            with (_log_dir / f"debug-{now:%Y-%m-%d}.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except Exception:
            # 저장 실패가 대화 실패로 전파되거나 오류 원문을 콘솔에 노출하지 않게 한다.
            _warn()


class debug_request:
    """한 번의 실제 생성 호출을 시작/완료 이벤트로 연결한다."""

    def __init__(self, stage: str, provider: str, model: str | None, request, *, bind_context=True):
        self.metadata = {"stage": stage, "provider": provider, "model": model}
        self.request = request
        self.details = {}
        self.generation = None
        self.token = None
        self.bind_context = bind_context

    def __enter__(self):
        with _lock:
            if not _enabled:
                return self
            self.generation = _generation
        self.metadata["request_id"] = uuid4().hex
        try:
            payload = self.request() if callable(self.request) else self.request
            _write({**self.metadata, "event": "request", "request": payload}, self.generation)
        except Exception:
            _warn()
        self.started = time.perf_counter()
        if self.bind_context:
            self.token = _active_request.set(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.generation is None:
            return False
        elapsed = time.perf_counter() - self.started
        if self.token is not None:
            _active_request.reset(self.token)
        result = {**self.metadata, "event": "result", "status": "success",
                  "elapsed_seconds": round(elapsed, 6), **self.details}
        if exc is not None:
            result.update(status="cancelled" if isinstance(exc, (GeneratorExit, KeyboardInterrupt))
                          or exc_type.__name__ == "CancelledError" else "error",
                          error_type=exc_type.__name__)
            try:
                result["error_message"] = str(exc)
                result["traceback"] = "".join(traceback.format_exception(exc_type, exc, tb))
            except Exception:
                pass
        _write(result, self.generation)
        return False


def record_debug_error(*, error_body: str | None = None, status_code: int | None = None,
                       exception: BaseException | None = None) -> None:
    """화면 표시용 오류로 변환하기 전 원문을 현재 호출에 첨부한다."""
    operation = _active_request.get()
    if operation is None:
        return
    operation.details["status"] = "error"
    if error_body is not None:
        operation.details["error_body"] = error_body
    if status_code is not None:
        operation.details["status_code"] = status_code
    if exception is not None:
        try:
            operation.details["original_error_message"] = str(exception)
            operation.details["original_traceback"] = "".join(traceback.format_exception(exception))
        except Exception:
            pass
