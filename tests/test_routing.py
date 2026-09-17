"""Which mode a message is answered in, and who is answered at all.

Every branch here is a way to get it wrong quietly. Serving the coach to someone
mid-intake loses the interview; serving the interviewer to an established user
re-interrogates them; and answering a stranger costs real money on a bot anyone
can find by searching Telegram.
"""

import pytest

from coach_agent import main, profile_store

_USER = "telegram_111"


@pytest.fixture(autouse=True)
def users_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_store, "USERS_DIR", tmp_path)
    monkeypatch.setattr(main, "ALLOWED_USER_KEYS", {_USER})
    return tmp_path


@pytest.fixture
def graph_calls(monkeypatch):
    """Records what would have been sent to the model, instead of sending it."""
    calls = []

    def _fake(user_key, text, system_prompt, tools=None, thread_id=None):
        calls.append(
            {
                "user_key": user_key,
                "text": text,
                "system_prompt": system_prompt,
                "tools": [tool["name"] for tool in tools] if tools else None,
                "thread_id": thread_id,
            }
        )
        return "תשובה"

    monkeypatch.setattr(main, "run_graph", _fake)
    return calls


def test_a_stranger_is_refused_without_reaching_the_model(graph_calls):
    stranger = "telegram_999"

    reply = main._reply_for(stranger, "היי")

    assert reply == main._UNKNOWN_USER_REPLY
    assert graph_calls == []
    assert not profile_store.trainee_path(stranger).exists()


def test_an_allowed_newcomer_gets_a_profile_and_the_interviewer(graph_calls):
    main._reply_for(_USER, "היי")

    assert profile_store.read_status(_USER) == profile_store.STATUS_INTAKE
    assert graph_calls[0]["tools"] == [
        "save_trainee_section",
        "update_coach_preferences",
        "finish_intake",
        "stop_intake",
        "get_current_datetime",
    ]
    assert "מראיין" in graph_calls[0]["system_prompt"]


def test_the_intake_runs_on_its_own_thread(graph_calls):
    """Otherwise the coach carries the whole interview in every later message."""
    main._reply_for(_USER, "היי")

    assert graph_calls[0]["thread_id"] == f"{_USER}:intake"


def test_an_established_user_gets_the_coach_on_their_own_thread(graph_calls):
    profile_store.create_from_template(_USER)
    profile_store.set_status(_USER, profile_store.STATUS_ACTIVE)

    main._reply_for(_USER, "מה אכלתי היום")

    assert graph_calls[0]["tools"] is None
    assert graph_calls[0]["thread_id"] is None
    assert "מאמן תזונה וכושר אישי" in graph_calls[0]["system_prompt"]


def test_a_blocked_intake_is_answered_without_calling_the_model(graph_calls):
    """The intake stopped on a flag the agent cannot handle. Another conversation
    about it is exactly what should not happen next."""
    profile_store.create_from_template(_USER)
    profile_store.set_status(_USER, profile_store.STATUS_BLOCKED)

    reply = main._reply_for(_USER, "אפשר תוכנית תזונה?")

    assert reply == main._BLOCKED_REPLY
    assert graph_calls == []


def test_a_resumed_intake_carries_the_answers_already_given(graph_calls):
    """A restart mid-interview must not re-ask what the user already answered."""
    profile_store.create_from_template(_USER)
    profile_store.replace_section(_USER, "מטרות", '- **יעד ראשי:** ירידה של 8 ק"ג')

    main._reply_for(_USER, "אז מה עכשיו")

    assert "ירידה של 8" in graph_calls[0]["system_prompt"]


def test_an_existing_profile_survives_a_second_first_message(graph_calls):
    """`create_from_template` refuses to overwrite, and the router must not ask it to."""
    profile_store.create_from_template(_USER)
    profile_store.replace_section(_USER, "מטרות", '- **יעד ראשי:** ירידה של 8 ק"ג')

    main._reply_for(_USER, "היי")
    main._reply_for(_USER, "היי שוב")

    assert "ירידה של 8" in profile_store.read_section(_USER, "מטרות")
