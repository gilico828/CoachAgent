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
    for block in message.content:
        if block.type == "text":
            return block.text
    raise ValueError("Claude response contained no text block")
