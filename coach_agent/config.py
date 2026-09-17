import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
USDA_API_KEY = os.environ["USDA_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
