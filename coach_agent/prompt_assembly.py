from pathlib import Path

_GENERAL_INSTRUCTIONS_PATH = Path(__file__).parent / "prompts" / "general_instructions.md"
_USERS_DIR = Path(__file__).parent / "users"


def load_user_profile(user_key: str) -> str | None:
    """The instruction file for this user, or None if no such file exists.

    None rather than FileNotFoundError: anyone can find the bot in Telegram and
    write to it, so an unknown key is an ordinary event the caller has to answer
    — not a broken deployment. Read on every message on purpose, so editing a
    profile takes effect on the next message without a restart.
    """
    path = _USERS_DIR / f"{user_key}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(user_profile: str) -> str:
    general = _GENERAL_INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()
    return f"{general}\n\n---\n\n{user_profile}"
