"""
기억 관리 다이얼로그
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QLineEdit,
    QMessageBox, QWidget, QSpinBox, QGroupBox
)
from PyQt6.QtCore import Qt
from datetime import datetime


class MemoryDialog(QDialog):
    """기억 관리 다이얼로그"""
    
    def __init__(self, memory_manager, bridge=None, parent=None):
        super().__init__(parent)
        self.memory_manager = memory_manager
        self.bridge = bridge  # WebBridge 참조
        
        self.setWindowTitle("ENE 기억 관리")
        self.setMinimumSize(600, 550)
        
        self._setup_ui()
        self._load_memories()
        self._load_settings()
    
    def _setup_ui(self):
        """UI 구성"""
        layout = QVBoxLayout(self)
        
        # === 자동 요약 설정 그룹 ===
        settings_group = QGroupBox("자동 요약 설정")
        settings_layout = QHBoxLayout(settings_group)
        
        settings_layout.addWidget(QLabel("대화"))
        
        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setMinimum(2)
        self.threshold_spinbox.setMaximum(100)
        self.threshold_spinbox.setValue(10)
        self.threshold_spinbox.setSuffix("개")
        self.threshold_spinbox.valueChanged.connect(self._on_threshold_changed)
        settings_layout.addWidget(self.threshold_spinbox)
        
        settings_layout.addWidget(QLabel("이상 시 자동 요약"))
        settings_layout.addStretch()
        
        layout.addWidget(settings_group)
        
        # === 기억 검색 설정 그룹 ===
        memory_settings_group = QGroupBox("기억 검색 설정")
        memory_settings_layout = QVBoxLayout(memory_settings_group)
        
        # 첫째 줄: 중요 기억 / 유사 기억
        row1 = QHBoxLayout()
        
        row1.addWidget(QLabel("최대 중요 기억:"))
        self.important_spinbox = QSpinBox()
        self.important_spinbox.setMinimum(0)
        self.important_spinbox.setMaximum(20)
        self.important_spinbox.setValue(3)
        self.important_spinbox.setSuffix("개")
        self.important_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        row1.addWidget(self.important_spinbox)
        
        row1.addSpacing(15)
        
        row1.addWidget(QLabel("최대 유사 기억:"))
        self.similar_spinbox = QSpinBox()
        self.similar_spinbox.setMinimum(0)
        self.similar_spinbox.setMaximum(20)
        self.similar_spinbox.setValue(3)
        self.similar_spinbox.setSuffix("개")
        self.similar_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        row1.addWidget(self.similar_spinbox)
        
        row1.addStretch()
        memory_settings_layout.addLayout(row1)
        
        # 둘째 줄: 최근 기억 / 최소 유사도
        row2 = QHBoxLayout()
        
        row2.addWidget(QLabel("최대 최근 기억:"))
        self.recent_spinbox = QSpinBox()
        self.recent_spinbox.setMinimum(0)
        self.recent_spinbox.setMaximum(20)
        self.recent_spinbox.setValue(2)
        self.recent_spinbox.setSuffix("개")
        self.recent_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        row2.addWidget(self.recent_spinbox)
        
        row2.addSpacing(15)
        
        row2.addWidget(QLabel("최소 유사도:"))
        self.similarity_spinbox = QSpinBox()
        self.similarity_spinbox.setMinimum(1)
        self.similarity_spinbox.setMaximum(100)
        self.similarity_spinbox.setValue(35)
        self.similarity_spinbox.setSuffix("%")
        self.similarity_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        row2.addWidget(self.similarity_spinbox)
        
        row2.addStretch()
        memory_settings_layout.addLayout(row2)
        
        layout.addWidget(memory_settings_group)
        
        # === 통계 및 검색 ===
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
        
        # 사용자 정보 관리 버튼
        profile_btn = QPushButton("👤 사용자 정보 관리")
        profile_btn.clicked.connect(self._show_profile_dialog)
        button_layout.addWidget(profile_btn)
        
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
    
    def _load_settings(self):
        """설정 로드"""
        if self.bridge:
            self.threshold_spinbox.setValue(self.bridge.summarize_threshold)
            
            # 기억 검색 설정 로드
            if hasattr(self.bridge, 'settings') and self.bridge.settings:
                config = self.bridge.settings.config
                self.important_spinbox.setValue(config.get('max_important_memories', 3))
                self.similar_spinbox.setValue(config.get('max_similar_memories', 3))
                self.similarity_spinbox.setValue(int(config.get('min_similarity', 0.35) * 100))
                self.recent_spinbox.setValue(config.get('max_recent_memories', 2))
    
    def _on_threshold_changed(self, value):
        """임계값 변경 시"""
        if self.bridge:
            self.bridge.summarize_threshold = value
            print(f"[Memory Dialog] 자동 요약 임계값: {value}개")
            
            # settings에도 저장
            if hasattr(self.bridge, 'settings') and self.bridge.settings:
                self.bridge.settings.config['summarize_threshold'] = value
                self.bridge.settings.save()
                print(f"[Memory Dialog] 설정 저장 완료")
    
    def _on_memory_setting_changed(self):
        """기억 검색 설정 변경 시"""
        if not self.bridge or not hasattr(self.bridge, 'settings') or not self.bridge.settings:
            return
        
        config = self.bridge.settings.config
        config['max_important_memories'] = self.important_spinbox.value()
        config['max_similar_memories'] = self.similar_spinbox.value()
        config['min_similarity'] = self.similarity_spinbox.value() / 100.0
        config['max_recent_memories'] = self.recent_spinbox.value()
        
        self.bridge.settings.save()
        
        print(f"[Memory Dialog] 기억 검색 설정 변경: "
              f"중요={config['max_important_memories']}, "
              f"유사={config['max_similar_memories']}, "
              f"유사도={config['min_similarity']:.2f}, "
              f"최근={config['max_recent_memories']}")

    
    def _show_profile_dialog(self):
        """사용자 정보 관리 다이얼로그 표시"""
        if not self.bridge or not hasattr(self.bridge, 'user_profile'):
            QMessageBox.warning(
                self,
                "프로필 없음",
                "사용자 프로필이 초기화되지 않았습니다."
            )
            return
        
        if not self.bridge.user_profile:
            QMessageBox.information(
                self,
                "프로필 정보 없음",
                "아직 저장된 마스터 정보가 없습니다.\n대화를 나누면 자동으로 정보가 추출됩니다."
            )
            return
        
        from src.ui.profile_dialog import ProfileDialog
        dialog = ProfileDialog(self.bridge.user_profile, self)
        dialog.exec()
