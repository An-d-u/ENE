"""
프롬프트 편집 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def build_prompt_tab(dialog):
    """프롬프트 설정 탭 위젯을 구성한다."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    dialog._prompt_scroll = scroll

    widget = QWidget()
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    dialog._prompt_content = widget
    layout = QGridLayout(widget)
    dialog._prompt_grid = layout
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    header = QFrame()
    header.setMinimumWidth(0)
    header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    header.setObjectName("FooterCard")
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(20, 18, 20, 18)
    header_layout.setSpacing(6)

    title = QLabel()
    dialog._bind_widget_text(title, "settings.prompt.header.title", "프롬프트 설정")
    title.setObjectName("FooterTitle")
    header_layout.addWidget(title)

    body = QLabel()
    dialog._bind_widget_text(
        body,
        "settings.prompt.header.body",
        "파이썬 파일 전체를 직접 수정하지 않고 BASE_SYSTEM_PROMPT, SUB_PROMPT, EMOTIONS와 감정 사용 가이드만 안전하게 관리합니다.",
    )
    body.setObjectName("FooterBody")
    body.setWordWrap(True)
    header_layout.addWidget(body)
    layout.addWidget(header, 0, 0, 1, 2)

    base_group = QGroupBox("BASE_SYSTEM_PROMPT")
    base_group.setMinimumWidth(0)
    base_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    base_layout = QVBoxLayout(base_group)
    base_layout.setSpacing(10)
    dialog._prompt_path_label = QLabel(str(dialog._prompt_path))
    dialog._prompt_path_label.setObjectName("FooterBody")
    dialog._prompt_path_label.setWordWrap(True)
    dialog._prompt_path_label.setMinimumWidth(0)
    dialog._prompt_path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    base_layout.addWidget(dialog._prompt_path_label)
    dialog.base_prompt_editor = QPlainTextEdit()
    dialog.base_prompt_editor.setMinimumWidth(0)
    dialog.base_prompt_editor.setMinimumHeight(320)
    dialog.base_prompt_editor.textChanged.connect(dialog._schedule_prompt_token_refresh)
    base_layout.addWidget(dialog.base_prompt_editor, 1)
    dialog._base_prompt_token_label = QLabel("BASE_SYSTEM_PROMPT 현재 토큰: 0개 · 문자 수: 0자")
    dialog._base_prompt_token_label.setObjectName("FooterBody")
    dialog._base_prompt_token_label.setWordWrap(True)
    dialog._base_prompt_token_label.setMinimumWidth(0)
    dialog._base_prompt_token_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    base_layout.addWidget(dialog._base_prompt_token_label)
    layout.addWidget(base_group, 1, 0)

    sub_group = QGroupBox()
    sub_group.setMinimumWidth(0)
    sub_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    dialog._bind_group_title(sub_group, "settings.prompt.sub.title", "SUB_PROMPT 본문")
    sub_layout = QVBoxLayout(sub_group)
    sub_layout.setSpacing(10)
    dialog._sub_prompt_path_label = QLabel(str(dialog._sub_prompt_path))
    dialog._sub_prompt_path_label.setObjectName("FooterBody")
    dialog._sub_prompt_path_label.setWordWrap(True)
    dialog._sub_prompt_path_label.setMinimumWidth(0)
    dialog._sub_prompt_path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    sub_layout.addWidget(dialog._sub_prompt_path_label)
    sub_note = QLabel()
    dialog._bind_widget_text(
        sub_note,
        "settings.prompt.sub.note",
        "감정 규칙과 감정 사용 가이드는 아래 감정 편집 카드에서 별도로 관리됩니다.",
    )
    sub_note.setObjectName("FooterBody")
    sub_note.setWordWrap(True)
    sub_layout.addWidget(sub_note)
    dialog.sub_prompt_editor = QPlainTextEdit()
    dialog.sub_prompt_editor.setMinimumWidth(0)
    dialog.sub_prompt_editor.setMinimumHeight(320)
    dialog.sub_prompt_editor.textChanged.connect(dialog._schedule_prompt_token_refresh)
    sub_layout.addWidget(dialog.sub_prompt_editor, 1)
    dialog._sub_prompt_token_label = QLabel("SUB_PROMPT 현재 토큰: 0개 · 문자 수: 0자")
    dialog._sub_prompt_token_label.setObjectName("FooterBody")
    dialog._sub_prompt_token_label.setWordWrap(True)
    dialog._sub_prompt_token_label.setMinimumWidth(0)
    dialog._sub_prompt_token_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    sub_layout.addWidget(dialog._sub_prompt_token_label)
    layout.addWidget(sub_group, 1, 1)
    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 1)

    dialog._life_world_group = QGroupBox()
    dialog._life_world_group.setMinimumWidth(0)
    dialog._life_world_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    dialog._life_world_group.setProperty("fullWidth", True)
    dialog._bind_group_title(
        dialog._life_world_group,
        "settings.prompt.life_world.title",
        "생활 환경",
    )
    life_world_layout = QVBoxLayout(dialog._life_world_group)
    life_world_layout.setSpacing(10)

    dialog._life_world_label = QLabel()
    dialog._bind_widget_text(
        dialog._life_world_label,
        "settings.prompt.life_world.label",
        "생활 환경 Markdown",
    )
    life_world_layout.addWidget(dialog._life_world_label)

    dialog._life_world_path_label = QLabel(str(dialog._life_world_path))
    dialog._life_world_path_label.setObjectName("FooterBody")
    dialog._life_world_path_label.setWordWrap(True)
    dialog._life_world_path_label.setMinimumWidth(0)
    dialog._life_world_path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    life_world_layout.addWidget(dialog._life_world_path_label)

    dialog.life_world_editor = QPlainTextEdit()
    dialog.life_world_editor.setMinimumWidth(0)
    dialog.life_world_editor.setMinimumHeight(220)
    dialog._register_text_binding(
        dialog.life_world_editor.setAccessibleName,
        "settings.prompt.life_world.accessible_name",
        "생활 환경 Markdown 편집기",
    )
    dialog._life_world_label.setBuddy(dialog.life_world_editor)
    dialog.life_world_editor.textChanged.connect(dialog._on_life_world_text_changed)
    life_world_layout.addWidget(dialog.life_world_editor, 1)

    dialog._life_world_warning_label = QLabel()
    dialog._bind_widget_text(
        dialog._life_world_warning_label,
        "settings.prompt.life_world.empty_warning",
        "생활 환경이 비어 있으면 생활 기록을 생성하지 않습니다.",
    )
    dialog._life_world_warning_label.setObjectName("InlineHint")
    dialog._life_world_warning_label.setWordWrap(True)
    life_world_layout.addWidget(dialog._life_world_warning_label)

    life_world_footer = QHBoxLayout()
    dialog._life_world_token_label = QLabel("생활 환경 현재 토큰: 0개 · 문자 수: 0자")
    dialog._life_world_token_label.setObjectName("FooterBody")
    dialog._life_world_token_label.setWordWrap(True)
    dialog._life_world_token_label.setMinimumWidth(0)
    dialog._life_world_token_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    life_world_footer.addWidget(dialog._life_world_token_label)
    life_world_footer.addStretch()

    life_world_default_btn = QPushButton()
    dialog._bind_widget_text(
        life_world_default_btn,
        "settings.prompt.life_world.default",
        "기본값 불러오기",
    )
    dialog._register_text_binding(
        life_world_default_btn.setAccessibleName,
        "settings.prompt.life_world.default",
        "생활 환경 기본값 불러오기",
    )
    life_world_default_btn.clicked.connect(dialog._load_default_life_world_prompt)
    life_world_footer.addWidget(life_world_default_btn)
    life_world_layout.addLayout(life_world_footer)
    layout.addWidget(dialog._life_world_group, 2, 0, 1, 2)

    emotion_group = QGroupBox()
    emotion_group.setMinimumWidth(0)
    emotion_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    dialog._bind_group_title(emotion_group, "settings.prompt.emotions.title", "감정 목록과 사용 가이드")
    emotion_layout = QHBoxLayout(emotion_group)
    emotion_layout.setSpacing(12)

    dialog.emotion_list = QListWidget()
    dialog.emotion_list.setMinimumHeight(260)
    dialog.emotion_list.currentRowChanged.connect(dialog._on_emotion_selected)
    emotion_layout.addWidget(dialog.emotion_list, 1)

    emotion_editor_col = QVBoxLayout()
    emotion_editor_col.setSpacing(10)

    dialog.emotion_name_input = QLineEdit()
    dialog._bind_placeholder(dialog.emotion_name_input, "settings.prompt.emotions.name.placeholder", "감정 키 (예: shy)")
    emotion_editor_col.addWidget(dialog.emotion_name_input)

    dialog.emotion_guide_editor = QPlainTextEdit()
    dialog._bind_placeholder(
        dialog.emotion_guide_editor,
        "settings.prompt.emotions.guide.placeholder",
        "감정 사용 가이드",
    )
    dialog.emotion_guide_editor.setMinimumHeight(180)
    emotion_editor_col.addWidget(dialog.emotion_guide_editor, 1)

    emotion_actions = QHBoxLayout()
    emotion_actions.setSpacing(8)

    emotion_new_btn = QPushButton()
    dialog._bind_widget_text(emotion_new_btn, "settings.prompt.emotions.new", "새 감정")
    emotion_new_btn.clicked.connect(dialog._new_emotion_item)
    emotion_actions.addWidget(emotion_new_btn)

    emotion_apply_btn = QPushButton()
    dialog._bind_widget_text(emotion_apply_btn, "settings.prompt.emotions.apply", "목록에 반영")
    emotion_apply_btn.setProperty("accent", True)
    emotion_apply_btn.style().unpolish(emotion_apply_btn)
    emotion_apply_btn.style().polish(emotion_apply_btn)
    emotion_apply_btn.clicked.connect(dialog._apply_emotion_item)
    emotion_actions.addWidget(emotion_apply_btn)

    emotion_delete_btn = QPushButton()
    dialog._bind_widget_text(emotion_delete_btn, "settings.prompt.emotions.delete", "삭제")
    emotion_delete_btn.clicked.connect(dialog._delete_emotion_item)
    emotion_actions.addWidget(emotion_delete_btn)

    emotion_editor_col.addLayout(emotion_actions)
    emotion_layout.addLayout(emotion_editor_col, 1)
    layout.addWidget(emotion_group, 3, 0, 1, 2)

    footer_row = QHBoxLayout()
    footer_row.setSpacing(10)

    dialog._prompt_status_label = QLabel()
    dialog._set_prompt_status("settings.prompt.status.idle", "로드 대기")
    dialog._prompt_status_label.setObjectName("FooterBody")
    footer_row.addWidget(dialog._prompt_status_label)

    footer_row.addStretch()

    reload_btn = QPushButton()
    dialog._bind_widget_text(reload_btn, "settings.prompt.reload", "다시 불러오기")
    reload_btn.clicked.connect(dialog._load_prompt_configuration)
    dialog._register_text_binding(
        reload_btn.setAccessibleName,
        "settings.prompt.reload",
        "프롬프트 다시 불러오기",
    )
    footer_row.addWidget(reload_btn)

    save_btn = QPushButton()
    dialog._bind_widget_text(save_btn, "settings.prompt.save", "저장")
    save_btn.setProperty("accent", True)
    save_btn.style().unpolish(save_btn)
    save_btn.style().polish(save_btn)
    save_btn.clicked.connect(dialog._save_prompt_configuration)
    dialog._register_text_binding(
        save_btn.setAccessibleName,
        "settings.prompt.save",
        "프롬프트 저장",
    )
    footer_row.addWidget(save_btn)
    layout.addLayout(footer_row, 4, 0, 1, 2)

    layout.setRowStretch(5, 1)
    scroll.setWidget(widget)
    dialog._load_prompt_configuration()
    dialog._refresh_prompt_token_counts()
    return scroll
