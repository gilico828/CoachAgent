"""Speech-to-text for incoming voice messages.

Nothing here knows what Telegram is: it takes audio bytes and gives back text.
That is what keeps the graph's entry point a plain `str` — a voice message is
normalised into a typed one *before* the agent sees it, so `run_graph` never
learns that audio exists.

Groq serves Whisper behind an OpenAI-compatible endpoint, so switching provider
is a URL and a key rather than a rewrite.
"""

import httpx

from coach_agent.config import GROQ_API_KEY

_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# Measured against whisper-large-v3 on a real Hebrew meal report: turbo is
# 2.8x cheaper, ~40% faster, and — once primed with the vocabulary below —
# spelled the food words the larger model got wrong ("פיתות", "פרגית"; large-v3
# insisted on "פיטות" even with the word in front of it). One sample is not a
# benchmark, but it is enough to put the burden of proof on the expensive model.
_MODEL = "whisper-large-v3-turbo"
_TIMEOUT_SECONDS = 60.0

# Telegram sends voice as OGG/Opus, which this endpoint accepts as-is — the
# reason there is no ffmpeg anywhere in this project.
AUDIO_FILENAME = "voice.ogg"

# A voice message longer than this is refused before it is ever downloaded.
# Enforced by the caller, which is the layer that knows the duration for free.
MAX_AUDIO_SECONDS = 120

# Whisper spells unfamiliar words phonetically unless it is primed, and Hebrew
# food and training vocabulary is exactly what a general model mangles.
# Measured: the hint only helps words that are actually *in* it — an earlier
# version without "פרגית" left the model writing "פרגיט", and adding the word
# fixed it. So this list is worth extending whenever a real recording comes back
# with a mangled term. Capped at 224 tokens by the API.
_VOCABULARY_HINT = (
    "דיווח על ארוחות ואימונים בעברית. "
    "מזון: פיתה, פרגית, שניצל, חזה עוף, אורז, קוטג', יוגורט, שייק חלבון, טחינה, אבוקדו, "
    "חלבון, פחמימות, שומן, קלוריות, גרם. "
    "אימון: אימון כוח, סטים, חזרות, סקוואט, דדליפט, לחיצת חזה, מתח, חתירה, אירובי, דופק, קילוגרם."
)


class TranscriptionError(Exception):
    """The provider could not be reached, or answered with something unusable."""


def transcribe(audio: bytes) -> str:
    """The Hebrew text of this audio, or "" if the provider heard nothing.

    An empty result is not an error: a pocket recording or two seconds of
    silence is an ordinary thing for a user to send, and the caller answers it
    differently from a provider that fell over — so it comes back as "" while a
    real failure raises.
    """
    try:
        response = httpx.post(
            _URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (AUDIO_FILENAME, audio)},
            data={
                "model": _MODEL,
                # Naming the language improves both accuracy and latency; left
                # out, Whisper guesses, and it guesses Arabic on short Hebrew.
                "language": "he",
                "prompt": _VOCABULARY_HINT,
                "response_format": "json",
            },
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"transcription request failed: {exc}") from exc

    try:
        return response.json()["text"].strip()
    except (ValueError, KeyError) as exc:
        raise TranscriptionError("transcription response carried no text") from exc
