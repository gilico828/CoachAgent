"""What a photo costs, and what survives of it in the conversation.

An image block is the single most expensive thing this bot can put in a
message — roughly width × height / 750 tokens, against ~26 for a text message
— and the checkpointer re-sends whatever it was given on every later turn. So
the rules worth pinning down are all about the same thing: the picture is sent
once, to one call, and what the history keeps afterwards is text.
"""

import base64
import types

from coach_agent import main
from coach_agent.graph import ImageAttachment, UserInput, _image_block, _opening_text, _with_image

_IMAGE = ImageAttachment(data=b"\xff\xd8\xff-not-really-a-jpeg", media_type="image/jpeg")


def _photo_turn(caption: str = "זה מה שאכלתי"):
    user_input = UserInput(text=caption, image=_IMAGE)
    return [{"role": "user", "content": _opening_text(user_input)}], _image_block(_IMAGE)


def test_the_bytes_reach_the_api_as_base64():
    block = _image_block(_IMAGE)
    assert block["source"]["media_type"] == "image/jpeg"
    assert base64.standard_b64decode(block["source"]["data"]) == _IMAGE.data


def test_a_photo_with_a_caption_keeps_both_in_the_history():
    assert _opening_text(UserInput("זה מה שאכלתי", _IMAGE)) == "[תמונה שהמשתמש שלח] זה מה שאכלתי"


def test_a_photo_with_no_caption_is_still_a_legal_message():
    # An empty content string is rejected by the API, so a caption-less photo
    # would have failed the whole turn rather than just arriving bare.
    assert _opening_text(UserInput("", _IMAGE)).strip() != ""


def test_a_plain_text_turn_is_left_exactly_as_it_was():
    assert _opening_text(UserInput("אכלתי פיתה")) == "אכלתי פיתה"


def test_the_image_is_attached_to_the_message_that_opened_the_turn():
    messages, block = _photo_turn()
    content = _with_image(messages, block)[-1]["content"]
    # Image first, then the caption: the caption is a question about the picture.
    assert [b["type"] for b in content] == ["image", "text"]
    assert content[0] == block


def test_the_history_itself_never_holds_the_image():
    messages, block = _photo_turn()
    _with_image(messages, block)
    # What the checkpointer keeps, and what every later turn is billed for.
    assert messages == [{"role": "user", "content": "[תמונה שהמשתמש שלח] זה מה שאכלתי"}]


def test_a_tool_round_trip_inside_the_same_turn_does_not_buy_the_image_again():
    messages, block = _photo_turn()
    mid_turn = messages + [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "lookup_food"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
    ]
    assert _with_image(mid_turn, block) == mid_turn


def test_a_text_turn_is_untouched_when_there_is_no_image():
    messages = [{"role": "user", "content": "אכלתי פיתה"}]
    assert _with_image(messages, None) == messages


def _sizes(*widths):
    return tuple(types.SimpleNamespace(width=w, height=w // 2, file_id=str(w)) for w in widths)


def test_the_largest_rendition_is_not_the_one_taken():
    # Telegram's largest is ~1280px — about 1200 tokens for detail a plate of
    # food does not need. The first one wide enough is the whole point.
    assert main._pick_photo_size(_sizes(90, 320, 800, 1280)).width == 800


def test_a_photo_smaller_than_the_threshold_is_still_looked_at():
    assert main._pick_photo_size(_sizes(90, 320)).width == 320
