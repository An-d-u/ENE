"""합성 로그로 공유본의 공개 범위와 실제 저장 흐름을 확인한다."""

import json

import pytest
from PyQt6.QtWidgets import QDialogButtonBox

from src.core.diagnostic_share import diagnostic_records
from tests.test_life_record_settings_ui import _dialog, prompt_paths


def result(**fields):
    return {
        "event": "result", "stage": "llm", "provider": "openai", "model": "gpt-4o-mini",
        "status": "error", "elapsed_seconds": 12.375, "status_code": 429, **fields,
    }


def write_events(path, events):
    path.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in events))


def test_report_uses_only_allowlisted_fields_and_values(tmp_path):
    path = tmp_path / "debug-2030-01-01.jsonl"
    private = "synthetic-private-value"
    write_events(path, [
        result(event="request", request={"text": private}),
        result(request_id=private, timestamp=private, extra=private, error_type=private,
               error_body=private, traceback=private, error_message=private),
        result(provider="custom_api", model="gpt-4o-mini", status_code=private, error_type="ReadTimeout"),
        result(stage="tts", provider="fish_audio", model="s2.1-pro", status="success", status_code=None),
        result(provider=private, model=private, elapsed_seconds=private, status_code=True),
        result(stage=private), result(status=private),
    ])
    rows = [item for item in diagnostic_records(path) if item is not None]
    assert rows == [
        {"stage": "llm", "provider": "openai", "model": "gpt-4o-mini", "status": "error",
         "elapsed_seconds": 12.375, "status_code": 429, "error_category": "rate_limit"},
        {"stage": "llm", "provider": "custom_api", "status": "error",
         "elapsed_seconds": 12.375, "error_category": "timeout"},
        {"stage": "tts", "provider": "fish_audio", "model": "s2.1-pro", "status": "success",
         "elapsed_seconds": 12.375},
        {"stage": "llm", "status": "error", "error_category": "other"},
    ]
    assert private not in json.dumps(rows)


def test_damaged_rows_and_wrong_types_do_not_hide_valid_results(tmp_path):
    path = tmp_path / "synthetic.jsonl"
    path.write_bytes(b'\xff\n[1]\n{"partial":\n' + json.dumps(result(
        model=["synthetic"], provider={}, error_type=[], status_code=1000, elapsed_seconds=float("nan"),
    )).encode() + b"\n")
    assert list(filter(None, diagnostic_records(path))) == [
        {"stage": "llm", "status": "error", "error_category": "other"}
    ]


def test_settings_preview_is_the_only_content_saved(prompt_paths, tmp_path, monkeypatch):
    from src.ui import diagnostic_share_dialog as ui
    from PyQt6.QtWidgets import QApplication
    monkeypatch.setattr("src.ui.settings_dialog.tiktoken", None)
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    path = log_dir / "debug-2030-01-02.jsonl"
    earlier = log_dir / "debug-2030-01-01.jsonl"
    write_events(earlier, [result(event="request", request={"text": "synthetic-unfinished"})])
    write_events(path, [result(elapsed_seconds=i, error_body="synthetic-hidden") for i in range(110)])
    monkeypatch.setattr(ui, "get_debug_log_dir", lambda: log_dir)
    target = tmp_path / "diagnostic-copy.json"
    settings = _dialog(prompt_paths, monkeypatch)

    def load(preview):
        while preview.timer.isActive():
            QApplication.processEvents()

    def interact(preview):
        load(preview)
        assert preview.editor.isReadOnly()
        assert preview.source.currentText() == "2030-01-02"
        save = preview.buttons.button(QDialogButtonBox.StandardButton.Save)
        assert save.isEnabled()
        preview.source.setCurrentIndex(1)
        load(preview)
        assert not save.isEnabled()
        assert "synthetic-unfinished" not in preview.editor.toPlainText()
        preview.source.setCurrentIndex(0)
        load(preview)
        text = preview.editor.toPlainText()
        assert [r["elapsed_seconds"] for r in json.loads(text)] == list(range(10, 110))
        assert "synthetic-hidden" not in text
        write_events(path, [result(elapsed_seconds=999)])
        original = path.read_bytes()
        monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
        save.click()
        assert not target.exists()
        monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
        save.click()
        assert path.read_bytes() == original
        monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
        def fail_write(*args):
            raise OSError("synthetic-storage-error")
        with monkeypatch.context() as failed:
            failed.setattr(ui, "write_bytes_data_atomic", fail_write)
            save.click()
            assert not target.exists()
            assert preview.editor.toPlainText() == text
        save.click()
        assert target.read_bytes() == text.encode("utf-8")
        assert preview.result() == ui.QDialog.DialogCode.Accepted
        return preview.result()

    # Qt 신호 슬롯 밖에서 단언 오류를 전달해야 테스트 러너가 원인을 표시한다.
    failures = []
    def run_modal(preview):
        try:
            return interact(preview)
        except Exception as error:
            failures.append(error)
            return 0
    monkeypatch.setattr(ui.DiagnosticShareDialog, "exec", run_modal)
    try:
        assert not settings.debug_mode_check.isChecked()
        settings.diagnostic_share_button.click()
        if failures:
            raise failures[0]
        assert target.exists()
    finally:
        settings.close()


@pytest.mark.parametrize("source_disappears", [False, True])
def test_unavailable_logs_never_enable_saving(tmp_path, monkeypatch, source_disappears):
    from PyQt6.QtWidgets import QApplication, QDialog
    from src.ui import diagnostic_share_dialog as ui

    class Parent(QDialog):
        def _translated_text(self, key, fallback):
            return fallback

    log_dir = tmp_path / "log"
    monkeypatch.setattr(ui, "get_debug_log_dir", lambda: log_dir)
    if source_disappears:
        log_dir.mkdir()
        source = log_dir / "debug-2030-01-01.jsonl"
        write_events(source, [result()])
    parent = Parent()
    dialog = ui.DiagnosticShareDialog(parent)
    if source_disappears:
        source.unlink()
        while dialog.timer.isActive():
            QApplication.processEvents()
        assert "읽을 수 없" in dialog.editor.placeholderText()
    else:
        assert not log_dir.exists()
        assert "로그가 없" in dialog.editor.placeholderText()
    assert not dialog.save_button.isEnabled()
    assert dialog.editor.toPlainText() == ""
    dialog.reject()
