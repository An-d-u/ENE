from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox


class _FakeListItem:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _FakeListWidget:
    def __init__(self):
        self.items = []

    def clear(self):
        self.items = []

    def addItems(self, items):
        self.items.extend(items)

    def count(self):
        return len(self.items)

    def item(self, index):
        return _FakeListItem(self.items[index])


def test_profile_memory_apply_proposal_updates_editors_and_saves():
    from src.ui.settings_tabs.profile_memory_tab import apply_profile_memory_proposal

    saved = []
    dialog = SimpleNamespace()
    dialog._basic_info_items = []
    dialog._fact_items = []
    dialog.basic_info_list = _FakeListWidget()
    dialog.likes_list = _FakeListWidget()
    dialog.dislikes_list = _FakeListWidget()
    dialog._refresh_basic_info_list = lambda: dialog.basic_info_list.addItems(
        [f"{key}: {value}" for key, value in dialog._basic_info_items]
    )
    dialog._refresh_preference_lists = lambda preferences: (
        dialog.likes_list.clear(),
        dialog.likes_list.addItems(preferences.get("likes", [])),
        dialog.dislikes_list.clear(),
        dialog.dislikes_list.addItems(preferences.get("dislikes", [])),
    )
    dialog._refresh_fact_list = lambda: None
    dialog._new_basic_info_item = lambda: None
    dialog._new_fact_item = lambda: None
    dialog._save_user_profile_data = lambda: saved.append("user")

    ene_panel = SimpleNamespace(
        _core_items=[],
        _fact_items=[],
        _refresh_core_list=lambda: None,
        _refresh_fact_list=lambda: None,
        _update_stats=lambda: None,
        _new_core_item=lambda: None,
        _new_fact_item=lambda: None,
        save_profile=lambda: saved.append("ene"),
    )
    dialog._embedded_ene_profile_panel = ene_panel

    proposal = {
        "user_profile": {
            "basic_info": {"display_name": "테스트 사용자"},
            "preferences": {"likes": ["짧은 회의"], "dislikes": ["불명확한 일정"]},
            "facts": [
                {
                    "content": "사용자는 프로젝트 상태를 간단히 확인하는 것을 선호한다.",
                    "category": "preference",
                    "source": "memory_organizer",
                }
            ],
        },
        "ene_profile": {
            "core_profile": {
                "identity": ["에네는 작업 흐름을 차분히 정리한다."],
                "speaking_style": [],
                "relationship_tone": [],
            },
            "facts": [
                {
                    "content": "에네는 변경 전 확인 단계를 선호한다.",
                    "category": "habit",
                    "source": "memory_organizer",
                    "origin": "manual",
                    "auto_update": False,
                }
            ],
        },
    }

    apply_profile_memory_proposal(dialog, proposal)

    assert dialog._basic_info_items == [("display_name", "테스트 사용자")]
    assert dialog.likes_list.items == ["짧은 회의"]
    assert dialog._fact_items[0]["content"] == "사용자는 프로젝트 상태를 간단히 확인하는 것을 선호한다."
    assert ene_panel._core_items == [{"group": "identity", "content": "에네는 작업 흐름을 차분히 정리한다."}]
    assert ene_panel._fact_items[0]["origin"] == "manual"
    assert saved == ["user", "ene"]


def test_profile_memory_organize_cancel_does_not_save(monkeypatch):
    from src.ui.settings_tabs.profile_memory_tab import handle_profile_memory_organize

    saved = []

    class FakeLlm:
        def _request_one_shot_raw(self, prompt, include_sub_prompt=False):
            assert "user_profile" in prompt
            return """
            {
              "user_profile": {"basic_info": {}, "preferences": {"likes": [], "dislikes": []}, "facts": []},
              "ene_profile": {"core_profile": {"identity": [], "speaking_style": [], "relationship_tone": []}, "facts": []}
            }
            """

    dialog = SimpleNamespace()
    dialog._bridge = SimpleNamespace(llm_client=FakeLlm())
    dialog._basic_info_items = []
    dialog._fact_items = []
    dialog.likes_list = _FakeListWidget()
    dialog.dislikes_list = _FakeListWidget()
    dialog._save_user_profile_data = lambda: saved.append("user")
    dialog._translated_text = lambda _key, fallback: fallback
    dialog._translated_text_format = lambda _key, fallback, **kwargs: fallback.format(**kwargs)
    dialog.profile_memory_status_label = SimpleNamespace(setText=lambda _text: None)
    dialog.profile_memory_organize_button = SimpleNamespace(setEnabled=lambda _enabled: None)
    dialog._embedded_ene_profile_panel = SimpleNamespace(
        _core_items=[],
        _fact_items=[],
        save_profile=lambda: saved.append("ene"),
    )

    opened = []

    class FakeReviewDialog:
        def __init__(self, parent, proposal):
            opened.append(proposal)

        def exec(self):
            return QMessageBox.StandardButton.No

    monkeypatch.setattr("src.ui.settings_tabs.profile_memory_tab.ProfileMemoryReviewDialog", FakeReviewDialog)
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.information", lambda *_args, **_kwargs: None)

    handle_profile_memory_organize(dialog)

    assert opened == [
        {
            "user_profile": {"basic_info": {}, "preferences": {"likes": [], "dislikes": []}, "facts": []},
            "ene_profile": {"core_profile": {"identity": [], "speaking_style": [], "relationship_tone": []}, "facts": []},
        }
    ]
    assert saved == []


