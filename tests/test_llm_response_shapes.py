"""The bot must survive every content shape the Messages API can return.

Written after a live failure: a response with no text block raised inside the
graph, the bot stopped answering, and every later message failed the same way.
"""

import types

from coach_agent import graph


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self) -> dict:
        return dict(self.__dict__)


_STATE = {
    "messages": [],
    "system_prompt": "s",
    "tools": [],
    "user_key": "telegram_1",
    "response": "",
}

def _message(content: list, stop_reason: str):
    return types.SimpleNamespace(content=content, stop_reason=stop_reason)


def _text(text: str) -> _Block:
    return _Block(type="text", text=text)


def _tool_use(**inp) -> _Block:
    return _Block(type="tool_use", id="t1", name="lookup_food", input=inp)


def _run(message, monkeypatch) -> tuple[str | None, bool]:
    """Returns (response the user would get, whether the graph routes to the tool)."""
    monkeypatch.setattr(graph, "call_agent", lambda *a, **k: message)
    update = graph._call_llm(_STATE)
    routed = graph._route_after_llm({"messages": [update["messages"][0]]}) == "run_tool"
    return update.get("response"), routed


def test_plain_text_is_answered(monkeypatch):
    response, routed = _run(_message([_text("שלום")], "end_turn"), monkeypatch)
    assert response == "שלום"
    assert not routed


def test_tool_use_defers_the_response_and_routes_to_the_tool(monkeypatch):
    response, routed = _run(_message([_tool_use(query="banana")], "tool_use"), monkeypatch)
    assert response is None
    assert routed


def test_text_alongside_tool_use_still_routes_to_the_tool(monkeypatch):
    message = _message([_text("בודק"), _tool_use(query="banana")], "tool_use")
    response, routed = _run(message, monkeypatch)
    assert response is None
    assert routed


def test_tool_use_truncated_by_max_tokens_routes_instead_of_raising(monkeypatch):
    """The live failure: stop_reason disagreed with the content, and extract_text
    raised before the router could send the turn to the tool."""
    response, routed = _run(_message([_tool_use()], "max_tokens"), monkeypatch)
    assert response is None
    assert routed


def test_a_reply_with_no_content_falls_back_instead_of_crashing(monkeypatch):
    response, routed = _run(_message([], "max_tokens"), monkeypatch)
    assert response == graph._EMPTY_RESPONSE_FALLBACK
    assert not routed
