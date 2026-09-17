"""Picking the right profile for a user key, and refusing when there is none.

The leak case is the one that matters: serving one user another user's profile
raises no exception and reads like a perfectly good answer — the bot simply
coaches the wrong person, with the wrong weight, goals and medical flags.
"""

from pathlib import Path

from coach_agent import profile_store, prompt_assembly


def _users_dir(monkeypatch, tmp_path: Path, profiles: dict[str, str]) -> None:
    for user_key, text in profiles.items():
        (tmp_path / f"{user_key}.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(profile_store, "USERS_DIR", tmp_path)


def test_returns_the_profile_of_the_given_key(monkeypatch, tmp_path):
    _users_dir(monkeypatch, tmp_path, {"telegram_111": "  מטרה: 83 ק\"ג  "})

    # Stripped, because the file's trailing newline would otherwise land in the
    # middle of the assembled system prompt.
    assert prompt_assembly.load_user_profile("telegram_111") == 'מטרה: 83 ק"ג'


def test_two_users_do_not_see_each_other(monkeypatch, tmp_path):
    _users_dir(monkeypatch, tmp_path, {"telegram_111": "פרופיל א", "telegram_222": "פרופיל ב"})

    assert prompt_assembly.load_user_profile("telegram_111") == "פרופיל א"
    assert prompt_assembly.load_user_profile("telegram_222") == "פרופיל ב"


def test_unknown_key_returns_none(monkeypatch, tmp_path):
    _users_dir(monkeypatch, tmp_path, {"telegram_111": "פרופיל א"})

    assert prompt_assembly.load_user_profile("telegram_999") is None


def test_directory_is_not_mistaken_for_a_profile(monkeypatch, tmp_path):
    # `exists()` would say yes here and read_text would then raise IsADirectoryError
    # deep inside a message handler — the exact failure the None return exists to avoid.
    (tmp_path / "telegram_111.md").mkdir()
    monkeypatch.setattr(profile_store, "USERS_DIR", tmp_path)

    assert prompt_assembly.load_user_profile("telegram_111") is None


def test_system_prompt_holds_every_layer(monkeypatch, tmp_path):
    _users_dir(monkeypatch, tmp_path, {"telegram_111": "פרופיל א"})
    profile_store.write_coach_preferences("telegram_111", {"tone": "ישיר-תכל'ס"})
    general = tmp_path / "general.md"
    general.write_text("הוראות כלליות", encoding="utf-8")
    monkeypatch.setattr(prompt_assembly, "_GENERAL_INSTRUCTIONS_PATH", general)

    assembled = prompt_assembly.build_system_prompt("telegram_111")

    assert "הוראות כלליות" in assembled
    assert "פרופיל א" in assembled
    assert "ישיר-תכל'ס" in assembled


def test_the_general_instructions_are_declared_to_outrank_the_personal_ones(
    monkeypatch, tmp_path
):
    """Without this line, "supplements, does not override" is a claim one layer
    makes about another with nothing standing above both to arbitrate."""
    _users_dir(monkeypatch, tmp_path, {"telegram_111": "פרופיל א"})
    general = tmp_path / "general.md"
    general.write_text("הוראות כלליות", encoding="utf-8")
    monkeypatch.setattr(prompt_assembly, "_GENERAL_INSTRUCTIONS_PATH", general)

    assembled = prompt_assembly.build_system_prompt("telegram_111")

    assert assembled.index("הוראות כלליות") < assembled.index("סעיף הבטיחות מנצח")
    assert assembled.index("סעיף הבטיחות מנצח") < assembled.index("פרופיל א")


def test_the_intake_prompt_carries_the_document_as_it_stands(monkeypatch, tmp_path):
    """A resumed intake must not re-ask what the user already answered."""
    monkeypatch.setattr(profile_store, "USERS_DIR", tmp_path)
    profile_store.create_from_template("telegram_111")
    profile_store.replace_section("telegram_111", "מטרות", "- **יעד ראשי:** ירידה של 8 ק\"ג")

    assembled = prompt_assembly.build_intake_prompt("telegram_111")

    assert "ירידה של 8" in assembled
    assert "שאלה אחת בכל הודעה" in assembled
