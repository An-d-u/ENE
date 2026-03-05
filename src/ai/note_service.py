"""
/note 명령 오케스트레이션 보조 서비스
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class NoteCommand:
    args: list[str]
    reason: str = ""


@dataclass(frozen=True)
class NotePlan:
    summary: str
    commands: list[NoteCommand]
    stop_on_error: bool = True


@dataclass(frozen=True)
class NoteCommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    ok: bool


class NoteService:
    """LLM 계획 기반 /note 실행을 담당한다."""
    _TOKEN_PATTERN = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')

    # https://aiandgamedev.com/ai/obsidian-cli-guide/ 기반으로 정리한 허용 명령 집합
    ALLOWED_COMMANDS = {
        "help",
        "version",
        "reload",
        "restart",
        "files",
        "file",
        "folders",
        "folder",
        "open",
        "create",
        "read",
        "append",
        "prepend",
        "move",
        "rename",
        "delete",
        "daily",
        "daily:path",
        "daily:read",
        "daily:append",
        "daily:prepend",
        "search",
        "search:context",
        "search:open",
        "backlinks",
        "links",
        "unresolved",
        "orphans",
        "deadends",
        "tags",
        "tag",
        "aliases",
        "properties",
        "property:set",
        "property:read",
        "property:remove",
        "tasks",
        "task",
        "templates",
        "template:read",
        "template:insert",
        "plugins",
        "plugins:enabled",
        "plugin:enable",
        "plugin:disable",
        "themes",
        "theme:set",
        "snippets",
        "snippet:enable",
        "snippet:disable",
        "vault",
        "vaults",
        "workspace",
        "workspace:save",
        "workspace:load",
        "tabs",
        "tab:open",
        "recents",
        "sync:status",
        "sync:start",
        "sync:stop",
        "history",
        "diff",
        # 기존 코드와의 호환
        "update",
        "write",
    }
    PATH_REQUIRED_COMMANDS = {
        "file",
        "open",
        "create",
        "read",
        "append",
        "prepend",
        "move",
        "rename",
        "delete",
        "backlinks",
        "links",
        "aliases",
        "properties",
        "property:set",
        "property:read",
        "property:remove",
        "tasks",
        "task",
        "template:insert",
        "tab:open",
        "history",
        "diff",
        "update",
        "write",
    }
    CONTENT_WRITE_COMMANDS = {"create", "write", "update", "append", "prepend"}

    def __init__(self, logs_dir: str | Path = "note_runs"):
        self.logs_dir = Path(logs_dir)

    def load_cli_reference_text(self) -> str:
        """옵션: Obsidian CLI 명령 레퍼런스 md를 로드한다."""
        candidates = [
            Path("docs/obsidian_cli_commands.md"),
            Path("obsidian_cli_commands.md"),
        ]
        for path in candidates:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8-sig").strip()
                except Exception:
                    try:
                        return path.read_text(encoding="utf-8").strip()
                    except Exception:
                        continue
        return ""

    def build_plan_prompt(self, user_instruction: str, obs_tree_lines: list[str], checked_files: list[tuple[str, str]]) -> str:
        tree_block = "\n".join(f"- {line}" for line in (obs_tree_lines or []))
        checked_block_lines: list[str] = []
        for rel, content in checked_files or []:
            checked_block_lines.append(f"[파일:{rel}]")
            checked_block_lines.append(content)
        checked_block = "\n".join(checked_block_lines)

        cli_ref = self.load_cli_reference_text()
        ref_block = f"\n[Obsidian CLI 레퍼런스]\n{cli_ref}\n" if cli_ref else ""

        return (
            "너의 작업은 /note 요청을 Obsidian CLI 실행 계획(Markdown)으로 만드는 것이다.\n"
            "반드시 아래 형식으로만 출력해라. 코드블록/부가 설명 금지.\n"
            "형식:\n"
            "# NOTE PLAN\n"
            "- summary: 한 줄 요약\n"
            "- stop_on_error: true\n"
            "## COMMANDS\n"
            "1. obsidian <command> <arg...>\n"
            "2. obsidian <command> <arg...>\n"
            "## REASONS\n"
            "1. 첫 명령 이유\n"
            "2. 둘째 명령 이유\n"
            "규칙:\n"
            "- 허용 명령만 사용.\n"
            "- 위험 토큰/외부 도구/파이프/리다이렉션 금지.\n"
            "- 경로는 Vault 상대경로만 사용.\n"
            "- 최소 명령 수로 정확하게 수행.\n"
            f"{ref_block}\n"
            "[Obsidian 트리 구조]\n"
            f"{tree_block}\n\n"
            "[체크된 파일 본문]\n"
            f"{checked_block}\n\n"
            "[사용자 요청]\n"
            f"{user_instruction}\n"
        ).strip()

    def _extract_line_value(self, text: str, key: str, default: str = "") -> str:
        pattern = re.compile(rf"^(?:[-*]\s*)?{re.escape(key)}\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
        match = pattern.search(text or "")
        if not match:
            return default
        return (match.group(1) or "").strip()

    def _parse_command_lines(self, text: str) -> list[str]:
        lines = (text or "").splitlines()
        commands: list[str] = []
        in_commands = False
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.lower() == "## commands":
                in_commands = True
                continue
            if line.startswith("## ") and in_commands:
                break
            if not in_commands:
                continue
            numeric = re.match(r"^\d+\.\s*(.+)$", line)
            bullet = re.match(r"^[-*]\s*(.+)$", line)
            if numeric:
                commands.append(numeric.group(1).strip())
                continue
            if bullet:
                commands.append(bullet.group(1).strip())
                continue
            if line.lower().startswith("obsidian "):
                commands.append(line)
        return commands

    def _parse_reason_lines(self, text: str) -> list[str]:
        lines = (text or "").splitlines()
        reasons: list[str] = []
        in_reasons = False
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.lower() == "## reasons":
                in_reasons = True
                continue
            if line.startswith("## ") and in_reasons:
                break
            if not in_reasons:
                continue
            match = re.match(r"^\d+\.\s*(.+)$", line)
            if match:
                reasons.append(match.group(1).strip())
        return reasons

    def _tokenize_command(self, command_line: str) -> list[str]:
        raw = (command_line or "").strip()
        if not raw:
            return []
        tokens: list[str] = []
        for match in self._TOKEN_PATTERN.finditer(raw):
            token = next((group for group in match.groups() if group is not None), None)
            if token is None:
                continue
            tokens.append(token)
        if tokens and tokens[0].lower() == "obsidian":
            tokens = tokens[1:]
        return tokens

    @staticmethod
    def _strip_fenced_block(text: str) -> str:
        body = (text or "").strip()
        if not body.startswith("```"):
            return body
        body = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", body, flags=re.IGNORECASE)
        body = re.sub(r"\n?```$", "", body)
        return body.strip()

    def parse_plan(self, raw_text: str) -> NotePlan:
        body = self._strip_fenced_block(raw_text)
        if "# note plan" not in body.lower():
            raise ValueError("NOTE PLAN 형식을 찾지 못했습니다.")

        summary = self._extract_line_value(body, "summary", "요청 기반 실행")
        stop_raw = self._extract_line_value(body, "stop_on_error", "true").lower()
        stop_on_error = stop_raw not in {"false", "0", "no"}

        cmd_lines = self._parse_command_lines(body)
        reason_lines = self._parse_reason_lines(body)
        commands: list[NoteCommand] = []
        for idx, line in enumerate(cmd_lines[:8]):
            args = self._tokenize_command(line)
            if not args:
                continue
            reason = reason_lines[idx] if idx < len(reason_lines) else ""
            commands.append(NoteCommand(args=args, reason=reason))

        if not commands:
            raise ValueError("실행할 commands가 비어 있습니다.")
        return NotePlan(summary=summary, commands=commands, stop_on_error=stop_on_error)

    def _find_primary_path(self, args: list[str]) -> str:
        # 명령 본문에서 첫 path-like 토큰을 경로로 본다.
        for token in args[1:]:
            low = token.lower()
            if low.startswith(("path=", "file=", "target=")):
                return token.split("=", 1)[1].strip().strip('"').strip("'")
            if "/" in token or "\\" in token or low.endswith(".md"):
                return token.strip().strip('"').strip("'")
        return ""

    @staticmethod
    def _extract_named_value(args: list[str], key: str) -> str:
        prefix = f"{key.lower()}="
        for token in args[1:]:
            low = token.lower()
            if low.startswith(prefix):
                return token.split("=", 1)[1]
        return ""

    def _extract_content_value(self, args: list[str]) -> str:
        named = self._extract_named_value(args, "content")
        if named:
            return named
        head = str(args[0]).lower() if args else ""
        if head in {"write", "update", "append", "prepend"} and len(args) >= 3:
            return str(args[2])
        return ""

    @staticmethod
    def has_cli_error_output(stdout: str, stderr: str) -> bool:
        texts = [str(stderr or "").strip().lower(), str(stdout or "").strip().lower()]
        for text in texts:
            if not text:
                continue
            if text.startswith("error:"):
                return True
            if "no commands matching" in text:
                return True
            if "command \"" in text and "not found" in text:
                return True
            if "missing required parameter" in text:
                return True
        return False

    def _normalize_args_for_cli(self, args: list[str]) -> list[str]:
        if not args:
            return []
        head = str(args[0]).lower()
        raw_rest = list(args[1:])
        named_map: dict[str, str] = {}
        named_tokens: list[str] = []
        positional: list[str] = []

        for token in raw_rest:
            token_str = str(token)
            if "=" in token_str and not token_str.startswith("="):
                key, _ = token_str.split("=", 1)
                key_low = key.strip().lower()
                if key_low and key_low not in named_map:
                    named_map[key_low] = token_str
                    named_tokens.append(token_str)
                    continue
            positional.append(token_str)

        def pop_positional() -> str:
            if not positional:
                return ""
            return positional.pop(0)

        def ensure_named(key: str, value: str):
            key_low = key.lower()
            if key_low in named_map:
                return
            if value == "":
                return
            token = f"{key}={value}"
            named_map[key_low] = token
            named_tokens.append(token)

        if head in {"create", "file", "folder", "open", "read", "delete", "backlinks", "links", "aliases", "properties", "task", "history", "diff"}:
            ensure_named("path", pop_positional())
        elif head == "tab:open":
            ensure_named("file", pop_positional())
        elif head in {"append", "prepend"}:
            ensure_named("path", pop_positional())
            ensure_named("content", pop_positional())
        elif head in {"daily:append", "daily:prepend"}:
            ensure_named("content", pop_positional())
        elif head == "move":
            ensure_named("path", pop_positional())
            ensure_named("to", pop_positional())
        elif head == "rename":
            ensure_named("path", pop_positional())
            ensure_named("name", pop_positional())
        elif head in {"search", "search:context", "search:open"}:
            ensure_named("query", pop_positional())
        elif head == "property:set":
            ensure_named("path", pop_positional())
            ensure_named("name", pop_positional())
            ensure_named("value", pop_positional())
        elif head in {"property:read", "property:remove"}:
            ensure_named("path", pop_positional())
            ensure_named("name", pop_positional())
        elif head == "template:insert":
            ensure_named("name", pop_positional())

        return [str(args[0]), *named_tokens, *positional]

    def validate_plan(self, plan: NotePlan):
        for cmd in plan.commands:
            head = str(cmd.args[0]).lower()
            if head not in self.ALLOWED_COMMANDS:
                raise ValueError(f"허용되지 않은 명령: {head}")

            for token in cmd.args:
                if any(x in token for x in ("&&", "||", ";", "|", ">", "<", "`", "$(")):
                    raise ValueError(f"위험한 토큰이 포함된 명령: {token}")

            if head in self.PATH_REQUIRED_COMMANDS:
                rel = self._find_primary_path(cmd.args)
                if not rel:
                    raise ValueError(f"{head} 명령에 경로가 없습니다.")
                norm = rel.replace("\\", "/")
                if norm.startswith("/") or norm.startswith("\\") or ".." in norm:
                    raise ValueError(f"허용되지 않은 경로: {rel}")

            if head in {"write", "update", "append", "prepend"}:
                if not self._extract_content_value(cmd.args).strip():
                    raise ValueError(f"{head} 명령의 본문이 비어 있습니다.")

    @staticmethod
    def is_document_generation_request(user_instruction: str) -> bool:
        text = (user_instruction or "").strip().lower()
        if not text:
            return False
        hints = (
            "작성해줘",
            "써줘",
            "정리해줘",
            "문서",
            "초안",
            "자기소개",
            "일기",
            "계획서",
        )
        return any(h in text for h in hints)

    @staticmethod
    def extract_target_markdown_path(user_instruction: str) -> str:
        text = (user_instruction or "").strip()
        if not text:
            return ""
        m = re.search(r"([^\s\"']+\.md)", text, re.IGNORECASE)
        if not m:
            return ""
        rel = m.group(1).strip().replace("\\", "/")
        rel = rel.strip("/").strip()
        if not rel or ".." in rel:
            return ""
        return rel

    def has_content_writing_command(self, plan: NotePlan) -> bool:
        for cmd in plan.commands:
            head = str(cmd.args[0]).lower()
            if head not in self.CONTENT_WRITE_COMMANDS:
                continue
            if self._extract_content_value(cmd.args).strip():
                # write/update/append/prepend + path + non-empty text
                return True
        return False

    def has_successful_content_writing_result(self, plan: NotePlan, results: list[NoteCommandResult]) -> bool:
        for idx, result in enumerate(results):
            if idx >= len(plan.commands):
                break
            if not result.ok:
                continue
            cmd = plan.commands[idx]
            head = str(cmd.args[0]).lower()
            if head in self.CONTENT_WRITE_COMMANDS and self._extract_content_value(cmd.args).strip():
                return True
        return False

    def extract_target_markdown_path_from_plan(self, plan: NotePlan) -> str:
        for cmd in plan.commands:
            rel = self._find_primary_path(cmd.args)
            if not rel:
                continue
            norm = rel.strip().strip("'").strip('"').replace("\\", "/").strip("/")
            if not norm or ".." in norm:
                continue
            if norm.lower().endswith(".md"):
                return norm
        return ""

    @staticmethod
    def build_default_markdown(user_instruction: str, target_path: str = "") -> str:
        stem = Path(target_path).stem.strip() if target_path else ""
        title = stem or "노트"
        safe_title = re.sub(r"[_-]+", " ", title).strip() or "노트"
        body = (user_instruction or "").strip() or "요청 내용을 바탕으로 작성한 문서입니다."
        return f"# {safe_title}\n\n{body}\n"

    def execute_plan(self, obsidian_manager, plan: NotePlan) -> list[NoteCommandResult]:
        results: list[NoteCommandResult] = []
        for cmd in plan.commands:
            normalized_args = self._normalize_args_for_cli(cmd.args)
            completed = obsidian_manager.execute_cli_args(normalized_args)
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            ok = completed.returncode == 0 and not self.has_cli_error_output(stdout, stderr)
            result = NoteCommandResult(
                args=normalized_args,
                returncode=int(completed.returncode),
                stdout=stdout[:5000],
                stderr=stderr[:3000],
                ok=ok,
            )
            results.append(result)
            if (not result.ok) and plan.stop_on_error:
                break
        return results

    def build_report_context(self, user_instruction: str, plan: NotePlan, results: list[NoteCommandResult], planner_error: str = "") -> str:
        lines = [
            "아래 실행 정보를 바탕으로 /note 실행 결과를 사용자에게 보고하세요.",
            "[사용자 요청]",
            user_instruction,
        ]
        if planner_error:
            lines.extend([
                "[계획 오류]",
                planner_error,
            ])
        lines.extend([
            "[실행 계획 요약]",
            plan.summary,
            "[실행 명령]",
        ])
        for i, cmd in enumerate(plan.commands, start=1):
            lines.append(f"{i}. {' '.join(cmd.args)}")
            if cmd.reason:
                lines.append(f"   - 이유: {cmd.reason}")
        lines.append("[실행 결과]")
        for i, item in enumerate(results, start=1):
            lines.append(f"{i}. rc={item.returncode} ok={item.ok} cmd={' '.join(item.args)}")
            if item.stdout:
                lines.append(f"   stdout: {item.stdout}")
            if item.stderr:
                lines.append(f"   stderr: {item.stderr}")
        return "\n".join(lines)

    def save_run_log(self, user_instruction: str, plan: NotePlan, results: list[NoteCommandResult], plan_raw: str, planner_error: str = ""):
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.logs_dir / f"{ts}.json"
        payload = {
            "timestamp": ts,
            "user_instruction": user_instruction,
            "plan_raw": plan_raw,
            "planner_error": planner_error,
            "plan": {
                "summary": plan.summary,
                "stop_on_error": plan.stop_on_error,
                "commands": [{"args": c.args, "reason": c.reason} for c in plan.commands],
            },
            "results": [
                {
                    "args": r.args,
                    "returncode": r.returncode,
                    "ok": r.ok,
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                }
                for r in results
            ],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")
