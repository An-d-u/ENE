from datetime import date, datetime, timedelta
from types import SimpleNamespace

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QSplitter, QWidget


def test_year_heatmap_and_picker_share_selection_including_leap_and_future_days():
    from src.ui.settings_tabs.conversation_journal import ConversationJournal

    app = QApplication.instance() or QApplication([])
    today = date(2024, 3, 2)
    first_day = date(2024, 2, 28)
    stats = SimpleNamespace(
        as_of=today, first_day=first_day, total_turns=9, characters=114,
        daily_turns={first_day: 2, first_day + timedelta(days=1): 7},
        hourly_turns=(2, 7) + (0,) * 22,
        longest=SimpleNamespace(started_at=datetime(2024, 2, 29, 1), minutes=12, turns=7),
        streak_days=2, streak_start=first_day, streak_end=first_day + timedelta(days=1),
    )
    journal = ConversationJournal(SimpleNamespace(), lambda: stats)
    journal.resize(460, 600)
    journal.show()
    try:
        app.processEvents()
        assert journal.picker.minimumDate() == QDate(2024, 1, 1)
        assert journal.picker.maximumDate() == QDate(2024, 12, 31)
        assert journal.picker.date() == QDate(2024, 2, 29)
        assert "7턴" in journal.readout.text()
        assert "114" in journal.characters.value.text()
        assert "12분" == journal.longest.value.text()
        assert "2일" == journal.streak.value.text()
        assert "01" in journal.hours.accessibleDescription()
        calendar = journal.calendar
        january = calendar.day_rect(date(2024, 1, 1))
        december = calendar.day_rect(date(2024, 12, 31))
        assert january.center().x() < calendar.width() * 0.05
        assert december.center().x() > calendar.width() * 0.95
        QTest.mouseClick(calendar, Qt.MouseButton.LeftButton, pos=december.center().toPoint())
        assert journal.picker.date() == QDate(2024, 12, 31)
        assert journal.readout.text() == "집계 전"
        journal.picker.setDate(QDate(2024, 3, 1))
        assert journal.readout.text() == "0턴"
        QTest.keyClick(calendar, Qt.Key.Key_Up)
        assert journal.picker.date() == QDate(2024, 2, 29)
        journal.picker.setDate(QDate(2024, 1, 1))
        assert journal.readout.text() == "첫 대화 전"
    finally:
        journal.close()


def test_empty_activity_does_not_render_a_peak_or_invent_a_first_day():
    from src.ui.settings_tabs.conversation_journal import ConversationJournal

    app = QApplication.instance() or QApplication([])
    stats = SimpleNamespace(
        as_of=date(2025, 2, 1), first_day=None, total_turns=0, characters=0,
        daily_turns={}, hourly_turns=(0,) * 24, longest=None,
        streak_days=0, streak_start=None, streak_end=None,
    )
    journal = ConversationJournal(SimpleNamespace(), lambda: stats)
    journal.resize(315, 500)
    journal.show()
    try:
        app.processEvents()
        assert journal.picker.date() == QDate(2025, 2, 1)
        assert journal.first.value.text() == "—"
        assert journal.longest.value.text() == "—"
        assert journal.streak.value.text() == "—"
        assert journal.readout.text() == "0턴"
        assert journal.horizontalScrollBar().maximum() == 0
        assert "기록이 없습니다" in journal.peak_note.text()
    finally:
        journal.close()


def test_journal_updates_language_and_paints_the_surface_used_to_compute_contrast():
    from src.core.conversation_activity import conversation_activity
    from src.core.i18n import I18n
    from src.ui.settings_tabs.conversation_journal import ConversationJournal

    app = QApplication.instance() or QApplication([])
    translator = I18n("en")
    dialog = SimpleNamespace(_dialog_i18n=translator, _translated_text=lambda key, fallback: translator.t(key))
    journal = ConversationJournal(dialog, conversation_activity)
    journal.resize(700, 700)
    journal.show()
    try:
        app.processEvents()
        assert journal.title.text() == "Time together"
        translator.language = "ja"
        journal.retranslate_ui()
        assert journal.title.text() == "一緒に過ごした時間"
        assert journal.picker.accessibleName() == "確認する日付"
        journal.apply_theme({"settings_window_bg_color": "#fafafa", "settings_card_bg_color": "#111123"})
        page = journal.widget().grab().toImage()
        assert page.pixelColor(3, 3).name() == "#111123"
        assert journal.ink.lightnessF() > 0.8
    finally:
        journal.close()


