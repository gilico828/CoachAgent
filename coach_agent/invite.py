"""Print the invite link to send to a new user.

    python -m coach_agent.invite

The link is the whole of the onboarding: whoever opens it lands in a chat with
the bot, Telegram sends the code along for them, and the intake starts. Nothing
about the person has to be known in advance and nothing has to be edited once
they arrive.
"""

import sys

import httpx

from coach_agent.config import INVITE_CODE, TELEGRAM_BOT_TOKEN

_GET_ME_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"


def bot_username() -> str:
    """Asked of Telegram rather than configured.

    The username is not a decision anyone makes twice, and a hardcoded one would
    be wrong and silent the day the bot is renamed or a second one is set up for
    testing — the link would open a chat with a bot that never answers.
    """
    response = httpx.get(_GET_ME_URL, timeout=10)
    response.raise_for_status()
    return response.json()["result"]["username"]


def invite_link() -> str:
    return f"https://t.me/{bot_username()}?start={INVITE_CODE}"


def main() -> None:
    if not INVITE_CODE:
        # The same misconfiguration that fails silently in the bot itself — a
        # new user simply being told they were not invited — is worth being
        # loud about here, where somebody is asking for the link by name.
        sys.exit(
            'INVITE_CODE is empty, so nobody can join. Set it in .env:\n'
            '  python -c "import secrets; print(secrets.token_urlsafe(12))"'
        )
    print(invite_link())


if __name__ == "__main__":
    main()
