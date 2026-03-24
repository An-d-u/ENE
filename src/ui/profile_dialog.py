"""
사용자 프로필 관리 다이얼로그
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt
from datetime import datetime

from ..core.i18n import tr as t


class ProfileDialog(QDialog):
    """사용자 프로필 관리 다이얼로그"""
    
    def __init__(self, user_profile, parent=None):
        super().__init__(parent)
        self.user_profile = user_profile
        
        self.setWindowTitle(t("profile.window.title"))
        self.setMinimumSize(600, 500)
        
        self._setup_ui()
        self._load_profile()
    
    def _setup_ui(self):
        """UI 구성"""
        layout = QVBoxLayout(self)
        
        # 상단: 통계
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel()
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)
        
        # 중간: 프로필 목록
        self.profile_list = QListWidget()
        self.profile_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.profile_list)
        
        # 하단: 버튼
        button_layout = QHBoxLayout()
        
        self.delete_btn = QPushButton(t("profile.button.delete"))
        self.delete_btn.clicked.connect(self._delete_fact)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)
        
        button_layout.addStretch()
        
        self.refresh_btn = QPushButton(t("profile.button.refresh"))
        self.refresh_btn.clicked.connect(self._load_profile)
        button_layout.addWidget(self.refresh_btn)
        
        self.close_btn = QPushButton(t("profile.button.close"))
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def _load_profile(self):
        """프로필 목록 로드"""
        self.profile_list.clear()
        
        if self.user_profile is None:
            return
        
        # 통계 업데이트
        total_facts = len(self.user_profile.facts)
        basic_count = len([k for k, v in self.user_profile.basic_info.items() if v])
        likes_count = len(self.user_profile.preferences.get('likes', []))
        
        self.stats_label.setText(
            t(
                "profile.stats.summary",
                basic_count=basic_count,
                fact_count=total_facts,
                likes_count=likes_count,
            )
        )
        
        # 1. 기본 정보 표시
        if self.user_profile.basic_info:
            self._add_basic_info_section()
        
        # 2. 취미/선호도 표시
        if self.user_profile.preferences.get('likes'):
            self._add_preferences_section()
        
        # 3. 자동 추출된 정보 표시
        if self.user_profile.facts:
            self._add_facts_section()
        
        # 아무것도 없으면
        if not self.user_profile.basic_info and not self.user_profile.facts:
            item = QListWidgetItem(t("profile.empty"))
            self.profile_list.addItem(item)
    
    def _add_basic_info_section(self):
        """기본 정보 섹션 추가"""
        # 헤더
        header_item = QListWidgetItem(t("profile.section.basic"))
        header_item.setBackground(Qt.GlobalColor.lightGray)
        self.profile_list.addItem(header_item)
        
        basic = self.user_profile.basic_info
        info_lines = []
        
        if basic.get('name'):
            info_lines.append(f"{t('profile.field.name')}: {basic['name']}")
        if basic.get('gender'):
            info_lines.append(f"{t('profile.field.gender')}: {basic['gender']}")
        if basic.get('birthday'):
            info_lines.append(f"{t('profile.field.birthday')}: {basic['birthday']}")
        if basic.get('occupation'):
            info_lines.append(f"{t('profile.field.occupation')}: {basic['occupation']}")
        if basic.get('major'):
            info_lines.append(f"{t('profile.field.major')}: {basic['major']}")
        if basic.get('location'):
            info_lines.append(f"{t('profile.field.location')}: {basic['location']}")
        
        for line in info_lines:
            item = QListWidgetItem(f"  • {line}")
            self.profile_list.addItem(item)
    
    def _add_preferences_section(self):
        """취미/선호도 섹션 추가"""
        # 헤더
        header_item = QListWidgetItem(t("profile.section.preferences"))
        header_item.setBackground(Qt.GlobalColor.lightGray)
        self.profile_list.addItem(header_item)
        
        likes = self.user_profile.preferences.get('likes', [])
        for like in likes:
            item = QListWidgetItem(f"  • {like}")
            self.profile_list.addItem(item)
    
    def _add_facts_section(self):
        """자동 추출 정보 섹션 추가"""
        # 헤더
        header_item = QListWidgetItem(t("profile.section.extracted"))
        header_item.setBackground(Qt.GlobalColor.lightGray)
        self.profile_list.addItem(header_item)
        
        # 시간순 정렬 (최신순)
        facts = sorted(
            self.user_profile.facts,
            key=lambda f: f.timestamp,
            reverse=True
        )
        
        # 목록에 추가
        for idx, fact in enumerate(facts):
            item = QListWidgetItem()
            widget = self._create_fact_widget(fact)
            
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, idx)
            
            self.profile_list.addItem(item)
            self.profile_list.setItemWidget(item, widget)
    
    def _create_fact_widget(self, fact):
        """프로필 항목 위젯 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 첫 줄: 시간
        first_line = QHBoxLayout()
        
        try:
            dt = datetime.fromisoformat(fact.timestamp)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except:
            time_str = fact.timestamp[:16]
        
        time_label = QLabel(time_str)
        time_label.setStyleSheet("color: gray; font-size: 11px;")
        first_line.addWidget(time_label)
        
        # 카테고리 표시
        category_label = QLabel(f"[{fact.category}]")
        category_label.setStyleSheet("color: #0066cc; font-size: 11px;")
        first_line.addWidget(category_label)
        
        first_line.addStretch()
        layout.addLayout(first_line)
        
        # 둘째 줄: 내용
        content_label = QLabel(fact.content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(content_label)
        
        # 셋째 줄: 출처 (있으면)
        if fact.source:
            source_label = QLabel(t("profile.source.label", source=fact.source))
            source_label.setStyleSheet("color: #666; font-size: 10px; font-style: italic;")
            layout.addWidget(source_label)
        
        return widget
    
    def _on_selection_changed(self):
        """선택 변경 시"""
        has_selection = len(self.profile_list.selectedItems()) > 0
        self.delete_btn.setEnabled(has_selection)
    
    def _delete_fact(self):
        """프로필 정보 삭제"""
        if not self.profile_list.selectedItems():
            return
        
        # 확인 대화상자
        reply = QMessageBox.question(
            self,
            t("profile.delete.title"),
            t("profile.delete.body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        selected_item = self.profile_list.selectedItems()[0]
        fact_index = selected_item.data(Qt.ItemDataRole.UserRole)
        
        # 삭제 (최신순으로 정렬된 인덱스이므로 실제 인덱스 찾기)
        facts_sorted = sorted(
            self.user_profile.facts,
            key=lambda f: f.timestamp,
            reverse=True
        )
        fact_to_delete = facts_sorted[fact_index]
        
        # 원본 리스트에서 찾아서 삭제
        for i, f in enumerate(self.user_profile.facts):
            if f.timestamp == fact_to_delete.timestamp and f.content == fact_to_delete.content:
                self.user_profile.delete_fact(i)
                break
        
        # 목록 새로고침
        self._load_profile()