def test_embedded_memory_controls_stage_search_settings_and_reveal_details():
    from src.ui.memory_dialog import MemoryDialog

    app = QApplication.instance() or QApplication([])
    manager = SimpleNamespace(memories=[], get_stats=lambda: {"total": 0, "important": 0, "with_embedding": 0})
    saved = []
    config = {"max_recent_memories": 4}
    bridge = SimpleNamespace(settings=SimpleNamespace(config=config, save=lambda: saved.append(True)),
                             summarize_threshold=9)
    panel = MemoryDialog(manager, bridge=bridge, embedded=True, include_topic_memory_tab=False)
    panel.show()
    try:
        app.processEvents()
        panel.threshold_spinbox.setValue(6)
        panel.recent_spinbox.setValue(3)
        assert saved == []
        assert config == {"max_recent_memories": 4}
        assert bridge.summarize_threshold == 9
        assert panel.tuning_changes() == {"summarize_threshold": 6, "max_recent_memories": 3}
        panel.threshold_spinbox.setValue(9)
        assert panel.tuning_changes() == {"max_recent_memories": 3}
        assert not panel.inspector_time_value.isVisibleTo(panel)
        panel.detail_toggle.click()
        assert panel.inspector_time_value.isVisibleTo(panel)
    finally:
        panel.close()


def test_topic_details_remain_readable_below_the_map_in_a_narrow_panel():
    from src.ui.topic_memory_mindmap import TopicMemoryMindmapPanel

    app = QApplication.instance() or QApplication([])
    panel = TopicMemoryMindmapPanel()
    panel.resize(475, 640)
    panel.show()
    try:
        app.processEvents()
        splitter = panel.findChild(QSplitter)
        assert splitter.orientation() == Qt.Orientation.Vertical
        assert panel.detail_body.width() >= panel.width() * .85
        panel.resize(900, 640)
        app.processEvents()
        assert splitter.orientation() == Qt.Orientation.Horizontal
    finally:
        panel.close()


def test_topic_map_uses_the_settings_language_for_controls_and_details():
    from src.core.i18n import I18n
    from src.ui.topic_memory_mindmap import TopicMemoryMindmapPanel

    app = QApplication.instance() or QApplication([])
    translator = I18n("en")
    panel = TopicMemoryMindmapPanel(translate=translator.t)
    try:
        assert panel.search_input.placeholderText() == translator.t("memory.topic_map.search.placeholder")
        translator.language = "ja"
        panel.retranslate_ui()
        assert panel.refresh_btn.text() == translator.t("memory.topic_map.refresh")
        assert panel.state_filter.itemText(0) == translator.t("memory.topic_map.state.all")
        assert panel.summary_label.text() == translator.t("memory.topic_map.summary", topics=0, clues=0)
    finally:
        panel.close()


def test_embedded_memory_filters_follow_the_settings_language_on_preview():
    from src.core.i18n import I18n
    from src.ui.memory_dialog import MemoryDialog

    app = QApplication.instance() or QApplication([])
    translator = I18n("en")
    owner = QWidget()
    owner._translated_text_format = lambda key, fallback, **values: translator.t(key, **values)
    manager = SimpleNamespace(memories=[], get_stats=lambda: {"total": 0, "important": 0, "with_embedding": 0})
    panel = MemoryDialog(manager, parent=owner, embedded=True, include_topic_memory_tab=False)
    try:
        translator.language = "ja"
        panel.retranslate_ui()
        assert panel.source_filter.currentText() == translator.t("memory.filter.source.prefix", value=translator.t("memory.filter.source.all"))
        assert panel.detail_toggle.text() == translator.t("memory.inspector.title")
        assert translator.t("memory.metric.total.label") in panel.memory_totals.text()
    finally:
        owner.close()
