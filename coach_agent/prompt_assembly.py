from pathlib import Path

_GENERAL_INSTRUCTIONS_PATH = Path(__file__).parent / "prompts" / "general_instructions.md"
_DEFAULT_USER_INSTRUCTIONS_PATH = Path(__file__).parent / "users" / "gili.md"


def build_system_prompt() -> str:
    general = _GENERAL_INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()
    user = _DEFAULT_USER_INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()
    return f"{general}\n\n---\n\n{user}"