def test_profile_memory_preview_shows_contents_not_counts():
    from src.ui.settings_tabs.profile_memory_tab import format_profile_memory_preview

    proposal = {
        "user_profile": {
            "basic_info": {"display_name": "테스트 사용자"},
            "preferences": {"likes": ["짧은 회의"], "dislikes": ["불명확한 일정"]},
            "facts": [
                {
                    "content": "사용자는 프로젝트 상태를 간단히 확인하는 것을 선호한다.",
                    "category": "preference",
                }
            ],
        },
        "ene_profile": {
            "core_profile": {
                "identity": ["에네는 작업 흐름을 차분히 정리한다."],
                "speaking_style": [],
                "relationship_tone": [],
            },
            "facts": [
                {
                    "content": "에네는 변경 전 확인 단계를 선호한다.",
                    "category": "habit",
                }
            ],
        },
    }

    preview = format_profile_memory_preview(proposal)

    assert "테스트 사용자" in preview
    assert "짧은 회의" in preview
    assert "사용자는 프로젝트 상태를 간단히 확인하는 것을 선호한다." in preview
    assert "에네는 작업 흐름을 차분히 정리한다." in preview
    assert "에네는 변경 전 확인 단계를 선호한다." in preview
    assert "사용자 facts: 1개" not in preview


def test_profile_memory_proposal_preserves_existing_fact_source():
    from src.ui.settings_tabs.profile_memory_tab import parse_profile_memory_proposal

    proposal = parse_profile_memory_proposal(
        """
        {
          "user_profile": {
            "basic_info": {},
            "preferences": {"likes": [], "dislikes": []},
            "facts": [
              {
                "content": "사용자는 짧은 회의를 선호한다.",
                "category": "preference",
                "source": "대화 요약 (2026-04-10 20:29)"
              }
            ]
          },
          "ene_profile": {
            "core_profile": {"identity": [], "speaking_style": [], "relationship_tone": []},
            "facts": [
              {
                "content": "에네는 검토 후 적용한다.",
                "category": "habit",
                "source": "대화 요약 (2026-04-10 20:29)"
              }
            ]
          }
        }
        """
    )

    assert proposal["user_profile"]["facts"][0]["source"] == "대화 요약 (2026-04-10 20:29)"
    assert proposal["ene_profile"]["facts"][0]["source"] == "대화 요약 (2026-04-10 20:29)"


def test_profile_memory_proposal_uses_cleanup_source_for_new_or_merged_facts():
    from src.ui.settings_tabs.profile_memory_tab import parse_profile_memory_proposal

    proposal = parse_profile_memory_proposal(
        """
        {
          "user_profile": {
            "basic_info": {},
            "preferences": {"likes": [], "dislikes": []},
            "facts": [
              {"content": "사용자는 정리된 상태 공유를 선호한다.", "category": "preference"}
            ]
          },
          "ene_profile": {
            "core_profile": {"identity": [], "speaking_style": [], "relationship_tone": []},
            "facts": [
              {
                "content": "에네는 병합된 기억을 검토한다.",
                "category": "habit",
                "source": "memory_organizer"
              }
            ]
          }
        }
        """
    )

    assert proposal["user_profile"]["facts"][0]["source"].startswith("기억 정리 (")
    assert proposal["ene_profile"]["facts"][0]["source"].startswith("기억 정리 (")
    assert proposal["ene_profile"]["facts"][0]["source"] != "memory_organizer"
