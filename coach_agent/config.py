import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
USDA_API_KEY = os.environ["USDA_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# The shared secret carried by an invite link, and the only way a new person can
# start an intake. It replaced a list of Telegram ids: that list could only be
# written after someone had already messaged the bot and been refused, which
# made every new user cost a look through the logs and a redeploy. A code in a
# link needs to know nothing about them in advance.
#
# Empty means nobody can join — deliberately, because the failure that matters
# is the other one. Generate with `python -c "import secrets;
# print(secrets.token_urlsafe(12))"`; it travels in a URL, so keep it URL-safe.
INVITE_CODE = os.environ.get("INVITE_CODE", "").strip()
