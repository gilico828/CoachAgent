import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from coach_agent.config import TELEGRAM_BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(update.message.text)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    logger.info("Coach Agent bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
