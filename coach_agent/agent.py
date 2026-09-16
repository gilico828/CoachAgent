import anthropic
from langsmith.wrappers import wrap_anthropic

from coach_agent.config import ANTHROPIC_API_KEY

_MODEL = "claude-sonnet-5"

# LangGraph traces its own nodes, but the call inside them is invisible to
# LangSmith unwrapped: every run arrived as a chain with no usage, so there was
# nothing to price. Wrapped, each call is an llm run carrying the token counts
# the response already returns, and LangSmith costs it from those.
_client = wrap_anthropic(anthropic.Anthropic(api_key=ANTHROPIC_API_KEY))


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
