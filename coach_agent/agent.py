import anthropic

from coach_agent.config import ANTHROPIC_API_KEY

_MODEL = "claude-sonnet-5"

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_agent(messages: list[dict], system_prompt: str) -> str:
    response = _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text
