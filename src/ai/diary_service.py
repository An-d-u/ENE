"""
/diary 명령 파싱 및 마크다운 파일 저장 서비스
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re


_DIARY_COMMAND_PATTERN = re.compile(r"^/diary(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_SAFE_SLUG_PATTERN = re.compile(r"[^0-9A-Za-z가-힣_-]+")


@dataclass(frozen=True)
class DiaryWriteResult:
    """일기/문서 저장 결과"""

    relative_path: str
    absolute_path: str
    content: str
    title_slug: str


class DiaryService:
    """/diary 명령 처리 및 파일 저장을 담당한다."""

    def __init__(self, base_dir: str | Path = "diary"):
        self.base_dir = Path(base_dir)

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
        """마크다운을 diary 폴더에 UTF-8 BOM으로 저장한다."""
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
        )