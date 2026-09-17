import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from coach_agent import profile_store
from coach_agent.config import ALLOWED_USER_KEYS, TELEGRAM_BOT_TOKEN
from coach_agent.graph import run_graph
from coach_agent.prompt_assembly import build_intake_prompt, build_system_prompt
from coach_agent.tools import INTAKE_TOOLS
from coach_agent.transcription import MAX_AUDIO_SECONDS, TranscriptionError, transcribe

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
_BLOCKED_REPLY = (
    "היי. דיברנו על משהו שאני לא הכתובת הנכונה בשבילו, אז אני לא ממשיך בליווי כאן. "
    "זה לא סירוב ולא שיפוט — פשוט יש אנשי מקצוע שזה התחום שלהם, ואני לא אחד מהם. "
    "אם בא לך לחזור אחרי שדיברת עם מישהו, גילי יכול לפתוח את זה מחדש."
)
_VOICE_TOO_LONG_REPLY = (
    f"ההקלטה ארוכה מדי בשבילי — {MAX_AUDIO_SECONDS // 60} דקות זה המקסימום. "
    "אפשר לחלק לכמה הקלטות קצרות?"
)
_NOTHING_HEARD_REPLY = "לא הצלחתי לשמוע כלום בהקלטה. אפשר לנסות שוב?"
_VOICE_FAILED_REPLY = "משהו השתבש לי בהאזנה להקלטה. אפשר לנסות שוב, או פשוט לכתוב לי."
_UNSUPPORTED_MESSAGE_REPLY = (
    "אני יודע לקרוא טקסט ולהקשיב להודעות קוליות — את זה עוד לא. "
    "אפשר לכתוב לי, או להקליט."
)


def _user_key(update: Update) -> str:
    """Channel-qualified identity for the sender.

    The Telegram id on its own would be ambiguous the day a second channel
    exists, and this one key names the profile file, the conversation thread and
    (later) the food-log rows — so it is worth qualifying once, here.
    """
    return f"{_CHANNEL}_{update.effective_user.id}"


def _reply_for(user_key: str, text: str) -> str:
    """The answer to one message, whichever mode this user is in.

    Every route out of here is decided by the status in the user's own file, so
    a restart mid-intake resumes where it stopped and nothing has to be held in
    memory between messages.
    """
    status = profile_store.read_status(user_key)

    if status is None:
        if user_key not in ALLOWED_USER_KEYS:
            # This log line is the only way to learn a new user's id: while
            # polling is running it consumes every update, so getUpdates has
            # nothing left to show.
            logger.warning("Message from unknown user %s — not on the allowlist.", user_key)
            return _UNKNOWN_USER_REPLY
        logger.info("Starting an intake for %s", user_key)
        profile_store.create_from_template(user_key)
        status = profile_store.STATUS_INTAKE

    if status == profile_store.STATUS_BLOCKED:
        # Answered without reaching the model at all: the intake stopped on a
        # flag the agent is not equipped to handle, and another conversation
        # about it is exactly what should not happen next.
        return _BLOCKED_REPLY

    if status == profile_store.STATUS_INTAKE:
        # Its own thread, so the coach does not carry the whole interview in
        # every later message — the two documents are that conversation's
        # summary, which is why they were written.
        return run_graph(
            user_key,
            text,
            build_intake_prompt(user_key),
            tools=INTAKE_TOOLS,
            thread_id=f"{user_key}:intake",
        )

    return run_graph(user_key, text, build_system_prompt(user_key))


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    if profile_store.read_status(user_key) == profile_store.STATUS_ACTIVE:
        await update.message.reply_text(_START_REPLY)
        return
    # For everyone else /start is the first message of the intake, not a
    # greeting to answer before it: it is how most first conversations open.
    await update.message.reply_text(_reply_for(user_key, "/start"))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_reply_for(_user_key(update), update.message.text))


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    # Refusing before the download and not inside the graph is the point: an
    # unknown sender costs no transfer, no transcription and no tokens.
    if profile_store.read_status(user_key) is None and user_key not in ALLOWED_USER_KEYS:
        logger.warning("Voice message from unknown user %s — not on the allowlist.", user_key)
        await update.message.reply_text(_UNKNOWN_USER_REPLY)
        return

    voice = update.message.voice
    # The duration arrives with the update, for free, before anything is
    # downloaded — so a recording we have already decided to refuse never costs
    # a transfer or a transcription.
    if voice.duration > MAX_AUDIO_SECONDS:
        await update.message.reply_text(_VOICE_TOO_LONG_REPLY)
        return

    # The update carries only metadata — the audio itself has to be fetched, in
    # two round-trips to Telegram, straight into memory and never to disk.
    # Either one can fail on the network, and an unhandled error here would
    # reach the user as the exact silence this Phase set out to remove.
    try:
        file = await context.bot.get_file(voice.file_id)
        audio = bytes(await file.download_as_bytearray())
    except TelegramError:
        logger.exception("Could not download voice message from %s", user_key)
        await update.message.reply_text(_VOICE_FAILED_REPLY)
        return

    # Transcription is billed per minute by a provider LangSmith knows nothing
    # about, so this line is the only place that cost is visible at all.
    logger.info("Voice message from %s: %ss", user_key, voice.duration)

    try:
        text = transcribe(audio)
    except TranscriptionError:
        logger.exception("Transcription failed for %s", user_key)
        await update.message.reply_text(_VOICE_FAILED_REPLY)
        return

    if not text:
        await update.message.reply_text(_NOTHING_HEARD_REPLY)
        return

    # Sent on its own, before the answer: a mistranscription otherwise produces
    # a perfectly coherent reply about something the user never said, with
    # nothing on screen to explain where it came from.
    await update.message.reply_text(f"🎤 שמעתי: {text}")
    await update.message.reply_text(_reply_for(user_key, text))


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_UNSUPPORTED_MESSAGE_REPLY)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    # Registered last on purpose: dispatch stops at the first handler that
    # matches, so this one catches whatever the handlers above did not — which
    # until now was answered with silence.
    app.add_handler(MessageHandler(filters.ALL, handle_unsupported))
    logger.info("Coach Agent bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
