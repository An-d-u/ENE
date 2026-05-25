import json

from src.ai.user_profile import ProfileFact, UserProfile


def test_profile_fact_to_dict_preserves_fields():
    fact = ProfileFact(
        content="매일 아침 영어 공부를 하는 습관이 있어요",
        category="habit",
        timestamp="2026-05-25T10:00:00",
        source="chat",
    )

    assert fact.to_dict() == {
        "content": "매일 아침 영어 공부를 하는 습관이 있어요",
        "category": "habit",
        "timestamp": "2026-05-25T10:00:00",
        "source": "chat",
    }


def test_load_existing_profile_data(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "facts": [
                    {
                        "content": "이름: 유나이고 전공은 컴퓨터공학입니다",
                        "category": "basic",
                        "timestamp": "2026-05-25T10:00:00",
                        "source": "seed",
                    }
                ],
                "basic_info": {"name": "유나"},
                "preferences": {"likes": ["녹차"], "dislikes": ["소음"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    profile = UserProfile(profile_path)

    assert profile.facts[0].content == "이름: 유나이고 전공은 컴퓨터공학입니다"
    assert profile.basic_info == {"name": "유나"}
    assert profile.preferences == {"likes": ["녹차"], "dislikes": ["소음"]}


def test_load_broken_profile_keeps_empty_state(tmp_path, capsys):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{broken", encoding="utf-8-sig")

    profile = UserProfile(profile_path)

    assert profile.facts == []
    assert profile.basic_info == {}
    assert profile.preferences == {"likes": [], "dislikes": []}
    assert "Load failed" in capsys.readouterr().out


def test_add_preference_fact_normalizes_persists_and_updates_likes(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile = UserProfile(profile_path)

    profile.add_fact("마스터는 녹차와 조용한 재즈 음악을 좋아해요", source="chat")

    assert len(profile.facts) == 1
    assert profile.facts[0].content == "녹차와 조용한 재즈 음악을 좋아해요"
    assert profile.facts[0].category == "preference"
    assert profile.facts[0].source == "chat"
    assert profile.preferences["likes"] == ["녹차와 조용한 재즈 음악을 좋아해요"]
    assert profile_path.read_bytes().startswith(b"\xef\xbb\xbf")

    saved = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    assert saved["facts"][0]["content"] == "녹차와 조용한 재즈 음악을 좋아해요"
    assert saved["preferences"]["likes"] == ["녹차와 조용한 재즈 음악을 좋아해요"]


def test_add_tagged_basic_facts_updates_structured_fields(tmp_path):
    profile = UserProfile(tmp_path / "profile.json")

    profile.add_fact("[basic] 이름: 유나이고 전공은 컴퓨터공학입니다")
    profile.add_fact("[basic] 생일: 1999-02-03 입니다")

    assert profile.basic_info["name"] == "유나이고 전공은 컴퓨터공학입니다"
    assert profile.basic_info["birthday"] == "1999-02-03"
    assert [fact.category for fact in profile.facts] == ["basic", "basic"]


def test_add_fact_skips_temporary_uncertain_and_unknown_items(tmp_path):
    profile = UserProfile(tmp_path / "profile.json")

    profile.add_fact("오늘은 녹차와 재즈 음악을 좋아해요")
    profile.add_fact("아마 파란색을 좋아하는 듯합니다")
    profile.add_fact("짧은 메모", category="misc")

    assert profile.facts == []


def test_similar_fact_updates_existing_fact_instead_of_duplicating(tmp_path):
    profile = UserProfile(tmp_path / "profile.json")

    profile.add_fact("매일 아침 영어 공부를 하는 습관이 있어요", source="first")
    profile.add_fact("매일 아침 영어 공부를 하는 습관이 있고 단어 암기도 해요", source="second")
    profile.add_fact("매일 아침 영어 공부를 하는 습관이 있고 단어 암기도 해요", source="duplicate")

    assert len(profile.facts) == 1
    assert profile.facts[0].content == "매일 아침 영어 공부를 하는 습관이 있고 단어 암기도 해요"
    assert profile.facts[0].source == "second"


def test_delete_fact_filters_by_category_and_builds_recent_context(tmp_path):
    profile = UserProfile(tmp_path / "profile.json")
    profile.facts = [
        ProfileFact("오래된 목표", "goal", "2026-05-24T09:00:00", "old"),
        ProfileFact("최근 습관", "habit", "2026-05-25T09:00:00", "new"),
    ]

    assert [fact.content for fact in profile.get_facts_by_category("habit")] == ["최근 습관"]
    assert profile.get_all_facts() == profile.facts
    assert profile.get_context_string().splitlines() == [
        "[Known user profile]",
        "- [habit] 최근 습관",
        "- [goal] 오래된 목표",
    ]

    profile.delete_fact(99)
    assert len(profile.facts) == 2

    profile.delete_fact(0)
    assert [fact.content for fact in profile.facts] == ["최근 습관"]
