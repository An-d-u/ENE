from src.ai.note_service import NoteService


def test_parse_markdown_plan():
    service = NoteService()
    raw = """
# NOTE PLAN
- summary: 테스트 요약
- stop_on_error: true
## COMMANDS
1. obsidian read "notes/a.md"
2. obsidian search "핵심 키워드"
## REASONS
1. 파일 내용을 확인
2. 관련 노트 탐색
"""
    plan = service.parse_plan(raw)
    assert plan.summary == "테스트 요약"
    assert plan.stop_on_error is True
    assert len(plan.commands) == 2
    assert plan.commands[0].args[0] == "read"
    assert plan.commands[0].args[1] == "notes/a.md"


def test_validate_plan_rejects_dangerous_token():
    service = NoteService()
    raw = """
# NOTE PLAN
- summary: 위험 테스트
- stop_on_error: true
## COMMANDS
1. obsidian read "notes/a.md; rm -rf /"
"""
    plan = service.parse_plan(raw)
    try:
        service.validate_plan(plan)
        assert False, "위험 토큰이 차단되어야 합니다."
    except ValueError as e:
        assert "위험한 토큰" in str(e)


def test_validate_plan_allows_extended_commands():
    service = NoteService()
    raw = """
# NOTE PLAN
- summary: 확장 명령 테스트
- stop_on_error: false
## COMMANDS
1. obsidian search:context "로드맵"
2. obsidian daily:append "오늘 작업 요약"
3. obsidian tags
"""
    plan = service.parse_plan(raw)
    service.validate_plan(plan)
    assert len(plan.commands) == 3


def test_detect_document_generation_request_and_target_path():
    service = NoteService()
    text = "에네의 자기소개를 ene_01.md라는 제목으로 작성해줘"
    assert service.is_document_generation_request(text) is True
    assert service.extract_target_markdown_path(text) == "ene_01.md"


def test_has_content_writing_command():
    service = NoteService()
    plan = service.parse_plan(
        """
# NOTE PLAN
- summary: 쓰기 명령 테스트
- stop_on_error: true
## COMMANDS
1. obsidian write "notes/a.md" "본문"
"""
    )
    assert service.has_content_writing_command(plan) is True


def test_has_content_writing_command_rejects_empty_content():
    service = NoteService()
    plan = service.parse_plan(
        """
# NOTE PLAN
- summary: 빈 본문 테스트
- stop_on_error: true
## COMMANDS
1. obsidian write "notes/a.md" ""
"""
    )
    assert service.has_content_writing_command(plan) is False


def test_extract_target_markdown_path_from_plan():
    service = NoteService()
    plan = service.parse_plan(
        """
# NOTE PLAN
- summary: 대상 추출
- stop_on_error: true
## COMMANDS
1. obsidian create "notes/ene_01.md"
2. obsidian read "notes/ene_01.md"
"""
    )
    assert service.extract_target_markdown_path_from_plan(plan) == "notes/ene_01.md"


def test_parse_plan_accepts_codefence_and_bullet_commands():
    service = NoteService()
    raw = """
```markdown
# NOTE PLAN
- summary: 유연 파싱
- stop_on_error: true
## COMMANDS
- obsidian read "notes/a.md"
- obsidian search "키워드"
```
"""
    plan = service.parse_plan(raw)
    assert len(plan.commands) == 2
    assert plan.commands[0].args[0] == "read"


def test_normalize_args_for_create_and_append():
    service = NoteService()
    create_args = service._normalize_args_for_cli(["create", "ene_01.md"])
    append_args = service._normalize_args_for_cli(["append", "ene_01.md", "본문"])
    assert create_args == ["create", "path=ene_01.md"]
    assert append_args == ["append", "path=ene_01.md", "content=본문"]


def test_cli_error_output_detection():
    service = NoteService()
    assert service.has_cli_error_output("Error: Missing required parameter: content=<text>", "") is True
    assert service.has_cli_error_output("", "No commands matching \"write\"") is True
    assert service.has_cli_error_output("Created: notes/a.md", "") is False


def test_execute_plan_treats_stdout_error_as_failure():
    service = NoteService()
    plan = service.parse_plan(
        """
# NOTE PLAN
- summary: stdout 오류 검출
- stop_on_error: true
## COMMANDS
1. obsidian append "a.md" "본문"
"""
    )

    class DummyCompleted:
        returncode = 0
        stdout = "Error: Missing required parameter: content=<text>"
        stderr = ""

    class DummyManager:
        def execute_cli_args(self, args):
            return DummyCompleted()

    results = service.execute_plan(DummyManager(), plan)
    assert len(results) == 1
    assert results[0].ok is False


def test_parse_plan_keeps_quoted_content_value_as_single_token():
    service = NoteService()
    raw = """
# NOTE PLAN
- summary: quoted content
- stop_on_error: true
## COMMANDS
1. obsidian create path="자소서.md" content="# 자기소개서\\n\\n- 성함: 양승완\\n- 전공: 컴퓨터과학"
"""
    plan = service.parse_plan(raw)
    assert len(plan.commands) == 1
    args = plan.commands[0].args
    assert args[0] == "create"
    assert args[1] == "path=자소서.md"
    assert args[2].startswith("content=# 자기소개서")


def test_build_plan_prompt_includes_recent_context_block():
    service = NoteService()
    prompt = service.build_plan_prompt(
        user_instruction="자기소개서 수정해줘",
        obs_tree_lines=[],
        checked_files=[],
        recent_context="[2026-03-07 00:10][사용자] 가쿠치카 보강해줘",
    )
    assert "[최근 대화 맥락]" in prompt
    assert "가쿠치카 보강해줘" in prompt


def test_build_plan_prompt_uses_selected_language_but_keeps_plan_contract():
    service = NoteService(ui_language="en")
    prompt = service.build_plan_prompt(
        user_instruction="Update launch checklist",
        obs_tree_lines=["launch.md"],
        checked_files=[],
    )

    assert "Your task is to turn the /note request into an Obsidian CLI execution plan" in prompt
    assert "# NOTE PLAN" in prompt
    assert "## COMMANDS" in prompt
    assert "obsidian <command> <arg...>" in prompt
    assert "[User Request]" in prompt


def test_build_generated_markdown_path_returns_md_file():
    service = NoteService()
    path = service.build_generated_markdown_path("오늘의 일기를 작성해줘")
    assert path.endswith(".md")
    assert "에네의 일기" in path


def test_build_generated_markdown_path_uses_human_readable_title():
    service = NoteService()
    path = service.build_generated_markdown_path("자소서에 필요한 양식이랑 내용을 생성해줘")
    assert path.endswith(".md")
    assert "자소서에 필요한 양식이랑 내용" in path
