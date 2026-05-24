"""UTF-8 with BOM
설정/기억 관리 데스크톱 다이얼로그.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class PrototypeMemory:
    timestamp: str
    title: str
    summary: str
    tags: tuple[str, ...]
    important: bool = False


SAMPLE_MEMORIES = [
    PrototypeMemory(
        timestamp="오늘 21:14",
        title="방송 전 루틴 조정",
        summary="시작 10분 전에는 알림을 줄이고, 음성 입력은 한국어 고정으로 두는 편이 안정적이라는 메모입니다.",
        tags=("방송", "루틴", "안정성"),
        important=True,
    ),
    PrototypeMemory(
        timestamp="어제 23:02",
        title="모델 응답 톤 선호",
        summary="짧고 단정한 답변은 선호하지만, 설정 변경처럼 민감한 작업에서는 변경 전 요약이 먼저 보여야 한다는 기록입니다.",
        tags=("응답톤", "설정", "UX"),
    ),
    PrototypeMemory(
        timestamp="3월 7일 18:40",
        title="기억 검색 민감도",
        summary="중요 기억 3개, 유사 기억 3개, 최근 기억 2개 조합이 가장 자연스럽고 과잉 회상을 줄였다는 테스트 결과입니다.",
        tags=("검색", "튜닝", "기억"),
        important=True,
    ),
    PrototypeMemory(
        timestamp="3월 6일 20:11",
        title="오브시디언 연동 메모",
        summary="대화 요약과 일기 저장은 한 화면에서 상태를 보여주되, 실제 실행 버튼은 보조 액션 영역으로 분리하는 편이 덜 산만합니다.",
        tags=("연동", "일기", "정리"),
    ),
]


def ensure_preview_font() -> None:
    for font_path in ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"):
        if Path(font_path).exists():
            QFontDatabase.addApplicationFont(font_path)

    app = QApplication.instance()
    if app is not None:
        app.setFont(QFont("Malgun Gothic", 10))


def apply_soft_shadow(widget: QWidget, blur: int = 36, alpha: int = 28) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 12)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)


class CardFrame(QFrame):
    def __init__(self, object_name: str = "Card", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        apply_soft_shadow(self)


class MemoryItemFrame(CardFrame):
    def __init__(self, on_click, parent: QWidget | None = None):
        super().__init__("MemoryItem", parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_click is not None:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class PrototypeActionDialog(QDialog):
    def __init__(self, title_text: str, body_text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)

        surface = CardFrame("Card")
        layout.addWidget(surface)

        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(24, 24, 24, 24)
        surface_layout.setSpacing(14)

        eyebrow = QLabel("세부 설정")
        eyebrow.setObjectName("Eyebrow")
        surface_layout.addWidget(eyebrow)

        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        surface_layout.addWidget(title)

        body = QLabel(body_text)
        body.setObjectName("Body")
        body.setWordWrap(True)
        surface_layout.addWidget(body)

        button_row = QHBoxLayout()
        button_row.addStretch()

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)

        surface_layout.addLayout(button_row)


class SettingsMemoryPrototypeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._drag_active = False
        self._drag_offset = QPoint()
        self._memories = list(SAMPLE_MEMORIES)
        self._selected_memory_index = 0
        self._memory_cards: list[QWidget] = []
        self._memory_list_layout: QVBoxLayout | None = None
        self._inspector_title_label: QLabel | None = None
        self._inspector_body_label: QLabel | None = None
        self._inspector_tags_layout: QHBoxLayout | None = None
        self._inspector_time_value: QLabel | None = None
        self._inspector_source_value: QLabel | None = None
        self._inspector_importance_value: QLabel | None = None
        self._inspector_priority_value: QLabel | None = None
        self._inspector_primary_button: QPushButton | None = None
        self._resize_active = False
        self._resize_edge = ""
        self._resize_start_global = QPoint()
        self._resize_start_pos = QPoint()
        self._resize_start_size = self.size()
        self._resize_margin = 14

        self.setWindowTitle("ENE 설정")
        self.resize(1520, 960)
        self.setMinimumSize(1180, 760)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._apply_stylesheet()
        self._build_ui()

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #EEF1F5;
                color: #111827;
                font-family: 'Malgun Gothic', 'Segoe UI Variable', 'Segoe UI', sans-serif;
            }
            QWidget {
                background: transparent;
            }
            QFrame#Surface {
                background: rgba(248, 249, 252, 0.96);
                border: 1px solid rgba(214, 218, 228, 0.92);
                border-radius: 30px;
            }
            QFrame#TitleBar {
                background: rgba(255, 255, 255, 0.72);
                border: 1px solid rgba(222, 226, 235, 0.96);
                border-radius: 22px;
            }
            QFrame#Card, QFrame#AccentCard, QFrame#MetricCard, QFrame#ListCard, QFrame#MemoryItem, QFrame#TabShell {
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(225, 229, 237, 0.96);
                border-radius: 26px;
            }
            QFrame#TabShell {
                background: rgba(252, 253, 255, 0.98);
            }
            QLabel#WindowTitle {
                color: #111827;
                font-size: 18px;
                font-weight: 700;
            }
            QFrame#AccentCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,0.98),
                    stop:1 rgba(240,246,255,0.98));
                border: 1px solid rgba(196, 214, 255, 0.95);
            }
            QFrame#MemoryItem[selected='true'] {
                border: 1px solid rgba(0, 113, 227, 0.36);
                background: rgba(246, 250, 255, 0.98);
            }
            QLabel#Eyebrow {
                color: #6B7280;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#HeroTitle {
                color: #111827;
                font-size: 30px;
                font-weight: 700;
            }
            QLabel#SectionTitle {
                color: #111827;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#CardTitle {
                color: #111827;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#Body {
                color: #4B5563;
                font-size: 14px;
                line-height: 1.5;
            }
            QLabel#MetricValue {
                color: #111827;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#MetricLabel {
                color: #6B7280;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#Pill, QLabel#TagPill, QLabel#BluePill, QLabel#MutedPill {
                border-radius: 14px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#Pill {
                background: rgba(17, 24, 39, 0.06);
                color: #374151;
                border: 1px solid rgba(209, 213, 219, 0.9);
            }
            QLabel#TagPill {
                background: rgba(241, 245, 249, 0.96);
                color: #475569;
                border: 1px solid rgba(226, 232, 240, 0.96);
            }
            QLabel#BluePill {
                background: rgba(0, 113, 227, 0.1);
                color: #005BB5;
                border: 1px solid rgba(147, 197, 253, 0.8);
            }
            QLabel#MutedPill {
                background: rgba(255, 255, 255, 0.86);
                color: #6B7280;
                border: 1px solid rgba(229, 231, 235, 0.96);
            }
            QLabel#KeyValueLabel {
                color: #6B7280;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#KeyValueValue {
                color: #111827;
                font-size: 14px;
                font-weight: 600;
            }
            QLineEdit {
                min-height: 46px;
                padding: 0 16px;
                border-radius: 18px;
                background: rgba(248, 250, 252, 0.98);
                border: 1px solid rgba(218, 223, 233, 1);
                color: #111827;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(0, 113, 227, 0.55);
                background: #FFFFFF;
            }
            QSpinBox {
                min-height: 44px;
                padding: 0 14px;
                border-radius: 16px;
                background: rgba(248, 250, 252, 0.98);
                border: 1px solid rgba(218, 223, 233, 1);
                color: #111827;
                font-size: 14px;
                font-weight: 600;
            }
            QSpinBox:focus {
                border: 1px solid rgba(0, 113, 227, 0.55);
                background: #FFFFFF;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 28px;
                border: none;
                background: transparent;
            }
            QPushButton {
                min-height: 44px;
                padding: 0 18px;
                border-radius: 18px;
                border: 1px solid rgba(214, 218, 228, 0.98);
                background: rgba(255, 255, 255, 0.96);
                color: #111827;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(248, 250, 252, 1);
            }
            QPushButton[accent='true'] {
                background: #0071E3;
                color: white;
                border: 1px solid #0071E3;
            }
            QPushButton[accent='true']:hover {
                background: #0067CF;
            }
            QPushButton[ghost='true'] {
                background: transparent;
                border: none;
                min-width: 34px;
                min-height: 34px;
                padding: 0;
                border-radius: 17px;
                color: #6B7280;
            }
            QPushButton[ghost='true']:hover {
                background: rgba(17, 24, 39, 0.06);
            }
            QTabWidget#MainTabs {
                background: transparent;
            }
            QTabWidget#MainTabs::pane {
                background: transparent;
                border: none;
                top: 12px;
            }
            QTabWidget#MainTabs::tab-bar {
                left: 0px;
            }
            QTabBar#MainTabBar {
                background: rgba(242, 245, 249, 0.98);
                border: 1px solid rgba(225, 229, 237, 0.96);
                border-radius: 22px;
                padding: 4px;
            }
            QTabBar#MainTabBar::tab {
                background: transparent;
                color: #6B7280;
                border: 1px solid transparent;
                padding: 11px 18px;
                margin: 0 6px 0 0;
                border-radius: 18px;
                min-width: 96px;
                font-size: 13px;
                font-weight: 600;
            }
            QTabBar#MainTabBar::tab:last {
                margin-right: 0px;
            }
            QTabBar#MainTabBar::tab:selected {
                background: rgba(255, 255, 255, 0.99);
                color: #111827;
                border: 1px solid rgba(225, 229, 237, 0.98);
            }
            QTabBar#MainTabBar::tab:hover:!selected {
                background: rgba(255, 255, 255, 0.56);
                color: #374151;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                width: 10px;
                background: transparent;
                margin: 8px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(148, 163, 184, 0.45);
                border-radius: 5px;
                min-height: 42px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
                background: transparent;
                border: none;
            }
            """
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        surface = CardFrame("Surface")
        root.addWidget(surface)

        layout = QVBoxLayout(surface)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        self.title_bar = self._build_title_bar()
        layout.addWidget(self.title_bar)

        tab_shell = CardFrame("TabShell")
        tab_shell_layout = QVBoxLayout(tab_shell)
        tab_shell_layout.setContentsMargins(16, 16, 16, 16)
        tab_shell_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setObjectName("MainTabBar")
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.addTab(self._wrap_scroll(self._build_overview_page()), "개요")
        self.tabs.addTab(self._wrap_scroll(self._build_window_page()), "창 설정")
        self.tabs.addTab(self._wrap_scroll(self._build_model_input_page()), "모델 설정")
        self.tabs.addTab(self._wrap_scroll(self._build_llm_page()), "LLM 설정")
        self.tabs.addTab(self._wrap_scroll(self._build_behavior_page()), "동작 설정")
        self.tabs.addTab(self._wrap_scroll(self._build_memory_panel()), "기억 관리")
        tab_shell_layout.addWidget(self.tabs)
        layout.addWidget(tab_shell, 1)

        layout.addWidget(self._build_footer_note())

    def _build_title_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(68)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)

        title = QLabel("ENE 설정")
        title.setObjectName("WindowTitle")
        layout.addWidget(title)
        layout.addWidget(self._pill("실시간 미리보기", "BluePill"))
        layout.addStretch()

        reset_btn = self._button("기본값 복원")
        layout.addWidget(reset_btn)

        save_btn = self._button("변경사항 저장", accent=True)
        layout.addWidget(save_btn)

        close_btn = self._button("×", popup=False)
        close_btn.setProperty("ghost", True)
        close_btn.style().unpolish(close_btn)
        close_btn.style().polish(close_btn)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        return bar

    def _build_header(self) -> QWidget:
        card = CardFrame("AccentCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._pill("설정 홈", "BluePill"), alignment=Qt.AlignmentFlag.AlignLeft)

        eyebrow = QLabel("창, 모델, 대화, 기억 관련 동작을 한곳에서 관리합니다")
        eyebrow.setObjectName("Eyebrow")
        left.addWidget(eyebrow)

        title = QLabel("설정")
        title.setObjectName("HeroTitle")
        left.addWidget(title)

        body = QLabel("자주 바꾸는 항목은 각 탭의 상단에서 바로 확인할 수 있고, 세부 값은 카드 안에서 순서대로 조정할 수 있습니다. 저장하기 전까지는 미리보기로만 반영됩니다.")
        body.setObjectName("Body")
        body.setWordWrap(True)
        left.addWidget(body)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        meta_row.addWidget(self._pill("설정 검색", "Pill"))
        meta_row.addWidget(self._pill("실시간 미리보기", "Pill"))
        meta_row.addWidget(self._pill("안전한 취소", "Pill"))
        meta_row.addStretch()
        left.addLayout(meta_row)

        layout.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._pill("마지막 저장 오늘 00:12", "MutedPill"), alignment=Qt.AlignmentFlag.AlignRight)

        search = QLineEdit()
        search.setPlaceholderText("설정 항목, 모델명, 기억 태그 검색")
        right.addWidget(search)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch()
        action_row.addWidget(self._button("기본값 복원"))
        action_row.addWidget(self._button("변경사항 저장", accent=True))
        right.addLayout(action_row)

        layout.addLayout(right)
        return card

    def _build_overview_page(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(
            self._section_header(
                "개요",
                "현재 상태와 자주 쓰는 액션만 먼저 모아 둔 시작 화면입니다.",
            )
        )

        top_grid = QGridLayout()
        top_grid.setHorizontalSpacing(12)
        top_grid.setVerticalSpacing(12)
        top_grid.addWidget(self._metric_card("창 상태", "우측 하단", "400 x 600"), 0, 0)
        top_grid.addWidget(self._metric_card("모델 배치", "1.00x", "X 50% · Y 50%"), 0, 1)
        top_grid.addWidget(self._metric_card("LLM", "gemini", "gemini-3-flash-preview"), 0, 2)
        top_grid.addWidget(self._metric_card("기억 정책", "10개 요약", "중요 3 · 유사 3 · 최근 2"), 0, 3)
        layout.addLayout(top_grid)

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(14)
        summary_grid.setVerticalSpacing(14)
        summary_grid.addWidget(
            self._detail_card(
                "현재 세션 요약",
                "자주 바뀌는 값만 추려서 시작 화면에서 바로 확인할 수 있게 했습니다.",
                [("창 위치", "X 100 · Y 100"), ("PTT 단축키", "Alt"), ("입력 중 TTS 끊기", "활성화")],
                ("창 설정 열기", "동작 설정 열기"),
            ),
            0,
            0,
        )
        summary_grid.addWidget(
            self._detail_card(
                "기억 회수 요약",
                "기억 관리 창에 있는 자동 요약 기준과 검색 파라미터를 그대로 요약합니다.",
                [("자동 요약", "대화 10개 이상"), ("최소 유사도", "35%"), ("중요 기억", "최대 3개")],
                ("기억 탭 열기", "사용자 정보 보기"),
            ),
            0,
            1,
        )
        layout.addLayout(summary_grid)
        layout.addStretch(1)
        return wrapper

    def _build_window_page(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(
            self._section_header(
                "창 설정",
                "창 위치와 크기, 배치 프리셋을 빠르게 조정할 수 있는 탭입니다.",
            )
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(
            self._detail_card(
                "창 위치",
                "X/Y 좌표와 위치 프리셋을 빠르게 조정할 수 있도록 정리했습니다.",
                [("X 좌표", "100 px"), ("Y 좌표", "100 px"), ("빠른 위치", "중앙 · 우측 하단 · 좌측 하단")],
                ("화면 중앙", "좌측 하단"),
            ),
            0,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "창 크기",
                "현재 창 너비/높이 스핀박스 흐름을 유지하되 결과를 먼저 읽기 쉽게 정리합니다.",
                [("너비", "400 px"), ("높이", "600 px"), ("범위", "200~3840 / 200~2160")],
                ("기본값 복원", "실시간 미리보기"),
            ),
            0,
            1,
        )
        grid.addWidget(
            self._detail_card(
                "위치 프리셋",
                "기존 버튼을 그대로 유지하되 설명을 붙여 초보자도 의미를 알 수 있게 한 영역입니다.",
                [("화면 중앙", "기준점 재정렬"), ("우측 하단", "방송/오버레이용"), ("좌측 하단", "작업공간 여유")],
                ("프리셋 비교", "현재 배치 저장"),
            ),
            1,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "실시간 반영",
                "설정 창은 저장 전 미리보기가 가능하므로, 적용 방식과 복구 흐름을 함께 보여줍니다.",
                [("미리보기", "저장 전 반영"), ("저장", "현재 값 확정"), ("취소", "원래 값 복구")],
                ("저장 방식 보기", "취소 흐름 보기"),
            ),
            1,
            1,
        )
        layout.addLayout(grid)
        layout.addStretch(1)
        return wrapper

    def _build_model_input_page(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(
            self._section_header(
                "모델 설정",
                "모델 크기와 위치를 직관적으로 조정할 수 있도록 배치한 탭입니다.",
            )
        )

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        metrics.addWidget(self._metric_card("모델 스케일", "1.00x", "0.10x ~ 2.00x"), 0, 0)
        metrics.addWidget(self._metric_card("X 위치", "50%", "-100% ~ 200%"), 0, 1)
        metrics.addWidget(self._metric_card("Y 위치", "50%", "-100% ~ 200%"), 0, 2)
        metrics.addWidget(self._metric_card("빠른 위치", "중앙", "좌측 · 우측 프리셋"), 0, 3)
        layout.addLayout(metrics)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(
            self._detail_card(
                "Live2D 배치",
                "스케일 입력과 슬라이더, 위치 슬라이더 2개가 서로 연동되도록 구성한 영역입니다.",
                [("스케일", "스핀박스 + 슬라이더 연동"), ("X 위치", "라벨 실시간 갱신"), ("Y 위치", "라벨 실시간 갱신")],
                ("위치 미세조정", "기본값 복원"),
            ),
            0,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "위치 프리셋",
                "현재 모델 위치를 중앙, 좌측, 우측으로 빠르게 이동시키는 버튼 그룹입니다.",
                [("중앙", "50, 50"), ("좌측", "25, 50"), ("우측", "75, 50")],
                ("중앙으로", "우측으로"),
            ),
            0,
            1,
        )
        grid.addWidget(
            self._detail_card(
                "가시적 피드백",
                "X/Y 값은 백분율 라벨로 즉시 보이고, 사용자는 숫자보다 배치 결과를 먼저 이해하게 됩니다.",
                [("X 라벨", "50%"), ("Y 라벨", "50%"), ("업데이트 방식", "슬라이더 이동 즉시 반영")],
                ("라벨 스타일", "미리보기 연결"),
            ),
            1,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "탭 구성 원칙",
                "모델 설정 탭은 배치와 크기 조정에 집중하도록 단순하게 유지합니다.",
                [("포함 항목", "크기 · X · Y · 프리셋"), ("제외 항목", "PTT · 감정 · LLM"), ("목표", "조절 집중도 향상")],
                ("탭 범위 보기", "동작 탭 이동"),
            ),
            1,
            1,
        )
        layout.addLayout(grid)
        layout.addStretch(1)
        return wrapper

    def _build_llm_page(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(
            self._section_header(
                "LLM 설정",
                "LLM 공급자와 모델, 파라미터, Custom API 연동을 관리하는 탭입니다.",
            )
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(
            self._detail_card(
                "LLM 공급자",
                "공급자 콤보박스를 기준으로 API 키, 모델, 모델별 파라미터가 함께 바뀌는 흐름입니다.",
                [("공급자", "gemini"), ("표시 형식", "display_name (provider)"), ("모델 키 관리", "provider별 별도 저장")],
                ("공급자 변경", "키 상태 보기"),
            ),
            0,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "모델 및 파라미터",
                "모델명 입력과 Temperature / Top P / Max Tokens를 한 그룹으로 묶습니다.",
                [("모델", "gemini-3-flash-preview"), ("Temperature", "0.90"), ("Top P / Max Tokens", "1.00 / 2048")],
                ("모델 변경", "기본값 비교"),
            ),
            0,
            1,
        )
        grid.addWidget(
            self._detail_card(
                "Custom API",
                "custom_api 공급자를 선택했을 때만 URL, 키/패스워드, 요청 모델, 포맷을 펼쳐 보여줍니다.",
                [("URL", "chat/completions 엔드포인트"), ("키/패스워드", "비밀값 분리 저장"), ("포맷", "OpenAI Compatible 등")],
                ("Custom API 보기", "포맷 선택"),
            ),
            1,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "반영 방식",
                "일부 LLM 설정은 저장 후 앱을 다시 시작해야 완전히 반영됩니다.",
                [("저장 방식", "provider별 모델/키 유지"), ("주의 문구", "재시작 후 완전 반영"), ("비밀값", "api_keys.json 분리")],
                ("적용 흐름 보기", "안내 문구 강조"),
            ),
            1,
            1,
        )
        layout.addLayout(grid)
        layout.addStretch(1)
        return wrapper

    def _build_settings_panel(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = self._section_header(
            "설정 스튜디오",
            "창 배치, 입력, 모델, 행동 제어를 카드 단위로 재배치한 영역입니다.",
        )
        layout.addWidget(header)

        summary_card = CardFrame("Card")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(22, 22, 22, 22)
        summary_layout.setSpacing(14)
        summary_layout.addWidget(self._pill("빠른 요약", "MutedPill"), alignment=Qt.AlignmentFlag.AlignLeft)

        summary_title = QLabel("지금의 ENE 상태를 먼저 보여주는 설정 홈")
        summary_title.setObjectName("CardTitle")
        summary_layout.addWidget(summary_title)

        summary_body = QLabel("설정 세부값을 찾으러 탭을 옮기기 전에, 창 위치, 음성 입력, 모델 라우팅, 분위기 제어를 먼저 한눈에 확인하도록 구성했습니다.")
        summary_body.setObjectName("Body")
        summary_body.setWordWrap(True)
        summary_layout.addWidget(summary_body)

        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(12)
        metric_grid.setVerticalSpacing(12)
        metric_grid.addWidget(self._metric_card("창 프리셋", "우측 하단", "400 x 600"), 0, 0)
        metric_grid.addWidget(self._metric_card("음성 입력", "한국어", "small · int8"), 0, 1)
        metric_grid.addWidget(self._metric_card("모델", "Gemini", "3 Flash Preview"), 1, 0)
        metric_grid.addWidget(self._metric_card("행동 시스템", "활성화", "감정 + 자리비움"), 1, 1)
        summary_layout.addLayout(metric_grid)
        layout.addWidget(summary_card)

        settings_grid = QGridLayout()
        settings_grid.setHorizontalSpacing(14)
        settings_grid.setVerticalSpacing(14)
        settings_grid.addWidget(
            self._detail_card(
                "레이아웃",
                "창 위치와 Live2D 배치를 한 카드 안에 묶었습니다.",
                [("창 좌표", "100, 100"), ("창 크기", "400 x 600"), ("모델 위치", "X 50% · Y 50%")],
                ("화면 중앙", "우측 하단"),
            ),
            0,
            0,
        )
        settings_grid.addWidget(
            self._detail_card(
                "대화 입력",
                "핫키와 음성 입력 설정을 바로 테스트 가능한 형태로 정리했습니다.",
                [("글로벌 PTT", "Alt"), ("STT 언어", "ko"), ("입력 중 TTS 중단", "활성화")],
                ("마이크 감도", "입력 미리듣기"),
            ),
            0,
            1,
        )
        settings_grid.addWidget(
            self._detail_card(
                "행동 및 감정",
                "캐릭터 반응 관련 토글을 상태 설명과 함께 노출합니다.",
                [("마우스 추적", "켜짐"), ("Idle motion", "강도 1.0 · 속도 1.0"), ("기분 업데이트", "normal")],
                ("자리비움 알림", "표현 프리셋"),
            ),
            1,
            0,
        )
        settings_grid.addWidget(
            self._detail_card(
                "모델 라우팅",
                "LLM 공급자와 모델 파라미터를 대화형 요약으로 보여줍니다.",
                [("공급자", "gemini"), ("모델", "gemini-3-flash-preview"), ("temperature", "0.9 · top_p 1.0")],
                ("모델 변경", "API 상태"),
            ),
            1,
            1,
        )
        layout.addLayout(settings_grid)
        layout.addStretch(1)
        return wrapper

    def _build_memory_panel(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = self._section_header(
            "기억 아카이브",
            "검색, 통계, 회수 튜닝, 항목 상세를 세로 스캔이 쉬운 구조로 재배치했습니다.",
        )
        layout.addWidget(header)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(12)
        stats_grid.setVerticalSpacing(12)
        stats_grid.addWidget(self._metric_card("총 기억", "12,842", "+184 이번 주"), 0, 0)
        stats_grid.addWidget(self._metric_card("중요 기억", "92", "보존 비율 0.7%"), 0, 1)
        stats_grid.addWidget(self._metric_card("임베딩 커버리지", "97%", "12,461개 연결"), 0, 2)
        stats_grid.addWidget(self._metric_card("자동 요약 기준", "10개", "대화 단위"), 0, 3)
        layout.addLayout(stats_grid)

        filter_card = CardFrame("Card")
        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(22, 20, 22, 20)
        filter_layout.setSpacing(14)

        filter_top = QHBoxLayout()
        filter_top.setSpacing(12)
        search = QLineEdit()
        search.setPlaceholderText("기억 제목, 요약, 태그 검색")
        filter_top.addWidget(search, 1)
        filter_top.addWidget(self._button("중요만"))
        filter_top.addWidget(self._button("최근순", accent=True))
        filter_layout.addLayout(filter_top)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(10)
        chip_row.addWidget(self._pill("태그: 방송", "TagPill"))
        chip_row.addWidget(self._pill("태그: UX", "TagPill"))
        chip_row.addWidget(self._pill("유사도 35% 이상", "TagPill"))
        chip_row.addWidget(self._pill("최근 기억 2개", "TagPill"))
        chip_row.addStretch()
        filter_layout.addLayout(chip_row)
        layout.addWidget(filter_card)

        lower_grid = QGridLayout()
        lower_grid.setHorizontalSpacing(14)
        lower_grid.setVerticalSpacing(14)
        lower_grid.addWidget(self._memory_list_card(), 0, 0, 2, 2)
        lower_grid.addWidget(self._inspector_card(), 0, 2)
        lower_grid.addWidget(self._retrieval_card(), 1, 2)
        lower_grid.setColumnStretch(0, 1)
        lower_grid.setColumnStretch(1, 1)
        lower_grid.setColumnStretch(2, 1)
        layout.addLayout(lower_grid, 1)
        return wrapper

    def _build_behavior_page(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(
            self._section_header(
                "동작 설정",
                "표시 요소, 전역 PTT, 노트, 유휴 모션, 감정 반응, 자리 비움 감지를 관리하는 탭입니다.",
            )
        )

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        metrics.addWidget(self._metric_card("UI 토글", "6개", "드래그 바 · 리롤 · 수정 · 요약 · 노트 · 기분"), 0, 0)
        metrics.addWidget(self._metric_card("전역 PTT", "활성화", "Alt · TTS 중단"), 0, 1)
        metrics.addWidget(self._metric_card("유휴 모션", "1.0x", "강도 1.0 · 속도 1.0"), 0, 2)
        metrics.addWidget(self._metric_card("자리 비움", "60분", "민감도 3.0%"), 0, 3)
        layout.addLayout(metrics)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(
            self._detail_card(
                "표시 요소 토글",
                "표시 요소와 버튼 토글을 한눈에 확인할 수 있도록 묶었습니다.",
                [("드래그 바", "표시"), ("최근 리롤/수정", "표시"), ("수동 요약/노트/기분", "표시")],
                ("노출 조정", "버튼 우선순위"),
            ),
            0,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "음성 입력 (전역 PTT)",
                "전역 PTT 활성화, PTT 시작 시 음성 출력 끊기, 단축키 캡처 흐름을 그대로 유지합니다.",
                [("전역 PTT", "활성화"), ("단축키", "Alt"), ("안내 문구", "누르고 있는 동안만 녹음")],
                ("단축키 설정", "기본값 복원"),
            ),
            0,
            1,
        )
        grid.addWidget(
            self._detail_card(
                "노트 설정",
                "/note 명령에 최근 대화 맥락을 자동 주입할지와 주입 턴 수를 설정하는 그룹입니다.",
                [("최근 맥락 주입", "비활성화"), ("주입 턴 수", "4턴"), ("0 값 의미", "전체 세션")],
                ("노트 흐름 보기", "주입 범위 조정"),
            ),
            1,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "유휴 모션",
                "유휴 모션 활성화, 다이나믹 모드, 강도, 속도를 한 그룹에서 조정합니다.",
                [("활성화", "켜짐"), ("강도", "1.0x"), ("속도", "1.0x")],
                ("강도 조절", "다이나믹 모드"),
            ),
            1,
            1,
        )
        grid.addWidget(
            self._detail_card(
                "머리 쓰다듬기",
                "강도, 페이드, 감정 기본값/커스텀값, 유지 시간을 한 그룹으로 구성합니다.",
                [("강도", "1.0x"), ("페이드", "180ms / 220ms"), ("감정", "eyeclose → shy · 5초")],
                ("감정 미리보기", "커스텀 감정"),
            ),
            2,
            0,
        )
        grid.addWidget(
            self._detail_card(
                "자리 비움/유휴 감지",
                "자동 말걸기, 유휴 시간, 화면 차이 민감도, 추가 재실행 횟수를 같은 문맥으로 묶습니다.",
                [("자동 말걸기", "활성화"), ("유휴 시간", "60분"), ("민감도/재시도", "3.0% / 0회")],
                ("민감도 조정", "재실행 횟수"),
            ),
            2,
            1,
        )
        layout.addLayout(grid)
        layout.addStretch(1)
        return wrapper

    def _memory_list_card(self) -> QWidget:
        card = CardFrame("ListCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.addWidget(self._pill("기억 목록", "MutedPill"))
        top.addStretch()
        top.addWidget(self._button("정렬"))
        top.addWidget(self._button("새로고침"))
        layout.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)
        self._memory_list_layout = container_layout
        self._rebuild_memory_list()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        return card

    def _inspector_card(self) -> QWidget:
        card = CardFrame("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        layout.addWidget(self._pill("선택된 기억", "BluePill"), alignment=Qt.AlignmentFlag.AlignLeft)

        self._inspector_title_label = QLabel()
        self._inspector_title_label.setObjectName("CardTitle")
        layout.addWidget(self._inspector_title_label)

        self._inspector_body_label = QLabel()
        self._inspector_body_label.setObjectName("Body")
        self._inspector_body_label.setWordWrap(True)
        layout.addWidget(self._inspector_body_label)

        tags = QHBoxLayout()
        tags.setSpacing(8)
        self._inspector_tags_layout = tags
        layout.addLayout(tags)

        time_row, self._inspector_time_value = self._key_value_row("기억 시각")
        layout.addWidget(time_row)
        source_row, self._inspector_source_value = self._key_value_row("원문 개수")
        layout.addWidget(source_row)
        importance_row, self._inspector_importance_value = self._key_value_row("중요 여부")
        layout.addWidget(importance_row)
        priority_row, self._inspector_priority_value = self._key_value_row("회수 우선순위")
        layout.addWidget(priority_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self._inspector_primary_button = self._button("중요 표시", accent=True, popup=False)
        self._inspector_primary_button.clicked.connect(self._toggle_selected_memory_importance)
        action_row.addWidget(self._inspector_primary_button)

        delete_btn = self._button("기억 삭제", popup=False)
        delete_btn.clicked.connect(self._show_delete_memory_popup)
        action_row.addWidget(delete_btn)
        layout.addLayout(action_row)

        user_info_btn = self._button("사용자 정보 관리", popup=False)
        user_info_btn.clicked.connect(lambda: self._show_action_popup("사용자 정보 관리"))
        layout.addWidget(user_info_btn)
        layout.addStretch(1)
        self._refresh_memory_selection()
        return card

    def _retrieval_card(self) -> QWidget:
        card = CardFrame("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("회수 튜닝")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        body = QLabel("원래 기억 관리 창에 있던 자동 요약과 검색 파라미터를 여기서 바로 조정할 수 있도록 실제 설정 항목 형태로 정리했습니다.")
        body.setObjectName("Body")
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addWidget(
            self._spin_setting_row(
                "대화 N개 이상 시 자동 요약",
                "기억이 누적된 대화 묶음이 이 값을 넘으면 자동 요약을 실행합니다.",
                10,
                2,
                100,
                "개",
            )
        )
        layout.addWidget(
            self._spin_setting_row(
                "최대 중요 기억",
                "회수 시 항상 우선 검토할 중요 기억의 최대 개수입니다.",
                3,
                0,
                20,
                "개",
            )
        )
        layout.addWidget(
            self._spin_setting_row(
                "최대 유사 기억",
                "현재 입력과 의미가 가까운 기억을 몇 개까지 가져올지 결정합니다.",
                3,
                0,
                20,
                "개",
            )
        )
        layout.addWidget(
            self._spin_setting_row(
                "최대 최근 기억",
                "유사도와 별개로 최근 맥락을 몇 개까지 보조로 포함할지 정합니다.",
                2,
                0,
                20,
                "개",
            )
        )
        layout.addWidget(
            self._spin_setting_row(
                "최소 유사도",
                "이 값보다 낮은 기억은 유사 기억 후보에서 제외합니다.",
                35,
                1,
                100,
                "%",
            )
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addWidget(self._button("기본값 복원"))
        action_row.addWidget(self._button("튜닝 값 임시 저장", accent=True))
        layout.addLayout(action_row)
        layout.addStretch(1)
        return card

    def _build_footer_note(self) -> QWidget:
        card = CardFrame("Card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(6)
        title = QLabel("설정 적용 안내")
        title.setObjectName("CardTitle")
        left.addWidget(title)

        body = QLabel("변경사항은 저장 전까지 미리보기로만 적용됩니다. 취소하면 이전 설정으로 돌아가며, 일부 LLM 관련 설정은 저장 후 다시 시작해야 완전히 반영됩니다.")
        body.setObjectName("Body")
        body.setWordWrap(True)
        left.addWidget(body)
        layout.addLayout(left, 1)
        return card

    def _section_header(self, title_text: str, description: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        body = QLabel(description)
        body.setObjectName("Body")
        body.setWordWrap(True)
        layout.addWidget(body)
        return widget

    def _metric_card(self, label_text: str, value_text: str, detail_text: str) -> QWidget:
        card = CardFrame("MetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("MetricLabel")
        layout.addWidget(label)

        value = QLabel(value_text)
        value.setObjectName("MetricValue")
        layout.addWidget(value)

        detail = QLabel(detail_text)
        detail.setObjectName("Body")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        return card

    def _detail_card(
        self,
        title_text: str,
        body_text: str,
        entries: list[tuple[str, str]],
        actions: tuple[str, str],
    ) -> QWidget:
        card = CardFrame("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)

        title = QLabel(title_text)
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        body = QLabel(body_text)
        body.setObjectName("Body")
        body.setWordWrap(True)
        layout.addWidget(body)

        for label_text, value_text in entries:
            layout.addWidget(self._key_value(label_text, value_text))

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self._button(actions[0], accent=True))
        button_row.addWidget(self._button(actions[1]))
        layout.addLayout(button_row)
        layout.addStretch(1)
        return card

    def _spin_setting_row(
        self,
        title_text: str,
        body_text: str,
        value: int,
        minimum: int,
        maximum: int,
        suffix: str,
    ) -> QWidget:
        card = CardFrame("Card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)

        title = QLabel(title_text)
        title.setObjectName("KeyValueValue")
        text_column.addWidget(title)

        body = QLabel(body_text)
        body.setObjectName("Body")
        body.setWordWrap(True)
        text_column.addWidget(body)
        layout.addLayout(text_column, 1)

        spinbox = QSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setValue(value)
        spinbox.setSuffix(suffix)
        layout.addWidget(spinbox)
        return card

    def _memory_item(self, memory: PrototypeMemory, index: int) -> QWidget:
        card = MemoryItemFrame(lambda idx=index: self._select_memory(idx))
        card.setProperty("selected", "true" if index == self._selected_memory_index else "false")
        card.style().unpolish(card)
        card.style().polish(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self._pill(memory.timestamp, "MutedPill"))
        if memory.important:
            top.addWidget(self._pill("중요", "BluePill"))
        top.addStretch()
        layout.addLayout(top)

        title = QLabel(memory.title)
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        summary = QLabel(memory.summary)
        summary.setObjectName("Body")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        tags = QHBoxLayout()
        tags.setSpacing(8)
        for tag in memory.tags:
            tags.addWidget(self._pill(tag, "TagPill"))
        tags.addStretch()
        layout.addLayout(tags)
        return card

    def _key_value_row(self, key_text: str) -> tuple[QWidget, QLabel]:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        key = QLabel(key_text)
        key.setObjectName("KeyValueLabel")
        layout.addWidget(key)
        layout.addStretch()

        value = QLabel("")
        value.setObjectName("KeyValueValue")
        layout.addWidget(value)
        return widget, value

    def _key_value(self, key_text: str, value_text: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        key = QLabel(key_text)
        key.setObjectName("KeyValueLabel")
        layout.addWidget(key)

        layout.addStretch()

        value = QLabel(value_text)
        value.setObjectName("KeyValueValue")
        layout.addWidget(value)
        return widget

    def _pill(self, text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    def _action_popup_spec(self, text: str) -> tuple[str, str]:
        specs = {
            "공급자 변경": (
                "공급자 변경",
                "여기서는 Gemini, OpenAI, Anthropic, OpenRouter, DeepSeek, Ollama, Custom API 목록과 현재 공급자별 모델 매핑 상태를 보여주는 팝업이 열립니다.",
            ),
            "키 상태 보기": (
                "API 키 상태",
                "공급자별 키 저장 여부와 비밀값 분리 저장 상태를 확인합니다. 저장된 값은 마스킹된 형태로 표시됩니다.",
            ),
            "단축키 설정": (
                "PTT 단축키 설정",
                "이 팝업에서 키를 직접 눌러 Alt, Ctrl+Alt 같은 조합을 캡처하고 바로 적용할 수 있습니다.",
            ),
            "기본값 복원": (
                "기본값 복원",
                "선택한 설정 그룹만 기본값으로 되돌릴지, 전체를 되돌릴지 확인하는 시트를 띄우는 흐름입니다.",
            ),
            "Custom API 보기": (
                "Custom API 설정",
                "URL, 키 또는 패스워드, 요청 모델, 포맷 선택을 한 번에 확인하는 보조 팝업입니다.",
            ),
            "감정 미리보기": (
                "감정 미리보기",
                "머리 쓰다듬기 중 감정과 종료 감정을 빠르게 테스트해 보는 팝업입니다.",
            ),
            "기억 탭 열기": (
                "기억 관리 이동",
                "자동 요약 기준, 유사도, 중요 기억 개수 같은 핵심 파라미터를 요약해서 보여준 뒤 기억 관리 탭으로 이동합니다.",
            ),
            "사용자 정보 보기": (
                "사용자 정보 관리",
                "저장된 사용자 프로필 요약과 편집 진입점을 보여줍니다.",
            ),
            "사용자 정보 관리": (
                "사용자 정보 관리",
                "이 팝업에서 저장된 사용자 프로필 요약, 수정 항목, 최신 추출 시점을 한 번에 확인합니다.",
            ),
        }
        if text in specs:
            return specs[text]
        return (
            text,
            f"여기서는 `{text}`와 관련된 세부 설정 또는 확인 절차를 별도 팝업에서 안내합니다.",
        )

    def _show_action_popup(self, text: str) -> None:
        title_text, body_text = self._action_popup_spec(text)
        dialog = PrototypeActionDialog(title_text, body_text, self)
        dialog.exec()

    def _rebuild_memory_list(self) -> None:
        if self._memory_list_layout is None:
            return

        while self._memory_list_layout.count():
            item = self._memory_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._memory_cards = []

        if not self._memories:
            self._selected_memory_index = -1
            empty = QLabel("현재 표시할 기억이 없습니다.")
            empty.setObjectName("Body")
            self._memory_list_layout.addWidget(empty)
            self._memory_list_layout.addStretch(1)
            self._refresh_memory_selection()
            return

        self._selected_memory_index = max(0, min(self._selected_memory_index, len(self._memories) - 1))
        for index, memory in enumerate(self._memories):
            card = self._memory_item(memory, index)
            self._memory_cards.append(card)
            self._memory_list_layout.addWidget(card)
        self._memory_list_layout.addStretch(1)
        self._refresh_memory_selection()

    def _current_memory(self) -> PrototypeMemory | None:
        if 0 <= self._selected_memory_index < len(self._memories):
            return self._memories[self._selected_memory_index]
        return None

    def _select_memory(self, index: int) -> None:
        self._selected_memory_index = index
        self._refresh_memory_selection()

    def _refresh_memory_selection(self) -> None:
        for index, card in enumerate(self._memory_cards):
            card.setProperty("selected", "true" if index == self._selected_memory_index else "false")
            card.style().unpolish(card)
            card.style().polish(card)

        memory = self._current_memory()
        if self._inspector_title_label is None or self._inspector_body_label is None:
            return

        if memory is None:
            self._inspector_title_label.setText("선택된 기억이 없습니다")
            self._inspector_body_label.setText("왼쪽 목록에서 기억을 선택하면 상세 정보와 액션이 여기에 표시됩니다.")
            if self._inspector_time_value is not None:
                self._inspector_time_value.setText("-")
            if self._inspector_source_value is not None:
                self._inspector_source_value.setText("-")
            if self._inspector_importance_value is not None:
                self._inspector_importance_value.setText("-")
            if self._inspector_priority_value is not None:
                self._inspector_priority_value.setText("-")
            if self._inspector_primary_button is not None:
                self._inspector_primary_button.setText("중요 표시")
                self._inspector_primary_button.setEnabled(False)
            self._replace_inspector_tags(())
            return

        self._inspector_title_label.setText(memory.title)
        self._inspector_body_label.setText(memory.summary)
        if self._inspector_time_value is not None:
            self._inspector_time_value.setText(memory.timestamp)
        if self._inspector_source_value is not None:
            self._inspector_source_value.setText(f"{len(memory.tags) + 1}개 단서")
        if self._inspector_importance_value is not None:
            self._inspector_importance_value.setText("보존 대상" if memory.important else "일반 기억")
        if self._inspector_priority_value is not None:
            self._inspector_priority_value.setText("중요 > 유사 > 최근" if memory.important else "유사 > 최근")
        if self._inspector_primary_button is not None:
            self._inspector_primary_button.setText("중요 해제" if memory.important else "중요 표시")
            self._inspector_primary_button.setEnabled(True)
        self._replace_inspector_tags(memory.tags)

    def _replace_inspector_tags(self, tags: tuple[str, ...]) -> None:
        if self._inspector_tags_layout is None:
            return

        while self._inspector_tags_layout.count():
            item = self._inspector_tags_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for tag in tags:
            self._inspector_tags_layout.addWidget(self._pill(tag, "TagPill"))
        self._inspector_tags_layout.addStretch()

    def _toggle_selected_memory_importance(self) -> None:
        memory = self._current_memory()
        if memory is None:
            return
        self._memories[self._selected_memory_index] = replace(memory, important=not memory.important)
        self._rebuild_memory_list()

    def _show_delete_memory_popup(self) -> None:
        memory = self._current_memory()
        if memory is None:
            self._show_action_popup("기억 삭제")
            return
        dialog = PrototypeActionDialog(
            "기억 삭제",
            f"여기서는 `{memory.title}` 항목을 삭제할지 다시 확인하고, 삭제 후 되돌릴 수 없는 점을 안내합니다.",
            self,
        )
        dialog.exec()

    def _button(self, text: str, accent: bool = False, popup: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("accent", accent)
        button.style().unpolish(button)
        button.style().polish(button)
        if popup and text != "×":
            button.clicked.connect(lambda _checked=False, label=text: self._show_action_popup(label))
        return button

    def _wrap_scroll(self, content: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("TabScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 22, 20, 20)
        container_layout.setSpacing(0)
        container_layout.addWidget(content)
        scroll.setWidget(container)
        return scroll

    def _hit_test_resize_edge(self, pos: QPoint) -> str:
        margin = self._resize_margin
        left = pos.x() <= margin
        right = pos.x() >= self.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= self.height() - margin

        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return ""

    def _update_resize_cursor(self, pos: QPoint) -> None:
        edge = self._hit_test_resize_edge(pos)
        cursor_map = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursor_map.get(edge, Qt.CursorShape.ArrowCursor))

    def _apply_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._resize_start_global
        new_x = self._resize_start_pos.x()
        new_y = self._resize_start_pos.y()
        new_width = self._resize_start_size.width()
        new_height = self._resize_start_size.height()
        min_width = self.minimumWidth()
        min_height = self.minimumHeight()

        if "left" in self._resize_edge:
            new_x += delta.x()
            new_width -= delta.x()
            if new_width < min_width:
                new_x = self._resize_start_pos.x() + self._resize_start_size.width() - min_width
                new_width = min_width
        elif "right" in self._resize_edge:
            new_width = max(min_width, self._resize_start_size.width() + delta.x())

        if "top" in self._resize_edge:
            new_y += delta.y()
            new_height -= delta.y()
            if new_height < min_height:
                new_y = self._resize_start_pos.y() + self._resize_start_size.height() - min_height
                new_height = min_height
        elif "bottom" in self._resize_edge:
            new_height = max(min_height, self._resize_start_size.height() + delta.y())

        self.setGeometry(new_x, new_y, new_width, new_height)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            edge = self._hit_test_resize_edge(position)
            if edge:
                self._resize_active = True
                self._resize_edge = edge
                self._resize_start_global = event.globalPosition().toPoint()
                self._resize_start_pos = self.pos()
                self._resize_start_size = self.size()
                event.accept()
                return
            if self.title_bar.geometry().contains(position):
                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resize_active and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_active = False
        self._resize_active = False
        self._resize_edge = ""
        self.unsetCursor()
        super().mouseReleaseEvent(event)


def render_screenshot(output_path: str) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    ensure_preview_font()
    dialog = SettingsMemoryPrototypeDialog()
    dialog.show()
    app.processEvents()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    def save_and_quit() -> None:
        dialog.grab().save(str(output))
        app.quit()

    QTimer.singleShot(120, save_and_quit)
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ENE 설정 창 미리보기")
    parser.add_argument("--screenshot", help="PNG 스크린샷 저장 경로")
    args = parser.parse_args(argv)

    if args.screenshot and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication.instance() or QApplication(sys.argv)
    ensure_preview_font()

    if args.screenshot:
        return render_screenshot(args.screenshot)

    dialog = SettingsMemoryPrototypeDialog()
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
