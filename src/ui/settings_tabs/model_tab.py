"""
모델 배치 탭 빌더.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)


def build_model_tab(dialog):
    self = dialog
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    layout.setContentsMargins(10, 10, 10, 10)

    preset_group = QGroupBox("빠른 배치")
    self._bind_group_title(preset_group, "settings.model.quick.title", "빠른 배치")
    preset_group_layout = QVBoxLayout(preset_group)
    preset_group_layout.setSpacing(10)
    preset_group_layout.addWidget(
        self._build_hint_label(
            "자주 쓰는 위치를 먼저 고른 뒤, 아래 슬라이더로 세밀하게 맞추면 더 편합니다.",
            key="settings.model.quick.hint",
        )
    )

    preset_layout = QHBoxLayout()
    center_btn = QPushButton("중앙")
    self._bind_widget_text(center_btn, "settings.model.quick.center", "중앙")
    center_btn.clicked.connect(lambda: self._set_model_position(50, 50))
    preset_layout.addWidget(center_btn)
    left_btn = QPushButton("좌측")
    self._bind_widget_text(left_btn, "settings.model.quick.left", "좌측")
    left_btn.clicked.connect(lambda: self._set_model_position(25, 50))
    preset_layout.addWidget(left_btn)
    right_btn = QPushButton("우측")
    self._bind_widget_text(right_btn, "settings.model.quick.right", "우측")
    right_btn.clicked.connect(lambda: self._set_model_position(75, 50))
    preset_layout.addWidget(right_btn)
    preset_group_layout.addLayout(preset_layout)
    layout.addWidget(preset_group)

    scale_group = QGroupBox("모델 크기")
    self._bind_group_title(scale_group, "settings.model.scale.title", "모델 크기")
    scale_layout = QVBoxLayout()
    scale_layout.setSpacing(8)
    scale_layout.setContentsMargins(10, 15, 10, 10)
    scale_form = QFormLayout()
    self.model_scale_spin = QDoubleSpinBox()
    self.model_scale_spin.setRange(0.1, 2.0)
    self.model_scale_spin.setSingleStep(0.05)
    self.model_scale_spin.setDecimals(2)
    self.model_scale_spin.setSuffix("x")
    self.model_scale_spin.valueChanged.connect(self._on_setting_changed)
    self._add_form_row(scale_form, "settings.model.scale.label", "스케일:", self.model_scale_spin)
    scale_layout.addLayout(scale_form)
    scale_layout.addWidget(
        self._build_hint_label(
            "1.00x를 기준으로 모델 전체 크기를 조정합니다.",
            key="settings.model.scale.hint",
        )
    )

    self.scale_slider = QSlider(Qt.Orientation.Horizontal)
    self.scale_slider.setRange(10, 200)
    self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
    self.scale_slider.setTickInterval(10)
    scale_layout.addWidget(self.scale_slider)
    self.model_scale_spin.valueChanged.connect(lambda v: self.scale_slider.setValue(int(v * 100)))
    self.scale_slider.valueChanged.connect(lambda v: self.model_scale_spin.setValue(v / 100.0))
    scale_group.setLayout(scale_layout)
    layout.addWidget(scale_group)

    x_group = QGroupBox("모델 X 위치")
    self._bind_group_title(x_group, "settings.model.position_x.title", "모델 X 위치")
    x_layout = QVBoxLayout()
    x_layout.setSpacing(8)
    x_layout.setContentsMargins(10, 15, 10, 10)
    x_layout.addWidget(
        self._build_hint_label(
            "모델을 화면의 왼쪽과 오른쪽 사이에서 조정합니다.",
            key="settings.model.position_x.hint",
        )
    )
    x_info = QHBoxLayout()
    left_label = QLabel("왼쪽")
    self._bind_widget_text(left_label, "settings.model.position_x.left", "왼쪽")
    x_info.addWidget(left_label)
    x_info.addStretch()
    self.model_x_value_label = QLabel("50%")
    self.model_x_value_label.setObjectName("ValueBadge")
    x_info.addWidget(self.model_x_value_label)
    x_info.addStretch()
    right_label = QLabel("오른쪽")
    self._bind_widget_text(right_label, "settings.model.position_x.right", "오른쪽")
    x_info.addWidget(right_label)
    x_layout.addLayout(x_info)
    self.model_x_slider = QSlider(Qt.Orientation.Horizontal)
    self.model_x_slider.setRange(-100, 200)
    self.model_x_slider.valueChanged.connect(lambda v: self.model_x_value_label.setText(f"{v}%"))
    self.model_x_slider.valueChanged.connect(self._on_setting_changed)
    x_layout.addWidget(self.model_x_slider)
    x_group.setLayout(x_layout)
    layout.addWidget(x_group)

    y_group = QGroupBox("모델 Y 위치")
    self._bind_group_title(y_group, "settings.model.position_y.title", "모델 Y 위치")
    y_layout = QVBoxLayout()
    y_layout.setSpacing(8)
    y_layout.setContentsMargins(10, 15, 10, 10)
    y_layout.addWidget(
        self._build_hint_label(
            "모델을 화면의 위쪽과 아래쪽 사이에서 조정합니다.",
            key="settings.model.position_y.hint",
        )
    )
    y_info = QHBoxLayout()
    top_label = QLabel("위쪽")
    self._bind_widget_text(top_label, "settings.model.position_y.top", "위쪽")
    y_info.addWidget(top_label)
    y_info.addStretch()
    self.model_y_value_label = QLabel("50%")
    self.model_y_value_label.setObjectName("ValueBadge")
    y_info.addWidget(self.model_y_value_label)
    y_info.addStretch()
    bottom_label = QLabel("아래쪽")
    self._bind_widget_text(bottom_label, "settings.model.position_y.bottom", "아래쪽")
    y_info.addWidget(bottom_label)
    y_layout.addLayout(y_info)
    self.model_y_slider = QSlider(Qt.Orientation.Horizontal)
    self.model_y_slider.setRange(-100, 200)
    self.model_y_slider.valueChanged.connect(lambda v: self.model_y_value_label.setText(f"{v}%"))
    self.model_y_slider.valueChanged.connect(self._on_setting_changed)
    y_layout.addWidget(self.model_y_slider)
    y_group.setLayout(y_layout)
    layout.addWidget(y_group)

    model_path_group = QGroupBox("Live2D 모델 파일")
    self._bind_group_title(model_path_group, "settings.model.path.title", "Live2D 모델 파일")
    model_path_layout = QVBoxLayout(model_path_group)
    model_path_layout.setSpacing(10)
    model_path_layout.addWidget(
        self._build_hint_label(
            "`.model3.json` 파일 경로를 직접 지정합니다. 저장 전에도 미리보기에서 모델이 다시 로드됩니다.",
            key="settings.model.path.hint",
        )
    )

    model_path_row = QHBoxLayout()
    model_path_row.setSpacing(8)
    self.model_json_path_edit = QLineEdit()
    self._bind_placeholder(
        self.model_json_path_edit,
        "settings.model.path.placeholder",
        "예: assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json",
    )
    self.model_json_path_edit.textChanged.connect(self._on_setting_changed)
    model_path_row.addWidget(self.model_json_path_edit, 1)

    browse_model_btn = QPushButton("찾아보기")
    self._bind_widget_text(browse_model_btn, "settings.common.browse", "찾아보기")
    browse_model_btn.clicked.connect(self._browse_live2d_model_path)
    model_path_row.addWidget(browse_model_btn)
    model_path_layout.addLayout(model_path_row)
    layout.addWidget(model_path_group)

    layout.addStretch()
    scroll.setWidget(widget)
    return scroll

