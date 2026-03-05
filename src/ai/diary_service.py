"""
/diary 명령 파싱 및 마크다운 파일 저장 서비스
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import subprocess


_DIARY_COMMAND_PATTERN = re.compile(r"^/diary(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_OBS_COMMAND_PATTERN = re.compile(r"^/obs(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_NOTE_COMMAND_PATTERN = re.compile(r"^/note(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_SAFE_SLUG_PATTERN = re.compile(r"[^0-9A-Za-z가-힣_-]+")


@dataclass(frozen=True)
class DiaryWriteResult:
    """일기/문서 저장 결과"""

    relative_path: str
    absolute_path: str
    content: str
    title_slug: str
    storage_target: str = "local_only"
    obsidian_cli_invoked: bool = False
    obsidian_cli_error: str = ""
    obsidian_output_path: str = ""


class DiaryService:
    """/diary 명령 처리 및 파일 저장을 담당한다."""

    def __init__(self, base_dir: str | Path = "diary", settings=None):
        self.base_dir = Path(base_dir)
        self.settings = settings

    @staticmethod
    def parse_diary_command(message: str) -> tuple[bool, str]:
        """/diary 명령 여부와 본문을 반환한다."""
        text = (message or "").strip()
        match = _DIARY_COMMAND_PATTERN.match(text)
        if not match:
            return False, ""
        body = (match.group(1) or "").strip()
        return True, body

    @staticmethod
    def parse_obs_command(message: str) -> tuple[bool, str]:
        """/obs 명령 여부와 본문을 반환한다."""
        text = (message or "").strip()
        match = _OBS_COMMAND_PATTERN.match(text)
        if not match:
            return False, ""
        body = (match.group(1) or "").strip()
        return True, body

    @staticmethod
    def parse_note_command(message: str) -> tuple[bool, str]:
        """/note 명령 여부와 본문을 반환한다."""
        text = (message or "").strip()
        match = _NOTE_COMMAND_PATTERN.match(text)
        if not match:
            return False, ""
        body = (match.group(1) or "").strip()
        return True, body

    @staticmethod
    def build_slug(source_text: str, max_length: int = 40) -> str:
        """파일명에 사용할 안전한 slug를 생성한다."""
        raw = (source_text or "").strip()
        if not raw:
            return "diary"

        first_line = raw.splitlines()[0].strip()
        cleaned = _SAFE_SLUG_PATTERN.sub("-", first_line)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-_")
        if not cleaned:
            cleaned = "diary"
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip("-_")
        return cleaned or "diary"

    def make_file_name(self, request_text: str) -> tuple[str, str]:
        """타임스탬프+slug 형식 파일명을 생성한다."""
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = self.build_slug(request_text)
        return f"{now}-{slug}.md", slug

    def save_markdown(self, request_text: str, markdown_text: str) -> DiaryWriteResult:
        """로컬 diary 폴더에 마크다운을 저장한다."""
        return self._save_local_markdown(request_text=request_text, markdown_text=markdown_text, storage_target="local_only")

    def save_markdown_via_priority(self, request_text: str, markdown_text: str) -> DiaryWriteResult:
        """
        우선순위 정책으로 저장한다.
        1) obsidian CLI 우선 (설정 활성 시)
        2) 실패 시 로컬 diary 폴더 폴백
        """
        primary_cli = True
        keep_local_copy = False
        cli_enabled = False
        cli_command = ""
        if self.settings:
            primary_cli = bool(self.settings.get("obsidian_cli_primary_for_diary", True))
            keep_local_copy = bool(self.settings.get("diary_keep_local_copy_on_cli_success", False))
            cli_enabled = bool(self.settings.get("obsidian_cli_enabled", False))
            cli_command = str(self.settings.get("obsidian_cli_command", "") or "").strip()

        if not primary_cli:
            return self._save_local_markdown(request_text=request_text, markdown_text=markdown_text, storage_target="local_only")
        if not cli_enabled or not cli_command:
            return self._save_local_markdown(request_text=request_text, markdown_text=markdown_text, storage_target="local_only")

        cli_result = self._try_obsidian_cli_write(request_text=request_text, markdown_text=markdown_text)
        if cli_result is not None:
            if keep_local_copy:
                local_result = self._save_local_markdown(
                    request_text=request_text,
                    markdown_text=markdown_text,
                    storage_target="obsidian",
                )
                return DiaryWriteResult(
                    relative_path=local_result.relative_path,
                    absolute_path=local_result.absolute_path,
                    content=local_result.content,
                    title_slug=local_result.title_slug,
                    storage_target="obsidian",
                    obsidian_cli_invoked=True,
                    obsidian_cli_error=cli_result.obsidian_cli_error,
                    obsidian_output_path=cli_result.obsidian_output_path,
                )
            return cli_result

        local_fallback = self._save_local_markdown(
            request_text=request_text,
            markdown_text=markdown_text,
            storage_target="local_fallback",
        )
        return DiaryWriteResult(
            relative_path=local_fallback.relative_path,
            absolute_path=local_fallback.absolute_path,
            content=local_fallback.content,
            title_slug=local_fallback.title_slug,
            storage_target="local_fallback",
            obsidian_cli_invoked=True,
            obsidian_cli_error=self._last_cli_error,
            obsidian_output_path=self._last_obsidian_output_path,
        )

    def _save_local_markdown(self, request_text: str, markdown_text: str, storage_target: str) -> DiaryWriteResult:
        """로컬 diary 폴더에 UTF-8 BOM으로 저장한다."""
        file_name, slug = self.make_file_name(request_text)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        file_path = self.base_dir / file_name
        content = (markdown_text or "").strip()
        file_path.write_text(content + "\n", encoding="utf-8-sig")

        return DiaryWriteResult(
            relative_path=file_path.as_posix(),
            absolute_path=str(file_path.resolve()),
            content=content,
            title_slug=slug,
            storage_target=storage_target,
        )

    def _try_obsidian_cli_write(self, request_text: str, markdown_text: str) -> DiaryWriteResult | None:
        """
        Obsidian CLI로 우선 저장을 시도한다.
        성공 시 DiaryWriteResult를 반환하고, 실패/비활성 시 None을 반환한다.
        """
        self._last_cli_error = ""
        self._last_obsidian_output_path = ""

        if not self.settings:
            return None

        enabled = bool(self.settings.get("obsidian_cli_enabled", False))
        command_template = str(self.settings.get("obsidian_cli_command", "") or "").strip()
        if not enabled or not command_template:
            return None

        timeout_sec = int(self.settings.get("obsidian_cli_timeout_sec", 20) or 20)
        timeout_sec = max(1, min(timeout_sec, 120))
        vault_path = ""

        file_name, slug = self.make_file_name(request_text)
        obsidian_relative = f"ENE Diary/{file_name}"
        obsidian_path = obsidian_relative
        content = (markdown_text or "").strip()

        try:
            command = command_template.format(
                vault_path=vault_path,
                file_path=str(obsidian_path),
                relative_path=obsidian_relative,
                file_name=file_name,
                file_stem=Path(file_name).stem,
                title_slug=slug,
                content=content,
            )
        except Exception as e:
            self._last_cli_error = f"명령 템플릿 포맷 실패: {e}"
            return None

        try:
            completed = subprocess.run(
                command,
                shell=True,
                text=True,
                capture_output=True,
                timeout=timeout_sec,
            )
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                self._last_cli_error = stderr or f"Obsidian CLI 종료 코드: {completed.returncode}"
                self._last_obsidian_output_path = obsidian_path
                return None

            self._last_obsidian_output_path = obsidian_path
            return DiaryWriteResult(
                relative_path=obsidian_relative.replace("\\", "/"),
                absolute_path=obsidian_path,
                content=content,
                title_slug=slug,
                storage_target="obsidian",
                obsidian_cli_invoked=True,
                obsidian_cli_error="",
                obsidian_output_path=obsidian_path,
            )
        except Exception as e:
            self._last_cli_error = str(e)
            self._last_obsidian_output_path = obsidian_path
            return None
