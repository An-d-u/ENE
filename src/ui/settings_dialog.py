"""
설정 다이얼로그
윈도우 위치, 크기, 모델 위치/스케일 등을 조정
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                              QSpinBox, QDoubleSpinBox, QSlider, QPushButton, 
                              QGroupBox, QFormLayout, QCheckBox, QTabWidget, QWidget)
from PyQt6.QtCore import Qt, pyqtSignal


class SettingsDialog(QDialog):
    """설정 다이얼로그"""
    
    # 설정 변경 시그널
    settings_changed = pyqtSignal(dict)
    settings_preview = pyqtSignal(dict)  # 실시간 미리보기용
    
    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        
        self.current_settings = current_settings.copy()
        
        self.setWindowTitle("ENE 설정")
        self.setMinimumWidth(450)
        self.setMinimumHeight(500)
        
        self._setup_ui()
        self._load_values()
    
    def _setup_ui(self):
        """UI 구성"""
        layout = QVBoxLayout(self)
        
        # 탭 위젯
        tabs = QTabWidget()
        
        # 탭 1: 창 설정
        window_tab = self._create_window_tab()
        tabs.addTab(window_tab, "창 설정")
        
        # 탭 2: 모델 설정
        model_tab = self._create_model_tab()
        tabs.addTab(model_tab, "모델 설정")
        
        layout.addWidget(tabs)
        
        # 저장/취소 버튼만 남김
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def _create_window_tab(self):
        """창 설정 탭 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 위치 그룹
        position_group = QGroupBox("창 위치")
        position_layout = QFormLayout()
        
        self.window_x_spin = QSpinBox()
        self.window_x_spin.setRange(-9999, 9999)
        self.window_x_spin.setSuffix(" px")
        position_layout.addRow("X 좌표:", self.window_x_spin)
        
        self.window_y_spin = QSpinBox()
        self.window_y_spin.setRange(-9999, 9999)
        self.window_y_spin.setSuffix(" px")
        position_layout.addRow("Y 좌표:", self.window_y_spin)
        
        position_group.setLayout(position_layout)
        layout.addWidget(position_group)
        
        # 크기 그룹
        size_group = QGroupBox("창 크기")
        size_layout = QFormLayout()
        
        self.window_width_spin = QSpinBox()
        self.window_width_spin.setRange(200, 3840)
        self.window_width_spin.setSuffix(" px")
        size_layout.addRow("너비:", self.window_width_spin)
        
        self.window_height_spin = QSpinBox()
        self.window_height_spin.setRange(200, 2160)
        self.window_height_spin.setSuffix(" px")
        size_layout.addRow("높이:", self.window_height_spin)
        
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)
        
        # 프리셋 버튼
        preset_layout = QHBoxLayout()
        
        center_btn = QPushButton("화면 중앙")
        center_btn.clicked.connect(self._preset_center)
        preset_layout.addWidget(center_btn)
        
        bottom_right_btn = QPushButton("우측 하단")
        bottom_right_btn.clicked.connect(self._preset_bottom_right)
        preset_layout.addWidget(bottom_right_btn)
        
        bottom_left_btn = QPushButton("좌측 하단")
        bottom_left_btn.clicked.connect(self._preset_bottom_left)
        preset_layout.addWidget(bottom_left_btn)
        
        layout.addLayout(preset_layout)
        
        # 기타 옵션
        other_group = QGroupBox("기타")
        other_layout = QVBoxLayout()
        
        self.show_drag_bar_check = QCheckBox("드래그 바 표시")
        other_layout.addWidget(self.show_drag_bar_check)
        
        self.mouse_tracking_check = QCheckBox("마우스 트래킹 활성화")
        other_layout.addWidget(self.mouse_tracking_check)
        
        other_group.setLayout(other_layout)
        layout.addWidget(other_group)
        
        layout.addStretch()
        
        return widget
    
    def _create_model_tab(self):
        """모델 설정 탭 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 모델 스케일
        scale_group = QGroupBox("모델 크기")
        scale_layout = QVBoxLayout()
        
        scale_form = QFormLayout()
        
        self.model_scale_spin = QDoubleSpinBox()
        self.model_scale_spin.setRange(0.1, 5.0)
        self.model_scale_spin.setSingleStep(0.1)
        self.model_scale_spin.setDecimals(2)
        self.model_scale_spin.setSuffix("x")
        scale_form.addRow("스케일:", self.model_scale_spin)
        
        scale_layout.addLayout(scale_form)
        
        # 스케일 슬라이더
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 500)  # 0.1x ~ 5.0x
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setTickInterval(50)
        scale_layout.addWidget(self.scale_slider)
        
        # 스핀박스와 슬라이더 연결
        self.model_scale_spin.valueChanged.connect(
            lambda v: self.scale_slider.setValue(int(v * 100))
        )
        self.scale_slider.valueChanged.connect(
            lambda v: self.model_scale_spin.setValue(v / 100.0)
        )
        
        # 실시간 미리보기 연결
        self.scale_slider.valueChanged.connect(self._on_setting_changed)
        
        scale_group.setLayout(scale_layout)
        layout.addWidget(scale_group)
        
        # 모델 위치 X
        x_group = QGroupBox("모델 X 위치 (좌우)")
        x_layout = QVBoxLayout()
        
        x_info_layout = QHBoxLayout()
        x_info_layout.addWidget(QLabel("← ← 좌측"))
        x_info_layout.addStretch()
        self.model_x_value_label = QLabel("50%")
        self.model_x_value_label.setStyleSheet("font-weight: bold;")
        x_info_layout.addWidget(self.model_x_value_label)
        x_info_layout.addStretch()
        x_info_layout.addWidget(QLabel("우측 → →"))
        x_layout.addLayout(x_info_layout)
        
        self.model_x_slider = QSlider(Qt.Orientation.Horizontal)
        self.model_x_slider.setRange(-100, 200)  # -100% ~ 200%
        self.model_x_slider.setValue(50)
        self.model_x_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.model_x_slider.setTickInterval(25)
        x_layout.addWidget(self.model_x_slider)
        
        # X 슬라이더 값 변경 시 레이블 업데이트 및 미리보기
        self.model_x_slider.valueChanged.connect(
            lambda v: self.model_x_value_label.setText(f"{v}%")
        )
        self.model_x_slider.valueChanged.connect(self._on_setting_changed)
        
        x_group.setLayout(x_layout)
        layout.addWidget(x_group)
        
        # 모델 위치 Y
        y_group = QGroupBox("모델 Y 위치 (상하)")
        y_layout = QVBoxLayout()
        
        y_info_layout = QHBoxLayout()
        y_info_layout.addWidget(QLabel("↑ ↑ 상단"))
        y_info_layout.addStretch()
        self.model_y_value_label = QLabel("50%")
        self.model_y_value_label.setStyleSheet("font-weight: bold;")
        y_info_layout.addWidget(self.model_y_value_label)
        y_info_layout.addStretch()
        y_info_layout.addWidget(QLabel("하단 ↓ ↓"))
        y_layout.addLayout(y_info_layout)
        
        self.model_y_slider = QSlider(Qt.Orientation.Horizontal)
        self.model_y_slider.setRange(-100, 200)  # -100% ~ 200%
        self.model_y_slider.setValue(50)
        self.model_y_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.model_y_slider.setTickInterval(25)
        y_layout.addWidget(self.model_y_slider)
        
        # Y 슬라이더 값 변경 시 레이블 업데이트 및 미리보기
        self.model_y_slider.valueChanged.connect(
            lambda v: self.model_y_value_label.setText(f"{v}%")
        )
        self.model_y_slider.valueChanged.connect(self._on_setting_changed)
        
        y_group.setLayout(y_layout)
        layout.addWidget(y_group)
        
        # 모델 위치 프리셋
        model_preset_layout = QHBoxLayout()
        
        model_center_btn = QPushButton("중앙")
        model_center_btn.clicked.connect(lambda: self._set_model_position(50, 50))
        model_preset_layout.addWidget(model_center_btn)
        
        model_left_btn = QPushButton("좌측")
        model_left_btn.clicked.connect(lambda: self._set_model_position(25, 50))
        model_preset_layout.addWidget(model_left_btn)
        
        model_right_btn = QPushButton("우측")
        model_right_btn.clicked.connect(lambda: self._set_model_position(75, 50))
        model_preset_layout.addWidget(model_right_btn)
        
        layout.addLayout(model_preset_layout)
        
        layout.addStretch()
        
        return widget
    
    def _on_setting_changed(self):
        """설정 값이 변경될 때 호출 - 항상 실시간 미리보기"""
        self._preview_settings()
    
    def _load_values(self):
        """현재 설정값을 UI에 로드"""
        # 창 설정
        self.window_x_spin.setValue(self.current_settings.get('window_x', 100))
        self.window_y_spin.setValue(self.current_settings.get('window_y', 100))
        self.window_width_spin.setValue(self.current_settings.get('window_width', 400))
        self.window_height_spin.setValue(self.current_settings.get('window_height', 600))
        self.show_drag_bar_check.setChecked(self.current_settings.get('show_drag_bar', True))
        self.mouse_tracking_check.setChecked(self.current_settings.get('mouse_tracking_enabled', True))
        
        # 모델 설정
        model_scale = self.current_settings.get('model_scale', 1.0)
        self.model_scale_spin.setValue(model_scale)
        
        self.model_x_slider.setValue(int(self.current_settings.get('model_x_percent', 50)))
        self.model_y_slider.setValue(int(self.current_settings.get('model_y_percent', 50)))
    
    def _preset_center(self):
        """화면 중앙 프리셋"""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        
        width = self.window_width_spin.value()
        height = self.window_height_spin.value()
        
        self.window_x_spin.setValue((screen.width() - width) // 2)
        self.window_y_spin.setValue((screen.height() - height) // 2)
    
    def _preset_bottom_right(self):
        """우측 하단 프리셋"""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        
        width = self.window_width_spin.value()
        height = self.window_height_spin.value()
        
        self.window_x_spin.setValue(screen.width() - width - 50)
        self.window_y_spin.setValue(screen.height() - height - 50)
    
    def _preset_bottom_left(self):
        """좌측 하단 프리셋"""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        
        height = self.window_height_spin.value()
        
        self.window_x_spin.setValue(50)
        self.window_y_spin.setValue(screen.height() - height - 50)
    
    def _set_model_position(self, x_percent, y_percent):
        """모델 위치 설정"""
        self.model_x_slider.setValue(int(x_percent))
        self.model_y_slider.setValue(int(y_percent))
    
    def _get_current_values(self):
        """현재 UI의 값들을 딕셔너리로 반환"""
        return {
            'window_x': self.window_x_spin.value(),
            'window_y': self.window_y_spin.value(),
            'window_width': self.window_width_spin.value(),
            'window_height': self.window_height_spin.value(),
            'show_drag_bar': self.show_drag_bar_check.isChecked(),
            'mouse_tracking_enabled': self.mouse_tracking_check.isChecked(),
            'model_scale': self.model_scale_spin.value(),
            'model_x_percent': self.model_x_slider.value(),
            'model_y_percent': self.model_y_slider.value(),
        }
    
    def _preview_settings(self):
        """미리보기 - 설정을 임시로 적용 (항상 활성화)"""
        new_settings = self._get_current_values()
        self.settings_preview.emit(new_settings)
    
    def _save_settings(self):
        """설정 저장 및 적용"""
        new_settings = self._get_current_values()
        self.settings_changed.emit(new_settings)
        self.accept()
