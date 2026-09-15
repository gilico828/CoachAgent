import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from coach_agent.config import TELEGRAM_BOT_TOKEN
from coach_agent.graph import run_graph
from coach_agent.prompt_assembly import build_system_prompt

logging.basicConfig(level=logging.INFO)
# python-telegram-bot puts the bot token in the request URL, and httpx logs every
# URL at INFO — which wrote the token in clear text into the container logs.
for _http_logger in ("httpx", "httpx2", "httpcore"):
    logging.getLogger(_http_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    reply = run_graph(user_id, update.message.text, build_system_prompt())
    await update.message.reply_text(reply)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Coach Agent bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
