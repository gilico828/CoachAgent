import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
USDA_API_KEY = os.environ["USDA_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# Telegram user keys allowed to start an intake, comma separated. Without this
# list "no profile yet" means "interview them", and anyone who finds the bot in
# search runs a twenty-minute LLM conversation on our bill. Users who already
# have a profile are unaffected — they never reach this gate.
ALLOWED_USER_KEYS = {
    key.strip() for key in os.environ.get("ALLOWED_USER_KEYS", "").split(",") if key.strip()
}
