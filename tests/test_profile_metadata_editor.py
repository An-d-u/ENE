import json
from types import SimpleNamespace

from src.ui.settings_dialog_profile import SettingsDialogProfileMixin


def test_settings_load_save_preserves_memory_metadata(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    path = tmp_path / "profile.json"
    fact = {"id": "fact-example", "content": "가상 계획 보류", "category": "goal", "timestamp": "2026-01-01", "source": "가상 대화", "state": "paused", "effective_at": "2026-01-01", "history": [{"content": "가상 계획 진행"}], "source_memory_id": "memory-example"}
    path.write_text(json.dumps({"facts": [fact], "basic_info": {}, "preferences": {}, "schema_version": 2}), encoding="utf-8")
    dialog = SimpleNamespace(
        _user_profile_path=path, _bridge=None,
        _read_text_file=lambda p: p.read_text(encoding="utf-8"),
        _write_text_file=lambda p, text: p.write_text(text, encoding="utf-8"),
        _refresh_basic_info_list=lambda: None, _refresh_preference_lists=lambda data: None,
        _refresh_fact_list=lambda: None, _new_basic_info_item=lambda: None, _new_fact_item=lambda: None,
        _set_profile_status=lambda *args, **kwargs: None,
        _translated_text=lambda key, fallback: fallback,
        _translated_text_format=lambda key, fallback, **kwargs: fallback,
        likes_list=SimpleNamespace(count=lambda: 0), dislikes_list=SimpleNamespace(count=lambda: 0),
    )
    SettingsDialogProfileMixin._load_user_profile_data(dialog)
    SettingsDialogProfileMixin._save_user_profile_data(dialog)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["facts"] == [fact]
    assert saved["schema_version"] == 2


class _List:
    def __init__(self, values=()):
        self.values = list(values)

    def count(self):
        return len(self.values)

    def item(self, index):
        return SimpleNamespace(text=lambda: self.values[index])

    def clear(self):
        self.values.clear()

    def addItems(self, values):
        self.values.extend(values)


class _Editor(SettingsDialogProfileMixin):
    def __init__(self, category, previous, edited):
        self._fact_items = [{"content": previous, "category": category, "state": "active"}]
        self._fact_current_index = 0
        self._basic_info_items = []
        self.likes_list = _List()
        self.dislikes_list = _List()
        self.fact_content_edit = SimpleNamespace(toPlainText=lambda: edited)
        self.fact_category_combo = SimpleNamespace(currentData=lambda: category)
        self.fact_source_input = SimpleNamespace(text=lambda: "수동 편집")
        self.fact_list = SimpleNamespace(setCurrentRow=lambda row: None, currentRow=lambda: 0)

    def _refresh_fact_list(self):
        pass

    def _refresh_basic_info_list(self):
        pass

    def _new_fact_item(self):
        pass


def test_fact_edit_and_delete_sync_preferences_without_removing_manual_values():
    dialog = _Editor("preference", "가상 퍼즐을 좋아한다", "가상 퍼즐을 좋아하지 않는다")
    dialog.likes_list.values = ["가상 퍼즐을 좋아한다", "별도 수동 취향"]
    dialog._apply_fact_item()
    assert dialog.likes_list.values == ["별도 수동 취향"]
    assert dialog.dislikes_list.values == ["가상 퍼즐을 좋아하지 않는다"]
    dialog._delete_fact_item()
    assert dialog.dislikes_list.values == []
    assert dialog.likes_list.values == ["별도 수동 취향"]


def test_fact_edit_and_delete_sync_only_matching_basic_fields():
    dialog = _Editor("basic", "전공: 가상학", "전공: 예시학")
    dialog._basic_info_items = [("major", "가상학"), ("occupation", "수동 직업")]
    dialog._apply_fact_item()
    assert dict(dialog._basic_info_items) == {"major": "예시학", "occupation": "수동 직업"}
    dialog._basic_info_items = [("major", "별도 수동 전공"), ("occupation", "수동 직업")]
    dialog._delete_fact_item()
    assert dict(dialog._basic_info_items) == {"major": "별도 수동 전공", "occupation": "수동 직업"}
