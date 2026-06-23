import json

from src.core.bridge_mixins.obsidian import ObsidianBridgeMixin


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, payload):
        self.emitted.append(payload)


class _DummyObsSettings:
    def __init__(self, checked_files):
        self.checked_files = list(checked_files)

    def get_checked_files(self):
        return list(self.checked_files)

    def set_checked_files(self, files):
        self.checked_files = list(files)


class _DummyObsidianManager:
    def __init__(self, tree):
        self.tree = dict(tree)

    def build_tree(self, allow_retry=True):
        return dict(self.tree)


class _DummyBridge(ObsidianBridgeMixin):
    def __init__(self, checked_files, tree):
        self._obsidian_integration_activated = True
        self._cached_checked_files_context = "[Obsidian 체크된 파일 본문]\n[파일:notes/old.md]\nold body"
        self._cached_checked_files_signature = tuple(checked_files)
        self._cached_obs_tree_json = "{}"
        self.obs_checked_files_worker = None
        self.obs_settings = _DummyObsSettings(checked_files)
        self.obsidian_manager = _DummyObsidianManager(tree)
        self.obs_tree_updated = _DummySignal()
        self.refresh_requested = False

    def _prompt_language(self):
        return "ko"

    def _schedule_checked_files_context_refresh(self, force=False):
        self.refresh_requested = bool(force)


def test_cached_checked_file_context_is_not_returned_after_tree_prunes_missing_file():
    bridge = _DummyBridge(
        checked_files=["notes/old.md"],
        tree={"ok": True, "nodes": [], "checked_files": []},
    )

    context = bridge._get_cached_checked_files_context()

    assert context == ""
    assert bridge._cached_checked_files_context == ""
    assert bridge._cached_checked_files_signature == tuple()
    assert bridge.obs_settings.get_checked_files() == []
    assert bridge.refresh_requested is False
    assert json.loads(bridge.obs_tree_updated.emitted[-1])["checked_files"] == []


def test_cached_checked_file_context_is_not_returned_when_tree_validation_fails():
    bridge = _DummyBridge(
        checked_files=["notes/old.md"],
        tree={"ok": False, "error": "CLI unavailable", "nodes": []},
    )

    context = bridge._get_cached_checked_files_context()

    assert context == ""
    assert bridge._cached_checked_files_context == ""
    assert bridge._cached_checked_files_signature == tuple()
