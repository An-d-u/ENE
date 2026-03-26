"""
Obsidian CLI 기반 연동 매니저
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import PurePosixPath


@dataclass
class ObsidianOpResult:
    ok: bool
    message: str
    path: str = ""


class ObsidianManager:
    """Obsidian CLI만 사용해 트리 조회/파일 조작을 수행한다."""

    def __init__(self, settings, obs_settings):
        self.settings = settings
        self.obs_settings = obs_settings
        self._cli_lock = threading.RLock()
        self._tree_connection_ok = False

    def _cli_bin(self) -> str:
        if self.settings is None:
            return "obsidian"
        return str(self.settings.get("obsidian_cli_bin", "obsidian") or "obsidian").strip() or "obsidian"

    def _timeout_sec(self) -> int:
        if self.settings is None:
            return 20
        value = int(self.settings.get("obsidian_cli_timeout_sec", 20) or 20)
        return max(1, min(value, 120))

    def _retry_count(self) -> int:
        if self.settings is None:
            return 2
        value = int(self.settings.get("obsidian_cli_retry_count", 2) or 2)
        return max(0, min(value, 5))

    def _retry_delay_sec(self) -> float:
        if self.settings is None:
            return 0.5
        value_ms = int(self.settings.get("obsidian_cli_retry_delay_ms", 500) or 500)
        return max(0.1, min(value_ms, 5000)) / 1000.0

    def _checked_max_chars_per_file(self) -> int:
        if self.settings is None:
            return 3000
        value = int(self.settings.get("obsidian_checked_max_chars_per_file", 3000) or 3000)
        return max(100, min(value, 200000))

    def _checked_total_max_chars(self) -> int:
        if self.settings is None:
            return 12000
        value = int(self.settings.get("obsidian_checked_total_max_chars", 12000) or 12000)
        return max(100, min(value, 1000000))

    def _resolve_cli_candidates(self) -> list[str]:
        """
        현재 실행 환경에서 Obsidian CLI 후보 실행 경로를 생성한다.
        - 설정값(obsidian_cli_bin)을 1순위로 사용
        - Windows에서 .cmd/.exe 확장을 자동 보강
        - PATH 해상도(shutil.which) 결과를 추가
        """
        raw_bin = self._cli_bin()
        seeds: list[str] = [raw_bin]

        if os.name == "nt":
            lowered = raw_bin.lower()
            if not lowered.endswith(".cmd"):
                seeds.append(f"{raw_bin}.cmd")
            if not lowered.endswith(".exe"):
                seeds.append(f"{raw_bin}.exe")

        candidates: list[str] = []
        seen = set()
        for seed in seeds:
            if not seed or seed in seen:
                continue
            seen.add(seed)
            candidates.append(seed)

            resolved = shutil.which(seed)
            if resolved and resolved not in seen:
                seen.add(resolved)
                candidates.append(resolved)

        return candidates or [raw_bin]

    def _split_cli_bin(self) -> list[str]:
        raw = self._cli_bin()
        try:
            parts = [p for p in shlex.split(raw, posix=False) if p]
        except Exception:
            parts = [raw]
        return parts or ["obsidian"]

    @staticmethod
    def _is_mutating_command(args: list[str]) -> bool:
        if not args:
            return False
        cmd = str(args[0]).strip().lower()
        return cmd in {"append", "update", "write"}

    @staticmethod
    def _looks_transient_error(stderr_text: str) -> bool:
        text = (stderr_text or "").lower()
        transient_hints = (
            "timed out",
            "timeout",
            "temporar",
            "busy",
            "try again",
            "connection",
            "econn",
            "resource",
            "잠시",
            "일시",
        )
        return any(hint in text for hint in transient_hints)

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        if isinstance(exc, subprocess.TimeoutExpired):
            return True
        if isinstance(exc, OSError):
            return True
        text = str(exc).lower()
        if "timed out" in text or "timeout" in text:
            return True
        # 실행 파일 미탐색은 재시도해도 성공 가능성이 낮다.
        if "실행 파일을 찾지 못했습니다" in text:
            return False
        return False

    def _run_cli_once(self, args: list[str]) -> subprocess.CompletedProcess:
        timeout = self._timeout_sec()
        last_error: Exception | None = None
        base_parts = self._split_cli_bin()

        # 1차: shell=False로 직접 실행 (가장 안전/예측 가능)
        if len(base_parts) > 1:
            try:
                return subprocess.run(
                    base_parts + list(args),
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    shell=False,
                )
            except FileNotFoundError as e:
                last_error = e
        else:
            for bin_path in self._resolve_cli_candidates():
                cmd = [bin_path] + list(args)
                try:
                    return subprocess.run(
                        cmd,
                        text=True,
                        capture_output=True,
                        timeout=timeout,
                        shell=False,
                    )
                except FileNotFoundError as e:
                    last_error = e
                    continue

        # 2차: Windows 환경에서 PowerShell alias/function 환경 폴백
        # shell=True는 GUI 앱 실행으로 튈 수 있어 사용하지 않는다.
        if os.name == "nt":
            try:
                ps_cmd = self._build_powershell_command(args)
                return subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    shell=False,
                )
            except Exception as e:
                last_error = e

        details = f"obsidian_cli_bin='{self._cli_bin()}', os='{os.name}', python='{sys.executable}'"
        if last_error:
            raise RuntimeError(f"Obsidian CLI 실행 파일을 찾지 못했습니다. ({details}) 원인: {last_error}") from last_error
        raise RuntimeError(f"Obsidian CLI 실행에 실패했습니다. ({details})")

    def _run_cli(self, args: list[str], allow_retry: bool = True) -> subprocess.CompletedProcess:
        """
        Obsidian CLI 실행 진입점.
        - 동시 실행 충돌을 줄이기 위해 전역 락 적용
        - 비파괴 명령에 한해 재시도(backoff) 적용
        - 상세 로그 출력
        """
        max_attempts = 1 + self._retry_count() if allow_retry else 1
        retryable = not self._is_mutating_command(args)
        delay = self._retry_delay_sec()
        last_exception: Exception | None = None
        last_completed: subprocess.CompletedProcess | None = None

        with self._cli_lock:
            for attempt in range(1, max_attempts + 1):
                try:
                    completed = self._run_cli_once(args)
                    last_completed = completed
                    stderr = (completed.stderr or "").strip()
                    if completed.returncode == 0:
                        if attempt > 1:
                            print(f"[ObsidianCLI] 복구 성공 (attempt {attempt}/{max_attempts}) args={args}")
                        return completed

                    print(
                        f"[ObsidianCLI] 실패 rc={completed.returncode} "
                        f"(attempt {attempt}/{max_attempts}) args={args} stderr={stderr[:240]}"
                    )
                    should_retry = (
                        retryable
                        and attempt < max_attempts
                        and (self._looks_transient_error(stderr) or not stderr)
                    )
                    if should_retry:
                        time.sleep(delay * (2 ** (attempt - 1)))
                        continue
                    return completed
                except Exception as e:
                    last_exception = e
                    print(f"[ObsidianCLI] 예외 (attempt {attempt}/{max_attempts}) args={args}: {e}")
                    should_retry = retryable and attempt < max_attempts and self._is_retryable_exception(e)
                    if should_retry:
                        time.sleep(delay * (2 ** (attempt - 1)))
                        continue
                    raise

        if last_exception:
            raise last_exception
        if last_completed is not None:
            return last_completed
        raise RuntimeError("Obsidian CLI 실행 결과를 얻지 못했습니다.")

    def execute_cli_args(self, args: list[str], allow_retry: bool = True) -> subprocess.CompletedProcess:
        """외부 오케스트레이터에서 사용할 CLI 실행 진입점."""
        return self._run_cli(list(args or []), allow_retry=allow_retry)

    def is_connected(self) -> bool:
        """최근 트리 조회 기준으로 Obsidian CLI 연결 여부를 반환한다."""
        return bool(self._tree_connection_ok)

    @staticmethod
    def _looks_like_not_found(stderr_text: str) -> bool:
        text = (stderr_text or "").lower()
        return (
            "not recognized as an internal or external command" in text
            or "is not recognized" in text
            or "command not found" in text
        )

    def _build_powershell_command(self, args: list[str]) -> str:
        # PowerShell 인자 이스케이프: ' -> ''
        def ps_quote(v: str) -> str:
            return "'" + str(v).replace("'", "''") + "'"

        parts = [ps_quote(v) for v in [*self._split_cli_bin(), *list(args)]]
        return "& " + " ".join(parts)

    @staticmethod
    def _normalize_rel(path: str) -> str:
        raw = str(path or "").strip().replace("\\", "/")
        while raw.startswith("./"):
            raw = raw[2:]
        return raw.lstrip("/")

    @staticmethod
    def _parse_files_output(output: str) -> list[str]:
        """`obsidian files` 출력에서 파일 경로를 추출한다."""
        lines = []
        for raw in (output or "").splitlines():
            line = raw.strip()
            if not line:
                continue

            # 트리 출력의 접두 기호 제거 (예: |--, ├──, - )
            line = re.sub(r"^[\|`\-├└─\s]+", "", line).strip()
            line = line.replace("\\", "/")
            if not line:
                continue

            # 디렉터리 라인 제외
            if line.endswith("/"):
                continue

            # md 파일 우선
            if ".md" in line.lower():
                idx = line.lower().find(".md")
                line = line[: idx + 3]

            if "/" not in line and "." not in line:
                continue

            rel = ObsidianManager._normalize_rel(line)
            if rel:
                lines.append(rel)

        # 순서 보존 중복 제거
        seen = set()
        uniq = []
        for p in lines:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return uniq

    @staticmethod
    def _build_tree_from_paths(paths: list[str], max_depth: int = 5, max_nodes: int = 1500) -> list[dict]:
        """path 리스트를 트리 노드 구조로 변환한다."""
        root: dict = {}

        for rel in paths:
            parts = [p for p in PurePosixPath(rel).parts if p]
            if not parts:
                continue
            node = root
            for i, part in enumerate(parts):
                is_file = (i == len(parts) - 1)
                if part not in node:
                    node[part] = {"__children__": {}, "__file__": is_file}
                if is_file:
                    node[part]["__file__"] = True
                node = node[part]["__children__"]

        counter = {"n": 0}

        def walk(tree: dict, prefix: str = "", depth: int = 0) -> list[dict]:
            if depth > max_depth:
                return []
            result = []
            keys = sorted(tree.keys(), key=lambda k: (tree[k].get("__file__", False), k.lower()))
            for key in keys:
                if counter["n"] >= max_nodes:
                    break
                item = tree[key]
                path = f"{prefix}/{key}".lstrip("/")
                children = item.get("__children__", {})
                is_file = bool(item.get("__file__", False)) and not children

                if is_file:
                    result.append({"type": "file", "name": key, "path": path})
                else:
                    result.append({
                        "type": "dir",
                        "name": key,
                        "path": path,
                        "children": walk(children, path, depth + 1),
                    })
                counter["n"] += 1
            return result

        return walk(root)

    def build_tree(self, max_depth: int = 5, max_nodes: int = 1500, allow_retry: bool = True) -> dict:
        try:
            completed = self._run_cli(["files"], allow_retry=allow_retry)
        except Exception as e:
            self._tree_connection_ok = False
            return {"ok": False, "error": f"Obsidian CLI 실행 실패: {e}", "nodes": []}

        if completed.returncode != 0:
            self._tree_connection_ok = False
            err = (completed.stderr or "").strip() or f"Obsidian CLI 종료 코드: {completed.returncode}"
            return {"ok": False, "error": err, "nodes": []}

        paths = self._parse_files_output(completed.stdout)
        nodes = self._build_tree_from_paths(paths, max_depth=max_depth, max_nodes=max_nodes)
        self._tree_connection_ok = True
        return {
            "ok": True,
            "cli": self._cli_bin(),
            "nodes": nodes,
            "checked_files": self.obs_settings.get_checked_files(),
        }

    def get_tree_json(self, allow_retry: bool = True) -> str:
        return json.dumps(self.build_tree(allow_retry=allow_retry), ensure_ascii=False)

    def get_tree_lines(self, max_lines: int = 120, allow_retry: bool = True) -> list[str]:
        tree = self.build_tree(allow_retry=allow_retry)
        if not tree.get("ok"):
            return [f"- 트리 조회 실패: {tree.get('error', 'unknown')}"]

        lines: list[str] = []

        def emit(nodes: list[dict], prefix: str = ""):
            for node in nodes:
                if len(lines) >= max_lines:
                    return
                if node.get("type") == "dir":
                    lines.append(f"{prefix}[DIR] {node.get('path')}")
                    emit(node.get("children", []), prefix + "  ")
                else:
                    lines.append(f"{prefix}[FILE] {node.get('path')}")

        emit(tree.get("nodes", []))
        return lines

    def read_file(self, rel_path: str, allow_retry: bool = True) -> str:
        rel = self._normalize_rel(rel_path)
        if not rel:
            raise ValueError("파일 경로가 비어 있습니다.")

        completed = self._run_cli(["read", rel], allow_retry=allow_retry)
        if completed.returncode != 0:
            self._tree_connection_ok = False
            err = (completed.stderr or "").strip() or "파일 읽기에 실패했습니다."
            raise RuntimeError(err)
        return completed.stdout or ""

    def append_file(self, rel_path: str, content: str, create_if_missing: bool = True) -> ObsidianOpResult:
        rel = self._normalize_rel(rel_path)
        if not rel:
            return ObsidianOpResult(False, "파일 경로가 비어 있습니다.")

        args = ["append", rel, str(content or "")]
        if create_if_missing:
            args.append("--create")

        try:
            completed = self._run_cli(args)
            if completed.returncode != 0:
                err = (completed.stderr or "").strip() or "파일 추가에 실패했습니다."
                return ObsidianOpResult(False, err, path=rel)
            return ObsidianOpResult(True, "파일에 내용을 추가했습니다.", path=rel)
        except Exception as e:
            return ObsidianOpResult(False, str(e), path=rel)

    def replace_in_file(self, rel_path: str, before: str, after: str) -> ObsidianOpResult:
        rel = self._normalize_rel(rel_path)
        if not rel:
            return ObsidianOpResult(False, "파일 경로가 비어 있습니다.")

        try:
            old_text = self.read_file(rel)
        except Exception as e:
            return ObsidianOpResult(False, f"파일 읽기 실패: {e}", path=rel)

        if before not in old_text:
            return ObsidianOpResult(False, "대상 문자열을 찾지 못했습니다.", path=rel)

        new_text = old_text.replace(before, after, 1)

        # CLI write가 없을 수 있으므로 update를 먼저 시도하고 실패 시 write 폴백
        for args in (["update", rel, new_text], ["write", rel, new_text]):
            try:
                completed = self._run_cli(args)
                if completed.returncode == 0:
                    return ObsidianOpResult(True, "파일 내용을 교체했습니다.", path=rel)
            except Exception:
                continue

        return ObsidianOpResult(False, "파일 쓰기 명령(update/write) 실행에 실패했습니다.", path=rel)

    def get_checked_file_contents(
        self,
        max_files: int = 8,
        max_chars_per_file: int | None = None,
        total_max_chars: int | None = None,
        allow_retry: bool = True,
    ) -> list[tuple[str, str]]:
        if max_chars_per_file is None:
            max_chars_per_file = self._checked_max_chars_per_file()
        if total_max_chars is None:
            total_max_chars = self._checked_total_max_chars()

        checked = self.obs_settings.get_checked_files()
        result: list[tuple[str, str]] = []
        total = 0
        for rel in checked[:max_files]:
            try:
                text = self.read_file(rel, allow_retry=allow_retry)
            except Exception:
                continue
            sliced = text[:max_chars_per_file]
            if total + len(sliced) > total_max_chars:
                remain = max(0, total_max_chars - total)
                sliced = sliced[:remain]
            if not sliced:
                break
            result.append((rel, sliced))
            total += len(sliced)
            if total >= total_max_chars:
                break
        return result
