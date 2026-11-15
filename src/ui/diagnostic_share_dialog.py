"""날짜별 디버그 로그에서 공유 가능한 내용만 미리 보고 저장한다."""

from collections import deque
import json
from pathlib import Path
import re
from subprocess import SubprocessError
import time

from PyQt6.QtCore import QStandardPaths, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from ..core.app_paths import write_bytes_data_atomic
from ..core.debug_logging import get_debug_log_dir
from ..core.diagnostic_share import diagnostic_records


class DiagnosticShareDialog(QDialog):
    def __init__(self, settings_dialog):
        super().__init__(settings_dialog)
        self.translate = settings_dialog._translated_text
        self.setWindowTitle(self.translate("settings.behavior.debug.share", "진단 공유본 만들기"))
        self.resize(620, 480)
        self.records = None
        self.rows = deque(maxlen=100)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._read_batch)
        self.finished.connect(self._stop_reading)

        layout = QVBoxLayout(self)
        self.source = QComboBox()
        label = QLabel(self.translate("settings.debug_share.date", "로그 날짜"))
        label.setBuddy(self.source)
        layout.addWidget(label)
        layout.addWidget(self.source)
        hint = QLabel(self.translate(
            "settings.debug_share.hint", "선택한 날짜의 최근 완료 기록 100건까지 표시합니다. 아래 내용이 그대로 저장됩니다.",
        ))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setAccessibleName(self.translate("settings.debug_share.preview", "저장할 내용 미리보기"))
        layout.addWidget(self.editor)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText(self.translate("settings.debug_share.save", "다른 이름으로 저장…"))
        self.save_button.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            self.translate("settings.footer.cancel", "취소")
        )
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        try:
            for path in sorted(get_debug_log_dir().glob("debug-*.jsonl"), reverse=True):
                if (re.fullmatch(r"debug-[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl", path.name)
                        and not path.is_symlink() and path.is_file()):
                    self.source.addItem(path.stem[6:], path)
        except OSError:
            self._read_error()
            return
        if self.source.count():
            self.source.currentIndexChanged.connect(self._load_day)
            self._load_day()
        else:
            self.source.setEnabled(False)
            self.editor.setPlaceholderText(self.translate(
                "settings.debug_share.no_logs", "아직 디버그 로그가 없습니다. 디버그 로그 저장을 켠 뒤 대화를 진행하세요.",
            ))

    def _stop_reading(self):
        self.timer.stop()
        if self.records is not None:
            self.records.close()
            self.records = None

    def _load_day(self):
        self._stop_reading()
        self.rows.clear()
        self.save_button.setEnabled(False)
        self.editor.clear()
        self.editor.setPlaceholderText(self.translate("settings.debug_share.loading", "진단 기록을 읽는 중…"))
        self.records = diagnostic_records(self.source.currentData())
        self.timer.start(0)

    def _read_error(self):
        self._stop_reading()
        self.save_button.setEnabled(False)
        self.editor.setPlaceholderText(self.translate("settings.debug_share.read_error", "로그를 읽을 수 없습니다."))

    def _read_batch(self):
        deadline = time.monotonic() + 0.008
        try:
            while time.monotonic() < deadline:
                row = next(self.records)
                if row is not None:
                    self.rows.append(row)
        except OSError:
            self._read_error()
        except StopIteration:
            self._stop_reading()
            if self.rows:
                self.editor.setPlainText(json.dumps(list(self.rows), indent=2, allow_nan=False))
                self.save_button.setEnabled(True)
            else:
                self.editor.setPlaceholderText(self.translate(
                    "settings.debug_share.empty", "이 날짜에 공유할 수 있는 완료 기록이 없습니다.",
                ))

    def _save(self):
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        selected, _ = QFileDialog.getSaveFileName(
            self, self.save_button.text(), str(Path(directory) / "ene-diagnostics.json"), "JSON (*.json)",
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".json":
            QMessageBox.warning(self, self.windowTitle(), self.translate(
                "settings.debug_share.extension", "공유본은 .json 파일로 저장하세요.",
            ))
            return
        try:
            write_bytes_data_atomic(path, self.editor.toPlainText().encode("utf-8"))
        except (OSError, SubprocessError):
            QMessageBox.warning(self, self.windowTitle(), self.translate(
                "settings.debug_share.save_error", "저장하지 못했습니다. 다른 위치를 선택해 다시 시도하세요.",
            ))
            return
        self.accept()


def open_diagnostic_share(settings_dialog):
    dialog = DiagnosticShareDialog(settings_dialog)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
