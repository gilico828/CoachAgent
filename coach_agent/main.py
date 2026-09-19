import hmac
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, PhotoSize, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from coach_agent import profile_store
from coach_agent.config import INVITE_CODE, TELEGRAM_BOT_TOKEN
from coach_agent.graph import AgentReply, ImageAttachment, UserInput, resume_graph, run_graph
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
    "היי! אני בוט אישי ואני עונה רק למי שהוזמן. "
    "אם קיבלת קישור הזמנה — כדאי ללחוץ עליו שוב, הוא זה שפותח לי את הדלת. "
    "ואם הגעת לכאן במקרה — סליחה על ההפרעה."
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
_PHOTO_FAILED_REPLY = "משהו השתבש לי בפתיחת התמונה. אפשר לנסות לשלוח אותה שוב?"
_UNSUPPORTED_MESSAGE_REPLY = (
    "אני יודע לקרוא טקסט, להקשיב להודעות קוליות ולהסתכל על תמונות — את זה עוד לא. "
    "אפשר לכתוב לי, להקליט, או לצלם."
)
_ALREADY_HANDLED_REPLY = "הרישום הזה כבר טופל."

# The two answers to "לרשום את זה ביומן?". A button and not a typed "כן",
# because the value has to come back as a decision and not as a sentence
# somebody has to interpret — and the one interpreting would be the same model
# whose proposal is being checked.
_APPROVE_DATA = "log:ok"
_REJECT_DATA = "log:no"
_APPROVAL_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("✅ לרשום", callback_data=_APPROVE_DATA),
            InlineKeyboardButton("❌ לא", callback_data=_REJECT_DATA),
        ]
    ]
)

# Telegram offers the same photo in a handful of sizes, and the cost of one is
# roughly width × height / 750 tokens — a 1280px plate is ~1200 tokens, against
# ~26 for a typical text message. So the largest is not taken by default: this
# is the narrowest width still worth looking at a plate of food through, and
# anything above it is detail nobody is billed for twice.
_MIN_PHOTO_WIDTH = 512


def _user_key(update: Update) -> str:
    """Channel-qualified identity for the sender.

    The Telegram id on its own would be ambiguous the day a second channel
    exists, and this one key names the profile file, the conversation thread and
    (later) the food-log rows — so it is worth qualifying once, here.
    """
    return f"{_CHANNEL}_{update.effective_user.id}"


async def _send(message, reply: AgentReply) -> None:
    """Put one answer on the wire, with the buttons if it is waiting on them.

    Every path out of the agent goes through here, so a reply that stops for
    approval cannot reach the user stripped of the only way to give it.
    """
    await message.reply_text(
        reply.text,
        reply_markup=_APPROVAL_KEYBOARD if reply.awaiting_approval else None,
    )


def _reply_for(user_key: str, message: str | UserInput) -> AgentReply:
    """The answer to one message, whichever mode this user is in.

    Every route out of here is decided by the status in the user's own file, so
    a restart mid-intake resumes where it stopped and nothing has to be held in
    memory between messages.
    """
    status = profile_store.read_status(user_key)

    if status is None:
        # Nothing is created here. A profile begins in one place only — a
        # /start carrying the invite code — so an ordinary message from a
        # stranger cannot open the door by arriving.
        logger.warning("Message from %s, who has no profile and no invite.", user_key)
        return AgentReply(_UNKNOWN_USER_REPLY)

    if status == profile_store.STATUS_BLOCKED:
        # Answered without reaching the model at all: the intake stopped on a
        # flag the agent is not equipped to handle, and another conversation
        # about it is exactly what should not happen next.
        return AgentReply(_BLOCKED_REPLY)

    if status == profile_store.STATUS_INTAKE:
        # Its own thread, so the coach does not carry the whole interview in
        # every later message — the two documents are that conversation's
        # summary, which is why they were written.
        return run_graph(
            user_key,
            message,
            build_intake_prompt(user_key),
            tools=INTAKE_TOOLS,
            thread_id=f"{user_key}:intake",
        )

    return run_graph(user_key, message, build_system_prompt(user_key))


