"""원문 없는 검색 진단을 제한된 로컬 파일에 기록한다."""
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock

from PyQt6.QtCore import QLockFile

from src.core.app_paths import write_bytes_data_atomic


_WRITE_LOCK = Lock()
_FIELDS = ("fact_ids", "summary_ids", "raw_chunks", "candidates", "excluded", "calls",
           "usage_recorded", "experience_refs", "experience_chars", "timings")


def save_retrieval_trace(path, request_id, trace, *, max_rows=200, max_bytes=1024 * 1024):
    """쓰기 실패와 다른 프로세스 점유는 대화를 막지 않는다."""
    path = Path(path)
    lock = None
    try:
        row = {key: getattr(trace, key) for key in _FIELDS}
        row.update(request_id=str(request_id), recorded_at=datetime.now(timezone.utc).isoformat())
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        if max_rows < 1 or len(encoded) > max_bytes:
            return False
        with _WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(path.with_name(path.name + ".write.lock")))
            if not lock.tryLock(50):
                return False
            rows = []
            if path.exists():
                with path.open("rb") as stream:
                    size = path.stat().st_size
                    if size > max_bytes:
                        stream.seek(size - max_bytes)
                        stream.readline()
                    for line in stream:
                        try:
                            old = json.loads(line)
                            if isinstance(old, dict) and old.get("request_id") != row["request_id"]:
                                rows.append(line)
                        except (ValueError, UnicodeError):
                            continue
            rows = rows[-(max_rows - 1):] if max_rows > 1 else []
            rows.append(encoded)
            total = sum(len(line) for line in rows)
            while len(rows) > 1 and total > max_bytes:
                total -= len(rows.pop(0))
            write_bytes_data_atomic(path, b"".join(rows))
        return True
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if lock is not None and lock.isLocked():
            lock.unlock()
