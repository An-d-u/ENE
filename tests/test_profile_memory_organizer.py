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


class _DummySignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


def test_profile_memory_organize_starts_worker_without_calling_llm(monkeypatch):
    from src.ui.settings_tabs.profile_memory_tab import handle_profile_memory_organize

    workers = []

    class FakeLlm:
        def _request_one_shot_raw(self, prompt, include_sub_prompt=False):
            raise AssertionError("프로필 정리 LLM 호출은 버튼 핸들러에서 동기 실행되면 안 됩니다.")

    class FakeWorker:
        def __init__(self, llm_client, prompt):
            self.llm_client = llm_client
            self.prompt = prompt
            self.proposal_ready = _DummySignal()
            self.failed = _DummySignal()
            self.finished = _DummySignal()
            self.started = False
            workers.append(self)

        def isRunning(self):
            return self.started

        def start(self):
            self.started = True

    dialog = SimpleNamespace()
    dialog._bridge = SimpleNamespace(llm_client=FakeLlm())
    dialog._basic_info_items = []
    dialog._fact_items = []
    dialog.likes_list = _FakeListWidget()
    dialog.dislikes_list = _FakeListWidget()
    dialog._save_user_profile_data = lambda: None
    dialog._translated_text = lambda _key, fallback: fallback
    dialog._translated_text_format = lambda _key, fallback, **kwargs: fallback.format(**kwargs)
    dialog.profile_memory_status_label = SimpleNamespace(setText=lambda _text: None)
    button_states = []
    dialog.profile_memory_organize_button = SimpleNamespace(setEnabled=lambda enabled: button_states.append(enabled))
    dialog._embedded_ene_profile_panel = SimpleNamespace(
        _core_items=[],
        _fact_items=[],
        save_profile=lambda: None,
    )

    monkeypatch.setattr("src.ui.settings_tabs.profile_memory_tab.ProfileMemoryProposalWorker", FakeWorker)

    handle_profile_memory_organize(dialog)

    assert len(workers) == 1
    assert workers[0].started is True
    assert "user_profile" in workers[0].prompt
    assert button_states == [False]
    assert dialog._profile_memory_organize_worker is workers[0]


def test_profile_memory_organize_cancel_does_not_save(monkeypatch):
    from src.ui.settings_tabs.profile_memory_tab import _finish_profile_memory_organize

    saved = []

    dialog = SimpleNamespace()
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

    proposal = {
        "user_profile": {"basic_info": {}, "preferences": {"likes": [], "dislikes": []}, "facts": []},
        "ene_profile": {
            "core_profile": {"identity": [], "speaking_style": [], "relationship_tone": []},
            "facts": [],
        },
    }

    opened = []

    class FakeReviewDialog:
        def __init__(self, parent, received_proposal):
            opened.append(received_proposal)

        def exec(self):
            return QMessageBox.StandardButton.No

    monkeypatch.setattr("src.ui.settings_tabs.profile_memory_tab.ProfileMemoryReviewDialog", FakeReviewDialog)
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.information", lambda *_args, **_kwargs: None)

    _finish_profile_memory_organize(dialog, proposal)

    assert opened == [proposal]
    assert saved == []


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