def _admit(user_key: str, args: list[str]) -> bool:
    """Whether this /start may be answered, creating a profile if it opens one.

    A Telegram deep link — t.me/<bot>?start=<code> — arrives as /start with the
    code as its argument, which is why a link is the whole of what a new person
    has to be sent: nothing about them has to be known beforehand and nothing
    has to be edited afterwards.
    """
    if profile_store.read_status(user_key) is not None:
        return True
    # compare_digest and not ==, because this is a shared secret compared on
    # every /start the bot ever receives.
    if not (INVITE_CODE and args[:1] and hmac.compare_digest(args[0], INVITE_CODE)):
        logger.warning("/start from %s without a valid invite code.", user_key)
        return False
    logger.info("Invite accepted — starting an intake for %s", user_key)
    profile_store.create_from_template(user_key)
    return True


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    if not _admit(user_key, context.args or []):
        await update.message.reply_text(_UNKNOWN_USER_REPLY)
        return
    if profile_store.read_status(user_key) == profile_store.STATUS_ACTIVE:
        await update.message.reply_text(_START_REPLY)
        return
    # For everyone else /start is the first message of the intake, not a
    # greeting to answer before it: it is how most first conversations open.
    await _send(update.message, _reply_for(user_key, "/start"))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update.message, _reply_for(_user_key(update), update.message.text))


async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A press on ✅ or ❌ — the only thing that lets a write actually run."""
    query = update.callback_query
    # Answered first and emptily: until it is, Telegram leaves a spinner on the
    # button, and what comes next is an LLM call measured in seconds.
    await query.answer()
    try:
        # Before the work, not after it, so the window in which the same
        # approval can be pressed twice is as short as the API allows.
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        logger.exception("Could not clear the approval buttons for %s", _user_key(update))

    reply = resume_graph(_user_key(update), approved=query.data == _APPROVE_DATA)
    if reply is None:
        # The graph is not holding anything: a button pressed twice, or one left
        # over from before a restart emptied the checkpointer.
        await query.message.reply_text(_ALREADY_HANDLED_REPLY)
        return
    await _send(query.message, reply)


def _pick_photo_size(sizes: tuple[PhotoSize, ...]) -> PhotoSize:
    """The cheapest rendition that is still worth showing the model.

    `update.message.photo` arrives ascending by size, so this is the first one
    wide enough — falling back to the largest when even that is small, because a
    thumbnail the user actually sent is better than refusing to look.
    """
    for size in sizes:
        if size.width >= _MIN_PHOTO_WIDTH:
            return size
    return sizes[-1]


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    # Same order as the voice path, for the same reason: a stranger's photo
    # costs no transfer and no tokens, and a photo cannot carry an invite code.
    if profile_store.read_status(user_key) is None:
        logger.warning("Photo from %s, who has no profile and no invite.", user_key)
        await update.message.reply_text(_UNKNOWN_USER_REPLY)
        return

    photo = _pick_photo_size(update.message.photo)
    try:
        file = await context.bot.get_file(photo.file_id)
        image = bytes(await file.download_as_bytearray())
    except TelegramError:
        logger.exception("Could not download photo from %s", user_key)
        await update.message.reply_text(_PHOTO_FAILED_REPLY)
        return

    # The dimensions are the price tag — roughly width × height / 750 tokens —
    # and this line is what makes the choice above measurable against LangSmith
    # rather than assumed.
    logger.info("Photo from %s: %sx%s", user_key, photo.width, photo.height)

    # A photo of a meal almost always comes with a caption ("זה מה שאכלתי"),
    # and the two are one message: they are handed over together, and the graph
    # decides what that becomes.
    await _send(
        update.message,
        _reply_for(
            user_key,
            UserInput(
                text=update.message.caption or "",
                # Telegram re-encodes every photo it serves as JPEG, whatever
                # was uploaded, so this is a fact about the platform and not a
                # guess about the file.
                image=ImageAttachment(data=image, media_type="image/jpeg"),
            ),
        ),
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_key = _user_key(update)
    # Refusing before the download and not inside the graph is the point: an
    # unknown sender costs no transfer, no transcription and no tokens. A
    # recording cannot carry an invite code, so there is nothing else to check.
    if profile_store.read_status(user_key) is None:
        logger.warning("Voice message from %s, who has no profile and no invite.", user_key)
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
    await _send(update.message, _reply_for(user_key, text))


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_UNSUPPORTED_MESSAGE_REPLY)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    # Its own update type, not a message, so it is matched before the catch-all
    # below ever looks at it.
    app.add_handler(CallbackQueryHandler(handle_approval))
    # Registered last on purpose: dispatch stops at the first handler that
    # matches, so this one catches whatever the handlers above did not — which
    # until now was answered with silence.
    app.add_handler(MessageHandler(filters.ALL, handle_unsupported))
    logger.info("Coach Agent bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
