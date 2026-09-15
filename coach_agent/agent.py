import anthropic

from coach_agent.config import ANTHROPIC_API_KEY

_MODEL = "claude-sonnet-5"

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_agent(
    messages: list[dict], system_prompt: str, tools: list[dict] | None = None
) -> anthropic.types.Message:
    return _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
        tools=tools or [],
    )


def extract_text(message: anthropic.types.Message) -> str:
    """Joined text of the message, or "" if it holds no text block at all.

    A response with no text is a shape the API can legitimately return (a
    tool_use-only turn, or one truncated by max_tokens), so the caller decides
    what to do about it rather than getting an exception mid-conversation.
    """
    return "\n".join(block.text for block in message.content if block.type == "text")
