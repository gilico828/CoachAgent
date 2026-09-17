"""The speech-to-text call, without touching the network.

The interesting part is the split between "the provider worked and heard
nothing" and "the provider broke": both leave the user without a transcript,
but only one of them is our fault, and they are answered differently in
main.py. Nothing here asserts transcription quality — that is measured against
real Hebrew audio, not mocked.
"""

import httpx
import pytest

from coach_agent import transcription

_AUDIO = b"not really ogg, nothing here decodes it"


def _fake_post(monkeypatch, *, json_body=None, status: int = 200, raises: Exception | None = None):
    """Replace the one HTTP call, and hand back whatever the test needs."""
    captured = {}

    def _post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        if raises is not None:
            raise raises
        return httpx.Response(status, json=json_body, request=httpx.Request("POST", url))

    monkeypatch.setattr(transcription.httpx, "post", _post)
    return captured


def test_returns_the_transcribed_text(monkeypatch):
    _fake_post(monkeypatch, json_body={"text": "אכלתי שתי פיתות עם פרגית"})
    assert transcription.transcribe(_AUDIO) == "אכלתי שתי פיתות עם פרגית"


def test_hebrew_and_the_vocabulary_hint_are_actually_sent(monkeypatch):
    """Both are accuracy levers, and both are easy to drop in a refactor without
    any test failing — the provider would happily keep transcribing, just worse."""
    captured = _fake_post(monkeypatch, json_body={"text": "שלום"})
    transcription.transcribe(_AUDIO)
    assert captured["data"]["language"] == "he"
    assert "פרגית" in captured["data"]["prompt"]
    assert captured["files"]["file"] == (transcription.AUDIO_FILENAME, _AUDIO)


def test_silence_comes_back_empty_rather_than_raising(monkeypatch):
    """A pocket recording is an ordinary thing for a user to send."""
    _fake_post(monkeypatch, json_body={"text": "   "})
    assert transcription.transcribe(_AUDIO) == ""


def test_provider_error_raises(monkeypatch):
    _fake_post(monkeypatch, json_body={"error": "invalid_api_key"}, status=401)
    with pytest.raises(transcription.TranscriptionError):
        transcription.transcribe(_AUDIO)


def test_network_failure_raises(monkeypatch):
    _fake_post(monkeypatch, raises=httpx.ConnectTimeout("timed out"))
    with pytest.raises(transcription.TranscriptionError):
        transcription.transcribe(_AUDIO)


def test_unexpected_response_shape_raises(monkeypatch):
    """A 200 with the wrong body would otherwise surface as a KeyError three
    layers up, in a handler that has no idea what to do with it."""
    _fake_post(monkeypatch, json_body={"transcript": "לא השדה שציפינו לו"})
    with pytest.raises(transcription.TranscriptionError):
        transcription.transcribe(_AUDIO)
