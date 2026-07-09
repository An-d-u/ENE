"""
사용자 프로필 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def build_user_profile_tab(dialog, embedded: bool = False):
    self = dialog
    scroll = None
    if not embedded:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    header = QFrame()
    header.setObjectName("FooterCard")
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(20, 18, 20, 18)
    header_layout.setSpacing(6)

    title = QLabel()
    self._bind_widget_text(title, "settings.profile.header.title", "사용자 기억 관리")
    title.setObjectName("FooterTitle")
    header_layout.addWidget(title)

    body = QLabel()
    self._bind_widget_text(
        body,
        "settings.profile.header.body",
        "user_profile.json의 기본 정보, likes, dislikes, facts만 구조적으로 관리합니다. 원본 JSON 전체를 직접 열지 않고 필요한 항목만 수정합니다.",
    )
    body.setObjectName("FooterBody")
    body.setWordWrap(True)
    header_layout.addWidget(body)
    layout.addWidget(header)

    top_row = QHBoxLayout()
    top_row.setSpacing(12)

    basic_group = QGroupBox()
    self._bind_group_title(basic_group, "settings.profile.basic.title", "기본 정보")
    basic_layout = QVBoxLayout(basic_group)
    basic_layout.setSpacing(10)

    self.basic_info_list = QListWidget()
    self.basic_info_list.setMinimumHeight(190)
    self.basic_info_list.currentRowChanged.connect(self._on_basic_info_selected)
    basic_layout.addWidget(self.basic_info_list)

    self.basic_info_key_input = QLineEdit()
    self._bind_placeholder(self.basic_info_key_input, "settings.profile.basic.key.placeholder", "항목 이름")
    basic_layout.addWidget(self.basic_info_key_input)

    self.basic_info_value_input = QLineEdit()
    self._bind_placeholder(self.basic_info_value_input, "settings.profile.basic.value.placeholder", "값")
    basic_layout.addWidget(self.basic_info_value_input)

    basic_actions = QHBoxLayout()
    basic_actions.setSpacing(8)

    basic_new_btn = QPushButton()
    self._bind_widget_text(basic_new_btn, "settings.profile.basic.new", "새 항목")
    basic_new_btn.clicked.connect(self._new_basic_info_item)
    basic_actions.addWidget(basic_new_btn)

    basic_apply_btn = QPushButton()
    self._bind_widget_text(basic_apply_btn, "settings.profile.basic.apply", "목록에 반영")
    basic_apply_btn.setProperty("accent", True)
    basic_apply_btn.style().unpolish(basic_apply_btn)
    basic_apply_btn.style().polish(basic_apply_btn)
    basic_apply_btn.clicked.connect(self._apply_basic_info_item)
    basic_actions.addWidget(basic_apply_btn)

    basic_delete_btn = QPushButton()
    self._bind_widget_text(basic_delete_btn, "settings.profile.basic.delete", "삭제")
    basic_delete_btn.clicked.connect(self._delete_basic_info_item)
    basic_actions.addWidget(basic_delete_btn)
    basic_layout.addLayout(basic_actions)

    top_row.addWidget(basic_group, 1)

    preference_group = QGroupBox()
    self._bind_group_title(preference_group, "settings.profile.preference.title", "선호와 비선호")
    preference_layout = QVBoxLayout(preference_group)
    preference_layout.setSpacing(12)

    likes_row = QVBoxLayout()
    likes_row.setSpacing(10)
    likes_label = QLabel()
    self._bind_widget_text(likes_label, "settings.profile.preference.likes.title", "likes")
    likes_label.setObjectName("FooterTitle")
    likes_row.addWidget(likes_label)

    likes_col = QVBoxLayout()
    likes_col.setSpacing(10)
    self.likes_list = QListWidget()
    self.likes_list.setMinimumHeight(92)
    self.likes_list.setMaximumHeight(120)
    self._configure_preference_list(self.likes_list)
    likes_col.addWidget(self.likes_list)
    self.likes_input = QLineEdit()
    self._bind_placeholder(self.likes_input, "settings.profile.preference.likes.placeholder", "좋아하는 항목 추가")
    likes_col.addWidget(self.likes_input)
    likes_actions = QHBoxLayout()
    likes_actions.setSpacing(8)
    likes_actions.addStretch()
    likes_add_btn = QPushButton()
    self._bind_widget_text(likes_add_btn, "settings.profile.preference.add", "추가")
    likes_add_btn.clicked.connect(lambda: self._add_preference_item("likes"))
    likes_actions.addWidget(likes_add_btn)
    likes_delete_btn = QPushButton()
    self._bind_widget_text(likes_delete_btn, "settings.profile.preference.delete", "삭제")
    likes_delete_btn.clicked.connect(lambda: self._delete_preference_item("likes"))
    likes_actions.addWidget(likes_delete_btn)
    likes_col.addLayout(likes_actions)
    likes_row.addLayout(likes_col)
    preference_layout.addLayout(likes_row)

    dislikes_row = QVBoxLayout()
    dislikes_row.setSpacing(10)
    dislikes_label = QLabel()
    self._bind_widget_text(dislikes_label, "settings.profile.preference.dislikes.title", "dislikes")
    dislikes_label.setObjectName("FooterTitle")
    dislikes_row.addWidget(dislikes_label)

    dislikes_col = QVBoxLayout()
    dislikes_col.setSpacing(10)
    self.dislikes_list = QListWidget()
    self.dislikes_list.setMinimumHeight(92)
    self.dislikes_list.setMaximumHeight(120)
    self._configure_preference_list(self.dislikes_list)
    dislikes_col.addWidget(self.dislikes_list)
    self.dislikes_input = QLineEdit()
    self._bind_placeholder(
        self.dislikes_input,
        "settings.profile.preference.dislikes.placeholder",
        "싫어하는 항목 추가",
    )
    dislikes_col.addWidget(self.dislikes_input)
    dislikes_actions = QHBoxLayout()
    dislikes_actions.setSpacing(8)
    dislikes_actions.addStretch()
    dislikes_add_btn = QPushButton()
    self._bind_widget_text(dislikes_add_btn, "settings.profile.preference.add", "추가")
    dislikes_add_btn.clicked.connect(lambda: self._add_preference_item("dislikes"))
    dislikes_actions.addWidget(dislikes_add_btn)
    dislikes_delete_btn = QPushButton()
    self._bind_widget_text(dislikes_delete_btn, "settings.profile.preference.delete", "삭제")
    dislikes_delete_btn.clicked.connect(lambda: self._delete_preference_item("dislikes"))
    dislikes_actions.addWidget(dislikes_delete_btn)
    dislikes_col.addLayout(dislikes_actions)
    dislikes_row.addLayout(dislikes_col)
    preference_layout.addLayout(dislikes_row)

    top_row.addWidget(preference_group, 1)
    layout.addLayout(top_row)

    facts_group = QGroupBox()
    self._bind_group_title(facts_group, "settings.profile.facts.title", "facts")
    facts_layout = QHBoxLayout(facts_group)
    facts_layout.setSpacing(12)

    self.fact_list = QListWidget()
    self.fact_list.setMinimumHeight(320)
    self.fact_list.currentRowChanged.connect(self._on_fact_selected)
    facts_layout.addWidget(self.fact_list, 1)

    fact_editor_col = QVBoxLayout()
    fact_editor_col.setSpacing(10)

    self.fact_content_edit = QPlainTextEdit()
    self._bind_placeholder(self.fact_content_edit, "settings.profile.facts.content.placeholder", "기억 내용")
    self.fact_content_edit.setMinimumHeight(150)
    fact_editor_col.addWidget(self.fact_content_edit)

    fact_meta_row = QHBoxLayout()
    fact_meta_row.setSpacing(10)

    self.fact_category_combo = QComboBox()
    for category in ("basic", "preference", "goal", "habit"):
        self.fact_category_combo.addItem(self._fact_category_label(category), category)
    fact_meta_row.addWidget(self.fact_category_combo)

    self.fact_source_input = QLineEdit()
    self._bind_placeholder(self.fact_source_input, "settings.profile.facts.source.placeholder", "출처")
    fact_meta_row.addWidget(self.fact_source_input, 1)
    fact_editor_col.addLayout(fact_meta_row)

    self.fact_timestamp_label = QLabel()
    self._set_fact_timestamp("settings.profile.facts.timestamp.new", "신규 항목")
    self.fact_timestamp_label.setObjectName("FooterBody")
    fact_editor_col.addWidget(self.fact_timestamp_label)

    fact_actions = QHBoxLayout()
    fact_actions.setSpacing(8)

    fact_new_btn = QPushButton()
    self._bind_widget_text(fact_new_btn, "settings.profile.facts.new", "새 항목")
    fact_new_btn.clicked.connect(self._new_fact_item)
    fact_actions.addWidget(fact_new_btn)

    fact_apply_btn = QPushButton()
    self._bind_widget_text(fact_apply_btn, "settings.profile.facts.apply", "목록에 반영")
    fact_apply_btn.setProperty("accent", True)
    fact_apply_btn.style().unpolish(fact_apply_btn)
    fact_apply_btn.style().polish(fact_apply_btn)
    fact_apply_btn.clicked.connect(self._apply_fact_item)
    fact_actions.addWidget(fact_apply_btn)

    fact_delete_btn = QPushButton()
    self._bind_widget_text(fact_delete_btn, "settings.profile.facts.delete", "삭제")
    fact_delete_btn.clicked.connect(self._delete_fact_item)
    fact_actions.addWidget(fact_delete_btn)
    fact_editor_col.addLayout(fact_actions)

    facts_layout.addLayout(fact_editor_col, 1)
    layout.addWidget(facts_group)

    footer_row = QHBoxLayout()
    footer_row.setSpacing(10)

    self._profile_status_label = QLabel()
    self._set_profile_status("settings.profile.status.idle", "로드 대기")
    self._profile_status_label.setObjectName("FooterBody")
    footer_row.addWidget(self._profile_status_label)

    footer_row.addStretch()

    profile_reload_btn = QPushButton()
    self._bind_widget_text(profile_reload_btn, "settings.profile.reload", "다시 불러오기")
    profile_reload_btn.clicked.connect(self._load_user_profile_data)
    footer_row.addWidget(profile_reload_btn)

    profile_save_btn = QPushButton()
    self._bind_widget_text(profile_save_btn, "settings.profile.save", "저장")
    profile_save_btn.setProperty("accent", True)
    profile_save_btn.style().unpolish(profile_save_btn)
    profile_save_btn.style().polish(profile_save_btn)
    profile_save_btn.clicked.connect(self._save_user_profile_data)
    footer_row.addWidget(profile_save_btn)

    layout.addLayout(footer_row)
    layout.addStretch()

    if scroll is not None:
        scroll.setWidget(widget)
    self._load_user_profile_data()
    return scroll if scroll is not None else widget
