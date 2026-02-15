"""
Calendar dialog.
Shows per-day conversation counts, head pat counts, and events.
"""
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CalendarDialog(QDialog):
    def __init__(self, calendar_manager, parent=None):
        super().__init__(parent)
        self.calendar_manager = calendar_manager

        self.setWindowTitle("ENE 캘린더")
        self.setMinimumSize(700, 500)

        self._setup_ui()
        self._load_calendar()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.calendar = QCalendarWidget()
        self.calendar.clicked.connect(self._on_date_selected)
        layout.addWidget(self.calendar)

        info_layout = QHBoxLayout()
        self.date_label = QLabel("날짜를 선택하세요")
        info_layout.addWidget(self.date_label)

        self.activity_label = QLabel("")
        info_layout.addWidget(self.activity_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)

        layout.addWidget(QLabel("일정:"))
        self.event_list = QListWidget()
        layout.addWidget(self.event_list)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_calendar(self):
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())

        for date_str, count in self.calendar_manager.conversation_counts.items():
            date = QDate.fromString(date_str, "yyyy-MM-dd")
            if not date.isValid():
                continue
            fmt = self.calendar.dateTextFormat(date)
            if count >= 10:
                fmt.setBackground(QColor(100, 150, 255, 150))
            elif count >= 5:
                fmt.setBackground(QColor(100, 150, 255, 80))
            elif count > 0:
                fmt.setBackground(QColor(100, 150, 255, 40))
            self.calendar.setDateTextFormat(date, fmt)

        for event in self.calendar_manager.events:
            date = QDate.fromString(event.date, "yyyy-MM-dd")
            if not date.isValid():
                continue
            fmt = self.calendar.dateTextFormat(date)
            fmt.setForeground(QColor(255, 200, 100))
            fmt.setFontWeight(700)
            self.calendar.setDateTextFormat(date, fmt)

    def _on_date_selected(self, date: QDate):
        date_str = date.toString("yyyy-MM-dd")
        self.date_label.setText(date.toString("yyyy년 MM월 dd일"))

        conversation_count = self.calendar_manager.get_conversation_count(date_str)
        head_pat_count = self.calendar_manager.get_head_pat_count(date_str)

        if conversation_count > 0 or head_pat_count > 0:
            self.activity_label.setText(f"💬 {conversation_count}회 | 🖐 {head_pat_count}회")
        else:
            self.activity_label.setText("")

        self.event_list.clear()
        events = self.calendar_manager.get_events_by_date(date_str)
        if not events:
            item = QListWidgetItem("일정이 없습니다")
            item.setForeground(QColor(150, 150, 150))
            self.event_list.addItem(item)
            return

        for event in events:
            item = QListWidgetItem()
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 5, 5, 5)

            checkbox = QCheckBox()
            checkbox.setChecked(event.completed)
            checkbox.toggled.connect(lambda checked, eid=event.id: self._on_event_toggled(eid, checked))
            row_layout.addWidget(checkbox)

            text_col = QVBoxLayout()
            title = QLabel(f"📌 {event.title}")
            if event.completed:
                title.setStyleSheet("font-weight: bold; color: gray; text-decoration: line-through;")
            else:
                title.setStyleSheet("font-weight: bold;")
            text_col.addWidget(title)

            if event.description:
                desc = QLabel(f"   {event.description}")
                if event.completed:
                    desc.setStyleSheet("color: gray; text-decoration: line-through;")
                else:
                    desc.setStyleSheet("color: gray;")
                text_col.addWidget(desc)

            source_text = "AI 자동 추출" if event.source == "ai_extracted" else "수동 입력"
            source_label = QLabel(f"   출처: {source_text}")
            source_label.setStyleSheet("color: #888; font-size: 10px;")
            text_col.addWidget(source_label)

            row_layout.addLayout(text_col, 1)

            delete_btn = QPushButton("✕")
            delete_btn.setFixedSize(30, 30)
            delete_btn.setStyleSheet(
                "QPushButton { background: rgba(255,100,100,0.3); border: none; border-radius: 15px; } "
                "QPushButton:hover { background: rgba(255,100,100,0.5); }"
            )
            delete_btn.clicked.connect(lambda checked, eid=event.id: self._on_event_deleted(eid))
            row_layout.addWidget(delete_btn)

            item.setSizeHint(row.sizeHint())
            self.event_list.addItem(item)
            self.event_list.setItemWidget(item, row)

    def _on_event_toggled(self, event_id: str, checked: bool):
        self.calendar_manager.toggle_event_completion(event_id)
        selected_date = self.calendar.selectedDate()
        self._on_date_selected(selected_date)
        self._load_calendar()

    def _on_event_deleted(self, event_id: str):
        reply = QMessageBox.question(
            self,
            "일정 삭제",
            "이 일정을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.calendar_manager.delete_event(event_id)
            selected_date = self.calendar.selectedDate()
            self._on_date_selected(selected_date)
            self._load_calendar()
