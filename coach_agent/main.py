import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from coach_agent.config import TELEGRAM_BOT_TOKEN
from coach_agent.graph import run_graph
from coach_agent.prompt_assembly import build_system_prompt, load_user_profile

logging.basicConfig(level=logging.INFO)
# python-telegram-bot puts the bot token in the request URL, and httpx logs every
# URL at INFO — which wrote the token in clear text into the container logs.
for _http_logger in ("httpx", "httpx2", "httpcore"):
    logging.getLogger(_http_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_CHANNEL = "telegram"

_START_REPLY = "היי! אני כאן. אפשר לספר לי מה אכלת, לשאול על אימונים, או פשוט להתחיל לדבר."
_UNKNOWN_USER_REPLY = (
    "היי! אני בוט אישי ואני לא מכיר אותך עדיין, אז אני לא יכול לענות. "
    "אם הגעת לכאן בטעות — סליחה על ההפרעה. אם לא — בקש/י מגילי להוסיף אותך."
)


def _user_key(update: Update) -> str:
    """Channel-qualified identity for the sender.

    The Telegram id on its own would be ambiguous the day a second channel
    exists, and this one key names the profile file, the conversation thread and
    (later) the food-log rows — so it is worth qualifying once, here.
    """
    return f"{_CHANNEL}_{update.effective_user.id}"


async def _reject_unknown(update: Update, user_key: str) -> None:
    # This log line is the only way to learn a new user's id: while polling is
    # running it consumes every update, so getUpdates has nothing left to show.
    logger.warning("Message from unknown user %s — no profile file, refusing.", user_key)
    await update.message.reply_text(_UNKNOWN_USER_REPLY)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    if load_user_profile(user_key) is None:
        await _reject_unknown(update, user_key)
        return
    await update.message.reply_text(_START_REPLY)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    profile = load_user_profile(user_key)
    # Refusing here and not inside the graph is the point: an unknown sender
    # costs no tokens and never reaches anyone else's profile.
    if profile is None:
        await _reject_unknown(update, user_key)
        return
    reply = run_graph(user_key, update.message.text, build_system_prompt(profile))
    await update.message.reply_text(reply)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Coach Agent bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
