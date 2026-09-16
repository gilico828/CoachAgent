"""Picking the right profile for a user key, and refusing when there is none.

The leak case is the one that matters: serving one user another user's profile
raises no exception and reads like a perfectly good answer — the bot simply
coaches the wrong person, with the wrong weight, goals and medical flags.
"""

from pathlib import Path

from coach_agent import prompt_assembly


def _users_dir(monkeypatch, tmp_path: Path, profiles: dict[str, str]) -> None:
    for user_key, text in profiles.items():
        (tmp_path / f"{user_key}.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(prompt_assembly, "_USERS_DIR", tmp_path)


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
    monkeypatch.setattr(prompt_assembly, "_USERS_DIR", tmp_path)

    assert prompt_assembly.load_user_profile("telegram_111") is None


def test_system_prompt_holds_both_layers(monkeypatch, tmp_path):
    general = tmp_path / "general.md"
    general.write_text("הוראות כלליות", encoding="utf-8")
    monkeypatch.setattr(prompt_assembly, "_GENERAL_INSTRUCTIONS_PATH", general)

    assembled = prompt_assembly.build_system_prompt("פרופיל א")

    assert "הוראות כלליות" in assembled
    assert "פרופיל א" in assembled
