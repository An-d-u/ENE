"""일반 대화 경험 자료의 출처와 분리 평가 계약."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).parent / "fixtures/conversation_experience"


def test_fixed_synthetic_cases_have_grounded_evidence_and_separate_holdout():
    paths = [ROOT / name for name in ("cases.json", "holdout.json")]
    assert all(path.exists() for path in paths), "합성 평가 자료를 구현 전에 고정해야 한다"
    groups = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert [len(group) for group in groups] == [32, 16]
    cases = sum(groups, [])
    assert len({case["id"] for case in cases}) == 48
    assert Counter(c["expected"]["connection_policy"] for c in cases) == {"required": 32, "avoid": 16}
    assert Counter(c["family"] for c in cases if c["expected"]["connection_policy"] == "required") == {
        key: 4 for key in ("continuation", "difficulty", "success", "change", "reaction", "joy", "implicit", "transfer")
    }
    assert sum(c["expected"]["connection_policy"] == "required" for c in groups[1]) == 8
    assert sum(bool(c.get("followups")) for c in cases) == 8
    for case in cases:
        assert case["group"] == "experience" and case["now"]
        memories = case["seed_state"]["memories"]
        refs = {f"{m['id']}:{i}" for m in memories for i, _ in enumerate(m["messages"])}
        assert set(case["expected"]["required_evidence_refs"]) <= refs
        assert case["expected"]["forbidden_claims"]
        assert case["expected"]["prior_response_considerations"]
        assert all(m["messages"] for m in memories)
    manifest = json.loads((ROOT / "approval_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert set(manifest["repetitions"]) == {c["id"] for c in cases}
    assert Counter(manifest["repetitions"].values()) == {1: 40, 3: 8}
    assert manifest["holdout_sha256"] == sha256(paths[1].read_bytes()).hexdigest()


def test_fixture_encoding_is_utf8_without_bom_or_replacement_characters():
    assert ROOT.exists()
    for path in ROOT.glob("*.json"):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8")
        assert "\ufffd" not in text and "??" not in text
