"""
에네 프로필 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..ene_profile_editor import EneProfileEditorPanel


def build_ene_profile_tab(dialog):
    self = dialog
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
    self._bind_widget_text(title, "settings.ene_profile.header.title", "ENE 기억 관리")
    title.setObjectName("FooterTitle")
    header_layout.addWidget(title)

    body = QLabel()
    self._bind_widget_text(
        body,
        "settings.ene_profile.header.body",
        "에네의 기본 설정과 대화에서 학습된 자기 정보를 분리해서 관리합니다. 자동 추출 정보와 수동 보강 정보를 같은 화면에서 정리할 수 있습니다.",
    )
    body.setObjectName("FooterBody")
    body.setWordWrap(True)
    header_layout.addWidget(body)
    layout.addWidget(header)

    ene_profile = getattr(self._bridge, "ene_profile", None) if self._bridge else None
    if ene_profile is not None:
        panel = EneProfileEditorPanel(
            ene_profile,
            widget,
            translate=self._translated_text,
            translate_format=self._translated_text_format,
            show_close_button=False,
        )
        self._embedded_ene_profile_panel = panel
        layout.addWidget(panel)
    else:
        card = QFrame()
        card.setObjectName("FooterCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(8)

        empty_title = QLabel()
        self._bind_widget_text(empty_title, "settings.ene_profile.empty.title", "ENE 기억 관리")
        empty_title.setObjectName("FooterTitle")
        card_layout.addWidget(empty_title)

        empty_body = QLabel()
        self._bind_widget_text(
            empty_body,
            "settings.ene_profile.empty.body",
            "에네 프로필이 아직 초기화되지 않아 편집 패널을 열 수 없습니다.",
        )
        empty_body.setObjectName("FooterBody")
        empty_body.setWordWrap(True)
        card_layout.addWidget(empty_body)
        layout.addWidget(card)

    layout.addStretch()
    scroll.setWidget(widget)
    return scroll

