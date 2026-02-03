"""
기억 관리 다이얼로그
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QLineEdit,
    QMessageBox, QWidget
)
from PyQt6.QtCore import Qt
from datetime import datetime


class MemoryDialog(QDialog):
    """기억 관리 다이얼로그"""
    
    def __init__(self, memory_manager, parent=None):
        super().__init__(parent)
        self.memory_manager = memory_manager
        
        self.setWindowTitle("ENE 기억 관리")
        self.setMinimumSize(600, 500)
        
        self._setup_ui()
        self._load_memories()
    
    def _setup_ui(self):
        """UI 구성"""
        layout = QVBoxLayout(self)
        
        # 상단: 통계 및 검색
        top_layout = QHBoxLayout()
        
        # 통계 레이블
        self.stats_label = QLabel()
        top_layout.addWidget(self.stats_label)
        
        top_layout.addStretch()
        
        # 검색창
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력...")
        self.search_input.textChanged.connect(self._on_search)
        top_layout.addWidget(self.search_input)
        
        search_btn = QPushButton("검색")
        search_btn.clicked.connect(self._on_search)
        top_layout.addWidget(search_btn)
        
        layout.addLayout(top_layout)
        
        # 중간: 기억 목록
        self.memory_list = QListWidget()
        self.memory_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.memory_list)
        
        # 하단: 버튼
        button_layout = QHBoxLayout()
        
        self.important_btn = QPushButton("⭐ 중요 표시")
        self.important_btn.clicked.connect(self._toggle_important)
        self.important_btn.setEnabled(False)
        button_layout.addWidget(self.important_btn)
        
        self.delete_btn = QPushButton("🗑️ 삭제")
        self.delete_btn.clicked.connect(self._delete_memory)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)
        
        button_layout.addStretch()
        
        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.clicked.connect(self._load_memories)
        button_layout.addWidget(refresh_btn)
        
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _load_memories(self):
        """기억 목록 로드"""
        self.memory_list.clear()
        
        if not self.memory_manager:
            return
        
        # 통계 업데이트
        stats = self.memory_manager.get_stats()
        self.stats_label.setText(
            f"총 {stats['total']}개 | "
            f"중요 {stats['important']}개 | "
            f"임베딩 {stats['with_embedding']}개"
        )
        
        # 시간순 정렬 (최신순)
        memories = sorted(
            self.memory_manager.memories,
            key=lambda m: m.timestamp,
            reverse=True
        )
        
        # 목록에 추가
        for memory in memories:
            item = QListWidgetItem()
            widget = self._create_memory_widget(memory)
            
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, memory.id)
            
            self.memory_list.addItem(item)
            self.memory_list.setItemWidget(item, widget)
    
    def _create_memory_widget(self, memory):
        """기억 항목 위젯 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 첫 줄: 시간 + 중요 표시
        first_line = QHBoxLayout()
        
        # 시간 (읽기 쉽게 포맷)
        try:
            dt = datetime.fromisoformat(memory.timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except:
            time_str = memory.timestamp[:16]
        
        time_label = QLabel(time_str)
        time_label.setStyleSheet("color: gray; font-size: 11px;")
        first_line.addWidget(time_label)
        
        if memory.is_important:
            important_label = QLabel("⭐ 중요")
            important_label.setStyleSheet("color: orange; font-weight: bold;")
            first_line.addWidget(important_label)
        
        first_line.addStretch()
        layout.addLayout(first_line)
        
        # 둘째 줄: 요약
        summary_label = QLabel(memory.summary)
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(summary_label)
        
        # 셋째 줄: 태그 (있으면)
        if memory.tags:
            tags_label = QLabel(" ".join([f"#{tag}" for tag in memory.tags]))
            tags_label.setStyleSheet("color: #0066cc; font-size: 11px;")
            layout.addWidget(tags_label)
        
        return widget
    
    def _on_selection_changed(self):
        """선택 변경 시"""
        has_selection = len(self.memory_list.selectedItems()) > 0
        self.important_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        
        # 중요 버튼 텍스트 업데이트
        if has_selection:
            selected_item = self.memory_list.selectedItems()[0]
            memory_id = selected_item.data(Qt.ItemDataRole.UserRole)
            
            # 해당 기억 찾기
            memory = next(
                (m for m in self.memory_manager.memories if m.id == memory_id),
                None
            )
            
            if memory:
                if memory.is_important:
                    self.important_btn.setText("⭐ 중요 해제")
                else:
                    self.important_btn.setText("⭐ 중요 표시")
    
    def _toggle_important(self):
        """중요 표시 토글"""
        if not self.memory_list.selectedItems():
            return
        
        selected_item = self.memory_list.selectedItems()[0]
        memory_id = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 해당 기억 찾기
        memory = next(
            (m for m in self.memory_manager.memories if m.id == memory_id),
            None
        )
        
        if memory:
            # 중요도 토글
            new_importance = not memory.is_important
            self.memory_manager.set_important(memory_id, new_importance)
            
            # 목록 새로고침
            self._load_memories()
    
    def _delete_memory(self):
        """기억 삭제"""
        if not self.memory_list.selectedItems():
            return
        
        # 확인 대화상자
        reply = QMessageBox.question(
            self,
            "삭제 확인",
            "선택한 기억을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        selected_item = self.memory_list.selectedItems()[0]
        memory_id = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 삭제
        self.memory_manager.delete(memory_id)
        
        # 목록 새로고침
        self._load_memories()
    
    def _on_search(self):
        """검색"""
        query = self.search_input.text().strip().lower()
        
        if not query:
            # 검색어가 없으면 전체 표시
            self._load_memories()
            return
        
        # 목록 필터링
        for i in range(self.memory_list.count()):
            item = self.memory_list.item(i)
            memory_id = item.data(Qt.ItemDataRole.UserRole)
            
            # 해당 기억 찾기
            memory = next(
                (m for m in self.memory_manager.memories if m.id == memory_id),
                None
            )
            
            if memory:
                # 요약이나 태그에서 검색
                matched = (
                    query in memory.summary.lower() or
                    any(query in tag.lower() for tag in memory.tags)
                )
                
                item.setHidden(not matched)
