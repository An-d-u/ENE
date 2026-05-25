"""
/diary와 /note 계열 명령에서 쓰는 Markdown 문서 생성 프롬프트.
"""

from __future__ import annotations

from .prompt_language import resolve_prompt_language


def build_markdown_document_prompt(message: str, memory_context: str = "", language: str | None = None) -> str:
    """요청과 메모리 컨텍스트를 Markdown 문서 작성 프롬프트로 변환한다."""
    resolved_language = resolve_prompt_language(language)
    enhanced = f"{memory_context}\n\n{message}" if memory_context else message
    if resolved_language == "en":
        prefix = (
            "Write a Markdown document for the request below.\n"
            "- Output only the Markdown body.\n"
            "- Do not include emotion tags, TTS blocks, or extra commentary.\n"
            "- Build a natural title/body structure suited to the request.\n\n"
        )
    elif resolved_language == "ja":
        prefix = (
            "次の依頼に合わせてMarkdown文書を書いてください。\n"
            "- 出力はMarkdown本文だけにしてください。\n"
            "- 感情タグ、TTSブロック、追加説明は絶対に含めないでください。\n"
            "- 依頼の目的に合うタイトルと本文構成を自然に作ってください。\n\n"
        )
    else:
        prefix = (
            "아래 요청에 맞춰 마크다운 문서를 작성하세요.\n"
            "- 출력은 마크다운 본문만 작성하세요.\n"
            "- 감정 태그, TTS 블록, 부가 설명은 절대 포함하지 마세요.\n"
            "- 요청의 목적에 맞는 제목/본문 구조를 자연스럽게 구성하세요.\n\n"
        )
    return f"{prefix}{enhanced}"
