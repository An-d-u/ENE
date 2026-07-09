"""
사용자 기억과 ENE 기억을 함께 관리하는 설정 탭.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


PROFILE_MEMORY_SOURCE = "memory_organizer"
PROFILE_MEMORY_SOURCE_TITLE = "기억 정리"
ENE_CORE_GROUPS = ("identity", "speaking_style", "relationship_tone")


class ProfileMemoryReviewDialog(QDialog):
    """LLM이 만든 기억 정리 제안을 적용 전에 검토하는 창."""

    def __init__(self, parent, proposal: dict[str, Any]):
        super().__init__(parent)
        normalized = _normalize_profile_memory_proposal(proposal)
        self.setWindowTitle("")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(820, 640)
        self.resize(900, 720)
        self._drag_header = None
        self._drag_start_global_pos = None
        self._drag_start_frame_pos = None
        self.setStyleSheet(
            self.styleSheet()
            + """
            QDialog {
                background: transparent;
            }
            QFrame#profileMemoryReviewSurface {
                border: 1px solid rgba(148, 163, 184, 0.48);
                border-radius: 14px;
                background: rgba(13, 15, 19, 0.82);
            }
            QFrame#profileMemoryReviewUserPanel,
            QFrame#profileMemoryReviewEnePanel {
                border: 1px solid rgba(148, 163, 184, 0.42);
                border-radius: 10px;
                background: rgba(28, 32, 40, 0.98);
            }
            QFrame#profileMemoryReviewSection {
                border: none;
                background: transparent;
            }
            QLabel#profileMemoryReviewItem {
                padding: 7px 9px;
                border: 1px solid rgba(148, 163, 184, 0.26);
                border-radius: 8px;
                background: rgba(39, 45, 56, 0.98);
                line-height: 1.45;
            }
            """
        )

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        surface = QFrame()
        surface.setObjectName("profileMemoryReviewSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        outer_layout.addWidget(surface)

        header = QWidget()
        header.setObjectName("profileMemoryReviewHeader")
        header.setCursor(Qt.CursorShape.ArrowCursor)
        self._drag_header = header
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 2)
        header_layout.setSpacing(6)

        title = QLabel(_tr(parent, "settings.profile_memory.review.header.title", "정리 제안 검토"))
        title.setObjectName("FooterTitle")
        header_layout.addWidget(title)

        body = QLabel(
            _tr(
                parent,
                "settings.profile_memory.review.header.body",
                "아래 내용이 실제로 저장될 정리 제안입니다. 적용하면 현재 사용자 기억과 ENE 기억 편집 내용이 이 제안으로 교체됩니다.",
            )
        )
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        header_layout.addWidget(body)
        layout.addWidget(header)

        review_scroll = QScrollArea()
        review_scroll.setWidgetResizable(True)
        review_scroll.setFrameShape(QFrame.Shape.NoFrame)
        review_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        review_host = QWidget()
        review_layout = QHBoxLayout(review_host)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(12)
        review_layout.addWidget(
            _build_review_panel(
                "profileMemoryReviewUserPanel",
                _tr(parent, "settings.profile_memory.review.user.title", "사용자 정보"),
                [
                    (
                        _tr(parent, "settings.profile_memory.review.user.basic", "기본 정보"),
                        _format_key_values(normalized["user_profile"]["basic_info"]),
                    ),
                    (
                        _tr(parent, "settings.profile_memory.review.user.likes", "선호"),
                        _format_list(normalized["user_profile"]["preferences"]["likes"]),
                    ),
                    (
                        _tr(parent, "settings.profile_memory.review.user.dislikes", "비선호"),
                        _format_list(normalized["user_profile"]["preferences"]["dislikes"]),
                    ),
                    (
                        _tr(parent, "settings.profile_memory.review.user.facts", "facts"),
                        _format_facts(normalized["user_profile"]["facts"]),
                    ),
                ],
            ),
            1,
        )
        review_layout.addWidget(
            _build_review_panel(
                "profileMemoryReviewEnePanel",
                _tr(parent, "settings.profile_memory.review.ene.title", "에네 정보"),
                [
                    (
                        _tr(parent, "settings.profile_memory.review.ene.core", "기본 설정"),
                        _format_core_profile(normalized["ene_profile"]["core_profile"]),
                    ),
                    (
                        _tr(parent, "settings.profile_memory.review.ene.facts", "학습 정보"),
                        _format_facts(normalized["ene_profile"]["facts"]),
                    ),
                ],
            ),
            1,
        )
        review_scroll.setWidget(review_host)
        layout.addWidget(review_scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if apply_button is not None:
            apply_button.setText(_tr(parent, "settings.profile_memory.review.apply", "적용"))
            apply_button.setProperty("accent", True)
            apply_button.style().unpolish(apply_button)
            apply_button.style().polish(apply_button)
        if cancel_button is not None:
            cancel_button.setText(_tr(parent, "settings.profile_memory.review.cancel", "취소"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _drag_region_height(self) -> int:
        header = getattr(self, "_drag_header", None)
        if header is None:
            return 0
        height = header.geometry().bottom()
        if height <= 0:
            height = header.sizeHint().height()
        return int(height) + 22

    def _event_local_y(self, event) -> int:
        position = event.position() if hasattr(event, "position") else event.pos()
        return int(position.y())

    def _event_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._event_local_y(event) <= self._drag_region_height():
            self._drag_start_global_pos = self._event_global_pos(event)
            self._drag_start_frame_pos = self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_start_global_pos is not None
            and self._drag_start_frame_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = self._event_global_pos(event) - self._drag_start_global_pos
            self.move(self._drag_start_frame_pos + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_start_global_pos is not None:
            self._drag_start_global_pos = None
            self._drag_start_frame_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _build_review_panel(object_name: str, title: str, sections: list[tuple[str, list[str]]]) -> QFrame:
    panel = QFrame()
    panel.setObjectName(object_name)
    panel.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(12)

    title_label = QLabel(title)
    title_label.setObjectName("FooterTitle")
    title_label.setWordWrap(True)
    layout.addWidget(title_label)

    for section_title, items in sections:
        section = QFrame()
        section.setObjectName("profileMemoryReviewSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(6)

        heading = QLabel(section_title)
        heading.setObjectName("FooterBody")
        heading.setProperty("sectionTitle", True)
        section_layout.addWidget(heading)

        for item in items:
            label = QLabel(item)
            label.setObjectName("profileMemoryReviewItem")
            label.setWordWrap(True)
            label.setTextInteractionFlags(label.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
            section_layout.addWidget(label)
        layout.addWidget(section)

    layout.addStretch()
    return panel


def build_profile_memory_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    layout.addWidget(_build_organizer_card(self))

    from . import ene_profile_tab, user_profile_tab

    user_widget = _call_builder(user_profile_tab.build_user_profile_tab, self)
    ene_widget = _call_builder(ene_profile_tab.build_ene_profile_tab, self)
    layout.addWidget(user_widget)
    layout.addWidget(ene_widget)
    layout.addStretch()

    scroll.setWidget(widget)
    return scroll


def _call_builder(builder, dialog):
    try:
        signature = inspect.signature(builder)
        if "embedded" in signature.parameters:
            return builder(dialog, embedded=True)
    except (TypeError, ValueError):
        pass
    return builder(dialog)


def _build_organizer_card(dialog):
    card = QFrame()
    card.setObjectName("FooterCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(8)

    title = QLabel()
    dialog._bind_widget_text(title, "settings.profile_memory.organizer.title", "기억 정리")
    title.setObjectName("FooterTitle")
    layout.addWidget(title)

    body = QLabel()
    dialog._bind_widget_text(
        body,
        "settings.profile_memory.organizer.body",
        "현재 사용자 정보와 ENE 학습 정보를 LLM으로 정리한 뒤, 적용 전에 변경 제안을 확인합니다.",
    )
    body.setObjectName("FooterBody")
    body.setWordWrap(True)
    layout.addWidget(body)

    action_row = QHBoxLayout()
    action_row.setSpacing(10)

    dialog.profile_memory_status_label = QLabel()
    dialog._bind_widget_text(
        dialog.profile_memory_status_label,
        "settings.profile_memory.organizer.status.idle",
        "정리 대기",
    )
    dialog.profile_memory_status_label.setObjectName("FooterBody")
    action_row.addWidget(dialog.profile_memory_status_label, 1)

    dialog.profile_memory_organize_button = QPushButton()
    dialog.profile_memory_organize_button.setObjectName("profileMemoryOrganizeButton")
    dialog._bind_widget_text(
        dialog.profile_memory_organize_button,
        "settings.profile_memory.organizer.button",
        "기억 정리 제안 만들기",
    )
    dialog.profile_memory_organize_button.setProperty("accent", True)
    dialog.profile_memory_organize_button.clicked.connect(lambda: handle_profile_memory_organize(dialog))
    action_row.addWidget(dialog.profile_memory_organize_button)

    layout.addLayout(action_row)
    return card


def handle_profile_memory_organize(dialog) -> None:
    button = getattr(dialog, "profile_memory_organize_button", None)
    try:
        if button is not None:
            button.setEnabled(False)
        _set_organizer_status(dialog, "settings.profile_memory.organizer.status.running", "정리 제안을 만드는 중...")
        llm_client = _get_llm_client(dialog)
        if llm_client is None:
            QMessageBox.warning(
                dialog,
                _tr(dialog, "settings.profile_memory.organizer.missing_llm.title", "LLM을 사용할 수 없음"),
                _tr(dialog, "settings.profile_memory.organizer.missing_llm.body", "LLM 클라이언트가 아직 초기화되지 않았습니다."),
            )
            _set_organizer_status(dialog, "settings.profile_memory.organizer.status.failed", "정리 실패")
            return

        snapshot = collect_profile_memory_snapshot(dialog)
        prompt = build_profile_memory_prompt(snapshot)
        response_text = _request_profile_memory_proposal(llm_client, prompt)
        proposal = parse_profile_memory_proposal(response_text)
        review_dialog = ProfileMemoryReviewDialog(dialog, proposal)
        if review_dialog.exec() != QDialog.DialogCode.Accepted:
            _set_organizer_status(dialog, "settings.profile_memory.organizer.status.cancelled", "적용 취소됨")
            return

        apply_profile_memory_proposal(dialog, proposal)
        _set_organizer_status(dialog, "settings.profile_memory.organizer.status.saved", "정리 결과 저장 완료")
        QMessageBox.information(
            dialog,
            _tr(dialog, "settings.profile_memory.organizer.saved.title", "저장 완료"),
            _tr(dialog, "settings.profile_memory.organizer.saved.body", "사용자 기억과 ENE 기억을 정리해 저장했습니다."),
        )
    except Exception as exc:
        _set_organizer_status(dialog, "settings.profile_memory.organizer.status.failed", "정리 실패")
        QMessageBox.warning(
            dialog,
            _tr(dialog, "settings.profile_memory.organizer.failed.title", "기억 정리 실패"),
            _trf(
                dialog,
                "settings.profile_memory.organizer.failed.body",
                "정리 제안을 만들거나 적용하지 못했습니다.\n{error}",
                error=exc,
            ),
        )
    finally:
        if button is not None:
            button.setEnabled(True)


def collect_profile_memory_snapshot(dialog) -> dict[str, Any]:
    ene_panel = getattr(dialog, "_embedded_ene_profile_panel", None)
    return {
        "user_profile": {
            "basic_info": {key: value for key, value in getattr(dialog, "_basic_info_items", []) if key},
            "preferences": {
                "likes": _list_widget_values(getattr(dialog, "likes_list", None)),
                "dislikes": _list_widget_values(getattr(dialog, "dislikes_list", None)),
            },
            "facts": list(getattr(dialog, "_fact_items", []) or []),
        },
        "ene_profile": {
            "core_profile": _collect_ene_core_profile(ene_panel, dialog),
            "facts": _collect_ene_facts(ene_panel, dialog),
        },
    }


def build_profile_memory_prompt(snapshot: dict[str, Any]) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    cleanup_source = _profile_memory_source_label()
    return (
        "다음 user_profile와 ene_profile 데이터를 중복 없이 간결하게 정리해 주세요.\n"
        "실제 인물 정보나 새 사실을 추측하지 말고, 입력에 있는 정보만 병합/정리하세요.\n"
        "facts의 source는 기존 항목에서 이어진 정보라면 원래 source를 그대로 유지하세요.\n"
        f"여러 항목을 병합했거나 새로 정리한 항목이면 source를 \"{cleanup_source}\"로 쓰세요.\n"
        "반드시 아래 JSON 스키마만 반환하세요. 설명 문장이나 Markdown 코드는 넣지 마세요.\n"
        "{\n"
        '  "user_profile": {\n'
        '    "basic_info": {"key": "value"},\n'
        '    "preferences": {"likes": ["..."], "dislikes": ["..."]},\n'
        '    "facts": [{\n'
        '      "content": "...",\n'
        '      "category": "basic|preference|goal|habit",\n'
        f'      "source": "기존 source 또는 {cleanup_source}"\n'
        "    }]\n"
        "  },\n"
        '  "ene_profile": {\n'
        '    "core_profile": {"identity": ["..."], "speaking_style": ["..."], "relationship_tone": ["..."]},\n'
        '    "facts": [{\n'
        '      "content": "...",\n'
        '      "category": "basic|preference|goal|habit|speaking_style|relationship_tone",\n'
        f'      "source": "기존 source 또는 {cleanup_source}",\n'
        '      "origin": "manual",\n'
        '      "auto_update": false\n'
        "    }]\n"
        "  }\n"
        "}\n\n"
        f"입력 데이터:\n{snapshot_json}"
    )


def parse_profile_memory_proposal(response_text: str) -> dict[str, Any]:
    raw = json.loads(_extract_json_object(response_text))
    return _normalize_profile_memory_proposal(raw)


def _format_key_values(values: dict[str, str]) -> list[str]:
    if not values:
        return ["- 없음"]
    return [f"- {key}: {value}" for key, value in values.items()]


def _format_list(values: list[str]) -> list[str]:
    if not values:
        return ["- 없음"]
    return [f"- {value}" for value in values]


def _format_facts(facts: list[dict[str, Any]]) -> list[str]:
    if not facts:
        return ["- 없음"]
    lines = []
    for fact in facts:
        category = str(fact.get("category") or "basic").strip() or "basic"
        content = str(fact.get("content") or "").strip()
        source = str(fact.get("source") or "").strip()
        suffix = f" / 출처: {source}" if source else ""
        if content:
            lines.append(f"- [{category}] {content}{suffix}")
    return lines or ["- 없음"]


def _format_core_profile(core_profile: dict[str, list[str]]) -> list[str]:
    lines = []
    labels = {
        "identity": "자기 정의",
        "speaking_style": "말투",
        "relationship_tone": "관계 톤",
    }
    for group, values in core_profile.items():
        label = labels.get(group, group)
        if not values:
            lines.append(f"- {label}: 없음")
            continue
        for value in values:
            lines.append(f"- {label}: {value}")
    return lines or ["- 없음"]


def apply_profile_memory_proposal(dialog, proposal: dict[str, Any]) -> None:
    normalized = _normalize_profile_memory_proposal(proposal)
    user_profile = normalized["user_profile"]
    dialog._basic_info_items = list(user_profile["basic_info"].items())
    dialog._fact_items = user_profile["facts"]
    _clear_widget(getattr(dialog, "basic_info_list", None))
    _call_if_present(dialog, "_refresh_basic_info_list")
    _call_if_present(dialog, "_refresh_preference_lists", user_profile["preferences"])
    _call_if_present(dialog, "_refresh_fact_list")
    _call_if_present(dialog, "_new_basic_info_item")
    _call_if_present(dialog, "_new_fact_item")
    _call_if_present(dialog, "_save_user_profile_data")

    ene_panel = getattr(dialog, "_embedded_ene_profile_panel", None)
    if ene_panel is not None:
        ene_profile = normalized["ene_profile"]
        ene_panel._core_items = [
            {"group": group, "content": content}
            for group, values in ene_profile["core_profile"].items()
            for content in values
        ]
        ene_panel._fact_items = ene_profile["facts"]
        _call_if_present(ene_panel, "_refresh_core_list")
        _call_if_present(ene_panel, "_refresh_fact_list")
        _call_if_present(ene_panel, "_update_stats")
        _call_if_present(ene_panel, "_new_core_item")
        _call_if_present(ene_panel, "_new_fact_item")
        _call_if_present(ene_panel, "save_profile")


def _request_profile_memory_proposal(llm_client, prompt: str) -> str:
    custom = getattr(llm_client, "organize_profile_memory", None)
    if callable(custom):
        return str(_resolve_result(custom(prompt)) or "")
    raw = getattr(llm_client, "_request_one_shot_raw", None)
    if callable(raw):
        return str(raw(prompt, include_sub_prompt=False) or "")
    gemini_raw = getattr(llm_client, "_generate_one_shot_text", None)
    if callable(gemini_raw):
        return str(gemini_raw(prompt, include_sub_prompt=False) or "")
    raise RuntimeError("현재 LLM 클라이언트가 일회성 정리 요청을 지원하지 않습니다.")


def _resolve_result(value):
    if inspect.isawaitable(value):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(value)
        finally:
            asyncio.set_event_loop(None)
            loop.close()
    return value


def _normalize_profile_memory_proposal(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("정리 제안은 JSON 객체여야 합니다.")
    user_raw = raw.get("user_profile") if isinstance(raw.get("user_profile"), dict) else {}
    ene_raw = raw.get("ene_profile") if isinstance(raw.get("ene_profile"), dict) else {}
    now = datetime.now().isoformat()
    cleanup_source = _profile_memory_source_label()
    preferences = user_raw.get("preferences") if isinstance(user_raw.get("preferences"), dict) else {}
    return {
        "user_profile": {
            "basic_info": _normalize_string_dict(user_raw.get("basic_info")),
            "preferences": {
                "likes": _normalize_string_list(preferences.get("likes")),
                "dislikes": _normalize_string_list(preferences.get("dislikes")),
            },
            "facts": [
                {
                    "content": item["content"],
                    "category": item.get("category") or "basic",
                    "timestamp": item.get("timestamp") or now,
                    "source": _normalize_fact_source(item.get("source"), cleanup_source),
                }
                for item in _normalize_fact_items(user_raw.get("facts"), now)
            ],
        },
        "ene_profile": {
            "core_profile": _normalize_core_profile(ene_raw.get("core_profile")),
            "facts": [
                {
                    "content": item["content"],
                    "category": item.get("category") or "basic",
                    "timestamp": item.get("timestamp") or now,
                    "source": _normalize_fact_source(item.get("source"), cleanup_source),
                    "origin": item.get("origin") or "manual",
                    "auto_update": bool(item.get("auto_update", False)),
                    "confidence": item.get("confidence"),
                }
                for item in _normalize_fact_items(ene_raw.get("facts"), now)
            ],
        },
    }


def _profile_memory_source_label(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    return f"{PROFILE_MEMORY_SOURCE_TITLE} ({timestamp})"


def _normalize_fact_source(source: str | None, cleanup_source: str) -> str:
    normalized = str(source or "").strip()
    if not normalized or normalized == PROFILE_MEMORY_SOURCE:
        return cleanup_source
    return normalized


def _normalize_fact_items(value, now: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue
        content = str(raw_item.get("content", "") or "").strip()
        if not content:
            continue
        items.append(
            {
                "content": content,
                "category": str(raw_item.get("category", "basic") or "basic").strip(),
                "timestamp": str(raw_item.get("timestamp", "") or "").strip() or now,
                "source": str(raw_item.get("source", "") or "").strip(),
                "origin": str(raw_item.get("origin", "manual") or "manual").strip(),
                "auto_update": bool(raw_item.get("auto_update", False)),
                "confidence": raw_item.get("confidence"),
            }
        )
    return items


def _normalize_core_profile(value) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        value = {}
    normalized = {group: _normalize_string_list(value.get(group)) for group in ENE_CORE_GROUPS}
    for group, values in value.items():
        key = str(group or "").strip()
        if key and key not in normalized:
            normalized[key] = _normalize_string_list(values)
    return normalized


def _normalize_string_dict(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _normalize_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _extract_json_object(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM 응답에서 JSON 객체를 찾지 못했습니다.")
    return stripped[start : end + 1]


def _collect_ene_core_profile(ene_panel, dialog) -> dict[str, list[str]]:
    if ene_panel is not None and hasattr(ene_panel, "_core_items"):
        core_profile = {group: [] for group in ENE_CORE_GROUPS}
        for item in getattr(ene_panel, "_core_items", []) or []:
            if not isinstance(item, dict):
                continue
            group = str(item.get("group") or "identity").strip() or "identity"
            content = str(item.get("content") or "").strip()
            if content:
                core_profile.setdefault(group, []).append(content)
        return core_profile
    ene_profile = getattr(getattr(dialog, "_bridge", None), "ene_profile", None)
    return _normalize_core_profile(getattr(ene_profile, "core_profile", {}) if ene_profile is not None else {})


def _collect_ene_facts(ene_panel, dialog) -> list[dict[str, Any]]:
    if ene_panel is not None and hasattr(ene_panel, "_fact_items"):
        return list(getattr(ene_panel, "_fact_items", []) or [])
    ene_profile = getattr(getattr(dialog, "_bridge", None), "ene_profile", None)
    facts = []
    for fact in getattr(ene_profile, "facts", []) or []:
        facts.append(
            {
                "content": str(getattr(fact, "content", "") or "").strip(),
                "category": str(getattr(fact, "category", "basic") or "basic").strip(),
                "timestamp": str(getattr(fact, "timestamp", "") or "").strip(),
                "source": str(getattr(fact, "source", "") or "").strip(),
                "origin": str(getattr(fact, "origin", "auto") or "auto").strip(),
                "auto_update": bool(getattr(fact, "auto_update", True)),
                "confidence": getattr(fact, "confidence", None),
            }
        )
    return facts


def _list_widget_values(widget) -> list[str]:
    if widget is None or not hasattr(widget, "count"):
        return []
    return [
        widget.item(index).text().strip()
        for index in range(widget.count())
        if widget.item(index) and widget.item(index).text().strip()
    ]


def _get_llm_client(dialog):
    bridge = getattr(dialog, "_bridge", None)
    return getattr(bridge, "llm_client", None) if bridge is not None else None


def _set_organizer_status(dialog, key: str, fallback: str) -> None:
    label = getattr(dialog, "profile_memory_status_label", None)
    if label is not None and hasattr(label, "setText"):
        label.setText(_tr(dialog, key, fallback))


def _tr(dialog, key: str, fallback: str) -> str:
    translator = getattr(dialog, "_translated_text", None)
    return translator(key, fallback) if callable(translator) else fallback


def _trf(dialog, key: str, fallback: str, **kwargs) -> str:
    translator = getattr(dialog, "_translated_text_format", None)
    return translator(key, fallback, **kwargs) if callable(translator) else fallback.format(**kwargs)


def _clear_widget(widget) -> None:
    clear = getattr(widget, "clear", None)
    if callable(clear):
        clear()


def _call_if_present(target, name: str, *args) -> None:
    callback = getattr(target, name, None)
    if callable(callback):
        callback(*args)
