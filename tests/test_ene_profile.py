from src.ai.user_profile import UserProfile


def test_ene_profile_roundtrip_preserves_core_and_fact_fields(tmp_path):
    from src.ai.ene_profile import EneProfile

    profile = EneProfile(profile_file=tmp_path / "ene_profile.json")
    profile.core_profile["identity"] = ["에네는 차분한 동반자다."]
    profile.add_fact(
        content="[speaking_style] 짧고 또렷한 문장을 선호한다.",
        source="manual",
        origin="manual",
        auto_update=False,
    )

    reloaded = EneProfile(profile_file=tmp_path / "ene_profile.json")

    assert reloaded.core_profile["identity"] == ["에네는 차분한 동반자다."]
    assert len(reloaded.facts) == 1
    assert reloaded.facts[0].category == "speaking_style"
    assert reloaded.facts[0].origin == "manual"
    assert reloaded.facts[0].auto_update is False


def test_add_fact_skips_content_that_duplicates_user_profile(tmp_path):
    from src.ai.ene_profile import EneProfile

    user_profile = UserProfile(profile_file=tmp_path / "user_profile.json")
    user_profile.add_fact("[preference] 다크 판타지를 좋아한다.", source="chat")

    profile = EneProfile(
        profile_file=tmp_path / "ene_profile.json",
        user_profile=user_profile,
    )
    profile.add_fact("[preference] 다크 판타지를 좋아한다.", source="chat")

    assert profile.facts == []


def test_auto_fact_cannot_override_manual_locked_fact(tmp_path):
    from src.ai.ene_profile import EneProfile

    profile = EneProfile(profile_file=tmp_path / "ene_profile.json")
    profile.add_fact(
        "[relationship_tone] 사용자를 다정하게 챙긴다.",
        origin="manual",
        auto_update=False,
    )
    profile.add_fact(
        "[relationship_tone] 사용자를 장난스럽게 몰아붙인다.",
        origin="auto",
        auto_update=True,
    )

    assert len(profile.facts) == 1
    assert profile.facts[0].content == "사용자를 다정하게 챙긴다."
    assert profile.facts[0].origin == "manual"
