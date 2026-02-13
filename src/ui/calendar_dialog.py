"""
캘린더 다이얼로그
날짜별 대화 횟수 및 일정 표시
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCalendarWidget,
    QLabel, QListWidget, QPushButton, QListWidgetItem, QWidget, QCheckBox
)
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QTextCharFormat, QColor
from datetime import datetime


class CalendarDialog(QDialog):
    """캘린더 다이얼로그"""
    
    def __init__(self, calendar_manager, parent=None):
        super().__init__(parent)
        self.calendar_manager = calendar_manager
        
        self.setWindowTitle("ENE 캘린더")
        self.setMinimumSize(700, 500)
        
        self._setup_ui()
        self._load_calendar()
    
    def _setup_ui(self):
        """UI 구성"""
        layout = QVBoxLayout(self)
        
        # 캘린더 위젯
        self.calendar = QCalendarWidget()
        self.calendar.clicked.connect(self._on_date_selected)
        layout.addWidget(self.calendar)
        
        # 선택된 날짜 정보
        info_layout = QHBoxLayout()
        
        self.date_label = QLabel("날짜를 선택하세요")
        info_layout.addWidget(self.date_label)
        
        self.conv_count_label = QLabel("")
        info_layout.addWidget(self.conv_count_label)
        
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        # 일정 목록
        layout.addWidget(QLabel("일정:"))
        self.event_list = QListWidget()
        layout.addWidget(self.event_list)
        
        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    
    def _load_calendar(self):
        """캘린더에 대화 횟수 및 일정 표시"""
        # 대화가 있는 날짜 강조
        for date_str, count in self.calendar_manager.conversation_counts.items():
            try:
                date = QDate.fromString(date_str, "yyyy-MM-dd")
                
                # 대화 횟수에 따라 배경색 변경
                format = QTextCharFormat()
                if count >= 10:
                    format.setBackground(QColor(100, 150, 255, 150))
                elif count >= 5:
                    format.setBackground(QColor(100, 150, 255, 80))
                else:
                    format.setBackground(QColor(100, 150, 255, 40))
                
                self.calendar.setDateTextFormat(date, format)
            except:
                pass
        
        # 일정이 있는 날짜 표시
        for event in self.calendar_manager.events:
            try:
                date = QDate.fromString(event.date, "yyyy-MM-dd")
                format = self.calendar.dateTextFormat(date)
                format.setForeground(QColor(255, 200, 100))
                format.setFontWeight(700)
                self.calendar.setDateTextFormat(date, format)
            except:
                pass
    
    def _on_date_selected(self, date: QDate):
        """날짜 선택 시"""
        date_str = date.toString("yyyy-MM-dd")
        
        # 날짜 표시
        self.date_label.setText(date.toString("yyyy년 MM월 dd일"))
        
        # 대화 횟수 표시
        count = self.calendar_manager.get_conversation_count(date_str)
        if count > 0:
            self.conv_count_label.setText(f"💬 {count}회 대화")
        else:
            self.conv_count_label.setText("")
        
        # 일정 목록 표시
        self.event_list.clear()
        events = self.calendar_manager.get_events_by_date(date_str)
        
        if events:
            for event in events:
                item = QListWidgetItem()
                widget = QWidget()
                widget_layout = QHBoxLayout(widget)
                widget_layout.setContentsMargins(5, 5, 5, 5)
                
                # 체크박스
                checkbox = QCheckBox()
                checkbox.setChecked(event.completed)
                checkbox.setStyleSheet("QCheckBox { spacing: 5px; }")
                checkbox.toggled.connect(lambda checked, eid=event.id: self._on_event_toggled(eid, checked))
                widget_layout.addWidget(checkbox)
                
                # 일정 정보 (세로 레이아웃)
                info_layout = QVBoxLayout()
                info_layout.setSpacing(2)
                
                # 제목
                title_label = QLabel(f"📅 {event.title}")
                title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
                
                # 완료된 일정은 취소선
                if event.completed:
                    title_label.setStyleSheet("font-weight: bold; font-size: 13px; text-decoration: line-through; color: gray;")
                
                info_layout.addWidget(title_label)
                
                # 상세 설명
                if event.description:
                    desc_label = QLabel(f"   {event.description}")
                    desc_label.setStyleSheet("color: gray; font-size: 12px;")
                    if event.completed:
                        desc_label.setStyleSheet("color: gray; font-size: 12px; text-decoration: line-through;")
                    info_layout.addWidget(desc_label)
                
                # 출처
                source_text = "AI 자동 추출" if event.source == "ai_extracted" else "수동 입력"
                source_label = QLabel(f"   출처: {source_text}")
                source_label.setStyleSheet("color: #888; font-size: 10px;")
                info_layout.addWidget(source_label)
                
                widget_layout.addLayout(info_layout, 1)  # stretch factor 1
                
                # 삭제 버튼
                delete_btn = QPushButton("🗑️")
                delete_btn.setFixedSize(30, 30)
                delete_btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(255, 100, 100, 0.3);
                        border: none;
                        border-radius: 15px;
                        font-size: 14px;
                    }
                    QPushButton:hover {
                        background: rgba(255, 100, 100, 0.5);
                    }
                """)
                delete_btn.clicked.connect(lambda checked, eid=event.id: self._on_event_deleted(eid))
                widget_layout.addWidget(delete_btn)
                
                item.setSizeHint(widget.sizeHint())
                self.event_list.addItem(item)
                self.event_list.setItemWidget(item, widget)
        else:
            item = QListWidgetItem("일정이 없습니다")
            item.setForeground(QColor(150, 150, 150))
            self.event_list.addItem(item)
    
    def _on_event_toggled(self, event_id: str, checked: bool):
        """일정 완료 상태 토글"""
        self.calendar_manager.toggle_event_completion(event_id)
        # UI 새로고침
        selected_date = self.calendar.selectedDate()
        self._on_date_selected(selected_date)
        self._load_calendar()  # 캘린더 색상도 업데이트
    
    def _on_event_deleted(self, event_id: str):
        """일정 삭제"""
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self,
            "일정 삭제",
            "이 일정을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.calendar_manager.delete_event(event_id)
            # UI 새로고침
            selected_date = self.calendar.selectedDate()
            self._on_date_selected(selected_date)
            self._load_calendar()  # 캘린더 색상도 업데이트
