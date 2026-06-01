from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox

from src.core import app as app_module


class _DummySignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in list(self.callbacks):
            callback()


class _DummyBridge:
    def __init__(self, conversation_buffer=None):
        self.conversation_buffer = list(conversation_buffer or [])
        self.summary_review_saved = _DummySignal()
        self.stop_away_monitor_calls = 0
        self.summarize_now_calls = 0
        self.clear_conversation_calls = 0

    def stop_away_monitor(self):
        self.stop_away_monitor_calls += 1

    def summarize_now(self):
        self.summarize_now_calls += 1

    def clear_conversation(self):
        self.clear_conversation_calls += 1


class _DummyWindow:
    def __init__(self, bridge=None):
        self.bridge = bridge
        self.show_calls = 0
        self.shutdown_calls = 0
        self.close_calls = 0

    def show(self):
        self.show_calls += 1

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def shutdown(self):
        self.shutdown_calls += 1

    def close(self):
        self.close_calls += 1


class _DummyTimer:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def _build_quit_app(monkeypatch, bridge, question_reply):
    app = app_module.ENEApplication.__new__(app_module.ENEApplication)
    app.overlay_window = _DummyWindow(bridge)
    app.obsidian_panel_window = _DummyWindow()
    app.global_ptt = SimpleNamespace(shutdown_calls=0)
    app.global_ptt.shutdown = lambda: setattr(app.global_ptt, "shutdown_calls", app.global_ptt.shutdown_calls + 1)
    app.system_theme_timer = _DummyTimer()
    app._settings_dialog = SimpleNamespace(isVisible=lambda: False, close=lambda: None)
    app._quit_after_summary_review = False
    app._quit_in_progress = False
    app._quit_summary_review_connected = False
    question_calls = []
    quit_calls = []

    def fake_question(*args, **kwargs):
        question_calls.append((args, kwargs))
        return question_reply

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(app_module.QApplication, "quit", lambda: quit_calls.append("quit"))
    return app, question_calls, quit_calls


def test_tray_quit_prompts_and_opens_manual_summary_review_when_user_accepts(monkeypatch):
    bridge = _DummyBridge([("user", "hello", "2026-06-01 10:00")])
    app, question_calls, quit_calls = _build_quit_app(
        monkeypatch,
        bridge,
        QMessageBox.StandardButton.Yes,
    )

    app_module.ENEApplication._quit_application(app)

    assert len(question_calls) == 1
    assert bridge.stop_away_monitor_calls == 0
    assert bridge.summarize_now_calls == 1
    assert bridge.clear_conversation_calls == 0
    assert app.overlay_window.show_calls == 1
    assert quit_calls == []


def test_tray_quit_skips_summary_and_exits_when_user_declines(monkeypatch):
    bridge = _DummyBridge([("user", "hello", "2026-06-01 10:00")])
    app, question_calls, quit_calls = _build_quit_app(
        monkeypatch,
        bridge,
        QMessageBox.StandardButton.No,
    )

    app_module.ENEApplication._quit_application(app)

    assert len(question_calls) == 1
    assert bridge.summarize_now_calls == 0
    assert bridge.clear_conversation_calls == 0
    assert app.overlay_window.shutdown_calls == 1
    assert app.overlay_window.close_calls == 1
    assert quit_calls == ["quit"]


def test_tray_quit_finishes_after_summary_review_is_saved(monkeypatch):
    bridge = _DummyBridge([("user", "hello", "2026-06-01 10:00")])
    app, _, quit_calls = _build_quit_app(
        monkeypatch,
        bridge,
        QMessageBox.StandardButton.Yes,
    )

    app_module.ENEApplication._quit_application(app)
    bridge.summary_review_saved.emit()

    assert bridge.summarize_now_calls == 1
    assert app.overlay_window.shutdown_calls == 1
    assert app.overlay_window.close_calls == 1
    assert quit_calls == ["quit"]
