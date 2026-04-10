"""
에네 자기 정보 관리 다이얼로그
"""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QVBoxLayout

from ..core.i18n import tr as t
from .ene_profile_editor import EneProfileEditorPanel


class EneProfileDialog(QDialog):
    """에네 자기 정보 CRUD 다이얼로그."""

    def __init__(self, ene_profile, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("ene_profile.window.title"))
        self.setMinimumSize(860, 620)

        layout = QVBoxLayout(self)
        self.panel = EneProfileEditorPanel(ene_profile, self, show_close_button=True)
        if self.panel.close_btn is not None:
            self.panel.close_btn.clicked.connect(self.accept)
        layout.addWidget(self.panel)

        self.stats_label = self.panel.stats_label
        self.core_group = self.panel.core_group
        self.fact_group = self.panel.fact_group
        self.core_list = self.panel.core_list
        self.fact_list = self.panel.fact_list
        self.refresh_btn = self.panel.refresh_btn
        self.save_btn = self.panel.save_btn
        self.close_btn = self.panel.close_btn
